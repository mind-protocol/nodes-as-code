from __future__ import annotations

import json
import time
import uuid
from typing import Any

from .graph import GraphStore


def canonical_event_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def emit_event(
    store: GraphStore,
    *,
    event_type: str,
    target_id: str,
    source_actor_id: str = "actor-nlr",
    payload: dict[str, Any] | None = None,
) -> str:
    event_id = f"event:{uuid.uuid4()}"
    rows = store.write(
        """
        MATCH (target {id:$target_id})
        CREATE (event:RuntimeNode {
            id:$event_id,
            node_type:'moment',
            subtype:'graph_event',
            status:'pending',
            event_type:$event_type,
            target_id:$target_id,
            source_actor_id:$source_actor_id,
            payload_json:$payload_json,
            occurred_at:$occurred_at
        })
        MERGE (event)-[:CONCERNS]->(target)
        RETURN event.id
        """,
        {
            "event_id": event_id,
            "event_type": event_type,
            "target_id": target_id,
            "source_actor_id": source_actor_id,
            "payload_json": canonical_event_payload(payload or {}),
            "occurred_at": int(time.time() * 1000),
        },
    )
    if not rows:
        raise KeyError(f"target not found: {target_id}")
    return str(rows[0][0])
