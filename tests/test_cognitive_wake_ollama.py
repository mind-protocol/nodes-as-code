"""
Test Suite for Cognitive Wake Activation & Ollama LLM Integration.

Verifies:
1. Energy accumulation in Global Workspace triggers check_wake_threshold().
2. Executive Engine compiles L1 graph state into a structured prompt context.
3. Ollama provider executes or invokes clean fallback.
"""

from __future__ import annotations

import unittest

from mind_node_runtime.brain.affect import AffectEngine
from mind_node_runtime.brain.executive import ExecutiveEngine
from mind_node_runtime.brain.metabolism import MetabolismEngine
from mind_node_runtime.brain.ollama_provider import OllamaLLMProvider
from mind_node_runtime.brain.subentities import SubentitiesEngine
from mind_node_runtime.brain.workspace import GlobalWorkspaceEngine, WorkspaceItem


class TestCognitiveWakeOllama(unittest.TestCase):

    def test_wake_threshold_trigger(self):
        gw = GlobalWorkspaceEngine(max_slots=3)
        check_before = gw.check_wake_threshold(threshold=1.0)
        self.assertFalse(check_before["wake_triggered"])

        gw.submit_candidate(WorkspaceItem("item:urgent", "Question importante", heat=1.5))
        check_after = gw.check_wake_threshold(threshold=1.0)
        self.assertTrue(check_after["wake_triggered"])
        self.assertEqual(check_after["leader_item_id"], "item:urgent")

    def test_compile_wake_context(self):
        executive = ExecutiveEngine()
        context = executive.compile_wake_context(
            citizen_id="actor:citizen:nlr_ai",
            user_message="Comment ça va ?",
            workspace_snapshot={"leader": {"content": "Analyse de situation"}},
            metabolism_snapshot={"regime": "RESTORED"},
            affect_snapshot={"dominant_prototype": "curiosity_exploration"},
            subentity_arbitration={"active_controller": "subentity:architect"},
            active_role="companion",
        )

        self.assertIn("actor:citizen:nlr_ai", context["system_prompt"])
        self.assertIn("subentity:architect", context["system_prompt"])
        self.assertEqual(context["user_message"], "Comment ça va ?")

    def test_execute_wake_tick_with_ollama_provider(self):
        executive = ExecutiveEngine()
        provider = OllamaLLMProvider(base_url="http://localhost:11434")

        compiled = executive.compile_wake_context(
            citizen_id="actor:citizen:nlr_ai",
            user_message="Comment ça va ?",
            workspace_snapshot={"leader": {"content": "Analyse de situation"}},
            metabolism_snapshot={"regime": "RESTORED"},
            affect_snapshot={"dominant_prototype": "curiosity_exploration"},
            subentity_arbitration={"active_controller": "subentity:architect"},
            active_role="companion",
        )

        result = executive.execute_wake_tick(provider, compiled)
        self.assertIn(result["status"], ("success", "fallback_offline"))
        self.assertTrue(len(result["response_text"]) > 10)


if __name__ == "__main__":
    unittest.main()
