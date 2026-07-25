"""Graph ChangeSet: declare the `graph_write_single_node_v0` input adapter.

Graph-first fix for the MCP `graph_write` adapter. The batch executor
(`execute_graph_upsert`) is NOT changed. Instead, the tool contract node in the
operational graph declares an `input_adapter`, and the MCP dispatcher applies
the named, vetted normalizer (`normalize_graph_write_arguments`) upstream of the
executor. This mirrors the `executor_type` pattern: a graph-declared string
selects a Python implementation.

This ChangeSet:
  * updates  contract:l2:mcp:graph-write-tool:v0
       - sets input_adapter = 'graph_write_single_node_v0'
       - rewrites input_schema_json to declare BOTH accepted shapes honestly
       - bumps version 0.2.0 -> 0.3.0
  * creates  code:l2:mcp:graph-write-adapter:v0  (CodeDefinition of the adapter)
  * relates  contract -[:USES_INPUT_ADAPTER]-> adapter code
             adapter code -[:IMPLEMENTED_BY]-> server module code
  * records  moment:l2:mcp:graph-write-adapter-deploy:v0  (provenance)

Idempotent: re-running MERGEs the same nodes/relations.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from falkordb import FalkorDB

GRAPH = "mind_kernel_v0"
CONTRACT_ID = "contract:l2:mcp:graph-write-tool:v0"
ADAPTER_CODE_ID = "code:l2:mcp:graph-write-adapter:v0"
SERVER_MODULE_CODE_ID = "code:l2:mcp:nodes-as-code-server:v0"
MOMENT_ID = "moment:l2:mcp:graph-write-adapter-deploy:v0"
ADAPTER_ID = "graph_write_single_node_v0"

# Honest schema: the runtime now accepts EITHER shape. The adapter normalizes
# the shorthand single-node form into the canonical batch form before the
# executor runs, so both are declared here.
GRAPH_WRITE_SCHEMA_V3 = {
    "type": "object",
    "description": (
        "Two accepted shapes, normalized by input adapter "
        f"'{ADAPTER_ID}'. "
        "Batch: {\"nodes\":[{...}], \"relations\":[{\"source\",\"relation\",\"target\"}]}. "
        "Shorthand single node: {\"node_type\",\"id\", ...} with optional implicit-relation "
        "shortcuts parent/link_to/spaces/things (expanded to CONTRIBUTES_TO / "
        "RELATES_TO / OCCURRED_IN / RELATES_TO respectively)."
    ),
    "properties": {
        "password": {"type": "string"},
        # ---- batch mode ----
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "node_type": {"type": "string",
                                  "enum": ["actor", "moment", "narrative", "space", "thing"]},
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
        # ---- shorthand single-node mode ----
        "node_type": {"type": "string",
                      "enum": ["actor", "moment", "narrative", "space", "thing"]},
        "id": {"type": "string"},
        "type": {"type": "string"},
        "subtype": {"type": "string"},
        "name": {"type": "string"},
        "content": {"type": "string"},
        "synthesis": {"type": "string"},
        "parent": {"type": "string"},
        "link_to": {"type": "array", "items": {"type": "string"}},
        "spaces": {"type": "array", "items": {"type": "string"}},
        "things": {"type": "array", "items": {"type": "string"}},
        # ---- flags ----
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

    # 1. Update the tool contract node: declare the adapter + honest schema.
    q(
        """
        MATCH (c {id:$id})
        SET c.input_adapter = $adapter,
            c.input_schema_json = $schema,
            c.version = '0.3.0',
            c.updated_at = $t
        """,
        {"id": CONTRACT_ID, "adapter": ADAPTER_ID,
         "schema": json.dumps(GRAPH_WRITE_SCHEMA_V3, ensure_ascii=False, sort_keys=True),
         "t": ts},
    )

    # 2. CodeDefinition of the adapter (implemented in the server module).
    q(
        """
        MERGE (code {id:$id})
        SET code:RuntimeNode,
            code.node_type = 'thing',
            code.type = 'code',
            code.subtype = 'code',
            code.name = 'CodeDefinition · graph_write input adapter v0',
            code.adapter_id = $adapter,
            code.authority_mode = 'graph_structured_definition',
            code.status = 'implemented_in_server_module',
            code.implemented_by = $server_code,
            code.entrypoint = 'mind_node_runtime.mcp_server:normalize_graph_write_arguments',
            code.language = 'python',
            code.updated_at = $t
        """,
        {"id": ADAPTER_CODE_ID, "adapter": ADAPTER_ID, "server_code": SERVER_MODULE_CODE_ID, "t": ts},
    )

    # 3. Relations: contract uses the adapter; adapter implemented by server module.
    q(
        """
        MATCH (c {id:$contract}) MATCH (a {id:$adapter})
        MERGE (c)-[r:USES_INPUT_ADAPTER]->(a) SET r.updated_at = $t
        """,
        {"contract": CONTRACT_ID, "adapter": ADAPTER_CODE_ID, "t": ts},
    )
    # Only relate to the server module code node if it exists (do not invent it).
    q(
        """
        MATCH (a {id:$adapter}) MATCH (s {id:$server_code})
        MERGE (a)-[r:IMPLEMENTED_BY]->(s) SET r.updated_at = $t
        """,
        {"adapter": ADAPTER_CODE_ID, "server_code": SERVER_MODULE_CODE_ID, "t": ts},
    )

    # 4. Provenance Moment.
    q(
        """
        MERGE (m {id:$id})
        SET m:RuntimeNode,
            m.node_type = 'moment',
            m.subtype = 'change_applied',
            m.name = 'ChangeSet · graph_write input adapter declared',
            m.content = 'Declared input_adapter=graph_write_single_node_v0 on the graph_write contract; the MCP dispatcher normalizes shorthand single-node writes into the canonical batch form upstream of the unchanged batch executor.',
            m.status = 'measured',
            m.emitted_at = $t
        WITH m
        MATCH (c {id:$contract}) MERGE (m)-[:OCCURRED_IN]->(c)
        """,
        {"id": MOMENT_ID, "contract": CONTRACT_ID, "t": ts},
    )

    # 5. Read back proof (independent verification, not trusting the writes).
    contract = q(
        "MATCH (c {id:$id}) RETURN c.tool_name, c.version, c.input_adapter, c.input_schema_json",
        {"id": CONTRACT_ID},
    )
    adapter = q(
        "MATCH (a {id:$id}) RETURN a.id, a.adapter_id, a.status, a.entrypoint",
        {"id": ADAPTER_CODE_ID},
    )
    rel = q(
        "MATCH (c {id:$contract})-[r:USES_INPUT_ADAPTER]->(a {id:$adapter}) RETURN count(r)",
        {"contract": CONTRACT_ID, "adapter": ADAPTER_CODE_ID},
    )
    moment = q("MATCH (m {id:$id}) RETURN m.id, m.status", {"id": MOMENT_ID})

    schema_ok = False
    if contract:
        try:
            parsed = json.loads(contract[0][3])
            schema_ok = "node_type" in parsed.get("properties", {}) and "nodes" in parsed.get("properties", {})
        except (TypeError, json.JSONDecodeError):
            schema_ok = False

    proof = {
        "phase": "deploy-graph-write-input-adapter",
        "generatedAt": ts,
        "contract": {
            "tool_name": contract[0][0] if contract else None,
            "version": contract[0][1] if contract else None,
            "input_adapter": contract[0][2] if contract else None,
            "schema_declares_both_shapes": schema_ok,
        },
        "adapter_code": {
            "found": bool(adapter),
            "adapter_id": adapter[0][1] if adapter else None,
            "status": adapter[0][2] if adapter else None,
            "entrypoint": adapter[0][3] if adapter else None,
        },
        "contract_uses_adapter": bool(rel and rel[0][0] == 1),
        "provenance_moment": bool(moment),
    }
    print(json.dumps(proof, ensure_ascii=False, indent=2))

    ok = (
        proof["contract"]["input_adapter"] == ADAPTER_ID
        and schema_ok
        and proof["adapter_code"]["found"]
        and proof["contract_uses_adapter"]
        and proof["provenance_moment"]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
