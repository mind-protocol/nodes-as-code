"""
ChangeSet · Repair the run-command capability subprocess envelope token.

Problem
-------
`mind talk --help` (routed through the graph `run` tool, executor
`terminal_command_ref`) is refused with:

    capability envelope does not authorize subprocess execution

Root cause
----------
The runtime contract enforced by `mind_node_runtime.mcp_server.envelope_allows_subprocess`
requires:

    executor_type == 'terminal_command_ref'
    effect_subprocess == 'allowed_with_authenticated_caller'
    effect_graph_write == 'forbidden'

The capability node `capability:l2:mcp:run-command:v0` instead carries the stale
token `effect_subprocess = 'allowed_when_run_enabled'`. Every OTHER capability in
the graph already uses the exact vocabulary the code enforces
(`allowed_with_resolved_scope`, `allowed_with_write_password`, ...), so this single
value is the divergence. The valid authority is the enforced envelope contract;
the graph is repaired to match it.

This is a bounded, attributable, idempotent ChangeSet: it touches only the one
capability node and records a provenance Moment. Re-running it is a no-op.

Run
---
    python -m scripts.repair_run_command_envelope
    #   or
    python scripts/repair_run_command_envelope.py --graph mind_kernel_v0
"""

from __future__ import annotations

import argparse
import json
import os
import time

from mind_node_runtime.config import Settings
from mind_node_runtime.graph import GraphStore

CAPABILITY_ID = "capability:l2:mcp:run-command:v0"
EXPECTED_TOKEN = "allowed_with_authenticated_caller"
STALE_TOKEN = "allowed_when_run_enabled"


def repair(store: GraphStore) -> dict:
    now = int(time.time() * 1000)

    before = store.read(
        "MATCH (c {id:$id}) RETURN c.executor_type, c.effect_subprocess, c.effect_graph_write, c.registered",
        {"id": CAPABILITY_ID},
    )
    if not before:
        return {"status": "error", "reason": f"capability not found: {CAPABILITY_ID}"}

    executor_type, subprocess_token, graph_write, registered = before[0]
    if executor_type != "terminal_command_ref":
        return {
            "status": "error",
            "reason": f"unexpected executor_type {executor_type!r}; refusing to touch a non-terminal capability",
        }

    if subprocess_token == EXPECTED_TOKEN:
        return {
            "status": "noop",
            "capability": CAPABILITY_ID,
            "effect_subprocess": subprocess_token,
            "message": "Envelope token already aligned; nothing to repair.",
        }

    store.write(
        """
        MATCH (c:RuntimeNode {id:$id})
        SET c.effect_subprocess=$expected,
            c.effect_subprocess_prev=$stale,
            c.updated_at=$now

        MERGE (m:RuntimeNode {id:'moment:repair:run-command-subprocess-token:'+toString($now)})
        SET m.node_type='moment',
            m.subtype='capability_repair',
            m.name='Repair · run-command subprocess envelope token',
            m.epistemic_status='observed',
            m.content=$content,
            m.created_at=$now
        MERGE (m)-[:AFFECTS]->(c)
        """,
        {
            "id": CAPABILITY_ID,
            "expected": EXPECTED_TOKEN,
            "stale": STALE_TOKEN,
            "now": now,
            "content": (
                f"Aligned effect_subprocess {subprocess_token!r} -> {EXPECTED_TOKEN!r} to match the "
                "enforced envelope contract in mcp_server.envelope_allows_subprocess."
            ),
        },
    )

    after = store.read(
        "MATCH (c {id:$id}) RETURN c.executor_type, c.effect_subprocess, c.effect_graph_write",
        {"id": CAPABILITY_ID},
    )[0]

    return {
        "status": "repaired",
        "capability": CAPABILITY_ID,
        "before": {"effect_subprocess": subprocess_token},
        "after": {
            "executor_type": after[0],
            "effect_subprocess": after[1],
            "effect_graph_write": after[2],
        },
        "changeset_moment": f"moment:repair:run-command-subprocess-token:{now}",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", default=os.getenv("FALKOR_GRAPH", "mind_kernel_v0"))
    args = parser.parse_args()

    store = GraphStore(Settings(graph_name=args.graph))
    result = repair(store)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
