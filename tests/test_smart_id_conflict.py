"""Tests for smart id-conflict resolution in graph_write / graph_upsert.

Pure-decision tests need no database. The integration tests exercise the real
FalkorDB behind the runtime (same convention as test_smart_write_and_sense) and
clean up every node they create.
"""
import unittest

from mind_node_runtime.config import Settings
from mind_node_runtime.graph import GraphStore
from mind_node_runtime.mcp_server import (
    ID_CONFLICT_MODES,
    ToolError,
    _names_match,
    _next_available_id,
    _token_jaccard,
    decide_id_conflict,
    execute_graph_upsert,
    normalize_graph_write_arguments,
)


class TestDecideIdConflictPure(unittest.TestCase):
    """decide_id_conflict is a pure function: no I/O, deterministic."""

    def test_node_type_conflict_differentiates(self):
        d = decide_id_conflict(
            {"node_type": "actor", "name": "X", "content": "same text"},
            {"node_type": "space", "name": "X", "content": "same text"},
        )
        self.assertEqual(d["decision"], "differentiate")
        self.assertEqual(d["reason"], "node_type_conflict")

    def test_matching_names_merge(self):
        d = decide_id_conflict(
            {"node_type": "space", "name": "Auth Service", "content": "totally different words here"},
            {"node_type": "space", "name": "Auth Service", "content": "nothing in common at all"},
        )
        self.assertEqual(d["decision"], "merge")
        self.assertEqual(d["reason"], "name_match")

    def test_substring_name_matches_merge(self):
        d = decide_id_conflict(
            {"node_type": "space", "name": "Authentication"},
            {"node_type": "space", "name": "Authentication service v2"},
        )
        self.assertEqual(d["decision"], "merge")

    def test_conflicting_names_differentiate(self):
        d = decide_id_conflict(
            {"node_type": "narrative", "name": "Billing objective"},
            {"node_type": "narrative", "name": "Onboarding objective"},
        )
        self.assertEqual(d["decision"], "differentiate")
        self.assertEqual(d["reason"], "name_conflict")

    def test_identical_content_merges_when_no_names(self):
        d = decide_id_conflict(
            {"node_type": "moment", "content": "  Payment   RECEIVED "},
            {"node_type": "moment", "content": "payment received"},
        )
        self.assertEqual(d["decision"], "merge")
        self.assertEqual(d["reason"], "identical_content")
        self.assertEqual(d["content_similarity"], 1.0)

    def test_high_content_similarity_merges(self):
        base = "the quick brown fox jumps over the lazy dog every single morning"
        near = "the quick brown fox jumps over the lazy dog each single morning"
        d = decide_id_conflict(
            {"node_type": "moment", "content": near},
            {"node_type": "moment", "content": base},
        )
        self.assertEqual(d["decision"], "merge")
        self.assertEqual(d["reason"], "high_content_similarity")

    def test_low_content_similarity_differentiates(self):
        d = decide_id_conflict(
            {"node_type": "moment", "content": "apples oranges bananas grapes melon"},
            {"node_type": "moment", "content": "tcp handshake retransmit socket buffer"},
        )
        self.assertEqual(d["decision"], "differentiate")
        self.assertEqual(d["reason"], "low_content_similarity")

    def test_uncertain_band_differentiates_and_flags(self):
        # Jaccard = 3/5 = 0.6: neither >= 0.80 nor <= 0.35.
        d = decide_id_conflict(
            {"node_type": "moment", "content": "alpha beta gamma delta"},
            {"node_type": "moment", "content": "alpha beta gamma epsilon"},
        )
        self.assertEqual(d["decision"], "differentiate")
        self.assertEqual(d["reason"], "uncertain_similarity")
        self.assertTrue(d["uncertain"])

    def test_insufficient_evidence_defaults_to_merge(self):
        # No comparable name or content -> conservative in-place update.
        d = decide_id_conflict(
            {"node_type": "thing", "status": "active"},
            {"node_type": "thing", "name": "Existing thing"},
        )
        self.assertEqual(d["decision"], "merge")
        self.assertEqual(d["reason"], "insufficient_evidence_default_merge")

    def test_helpers(self):
        self.assertTrue(_names_match("Auth", "auth"))
        self.assertFalse(_names_match("", "x"))
        self.assertEqual(_token_jaccard("a b c", "a b c"), 1.0)
        self.assertEqual(_token_jaccard("a b", "c d"), 0.0)
        self.assertEqual(_token_jaccard("", ""), 1.0)


class TestAdapterDefaultsSmart(unittest.TestCase):
    def test_graph_write_defaults_to_smart(self):
        out = normalize_graph_write_arguments({"node_type": "space", "id": "space:test:x"})
        self.assertEqual(out["on_id_conflict"], "smart")

    def test_caller_override_respected(self):
        out = normalize_graph_write_arguments(
            {"node_type": "space", "id": "space:test:x", "on_id_conflict": "merge"}
        )
        self.assertEqual(out["on_id_conflict"], "merge")

    def test_batch_payload_gets_smart_default(self):
        out = normalize_graph_write_arguments(
            {"nodes": [{"id": "space:test:x", "node_type": "space"}], "relations": []}
        )
        self.assertEqual(out["on_id_conflict"], "smart")

    def test_mode_enum(self):
        self.assertEqual(ID_CONFLICT_MODES, {"merge", "smart", "differentiate", "reject"})


class TestSmartUpsertIntegration(unittest.TestCase):
    """Exercises the real graph. Every created node is removed in tearDown."""

    def setUp(self):
        self.store = GraphStore(Settings())
        self.prefix = "thing:test:smart-conflict"
        self._cleanup()
        self.provenance = {"graph": "test", "executor": "test"}

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        # Remove the base id and any -N differentiated siblings.
        self.store.write(
            "MATCH (n) WHERE n.id = $b OR n.id STARTS WITH $p DETACH DELETE n",
            {"b": self.prefix + ":v0", "p": self.prefix + ":v0-"},
        )

    def _count(self, node_id):
        rows = self.store.read("MATCH (n {id:$id}) RETURN count(n)", {"id": node_id})
        return rows[0][0] if rows else 0

    def test_merge_mode_never_duplicates(self):
        nid = self.prefix + ":v0"
        args = {"nodes": [{"id": nid, "node_type": "thing", "name": "Base"}], "relations": []}
        execute_graph_upsert(self.store, dict(args), None, self.provenance)
        execute_graph_upsert(self.store, dict(args), None, self.provenance)
        self.assertEqual(self._count(nid), 1)

    def test_smart_merges_same_entity(self):
        nid = self.prefix + ":v0"
        execute_graph_upsert(
            self.store,
            {"nodes": [{"id": nid, "node_type": "thing", "name": "Widget"}], "relations": []},
            None, self.provenance,
        )
        res = execute_graph_upsert(
            self.store,
            {"nodes": [{"id": nid, "node_type": "thing", "name": "Widget"}], "relations": [],
             "on_id_conflict": "smart"},
            None, self.provenance,
        )
        self.assertEqual(self._count(nid), 1)
        self.assertEqual(res["id_resolutions"][0]["decision"], "merge")

    def test_smart_differentiates_conflicting_entity(self):
        nid = self.prefix + ":v0"
        execute_graph_upsert(
            self.store,
            {"nodes": [{"id": nid, "node_type": "thing", "name": "Widget"}], "relations": []},
            None, self.provenance,
        )
        res = execute_graph_upsert(
            self.store,
            {"nodes": [{"id": nid, "node_type": "thing", "name": "Completely Different Gadget"}],
             "relations": [], "on_id_conflict": "smart"},
            None, self.provenance,
        )
        self.assertEqual(res["id_resolutions"][0]["decision"], "differentiate")
        self.assertEqual(res["id_resolutions"][0]["effective_id"], nid + "-2")
        self.assertEqual(self._count(nid), 1)
        self.assertEqual(self._count(nid + "-2"), 1)

    def test_reject_mode_raises_on_collision(self):
        nid = self.prefix + ":v0"
        execute_graph_upsert(
            self.store,
            {"nodes": [{"id": nid, "node_type": "thing", "name": "Base"}], "relations": []},
            None, self.provenance,
        )
        with self.assertRaises(ToolError):
            execute_graph_upsert(
                self.store,
                {"nodes": [{"id": nid, "node_type": "thing", "name": "Base"}], "relations": [],
                 "on_id_conflict": "reject"},
                None, self.provenance,
            )

    def test_next_available_id_skips_taken(self):
        nid = self.prefix + ":v0"
        for suffix in ("", "-2", "-3"):
            self.store.write(
                "MERGE (n:RuntimeNode {id:$id}) SET n.node_type='thing'", {"id": nid + suffix}
            )
        self.assertEqual(_next_available_id(self.store, nid), nid + "-4")


if __name__ == "__main__":
    unittest.main()
