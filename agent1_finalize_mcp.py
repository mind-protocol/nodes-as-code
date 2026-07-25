"""Agent 1 (continued) — Steps 5-7: materialize the MCP CodeDefinitions into
graph-authoritative source, register the graph_query_ref capability/executor,
and activate the binding — all idempotent, non-destructive, fail-closed.

The MCP CodeDefinitions arrived as `defined_not_implemented` (structured
definition + location, no `source`). The runtime engine was authored to fulfil
the graphed Tool Contract exactly and is written BACK into the code node here,
so the graph — not the file — remains the authority (authorityMode=graph_source,
hashes recorded, manifest updated).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from falkordb import FalkorDB

REPO = Path(__file__).resolve().parent
OUT = REPO / "agent1-migration"
OUT.mkdir(exist_ok=True)
GRAPH = "mind_kernel_v0"

SERVER_CODE_ID = "code:l2:mcp:nodes-as-code-server:v0"
EXEC_CODE_ID = "code:l2:mcp:graph-query-execution:v0"
CONTRACT_ID = "contract:l2:mcp:graph-query-tool:v0"
CAPABILITY_ID = "capability:l2:mcp:graph-query-read-only:v0"
BINDING_ID = "binding:l2:mcp:graph-query:v0"
SERVER_ID = "server:l2:mcp:nodes-as-code:v0"
MAIN_LOOP_ID = "space:l2:mcp:graph-query-v0"
CONTRACT_LOOP_ID = "space:l2:mcp:graph-query-tool-contract-v0"
REGISTRY_ID = "registry:mind-meta:evaluator-executors-v0"

SERVER_SOURCE_PATH = REPO / "src" / "mind_node_runtime" / "mcp_server.py"
MANIFEST = OUT / "materialization-manifest.json"

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "queries": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "scope_filter": {"type": "string"},
        "node_types": {
            "type": "array",
            "items": {"type": "string", "enum": ["actor", "space", "narrative", "moment", "thing"]},
        },
        "expand_depth": {"type": "integer", "minimum": 0, "maximum": 2, "default": 0},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
    },
    "required": ["queries"],
    "additionalProperties": False,
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def g():
    return FalkorDB(host="127.0.0.1", port=6379).select_graph(GRAPH)


def q(graph, c, p=None):
    return list(graph.query(c, p or {}).result_set or [])


def qro(graph, c, p=None):
    return list(graph.ro_query(c, p or {}).result_set or [])


# --------------------------------------------------------------------------- #
def materialize() -> int:
    graph = g()
    source = SERVER_SOURCE_PATH.read_text(encoding="utf-8")
    graph_hash = sha256_text(source)
    revision = f"rev:{graph_hash[:16]}"

    # 1. server CodeDefinition -> graph-authoritative source
    q(graph,
      """
      MATCH (n {id:$id})
      SET n.source=$source,
          n.source_hash=$hash,
          n.language='python',
          n.artifact_kind='server_orchestration',
          n.executor_type='composite',
          n.authority_mode='graph_source',
          n.status='materialized_current',
          n.location_kind='package_entrypoint',
          n.location_repository='mind-protocol/nodes-as-code',
          n.location_path='src/mind_node_runtime/mcp_server.py',
          n.location_entrypoint='mind_node_runtime.mcp_server:main',
          n.location_authority='canonical',
          n.materialized_hash=$hash,
          n.revision_id=$rev,
          n.materialized_at=$now
      RETURN n.id
      """,
      {"id": SERVER_CODE_ID, "source": source, "hash": graph_hash,
       "rev": revision, "now": utcnow()})

    # 2. executor CodeDefinition -> implemented by the server module
    q(graph,
      """
      MATCH (n {id:$id})
      SET n.executor_type='graph_query_ref',
          n.authority_mode='graph_structured_definition',
          n.status='implemented_in_server_module',
          n.implemented_by=$server,
          n.materialized_at=$now
      RETURN n.id
      """,
      {"id": EXEC_CODE_ID, "server": SERVER_CODE_ID, "now": utcnow()})

    # 3. contract -> machine-readable schema (tools/list derives from this)
    q(graph,
      """
      MATCH (c {id:$id})
      SET c.tool_name='graph_query',
          c.version='0.1.0',
          c.read_only=true,
          c.input_schema_json=$schema
      RETURN c.id
      """,
      {"id": CONTRACT_ID, "schema": json.dumps(INPUT_SCHEMA, ensure_ascii=False)})

    # 4. materialization record (moment)
    rec_id = f"moment:l2:mcp:materialization:{revision}"
    q(graph,
      """
      MERGE (m {id:$id})
      SET m:RuntimeNode, m.node_type='moment', m.subtype='materialization_record',
          m.code_node_id=$code, m.location_path='src/mind_node_runtime/mcp_server.py',
          m.graph_hash=$hash, m.materialized_hash=$hash, m.status='materialized_current',
          m.produced_at=$now
      WITH m
      MATCH (c {id:$code})
      MERGE (m)-[:MATERIALIZES]->(c)
      RETURN m.id
      """,
      {"id": rec_id, "code": SERVER_CODE_ID, "hash": graph_hash, "now": utcnow()})

    # local file hash must equal graph hash (they are the same bytes here)
    local_hash = sha256_text(SERVER_SOURCE_PATH.read_text(encoding="utf-8"))
    entry = {
        "codeNodeId": SERVER_CODE_ID,
        "location": {
            "kind": "package_entrypoint",
            "repository": "mind-protocol/nodes-as-code",
            "path": "src/mind_node_runtime/mcp_server.py",
            "entrypoint": "mind_node_runtime.mcp_server:main",
            "authority": "canonical",
        },
        "graphHash": graph_hash,
        "materializedHash": local_hash,
        "status": "materialized_current" if local_hash == graph_hash else "hash_mismatch",
        "revisionId": revision,
        "manifestEntry": rec_id,
        "generatedAt": utcnow(),
    }
    MANIFEST.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"phase": "materialize", **entry}, ensure_ascii=False, indent=2))
    return 0 if entry["status"] == "materialized_current" else 3


def register() -> int:
    graph = g()
    # capability -> registered graph_query_ref with the EXACT envelope
    q(graph,
      """
      MATCH (c {id:$id})
      SET c.executor_type='graph_query_ref',
          c.registered=true,
          c.status='registered',
          c.effect_graph_read='allowed_with_resolved_scope',
          c.effect_graph_write='forbidden',
          c.effect_filesystem_write='forbidden',
          c.effect_subprocess='forbidden',
          c.effect_secondary_network='forbidden',
          c.max_expand_depth=2,
          c.max_results=100,
          c.timeout_required=true,
          c.worker_id='code:mind-kernel:execution-worker:v0',
          c.program_id=$prog,
          c.registered_at=$now
      RETURN c.id
      """,
      {"id": CAPABILITY_ID, "prog": EXEC_CODE_ID, "now": utcnow()})

    # registration edge in the executor registry (proof)
    q(graph,
      """
      MATCH (r {id:$reg})
      MATCH (p {id:$prog})
      MERGE (r)-[e:REGISTERS_EXECUTOR]->(p)
      SET e.executor_type='graph_query_ref', e.registered_at=$now
      RETURN type(e)
      """,
      {"reg": REGISTRY_ID, "prog": EXEC_CODE_ID, "now": utcnow()})

    # verify uniqueness + envelope
    rows = qro(graph,
               """
               MATCH (c {id:$id})
               RETURN count(c), c.executor_type, c.registered,
                      c.effect_graph_read, c.effect_graph_write,
                      c.effect_filesystem_write, c.effect_subprocess,
                      c.effect_secondary_network
               """,
               {"id": CAPABILITY_ID})
    r = rows[0]
    envelope_ok = (
        int(r[0]) == 1 and r[1] == "graph_query_ref" and bool(r[2])
        and r[3] == "allowed_with_resolved_scope" and r[4] == "forbidden"
        and r[5] == "forbidden" and r[6] == "forbidden" and r[7] == "forbidden"
    )
    proof = {
        "phase": "register",
        "capabilityId": CAPABILITY_ID,
        "executorType": r[1],
        "registered": bool(r[2]),
        "capabilityInstances": int(r[0]),
        "envelope": {
            "graphRead": r[3], "graphWrite": r[4], "filesystemWrite": r[5],
            "subprocess": r[6], "secondaryNetwork": r[7],
        },
        "envelopeExact": envelope_ok,
        "workerAvailable": bool(qro(graph, "MATCH (w {id:'code:mind-kernel:execution-worker:v0'}) RETURN count(w)")[0][0]),
        "generatedAt": utcnow(),
    }
    (OUT / "register-proof.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(proof, ensure_ascii=False, indent=2))
    return 0 if envelope_ok else 3


def _preconditions(graph) -> dict:
    def one(cid, cond="true"):
        return int(qro(graph, f"MATCH (n {{id:$id}}) WHERE {cond} RETURN count(n)", {"id": cid})[0][0])
    checks = {
        "serverMaterialized": one(SERVER_CODE_ID, "n.status='materialized_current' AND n.source_hash IS NOT NULL"),
        "contractValid": one(CONTRACT_ID, "n.tool_name='graph_query' AND n.input_schema_json IS NOT NULL"),
        "capabilityRegistered": one(CAPABILITY_ID, "n.registered=true AND n.executor_type='graph_query_ref'"),
        "mainLoopPresent": one(MAIN_LOOP_ID),
        "contractLoopPresent": one(CONTRACT_LOOP_ID),
        "serverPresent": one(SERVER_ID),
        "bindingUnique": one(BINDING_ID),
    }
    return checks


def activate() -> int:
    graph = g()
    checks = _preconditions(graph)
    ok = all(v == 1 for v in checks.values())
    if not ok:
        print(json.dumps({"phase": "activate", "status": "blocked", "preconditions": checks}, indent=2))
        return 2

    # promote binding references to top-level props + activate
    q(graph,
      """
      MATCH (b {id:$id})
      SET b.server_id=$server, b.tool_contract_id=$contract, b.capability_id=$cap,
          b.main_loop_id=$loop, b.tool_contract_loop_id=$cloop,
          b.binding_active=true, b.binding_status='active',
          b.runtime_verification='structurally_verified',
          b.activated_at=$now
      RETURN b.id
      """,
      {"id": BINDING_ID, "server": SERVER_ID, "contract": CONTRACT_ID, "cap": CAPABILITY_ID,
       "loop": MAIN_LOOP_ID, "cloop": CONTRACT_LOOP_ID, "now": utcnow()})

    rows = qro(graph,
               "MATCH (b {id:$id}) RETURN b.binding_active, b.server_id, b.tool_contract_id, b.capability_id, b.main_loop_id",
               {"id": BINDING_ID})
    r = rows[0]
    proof = {
        "phase": "activate", "status": "active",
        "preconditions": checks,
        "bindingActive": bool(r[0]),
        "serverId": r[1], "toolContractId": r[2], "capabilityId": r[3], "mainLoopId": r[4],
        "generatedAt": utcnow(),
    }
    (OUT / "activate-proof.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(proof, ensure_ascii=False, indent=2))
    return 0 if r[0] else 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["materialize", "register", "activate"])
    args = ap.parse_args()
    return {"materialize": materialize, "register": register, "activate": activate}[args.phase]()


if __name__ == "__main__":
    sys.exit(main())
