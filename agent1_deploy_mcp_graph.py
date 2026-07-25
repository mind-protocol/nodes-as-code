from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from falkordb import FalkorDB


CANONICAL_IDS = [
    "space:l2:mcp:nodes-as-code-server-v0",
    "space:l2:mcp:graph-query-v0",
    "space:l2:mcp:runtime-activation-v0",
    "server:l2:mcp:nodes-as-code:v0",
    "contract:l2:mcp:graph-query-tool:v0",
    "capability:l2:mcp:graph-query-read-only:v0",
    "binding:l2:mcp:graph-query:v0",
    "code:l2:mcp:nodes-as-code-server:v0",
    "code:l2:mcp:graph-query-execution:v0",
]

EXPLICIT_DEPENDENCY_IDS = [
    "space:mind-meta:self-verifying-loop-v0",
    "code:mind-meta:type-definition-self-verifying-loop:v0",
    "space:mind-meta:evaluation-procedure-v0",
    "registry:mind-meta:evaluator-executors-v0",

    "space:mind-code:code-location-v0",
    "code:mind-code:type-definition-code-location:v0",
    "space:mind-code:code-definition-v0",
    "space:mind-code:materialization-v0",
    "space:mind-code:node-as-code-truth-v0",
    "code:mind-code:repository-code-materializer:v0",

    "space:mind-kernel:capability-v0",
    "space:mind-kernel:permission-effect-v0",
    "space:mind-kernel:changeset-v0",
    "space:mind-kernel:trigger-scheduler-v0",
    "code:mind-kernel:execution-worker:v0",
    "code:mind-kernel:runtime-daemon:v0",
    "code:mind-kernel:graph-scheduler:v0",
    "policy:mind-kernel:daemon-runtime-v0",

    "space:app:mcp_bridge",
    "space:l2:mind-connectors:mcp-bridge-availability-v0",

    "space:mind-runtime:stimulate-v0",
    "space:mind-runtime:propagate-v0",
]

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def safe_identifier(value: str, kind: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"Unsafe {kind}: {value!r}")
    return value


def connection() -> FalkorDB:
    kwargs: dict[str, Any] = {
        "host": os.environ.get("FALKOR_HOST", "127.0.0.1"),
        "port": int(os.environ.get("FALKOR_PORT", "6379")),
    }

    password = os.environ.get("FALKOR_PASSWORD")
    if password:
        kwargs["password"] = password

    return FalkorDB(**kwargs)


def query_rows(graph: Any, cypher: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
    result = graph.query(cypher, params or {})
    return list(result.result_set or [])


def load_source_nodes(source: Any) -> tuple[dict[str, dict[str, Any]], list[str]]:
    cypher = """
    MATCH (n)
    WHERE n.id IS NOT NULL
      AND (
        n.id CONTAINS 'l2:mcp'
        OR n.id CONTAINS 'mind-code:code-location'
        OR n.id IN $explicit_ids
      )
    RETURN n.id, labels(n), properties(n)
    ORDER BY n.id
    """

    rows = query_rows(
        source,
        cypher,
        {"explicit_ids": EXPLICIT_DEPENDENCY_IDS},
    )

    nodes: dict[str, dict[str, Any]] = {}
    duplicate_ids: list[str] = []

    for node_id, labels, properties in rows:
        node_id = str(node_id)

        if node_id in nodes:
            duplicate_ids.append(node_id)
            continue

        props = dict(properties or {})
        props["id"] = node_id

        nodes[node_id] = {
            "id": node_id,
            "labels": [str(label) for label in (labels or [])],
            "properties": props,
        }

    return nodes, sorted(set(duplicate_ids))


def load_source_relationships(source: Any, node_ids: list[str]) -> list[dict[str, Any]]:
    if not node_ids:
        return []

    cypher = """
    MATCH (a)-[r]->(b)
    WHERE a.id IN $ids AND b.id IN $ids
    RETURN a.id, type(r), properties(r), b.id
    ORDER BY a.id, type(r), b.id
    """

    rows = query_rows(source, cypher, {"ids": node_ids})

    return [
        {
            "source": str(source_id),
            "type": str(rel_type),
            "properties": dict(properties or {}),
            "target": str(target_id),
        }
        for source_id, rel_type, properties, target_id in rows
    ]


def inspect_target_node(target: Any, node_id: str) -> list[dict[str, Any]]:
    rows = query_rows(
        target,
        """
        MATCH (n {id:$id})
        RETURN labels(n), properties(n)
        """,
        {"id": node_id},
    )

    return [
        {
            "labels": list(labels or []),
            "properties": dict(properties or {}),
        }
        for labels, properties in rows
    ]


def inspect_target_relationship(
    target: Any,
    source_id: str,
    rel_type: str,
    target_id: str,
) -> int:
    rel_type = safe_identifier(rel_type, "relationship type")

    rows = query_rows(
        target,
        f"""
        MATCH (a {{id:$source_id}})-[r:`{rel_type}`]->(b {{id:$target_id}})
        RETURN count(r)
        """,
        {
            "source_id": source_id,
            "target_id": target_id,
        },
    )

    return int(rows[0][0]) if rows else 0


def merge_node(target: Any, node: dict[str, Any]) -> None:
    labels = [
        safe_identifier(label, "label")
        for label in node["labels"]
    ]

    label_clause = "".join(f":`{label}`" for label in labels)

    cypher = f"""
    MERGE (n {{id:$id}})
    SET n += $properties
    SET n{label_clause}
    """

    query_rows(
        target,
        cypher,
        {
            "id": node["id"],
            "properties": node["properties"],
        },
    )


def merge_relationship(target: Any, relationship: dict[str, Any]) -> None:
    rel_type = safe_identifier(
        relationship["type"],
        "relationship type",
    )

    cypher = f"""
    MATCH (a {{id:$source_id}})
    MATCH (b {{id:$target_id}})
    MERGE (a)-[r:`{rel_type}`]->(b)
    SET r += $properties
    """

    query_rows(
        target,
        cypher,
        {
            "source_id": relationship["source"],
            "target_id": relationship["target"],
            "properties": relationship["properties"],
        },
    )


def verify_canonical_ids(graph: Any) -> dict[str, int]:
    result: dict[str, int] = {}

    for node_id in CANONICAL_IDS:
        rows = query_rows(
            graph,
            """
            MATCH (n {id:$id})
            RETURN count(n)
            """,
            {"id": node_id},
        )

        result[node_id] = int(rows[0][0]) if rows else 0

    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--source",
        default=os.environ.get("FALKOR_SOURCE_GRAPH", "design"),
    )
    parser.add_argument(
        "--target",
        default=os.environ.get("FALKOR_TARGET_GRAPH", "mind_kernel_v0"),
    )
    parser.add_argument(
        "--report",
        default="agent1-mcp-deployment-report.json",
    )
    args = parser.parse_args()

    if args.source == args.target:
        raise SystemExit("Source and target graphs must differ.")

    db = connection()
    source = db.select_graph(args.source)
    target = db.select_graph(args.target)

    source_nodes, source_duplicate_ids = load_source_nodes(source)
    source_node_ids = sorted(source_nodes)

    relationships = load_source_relationships(
        source,
        source_node_ids,
    )

    missing_canonical_source = [
        node_id
        for node_id in CANONICAL_IDS
        if node_id not in source_nodes
    ]

    target_duplicates: list[str] = []
    version_conflicts: list[dict[str, Any]] = []
    existing_nodes = 0
    missing_nodes = 0

    for node_id, source_node in source_nodes.items():
        matches = inspect_target_node(target, node_id)

        if len(matches) > 1:
            target_duplicates.append(node_id)
            continue

        if not matches:
            missing_nodes += 1
            continue

        existing_nodes += 1

        source_version = source_node["properties"].get("version")
        target_version = matches[0]["properties"].get("version")

        if (
            source_version is not None
            and target_version is not None
            and source_version != target_version
        ):
            version_conflicts.append(
                {
                    "id": node_id,
                    "sourceVersion": source_version,
                    "targetVersion": target_version,
                }
            )

    duplicate_relationships: list[dict[str, Any]] = []
    existing_relationships = 0
    missing_relationships = 0

    for relationship in relationships:
        count = inspect_target_relationship(
            target,
            relationship["source"],
            relationship["type"],
            relationship["target"],
        )

        if count > 1:
            duplicate_relationships.append(
                {
                    "source": relationship["source"],
                    "type": relationship["type"],
                    "target": relationship["target"],
                    "count": count,
                }
            )
        elif count == 1:
            existing_relationships += 1
        else:
            missing_relationships += 1

    blockers = {
        "missingCanonicalSource": missing_canonical_source,
        "sourceDuplicateIds": source_duplicate_ids,
        "targetDuplicateIds": target_duplicates,
        "versionConflicts": version_conflicts,
        "duplicateRelationships": duplicate_relationships,
    }

    safe_to_apply = not any(blockers.values())

    report: dict[str, Any] = {
        "agent": "Agent 1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceGraph": args.source,
        "targetGraph": args.target,
        "mode": "apply" if args.apply else "dry_run",
        "safeToApply": safe_to_apply,
        "selection": {
            "idScopes": [
                "l2:mcp",
                "mind-code:code-location",
            ],
            "explicitDependencyCount": len(EXPLICIT_DEPENDENCY_IDS),
        },
        "source": {
            "nodeCount": len(source_nodes),
            "relationshipCount": len(relationships),
        },
        "targetBefore": {
            "existingNodeCount": existing_nodes,
            "missingNodeCount": missing_nodes,
            "existingRelationshipCount": existing_relationships,
            "missingRelationshipCount": missing_relationships,
        },
        "blockers": blockers,
        "applied": False,
        "targetCanonicalIds": {},
    }

    if args.apply:
        if not safe_to_apply:
            report["status"] = "blocked"
        else:
            for node_id in source_node_ids:
                merge_node(target, source_nodes[node_id])

            for relationship in relationships:
                merge_relationship(target, relationship)

            report["applied"] = True
            report["targetCanonicalIds"] = verify_canonical_ids(target)

            missing_after = [
                node_id
                for node_id, count in report["targetCanonicalIds"].items()
                if count != 1
            ]

            report["status"] = (
                "completed"
                if not missing_after
                else "failed_verification"
            )
            report["missingCanonicalAfterApply"] = missing_after
    else:
        report["status"] = (
            "dry_run_ready"
            if safe_to_apply
            else "dry_run_blocked"
        )

    Path(args.report).write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(json.dumps(report, indent=2, ensure_ascii=False))

    if not safe_to_apply:
        return 2

    if args.apply and report["status"] != "completed":
        return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
