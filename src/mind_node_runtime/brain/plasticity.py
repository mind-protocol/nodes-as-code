"""
Loop 8 Engine: Apprentissage et Plasticité.

Slow associative weight modification (Phi), prediction error calculation,
behavior pattern reinforcement (REINFORCES) or weakening (WEAKENS), and procedural compilation.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


class BehaviorPattern:
    def __init__(
        self, pattern_id: str, name: str, weight: float = 0.5, execution_count: int = 0
    ) -> None:
        self.pattern_id = pattern_id
        self.name = name
        self.weight = max(0.0, min(1.0, weight))
        self.execution_count = execution_count

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "name": self.name,
            "weight": round(self.weight, 4),
            "execution_count": self.execution_count,
        }


class PlasticityEngine:
    """Engine for Loop 8 (space:brain:plasticity-v0)."""

    def __init__(self, learning_rate: float = 0.05) -> None:
        self.learning_rate = learning_rate
        self.patterns: Dict[str, BehaviorPattern] = {}

    def compute_prediction_error(
        self, expected_outcome: float, actual_outcome: float
    ) -> float:
        return actual_outcome - expected_outcome

    def update_pattern_weight(
        self, pattern: BehaviorPattern, expected: float, actual: float
    ) -> Dict[str, Any]:
        error = self.compute_prediction_error(expected, actual)
        delta = self.learning_rate * error
        old_weight = pattern.weight
        pattern.weight = max(0.0, min(1.0, pattern.weight + delta))
        pattern.execution_count += 1
        self.patterns[pattern.pattern_id] = pattern

        relation = "REINFORCES" if delta > 0 else "WEAKENS"
        return {
            "pattern_id": pattern.pattern_id,
            "old_weight": round(old_weight, 4),
            "new_weight": round(pattern.weight, 4),
            "prediction_error": round(error, 4),
            "relation": relation,
        }

    def check_compilation_eligibility(
        self, pattern: BehaviorPattern, threshold_count: int = 10, threshold_weight: float = 0.8
    ) -> bool:
        return pattern.execution_count >= threshold_count and pattern.weight >= threshold_weight
