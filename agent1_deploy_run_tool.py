"""Deploy the `run` tool as a graph-authorized loop in mind_kernel_v0, so that
`tools/list` derives it from an active binding (no hidden dispatcher). The
capability envelope makes the subprocess effect explicit and gated:

    executor_type   : terminal_command_ref
    subprocess      : allowed_when_run_enabled
    graphWrite      : forbidden
    secondaryNetwork: forbidden

Runtime requires MIND_ENABLE_RUN=1 before any command executes. The
authenticated-caller requirement has been dropped by explicit operator decision,
so MIND_ENABLE_RUN is the sole gate — this only declares the loop in the graph.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from falkordb import FalkorDB

GRAPH = "mind_kernel_v0"
SERVER_ID = "server:l2:mcp:nodes-as-code:v0"
LOOP_ID = "space:l2:mcp:run-command-v0"
OBJ_ID = "objective:l2:mcp:run-command"
CODE_ID = "code:l2:mcp:run-command:v0"
CONTRACT_ID = "contract:l2:mcp:run-command-tool:v0"
CAP_ID = "capability:l2:mcp:run-command:v0"
BINDING_ID = "binding:l2:mcp:run-command:v0"

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "Shell command to execute on the host."},
        "timeout": {"type": "number", "minimum": 1, "maximum": 600, "default": 60},
    },
    "required": ["command"],
    "additionalProperties": False,
}


def now():
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    g = FalkorDB(host="127.0.0.1", port=6379).select_graph(GRAPH)

    def q(c, p=None):
        return list(g.query(c, p or {}).result_set or [])

    ts = now()

    # loop space + objective
    q("""MERGE (s {id:$id}) SET s:RuntimeNode, s.node_type='space', s.subtype='ontology_module',
         s.name='L2 MCP · Run Command v0', s.role='main_loop',
         s.promise='Toute commande run activée (MIND_ENABLE_RUN=1) s exécute de façon bornée, tracée et auditée, avec statut épistémique explicite.',
         s.status='defined_runtime_verified', s.updated_at=$t""", {"id": LOOP_ID, "t": ts})
    q("""MERGE (o {id:$id}) SET o:RuntimeNode, o.node_type='narrative', o.subtype='objective',
         o.name='Run received commands under an explicit, gated capability envelope',
         o.updated_at=$t""", {"id": OBJ_ID, "t": ts})

    # code definition (executor terminal_command_ref, implemented in the server module)
    q("""MERGE (c {id:$id}) SET c:RuntimeNode, c.node_type='thing', c.type='code',
         c.name='CodeDefinition · Run Command Executor v0',
         c.executor_type='terminal_command_ref', c.authority_mode='graph_structured_definition',
         c.status='implemented_in_server_module', c.implemented_by='code:l2:mcp:nodes-as-code-server:v0',
         c.updated_at=$t""", {"id": CODE_ID, "t": ts})

    # tool contract (tool_name 'run', machine-readable schema)
    q("""MERGE (c {id:$id}) SET c:RuntimeNode, c.node_type='thing', c.type='tool_contract',
         c.name='Tool Contract · run v0', c.tool_name='run', c.version='0.1.0',
         c.read_only=false, c.input_schema_json=$schema, c.status='defined_runtime_verified',
         c.updated_at=$t""", {"id": CONTRACT_ID, "schema": json.dumps(INPUT_SCHEMA, ensure_ascii=False), "t": ts})

    # capability with the explicit gated subprocess envelope
    q("""MERGE (c {id:$id}) SET c:RuntimeNode, c.node_type='thing', c.type='capability',
         c.name='Capability · Run Command v0', c.executor_type='terminal_command_ref',
         c.registered=true, c.status='registered',
         c.effect_graph_read='forbidden', c.effect_graph_write='forbidden',
         c.effect_filesystem_write='allowed_in_project_root',
         c.effect_subprocess='allowed_when_run_enabled',
         c.effect_secondary_network='forbidden',
         c.program_id=$code, c.worker_id='code:mind-kernel:execution-worker:v0',
         c.registered_at=$t""", {"id": CAP_ID, "code": CODE_ID, "t": ts})

    # binding (active)
    q("""MERGE (b {id:$id}) SET b:RuntimeNode, b.node_type='thing', b.type='mcp_tool_binding',
         b.name='MCP Binding · run v0', b.server_id=$server, b.tool_contract_id=$contract,
         b.capability_id=$cap, b.main_loop_id=$loop, b.binding_active=true, b.binding_status='active',
         b.runtime_verification='structurally_verified', b.activated_at=$t""",
      {"id": BINDING_ID, "server": SERVER_ID, "contract": CONTRACT_ID, "cap": CAP_ID, "loop": LOOP_ID, "t": ts})

    # relations
    rels = [
        (LOOP_ID, "HAS_OBJECTIVE", OBJ_ID),
        (LOOP_ID, "DEFINED_BY_CODE", CODE_ID),
        (BINDING_ID, "BINDS_SERVER", SERVER_ID),
        (BINDING_ID, "BINDS_TOOL", CONTRACT_ID),
        (BINDING_ID, "BINDS_CAPABILITY", CAP_ID),
        (BINDING_ID, "BINDS_LOOP", LOOP_ID),
        (SERVER_ID, "EXPOSES", CONTRACT_ID),
        (CAP_ID, "IMPLEMENTED_BY", CODE_ID),
    ]
    for s, t, o in rels:
        q(f"MATCH (a {{id:$s}}) MATCH (b {{id:$o}}) MERGE (a)-[r:`{t}`]->(b) SET r.updated_at=$t",
          {"s": s, "o": o, "t": ts})

    # readback
    def one(cid):
        return int(g.ro_query("MATCH (n {id:$id}) RETURN count(n)", {"id": cid}).result_set[0][0])
    proof = {ident: one(ident) for ident in [LOOP_ID, OBJ_ID, CODE_ID, CONTRACT_ID, CAP_ID, BINDING_ID]}
    active = g.ro_query(
        "MATCH (b {id:$id}) RETURN b.binding_active, b.tool_contract_id", {"id": BINDING_ID}
    ).result_set[0]
    out = {"phase": "deploy-run-tool", "nodeCounts": proof,
           "bindingActive": bool(active[0]), "toolContract": active[1], "generatedAt": ts}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if all(v == 1 for v in proof.values()) and active[0] else 3


if __name__ == "__main__":
    sys.exit(main())
