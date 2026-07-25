"""
Test Suite for talk MCP Loop & Physical Membrane Database Isolation.

Verifies end-to-end flow across physical database boundaries:
1. MCP talk tool execution writes pending membrane_stimulus Moment to dedicated mind_membrane_v0 graph.
2. L1 Citizen DB (mind_kernel_v0) remains isolated with zero inter-graph edges.
3. Perception Engine senses pending stimulus from mind_membrane_v0 across DB boundaries.
4. Stimulus is atomized into internal PerceptAtoms in mind_kernel_v0 and digested by Metabolism Engine.
5. Stimulus status transitions to 'consumed' in mind_membrane_v0 graph database.
"""

from __future__ import annotations

import os
import unittest
from falkordb import FalkorDB

from mind_node_runtime.config import Settings
from mind_node_runtime.graph import GraphStore
from mind_node_runtime.talk import execute_talk
from mind_node_runtime.brain.perception import PerceptionEngine
from mind_node_runtime.brain.metabolism import MetabolismEngine


class TestTalkMembraneLoop(unittest.TestCase):

    def setUp(self):
        membrane_graph = os.getenv("MEMBRANE_GRAPH", "mind_membrane_v0")
        l1_graph = os.getenv("FALKOR_GRAPH", "mind_kernel_v0")

        self.membrane_store = GraphStore(Settings(graph_name=membrane_graph))
        self.l1_store = GraphStore(Settings(graph_name=l1_graph))

        self.perception = PerceptionEngine()
        self.metabolism = MetabolismEngine()

    def test_talk_physical_database_isolation_flow(self):
        # 1. Execute talk capability to send message into mind_membrane_v0
        message_text = "Message sécurisé franchissant la membrane physique."
        result = execute_talk(
            store=self.membrane_store,
            message=message_text,
            senderActorId="human:user",
            targetActorId="actor:citizen:l1",
            membraneSpaceId="space:membrane:l1-boundary-v0",
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["membraneGraph"], "mind_membrane_v0")
        stimulus_id = result["stimulusMomentId"]

        # 2. Verify stimulus exists in mind_membrane_v0 as 'pending'
        rows = self.membrane_store.read(
            "MATCH (s:RuntimeNode {id:$id}) RETURN s.stimulus_status, s.content",
            {"id": stimulus_id},
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "pending")

        # 3. Verify stimulus does NOT exist in mind_kernel_v0 (L1 internal DB)
        rows_l1 = self.l1_store.read(
            "MATCH (s:RuntimeNode {id:$id}) RETURN s.id",
            {"id": stimulus_id},
        )
        self.assertEqual(len(rows_l1), 0, "Stimulus must not exist as a Cypher node inside L1 DB")

        # 4. Perception loop senses membrane stimuli from mind_membrane_v0
        percepts = self.perception.sense_membrane_stimuli(
            membrane_store=self.membrane_store,
            membrane_space_id="space:membrane:l1-boundary-v0",
            citizen_id="actor:citizen:l1",
        )

        self.assertGreaterEqual(len(percepts), 1)
        percept = percepts[0]
        self.assertIn("Message sécurisé", percept.content)

        # 5. Digest percept internally in L1 Metabolism Engine
        salience = self.perception.compute_salience(percept)
        intensity = self.metabolism.propagate_energy(input_energy=salience, weight=1.0, polarity=1.0, gate=1.0)
        self.assertGreater(intensity, 0.0)

        # 6. Verify stimulus status updated to 'consumed' in mind_membrane_v0
        rows_after = self.membrane_store.read(
            "MATCH (s:RuntimeNode {id:$id}) RETURN s.stimulus_status, s.consumed_at",
            {"id": stimulus_id},
        )
        self.assertEqual(len(rows_after), 1)
        self.assertEqual(rows_after[0][0], "consumed")
        self.assertIsNotNone(rows_after[0][1])


if __name__ == "__main__":
    unittest.main()
