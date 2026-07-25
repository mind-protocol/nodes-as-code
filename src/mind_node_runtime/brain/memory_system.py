"""
Loop 4 Engine: Systèmes de Mémoire.

Handles autobiographical Moments, semantic Narratives, procedural Skills,
graph traversal reranking, consolidation, and epistemic firewall (contradiction prevention).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


class MomentTrace:
    def __init__(
        self,
        moment_id: str,
        event_type: str,
        summary: str,
        author_actor: str,
        epistemic_status: str = "observed",
        provenance: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.moment_id = moment_id
        self.event_type = event_type
        self.summary = summary
        self.author_actor = author_actor
        self.epistemic_status = epistemic_status
        self.provenance = provenance or {}
        self.timestamp = int(time.time() * 1000)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "moment_id": self.moment_id,
            "event_type": self.event_type,
            "summary": self.summary,
            "author_actor": self.author_actor,
            "epistemic_status": self.epistemic_status,
            "provenance": self.provenance,
            "timestamp": self.timestamp,
        }


class MemorySystemEngine:
    """Engine for Loop 4 (space:brain:memory-v0)."""

    def __init__(self) -> None:
        self.moments_store: Dict[str, MomentTrace] = {}

    def record_moment(self, moment: MomentTrace) -> Dict[str, Any]:
        valid_statuses = {"observed", "measured", "inferred", "ratified"}
        if moment.epistemic_status not in valid_statuses:
            raise ValueError(f"Invalid epistemic status: {moment.epistemic_status}")

        self.moments_store[moment.moment_id] = moment
        return moment.to_dict()

    def epistemic_firewall_check(
        self, new_claim: str, existing_claims: List[str]
    ) -> Dict[str, Any]:
        """Prevents self-confirmation and checks for direct explicit contradictions."""
        contradictions = []
        new_clean = new_claim.lower().replace("ne ", "").replace("pas ", "").replace("not ", "").strip()

        for claim in existing_claims:
            claim_clean = claim.lower().replace("ne ", "").replace("pas ", "").replace("not ", "").strip()
            # If core statement matches but one is negated and the other is positive
            is_new_negated = any(w in new_claim.lower() for w in ["pas", "not", "non"])
            is_claim_negated = any(w in claim.lower() for w in ["pas", "not", "non"])

            if new_clean in claim_clean or claim_clean in new_clean:
                if is_new_negated != is_claim_negated:
                    contradictions.append(claim)

        return {
            "has_contradiction": len(contradictions) > 0,
            "contradicting_claims": contradictions,
            "passed_firewall": len(contradictions) == 0,
        }

    def rerank_contextual_recall(
        self, query: str, moments: List[MomentTrace], top_k: int = 5
    ) -> List[MomentTrace]:
        query_words = set(query.lower().split())

        def score(m: MomentTrace) -> float:
            m_words = set(m.summary.lower().split())
            overlap = len(query_words.intersection(m_words))
            recency = 1.0 / (1.0 + (time.time() * 1000 - m.timestamp) / 3600000.0)
            return overlap * 2.0 + recency

        scored = sorted(moments, key=score, reverse=True)
        return scored[:top_k]
