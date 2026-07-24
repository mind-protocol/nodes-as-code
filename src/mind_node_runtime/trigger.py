from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from .config import Settings
from .events import emit_event
from .graph import GraphStore
from .input_utils import parse_json_input
from .worker import Worker

TERMINAL_INTENT_STATUSES = {"completed", "permanent_failure", "cancelled"}



def find_authorizing_rules(
    store: GraphStore,
    *,
    program_id: str,
    event_type: str,
    target_id: str,
) -> list[dict[str, Any]]:
    target = store.load_target(target_id)
    rows = store.read(
        """
        MATCH (rule)
        WHERE rule.node_type='thing'
          AND rule.subtype='trigger_rule'
          AND rule.status='active'
          AND rule.program_id=$program_id
        RETURN rule.id, rule.version, rule.event_types_json,
               rule.target_node_type, rule.target_subtype,
               rule.contract_id
        """,
        {"program_id": program_id},
    )
    matches: list[dict[str, Any]] = []
    for row in rows:
        event_types = json.loads(row[2] or "[]")
        target_node_type = row[3]
        target_subtype = row[4]
        if event_type not in event_types:
            continue
        if target_node_type not in (None, "", "*") and target["node_type"] != target_node_type:
            continue
        if target_subtype not in (None, "", "*") and target["subtype"] != target_subtype:
            continue
        matches.append(
            {
                "id": row[0],
                "version": row[1],
                "contractId": row[5],
            }
        )
    return matches


def event_execution_snapshot(store: GraphStore, event_id: str) -> dict[str, Any]:
    rows = store.read(
        """
        MATCH (event {id:$event_id})
        OPTIONAL MATCH (intent)-[:TRIGGERED_BY]->(event)
        OPTIONAL MATCH (run)-[:EXECUTES_INTENT]->(intent)
        OPTIONAL MATCH (run)-[:PRODUCED]->(result)
        RETURN event.status,
               event.matched_rule_count,
               intent.id,
               intent.status,
               intent.last_error,
               run.id,
               run.status,
               run.error_message,
               result.id,
               result.result_type,
               result.information_status,
               result.value_json,
               result.output_hash
        ORDER BY coalesce(run.started_at, 0) DESC
        """,
        {"event_id": event_id},
    )
    if not rows:
        raise KeyError(f"event not found: {event_id}")

    row = rows[0]
    value = json.loads(row[11]) if row[11] else None
    return {
        "event": {
            "id": event_id,
            "status": row[0],
            "matchedRuleCount": row[1],
        },
        "intent": {
            "id": row[2],
            "status": row[3],
            "error": row[4],
        }
        if row[2]
        else None,
        "run": {
            "id": row[5],
            "status": row[6],
            "error": row[7],
        }
        if row[5]
        else None,
        "result": {
            "id": row[8],
            "resultType": row[9],
            "informationStatus": row[10],
            "value": value,
            "outputHash": row[12],
        }
        if row[8]
        else None,
    }


def trigger_and_wait(
    store: GraphStore,
    settings: Settings,
    *,
    program_id: str,
    target_id: str,
    event_type: str,
    inputs: dict[str, Any],
    source_actor_id: str,
    requested_mode: str | None,
    timeout_seconds: float,
    poll_seconds: float,
    run_worker: bool = True,
) -> dict[str, Any]:
    # Presence check gives a clear error before an event is emitted.
    store.load_program(program_id)
    rules = find_authorizing_rules(
        store,
        program_id=program_id,
        event_type=event_type,
        target_id=target_id,
    )
    if not rules:
        raise PermissionError(
            "no active TriggerRule in this graph authorizes "
            f"program={program_id!r}, event={event_type!r}, target={target_id!r}"
        )

    payload: dict[str, Any] = {
        "programId": program_id,
        "inputs": inputs,
    }
    if requested_mode:
        payload["requestedMode"] = requested_mode

    event_id = emit_event(
        store,
        event_type=event_type,
        target_id=target_id,
        source_actor_id=source_actor_id,
        payload=payload,
    )

    if not run_worker:
        return {
            "eventId": event_id,
            "authorizedBy": rules,
            "status": "emitted",
        }

    worker = Worker(store, settings)
    deadline = time.monotonic() + timeout_seconds
    last_snapshot: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        worker.tick()
        last_snapshot = event_execution_snapshot(store, event_id)
        if last_snapshot["result"] is not None:
            return {
                "authorizedBy": rules,
                **last_snapshot,
            }
        intent = last_snapshot.get("intent")
        if intent and intent.get("status") in TERMINAL_INTENT_STATUSES:
            return {
                "authorizedBy": rules,
                **last_snapshot,
            }
        if last_snapshot["event"]["status"] in {"ignored", "invalid"}:
            return {
                "authorizedBy": rules,
                **last_snapshot,
            }
        time.sleep(poll_seconds)

    return {
        "authorizedBy": rules,
        **(last_snapshot or {"event": {"id": event_id, "status": "unknown"}}),
        "timedOut": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Trigger a graph-authorized Node-as-Code program in a selected FalkorDB graph "
            "and print its EvaluationResult."
        )
    )
    parser.add_argument("--graph", default=os.getenv("FALKOR_GRAPH", "mind_kernel_v0"))
    parser.add_argument("--program", required=True, help="Thing/code ID")
    parser.add_argument("--target", required=True, help="Target node ID")
    parser.add_argument("--event", default="manual_code_execution_requested")
    parser.add_argument("--inputs", help='Inline JSON object, for example \'{"requestedMode":"complete"}\'')
    parser.add_argument("--inputs-file", help="Path to a JSON inputs file")
    parser.add_argument("--mode", choices=["create", "audit", "complete"])
    parser.add_argument("--actor", default="actor-nlr")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--poll", type=float, default=0.5)
    parser.add_argument("--emit-only", action="store_true")
    parser.add_argument("--output", help="Also save the full JSON response to this file")
    parser.add_argument(
        "--executor-mode",
        choices=["deterministic", "ollama-cli"],
        default=os.getenv("MIND_EXECUTOR_MODE", "deterministic"),
    )
    parser.add_argument("--model-command", default=os.getenv("MIND_MODEL_COMMAND"))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    inputs = parse_json_input(args.inputs, args.inputs_file)
    settings = Settings(
        graph_name=args.graph,
        executor_mode=args.executor_mode,
        model_command=args.model_command,
    )
    store = GraphStore(settings)
    try:
        response = trigger_and_wait(
            store,
            settings,
            program_id=args.program,
            target_id=args.target,
            event_type=args.event,
            inputs=inputs,
            source_actor_id=args.actor,
            requested_mode=args.mode,
            timeout_seconds=args.timeout,
            poll_seconds=args.poll,
            run_worker=not args.emit_only,
        )
    except KeyError as exc:
        missing = str(exc).strip("'")
        raise SystemExit(
            f"{missing}\n"
            "The target must exist in the selected graph before it can be triggered.\n"
            "Create it with mind-seed-blueprint or choose a target already present in that graph."
        ) from exc
    rendered = json.dumps(response, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
