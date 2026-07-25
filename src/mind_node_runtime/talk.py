"""
MCP Talk Capability Execution Handler.

Writes incoming stimulus Moment nodes directly into the dedicated Membrane
graph database (default: mind_membrane_v0), enforcing physical database isolation.

Before a stimulus is written, the requested recipient is resolved against the
membrane's actor registry. When the recipient is *known_absent* the handler does
NOT invent a delivery: it returns a structured `recipient_not_found` result that
suggests reachable recipients, ranked both by name similarity and by the actor
clusters that actually exist in the membrane graph.
"""

from __future__ import annotations

import os
import re
import time
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from .config import Settings
from .graph import GraphStore


# --------------------------------------------------------------------------- #
# Recipient resolution helpers                                                #
# --------------------------------------------------------------------------- #
def _normalize(text: str) -> str:
    """Lowercase and strip everything but alphanumerics (so `actor-nlr-ai`,
    `actor:citizen:nlr_ai`, and `NLR_AI` all become comparable)."""
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", str(text or "").lower()) if t}


def _similarity(requested: str, candidate_id: str, candidate_name: Optional[str]) -> float:
    """Blended [0,1] similarity between the requested target and a candidate.

    Combines a character-level ratio on the normalized strings with a
    token-overlap (Jaccard) score, taken against both the candidate id and its
    human-readable name. The best signal wins so that e.g. `actor-nlr-ai`
    strongly matches `actor:citizen:nlr_ai` even though the middle segment
    differs."""
    req_norm = _normalize(requested)
    req_tokens = _tokens(requested)

    best = 0.0
    for field in (candidate_id, candidate_name):
        if not field:
            continue
        seq = SequenceMatcher(None, req_norm, _normalize(field)).ratio()
        cand_tokens = _tokens(field)
        jaccard = (
            len(req_tokens & cand_tokens) / len(req_tokens | cand_tokens)
            if (req_tokens | cand_tokens)
            else 0.0
        )
        best = max(best, seq, jaccard)
    return round(best, 3)


def _membrane_actors(store: GraphStore) -> List[Dict[str, Any]]:
    rows = store.read(
        """
        MATCH (a)
        WHERE a.node_type='actor'
        RETURN a.id, a.name, a.subtype
        ORDER BY a.id
        """
    )
    return [{"id": r[0], "name": r[1], "subtype": r[2]} for r in rows]


def _membrane_clusters(store: GraphStore) -> List[Dict[str, Any]]:
    """Group membrane actors by the Space that bounds them (BOUNDS_ACTOR).

    Each returned cluster is a real subgraph of the membrane, so the caller can
    pick a recipient that shares a boundary context with what they intended."""
    rows = store.read(
        """
        MATCH (s)-[:BOUNDS_ACTOR]->(a)
        WHERE s.node_type='space' AND a.node_type='actor'
        RETURN s.id, s.name, a.id, a.name
        ORDER BY s.id, a.id
        """
    )
    clusters: Dict[str, Dict[str, Any]] = {}
    for space_id, space_name, actor_id, actor_name in rows:
        cluster = clusters.setdefault(
            space_id, {"spaceId": space_id, "spaceName": space_name, "members": []}
        )
        cluster["members"].append({"id": actor_id, "name": actor_name})
    return list(clusters.values())


def _recipient_not_found(
    store: GraphStore,
    *,
    requested_target: str,
    sender_id: str,
    membrane_space_id: str,
    now: int,
    max_suggestions: int = 5,
) -> Dict[str, Any]:
    actors = _membrane_actors(store)
    clusters = _membrane_clusters(store)

    scored = sorted(
        (
            {
                "id": a["id"],
                "name": a["name"],
                "subtype": a["subtype"],
                "score": _similarity(requested_target, a["id"], a["name"]),
            }
            for a in actors
        ),
        key=lambda s: s["score"],
        reverse=True,
    )
    suggestions_by_name = scored[:max_suggestions]

    # Human-readable summary the caller (or an LLM) can relay directly.
    if suggestions_by_name:
        name_hint = "; ".join(
            f"{s['id']}"
            + (f" ({s['name']})" if s["name"] else "")
            + f" [{s['score']:.2f}]"
            for s in suggestions_by_name
        )
    else:
        name_hint = "aucun acteur enregistré dans la membrane"

    if clusters:
        cluster_hint = " | ".join(
            f"{c['spaceName'] or c['spaceId']}: "
            + ", ".join(m["id"] for m in c["members"])
            for c in clusters
        )
    else:
        cluster_hint = "aucun cluster (BOUNDS_ACTOR) dans la membrane"

    human_message = (
        f"Destinataire introuvable : '{requested_target}' n'existe pas dans la membrane "
        f"(statut épistémique : known_absent). Aucun stimulus n'a été écrit. "
        f"Destinataires proches par nom → {name_hint}. "
        f"Clusters de la membrane → {cluster_hint}."
    )

    return {
        "status": "recipient_not_found",
        "epistemic_status": "known_absent",
        "membraneGraph": store.graph.name,
        "membraneSpaceId": membrane_space_id,
        "senderActorId": sender_id,
        "requestedTargetActorId": requested_target,
        "stimulusWritten": False,
        "message": human_message,
        "suggestionsByName": suggestions_by_name,
        "suggestionsByCluster": clusters,
        "timestamp": now,
    }


# --------------------------------------------------------------------------- #
# Talk execution                                                              #
# --------------------------------------------------------------------------- #
def execute_talk(
    store: Optional[GraphStore] = None,
    *,
    message: str,
    senderActorId: str = "human:user",
    targetActorId: str = "actor:citizen:l1",
    membraneSpaceId: str = "space:membrane:l1-boundary-v0",
    membraneGraphName: Optional[str] = None,
) -> Dict[str, Any]:
    if not message or not message.strip():
        raise ValueError("Message content cannot be empty")

    graph_name = membraneGraphName or os.getenv("MEMBRANE_GRAPH", "mind_membrane_v0")
    membrane_store = store or GraphStore(Settings(graph_name=graph_name))

    now = int(time.time() * 1000)

    # 1. Resolve the recipient against the membrane's actor registry. A missing
    #    recipient is a known_absent, not a silent success.
    target_rows = membrane_store.read(
        "MATCH (t:RuntimeNode {id:$id}) WHERE t.node_type='actor' RETURN t.id LIMIT 1",
        {"id": targetActorId},
    )
    if not target_rows:
        return _recipient_not_found(
            membrane_store,
            requested_target=targetActorId,
            sender_id=senderActorId,
            membrane_space_id=membraneSpaceId,
            now=now,
        )

    # 2. Recipient exists — write the pending stimulus across the membrane.
    stimulus_moment_id = f"moment:stimulus:{now}"

    membrane_store.write(
        """
        MATCH (membrane:RuntimeNode {id:$membrane_id})
        MATCH (target:RuntimeNode {id:$target_id})

        MERGE (stimulus:RuntimeNode {id:$stimulus_id})
        SET stimulus.node_type='moment',
            stimulus.subtype='membrane_stimulus',
            stimulus.name='Membrane Stimulus Moment',
            stimulus.content=$message,
            stimulus.author_actor=$sender_id,
            stimulus.epistemic_status='observed',
            stimulus.stimulus_status='pending',
            stimulus.created_at=$now

        MERGE (membrane)-[:CONTAINS_STIMULUS]->(stimulus)
        MERGE (stimulus)-[:TARGETS_ACTOR]->(target)

        RETURN stimulus.id
        """,
        {
            "membrane_id": membraneSpaceId,
            "target_id": targetActorId,
            "stimulus_id": stimulus_moment_id,
            "message": message.strip(),
            "sender_id": senderActorId,
            "now": now,
        },
    )

    return {
        "status": "success",
        "epistemic_status": "observed",
        "membraneGraph": membrane_store.graph.name,
        "stimulusMomentId": stimulus_moment_id,
        "membraneSpaceId": membraneSpaceId,
        "senderActorId": senderActorId,
        "targetActorId": targetActorId,
        "stimulusWritten": True,
        "messageSnippet": message[:60],
        "stimulusStatus": "pending",
        "timestamp": now,
    }
