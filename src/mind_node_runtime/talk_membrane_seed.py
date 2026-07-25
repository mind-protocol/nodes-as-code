"""
Seed Script for talk MCP Loop & Membrane Boundary Space.

Creates in mind_kernel_v0:
- space:membrane:l1-boundary-v0 (Membrane Boundary Space)
- space:mcp:talk-v0 (talk MCP Loop Space)
- contract:mcp:talk:v0 (Contract for talk tool)
- code:mcp:talk-execution:v0 (Execution code node for talk tool)
- actor:citizen:l1 (Default L1 Citizen AI Actor)
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict


def seed_talk_membrane(store: Any) -> Dict[str, Any]:
    input_schema = {
        "type": "object",
        "required": ["message", "senderActorId", "targetActorId"],
        "properties": {
            "message": {"type": "string", "description": "The message text to send across the membrane"},
            "senderActorId": {"type": "string", "description": "ID of the sending actor"},
            "targetActorId": {"type": "string", "description": "ID of the target Citizen AI"},
        },
    }
    output_schema = {
        "type": "object",
        "required": ["status", "stimulusMomentId", "membraneSpaceId"],
        "properties": {
            "status": {"type": "string"},
            "stimulusMomentId": {"type": "string"},
            "membraneSpaceId": {"type": "string"},
        },
    }

    store.write(
        """
        MERGE (membrane:RuntimeNode {id:'space:membrane:l1-boundary-v0'})
        SET membrane.node_type='space',
            membrane.subtype='membrane_boundary',
            membrane.name='Membrane Boundary · L1 System v0',
            membrane.status='active',
            membrane.content='Isolation membrane boundary receiving external stimuli for L1 Citizen AI.'

        MERGE (talk_space:RuntimeNode {id:'space:mcp:talk-v0'})
        SET talk_space.node_type='space',
            talk_space.subtype='ontology_module',
            talk_space.name='Loop · MCP Talk Capability v0',
            talk_space.status='active',
            talk_space.content='MCP Loop allowing external actors or agents to send messages to a Citizen AI across the membrane.'

        MERGE (contract:RuntimeNode {id:'contract:mcp:talk:v0'})
        SET contract.node_type='thing',
            contract.subtype='tool_contract',
            contract.name='Contract · MCP talk tool v0',
            contract.version='0.1.0',
            contract.input_schema_json=$input_schema_json,
            contract.output_schema_json=$output_schema_json,
            contract.result_type='membrane_stimulus_result'

        MERGE (code:RuntimeNode {id:'code:mcp:talk-execution:v0'})
        SET code.node_type='thing',
            code.subtype='code',
            code.name='Code · MCP talk execution handler v0',
            code.artifact_kind='python_script',
            code.language='python',
            code.authority_mode='graph_source',
            code.version='0.1.0',
            code.status='active',
            code.executor_type='python_script',
            code.entrypoint='mind_node_runtime.talk:execute_talk'

        MERGE (citizen:RuntimeNode {id:'actor:citizen:l1'})
        SET citizen.node_type='actor',
            citizen.subtype='citizen_ai',
            citizen.name='Primary L1 Citizen AI',
            citizen.status='active'

        MERGE (talk_space)-[:DEFINED_BY_CODE]->(code)
        MERGE (talk_space)-[:USES_CONTRACT]->(contract)
        MERGE (code)-[:USES_CONTRACT]->(contract)
        MERGE (membrane)-[:BOUNDS_ACTOR]->(citizen)
        """,
        {
            "input_schema_json": json.dumps(input_schema, sort_keys=True),
            "output_schema_json": json.dumps(output_schema, sort_keys=True),
        },
    )

    return {
        "status": "success",
        "membrane_space": "space:membrane:l1-boundary-v0",
        "talk_space": "space:mcp:talk-v0",
        "citizen_actor": "actor:citizen:l1",
    }


# Citizen actors that must be reachable recipients on the `talk` side of the
# membrane. The membrane graph is physically isolated from the L1 kernel, so
# each recipient needs its own reference node + BOUNDS_ACTOR link here.
DEFAULT_MEMBRANE_RECIPIENTS = [
    {"id": "actor:citizen:l1", "name": "Primary L1 Citizen AI Reference"},
    {"id": "actor:citizen:nlr_ai", "name": "NLR_AI Citizen Reference"},
]


def seed_membrane_recipients(store: Any, recipients: Any = None) -> Dict[str, Any]:
    """Register citizen actors as bounded recipients inside the *membrane* graph.

    Idempotent. Ensures the membrane boundary Space exists and that each citizen
    actor is present and linked via BOUNDS_ACTOR, so `execute_talk` resolves them
    as reachable recipients (and so they appear in membrane clusters when another
    recipient is not found)."""
    recipients = recipients or DEFAULT_MEMBRANE_RECIPIENTS

    store.write(
        """
        MERGE (membrane:RuntimeNode {id:'space:membrane:l1-boundary-v0'})
        SET membrane.node_type='space',
            membrane.subtype='membrane_boundary',
            membrane.name='Membrane Boundary · L1 System v0',
            membrane.status='active'
        """
    )

    linked = []
    for recipient in recipients:
        store.write(
            """
            MATCH (membrane:RuntimeNode {id:'space:membrane:l1-boundary-v0'})
            MERGE (citizen:RuntimeNode {id:$citizen_id})
            SET citizen.node_type='actor',
                citizen.subtype='citizen_ai',
                citizen.name=$citizen_name,
                citizen.status='active'
            MERGE (membrane)-[:BOUNDS_ACTOR]->(citizen)
            """,
            {"citizen_id": recipient["id"], "citizen_name": recipient["name"]},
        )
        linked.append(recipient["id"])

    return {"status": "success", "membrane_recipients_linked": linked}


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed talk MCP Loop & Membrane Boundary Space.")
    parser.add_argument("--graph", default=os.getenv("FALKOR_GRAPH", "mind_kernel_v0"))
    parser.add_argument(
        "--membrane-graph",
        default=os.getenv("MEMBRANE_GRAPH", "mind_membrane_v0"),
        help="Also register default citizen recipients (incl. NLR_AI) in this membrane graph.",
    )
    args = parser.parse_args()

    from .config import Settings
    from .graph import GraphStore

    store = GraphStore(Settings(graph_name=args.graph))
    result = seed_talk_membrane(store)

    if args.membrane_graph:
        membrane_store = GraphStore(Settings(graph_name=args.membrane_graph))
        result["membrane"] = seed_membrane_recipients(membrane_store)

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
