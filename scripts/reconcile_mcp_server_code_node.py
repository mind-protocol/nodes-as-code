"""Reconcile the change INTO the graph authority (not just the file).

The MCP server module's authority is the CodeDefinition node
`code:l2:mcp:nodes-as-code-server:v0` (authority_mode=graph_source). Its
`source` field is the canonical source; `src/mind_node_runtime/mcp_server.py`
is the materialization and must hash-match.

The graph-driven input-adapter change was authored in the module. This script
writes that source back INTO the node's `source`, recomputes the hashes,
records a materialization Moment, and reads everything back so the node — not
the file — is the recorded authority again. Scoped to the server code node
only; no unrelated graph state is mutated.

Idempotent: re-running with an unchanged file is a no-op (same hash).
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from falkordb import FalkorDB

GRAPH = "mind_kernel_v0"
SERVER_CODE_ID = "code:l2:mcp:nodes-as-code-server:v0"
REPO = Path(__file__).resolve().parents[1]
SERVER_SOURCE_PATH = REPO / "src" / "mind_node_runtime" / "mcp_server.py"

# Markers proving the live-tool-discovery change is present in the source we
# persist: listChanged=true + a graph tool-set watcher that emits
# notifications/tools/list_changed over stdio and an HTTP SSE stream.
REQUIRED_MARKERS = (
    '"tools": {"listChanged": True}',
    "def watch_tool_changes(",
    "def start_tool_watcher(",
    "notifications/tools/list_changed",
    "def _serve_sse(",
    "text/event-stream",
    # the prior input-adapter change must remain present (no regression)
    "def normalize_graph_write_arguments(",
    'adapter_id = tool.get("inputAdapter")',
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def main() -> int:
    source = SERVER_SOURCE_PATH.read_text(encoding="utf-8")

    missing = [m for m in REQUIRED_MARKERS if m not in source]
    if missing:
        print(json.dumps({"status": "aborted",
                          "reason": "source is missing the adapter change; refusing to persist",
                          "missing_markers": missing}, indent=2))
        return 2

    graph_hash = sha256_text(source)
    revision = f"rev:{graph_hash[:16]}"
    now = utcnow()

    g = FalkorDB(host="127.0.0.1", port=6379).select_graph(GRAPH)

    def q(c, p=None):
        return list(g.query(c, p or {}).result_set or [])

    def qro(c, p=None):
        return list(g.ro_query(c, p or {}).result_set or [])

    prev = qro("MATCH (n {id:$id}) RETURN n.source_hash, n.revision_id", {"id": SERVER_CODE_ID})
    prev_hash = prev[0][0] if prev else None
    prev_rev = prev[0][1] if prev else None

    # Write the change INTO the node.source (the graph authority).
    updated = q(
        """
        MATCH (n {id:$id})
        SET n.source = $source,
            n.source_hash = $hash,
            n.language = 'python',
            n.artifact_kind = 'server_orchestration',
            n.authority_mode = 'graph_source',
            n.status = 'materialized_current',
            n.location_kind = 'package_entrypoint',
            n.location_repository = 'mind-protocol/nodes-as-code',
            n.location_path = 'src/mind_node_runtime/mcp_server.py',
            n.location_entrypoint = 'mind_node_runtime.mcp_server:main',
            n.location_authority = 'canonical',
            n.materialized_hash = $hash,
            n.revision_id = $rev,
            n.materialized_at = $now
        RETURN n.id
        """,
        {"id": SERVER_CODE_ID, "source": source, "hash": graph_hash, "rev": revision, "now": now},
    )
    if not updated:
        print(json.dumps({"status": "aborted", "reason": f"code node not found: {SERVER_CODE_ID}"}, indent=2))
        return 2

    # Objective this revision protects + why the mechanism satisfies it.
    obj_id = "objective:l2:mcp:tool-discovery-stays-current"
    just_id = "narrative:l2:mcp:listchanged-notifications-justification"
    obj_success = (
        "After a tool binding becomes active, connected clients receive "
        "notifications/tools/list_changed and re-fetch tools/list without a manual reconnect."
    )
    just_content = (
        "tools/list is derived fresh from the graph on every call, so a client's cached manifest "
        "only goes stale when the active binding set changes. A watcher polls that set and broadcasts "
        "notifications/tools/list_changed to every live transport (stdio writer, HTTP chunked SSE at "
        "GET /mcp). Advertised via capabilities.tools.listChanged=true. Rejected alternative: relying "
        "on client reconnects, which was the failure mode being fixed."
    )
    q(
        """
        MERGE (o {id:$obj}) SET o:RuntimeNode, o.node_type='narrative', o.subtype='objective',
            o.name='A client discovers newly deployed graph tools without reconnecting',
            o.success_condition=$obj_success,
            o.updated_at=$now
        MERGE (j {id:$just}) SET j:RuntimeNode, j.node_type='narrative', j.subtype='justification',
            j.name='listChanged + graph watcher + SSE stream',
            j.content=$just_content,
            j.updated_at=$now
        WITH o, j
        MATCH (c {id:$code})
        MERGE (c)-[:HAS_OBJECTIVE]->(o)
        MERGE (c)-[:JUSTIFIED_BY]->(j)
        MERGE (j)-[:JUSTIFIES]->(o)
        RETURN o.id, j.id
        """,
        {"obj": obj_id, "just": just_id, "code": SERVER_CODE_ID, "now": now,
         "obj_success": obj_success, "just_content": just_content},
    )

    # Provenance Moment: this revision materializes the server code node.
    rec_id = f"moment:l2:mcp:materialization:{revision}"
    change_summary = (
        "Advertise tools.listChanged=true; watcher emits notifications/tools/list_changed over "
        "stdio and HTTP chunked SSE (GET /mcp) when active graph tool bindings change."
    )
    q(
        """
        MERGE (m {id:$id})
        SET m:RuntimeNode, m.node_type = 'moment', m.subtype = 'materialization_record',
            m.name = 'Materialization · MCP server live tool-discovery (listChanged + SSE)',
            m.change_summary = $change_summary,
            m.code_node_id = $code, m.location_path = 'src/mind_node_runtime/mcp_server.py',
            m.graph_hash = $hash, m.materialized_hash = $hash, m.status = 'materialized_current',
            m.previous_revision = $prev_rev,
            m.produced_at = $now
        WITH m
        MATCH (c {id:$code}) MERGE (m)-[:MATERIALIZES]->(c)
        RETURN m.id
        """,
        {"id": rec_id, "code": SERVER_CODE_ID, "hash": graph_hash,
         "prev_rev": prev_rev, "now": now, "change_summary": change_summary},
    )

    # Independent readback: node is now the authority and hash-matches the file.
    rows = qro(
        "MATCH (n {id:$id}) RETURN n.source_hash, n.materialized_hash, n.revision_id, "
        "n.status, n.authority_mode, size(n.source)",
        {"id": SERVER_CODE_ID},
    )
    r = rows[0]
    node_source_hash, node_mat_hash, node_rev, status, authority, node_source_len = r
    file_hash = sha256_text(SERVER_SOURCE_PATH.read_text(encoding="utf-8"))

    node_has_adapter = qro(
        "MATCH (n {id:$id}) WHERE n.source CONTAINS 'normalize_graph_write_arguments' "
        "AND n.source CONTAINS 'inputAdapter' RETURN count(n)",
        {"id": SERVER_CODE_ID},
    )[0][0]

    proof = {
        "phase": "reconcile-mcp-server-code-node",
        "generatedAt": now,
        "previous": {"source_hash": prev_hash, "revision_id": prev_rev},
        "current": {
            "source_hash": node_source_hash,
            "materialized_hash": node_mat_hash,
            "revision_id": node_rev,
            "status": status,
            "authority_mode": authority,
            "node_source_chars": node_source_len,
        },
        "file_hash": file_hash,
        "node_source_hash_equals_file": node_source_hash == file_hash,
        "materialized_hash_equals_source": node_mat_hash == node_source_hash,
        "node_source_contains_adapter": int(node_has_adapter) == 1,
        "changed": prev_hash != node_source_hash,
        "materialization_moment": rec_id,
    }
    print(json.dumps(proof, ensure_ascii=False, indent=2))

    ok = (
        proof["node_source_hash_equals_file"]
        and proof["materialized_hash_equals_source"]
        and proof["node_source_contains_adapter"]
    )
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
