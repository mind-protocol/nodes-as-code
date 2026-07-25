"""
Loop 1 Engine: Substrat, Énergie et Régulation (Metabolism).

Enforces energy conservation (I = E * W * P * G), calculates metabolic snapshots,
tracks fatigue/pain/hunger/recovery, and manages capacity regimes:
RESTORED, AVAILABLE, STRAINED, DEPLETED, OVERLOADED.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Literal

CapacityRegime = Literal["RESTORED", "AVAILABLE", "STRAINED", "DEPLETED", "OVERLOADED"]


class MetabolicStateSnapshot:
    def __init__(
        self,
        energy_pool: float = 100.0,
        fatigue: float = 0.0,
        pain: float = 0.0,
        hunger: float = 0.0,
        temperature: float = 37.0,
        recovery_rate: float = 5.0,
    ) -> None:
        self.energy_pool = max(0.0, min(100.0, energy_pool))
        self.fatigue = max(0.0, min(100.0, fatigue))
        self.pain = max(0.0, min(100.0, pain))
        self.hunger = max(0.0, min(100.0, hunger))
        self.temperature = temperature
        self.recovery_rate = recovery_rate
        self.timestamp = int(time.time() * 1000)

    def determine_regime(self) -> CapacityRegime:
        if self.energy_pool < 15.0 or self.fatigue > 85.0:
            return "DEPLETED"
        if self.energy_pool < 40.0 or self.fatigue > 60.0 or self.pain > 50.0:
            return "STRAINED"
        if self.energy_pool > 90.0 and self.fatigue < 10.0:
            return "RESTORED"
        if self.fatigue > 90.0 and self.pain > 70.0:
            return "OVERLOADED"
        return "AVAILABLE"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "energy_pool": round(self.energy_pool, 2),
            "fatigue": round(self.fatigue, 2),
            "pain": round(self.pain, 2),
            "hunger": round(self.hunger, 2),
            "temperature": round(self.temperature, 2),
            "recovery_rate": round(self.recovery_rate, 2),
            "regime": self.determine_regime(),
            "timestamp": self.timestamp,
        }


class MetabolismEngine:
    """Engine for Loop 1 (space:brain:metabolism-v0)."""

    def __init__(self, initial_snapshot: Optional[MetabolicStateSnapshot] = None) -> None:
        self.state = initial_snapshot or MetabolicStateSnapshot()

    def propagate_energy(
        self, input_energy: float, weight: float, polarity: float, gate: float
    ) -> float:
        """Energy propagation following I = E * W * P * G without energy creation."""
        clamped_weight = max(0.0, min(1.0, weight))
        clamped_polarity = max(-1.0, min(1.0, polarity))
        clamped_gate = max(0.0, min(1.0, gate))
        intensity = input_energy * clamped_weight * clamped_polarity * clamped_gate
        cost = abs(intensity) * 0.05
        self.state.energy_pool = max(0.0, self.state.energy_pool - cost)
        self.state.fatigue = min(100.0, self.state.fatigue + cost * 0.5)
        return intensity

    def recover(self, duration_minutes: float) -> MetabolicStateSnapshot:
        rested_energy = duration_minutes * self.state.recovery_rate
        self.state.energy_pool = min(100.0, self.state.energy_pool + rested_energy)
        self.state.fatigue = max(0.0, self.state.fatigue - rested_energy * 0.8)
        self.state.pain = max(0.0, self.state.pain - rested_energy * 0.3)
        self.state.timestamp = int(time.time() * 1000)
        return self.state

    def check_health() -> Dict[str, Any]:
        regime = self.state.determine_regime()
        status = "healthy" if regime in ("RESTORED", "AVAILABLE") else "degraded"
        if regime == "DEPLETED":
            status = "stale"
        return {
            "loop_id": "space:brain:metabolism-v0",
            "status": status,
            "regime": regime,
            "snapshot": self.state.to_dict(),
        }
