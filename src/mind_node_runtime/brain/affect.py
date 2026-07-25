"""
Loop 5 Engine: Besoins, Affects et Émotions.

Manages continuous multi-dimensional limbic state vector, emotional prototypes,
valence, threat detection, frustration evaluation, and homeostatic regulation strategies.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


class LimbicStateVector:
    def __init__(
        self,
        arousal: float = 0.5,
        valence: float = 0.0,
        dominance: float = 0.5,
        curiosity: float = 0.5,
        frustration: float = 0.0,
        threat_level: float = 0.0,
    ) -> None:
        self.arousal = max(0.0, min(1.0, arousal))
        self.valence = max(-1.0, min(1.0, valence))
        self.dominance = max(0.0, min(1.0, dominance))
        self.curiosity = max(0.0, min(1.0, curiosity))
        self.frustration = max(0.0, min(1.0, frustration))
        self.threat_level = max(0.0, min(1.0, threat_level))
        self.timestamp = int(time.time() * 1000)

    def determine_dominant_prototype(self) -> str:
        if self.threat_level > 0.5:
            return "fear_alert"
        if self.frustration > 0.5:
            return "frustration_pivot"
        if self.curiosity > 0.5 and self.valence >= 0.0:
            return "curiosity_exploration"
        if self.valence > 0.4 and self.arousal > 0.4:
            return "joy_engagement"
        if self.valence < -0.4 and self.arousal < 0.4:
            return "sadness_withdrawal"
        return "neutral_baseline"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "arousal": round(self.arousal, 2),
            "valence": round(self.valence, 2),
            "dominance": round(self.dominance, 2),
            "curiosity": round(self.curiosity, 2),
            "frustration": round(self.frustration, 2),
            "threat_level": round(self.threat_level, 2),
            "dominant_prototype": self.determine_dominant_prototype(),
            "timestamp": self.timestamp,
        }


class AffectEngine:
    """Engine for Loop 5 (space:brain:affect-v0)."""

    def __init__(self, initial_state: Optional[LimbicStateVector] = None) -> None:
        self.state = initial_state or LimbicStateVector()

    def update_from_percept_signal(
        self, signal: Dict[str, Any]
    ) -> LimbicStateVector:
        candidate = signal.get("candidate_signal", "")
        confidence = float(signal.get("confidence", 0.5))

        if candidate == "frustration":
            self.state.frustration = min(1.0, self.state.frustration + 0.6 * confidence)
            self.state.valence = max(-1.0, self.state.valence - 0.3 * confidence)
        elif candidate == "threat":
            self.state.threat_level = min(1.0, self.state.threat_level + 0.7 * confidence)
            self.state.arousal = min(1.0, self.state.arousal + 0.4 * confidence)
        elif candidate == "curiosity":
            self.state.curiosity = min(1.0, self.state.curiosity + 0.6 * confidence)
            self.state.valence = min(1.0, self.state.valence + 0.2 * confidence)

        self.state.timestamp = int(time.time() * 1000)
        return self.state

    def decay_towards_baseline(self, decay_factor: float = 0.1) -> LimbicStateVector:
        self.state.arousal += (0.5 - self.state.arousal) * decay_factor
        self.state.valence += (0.0 - self.state.valence) * decay_factor
        self.state.frustration = max(0.0, self.state.frustration - 0.1)
        self.state.threat_level = max(0.0, self.state.threat_level - 0.1)
        self.state.timestamp = int(time.time() * 1000)
        return self.state
