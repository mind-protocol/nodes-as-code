from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .graph import GraphStore
from .hashing import canonical_json, stable_id


PERIODIC_MODES = {"periodic", "hybrid"}
ACTIVE_INTENT_STATUSES = {
    "queued",
    "claimed",
    "running",
    "retryable_failure",
}


@dataclass(frozen=True)
class SchedulePolicy:
    id: str
    status: str
    execution_mode: str
    interval_seconds: float
    initial_delay_seconds: float
    last_emitted_at: int
    created_at: int
    emits_event_type: str
    target_program_id: str
    target_id: str
    payload: dict[str, Any]
    coalescing: bool

    @classmethod
    def from_row(cls, row: list[Any]) -> "SchedulePolicy":
        payload = json.loads(row[10] or "{}")
        if not isinstance(payload, dict):
            raise ValueError(f"schedule {row[0]} payload_json must contain an object")
        return cls(
            id=str(row[0]),
            status=str(row[1] or "inactive"),
            execution_mode=str(row[2] or "periodic"),
            interval_seconds=float(row[3] or 0),
            initial_delay_seconds=float(row[4] or 0),
            last_emitted_at=int(row[5] or 0),
            created_at=int(row[6] or 0),
            emits_event_type=str(row[7] or ""),
            target_program_id=str(row[8] or ""),
            target_id=str(row[9] or ""),
            payload=payload,
            coalescing=bool(row[11]) if row[11] is not None else True,
        )


def due_at_ms(policy: SchedulePolicy, *, now_ms: int) -> int | None:
    if policy.status != "active" or policy.execution_mode not in PERIODIC_MODES:
        return None
    if policy.interval_seconds <= 0:
        return None
    base = policy.last_emitted_at
    if base <= 0:
        base = policy.created_at or now_ms
        return base + int(policy.initial_delay_seconds * 1000)
    return base + int(policy.interval_seconds * 1000)


def bind_runtime_values(value: Any, runtime_context: dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$daemon."):
        key = value.removeprefix("$daemon.")
        if key not in runtime_context:
            raise KeyError(f"runtime binding not found: {value}")
        return runtime_context[key]
    if isinstance(value, list):
        return [bind_runtime_values(item, runtime_context) for item in value]
    if isinstance(value, dict):
        return {key: bind_runtime_values(item, runtime_context) for key, item in value.items()}
    return value


class GraphScheduler:
    """Physical clock that materializes graph-owned SchedulePolicy decisions.

    The class knows only generic schedule semantics. Program IDs, event types,
    intervals, targets and payloads are read from FalkorDB on every tick.
    """

    def __init__(self, store: GraphStore) -> None:
        self.store = store

    def list_active(self) -> list[SchedulePolicy]:
        rows = self.store.read(
            """
            MATCH (schedule)
            WHERE schedule.node_type='thing'
              AND schedule.subtype='schedule_policy'
              AND schedule.status='active'
            RETURN schedule.id, schedule.status, schedule.execution_mode,
                   schedule.interval_seconds, schedule.initial_delay_seconds,
                   schedule.last_emitted_at, schedule.created_at,
                   schedule.emits_event_type, schedule.target_program_id,
                   schedule.target_id, schedule.payload_json,
                   schedule.coalescing
            ORDER BY schedule.id
            """
        )
        return [SchedulePolicy.from_row(row) for row in rows]

    def has_active_intent(self, schedule_id: str) -> bool:
        rows = self.store.read(
            """
            MATCH (intent)
            WHERE intent.node_type='moment'
              AND intent.subtype='execution_intent'
              AND intent.schedule_id=$schedule_id
              AND intent.status IN ['queued','claimed','running','retryable_failure']
            RETURN count(intent)
            """,
            {"schedule_id": schedule_id},
        )
        return bool(rows and int(rows[0][0]) > 0)

    def emit_due(
        self,
        policy: SchedulePolicy,
        *,
        due_at: int,
        now_ms: int,
        runtime_context: dict[str, Any],
    ) -> str | None:
        if policy.coalescing and self.has_active_intent(policy.id):
            return None

        payload = bind_runtime_values(policy.payload, runtime_context)
        payload.setdefault("programId", policy.target_program_id)
        payload.setdefault("scheduleId", policy.id)
        event_id = stable_id("event", policy.id, due_at)
        rows = self.store.write(
            """
            MATCH (schedule {id:$schedule_id})
            MATCH (target {id:$target_id})
            WHERE schedule.status='active'
              AND coalesce(schedule.last_emitted_at,0)=$expected_last_emitted_at
            MERGE (event:RuntimeNode {id:$event_id})
            ON CREATE SET
                event.node_type='moment',
                event.subtype='graph_event',
                event.status='pending',
                event.event_type=$event_type,
                event.target_id=$target_id,
                event.source_actor_id='actor:service:mind-kernel-daemon',
                event.schedule_id=$schedule_id,
                event.payload_json=$payload_json,
                event.occurred_at=$now
            SET schedule.last_emitted_at=$now,
                schedule.last_due_at=$due_at,
                schedule.last_event_id=$event_id
            MERGE (event)-[:CONCERNS]->(target)
            MERGE (event)-[:EMITTED_BY_SCHEDULE]->(schedule)
            RETURN event.id
            """,
            {
                "schedule_id": policy.id,
                "target_id": policy.target_id,
                "expected_last_emitted_at": policy.last_emitted_at,
                "event_id": event_id,
                "event_type": policy.emits_event_type,
                "payload_json": canonical_json(payload),
                "now": now_ms,
                "due_at": due_at,
            },
        )
        return str(rows[0][0]) if rows else None

    def tick(self, *, runtime_context: dict[str, Any] | None = None) -> dict[str, Any]:
        runtime_context = dict(runtime_context or {})
        now_ms = int(time.time() * 1000)
        emitted: list[str] = []
        errors: list[dict[str, str]] = []
        checked = 0
        for policy in self.list_active():
            checked += 1
            try:
                due_at = due_at_ms(policy, now_ms=now_ms)
                if due_at is None or now_ms < due_at:
                    continue
                event_id = self.emit_due(
                    policy,
                    due_at=due_at,
                    now_ms=now_ms,
                    runtime_context=runtime_context,
                )
                if event_id:
                    emitted.append(event_id)
            except Exception as exc:
                errors.append({"scheduleId": policy.id, "error": repr(exc)})
        return {"checked": checked, "emittedEvents": emitted, "errors": errors}
