"""
Graph ChangeSet: Deploy and activate the `think` Loop + MCP tool in mind_kernel_v0.

Creates, idempotently, the full causal chain the MCP server needs to *serve*
`think` (it derives `tools/list` purely from active bindings + contracts):

- space:l2:mind-citizen:think-loop-v0        (the self-verifying loop / Space)
- objective:l2:mind-citizen:think-emergence  (Objective narrative)
- contract:l2:mcp:think-tool:v0              (tool contract, tool_name='think')
- capability:l2:mcp:think-cognition:v0       (executor_type='think_ref' envelope)
- code:l2:mcp:think:v0                        (entrypoint mind_node_runtime.think:execute_think)
- binding:l2:mcp:think:v0                     (ACTIVE mcp_tool_binding)

Run:
    python -m mind_node_runtime.think_seed --graph mind_kernel_v0
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict

from .think import DEFAULT_MAX_TICKS, DEFAULT_THINK_CITIZEN, DEFAULT_THINK_TEXT

SERVER_ID = "server:l2:mcp:nodes-as-code:v0"

THINK_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
            "default": DEFAULT_THINK_TEXT,
            "description": "Texte du stimulus interne injecté directement dans le L1 du citoyen "
                           "(optionnel, défaut « continuons »).",
        },
        "citizen": {
            "type": "string",
            "default": DEFAULT_THINK_CITIZEN,
            "description": "Citoyen cible : handle court (« nlr_ai ») ou id complet "
                           "(« actor:citizen:nlr_ai »). Défaut « nlr_ai ».",
        },
        "max_ticks": {
            "type": "integer",
            "default": DEFAULT_MAX_TICKS,
            "description": "Nombre maximal de ticks cognitifs à exécuter avant d'abandonner "
                           "si aucune réponse n'émerge dans le Global Workspace.",
        },
    },
    "additionalProperties": False,
}


LOOP_PROMISE = (
    "think injecte un stimulus interne directement dans le L1 du citoyen puis exécute "
    "des ticks cognitifs jusqu'à ce qu'une réponse émerge dans le Global Workspace, sans "
    "convertir l'absence de réveil en réponse inventée."
)
OBJECTIVE_CONTENT = (
    "GIVEN un stimulus interne écrit dans le L1 du citoyen WHEN think exécute des ticks "
    "THEN une réponse émerge dans le gw dès que la chaleur du leader franchit le seuil de "
    "réveil, OU le stimulus reste pending et information_status=not_measured si le budget "
    "de ticks est épuisé."
)
CONTRACT_DESCRIPTION = (
    "Injecte un stimulus interne directement dans le L1 d'un citoyen (défaut nlr_ai) et "
    "exécute des ticks jusqu'à ce qu'une réponse émerge dans le Global Workspace."
)


def seed_think(store: Any) -> Dict[str, Any]:
    """Idempotently deploy the think loop, contract, capability, code and active binding."""
    store.write(
        """
        MERGE (loop:RuntimeNode {id:'space:l2:mind-citizen:think-loop-v0'})
        SET loop.node_type='space',
            loop.subtype='ontology_module',
            loop.name='Loop · Citizen Think & Workspace Emergence v0',
            loop.status='active',
            loop.contract_kind='self_verifying_loop',
            loop.promise=$loop_promise

        MERGE (obj:RuntimeNode {id:'objective:l2:mind-citizen:think-emergence'})
        SET obj.node_type='narrative',
            obj.subtype='objective',
            obj.name='Faire émerger une réponse interne dans le Global Workspace',
            obj.content=$objective_content

        MERGE (contract:RuntimeNode {id:'contract:l2:mcp:think-tool:v0'})
        SET contract.node_type='thing',
            contract.subtype='tool_contract',
            contract.tool_name='think',
            contract.description=$contract_description,
            contract.input_schema_json=$think_schema,
            contract.read_only=false,
            contract.version='0.1.0'

        MERGE (code:RuntimeNode {id:'code:l2:mcp:think:v0'})
        SET code.node_type='thing',
            code.subtype='code',
            code.name='Code · MCP Think Tool v0',
            code.artifact_kind='python_entrypoint',
            code.language='python',
            code.authority_mode='graph_source',
            code.entrypoint='mind_node_runtime.think:execute_think',
            code.executor_type='think_ref',
            code.status='active'

        MERGE (cap:RuntimeNode {id:'capability:l2:mcp:think-cognition:v0'})
        SET cap.node_type='thing',
            cap.subtype='capability',
            cap.name='Capability · MCP Think Internal Cognition v0',
            cap.executor_type='think_ref',
            cap.registered=true,
            cap.effect_graph_read='allowed_with_resolved_scope',
            cap.effect_graph_write='allowed_for_internal_cognition',
            cap.effect_filesystem_write='forbidden',
            cap.effect_subprocess='forbidden',
            cap.effect_secondary_network='allowed_local_llm',
            cap.max_expand_depth=2,
            cap.max_results=100

        MERGE (binding:RuntimeNode {id:'binding:l2:mcp:think:v0'})
        SET binding.node_type='thing',
            binding.subtype='mcp_tool_binding',
            binding.type='mcp_tool_binding',
            binding.binding_active=true,
            binding.tool_contract_id='contract:l2:mcp:think-tool:v0',
            binding.capability_id='capability:l2:mcp:think-cognition:v0',
            binding.server_id=$server_id,
            binding.main_loop_id='space:l2:mind-citizen:think-loop-v0'

        MERGE (loop)-[:CONTAINS]->(obj)
        MERGE (loop)-[:DEFINED_BY_CODE]->(code)
        MERGE (loop)-[:USES_CONTRACT]->(contract)
        MERGE (code)-[:USES_CONTRACT]->(contract)
        MERGE (code)-[:IMPLEMENTS]->(cap)
        MERGE (binding)-[:BINDS_TOOL]->(contract)
        MERGE (binding)-[:USES_CAPABILITY]->(cap)
        """,
        {
            "think_schema": json.dumps(THINK_SCHEMA, sort_keys=True),
            "server_id": SERVER_ID,
            "loop_promise": LOOP_PROMISE,
            "objective_content": OBJECTIVE_CONTENT,
            "contract_description": CONTRACT_DESCRIPTION,
        },
    )

    return {
        "status": "success",
        "loop": "space:l2:mind-citizen:think-loop-v0",
        "contract": "contract:l2:mcp:think-tool:v0",
        "capability": "capability:l2:mcp:think-cognition:v0",
        "binding": "binding:l2:mcp:think:v0",
        "code": "code:l2:mcp:think:v0",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the think MCP Loop & tool binding.")
    parser.add_argument("--graph", default=os.getenv("FALKOR_GRAPH", "mind_kernel_v0"))
    args = parser.parse_args()

    from .config import Settings
    from .graph import GraphStore

    store = GraphStore(Settings(graph_name=args.graph))
    result = seed_think(store)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
