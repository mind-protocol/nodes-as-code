"""Graph ChangeSet: Deploy and activate MCP graph write tools in mind_kernel_v0.

Graph-first deployment of:
- graph_write  (smart structured MERGE write)
- graph_upsert (structured MERGE write)
- graph_cypher (raw Cypher write query)

Registers tool contracts, capabilities, and active MCP bindings in mind_kernel_v0.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from falkordb import FalkorDB

GRAPH = "mind_kernel_v0"
SERVER_ID = "server:l2:mcp:nodes-as-code:v0"

WRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "password": {"type": "string"},
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
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
    },
    "additionalProperties": True,
}

UPSERT_SCHEMA = {
    "type": "object",
    "properties": {
        "password": {"type": "string"},
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
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
    },
    "additionalProperties": True,
}

CYPHER_SCHEMA = {
    "type": "object",
    "properties": {
        "password": {"type": "string"},
        "cypher": {"type": "string"},
        "params": {"type": "object"},
    },
    "required": ["cypher"],
    "additionalProperties": True,
}

TOOLS = [
    {
        "tool": "graph_write",
        "executor": "graph_upsert_ref",
        "schema": WRITE_SCHEMA,
        "loop": "space:l2:mcp:graph-write-v0",
        "obj": "objective:l2:mcp:graph-write",
        "code": "code:l2:mcp:graph-write:v0",
        "contract": "contract:l2:mcp:graph-write-tool:v0",
        "cap": "capability:l2:mcp:graph-write:v0",
        "binding": "binding:l2:mcp:graph-write:v0",
        "promise": "Écriture structurée intelligente et idempotente dans le graphe.",
    },
    {
        "tool": "graph_upsert",
        "executor": "graph_upsert_ref",
        "schema": UPSERT_SCHEMA,
        "loop": "space:l2:mcp:graph-upsert-v0",
        "obj": "objective:l2:mcp:graph-upsert",
        "code": "code:l2:mcp:graph-upsert:v0",
        "contract": "contract:l2:mcp:graph-upsert-tool:v0",
        "cap": "capability:l2:mcp:graph-upsert:v0",
        "binding": "binding:l2:mcp:graph-upsert:v0",
        "promise": "Écriture structurée idempotente (MERGE par identité) bornée.",
    },
    {
        "tool": "graph_cypher",
        "executor": "graph_cypher_ref",
        "schema": CYPHER_SCHEMA,
        "loop": "space:l2:mcp:graph-cypher-v0",
        "obj": "objective:l2:mcp:graph-cypher",
        "code": "code:l2:mcp:graph-cypher:v0",
        "contract": "contract:l2:mcp:graph-cypher-tool:v0",
        "cap": "capability:l2:mcp:graph-cypher:v0",
        "binding": "binding:l2:mcp:graph-cypher:v0",
        "promise": "Exécution de requêtes Cypher d'écriture directes.",
    },
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    g = FalkorDB(host="127.0.0.1", port=6379).select_graph(GRAPH)

    def q(c, p=None):
        return list(g.query(c, p or {}).result_set or [])

    ts = now()
    proof = {}

    # Ensure main server node exists
    q("""MERGE (s {id:$id}) SET s:RuntimeNode, s.node_type='thing', s.type='mcp_server',
         s.name='Mind Nodes-as-Code MCP Server', s.version='0.3.0', s.status='running', s.updated_at=$t""",
      {"id": SERVER_ID, "t": ts})

    for t in TOOLS:
        q("""MERGE (s {id:$id}) SET s:RuntimeNode, s.node_type='space', s.subtype='ontology_module',
             s.name=$name, s.role='main_loop', s.promise=$promise,
             s.status='defined_runtime_verified', s.updated_at=$t""",
          {"id": t["loop"], "name": f"L2 MCP · {t['tool']} v0", "promise": t["promise"], "t": ts})

        q("""MERGE (o {id:$id}) SET o:RuntimeNode, o.node_type='narrative', o.subtype='objective',
             o.name=$name, o.updated_at=$t""",
          {"id": t["obj"], "name": f"Graph write via {t['tool']} is graph-authorized and verified", "t": ts})

        q("""MERGE (c {id:$id}) SET c:RuntimeNode, c.node_type='thing', c.type='code',
             c.name=$name, c.executor_type=$ex, c.authority_mode='graph_structured_definition',
             c.status='implemented_in_server_module', c.implemented_by='code:l2:mcp:nodes-as-code-server:v0',
             c.updated_at=$t""",
          {"id": t["code"], "name": f"CodeDefinition · {t['tool']} v0", "ex": t["executor"], "t": ts})

        q("""MERGE (c {id:$id}) SET c:RuntimeNode, c.node_type='thing', c.type='tool_contract',
             c.name=$name, c.tool_name=$tool, c.version='0.1.0', c.read_only=false,
             c.input_schema_json=$schema, c.status='defined_runtime_verified', c.updated_at=$t""",
          {"id": t["contract"], "name": f"Tool Contract · {t['tool']} v0", "tool": t["tool"],
           "schema": json.dumps(t["schema"], ensure_ascii=False), "t": ts})

        q("""MERGE (c {id:$id}) SET c:RuntimeNode, c.node_type='thing', c.type='capability',
             c.name=$name, c.executor_type=$ex, c.registered=true, c.status='registered',
             c.effect_graph_read='allowed_with_resolved_scope',
             c.effect_graph_write='allowed_with_write_password',
             c.effect_filesystem_write='forbidden', c.effect_subprocess='forbidden',
             c.effect_secondary_network='forbidden',
             c.auth_mode='write_password_argument', c.program_id=$code,
             c.worker_id='code:mind-kernel:execution-worker:v0', c.registered_at=$t""",
          {"id": t["cap"], "name": f"Capability · {t['tool']} v0", "ex": t["executor"], "code": t["code"], "t": ts})

        q("""MERGE (b {id:$id}) SET b:RuntimeNode, b.node_type='thing', b.type='mcp_tool_binding',
             b.name=$name, b.server_id=$server, b.tool_contract_id=$contract, b.capability_id=$cap,
             b.main_loop_id=$loop, b.binding_active=true, b.binding_status='active',
             b.runtime_verification='structurally_verified', b.activated_at=$t""",
          {"id": t["binding"], "name": f"MCP Binding · {t['tool']} v0", "server": SERVER_ID,
           "contract": t["contract"], "cap": t["cap"], "loop": t["loop"], "t": ts})

        for s, rel, o in [
            (t["loop"], "HAS_OBJECTIVE", t["obj"]),
            (t["loop"], "DEFINED_BY_CODE", t["code"]),
            (t["binding"], "BINDS_SERVER", SERVER_ID),
            (t["binding"], "BINDS_TOOL", t["contract"]),
            (t["binding"], "BINDS_CAPABILITY", t["cap"]),
            (t["binding"], "BINDS_LOOP", t["loop"]),
            (SERVER_ID, "EXPOSES", t["contract"]),
            (t["cap"], "IMPLEMENTED_BY", t["code"]),
        ]:
            q(f"MATCH (a {{id:$s}}) MATCH (b {{id:$o}}) MERGE (a)-[r:`{rel}`]->(b) SET r.updated_at=$t",
              {"s": s, "o": o, "t": ts})

        cnt = int(g.ro_query("MATCH (b {id:$id}) WHERE b.binding_active=true RETURN count(b)",
                             {"id": t["binding"]}).result_set[0][0])
        proof[t["tool"]] = {"binding": t["binding"], "active": cnt == 1}

    out = {"phase": "deploy-write-tools-graph", "tools": proof, "generatedAt": ts}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if all(v["active"] for v in proof.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
