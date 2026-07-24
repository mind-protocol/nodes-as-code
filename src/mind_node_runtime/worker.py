from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings
from .contracts import validate_against_schema, validate_output
from .executors import (
    execute_deterministic,
    execute_ollama_cli,
    execute_registered_python_entrypoint,
)
from .graph import GraphStore
from .hashing import canonical_json, sha256_text, stable_id


@dataclass(frozen=True)
class ClaimedIntent:
    id: str
    program_id: str
    contract_id: str
    target_id: str
    inputs: dict[str, Any]
    attempt_count: int


class Worker:
    def __init__(self, store: GraphStore, settings: Settings) -> None:
        self.store = store
        self.settings = settings

    def resolve_pending_events(self, limit: int = 50) -> int:
        event_rows = self.store.read(
            """
            MATCH (event)
            WHERE event.node_type='moment'
              AND event.subtype='graph_event'
              AND event.status='pending'
            RETURN event.id, event.event_type, event.target_id, event.payload_json, event.occurred_at
            ORDER BY event.occurred_at ASC
            LIMIT $limit
            """,
            {"limit": limit},
        )
        rule_rows = self.store.read(
            """
            MATCH (rule)
            WHERE rule.node_type='thing'
              AND rule.subtype='trigger_rule'
              AND rule.status='active'
            RETURN rule.id, rule.version, rule.event_types_json, rule.mode_mapping_json,
                   rule.target_node_type, rule.target_subtype,
                   rule.program_id, rule.contract_id, rule.priority, rule.max_attempts
            """
        )
        resolved = 0
        for event_row in event_rows:
            event_id, event_type, target_id, payload_json, occurred_at = event_row
            target = self.store.load_target(str(target_id))
            payload = json.loads(payload_json or "{}")
            requested_program_id = payload.get("programId")
            requested_contract_id = payload.get("contractId")
            supplied_inputs = payload.get("inputs")
            if supplied_inputs is not None and not isinstance(supplied_inputs, dict):
                self.store.write(
                    """
                    MATCH (event {id:$event_id})
                    SET event.status='invalid',
                        event.last_error='payload.inputs must be an object',
                        event.resolved_at=$now
                    """,
                    {"event_id": event_id, "now": int(time.time() * 1000)},
                )
                resolved += 1
                continue

            matched = 0
            for rule_row in rule_rows:
                (
                    rule_id,
                    rule_version,
                    event_types_json,
                    mode_mapping_json,
                    target_node_type,
                    target_subtype,
                    program_id,
                    contract_id,
                    priority,
                    max_attempts,
                ) = rule_row
                if event_type not in json.loads(event_types_json):
                    continue
                if requested_program_id and requested_program_id != program_id:
                    continue
                if requested_contract_id and requested_contract_id != contract_id:
                    continue
                if target_node_type not in (None, "", "*") and target.get("node_type") != target_node_type:
                    continue
                if target_subtype not in (None, "", "*") and target.get("subtype") != target_subtype:
                    continue

                mode = payload.get("requestedMode") or json.loads(mode_mapping_json or "{}").get(event_type)
                inputs = dict(supplied_inputs or {})
                if target.get("subtype") == "ontology_module":
                    inputs.setdefault("blueprintId", target_id)
                    if mode:
                        inputs.setdefault("requestedMode", mode)
                elif mode:
                    inputs.setdefault("requestedMode", mode)

                program = self.store.load_program(str(program_id))
                contract = self.store.load_contract(str(contract_id))
                intent_id = stable_id(
                    "intent",
                    event_id,
                    rule_id,
                    rule_version,
                    program["source_hash"],
                    contract["version"],
                    target_id,
                    inputs,
                )
                self.store.write(
                    """
                    MATCH (event {id:$event_id})
                    MATCH (rule {id:$rule_id})
                    MATCH (program {id:$program_id})
                    MATCH (contract {id:$contract_id})
                    MATCH (target {id:$target_id})
                    MERGE (intent:RuntimeNode {id:$intent_id})
                    ON CREATE SET
                        intent.node_type='moment',
                        intent.subtype='execution_intent',
                        intent.status='queued',
                        intent.event_id=$event_id,
                        intent.rule_id=$rule_id,
                        intent.rule_version=$rule_version,
                        intent.program_id=$program_id,
                        intent.contract_id=$contract_id,
                        intent.target_id=$target_id,
                        intent.inputs_json=$inputs_json,
                        intent.priority=$priority,
                        intent.attempt_count=0,
                        intent.max_attempts=$max_attempts,
                        intent.next_attempt_at=$occurred_at,
                        intent.created_at=$occurred_at,
                        intent.claimed_by='',
                        intent.lease_until=0,
                        intent.schedule_id=$schedule_id
                    MERGE (intent)-[:TRIGGERED_BY]->(event)
                    MERGE (intent)-[:AUTHORIZED_BY]->(rule)
                    MERGE (intent)-[:EXECUTES]->(program)
                    MERGE (intent)-[:USES_CONTRACT]->(contract)
                    MERGE (intent)-[:TARGETS]->(target)
                    RETURN intent.id
                    """,
                    {
                        "event_id": event_id,
                        "rule_id": rule_id,
                        "rule_version": rule_version,
                        "program_id": program_id,
                        "contract_id": contract_id,
                        "target_id": target_id,
                        "intent_id": intent_id,
                        "inputs_json": canonical_json(inputs),
                        "priority": int(priority),
                        "max_attempts": int(max_attempts),
                        "occurred_at": int(occurred_at),
                        "schedule_id": str(payload.get("scheduleId") or ""),
                    },
                )
                matched += 1

            self.store.write(
                """
                MATCH (event {id:$event_id})
                SET event.status=$status,
                    event.matched_rule_count=$matched,
                    event.resolved_at=$now
                """,
                {
                    "event_id": event_id,
                    "status": "resolved" if matched else "ignored",
                    "matched": matched,
                    "now": int(time.time() * 1000),
                },
            )
            resolved += 1
        return resolved

    def claim_next(self) -> ClaimedIntent | None:
        now = int(time.time() * 1000)
        lease_until = now + self.settings.lease_seconds * 1000
        rows = self.store.write(
            """
            MATCH (intent)
            WHERE intent.node_type='moment'
              AND intent.subtype='execution_intent'
              AND intent.status IN ['queued','retryable_failure']
              AND intent.next_attempt_at <= $now
              AND intent.lease_until <= $now
              AND intent.attempt_count < intent.max_attempts
            WITH intent
            ORDER BY intent.priority DESC, intent.created_at ASC
            LIMIT 1
            SET intent.status='claimed',
                intent.claimed_by=$worker_id,
                intent.lease_until=$lease_until,
                intent.attempt_count=intent.attempt_count + 1,
                intent.claimed_at=$now
            RETURN intent.id, intent.program_id, intent.contract_id,
                   intent.target_id, intent.inputs_json, intent.attempt_count
            """,
            {
                "now": now,
                "lease_until": lease_until,
                "worker_id": self.settings.worker_id,
            },
        )
        if not rows:
            return None
        row = rows[0]
        return ClaimedIntent(
            id=str(row[0]),
            program_id=str(row[1]),
            contract_id=str(row[2]),
            target_id=str(row[3]),
            inputs=json.loads(row[4]),
            attempt_count=int(row[5]),
        )

    def execute(self, intent: ClaimedIntent) -> str:
        now = int(time.time() * 1000)
        run_id = f"run:{uuid.uuid4()}"
        trace_id = f"trace:{uuid.uuid4()}"
        started = self.store.write(
            """
            MATCH (intent {id:$intent_id})
            WHERE intent.status='claimed'
              AND intent.claimed_by=$worker_id
              AND intent.lease_until > $now
            CREATE (run:RuntimeNode {
                id:$run_id,
                node_type:'moment',
                subtype:'evaluation_run',
                status:'running',
                intent_id:$intent_id,
                program_id:$program_id,
                contract_id:$contract_id,
                target_id:$target_id,
                attempt_number:$attempt_number,
                trace_id:$trace_id,
                started_at:$now
            })
            SET intent.status='running'
            MERGE (run)-[:EXECUTES_INTENT]->(intent)
            RETURN run.id
            """,
            {
                "intent_id": intent.id,
                "worker_id": self.settings.worker_id,
                "now": now,
                "run_id": run_id,
                "program_id": intent.program_id,
                "contract_id": intent.contract_id,
                "target_id": intent.target_id,
                "attempt_number": intent.attempt_count,
                "trace_id": trace_id,
            },
        )
        if not started:
            raise RuntimeError("intent lease lost before run start")

        try:
            program = self.store.load_program(intent.program_id)
            contract = self.store.load_contract(intent.contract_id)
            input_errors = validate_against_schema(intent.inputs, contract["input_schema"])
            if input_errors:
                raise ValueError("input validation failed: " + "; ".join(input_errors))

            target = self.store.load_target(intent.target_id)
            neighbours = self.store.load_neighbours(intent.target_id)
            executor_type = program["executor_type"]

            if executor_type == "prompt_program":
                if self.settings.executor_mode == "ollama-cli":
                    if not self.settings.model_command:
                        raise RuntimeError("MIND_MODEL_COMMAND is required for ollama-cli mode")
                    output = execute_ollama_cli(
                        self.settings.model_command,
                        program["source"],
                        intent.inputs,
                        target,
                        neighbours,
                    )
                elif program.get("fallback_executor") == "deterministic_blueprint_inventory_v0":
                    output = execute_deterministic(target, neighbours)
                else:
                    raise RuntimeError(
                        "this program has no executor available in deterministic mode; "
                        "configure an Ollama command or register a supported executor"
                    )
            elif executor_type == "python_script":
                if program.get("entrypoint") == "mind_node_runtime.materialize:execute_materializer":
                    local_source = Path(__file__).with_name("materialize.py").read_text(encoding="utf-8")
                    local_hash = sha256_text(local_source)
                    if program.get("source_hash") and program["source_hash"] != local_hash:
                        raise RuntimeError(
                            "bootstrap materializer source differs from the active graph source; "
                            "update the installed runtime before execution"
                        )
                output = execute_registered_python_entrypoint(
                    entrypoint=program.get("entrypoint"),
                    store=self.store,
                    inputs=intent.inputs,
                )
            else:
                raise RuntimeError(f"unsupported executor_type {executor_type!r}")

            errors = validate_against_schema(output.value, contract["output_schema"])
            if contract["result_type"] == "blueprint_loop_analysis":
                errors.extend(validate_output(output.value))
            if errors:
                raise ValueError("output validation failed: " + "; ".join(errors))

            completed = int(time.time() * 1000)
            result_id = f"result:{run_id}"
            value_json = canonical_json(output.value)
            self.store.write(
                """
                MATCH (intent {id:$intent_id})
                MATCH (run {id:$run_id})
                MATCH (target {id:$target_id})
                CREATE (result:RuntimeNode {
                    id:$result_id,
                    node_type:'thing',
                    subtype:'evaluation_result',
                    result_type:$result_type,
                    information_status:'measured',
                    value_json:$value_json,
                    output_hash:$output_hash,
                    executor_type:$executor_type,
                    produced_at:$completed
                })
                SET run.status='completed',
                    run.completed_at=$completed,
                    run.duration_ms=$completed - run.started_at,
                    run.executor_type=$executor_type,
                    run.input_hash=$input_hash,
                    run.output_hash=$output_hash
                SET intent.status='completed',
                    intent.completed_at=$completed,
                    intent.lease_until=0
                MERGE (run)-[:PRODUCED]->(result)
                MERGE (result)-[:RESULT_FOR]->(target)
                RETURN result.id
                """,
                {
                    "intent_id": intent.id,
                    "run_id": run_id,
                    "target_id": intent.target_id,
                    "result_id": result_id,
                    "result_type": contract["result_type"],
                    "value_json": value_json,
                    "output_hash": sha256_text(value_json),
                    "input_hash": sha256_text(canonical_json(intent.inputs)),
                    "executor_type": output.executor_type,
                    "completed": completed,
                },
            )
            return run_id
        except Exception as exc:
            failed = int(time.time() * 1000)
            retryable = intent.attempt_count < 3
            next_status = "retryable_failure" if retryable else "permanent_failure"
            delay_ms = 5000 if intent.attempt_count == 1 else 30000
            self.store.write(
                """
                MATCH (intent {id:$intent_id})
                MATCH (run {id:$run_id})
                SET run.status=$run_status,
                    run.completed_at=$failed,
                    run.duration_ms=$failed - run.started_at,
                    run.error_message=$error_message
                SET intent.status=$intent_status,
                    intent.last_error=$error_message,
                    intent.next_attempt_at=$next_attempt_at,
                    intent.lease_until=0
                """,
                {
                    "intent_id": intent.id,
                    "run_id": run_id,
                    "run_status": next_status,
                    "intent_status": next_status,
                    "error_message": repr(exc)[:2000],
                    "failed": failed,
                    "next_attempt_at": failed + delay_ms,
                },
            )
            raise

    def reconcile_expired_leases(self) -> int:
        now = int(time.time() * 1000)
        rows = self.store.write(
            """
            MATCH (intent)
            WHERE intent.node_type='moment'
              AND intent.subtype='execution_intent'
              AND intent.status IN ['claimed','running']
              AND intent.lease_until > 0
              AND intent.lease_until < $now
            SET intent.status='retryable_failure',
                intent.claimed_by='',
                intent.lease_until=0,
                intent.next_attempt_at=$now,
                intent.last_error='lease_expired'
            RETURN count(intent)
            """,
            {"now": now},
        )
        return int(rows[0][0]) if rows else 0

    def tick(self) -> dict[str, Any]:
        reconciled = self.reconcile_expired_leases()
        resolved = self.resolve_pending_events()
        intent = self.claim_next()
        run_id = None
        error = None
        if intent:
            try:
                run_id = self.execute(intent)
            except Exception as exc:  # The graph already contains the failure trace.
                error = repr(exc)
        return {
            "reconciled": reconciled,
            "resolvedEvents": resolved,
            "claimedIntent": intent.id if intent else None,
            "runId": run_id,
            "error": error,
        }
