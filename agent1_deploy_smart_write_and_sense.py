"""Graph ChangeSet: Deploy and activate Smart graph_write and Sense Loop in mind_kernel_v0.

Graph-first deployment of:
- space:l2:mind-citizen:sense-situated-state-v0 (Sense Loop)
- objective:l2:mind-citizen:sense-situated-state (Sense Objective)
- contract:l2:mcp:sense-tool:v0 (Tool Contract for sense)
- capability:l2:mcp:sense-read-only:v0 (Read-only capability for sense)
- binding:l2:mcp:sense:v0 (Active MCP Binding for sense)
- Smart graph_write contract & capability updates
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from falkordb import FalkorDB

GRAPH = "mind_kernel_v0"
SERVER_ID = "server:l2:mcp:nodes-as-code:v0"

SENSE_SCHEMA = {
    "type": "object",
    "properties": {
        "scope": {"type": "string", "default": "all"},
        "include_moments": {"type": "boolean", "default": True},
        "limit_moments": {"type": "integer", "default": 5},
    },
    "additionalProperties": False,
}

SMART_WRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "password": {"type": "string"},
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "node_type": {"type": "string", "enum": ["actor", "moment", "narrative", "space", "thing"]},
                    "subtype": {"type": "string"},
                    "name": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["id"],
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "relation": {"type": "string"},
                    "target": {"type": "string"},
                },
                "required": ["source", "relation", "target"],
            },
        },
        "check_orphans": {"type": "boolean", "default": True},
        "check_similarity": {"type": "boolean", "default": True},
        "suggest_links": {"type": "boolean", "default": True},
    },
    "additionalProperties": True,
}

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

def main() -> int:
    g = FalkorDB(host="127.0.0.1", port=6379).select_graph(GRAPH)

    def q(c, p=None):
        return list(g.query(c, p or {}).result_set or [])

    ts = now()

    # 1. Deploy Sense Loop & Objective
    q("""
    MERGE (loop:RuntimeNode {id: 'space:l2:mind-citizen:sense-situated-state-v0'})
    SET loop.node_type = 'space',
        loop.subtype = 'ontology_module',
        loop.name = 'Loop · Citizen Sense & Situated State v0',
        loop.status = 'active',
        loop.contract_kind = 'self_verifying_loop',
        loop.promise = 'sense produit un snapshot situé, daté et sourcé des états L1/L2/L3 sans convertir absence de mesure en valeur nulle.'

    MERGE (obj:RuntimeNode {id: 'objective:l2:mind-citizen:sense-situated-state'})
    SET obj.node_type = 'narrative',
        obj.subtype = 'objective',
        obj.name = 'Produire un sense situé, frais et non inventé',
        obj.content = 'GIVEN les sources perceptives réellement disponibles WHEN sense est appelé THEN produire un snapshot daté avec provenance et fraîcheur.'

    MERGE (loop)-[:CONTAINS]->(obj)
    """)

    # 2. Deploy Sense Tool Contract, Capability, Code & MCP Binding
    q("""
    MERGE (contract:RuntimeNode {id: 'contract:l2:mcp:sense-tool:v0'})
    SET contract.node_type = 'thing',
        contract.subtype = 'tool_contract',
        contract.tool_name = 'sense',
        contract.description = 'Lecture composée du snapshot situé, frais et non inventé des états L1/L2/L3 du Citizen.',
        contract.input_schema_json = $sense_schema,
        contract.read_only = true,
        contract.version = '0.1.0'

    MERGE (code:RuntimeNode {id: 'code:l2:mcp:sense:v0'})
    SET code.node_type = 'thing',
        code.subtype = 'code',
        code.name = 'Code · MCP Sense Tool v0',
        code.artifact_kind = 'python_entrypoint',
        code.language = 'python',
        code.entrypoint = 'mind_node_runtime.mcp_server:execute_sense',
        code.status = 'active'

    MERGE (cap:RuntimeNode {id: 'capability:l2:mcp:sense-read-only:v0'})
    SET cap.node_type = 'thing',
        cap.subtype = 'capability',
        cap.name = 'Capability · MCP Sense Read-Only v0',
        cap.executor_type = 'sense_ref',
        cap.registered = true,
        cap.effect_graph_read = 'allowed_with_resolved_scope',
        cap.effect_graph_write = 'forbidden',
        cap.effect_filesystem_write = 'forbidden',
        cap.effect_subprocess = 'forbidden',
        cap.effect_secondary_network = 'forbidden',
        cap.max_expand_depth = 2,
        cap.max_results = 100

    MERGE (binding:RuntimeNode {id: 'binding:l2:mcp:sense:v0'})
    SET binding.node_type = 'thing',
        binding.subtype = 'mcp_tool_binding',
        binding.type = 'mcp_tool_binding',
        binding.binding_active = true,
        binding.tool_contract_id = 'contract:l2:mcp:sense-tool:v0',
        binding.capability_id = 'capability:l2:mcp:sense-read-only:v0',
        binding.server_id = $server_id,
        binding.main_loop_id = 'space:l2:mind-citizen:sense-situated-state-v0'

    MERGE (code)-[:USES_CONTRACT]->(contract)
    MERGE (code)-[:IMPLEMENTS]->(cap)
    MERGE (binding)-[:BINDS_TOOL]->(contract)
    MERGE (binding)-[:USES_CAPABILITY]->(cap)
    """, {
        "sense_schema": json.dumps(SENSE_SCHEMA, sort_keys=True),
        "server_id": SERVER_ID,
    })

    # 3. Update / Ensure Smart graph_write Contract & Capability
    q("""
    MERGE (contract:RuntimeNode {id: 'contract:l2:mcp:graph-write-tool:v0'})
    SET contract.node_type = 'thing',
        contract.subtype = 'tool_contract',
        contract.tool_name = 'graph_write',
        contract.description = 'Écriture intelligente dans le graphe : validation ontologique, upsert partiel, détection d orphelins, recherche de similarités et suggestions de liens.',
        contract.input_schema_json = $smart_write_schema,
        contract.read_only = false,
        contract.version = '0.2.0'

    MERGE (cap:RuntimeNode {id: 'capability:l2:mcp:graph-write:v0'})
    SET cap.node_type = 'thing',
        cap.subtype = 'capability',
        cap.name = 'Capability · MCP Smart Graph Write v0',
        cap.executor_type = 'graph_upsert_ref',
        cap.registered = true,
        cap.effect_graph_read = 'allowed_with_resolved_scope',
        cap.effect_graph_write = 'allowed_with_write_password',
        cap.effect_filesystem_write = 'forbidden',
        cap.effect_subprocess = 'forbidden',
        cap.effect_secondary_network = 'forbidden',
        cap.max_expand_depth = 2,
        cap.max_results = 100

    MERGE (binding:RuntimeNode {id: 'binding:l2:mcp:graph-write:v0'})
    SET binding.node_type = 'thing',
        binding.subtype = 'mcp_tool_binding',
        binding.type = 'mcp_tool_binding',
        binding.binding_active = true,
        binding.tool_contract_id = 'contract:l2:mcp:graph-write-tool:v0',
        binding.capability_id = 'capability:l2:mcp:graph-write:v0',
        binding.server_id = $server_id,
        binding.main_loop_id = 'space:l2:mcp:graph-write-v0'

    MERGE (binding)-[:BINDS_TOOL]->(contract)
    MERGE (binding)-[:USES_CAPABILITY]->(cap)
    """, {
        "smart_write_schema": json.dumps(SMART_WRITE_SCHEMA, sort_keys=True),
        "server_id": SERVER_ID,
    })

    print(f"[{ts}] Deployed Sense Loop, Sense MCP Tool, and Smart graph_write to {GRAPH}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
