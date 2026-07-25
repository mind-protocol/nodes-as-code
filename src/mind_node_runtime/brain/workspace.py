"""
Loop 3 Engine: Global Workspace et Mémoire de Travail.

Manages Global Workspace slot allocation (max 5 slots), competition based on heat/salience,
leader selection, secondary support slots, carryover memory (5 recent moments), episodic tail recall,
and Cognitive Wake threshold evaluation.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


class WorkspaceItem:
    def __init__(
        self, item_id: str, content: str, heat: float, source_type: str = "moment"
    ) -> None:
        self.item_id = item_id
        self.content = content
        self.heat = heat
        self.source_type = source_type
        self.monopolization_count = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "content": self.content,
            "heat": round(self.heat, 4),
            "source_type": self.source_type,
            "monopolization_count": self.monopolization_count,
        }


class GlobalWorkspaceEngine:
    """Engine for Loop 3 (space:brain:workspace-v0)."""

    def __init__(self, max_slots: int = 5, carryover_capacity: int = 5) -> None:
        self.max_slots = max_slots
        self.carryover_capacity = carryover_capacity
        self.active_slots: List[WorkspaceItem] = []
        self.carryover_moments: List[Dict[str, Any]] = []

    def submit_candidate(self, item: WorkspaceItem) -> bool:
        for existing in self.active_slots:
            if existing.item_id == item.item_id:
                existing.heat = max(existing.heat, item.heat)
                existing.monopolization_count += 1
                return True

        if len(self.active_slots) < self.max_slots:
            self.active_slots.append(item)
            return True

        min_item = min(self.active_slots, key=lambda x: x.heat - (x.monopolization_count * 0.1))
        effective_heat = item.heat
        if effective_heat > min_item.heat:
            self.active_slots.remove(min_item)
            self.active_slots.append(item)
            return True
        return False

    def select_leader(self) -> Optional[WorkspaceItem]:
        if not self.active_slots:
            return None
        leader = max(self.active_slots, key=lambda x: x.heat)
        leader.monopolization_count += 1
        return leader

    def check_wake_threshold(self, threshold: float = 1.0) -> Dict[str, Any]:
        """Evaluates whether accumulated physical heat triggers a Cognitive Wake Tick."""
        leader = self.select_leader()
        if not leader:
            return {"wake_triggered": False, "leader_heat": 0.0, "threshold": threshold}

        is_triggered = leader.heat >= threshold
        return {
            "wake_triggered": is_triggered,
            "leader_heat": round(leader.heat, 4),
            "threshold": threshold,
            "leader_item_id": leader.item_id,
            "leader_content": leader.content,
        }

    def push_carryover_moment(self, moment: Dict[str, Any]) -> None:
        self.carryover_moments.insert(0, moment)
        if len(self.carryover_moments) > self.carryover_capacity:
            self.carryover_moments.pop()

    def get_snapshot(self) -> Dict[str, Any]:
        leader = self.select_leader()
        return {
            "slots_count": len(self.active_slots),
            "max_slots": self.max_slots,
            "leader": leader.to_dict() if leader else None,
            "slots": [s.to_dict() for s in self.active_slots],
            "carryover_moments_count": len(self.carryover_moments),
            "carryover_moments": self.carryover_moments,
            "timestamp": int(time.time() * 1000),
        }
