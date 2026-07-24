from __future__ import annotations

import json
from typing import Any

from .graph import GraphStore


def _section(store: GraphStore, subtype: str, limit: int = 20) -> list[dict[str, Any]]:
    rows = store.read(
        """
        MATCH (n)
        WHERE n.subtype=$subtype
        RETURN n.id, n.status, n.event_type, n.target_id,
               n.executor_type, n.error_message, n.value_json
        ORDER BY coalesce(n.occurred_at, n.created_at, n.started_at, n.produced_at) DESC
        LIMIT $limit
        """,
        {"subtype": subtype, "limit": limit},
    )
    result = []
    for row in rows:
        value = row[6]
        result.append(
            {
                "id": row[0],
                "status": row[1],
                "eventType": row[2],
                "targetId": row[3],
                "executorType": row[4],
                "error": row[5],
                "value": json.loads(value) if value else None,
            }
        )
    return result


def snapshot(store: GraphStore) -> dict[str, Any]:
    return {
        "events": _section(store, "graph_event"),
        "intents": _section(store, "execution_intent"),
        "runs": _section(store, "evaluation_run"),
        "results": _section(store, "evaluation_result"),
        "schedules": _section(store, "schedule_policy"),
        "heartbeats": _section(store, "daemon_heartbeat"),
        "runtimeInstances": _section(store, "runtime_instance"),
        "problems": _section(store, "problem"),
        "health": _section(store, "health"),
    }
