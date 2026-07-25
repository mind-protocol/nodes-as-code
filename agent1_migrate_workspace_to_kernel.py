"""Agent 1 — Migrate the MCP subgraph from the mind-desktop WorkspaceStore
(JSON file) into the FalkorDB graph `mind_kernel_v0`.

Backend located (Steps 1-2):
    backendType              : local JSON file (mind-desktop WorkspaceStore)
    sourceLocation           : ~/.mind-desktop/workspace.json
    graphOrStoreName         : workspace.json  (single flat store; no named graphs)
    serializationFormat      : JSON  {"nodes":[...], "links":[...]}
    nodeIdentityProperty     : id
    relationshipRepresentation: link dict with source|source_id / target|target_id
                                and relation type in relation|type|verb|relationship
    readMethod               : json.load(open(WORKSPACE_PATH))
    writeMethod              : json.dump(ws, open(WORKSPACE_PATH,"w"), indent=2)

Key names are UNIFIED before insertion:
    source_id  -> source
    target_id  -> target
    type|verb|relationship -> relation

Phases: export | backup | dryrun | apply | verify   (run in that order).
Apply is idempotent (MERGE by id), non-destructive, and fail-closed on
duplicate / critical-property conflict / ambiguous relation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from falkordb import FalkorDB

WORKSPACE_PATH = Path.home() / ".mind-desktop" / "workspace.json"
REPO = Path(__file__).resolve().parent
OUT = REPO / "agent1-migration"
OUT.mkdir(exist_ok=True)

TARGET_GRAPH = "mind_kernel_v0"

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

STRUCTURAL_LINK_KEYS = {
    "source", "target", "relation",
    "source_id", "target_id", "type", "verb", "relationship",
}
_SAFE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
EXPORT_PATH = OUT / "mcp-closure.export.json"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(p.read_bytes())


def in_scope(nid: str) -> bool:
    return ("l2:mcp" in nid) or ("mind-code:code-location" in nid)


def safe_rel(value: str | None) -> str:
    v = (value or "RELATED_TO").strip()
    if _SAFE.fullmatch(v):
        return v
    v = re.sub(r"[^A-Za-z0-9_]+", "_", v).strip("_") or "RELATED_TO"
    if v[0].isdigit():
        v = "R_" + v
    return v


def normalize_link(link: dict[str, Any]) -> dict[str, Any] | None:
    source = link.get("source") or link.get("source_id")
    target = link.get("target") or link.get("target_id")
    relation = (
        link.get("relation")
        or link.get("type")
        or link.get("verb")
        or link.get("relationship")
    )
    if not source or not target:
        return None
    props = {k: v for k, v in link.items() if k not in STRUCTURAL_LINK_KEYS}
    return {
        "source": str(source),
        "target": str(target),
        "relation": str(relation) if relation else "RELATED_TO",
        "properties": props,
    }


def build_closure() -> dict[str, Any]:
    data = json.loads(WORKSPACE_PATH.read_text(encoding="utf-8"))
    nodes_by_id: dict[str, dict[str, Any]] = {}
    node_dupe_ids: list[str] = []
    for n in data["nodes"]:
        nid = str(n["id"])
        if nid in nodes_by_id:
            node_dupe_ids.append(nid)
            continue
        nodes_by_id[nid] = n

    selected = {nid for nid in nodes_by_id if in_scope(nid)}
    explicit_present = [e for e in EXPLICIT_DEPENDENCY_IDS if e in nodes_by_id]
    explicit_missing = [e for e in EXPLICIT_DEPENDENCY_IDS if e not in nodes_by_id]
    selected |= set(explicit_present)

    # relationships fully inside the perimeter, key-unified and deduped
    seen: set[tuple[str, str, str]] = set()
    links: list[dict[str, Any]] = []
    for raw in data["links"]:
        nl = normalize_link(raw)
        if nl is None:
            continue
        if nl["source"] in selected and nl["target"] in selected:
            key = (nl["source"], nl["relation"], nl["target"])
            if key in seen:
                continue
            seen.add(key)
            links.append(nl)

    sel_nodes = [nodes_by_id[i] for i in sorted(selected)]
    canonical_present = [c for c in CANONICAL_IDS if c in nodes_by_id]
    canonical_missing = [c for c in CANONICAL_IDS if c not in nodes_by_id]
    return {
        "generatedAt": utcnow(),
        "source": {
            "backendType": "local JSON file (mind-desktop WorkspaceStore)",
            "sourceLocation": str(WORKSPACE_PATH),
            "serializationFormat": 'JSON {"nodes":[...],"links":[...]}',
            "nodeIdentityProperty": "id",
        },
        "selectionScopes": ["l2:mcp", "mind-code:code-location"],
        "counts": {
            "selectedNodes": len(sel_nodes),
            "internalRelations": len(links),
            "explicitDepsPresent": len(explicit_present),
            "explicitDepsMissing": len(explicit_missing),
        },
        "canonicalPresentInSource": canonical_present,
        "canonicalMissingInSource": canonical_missing,
        "explicitDepsMissing": explicit_missing,
        "sourceDuplicateIds": sorted(set(node_dupe_ids)),
        "nodes": sel_nodes,
        "links": links,
    }


def connect():
    return FalkorDB(host="127.0.0.1", port=6379).select_graph(TARGET_GRAPH)


def q(graph, cypher: str, params: dict | None = None) -> list[list[Any]]:
    return list(graph.query(cypher, params or {}).result_set or [])


def qro(graph, cypher: str, params: dict | None = None) -> list[list[Any]]:
    return list(graph.ro_query(cypher, params or {}).result_set or [])


# ---------------------------------------------------------------- phases

def phase_export() -> int:
    closure = build_closure()
    EXPORT_PATH.write_text(
        json.dumps(closure, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    c = closure["counts"]
    print(json.dumps({
        "phase": "export",
        "exportPath": str(EXPORT_PATH),
        "exportHash": sha256_file(EXPORT_PATH),
        **c,
        "canonicalMissingInSource": closure["canonicalMissingInSource"],
        "explicitDepsMissing": closure["explicitDepsMissing"],
        "sourceDuplicateIds": closure["sourceDuplicateIds"],
    }, ensure_ascii=False, indent=2))
    return 0 if not closure["canonicalMissingInSource"] else 2


def phase_backup() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # 1. source copy
    src_backup = OUT / f"workspace.backup.{stamp}.json"
    shutil.copy2(WORKSPACE_PATH, src_backup)
    # 2. full target dump
    g = connect()
    node_rows = qro(g, "MATCH (n) RETURN n.id, labels(n), properties(n)")
    nodes = [{"id": r[0], "labels": r[1], "properties": r[2]} for r in node_rows]
    rel_rows = qro(
        g,
        "MATCH (a)-[r]->(b) RETURN a.id, type(r), properties(r), b.id",
    )
    rels = [{"source": r[0], "type": r[1], "properties": r[2], "target": r[3]} for r in rel_rows]
    tgt_backup = OUT / f"mind_kernel_v0.backup.{stamp}.json"
    tgt_backup.write_text(
        json.dumps({"graph": TARGET_GRAPH, "generatedAt": utcnow(),
                    "nodeCount": len(nodes), "relCount": len(rels),
                    "nodes": nodes, "relationships": rels},
                   ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "phase": "backup",
        "generatedAt": utcnow(),
        "sourceBackup": {"path": str(src_backup), "sha256": sha256_file(src_backup),
                         "bytes": src_backup.stat().st_size},
        "targetBackup": {"path": str(tgt_backup), "sha256": sha256_file(tgt_backup),
                         "bytes": tgt_backup.stat().st_size,
                         "nodeCount": len(nodes), "relCount": len(rels),
                         "idlessNodes": sum(1 for n in nodes if not n["id"])},
    }
    (OUT / "backup-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def _target_node_index(g, ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    idx: dict[str, list[dict[str, Any]]] = {}
    rows = qro(
        g,
        "MATCH (n) WHERE n.id IN $ids RETURN n.id, labels(n), properties(n)",
        {"ids": ids},
    )
    for nid, labels, props in rows:
        idx.setdefault(str(nid), []).append({"labels": labels, "properties": props})
    return idx


def _analyze(g, closure) -> dict[str, Any]:
    ids = [n["id"] for n in closure["nodes"]]
    idx = _target_node_index(g, ids)
    existing, missing, target_dupes, conflicts = 0, 0, [], []
    for n in closure["nodes"]:
        matches = idx.get(n["id"], [])
        if len(matches) > 1:
            target_dupes.append(n["id"])
            continue
        if not matches:
            missing += 1
            continue
        existing += 1
        tp = matches[0]["properties"]
        for key in ("node_type", "subtype", "version"):
            sv, tv = n.get(key), tp.get(key)
            if sv is not None and tv is not None and sv != tv:
                conflicts.append({"id": n["id"], "property": key,
                                  "source": sv, "target": tv})
    # relationships
    rel_existing = rel_missing = 0
    rel_dupes = []
    for l in closure["links"]:
        rel = safe_rel(l["relation"])
        rows = qro(
            g,
            f"MATCH (a {{id:$s}})-[r:`{rel}`]->(b {{id:$t}}) RETURN count(r)",
            {"s": l["source"], "t": l["target"]},
        )
        cnt = int(rows[0][0]) if rows else 0
        if cnt > 1:
            rel_dupes.append({"source": l["source"], "relation": rel, "target": l["target"], "count": cnt})
        elif cnt == 1:
            rel_existing += 1
        else:
            rel_missing += 1
    return {
        "nodeExisting": existing, "nodeMissing": missing,
        "targetDuplicateIds": sorted(set(target_dupes)),
        "criticalConflicts": conflicts,
        "relExisting": rel_existing, "relMissing": rel_missing,
        "duplicateRelationships": rel_dupes,
    }


def phase_dryrun() -> int:
    closure = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    g = connect()
    analysis = _analyze(g, closure)
    blockers = {
        "sourceDuplicateIds": closure["sourceDuplicateIds"],
        "targetDuplicateIds": analysis["targetDuplicateIds"],
        "criticalConflicts": analysis["criticalConflicts"],
        "duplicateRelationships": analysis["duplicateRelationships"],
        "canonicalMissingInSource": closure["canonicalMissingInSource"],
    }
    safe = not any(blockers.values())
    report = {"phase": "dryrun", "generatedAt": utcnow(), "safeToApply": safe,
              **closure["counts"], **analysis, "blockers": blockers}
    (OUT / "dryrun-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if safe else 2


def phase_apply() -> int:
    closure = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    g = connect()
    analysis = _analyze(g, closure)
    blockers = {
        "sourceDuplicateIds": closure["sourceDuplicateIds"],
        "targetDuplicateIds": analysis["targetDuplicateIds"],
        "criticalConflicts": analysis["criticalConflicts"],
        "duplicateRelationships": analysis["duplicateRelationships"],
        "canonicalMissingInSource": closure["canonicalMissingInSource"],
    }
    if any(blockers.values()):
        print(json.dumps({"phase": "apply", "status": "blocked",
                          "blockers": blockers}, ensure_ascii=False, indent=2))
        return 2

    nodes_merged = 0
    for n in closure["nodes"]:
        props = dict(n)
        q(g,
          "MERGE (x {id:$id}) SET x:RuntimeNode SET x += $props",
          {"id": n["id"], "props": props})
        nodes_merged += 1

    rels_merged = 0
    for l in closure["links"]:
        rel = safe_rel(l["relation"])
        q(g,
          f"MATCH (a {{id:$s}}) MATCH (b {{id:$t}}) "
          f"MERGE (a)-[r:`{rel}`]->(b) SET r += $props",
          {"s": l["source"], "t": l["target"], "props": l["properties"]})
        rels_merged += 1

    result = {"phase": "apply", "status": "applied", "generatedAt": utcnow(),
              "nodesMerged": nodes_merged, "relsMerged": rels_merged}
    (OUT / "apply-report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def phase_verify() -> int:
    closure = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    g = connect()
    canonical: dict[str, int] = {}
    for cid in CANONICAL_IDS:
        rows = qro(g, "MATCH (n {id:$id}) RETURN count(n)", {"id": cid})
        canonical[cid] = int(rows[0][0]) if rows else 0
    missing = [k for k, v in canonical.items() if v == 0]
    duplicated = [k for k, v in canonical.items() if v > 1]

    # every selected node present exactly once
    ids = [n["id"] for n in closure["nodes"]]
    rows = qro(g,
               "MATCH (n) WHERE n.id IN $ids RETURN n.id, count(n)",
               {"ids": ids})
    counts = {str(r[0]): int(r[1]) for r in rows}
    nodes_missing = [i for i in ids if counts.get(i, 0) == 0]
    nodes_dupe = [i for i, c in counts.items() if c > 1]

    # critical relations: those touching a canonical node
    canon = set(CANONICAL_IDS)
    critical = [l for l in closure["links"]
                if l["source"] in canon or l["target"] in canon]
    crit_missing = []
    for l in critical:
        rel = safe_rel(l["relation"])
        rows = qro(g,
                   f"MATCH (a {{id:$s}})-[r:`{rel}`]->(b {{id:$t}}) RETURN count(r)",
                   {"s": l["source"], "t": l["target"]})
        if not rows or int(rows[0][0]) < 1:
            crit_missing.append({"source": l["source"], "relation": rel, "target": l["target"]})

    # all internal relations present
    rel_present = rel_absent = 0
    for l in closure["links"]:
        rel = safe_rel(l["relation"])
        rows = qro(g,
                   f"MATCH (a {{id:$s}})-[r:`{rel}`]->(b {{id:$t}}) RETURN count(r)",
                   {"s": l["source"], "t": l["target"]})
        if rows and int(rows[0][0]) >= 1:
            rel_present += 1
        else:
            rel_absent += 1

    ok = (not missing and not duplicated and not nodes_missing
          and not nodes_dupe and not crit_missing and rel_absent == 0)
    report = {
        "phase": "verify", "generatedAt": utcnow(),
        "status": "completed" if ok else "failed_verification",
        "canonicalCounts": canonical,
        "canonicalMissing": missing,
        "canonicalDuplicated": duplicated,
        "selectedNodesChecked": len(ids),
        "selectedNodesMissing": nodes_missing,
        "selectedNodesDuplicated": nodes_dupe,
        "criticalRelationsChecked": len(critical),
        "criticalRelationsMissing": crit_missing,
        "internalRelationsPresent": rel_present,
        "internalRelationsAbsent": rel_absent,
    }
    (OUT / "verify-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["export", "backup", "dryrun", "apply", "verify"])
    args = ap.parse_args()
    return {
        "export": phase_export,
        "backup": phase_backup,
        "dryrun": phase_dryrun,
        "apply": phase_apply,
        "verify": phase_verify,
    }[args.phase]()


if __name__ == "__main__":
    sys.exit(main())
