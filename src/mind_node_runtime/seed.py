from __future__ import annotations

import argparse
import json
import os

from .config import Settings


def default_objective_id(blueprint_id: str) -> str:
    if blueprint_id.startswith("space:"):
        return "objective:" + blueprint_id[len("space:") :] + ":primary"
    return f"objective:{blueprint_id}:primary"


def seed_blueprint(
    store,
    *,
    blueprint_id: str,
    name: str,
    objective_id: str,
    objective_name: str,
    objective_text: str,
    status: str = "planned",
) -> dict[str, str]:
    store.write(
        """
        MERGE (blueprint:RuntimeNode {id:$blueprint_id})
        SET blueprint.node_type='space',
            blueprint.subtype='ontology_module',
            blueprint.name=$name,
            blueprint.status=$status,
            blueprint.content=$blueprint_content

        MERGE (objective:RuntimeNode {id:$objective_id})
        SET objective.node_type='narrative',
            objective.subtype='objective',
            objective.name=$objective_name,
            objective.content=$objective_text

        MERGE (blueprint)-[:CONTAINS]->(objective)

        RETURN blueprint.id, objective.id
        """,
        {
            "blueprint_id": blueprint_id,
            "name": name,
            "status": status,
            "blueprint_content": (
                "Minimal ontology-module seed. The loop is intentionally incomplete and "
                "must be completed through graph-authorized Node-as-Code execution."
            ),
            "objective_id": objective_id,
            "objective_name": objective_name,
            "objective_text": objective_text,
        },
    )
    return {
        "blueprintId": blueprint_id,
        "objectiveId": objective_id,
        "status": status,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a minimal ontology-module Space and its Objective in a selected FalkorDB graph."
    )
    parser.add_argument("--graph", default=os.getenv("FALKOR_GRAPH", "mind_kernel_v0"))
    parser.add_argument("--id", required=True, dest="blueprint_id")
    parser.add_argument("--name", required=True)
    parser.add_argument("--status", default="planned")
    parser.add_argument("--objective-id")
    parser.add_argument("--objective-name", default="Primary objective")
    parser.add_argument("--objective", required=True, dest="objective_text")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    from .graph import GraphStore

    settings = Settings(graph_name=args.graph)
    store = GraphStore(settings)
    result = seed_blueprint(
        store,
        blueprint_id=args.blueprint_id,
        name=args.name,
        objective_id=args.objective_id or default_objective_id(args.blueprint_id),
        objective_name=args.objective_name,
        objective_text=args.objective_text,
        status=args.status,
    )
    print(json.dumps({"graph": args.graph, **result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
