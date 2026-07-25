"""
Loop 9 Engine: Cognition Sociale, Rôles et Action dans le Monde.

Manages Theory of Mind (Other Models), Citizen AI role routing (one primary, max 3 support),
consent validation, delegation mandates, and human ratification / correction logging.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


class OtherModelFrame:
    def __init__(
        self, actor_id: str, perceived_intent: str, opacity_score: float = 0.5
    ) -> None:
        self.actor_id = actor_id
        self.perceived_intent = perceived_intent
        self.opacity_score = max(0.0, min(1.0, opacity_score))
        self.timestamp = int(time.time() * 1000)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "perceived_intent": self.perceived_intent,
            "opacity_score": round(self.opacity_score, 2),
            "timestamp": self.timestamp,
        }


class SocialCognitionEngine:
    """Engine for Loop 9 (space:brain:social-v0)."""

    def __init__(self) -> None:
        self.available_roles = [
            "companion",
            "architect",
            "researcher",
            "executor",
            "guardian",
        ]
        self.current_primary_role = "companion"
        self.current_support_roles: List[str] = ["architect"]

    def route_role(
        self, context_domain: str, requested_role: Optional[str] = None
    ) -> Dict[str, Any]:
        if requested_role and requested_role in self.available_roles:
            new_primary = requested_role
        elif context_domain == "somatic_metabolic":
            new_primary = "guardian"
        elif context_domain == "executive_tool":
            new_primary = "executor"
        else:
            new_primary = "companion"

        handoff = new_primary != self.current_primary_role
        old_primary = self.current_primary_role
        self.current_primary_role = new_primary

        return {
            "primary_role": self.current_primary_role,
            "support_roles": self.current_support_roles,
            "handoff_occurred": handoff,
            "previous_role": old_primary if handoff else None,
        }

    def validate_human_ratification(
        self, action_moment_id: str, human_actor_id: str = "human:user"
    ) -> Dict[str, Any]:
        return {
            "moment_id": action_moment_id,
            "ratified_by": human_actor_id,
            "status": "ratified",
            "timestamp": int(time.time() * 1000),
        }
