import unittest
from mind_node_runtime.config import Settings
from mind_node_runtime.graph import GraphStore
from mind_node_runtime.mcp_server import (
    ReadOnlyGraph,
    ToolError,
    execute_sense,
    execute_graph_upsert,
    normalize_graph_write_arguments,
    apply_input_adapter,
    UNIVERSAL_NODE_TYPES,
    _infer_suggested_type,
)


class TestSmartWriteAndSense(unittest.TestCase):
    def test_universal_node_types(self):
        self.assertIn("actor", UNIVERSAL_NODE_TYPES)
        self.assertIn("space", UNIVERSAL_NODE_TYPES)
        self.assertIn("narrative", UNIVERSAL_NODE_TYPES)
        self.assertIn("moment", UNIVERSAL_NODE_TYPES)
        self.assertIn("thing", UNIVERSAL_NODE_TYPES)
        self.assertEqual(_infer_suggested_type("space:demo:v0", "ontology_module"), "space")
        self.assertEqual(_infer_suggested_type("actor:user:v0", "user"), "actor")
        self.assertEqual(_infer_suggested_type("objective:demo:v0", "objective"), "narrative")
        self.assertEqual(_infer_suggested_type("moment:event:v0", "event"), "moment")

    def test_execute_sense(self):
        settings = Settings()
        graph = ReadOnlyGraph(settings)
        provenance_base = {
            "graph": settings.graph_name,
            "host": settings.host,
            "port": settings.port,
            "bindingId": "binding:l2:mcp:sense:v0",
            "contractId": "contract:l2:mcp:sense-tool:v0",
            "capabilityId": "capability:l2:mcp:sense-read-only:v0",
            "mainLoopId": "space:l2:mind-citizen:sense-situated-state-v0",
        }
        result = execute_sense(graph, {"include_moments": True, "limit_moments": 3}, provenance_base)
        self.assertEqual(result["information_status"], "measured")
        self.assertIn("projection", result)
        proj = result["projection"]
        self.assertIn("identity", proj)
        self.assertIn("spaces_and_loops", proj)
        self.assertIn("mcp_bindings", proj)
        self.assertIn("daemons_and_health", proj)
        self.assertIn("recent_moments", proj)
        self.assertEqual(result["provenance"]["executor"], "sense_ref")

    def test_execute_smart_graph_upsert(self):
        settings = Settings()
        store = GraphStore(settings)
        provenance_base = {
            "graph": settings.graph_name,
            "host": settings.host,
            "port": settings.port,
            "bindingId": "binding:l2:mcp:graph-write:v0",
            "contractId": "contract:l2:mcp:graph-write-tool:v0",
            "capabilityId": "capability:l2:mcp:graph-write:v0",
            "mainLoopId": "space:l2:mcp:graph-write-v0",
        }

        args = {
            "nodes": [
                {
                    "id": "thing:test:smart-write-orphan-v0",
                    "node_type": "invalid_custom_type",
                    "subtype": "test_node",
                    "name": "Smart Write Test Node",
                }
            ],
            "relations": [],
            "check_orphans": True,
            "check_similarity": True,
            "suggest_links": True,
        }

        res = execute_graph_upsert(store, args, server_password=None, provenance_base=provenance_base)
        self.assertEqual(res["information_status"], "measured")
        self.assertEqual(res["nodesUpserted"], 1)
        self.assertEqual(len(res["validation_errors"]), 1)
        self.assertEqual(res["validation_errors"][0]["node_id"], "thing:test:smart-write-orphan-v0")
        self.assertEqual(len(res["suggested_corrections"]), 1)
        self.assertEqual(res["suggested_corrections"][0]["suggested_value"], "thing")

        # Verify orphan node detection
        self.assertEqual(len(res["orphan_nodes"]), 1)
        self.assertEqual(res["orphan_nodes"][0]["node_id"], "thing:test:smart-write-orphan-v0")

        # Verify candidate link suggestions
        self.assertIn("suggested_candidate_links", res)


class TestGraphWriteInputAdapter(unittest.TestCase):
    """The graph-declared `graph_write_single_node_v0` input adapter."""

    def test_batch_payload_passthrough(self):
        args = {
            "nodes": [{"id": "space:test:x", "node_type": "space"}],
            "relations": [{"source": "a", "relation": "R", "target": "b"}],
            "password": "pw",
            "check_orphans": False,
        }
        out = normalize_graph_write_arguments(args)
        self.assertEqual(out["nodes"], args["nodes"])
        self.assertEqual(out["relations"], args["relations"])
        # Control fields are preserved through normalization.
        self.assertEqual(out["password"], "pw")
        self.assertEqual(out["check_orphans"], False)

    def test_shorthand_single_node(self):
        out = normalize_graph_write_arguments({
            "node_type": "space",
            "id": "space:test:single-node-v0",
            "type": "ontology_module",
            "name": "Single node graph_write test",
            "content": "Tests normalization from one node to a canonical batch.",
            "password": "pw",
        })
        self.assertEqual(len(out["nodes"]), 1)
        node = out["nodes"][0]
        self.assertEqual(node["id"], "space:test:single-node-v0")
        self.assertEqual(node["node_type"], "space")
        self.assertEqual(node["type"], "ontology_module")
        self.assertEqual(node["name"], "Single node graph_write test")
        self.assertEqual(out["relations"], [])
        self.assertEqual(out["password"], "pw")
        # Control keys must not leak into the node props.
        self.assertNotIn("password", node)

    def test_shorthand_implicit_relations(self):
        out = normalize_graph_write_arguments({
            "node_type": "narrative",
            "id": "objective:test:child-v0",
            "type": "objective",
            "name": "Child objective",
            "parent": "project:test:parent-v0",
            "spaces": ["space:test:single-node-v0"],
        })
        self.assertEqual(len(out["nodes"]), 1)
        # Relations use THIS executor's canonical source/relation/target keys.
        self.assertIn(
            {"source": "objective:test:child-v0", "relation": "CONTRIBUTES_TO",
             "target": "project:test:parent-v0"},
            out["relations"],
        )
        self.assertIn(
            {"source": "objective:test:child-v0", "relation": "OCCURRED_IN",
             "target": "space:test:single-node-v0"},
            out["relations"],
        )

    def test_shorthand_requires_id(self):
        with self.assertRaises(ToolError):
            normalize_graph_write_arguments({"node_type": "space", "name": "no id"})

    def test_empty_payload_rejected(self):
        with self.assertRaises(ToolError):
            normalize_graph_write_arguments({})

    def test_apply_input_adapter_dispatch(self):
        out = apply_input_adapter("graph_write_single_node_v0",
                                  {"node_type": "thing", "id": "thing:test:z"})
        self.assertEqual(out["nodes"][0]["id"], "thing:test:z")

    def test_apply_unknown_adapter_rejected(self):
        with self.assertRaises(ToolError):
            apply_input_adapter("does_not_exist_v0", {"id": "x"})


if __name__ == "__main__":
    unittest.main()
