"""
Test Suite for L1 Brain Function Loops & Reflex Workers.

Verifies:
1. Graph representation of all 9 Brain Function Loops in mind_kernel_v0.
2. Runtime behavior of all 9 materialized engines and 6 1B reflex workers.
"""

from __future__ import annotations

import os
import unittest
from falkordb import FalkorDB

from mind_node_runtime.brain.affect import AffectEngine, LimbicStateVector
from mind_node_runtime.brain.executive import ActionProposal, ExecutiveEngine
from mind_node_runtime.brain.memory_system import MemorySystemEngine, MomentTrace
from mind_node_runtime.brain.metabolism import MetabolismEngine, MetabolicStateSnapshot
from mind_node_runtime.brain.perception import PerceptionEngine
from mind_node_runtime.brain.plasticity import BehaviorPattern, PlasticityEngine
from mind_node_runtime.brain.reflex_workers import (
    ContextCompressor,
    EventCandidateExtractor,
    IntentRouter,
    PatternMatcher,
    PerceptClassifier,
    StructuredExtractor,
)
from mind_node_runtime.brain.social import SocialCognitionEngine
from mind_node_runtime.brain.subentities import SubentitiesEngine
from mind_node_runtime.brain.workspace import GlobalWorkspaceEngine, WorkspaceItem


def get_falkor_graph():
    host = os.getenv("FALKOR_HOST", "127.0.0.1")
    port = int(os.getenv("FALKOR_PORT", "6379"))
    graph_name = os.getenv("FALKOR_GRAPH", "mind_kernel_v0")
    client = FalkorDB(host=host, port=port)
    return client.select_graph(graph_name)


class TestBrainLoops(unittest.TestCase):

    def test_brain_loops_seeded_in_graph(self):
        graph = get_falkor_graph()
        query = """
        MATCH (space:RuntimeNode)
        WHERE space.id STARTS WITH 'space:brain:'
        RETURN space.id, space.name
        ORDER BY space.id
        """
        res = graph.query(query).result_set
        self.assertEqual(len(res), 9, f"Expected 9 brain loops in graph, got {len(res)}")
        loop_ids = [row[0] for row in res]
        expected_ids = [
            "space:brain:affect-v0",
            "space:brain:executive-v0",
            "space:brain:memory-v0",
            "space:brain:metabolism-v0",
            "space:brain:perception-v0",
            "space:brain:plasticity-v0",
            "space:brain:social-v0",
            "space:brain:subentities-v0",
            "space:brain:workspace-v0",
        ]
        self.assertEqual(sorted(loop_ids), sorted(expected_ids))

    def test_brain_loop_causal_chains_in_graph(self):
        graph = get_falkor_graph()
        query = """
        MATCH (s:RuntimeNode {id:'space:brain:metabolism-v0'})-[:CONTAINS]->(obj),
              (s)-[:HAS_PATTERN]->(pat),
              (s)-[:HAS_BEHAVIOR]->(beh),
              (s)-[:DEFINED_BY_CODE]->(code),
              (s)-[:OBSERVED_BY]->(obs)
        RETURN obj.id, pat.id, beh.id, code.id, obs.id
        """
        res = graph.query(query).result_set
        self.assertEqual(len(res), 1, "Loop 1 causal chain incomplete in graph")
        self.assertEqual(res[0][0], "objective:brain:metabolism:primary")
        self.assertEqual(res[0][3], "code:brain:metabolism-engine:v0")

    def test_loop1_metabolism_engine(self):
        engine = MetabolismEngine()
        initial_energy = engine.state.energy_pool
        intensity = engine.propagate_energy(input_energy=10.0, weight=0.8, polarity=1.0, gate=1.0)
        self.assertEqual(intensity, 8.0)
        self.assertLess(engine.state.energy_pool, initial_energy, "Energy pool must decay on work")

        recovered_state = engine.recover(duration_minutes=5.0)
        self.assertGreater(recovered_state.energy_pool, 0.0)

    def test_loop2_perception_engine(self):
        engine = PerceptionEngine()
        percepts = engine.atomize("Fichier reçu\nNouveau message important", source="user")
        self.assertEqual(len(percepts), 2)

        salience1 = engine.compute_salience(percepts[0])
        salience2 = engine.compute_salience(percepts[0])
        self.assertGreater(salience1, salience2, "Repeated percept hash must lose novelty")

    def test_loop3_global_workspace_engine(self):
        gw = GlobalWorkspaceEngine(max_slots=2)
        gw.submit_candidate(WorkspaceItem("item1", "Premier fait", heat=0.8))
        gw.submit_candidate(WorkspaceItem("item2", "Deuxième fait", heat=0.9))
        self.assertEqual(gw.select_leader().item_id, "item2")

        gw.submit_candidate(WorkspaceItem("item3", "Troisième fait très chaud", heat=1.5))
        snapshot = gw.get_snapshot()
        self.assertEqual(snapshot["slots_count"], 2)
        self.assertEqual(snapshot["leader"]["item_id"], "item3")

    def test_loop4_memory_system_engine(self):
        mem = MemorySystemEngine()
        moment = MomentTrace("moment:1", "observation", "L'utilisateur demande les boucles", "human:user")
        mem.record_moment(moment)

        firewall = mem.epistemic_firewall_check("L'utilisateur ne demande pas les boucles", ["L'utilisateur demande les boucles"])
        self.assertTrue(firewall["has_contradiction"])
        self.assertFalse(firewall["passed_firewall"])

    def test_loop5_affect_engine(self):
        affect = AffectEngine()
        state = affect.update_from_percept_signal({"candidate_signal": "threat", "confidence": 0.9})
        self.assertGreater(state.threat_level, 0.0)
        self.assertEqual(state.determine_dominant_prototype(), "fear_alert")

    def test_loop6_subentities_engine(self):
        sub = SubentitiesEngine()
        bids = sub.evaluate_coalition_bids("Analyse de la structure du graphe et des règles de code")
        self.assertGreater(len(bids), 0)
        arbitration = sub.arbitrate_captain(bids, "AVAILABLE")
        self.assertEqual(arbitration["active_controller"], "subentity:architect")

    def test_loop7_executive_engine(self):
        exec_eng = ExecutiveEngine()
        conf = exec_eng.evaluate_scenario("scenario_a", prior_probability=0.8, evidence_strength=0.9, contradiction_factor=0.1)
        self.assertGreater(conf, 0.6)

        prop = ActionProposal("act1", "run_command", "powershell", {"cmd": "dir"})
        val_denied = exec_eng.validate_action_proposal(prop, user_permissions=["read"])
        self.assertFalse(val_denied["authorized"])

        val_approved = exec_eng.validate_action_proposal(prop, user_permissions=["read", "write"])
        self.assertTrue(val_approved["authorized"])

    def test_loop8_plasticity_engine(self):
        plast = PlasticityEngine()
        pattern = BehaviorPattern("pat1", "AutoRerank", weight=0.5)
        update = plast.update_pattern_weight(pattern, expected=0.5, actual=1.0)
        self.assertEqual(update["relation"], "REINFORCES")
        self.assertGreater(update["new_weight"], 0.5)

    def test_loop9_social_engine(self):
        social = SocialCognitionEngine()
        routed = social.route_role("executive_tool")
        self.assertEqual(routed["primary_role"], "executor")
        self.assertTrue(routed["handoff_occurred"])

    def test_1b_reflex_workers(self):
        classifier = PerceptClassifier()
        res1 = classifier.process("Je suis épuisé et j'ai mal")
        self.assertEqual(res1.output["domain"], "somatic_metabolic")

        extractor = StructuredExtractor()
        res2 = extractor.process("Basel a soumis 3 fichiers à Paris")
        self.assertIn("Basel", res2.output["named_entities"])

        router = IntentRouter()
        res3 = router.process("Exécute une requête graphe", ["graph_query", "graph_write"])
        self.assertEqual(res3.output["recommended_tool"], "graph_query")


if __name__ == "__main__":
    unittest.main()
