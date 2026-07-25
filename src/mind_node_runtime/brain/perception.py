"""
Loop 2 Engine: Sensation, Perception et Attention.

Atomizes sensory inputs into sourcetracked Percepts, senses pending stimuli
crossing the dedicated Membrane database boundary (mind_membrane_v0), calculates novelty,
and computes salience S = Energy * Weight * Novelty * Priority.
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any, Dict, List, Optional

from mind_node_runtime.config import Settings
from mind_node_runtime.graph import GraphStore


class PerceptAtom:
    def __init__(
        self,
        percept_id: str,
        source: str,
        content: str,
        energy: float = 1.0,
        priority: float = 1.0,
    ) -> None:
        self.percept_id = percept_id
        self.source = source
        self.content = content
        self.energy = max(0.0, energy)
        self.priority = max(0.1, priority)
        self.timestamp = int(time.time() * 1000)
        self.hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "percept_id": self.percept_id,
            "source": self.source,
            "content": self.content,
            "energy": round(self.energy, 2),
            "priority": round(self.priority, 2),
            "hash": self.hash,
            "timestamp": self.timestamp,
        }


class PerceptionEngine:
    """Engine for Loop 2 (space:brain:perception-v0)."""

    def __init__(self) -> None:
        self.seen_hashes: Dict[str, int] = {}

    def compute_novelty(self, percept: PerceptAtom) -> float:
        count = self.seen_hashes.get(percept.hash, 0)
        self.seen_hashes[percept.hash] = count + 1
        if count == 0:
            return 1.0
        return max(0.05, 1.0 / (count + 1))

    def compute_salience(
        self, percept: PerceptAtom, weight: float = 1.0, internal_demand: float = 0.5
    ) -> float:
        novelty = self.compute_novelty(percept)
        salience = percept.energy * weight * novelty * percept.priority * (1.0 + internal_demand)
        return round(salience, 4)

    def atomize(
        self, raw_input: str, source: str = "sensory_gateway:text"
    ) -> List[PerceptAtom]:
        chunks = [c.strip() for c in raw_input.split("\n") if c.strip()]
        percepts = []
        for i, chunk in enumerate(chunks):
            pid = f"percept:{int(time.time()*1000)}:{i}"
            percepts.append(PerceptAtom(pid, source, chunk))
        return percepts

    def sense_membrane_stimuli(
        self,
        membrane_store: Optional[GraphStore] = None,
        membrane_space_id: str = "space:membrane:l1-boundary-v0",
        citizen_id: str = "actor:citizen:l1",
        membrane_graph_name: Optional[str] = None,
    ) -> List[PerceptAtom]:
        """Senses pending stimulus nodes crossing the dedicated Membrane database boundary."""
        graph_name = membrane_graph_name or os.getenv("MEMBRANE_GRAPH", "mind_membrane_v0")
        store = membrane_store or GraphStore(Settings(graph_name=graph_name))

        now = int(time.time() * 1000)
        rows = store.read(
            """
            MATCH (membrane:RuntimeNode {id:$membrane_id})-[:CONTAINS_STIMULUS]->(stimulus:RuntimeNode {stimulus_status:'pending'})-[:TARGETS_ACTOR]->(citizen:RuntimeNode {id:$citizen_id})
            RETURN stimulus.id, stimulus.content, stimulus.author_actor
            """,
            {"membrane_id": membrane_space_id, "citizen_id": citizen_id},
        )

        perceived_atoms: List[PerceptAtom] = []

        for row in rows:
            stim_id, content, author = row[0], row[1], row[2]
            atoms = self.atomize(content, source=f"membrane_stimulus:{author}")
            perceived_atoms.extend(atoms)

            # Mark stimulus as consumed in the dedicated Membrane DB
            store.write(
                """
                MATCH (stimulus:RuntimeNode {id:$stim_id})
                SET stimulus.stimulus_status='consumed',
                    stimulus.consumed_at=$now
                """,
                {"stim_id": stim_id, "now": now},
            )

        return perceived_atoms
