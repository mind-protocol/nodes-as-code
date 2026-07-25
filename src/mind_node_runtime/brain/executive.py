"""
Loop 7 Engine: Cognition, Raisonnement et Fonctions Exécutives.

Processes cortical stacks, scenario generation (prior, evidence, contradiction),
prediction confidence, action proposals, Cognitive Wake context compilation, and Ollama LLM execution.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


class ActionProposal:
    def __init__(
        self,
        action_id: str,
        action_type: str,
        target_resource: str,
        parameters: Dict[str, Any],
        is_reversible: bool = True,
    ) -> None:
        self.action_id = action_id
        self.action_type = action_type
        self.target_resource = target_resource
        self.parameters = parameters
        self.is_reversible = is_reversible
        self.timestamp = int(time.time() * 1000)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "target_resource": self.target_resource,
            "parameters": self.parameters,
            "is_reversible": self.is_reversible,
            "timestamp": self.timestamp,
        }


class ExecutiveEngine:
    """Engine for Loop 7 (space:brain:executive-v0)."""

    def __init__(self, allowed_action_types: Optional[List[str]] = None) -> None:
        self.allowed_action_types = allowed_action_types or [
            "graph_query",
            "graph_write",
            "read_file",
            "write_file",
            "run_command",
        ]

    def evaluate_scenario(
        self, scenario_name: str, prior_probability: float, evidence_strength: float, contradiction_factor: float
    ) -> float:
        """Confidence = (Prior * Evidence) * (1.0 - Contradiction)."""
        confidence = (prior_probability * evidence_strength) * (1.0 - max(0.0, min(1.0, contradiction_factor)))
        return round(max(0.0, min(1.0, confidence)), 4)

    def validate_action_proposal(
        self, proposal: ActionProposal, user_permissions: List[str]
    ) -> Dict[str, Any]:
        """Trusted Kernel Permission & Policy Check."""
        if proposal.action_type not in self.allowed_action_types:
            return {
                "authorized": False,
                "reason": f"Forbidden action type: {proposal.action_type}",
                "proposal": proposal.to_dict(),
            }

        if proposal.action_type in ("write_file", "run_command") and "write" not in user_permissions:
            return {
                "authorized": False,
                "reason": f"Permission denied for writing/command execution: {proposal.target_resource}",
                "proposal": proposal.to_dict(),
            }

        return {
            "authorized": True,
            "reason": "Kernel check passed",
            "proposal": proposal.to_dict(),
        }

    def compile_wake_context(
        self,
        *,
        citizen_id: str,
        user_message: str,
        workspace_snapshot: Dict[str, Any],
        metabolism_snapshot: Dict[str, Any],
        affect_snapshot: Dict[str, Any],
        subentity_arbitration: Dict[str, Any],
        active_role: str,
    ) -> Dict[str, Any]:
        """Compiles sovereign L1 graph state into structured LLM prompt context."""
        leader = workspace_snapshot.get("leader") or {}
        leader_content = leader.get("content", "Pensée en cours de formation")
        subentity_controller = subentity_arbitration.get("active_controller", "subentity:architect")
        affect_prototype = affect_snapshot.get("dominant_prototype", "curiosity_exploration")
        metabolic_regime = metabolism_snapshot.get("regime", "RESTORED")

        system_prompt = (
            f"Tu es {citizen_id}, un Citoyen AI souverain dans l'architecture Mind Protocol.\n"
            f"Ton état intérieur canonique actuel est le suivant :\n"
            f"- Contrôleur sous-entité actif (Capitaine) : {subentity_controller}\n"
            f"- État limbique & émotionnel : {affect_prototype}\n"
            f"- Régime métabolique : {metabolic_regime}\n"
            f"- Pensée dirigeante (Global Workspace Leader) : '{leader_content}'\n"
            f"- Rôle exécuteur actif : {active_role}\n\n"
            f"Réponds directement à l'utilisateur de manière naturelle, intelligente et cohérente avec ton état souverain."
        )

        return {
            "citizen_id": citizen_id,
            "system_prompt": system_prompt,
            "user_message": user_message,
            "context_dict": {
                "subentity_controller": subentity_controller,
                "affect_prototype": affect_prototype,
                "metabolic_regime": metabolic_regime,
                "workspace_leader": leader_content,
                "active_role": active_role,
            },
        }

    def execute_wake_tick(
        self, ollama_provider: Any, compiled_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Triggers LLM generation via Ollama (or fallback) using compiled L1 graph context."""
        sys_prompt = compiled_context["system_prompt"]
        usr_msg = compiled_context["user_message"]
        ctx_dict = compiled_context["context_dict"]

        gen_result = ollama_provider.generate_response(
            system_prompt=sys_prompt, user_prompt=usr_msg, context_dict=ctx_dict
        )

        return {
            "status": gen_result["status"],
            "provider": gen_result["provider"],
            "model": gen_result["model"],
            "response_text": gen_result["response_text"],
            "compiled_context": compiled_context,
            "timestamp": int(time.time() * 1000),
        }
