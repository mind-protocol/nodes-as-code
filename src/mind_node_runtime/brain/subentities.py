"""
Loop 6 Engine: Personnalité, Sous-entités et Identité.

Tracks recurring coalitions, SubentityHypothesis, Subentity Activations,
WorkspaceBid generation, internal dissent, and Captain executive arbitration.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


class WorkspaceBid:
    def __init__(
        self,
        subentity_id: str,
        perceived_problem: str,
        proposed_content: str,
        bid_score: float,
    ) -> None:
        self.subentity_id = subentity_id
        self.perceived_problem = perceived_problem
        self.proposed_content = proposed_content
        self.bid_score = max(0.0, min(1.0, bid_score))
        self.timestamp = int(time.time() * 1000)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subentity_id": self.subentity_id,
            "perceived_problem": self.perceived_problem,
            "proposed_content": self.proposed_content,
            "bid_score": round(self.bid_score, 4),
            "timestamp": self.timestamp,
        }


class SubentitiesEngine:
    """Engine for Loop 6 (space:brain:subentities-v0)."""

    def __init__(self) -> None:
        self.registered_subentities: Dict[str, Dict[str, Any]] = {
            "subentity:puer": {
                "id": "subentity:puer",
                "name": "Puer / Exploration",
                "keywords": ["nouveauté", "exploration", "créativité", "liberté"],
                "gate": 1.0,
            },
            "subentity:architect": {
                "id": "subentity:architect",
                "name": "Architect / System Control",
                "keywords": ["structure", "graphe", "cohérence", "règles", "code"],
                "gate": 1.0,
            },
            "subentity:guardian": {
                "id": "subentity:guardian",
                "name": "Guardian / Safety",
                "keywords": ["sécurité", "risque", "permission", "danger", "erreur"],
                "gate": 1.0,
            },
        }
        self.hypotheses: List[Dict[str, Any]] = []

    def evaluate_coalition_bids(
        self, context_text: str
    ) -> List[WorkspaceBid]:
        bids = []
        lowered = context_text.lower()

        for sid, meta in self.registered_subentities.items():
            kws = meta["keywords"]
            hits = sum(1 for kw in kws if kw in lowered)
            if hits > 0:
                score = (hits / len(kws)) * meta["gate"]
                bid = WorkspaceBid(
                    subentity_id=sid,
                    perceived_problem=f"Context matches {meta['name']}",
                    proposed_content=f"Focus on {meta['name']} perspective",
                    bid_score=score,
                )
                bids.append(bid)

        bids.sort(key=lambda b: b.bid_score, reverse=True)
        return bids

    def arbitrate_captain(
        self, bids: List[WorkspaceBid], current_regime: str
    ) -> Dict[str, Any]:
        """Integrated Captain arbitration function."""
        if not bids:
            return {
                "active_controller": "subentity:architect",
                "selected_bid": None,
                "competing_bids_count": 0,
                "reason": "default_fallback",
            }

        winning_bid = bids[0]

        if current_regime in ("DEPLETED", "OVERLOADED") and winning_bid.subentity_id == "subentity:puer":
            guardian_bids = [b for b in bids if b.subentity_id == "subentity:guardian"]
            if guardian_bids:
                winning_bid = guardian_bids[0]

        return {
            "active_controller": winning_bid.subentity_id,
            "selected_bid": winning_bid.to_dict(),
            "competing_bids_count": len(bids),
            "reason": "captain_arbitration_success",
        }
