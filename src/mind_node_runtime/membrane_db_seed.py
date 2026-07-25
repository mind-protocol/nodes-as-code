"""
Seed Script for Dedicated Membrane Graph Database (mind_membrane_v0).

Enforces physical database isolation for the Membrane boundary space,
preventing direct Cypher edges between external inputs and L1 internal cognitive graph.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict


def seed_membrane_db(store: Any) -> Dict[str, Any]:
    store.write(
        """
        MERGE (membrane:RuntimeNode {id:'space:membrane:l1-boundary-v0'})
        SET membrane.node_type='space',
            membrane.subtype='membrane_boundary',
            membrane.name='Membrane Boundary · Dedicated Membrane DB v0',
            membrane.status='active',
            membrane.content='Physically isolated membrane database receiving external stimuli for L1 Citizen AI.'

        MERGE (citizen:RuntimeNode {id:'actor:citizen:l1'})
        SET citizen.node_type='actor',
            citizen.subtype='citizen_ai',
            citizen.name='Primary L1 Citizen AI Reference',
            citizen.status='active'

        MERGE (membrane)-[:BOUNDS_ACTOR]->(citizen)
        """
    )
    return {
        "status": "success",
        "membrane_db": store.graph.name,
        "membrane_space": "space:membrane:l1-boundary-v0",
        "target_actor": "actor:citizen:l1",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed dedicated Membrane graph database (default: mind_membrane_v0).")
    parser.add_argument("--graph", default=os.getenv("MEMBRANE_GRAPH", "mind_membrane_v0"))
    args = parser.parse_args()

    from .config import Settings
    from .graph import GraphStore

    settings = Settings(graph_name=args.graph)
    store = GraphStore(settings)
    result = seed_membrane_db(store)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
