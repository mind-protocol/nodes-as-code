"""
Graph Seed · Always-Up Loop for `ollama run deepseek-r1:14b`.

Expresses the loop as the graph source of truth BEFORE trusting the
materialized runtime file. Builds the full causal chain:

    Space
    -> Objective   (Narrative)
    -> Pattern     (Narrative)
    -> Behavior    (Narrative, GIVEN/WHEN/THEN)
    -> CodeDefinition (Thing, python entrypoint)
    -> Observer    (Thing)
    -> Health      (Thing, live derived state)
    -> Maintenance (Narrative, repair affordances)

and links the loop to the existing `always_up` decorator loop
(space:l2:mcp:stream-logger-decorator-v0) that governs it, via
WRAPPED_BY_DECORATOR / GOVERNED_BY_DECORATOR_LOOP. This is the "loop
wrapped by another loop" relation the request asks for.

The seed is idempotent (MERGE-only) and bounded to this loop's nodes.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict

from .ollama_deepseek_loop import CODE_NODE_ID, LOOP_SPACE_ID, OBSERVER_NODE_ID

# Existing decorator-loop identifiers (owned by always_up.py) — reused, not created.
STREAM_DECORATOR_SPACE_ID = "space:l2:mcp:stream-logger-decorator-v0"
DECORATOR_CODE_NODE_ID = "code:l2:mcp:always-up-decorator:v0"

OBJECTIVE_ID = "objective:l2:ollama:deepseek-r1-14b:primary"
PATTERN_ID = "pattern:l2:ollama:supervised-restart"
BEHAVIOR_ID = "behavior:l2:ollama:deepseek-r1-14b:stay-resident"
HEALTH_ID = "health:l2:ollama:deepseek-r1-14b"
MAINTENANCE_ID = "maintenance:l2:ollama:deepseek-r1-14b"


def seed_ollama_deepseek_loop(store: Any) -> Dict[str, Any]:
    store.write(
        """
        MERGE (space:RuntimeNode {id:$space_id})
        SET space.node_type='space',
            space.subtype='self_verifying_loop',
            space.name='Loop · Always-Up ollama run deepseek-r1:14b',
            space.status='active',
            space.contract_kind='self_verifying_loop',
            space.loop_type='always_up_process',
            space.reads='ollama HTTP API /api/tags, /api/generate',
            space.writes='local ollama subprocess lifecycle; graph log/error/health streams',
            space.forbidden_effects='no graph writes outside this loop; no model download; no data exfiltration',
            space.scope='local host ollama runtime',
            space.dependencies='ollama binary; model deepseek-r1:14b; localhost:11434',
            space.on_missing_evidence='report measurement_failed / known_absent, never healthy'

        MERGE (obj:RuntimeNode {id:$obj_id})
        SET obj.node_type='narrative',
            obj.subtype='objective',
            obj.name='Keep deepseek-r1:14b resident and responsive',
            obj.content='The local DeepSeek-R1 14B model started via `ollama run deepseek-r1:14b` must remain available; when the process exits it is restarted automatically. Observable success: /api/tags lists deepseek-r1:14b and a generate probe returns text.'

        MERGE (pat:RuntimeNode {id:$pat_id})
        SET pat.node_type='narrative',
            pat.subtype='pattern',
            pat.name='Supervised restart via @always_up decorator loop',
            pat.content='A worker subprocess is supervised by an outer restart loop. The worker RAISES on subprocess exit so the decorator restarts it with backoff, logging each crash and updating health. Normal return would end supervision and is therefore avoided.'

        MERGE (beh:RuntimeNode {id:$beh_id})
        SET beh.node_type='narrative',
            beh.subtype='behavior',
            beh.name='Stay resident behavior',
            beh.content='GIVEN the ollama runtime on localhost WHEN `ollama run deepseek-r1:14b` exits or crashes THEN the loop logs the crash, sets health_status=0, backs off, and restarts the process; FORBIDDEN: silently exiting supervision or reporting health as good without an independent probe.'

        MERGE (code:RuntimeNode {id:$code_id})
        SET code.node_type='thing',
            code.subtype='code',
            code.name='CodeDefinition · DeepSeek-R1 14B Runner v0',
            code.artifact_kind='python_script',
            code.language='python',
            code.authority_mode='graph_source',
            code.executor_type='python_script',
            code.entrypoint='mind_node_runtime.ollama_deepseek_loop:run_deepseek_r1_14b',
            code.command='ollama run deepseek-r1:14b',
            code.implementation_status='materialized',
            code.version='0.1.0',
            code.status='active'

        MERGE (obs:RuntimeNode {id:$obs_id})
        SET obs.node_type='thing',
            obs.subtype='observer',
            obs.name='Observer · DeepSeek-R1 14B Availability v0',
            obs.entrypoint='mind_node_runtime.ollama_deepseek_loop:observe_deepseek_health',
            obs.method='Query /api/tags independently; report observed / known_absent / measurement_failed',
            obs.status='active'

        MERGE (health:RuntimeNode {id:$health_id})
        SET health.node_type='thing',
            health.subtype='health',
            health.name='Health · DeepSeek-R1 14B Loop',
            health.states='healthy | degraded | stale | unknown | not_measured | measurement_failed',
            health.health_status='unknown',
            health.evidence='derived from Observer probe only, never from process existence',
            health.status='active'

        MERGE (maint:RuntimeNode {id:$maint_id})
        SET maint.node_type='narrative',
            maint.subtype='maintenance',
            maint.name='Maintenance · DeepSeek-R1 14B Loop',
            maint.affordances='retry (automatic backoff restart); inspect (--observe); suspend (stop process); recalibrate (change model/command env); relink (re-run seed); rematerialize (regenerate runtime file); ask_human (if ollama binary or model absent)'

        WITH space, obj, pat, beh, code, obs, health, maint
        MERGE (space)-[:CONTAINS]->(obj)
        MERGE (space)-[:HAS_PATTERN]->(pat)
        MERGE (space)-[:HAS_BEHAVIOR]->(beh)
        MERGE (space)-[:DEFINED_BY_CODE]->(code)
        MERGE (space)-[:OBSERVED_BY]->(obs)
        MERGE (space)-[:HAS_HEALTH]->(health)
        MERGE (space)-[:HAS_MAINTENANCE]->(maint)
        MERGE (code)-[:SERVES_OBJECTIVE]->(obj)
        MERGE (obs)-[:VERIFIES]->(code)
        MERGE (obs)-[:UPDATES_HEALTH]->(health)
        """,
        {
            "space_id": LOOP_SPACE_ID,
            "obj_id": OBJECTIVE_ID,
            "pat_id": PATTERN_ID,
            "beh_id": BEHAVIOR_ID,
            "code_id": CODE_NODE_ID,
            "obs_id": OBSERVER_NODE_ID,
            "health_id": HEALTH_ID,
            "maint_id": MAINTENANCE_ID,
        },
    )

    # Link this loop to the governing @always_up decorator loop, IF it exists.
    # Uses MATCH (not MERGE) so we never fabricate the decorator loop here — it
    # is owned by always_up.py and auto-created at runtime by ensure_loop_auto_linked.
    store.write(
        """
        MATCH (space:RuntimeNode {id:$space_id})
        MATCH (ld:RuntimeNode {id:$decorator_space_id})
        MERGE (space)-[:WRAPPED_BY_DECORATOR]->(ld)
        MERGE (space)-[:GOVERNED_BY_DECORATOR_LOOP]->(ld)
        """,
        {
            "space_id": LOOP_SPACE_ID,
            "decorator_space_id": STREAM_DECORATOR_SPACE_ID,
        },
    )

    return {
        "status": "success",
        "loop_space": LOOP_SPACE_ID,
        "code": CODE_NODE_ID,
        "observer": OBSERVER_NODE_ID,
        "health": HEALTH_ID,
        "governed_by": STREAM_DECORATOR_SPACE_ID,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed the always-up loop for `ollama run deepseek-r1:14b` into the kernel graph."
    )
    parser.add_argument("--graph", default=os.getenv("FALKOR_GRAPH", "mind_kernel_v0"))
    args = parser.parse_args()

    from .config import Settings
    from .graph import GraphStore

    settings = Settings(graph_name=args.graph)
    store = GraphStore(settings)
    result = seed_ollama_deepseek_loop(store)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
