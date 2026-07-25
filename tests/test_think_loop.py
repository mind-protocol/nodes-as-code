"""
Test Suite for the `think` Loop: internal L1 stimulus + Global Workspace emergence.

Verifies:
1. `think` writes an internal stimulus DIRECTLY into the citizen's L1 (no membrane).
2. Cognitive ticks run and a response emerges in the Global Workspace, persisted
   as a workspace_response moment linked back to the stimulus.
3. On emergence the stimulus transitions pending -> consumed in the same L1 graph.
4. Defaults apply (text='continuons', citizen='nlr_ai').
5. Epistemic honesty: when the wake threshold is never crossed within the tick
   budget, no response is invented — status='no_response_emerged',
   information_status='not_measured', stimulus stays 'pending'.
"""

from __future__ import annotations

import unittest

from mind_node_runtime.config import Settings
from mind_node_runtime.graph import GraphStore
from mind_node_runtime.think import (
    DEFAULT_THINK_CITIZEN,
    execute_think,
    resolve_citizen_id,
)

TEST_GRAPH = "test_think_v0"


class TestCitizenResolution(unittest.TestCase):
    """Pure resolution logic — no database required."""

    def test_bare_handle(self):
        self.assertEqual(resolve_citizen_id("nlr_ai"), "actor:citizen:nlr_ai")

    def test_full_id_preserved(self):
        self.assertEqual(
            resolve_citizen_id("actor:citizen:nlr_ai"), "actor:citizen:nlr_ai"
        )

    def test_dashed_and_cased(self):
        self.assertEqual(resolve_citizen_id("NLR-AI"), "actor:citizen:nlr_ai")

    def test_empty_falls_back_to_default(self):
        self.assertEqual(
            resolve_citizen_id(""), f"actor:citizen:{DEFAULT_THINK_CITIZEN}"
        )


class TestThinkLoop(unittest.TestCase):

    def setUp(self):
        self.store = GraphStore(Settings(graph_name=TEST_GRAPH))
        # Isolate each run: wipe the throwaway test graph.
        self.store.write("MATCH (n) DETACH DELETE n")

    def test_internal_stimulus_and_workspace_emergence(self):
        result = execute_think(
            store=self.store,
            text="Réfléchis à la cohérence de la structure du graphe.",
            citizen="nlr_ai",
            max_ticks=12,
        )

        # A response emerged in the Global Workspace.
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["information_status"], "measured")
        self.assertEqual(result["citizenActorId"], "actor:citizen:nlr_ai")
        self.assertGreaterEqual(result["ticksRun"], 1)
        self.assertIsNotNone(result["gwResponseMomentId"])
        self.assertTrue(len(result["responseText"]) > 10)

        stimulus_id = result["stimulusMomentId"]
        response_id = result["gwResponseMomentId"]

        # The stimulus was written directly into L1 as an internal_stimulus and
        # is now consumed.
        stim_rows = self.store.read(
            "MATCH (s:RuntimeNode {id:$id}) RETURN s.subtype, s.origin, s.stimulus_status",
            {"id": stimulus_id},
        )
        self.assertEqual(len(stim_rows), 1)
        self.assertEqual(stim_rows[0][0], "internal_stimulus")
        self.assertEqual(stim_rows[0][1], "self")
        self.assertEqual(stim_rows[0][2], "consumed")

        # The emerged response lives in the gw and points back to the stimulus.
        link_rows = self.store.read(
            "MATCH (r:RuntimeNode {id:$rid})-[:RESPONDS_TO]->(s:RuntimeNode {id:$sid}) "
            "RETURN r.subtype, r.node_type",
            {"rid": response_id, "sid": stimulus_id},
        )
        self.assertEqual(len(link_rows), 1)
        self.assertEqual(link_rows[0][0], "workspace_response")
        self.assertEqual(link_rows[0][1], "moment")

        # The gw response is contained by the citizen's L1 Global Workspace space.
        gw_rows = self.store.read(
            "MATCH (gw:RuntimeNode {id:$gw})-[:CONTAINS]->(r:RuntimeNode {id:$rid}) RETURN gw.subtype",
            {"gw": result["gwSpaceId"], "rid": response_id},
        )
        self.assertEqual(len(gw_rows), 1)
        self.assertEqual(gw_rows[0][0], "global_workspace")

    def test_defaults_applied(self):
        result = execute_think(store=self.store)

        self.assertEqual(result["citizenActorId"], "actor:citizen:nlr_ai")
        stim_rows = self.store.read(
            "MATCH (s:RuntimeNode {id:$id}) RETURN s.content",
            {"id": result["stimulusMomentId"]},
        )
        self.assertEqual(len(stim_rows), 1)
        self.assertEqual(stim_rows[0][0], "continuons")

    def test_no_response_is_honest_not_invented(self):
        # An unreachable wake threshold guarantees no emergence within the budget.
        result = execute_think(
            store=self.store,
            text="signal faible",
            citizen="nlr_ai",
            max_ticks=3,
            wake_threshold=999.0,
        )

        self.assertEqual(result["status"], "no_response_emerged")
        self.assertEqual(result["information_status"], "not_measured")
        self.assertIsNone(result["gwResponseMomentId"])
        self.assertIsNone(result["responseText"])
        self.assertEqual(result["ticksRun"], 3)

        # The stimulus must remain pending — absence is never a fabricated answer.
        stim_rows = self.store.read(
            "MATCH (s:RuntimeNode {id:$id}) RETURN s.stimulus_status",
            {"id": result["stimulusMomentId"]},
        )
        self.assertEqual(len(stim_rows), 1)
        self.assertEqual(stim_rows[0][0], "pending")


if __name__ == "__main__":
    unittest.main()
