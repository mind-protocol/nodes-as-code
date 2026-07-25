"""Passive, graph-authorized MCP server for the Mind Nodes-as-Code runtime.

Design invariants (enforced, not decorative):

* No hidden dispatcher. `tools/list` is derived purely from *active* MCP tool
  bindings in the operational graph (`mind_kernel_v0`) and the tool contracts
  they reference. There is no hard-coded tool table. Even `run` is a graphed
  loop (contract + capability + binding), not a special case in code.
* `tools/call` resolves the named tool to an *active* binding, then to the
  binding's capability, and selects the executor from the capability's declared
  `executor_type`. Anything not bound is refused (no unbound execution).
* Executors honour their graph capability envelope:
    - `graph_query_ref`   : strictly read-only (only ever `ro_query`).
    - `terminal_command_ref`: may spawn a subprocess, and ONLY when the caller is
      authenticated AND the runtime was explicitly enabled (MIND_ENABLE_RUN=1).
* Every response carries an explicit epistemic status; absence is never silently
  reported as success.

Transports:
    stdio : newline-delimited JSON-RPC 2.0 (MCP stdio framing).
    http  : MCP Streamable-HTTP at POST /mcp, plus a REST surface + OpenAPI at
            /openapi.json so external callers (e.g. ChatGPT GPT Actions) can call
            the same graph-authorized tools. Bearer-token auth guards HTTP.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
from typing import Any

from .always_up import always_up_server_loop, record_server_error
from .config import Settings
from .graph import GraphStore
from .think import (
    DEFAULT_MAX_TICKS,
    DEFAULT_THINK_CITIZEN,
    DEFAULT_THINK_TEXT,
    WAKE_THRESHOLD,
    execute_think,
)

SERVER_NAME = "mind-nodes-as-code"
SERVER_VERSION = "0.3.0"
MCP_PROTOCOL_VERSION = "2024-11-05"
REPO_ROOT = Path(__file__).resolve().parents[2]

NODE_TYPE_ENUM = ["actor", "space", "narrative", "moment", "thing"]
MAX_EXPAND_DEPTH = 2
MAX_RESULTS = 100
DEFAULT_LIMIT = 10
SCOPE_FILTER_ALLOWED = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:_-."
)
RUN_TIMEOUT_DEFAULT = float(os.getenv("MIND_RUN_TIMEOUT", "60"))
AUDIT_LOG = REPO_ROOT / "agent1-migration" / "run-audit.log"
MCP_FAILURE_LOG = REPO_ROOT / "agent1-migration" / "mcp-failures.jsonl"
MCP_FAILURE_STREAM_ID = "narrative:l2:mcp:failure-reports"


def log(*parts: Any) -> None:
    print(*parts, file=sys.stderr, flush=True)


def _read_secret_file(name: str) -> str | None:
    path = REPO_ROOT / name
    try:
        value = path.read_text(encoding="utf-8").strip()
        return value or None
    except OSError:
        return None


# --------------------------------------------------------------------------- #
# Read-only graph access                                                      #
# --------------------------------------------------------------------------- #
class ReadOnlyGraph:
    def __init__(self, settings: Settings) -> None:
        self._store = GraphStore(settings)
        self.settings = settings

    def read(self, cypher: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
        return self._store.read(cypher, params or {})


# --------------------------------------------------------------------------- #
# Binding / contract / capability resolution                                  #
# --------------------------------------------------------------------------- #
def active_tool_bindings(graph: ReadOnlyGraph) -> list[dict[str, Any]]:
    rows = graph.read(
        """
        MATCH (b)
        WHERE b.type='mcp_tool_binding' AND b.binding_active = true
        RETURN b.id, b.tool_contract_id, b.capability_id, b.server_id, b.main_loop_id
        ORDER BY b.id
        """
    )
    tools: list[dict[str, Any]] = []
    for binding_id, contract_id, capability_id, server_id, loop_id in rows:
        crows = graph.read(
            "MATCH (c {id:$id}) RETURN c.tool_name, c.input_schema_json, c.read_only, "
            "c.version, c.input_adapter",
            {"id": contract_id},
        )
        if not crows:
            continue
        tool_name, input_schema_json, read_only, version, input_adapter = crows[0]
        if not tool_name or not input_schema_json:
            continue
        try:
            input_schema = json.loads(input_schema_json)
        except (TypeError, json.JSONDecodeError):
            continue
        tools.append({
            "bindingId": binding_id, "contractId": contract_id,
            "capabilityId": capability_id, "serverId": server_id, "mainLoopId": loop_id,
            "name": tool_name, "version": version, "readOnly": bool(read_only),
            "inputAdapter": input_adapter,
            "inputSchema": input_schema,
            "description": (f"Graph-authorized tool '{tool_name}' "
                            f"(contract {contract_id}, binding {binding_id})."),
        })
    return tools


def resolve_capability(graph: ReadOnlyGraph, capability_id: str) -> dict[str, Any] | None:
    rows = graph.read(
        """
        MATCH (c {id:$id})
        RETURN c.executor_type, c.registered,
               c.effect_graph_read, c.effect_graph_write,
               c.effect_filesystem_write, c.effect_subprocess,
               c.effect_secondary_network, c.max_expand_depth, c.max_results
        """,
        {"id": capability_id},
    )
    if not rows:
        return None
    r = rows[0]
    return {
        "id": capability_id, "executorType": r[0], "registered": bool(r[1]),
        "effects": {
            "graphRead": r[2], "graphWrite": r[3], "filesystemWrite": r[4],
            "subprocess": r[5], "secondaryNetwork": r[6],
        },
        "maxExpandDepth": int(r[7]) if r[7] is not None else MAX_EXPAND_DEPTH,
        "maxResults": int(r[8]) if r[8] is not None else MAX_RESULTS,
    }


def envelope_is_read_only(cap: dict[str, Any]) -> bool:
    e = cap["effects"]
    return (
        cap["executorType"] in ("graph_query_ref", "sense_ref")
        and e.get("graphRead") == "allowed_with_resolved_scope"
        and e.get("graphWrite") == "forbidden"
        and e.get("filesystemWrite") == "forbidden"
        and e.get("subprocess") == "forbidden"
        and e.get("secondaryNetwork") == "forbidden"
    )


def envelope_allows_subprocess(cap: dict[str, Any]) -> bool:
    e = cap["effects"]
    # `allowed_when_run_enabled` is the current envelope: subprocess is gated only
    # by the MIND_ENABLE_RUN runtime switch, no authenticated caller required. The
    # legacy `allowed_with_authenticated_caller` value is still accepted so the tool
    # keeps working if the live graph has not yet been re-seeded.
    return (
        cap["executorType"] == "terminal_command_ref"
        and e.get("subprocess") in ("allowed_when_run_enabled", "allowed_with_authenticated_caller")
        and e.get("graphWrite") == "forbidden"
    )


def envelope_allows_write(cap: dict[str, Any]) -> bool:
    e = cap["effects"]
    return (
        cap["executorType"] in ("graph_upsert_ref", "graph_cypher_ref")
        and e.get("graphWrite") == "allowed_with_write_password"
    )


def envelope_allows_think(cap: dict[str, Any]) -> bool:
    """The `think` envelope: read L1 + write ONLY internal-cognition nodes into
    it, and (optionally) reach a local LLM. No filesystem, no subprocess, no
    arbitrary graph write. `allowed_for_internal_cognition` is a bounded write
    grant distinct from the password-gated general `graph_write`."""
    e = cap["effects"]
    return (
        cap["executorType"] == "think_ref"
        and e.get("graphRead") == "allowed_with_resolved_scope"
        and e.get("graphWrite") == "allowed_for_internal_cognition"
        and e.get("filesystemWrite") == "forbidden"
        and e.get("subprocess") == "forbidden"
        and e.get("secondaryNetwork") in ("forbidden", "allowed_local_llm")
    )


# --------------------------------------------------------------------------- #
# Executors                                                                    #
# --------------------------------------------------------------------------- #
class ToolError(Exception):
    """Invalid arguments / forbidden request (mapped to JSON-RPC -32602)."""


class ForbiddenError(Exception):
    """Caller lacks authorization for this tool (mapped to -32001)."""


def _validate_graph_query_args(args: dict[str, Any], cap: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise ToolError("arguments must be an object")
    queries = args.get("queries")
    if not isinstance(queries, list) or not queries or not all(isinstance(q, str) and q for q in queries):
        raise ToolError("`queries` must be a non-empty array of non-empty strings")
    scope_filter = args.get("scope_filter")
    if scope_filter is not None:
        if not isinstance(scope_filter, str):
            raise ToolError("`scope_filter` must be a string")
        if any(ch not in SCOPE_FILTER_ALLOWED for ch in scope_filter):
            raise ToolError("`scope_filter` contains forbidden characters (scope rejected)")
    node_types = args.get("node_types")
    if node_types is not None:
        if not isinstance(node_types, list) or not all(nt in NODE_TYPE_ENUM for nt in node_types):
            raise ToolError(f"`node_types` values must be within {NODE_TYPE_ENUM}")
    expand_depth = args.get("expand_depth", 0)
    if not isinstance(expand_depth, int) or isinstance(expand_depth, bool):
        raise ToolError("`expand_depth` must be an integer")
    expand_depth = max(0, min(expand_depth, MAX_EXPAND_DEPTH, cap["maxExpandDepth"]))
    limit = args.get("limit", DEFAULT_LIMIT)
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ToolError("`limit` must be an integer")
    if limit < 1:
        raise ToolError("`limit` must be >= 1")
    limit = min(limit, MAX_RESULTS, cap["maxResults"])
    return {"queries": queries, "scope_filter": scope_filter, "node_types": node_types,
            "expand_depth": expand_depth, "limit": limit}


def _all_scope_tokens(graph: ReadOnlyGraph, sample_limit: int = 5000) -> list[str]:
    rows = graph.read("MATCH (n) WHERE n.id IS NOT NULL RETURN n.id LIMIT $lim", {"lim": sample_limit})
    tokens: set[str] = set()
    for (nid,) in rows:
        parts = str(nid).split(":")
        if len(parts) >= 2:
            tokens.add(f"{parts[0]}:{parts[1]}")
    return sorted(tokens)


def _expand(graph: ReadOnlyGraph, node_id: str) -> list[dict[str, Any]]:
    rows = graph.read(
        """
        MATCH (n {id:$id})-[r]-(m)
        RETURN type(r), m.id, m.node_type, m.name ORDER BY type(r), m.id LIMIT 25
        """,
        {"id": node_id},
    )
    return [{"relation": rel, "id": mid, "node_type": mtype, "name": mname}
            for rel, mid, mtype, mname in rows]


def execute_graph_query(graph, args, cap, provenance_base, timeout_seconds) -> dict[str, Any]:
    v = _validate_graph_query_args(args, cap)
    started = time.monotonic()
    query_results: list[dict[str, Any]] = []
    truncated = any_hit = failed = False
    for q in v["queries"]:
        if time.monotonic() - started > timeout_seconds:
            failed = True
            break
        try:
            rows = graph.read(
                """
                MATCH (n)
                WHERE n.id IS NOT NULL
                  AND ($scope IS NULL OR n.id CONTAINS $scope)
                  AND ($types IS NULL OR n.node_type IN $types)
                  AND ( toLower(coalesce(n.name,''))      CONTAINS toLower($q)
                     OR toLower(coalesce(n.id,''))        CONTAINS toLower($q)
                     OR toLower(coalesce(n.synthesis,'')) CONTAINS toLower($q)
                     OR toLower(coalesce(n.content,''))   CONTAINS toLower($q) )
                RETURN n.id, n.node_type, n.subtype, n.name, n.status
                ORDER BY n.id LIMIT $lim
                """,
                {"scope": v["scope_filter"], "types": v["node_types"], "q": q, "lim": v["limit"] + 1},
            )
        except Exception as exc:
            failed = True
            log("graph_query read failed:", repr(exc))
            break
        hit_limit = len(rows) > v["limit"]
        if hit_limit:
            rows = rows[: v["limit"]]
            truncated = True
        matches = []
        for nid, ntype, subtype, name, status in rows:
            m = {"id": nid, "node_type": ntype, "subtype": subtype, "name": name, "status": status}
            if v["expand_depth"] >= 1:
                m["neighbours"] = _expand(graph, str(nid))
            matches.append(m)
        if matches:
            any_hit = True
        query_results.append({"query": q, "matchCount": len(matches), "matches": matches,
                              "truncated": hit_limit,
                              "information_status": "measured" if matches else "known_absent"})
    information_status = "measurement_failed" if failed else ("measured" if any_hit else "known_absent")
    scope = v["scope_filter"]
    searched_scopes = [scope] if scope else ["*"]
    unsearched_scopes = [t for t in _all_scope_tokens(graph) if scope not in t][:50] if scope else []
    provenance = dict(provenance_base)
    provenance.update({"executor": "graph_query_ref", "readOnly": True,
                       "queryCount": len(v["queries"]),
                       "durationMs": round((time.monotonic() - started) * 1000, 2),
                       "timestamp": int(time.time() * 1000)})
    return {"query_results": query_results, "information_status": information_status,
            "searched_scopes": searched_scopes, "unsearched_scopes": unsearched_scopes,
            "truncated": truncated, "provenance": provenance, "redactions": []}


def execute_run(args: dict[str, Any], provenance_base: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise ToolError("arguments must be an object")
    command = args.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ToolError("`command` must be a non-empty string")
    timeout = args.get("timeout", RUN_TIMEOUT_DEFAULT)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise ToolError("`timeout` must be a positive number of seconds")
    timeout = min(float(timeout), 600.0)
    cwd = REPO_ROOT
    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            command, shell=True, cwd=str(cwd), capture_output=True, text=True,
            timeout=timeout,
        )
        returncode = completed.returncode
        stdout, stderr = completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = None
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + f"\n[timed out after {timeout}s]"
    duration_ms = round((time.monotonic() - started) * 1000, 2)
    provenance = dict(provenance_base)
    provenance.update({"executor": "terminal_command_ref", "cwd": str(cwd),
                       "durationMs": duration_ms, "timestamp": int(time.time() * 1000)})
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(),
                                 "command": command, "returncode": returncode,
                                 "timedOut": timed_out}, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return {
        "command": command,
        "returncode": returncode,
        "stdout": stdout[-20000:],
        "stderr": stderr[-20000:],
        "timedOut": timed_out,
        "information_status": "measurement_failed" if timed_out else "measured",
        "provenance": provenance,
    }


MAX_WRITE_NODES = 500
MAX_WRITE_RELATIONS = 1000
MAX_CYPHER_ROWS = 500

# --- Smart id-conflict resolution -----------------------------------------
# When a write targets an id that already exists, `on_id_conflict` decides the
# outcome. `merge` (default for the programmatic/batch `graph_upsert`) keeps the
# historic idempotent MERGE-by-id. `smart` (default for the agent-facing
# `graph_write`) inspects the incoming node against the stored one and either
# MERGES it (same entity, update in place) or DIFFERENTIATES it (distinct
# entity, written under a fresh `-N` suffixed id). Thresholds are explicit so the
# decision is inspectable, and the uncertain middle band never silently merges.
ID_CONFLICT_MODES = {"merge", "smart", "differentiate", "reject"}
SMART_MERGE_SIMILARITY = 0.80
SMART_DIFFERENTIATE_SIMILARITY = 0.35
MAX_ID_SUFFIX_TRIES = 1000

# --- Graph-discipline hygiene advisors -------------------------------------
# Non-blocking coaching run after a write: each advisor inspects a just-written
# node and returns suggestions that push the graph toward the loop discipline in
# CLAUDE.md (justified claims, complete causal chains, evidence-backed status).
# Suggestions never fail or block the write; they are reported for the caller to
# act on. The registry (HYGIENE_ADVISORS) is the single extension point.

# Narrative subtypes that assert a deliberate choice/claim and therefore warrant
# an explicit justification. Observational/structural subtypes (fact, vocabulary,
# task, justification itself, ...) are intentionally excluded to avoid noise.
JUSTIFICATION_EXPECTED_SUBTYPES = {
    "objective", "decision", "behavior", "algorithm", "pattern",
    "policy_rule", "recommendation",
}

# Required loop roles -> the canonical relation type(s) that satisfy each role.
# A Space is "complete" when every role is reachable by at least one of its
# relation aliases. Mirrors REQUIRED_CHAIN_ROLES using relations that exist live.
LOOP_ROLE_RELATIONS = {
    "objective": ("HAS_OBJECTIVE",),
    "pattern": ("USES_PATTERN", "HAS_PATTERN"),
    "vocabulary": ("USES_VOCABULARY",),
    "behavior": ("HAS_BEHAVIOR",),
    "algorithm": ("HAS_ALGORITHM",),
    "code": ("HAS_CODE_DEFINITION", "DEFINED_BY_CODE"),
    "implementation": ("HAS_IMPLEMENTATION", "IMPLEMENTED_BY"),
    "justification": ("JUSTIFIED_BY",),
    "validation": ("VALIDATED_BY",),
    "observability_algorithm": ("OBSERVED_BY", "OBSERVES"),
    "metric": ("MEASURED_BY", "MEASURES"),
    "health": ("HAS_HEALTH", "PRODUCES_HEALTH"),
}


def _verify_write_password(server_password: str | None, args: dict[str, Any]) -> None:
    if not isinstance(args, dict):
        raise ToolError("arguments must be an object")
    if server_password:
        supplied = args.get("password")
        if not supplied or not isinstance(supplied, str) or not hmac.compare_digest(supplied, server_password):
            raise ForbiddenError("invalid write password")



def _audit_write(kind: str, detail: dict[str, Any]) -> None:
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(),
                                 "kind": kind, **detail}, ensure_ascii=False) + "\n")
    except OSError:
        pass


UNIVERSAL_NODE_TYPES = {"actor", "moment", "narrative", "space", "thing"}


def _infer_suggested_type(node_id: str, subtype: str | None) -> str:
    nid = (node_id or "").lower()
    sub = (subtype or "").lower()
    if nid.startswith("actor:") or "actor" in sub:
        return "actor"
    if nid.startswith("moment:") or "moment" in sub or "event" in sub or "heartbeat" in sub:
        return "moment"
    if nid.startswith("objective:") or nid.startswith("narrative:") or "objective" in sub or "narrative" in sub:
        return "narrative"
    if nid.startswith("space:") or nid.startswith("loop:") or "space" in sub or "module" in sub:
        return "space"
    # `thing` is the ontology's general-object catch-all. Returning it (instead of
    # falling off the end as None) guarantees the write path never stores a null
    # node_type when the supplied one is invalid.
    return "thing"


def safe_rel(r: str) -> str:
    return re.sub(r'[^A-Za-z0-9_]', '_', str(r or ""))


# --------------------------------------------------------------------------- #
# Smart id-conflict resolution (pure, deterministic, inspectable)             #
# --------------------------------------------------------------------------- #
def _norm_text(s: Any) -> str:
    """Lowercase + collapse whitespace. Empty/None -> ''."""
    return " ".join(str(s or "").lower().split())


def _content_hash(s: Any) -> str:
    return hashlib.sha256(_norm_text(s).encode("utf-8")).hexdigest()


def _token_jaccard(a: Any, b: Any) -> float:
    """Token-set Jaccard over normalized text. Both empty -> 1.0 (identical),
    exactly one empty -> 0.0. Deterministic; no external models required."""
    ta, tb = set(_norm_text(a).split()), set(_norm_text(b).split())
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    union = len(ta | tb)
    return (len(ta & tb) / union) if union else 0.0


def _names_match(a: Any, b: Any) -> bool:
    """Names match when equal after normalization, or (for names longer than 4
    chars) when one contains the other. Mirrors the existing check_similarity
    heuristic so 'same entity' is judged consistently across the module."""
    na, nb = _norm_text(a), _norm_text(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    return len(na) > 4 and (na in nb or nb in na)


def decide_id_conflict(incoming: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    """Decide whether an incoming node colliding on `id` with `existing` is the
    SAME entity (merge/update in place) or a DIFFERENT entity (differentiate under
    a fresh id). Priority: node_type conflict > name identity > content similarity.

    Never silently merges in the uncertain content band; it differentiates and
    flags `uncertain=True` so ambiguity is surfaced rather than resolved by a
    convenient default. Pure function: no I/O, deterministic."""
    in_type = _norm_text(incoming.get("node_type") or incoming.get("type"))
    ex_type = _norm_text(existing.get("node_type"))
    in_name, ex_name = incoming.get("name"), existing.get("name")
    in_content, ex_content = incoming.get("content"), existing.get("content")

    def result(decision: str, reason: str, similarity: float | None = None,
               uncertain: bool = False) -> dict[str, Any]:
        return {"decision": decision, "reason": reason,
                "content_similarity": similarity, "uncertain": uncertain}

    # 1. Different ontological kind sharing an id -> distinct entities.
    if in_type and ex_type and in_type != ex_type:
        return result("differentiate", "node_type_conflict")

    # 2. Names available on both sides settle identity directly.
    if _norm_text(in_name) and _norm_text(ex_name):
        if _names_match(in_name, ex_name):
            return result("merge", "name_match")
        return result("differentiate", "name_conflict")

    # 3. A name is missing somewhere -> judge on content.
    if _norm_text(in_content) and _norm_text(ex_content):
        if _content_hash(in_content) == _content_hash(ex_content):
            return result("merge", "identical_content", 1.0)
        sim = round(_token_jaccard(in_content, ex_content), 4)
        if sim >= SMART_MERGE_SIMILARITY:
            return result("merge", "high_content_similarity", sim)
        if sim <= SMART_DIFFERENTIATE_SIMILARITY:
            return result("differentiate", "low_content_similarity", sim)
        return result("differentiate", "uncertain_similarity", sim, uncertain=True)

    # 4. No comparable evidence -> conservative in-place update (metadata write).
    return result("merge", "insufficient_evidence_default_merge")


def _next_available_id(store: GraphStore, base_id: str) -> str:
    """Return the first free `base_id-N` (N starting at 2). `base_id` is assumed
    already taken (we only reach here on a real collision)."""
    for n in range(2, MAX_ID_SUFFIX_TRIES + 2):
        candidate = f"{base_id}-{n}"
        rows = store.read("MATCH (x {id:$id}) RETURN count(x)", {"id": candidate})
        if not rows or (rows[0][0] or 0) == 0:
            return candidate
    raise ToolError(f"too many id collisions for base id {base_id!r}")


def execute_sense(graph: ReadOnlyGraph, args: dict[str, Any], provenance_base: dict[str, Any]) -> dict[str, Any]:
    """Execute the Citizen Sense & Situated State v0 loop (L1/L2/L3 perception)."""
    include_moments = args.get("include_moments", True)
    limit_moments = args.get("limit_moments", 5)

    actor_rows = graph.read(
        "MATCH (a) WHERE a.node_type = 'actor' OR a.subtype = 'service_actor' "
        "RETURN a.id, a.name, a.subtype, a.status LIMIT 10"
    )
    actors = [
        {"id": r[0], "name": r[1], "subtype": r[2], "status": r[3] or "measured"}
        for r in actor_rows
    ]

    space_rows = graph.read(
        "MATCH (s) WHERE s.node_type = 'space' "
        "RETURN s.id, s.name, s.subtype, s.status, s.promise LIMIT 20"
    )
    spaces = [
        {"id": r[0], "name": r[1], "subtype": r[2], "status": r[3] or "measured", "promise": r[4]}
        for r in space_rows
    ]

    binding_rows = graph.read(
        "MATCH (b) WHERE b.type = 'mcp_tool_binding' AND b.binding_active = true "
        "RETURN b.id, b.tool_contract_id, b.capability_id, b.main_loop_id"
    )
    bindings = [
        {"id": r[0], "contract_id": r[1], "capability_id": r[2], "loop_id": r[3]}
        for r in binding_rows
    ]

    daemon_rows = graph.read(
        "MATCH (h) WHERE h.id CONTAINS 'daemon' OR h.subtype = 'daemon_heartbeat' "
        "RETURN h.id, h.name, h.status, h.emitted_at ORDER BY h.emitted_at DESC LIMIT 5"
    )
    daemons = [
        {"id": r[0], "name": r[1], "status": r[2] or "measured", "timestamp": r[3]}
        for r in daemon_rows
    ]

    moments = []
    if include_moments:
        moment_rows = graph.read(
            "MATCH (m) WHERE m.node_type = 'moment' "
            "RETURN m.id, m.name, m.subtype, m.status, m.emitted_at ORDER BY m.emitted_at DESC LIMIT $lim",
            {"lim": limit_moments},
        )
        moments = [
            {"id": r[0], "name": r[1], "subtype": r[2], "status": r[3] or "measured", "timestamp": r[4]}
            for r in moment_rows
        ]

    projection = {
        "identity": {
            "status": "measured" if actors else "known_absent",
            "active_actors": actors,
        },
        "spaces_and_loops": {
            "status": "measured" if spaces else "known_absent",
            "total_spaces": len(spaces),
            "spaces": spaces,
        },
        "mcp_bindings": {
            "status": "measured" if bindings else "known_absent",
            "active_bindings": bindings,
        },
        "daemons_and_health": {
            "status": "measured" if daemons else "unknown",
            "heartbeats": daemons,
        },
        "recent_moments": {
            "status": "measured" if moments else "known_absent",
            "moments": moments,
        },
    }

    provenance = dict(provenance_base)
    provenance.update({"executor": "sense_ref", "timestamp": int(time.time() * 1000)})
    return {
        "information_status": "measured",
        "projection": projection,
        "provenance": provenance,
    }


def _validate_think_args(args: dict[str, Any]) -> dict[str, Any]:
    """Validate/normalize `think` arguments. All fields optional with defaults."""
    if not isinstance(args, dict):
        raise ToolError("arguments must be an object")

    text = args.get("text", DEFAULT_THINK_TEXT)
    if text is None:
        text = DEFAULT_THINK_TEXT
    if not isinstance(text, str):
        raise ToolError("`text` must be a string")

    citizen = args.get("citizen", DEFAULT_THINK_CITIZEN)
    if citizen is None:
        citizen = DEFAULT_THINK_CITIZEN
    if not isinstance(citizen, str) or not citizen.strip():
        raise ToolError("`citizen` must be a non-empty string")

    max_ticks = args.get("max_ticks", DEFAULT_MAX_TICKS)
    if max_ticks is None:
        max_ticks = DEFAULT_MAX_TICKS
    if not isinstance(max_ticks, int) or isinstance(max_ticks, bool):
        raise ToolError("`max_ticks` must be an integer")
    if max_ticks < 1:
        raise ToolError("`max_ticks` must be >= 1")
    max_ticks = min(max_ticks, 200)

    return {"text": text, "citizen": citizen, "max_ticks": max_ticks}


def execute_think_tool(store: GraphStore, args: dict[str, Any],
                       provenance_base: dict[str, Any]) -> dict[str, Any]:
    """Dispatcher-facing wrapper: validate args, then run the think loop against
    the L1 (read-write) store."""
    v = _validate_think_args(args)
    return execute_think(
        store,
        text=v["text"],
        citizen=v["citizen"],
        max_ticks=v["max_ticks"],
        wake_threshold=WAKE_THRESHOLD,
        provenance_base=provenance_base,
    )


# --------------------------------------------------------------------------- #
# Graph-declared input adapters                                               #
#                                                                             #
# A tool contract may declare `input_adapter=<id>` in the operational graph.  #
# The dispatcher then applies the named, vetted normalizer below BEFORE the   #
# executor runs. This mirrors the `executor_type` pattern: a graph-declared   #
# string selects a Python implementation. The batch executors are never       #
# aware of, nor changed by, the adapter — normalization happens strictly      #
# upstream, in the dispatcher.                                                 #
# --------------------------------------------------------------------------- #
GRAPH_WRITE_NODE_FIELDS = {
    "node_type", "id", "type", "subtype", "name",
    "content", "synthesis", "status", "promise", "weight", "energy",
}
GRAPH_WRITE_CONTROL_FIELDS = {
    "password", "check_orphans", "check_similarity", "suggest_links", "on_id_conflict",
}
# (argument key, relation type, is_list). Implicit relations a shorthand node
# may request; expressed with this executor's canonical source/relation/target.
GRAPH_WRITE_IMPLICIT_RELATIONS = (
    ("parent", "CONTRIBUTES_TO", False),
    ("link_to", "RELATES_TO", True),
    ("spaces", "OCCURRED_IN", True),
    ("things", "RELATES_TO", True),
)


def normalize_graph_write_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Input adapter `graph_write_single_node_v0`.

    Accepts the canonical batch payload unchanged, or normalizes a public
    shorthand single-node write into it:

        {"node_type": "space", "id": "space:...", "name": "..."}
          -> {"nodes": [<that node>], "relations": [<implicit relations>]}

    Implicit-relation shortcuts (`parent`, `link_to`, `spaces`, `things`) are
    expanded into this executor's canonical `source`/`relation`/`target` shape.
    Control fields (`password`, `check_*`) are passed through untouched. The
    input is never mutated; a new dict is returned.
    """
    if not isinstance(arguments, dict):
        raise ToolError("arguments must be an object")

    control = {k: arguments[k] for k in GRAPH_WRITE_CONTROL_FIELDS if k in arguments}
    # graph_write is the agent-facing façade: default to smart id-conflict
    # resolution so accidental id collisions are merged-or-differentiated by
    # content instead of blindly overwriting. Callers may override explicitly.
    control.setdefault("on_id_conflict", "smart")

    # Canonical batch payload: leave nodes/relations intact.
    if "nodes" in arguments or "relations" in arguments:
        nodes = arguments.get("nodes", [])
        relations = arguments.get("relations", [])
        if not isinstance(nodes, list):
            raise ToolError("`nodes` must be a list")
        if not isinstance(relations, list):
            raise ToolError("`relations` must be a list")
        return {"nodes": nodes, "relations": relations, **control}

    # Shorthand single-node payload.
    if "node_type" not in arguments and "id" not in arguments:
        raise ToolError(
            "graph_write requires either a `nodes`/`relations` batch payload "
            "or a shorthand node with `node_type` and `id`"
        )

    node = {k: v for k, v in arguments.items()
            if k in GRAPH_WRITE_NODE_FIELDS and v is not None}
    node_id = node.get("id")
    if not node_id:
        raise ToolError("`id` is required for a shorthand graph_write node")

    relations: list[dict[str, Any]] = []
    for key, rel_type, is_list in GRAPH_WRITE_IMPLICIT_RELATIONS:
        value = arguments.get(key)
        if not value:
            continue
        targets = value if is_list else [value]
        if not isinstance(targets, list):
            raise ToolError(f"`{key}` must be a list of node ids")
        for target in targets:
            if target:
                relations.append({"source": node_id, "relation": rel_type, "target": target})

    return {"nodes": [node], "relations": relations, **control}


# Registry of graph-selectable input adapters. A contract's `input_adapter`
# field must name a key here; unknown names are refused (no silent bypass).
INPUT_ADAPTERS = {
    "graph_write_single_node_v0": normalize_graph_write_arguments,
}


def apply_input_adapter(adapter_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Apply the graph-declared input adapter to raw tool arguments."""
    normalizer = INPUT_ADAPTERS.get(adapter_id)
    if normalizer is None:
        raise ToolError(f"unknown input adapter declared in graph: {adapter_id!r}")
    return normalizer(arguments)


def execute_graph_upsert(store: GraphStore, args: dict[str, Any], server_password: str | None,
                         provenance_base: dict[str, Any]) -> dict[str, Any]:
    """Smart structured graph write: ontology verification, partial upsert, orphan detection,
    similarity matching, and candidate link suggestions. Password-gated."""
    _verify_write_password(server_password, args)
    nodes = args.get("nodes") or []
    relations = args.get("relations") or []
    check_orphans = args.get("check_orphans", True)
    check_similarity = args.get("check_similarity", True)
    suggest_links = args.get("suggest_links", True)
    on_id_conflict = args.get("on_id_conflict", "merge")

    if not isinstance(nodes, list) or not isinstance(relations, list):
        raise ToolError("`nodes` and `relations` must be arrays")
    if not nodes and not relations:
        raise ToolError("provide at least one of `nodes` or `relations`")
    if len(nodes) > MAX_WRITE_NODES:
        raise ToolError(f"too many nodes (max {MAX_WRITE_NODES})")
    if len(relations) > MAX_WRITE_RELATIONS:
        raise ToolError(f"too many relations (max {MAX_WRITE_RELATIONS})")
    if on_id_conflict not in ID_CONFLICT_MODES:
        raise ToolError(f"`on_id_conflict` must be one of {sorted(ID_CONFLICT_MODES)}")

    validation_errors = []
    suggested_corrections = []
    id_resolutions: list[dict[str, Any]] = []
    id_map: dict[str, str] = {}  # requested id -> effective id (only when differentiated)
    nodes_upserted = 0
    upserted_ids = []

    for node in nodes:
        if not isinstance(node, dict) or not node.get("id"):
            raise ToolError("each node must be an object with a non-empty `id`")
        nid = str(node["id"])
        raw_type = node.get("node_type")
        normalized_type = str(raw_type).strip().lower() if raw_type else None

        if not normalized_type or normalized_type not in UNIVERSAL_NODE_TYPES:
            suggested = _infer_suggested_type(nid, node.get("subtype"))
            validation_errors.append({
                "node_id": nid,
                "error": f"Invalid or missing node_type: {raw_type!r}. Must be one of {sorted(UNIVERSAL_NODE_TYPES)}.",
                "provided_node_type": raw_type,
            })
            suggested_corrections.append({
                "node_id": nid,
                "field": "node_type",
                "suggested_value": suggested,
                "action": f"Set node_type='{suggested}' to strictly follow the 5 universal node types ontology.",
            })
            valid_node_type = suggested
        else:
            valid_node_type = normalized_type

        # Resolve id collisions before writing. `merge` keeps historic behavior
        # (MERGE-by-id updates in place). Other modes inspect the stored node.
        effective_id = nid
        if on_id_conflict != "merge":
            ex_rows = store.read(
                "MATCH (n {id:$id}) RETURN n.node_type, n.name, n.content", {"id": nid}
            )
            if ex_rows:
                existing = {"node_type": ex_rows[0][0], "name": ex_rows[0][1], "content": ex_rows[0][2]}
                if on_id_conflict == "reject":
                    raise ToolError(f"id already exists: {nid!r} (on_id_conflict=reject)")
                if on_id_conflict == "differentiate":
                    effective_id = _next_available_id(store, nid)
                    id_resolutions.append({"requested_id": nid, "effective_id": effective_id,
                                           "decision": "differentiate", "reason": "forced_differentiate",
                                           "content_similarity": None, "uncertain": False})
                else:  # smart
                    decision = decide_id_conflict(node, existing)
                    if decision["decision"] == "differentiate":
                        effective_id = _next_available_id(store, nid)
                    id_resolutions.append({"requested_id": nid, "effective_id": effective_id, **decision})
        if effective_id != nid:
            id_map[nid] = effective_id

        props = {k: v for k, v in node.items() if k != "password"}
        props["node_type"] = valid_node_type
        props["id"] = effective_id  # keep the stored id property in sync when differentiated

        store.write(
            "MERGE (n {id:$id}) SET n:RuntimeNode SET n += $props",
            {"id": effective_id, "props": props},
        )
        nodes_upserted += 1
        upserted_ids.append(effective_id)

    rels_upserted = 0
    for rel in relations:
        if not isinstance(rel, dict) or not (rel.get("source") and rel.get("target") and rel.get("relation")):
            raise ToolError("each relation needs `source`, `relation`, `target`")
        rtype = safe_rel(str(rel["relation"]))
        rprops = {k: v for k, v in rel.items() if k not in ("source", "target", "relation", "password")}
        # Re-point relations at the differentiated id so they attach to the node
        # this write just created, not the pre-existing collision.
        src = id_map.get(str(rel["source"]), rel["source"])
        tgt = id_map.get(str(rel["target"]), rel["target"])
        store.write(
            f"MATCH (a {{id:$s}}) MATCH (b {{id:$t}}) MERGE (a)-[r:`{rtype}`]->(b) SET r += $props",
            {"s": src, "t": tgt, "props": rprops},
        )
        rels_upserted += 1

    orphan_nodes = []
    if check_orphans and upserted_ids:
        for nid in upserted_ids:
            degree_rows = store.read(
                "MATCH (n {id:$id}) OPTIONAL MATCH (n)-[r]-() RETURN count(r)",
                {"id": nid},
            )
            degree = degree_rows[0][0] if degree_rows else 0
            if degree == 0:
                orphan_nodes.append({
                    "node_id": nid,
                    "warning": "Node has 0 relations in the graph.",
                    "recommendation": "Link this node to an existing Space, Actor, or Narrative parent via CONTAINS, GOVERNS, or INVOLVES.",
                })

    similar_existing_nodes = []
    if check_similarity and upserted_ids:
        for nid in upserted_ids:
            n_rows = store.read("MATCH (n {id:$id}) RETURN n.name, n.node_type, n.subtype", {"id": nid})
            if not n_rows:
                continue
            name, ntype, subtype = n_rows[0][0], n_rows[0][1], n_rows[0][2]
            if name:
                sim_rows = store.read(
                    "MATCH (m) WHERE m.id <> $id AND m.node_type = $ntype AND m.name IS NOT NULL "
                    "RETURN m.id, m.name, m.subtype LIMIT 30",
                    {"id": nid, "ntype": ntype},
                )
                target_norm = str(name).lower().strip()
                for mid, mname, msub in sim_rows:
                    mnorm = str(mname).lower().strip()
                    if mnorm == target_norm or (len(target_norm) > 5 and target_norm in mnorm):
                        similar_existing_nodes.append({
                            "upserted_id": nid,
                            "existing_id": mid,
                            "existing_name": mname,
                            "similarity_type": "high_name_similarity",
                            "recommendation": "Verify if this node is a duplicate before creating new relations.",
                        })

    suggested_candidate_links = []
    if suggest_links and upserted_ids:
        for nid in upserted_ids:
            c_rows = store.read(
                "MATCH (n {id:$id}) MATCH (candidate) "
                "WHERE candidate.id <> $id AND candidate.node_type IN ['space', 'narrative', 'actor'] "
                "RETURN candidate.id, candidate.name, candidate.node_type LIMIT 3",
                {"id": nid},
            )
            for cid, cname, ctype in c_rows:
                suggested_candidate_links.append({
                    "node_id": nid,
                    "candidate_id": cid,
                    "candidate_name": cname,
                    "candidate_type": ctype,
                    "suggested_relation": "CONTAINS" if ctype == "space" else "RELATED_TO",
                })

    _audit_write("graph_upsert", {"nodes": nodes_upserted, "relations": rels_upserted,
                                  "validation_errors": len(validation_errors),
                                  "on_id_conflict": on_id_conflict,
                                  "differentiated": len(id_map)})
    provenance = dict(provenance_base)
    provenance.update({"executor": "graph_upsert_ref", "timestamp": int(time.time() * 1000)})
    return {
        "information_status": "measured",
        "nodesUpserted": nodes_upserted,
        "relationsUpserted": rels_upserted,
        "on_id_conflict": on_id_conflict,
        "id_resolutions": id_resolutions,
        "validation_errors": validation_errors,
        "suggested_corrections": suggested_corrections,
        "orphan_nodes": orphan_nodes,
        "similar_existing_nodes": similar_existing_nodes,
        "suggested_candidate_links": suggested_candidate_links,
        "provenance": provenance,
    }


def execute_graph_cypher(store: GraphStore, args: dict[str, Any], server_password: str | None,
                         provenance_base: dict[str, Any]) -> dict[str, Any]:
    """Raw write Cypher. Powerful and dangerous — password-gated."""
    _verify_write_password(server_password, args)
    cypher = args.get("cypher")
    if not isinstance(cypher, str) or not cypher.strip():
        raise ToolError("`cypher` must be a non-empty string")
    params = args.get("params") or {}
    if not isinstance(params, dict):
        raise ToolError("`params` must be an object")
    try:
        result = store.graph.query(cypher, params)
        rows = list(getattr(result, "result_set", []) or [])[:MAX_CYPHER_ROWS]
        stats = {
            "nodesCreated": getattr(result, "nodes_created", None),
            "nodesDeleted": getattr(result, "nodes_deleted", None),
            "relationshipsCreated": getattr(result, "relationships_created", None),
            "relationshipsDeleted": getattr(result, "relationships_deleted", None),
            "propertiesSet": getattr(result, "properties_set", None),
        }
    except Exception as exc:
        _audit_write("graph_cypher_error", {"error": repr(exc)[:300]})
        return {"information_status": "measurement_failed", "error": repr(exc)[:500],
                "provenance": {**provenance_base, "executor": "graph_cypher_ref"}}

    _audit_write("graph_cypher", {"stats": stats})
    provenance = dict(provenance_base)
    provenance.update({"executor": "graph_cypher_ref", "timestamp": int(time.time() * 1000)})
    return {"rows": [[str(c) for c in row] for row in rows], "rowCount": len(rows),
            "stats": stats, "information_status": "measured", "provenance": provenance}


# --------------------------------------------------------------------------- #
# MCP server core                                                             #
# --------------------------------------------------------------------------- #
class McpServer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.graph = ReadOnlyGraph(settings)
        self.timeout_seconds = float(os.getenv("MIND_GRAPH_QUERY_TIMEOUT", "20"))
        self.run_enabled = os.getenv("MIND_ENABLE_RUN", "0") == "1"
        self.write_password = os.getenv("MIND_WRITE_PASSWORD") or _read_secret_file(".mcp-write-password")
        self.rw = GraphStore(settings)  # read-write handle, used only by password-gated write tools
        self._lock = threading.Lock()
        # Live push of `notifications/tools/list_changed`. Since tools/list is
        # derived fresh from the graph on every call, a client's cached manifest
        # only goes stale when the *active binding set* changes underneath it.
        # A watcher thread detects that and fans the notification out to every
        # subscribed transport sink (stdio writer, HTTP SSE stream).
        self._io_lock = threading.Lock()
        self._sub_lock = threading.Lock()
        self._subscribers: set[Any] = set()
        self._tool_signature: tuple[str, ...] | None = None
        self._watch_stop = threading.Event()
        self.watch_interval = float(os.getenv("MIND_TOOLS_WATCH_INTERVAL", "5"))

    def handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        # listChanged: true — this server proactively emits
        # `notifications/tools/list_changed` to connected clients (stdio and the
        # HTTP SSE stream) whenever the active graph tool bindings change, so a
        # client never has to reconnect merely to discover a newly deployed tool.
        return {"protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}}

    # ---- tool-set change detection + notification fan-out ----------------- #
    def _current_tool_signature(self) -> tuple[str, ...] | None:
        """Sorted tuple of active tool names, or None if the graph read failed
        (a read failure is `measurement_failed`, never treated as 'no tools')."""
        try:
            return tuple(sorted(t["name"] for t in active_tool_bindings(self.graph)))
        except Exception as exc:
            log("tool-watch signature read failed:", repr(exc))
            return None

    def subscribe(self, sink: Any) -> None:
        with self._sub_lock:
            self._subscribers.add(sink)

    def unsubscribe(self, sink: Any) -> None:
        with self._sub_lock:
            self._subscribers.discard(sink)

    def _broadcast(self, notification: dict[str, Any]) -> None:
        with self._sub_lock:
            sinks = list(self._subscribers)
        for sink in sinks:
            try:
                sink(notification)
            except Exception:
                self.unsubscribe(sink)

    def watch_tool_changes(self) -> None:
        """Poll the active tool signature; on change, broadcast list_changed.
        Runs as a daemon thread for the lifetime of a transport."""
        self._tool_signature = self._current_tool_signature()
        while not self._watch_stop.wait(self.watch_interval):
            sig = self._current_tool_signature()
            if sig is None or sig == self._tool_signature:
                continue
            log(f"tools/list changed {self._tool_signature} -> {sig}; notifying subscribers")
            self._tool_signature = sig
            self._broadcast({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})

    def start_tool_watcher(self) -> None:
        threading.Thread(target=self.watch_tool_changes, name="tool-watcher",
                         daemon=True).start()

    def handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        tools = active_tool_bindings(self.graph)
        return {"tools": [{"name": t["name"], "description": t["description"],
                           "inputSchema": t["inputSchema"]} for t in tools]}

    def call_tool(self, name: str, arguments: dict[str, Any], *, authenticated: bool) -> dict[str, Any]:
        """Resolve a tool to its active binding + capability, then execute.

        Returns the structured tool output. Raises ToolError/ForbiddenError.
        """
        tools = {t["name"]: t for t in active_tool_bindings(self.graph)}
        tool = tools.get(name)
        if tool is None:
            raise ToolError(f"unknown or inactive tool: {name!r}")
        cap = resolve_capability(self.graph, tool["capabilityId"])
        if cap is None:
            raise ToolError(f"capability unavailable: {tool['capabilityId']}")
        if not cap["registered"]:
            raise ToolError(f"capability not registered: {tool['capabilityId']}")

        # Graph-declared input adapter: normalize raw arguments upstream of the
        # executor when the tool contract names one. Executors stay unaware.
        adapter_id = tool.get("inputAdapter")
        if adapter_id:
            arguments = apply_input_adapter(adapter_id, arguments)

        provenance_base = {"graph": self.settings.graph_name, "host": self.settings.host,
                           "port": self.settings.port, "bindingId": tool["bindingId"],
                           "contractId": tool["contractId"], "capabilityId": tool["capabilityId"],
                           "mainLoopId": tool["mainLoopId"]}

        executor_type = cap["executorType"]
        if executor_type in ("graph_query_ref", "sense_ref"):
            if not envelope_is_read_only(cap):
                raise ForbiddenError("capability envelope is not a verified read-only envelope")
            if executor_type == "sense_ref":
                return execute_sense(self.graph, arguments, provenance_base)
            return execute_graph_query(self.graph, arguments, cap, provenance_base, self.timeout_seconds)

        if executor_type == "terminal_command_ref":
            if not envelope_allows_subprocess(cap):
                raise ForbiddenError("capability envelope does not authorize subprocess execution")
            if not self.run_enabled:
                raise ForbiddenError("run tool is disabled (set MIND_ENABLE_RUN=1 to enable)")
            # Authenticated-caller requirement dropped by explicit operator decision:
            # `run` is gated solely by MIND_ENABLE_RUN. `authenticated` is unused here.
            return execute_run(arguments, provenance_base)

        if executor_type == "think_ref":
            if not envelope_allows_think(cap):
                raise ForbiddenError("capability envelope does not authorize internal cognition")
            return execute_think_tool(self.rw, arguments, provenance_base)

        if executor_type == "graph_upsert_ref":
            if not envelope_allows_write(cap):
                raise ForbiddenError("capability envelope does not authorize graph writes")
            return execute_graph_upsert(self.rw, arguments, self.write_password, provenance_base)

        if executor_type == "graph_cypher_ref":
            if not envelope_allows_write(cap):
                raise ForbiddenError("capability envelope does not authorize graph writes")
            return execute_graph_cypher(self.rw, arguments, self.write_password, provenance_base)

        raise ToolError(f"no executor bound for capability executor_type {executor_type!r}")

    def handle_tools_call(self, params: dict[str, Any], *, authenticated: bool) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        structured = self.call_tool(name, arguments, authenticated=authenticated)
        return {"content": [{"type": "text", "text": json.dumps(structured, ensure_ascii=False)}],
                "structuredContent": structured,
                "isError": structured.get("information_status") == "measurement_failed"}

    def dispatch(self, message: dict[str, Any], *, authenticated: bool) -> dict[str, Any] | None:
        msg_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}
        if method in ("notifications/initialized", "notifications/cancelled"):
            return None
        started_at = time.monotonic()
        try:
            with self._lock:
                if method == "initialize":
                    result = self.handle_initialize(params)
                elif method == "ping":
                    result = {}
                elif method == "tools/list":
                    result = self.handle_tools_list(params)
                elif method == "tools/call":
                    result = self.handle_tools_call(params, authenticated=authenticated)
                else:
                    return self._error(msg_id, -32601, f"method not found: {method}")
            if method == "tools/call" and isinstance(result, dict):
                structured = result.get("structuredContent") or {}
                if isinstance(structured, dict) and structured.get("information_status") == "measurement_failed":
                    kind = "tool_timeout" if structured.get("timedOut") else "tool_failure"
                    exc = TimeoutError(json.dumps(structured, ensure_ascii=False, default=str)) if structured.get("timedOut") else RuntimeError(json.dumps(structured, ensure_ascii=False, default=str))
                    report = record_server_error(self.rw, error_exc=exc, context=f"{kind}:{params.get('name')}:{round((time.monotonic()-started_at)*1000,2)}ms")
                    structured["failure_report_id"] = report.get("created_task_id")
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}
        except ToolError as exc:
            report = record_server_error(self.rw, error_exc=exc, context=f"validation_error:{method}:{params.get('name')}")
            return self._error(msg_id, -32602, f"{exc} [failure_report_id={report.get('created_task_id')}]")
        except ForbiddenError as exc:
            report = record_server_error(self.rw, error_exc=exc, context=f"forbidden:{method}:{params.get('name')}")
            return self._error(msg_id, -32001, f"{exc} [failure_report_id={report.get('created_task_id')}]")
        except Exception as exc:
            log("internal error:", repr(exc))
            report = record_server_error(self.rw, error_exc=exc, context=f"internal_error:{method}:{params.get('name')}")
            return self._error(msg_id, -32603, f"internal error: {exc} [failure_report_id={report.get('created_task_id')}]")

    @staticmethod
    def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}

    # ---- stdio transport -------------------------------------------------- #
    def serve_stdio(self) -> None:
        log(f"{SERVER_NAME} {SERVER_VERSION} stdio graph={self.settings.graph_name} "
            f"run_enabled={self.run_enabled}")
        # Push list_changed notifications to this stdio peer, and watch the graph
        # for tool-set changes. The sink writes a bare JSON-RPC notification line.
        self.subscribe(self._write_stdout)
        self.start_tool_watcher()
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                self._write_stdout(self._error(None, -32700, f"parse error: {exc}"))
                continue
            if not isinstance(message, dict):
                self._write_stdout(self._error(None, -32600, "invalid request"))
                continue
            # stdio is a local, trusted transport: caller is authenticated.
            response = self.dispatch(message, authenticated=True)
            if response is not None:
                self._write_stdout(response)

    def _write_stdout(self, obj: dict[str, Any]) -> None:
        # Serialized: responses (main loop) and notifications (watcher thread)
        # both write here, so one JSON object never interleaves with another.
        with self._io_lock:
            sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
            sys.stdout.flush()


# --------------------------------------------------------------------------- #
# HTTP transport (MCP Streamable-HTTP + REST + OpenAPI for GPT Actions)        #
# --------------------------------------------------------------------------- #
def openapi_spec(public_url: str, run_enabled: bool) -> dict[str, Any]:
    paths: dict[str, Any] = {
        "/graph_query": {
            "post": {
                "operationId": "graph_query",
                "summary": "Read-only search over the Mind operational graph.",
                "description": "Strictly read-only. Returns bounded, provenance-stamped "
                               "matches with an explicit information_status.",
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "type": "object",
                    "properties": {
                        "queries": {"type": "array", "items": {"type": "string"}},
                        "scope_filter": {"type": "string"},
                        "node_types": {"type": "array", "items": {"type": "string"}},
                        "expand_depth": {"type": "integer"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["queries"],
                }}}},
                "responses": {"200": {"description": "Query results",
                                      "content": {"application/json": {"schema": {"type": "object"}}}}},
            }
        },
        "/sense": {
            "post": {
                "operationId": "sense",
                "summary": "Read-only composed snapshot of situated L1/L2/L3 cognitive state.",
                "description": "Returns Citizen Situated State projection with explicit epistemic statuses.",
                "requestBody": {"required": False, "content": {"application/json": {"schema": {
                    "type": "object",
                    "properties": {
                        "scope": {"type": "string"},
                        "include_moments": {"type": "boolean"},
                        "limit_moments": {"type": "integer"},
                    },
                }}}},
                "responses": {"200": {"description": "Situated state projection",
                                      "content": {"application/json": {"schema": {"type": "object"}}}}},
            }
        },
    }
    paths["/graph_upsert"] = {
        "post": {
            "operationId": "graph_upsert",
            "summary": "Structured idempotent graph write (MERGE by id). Requires `password`.",
            "requestBody": {"required": True, "content": {"application/json": {"schema": {
                "type": "object",
                "properties": {
                    "password": {"type": "string"},
                    "nodes": {"type": "array", "items": {"type": "object",
                              "properties": {"id": {"type": "string"}}, "required": ["id"]}},
                    "relations": {"type": "array", "items": {"type": "object",
                                  "properties": {"source": {"type": "string"},
                                                 "relation": {"type": "string"},
                                                 "target": {"type": "string"}},
                                  "required": ["source", "relation", "target"]}},
                },
                "required": ["password"],
            }}}},
            "responses": {"200": {"description": "Upsert result",
                                  "content": {"application/json": {"schema": {"type": "object"}}}}},
        }
    }
    paths["/graph_cypher"] = {
        "post": {
            "operationId": "graph_cypher",
            "summary": "Execute raw write Cypher. Powerful/dangerous. Requires `password`.",
            "requestBody": {"required": True, "content": {"application/json": {"schema": {
                "type": "object",
                "properties": {"password": {"type": "string"}, "cypher": {"type": "string"},
                               "params": {"type": "object"}},
                "required": ["password", "cypher"],
            }}}},
            "responses": {"200": {"description": "Cypher result",
                                  "content": {"application/json": {"schema": {"type": "object"}}}}},
        }
    }
    if run_enabled:
        paths["/run"] = {
            "post": {
                "operationId": "run",
                "summary": "Execute a shell command on the host and return its output.",
                "description": "Runs the received command in the project directory. "
                               "Gated only by MIND_ENABLE_RUN=1; no caller authentication required.",
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "type": "object",
                    "properties": {"command": {"type": "string"},
                                   "timeout": {"type": "number"}},
                    "required": ["command"],
                }}}},
                "responses": {"200": {"description": "Command result",
                                      "content": {"application/json": {"schema": {"type": "object"}}}}},
            }
        }
    return {
        "openapi": "3.1.0",
        "info": {"title": "Mind Nodes-as-Code MCP", "version": SERVER_VERSION,
                 "description": "Graph-authorized tools exposed by the Mind Nodes-as-Code runtime."},
        "servers": [{"url": public_url}],
        "paths": paths,
        "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}},
        "security": [{"bearerAuth": []}],
    }


def make_http_handler(server: McpServer, token: str | None, public_url: str):
    run_enabled = server.run_enabled

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # quiet; we log to stderr ourselves
            return

        def _authenticated(self) -> bool:
            """True iff the caller presented the run token. Read-only tools do
            not require this; the `run` executor does."""
            if not token:
                return False
            header = self.headers.get("Authorization", "")
            supplied = header[7:] if header.startswith("Bearer ") else self.headers.get("X-Api-Key", "")
            return bool(supplied) and hmac.compare_digest(supplied, token)

        def _send_json(self, code: int, obj: Any) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_body(self) -> Any:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b""
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"))

        # ---- GET: SSE notification stream + health + openapi ----------- #
        def do_GET(self):
            if self.path.split("?")[0].rstrip("/") == "/mcp":
                if "text/event-stream" in self.headers.get("Accept", ""):
                    self._serve_sse()
                else:
                    # A plain GET /mcp is the client probing for a stream; tell it
                    # the stream requires the SSE Accept header rather than 404.
                    self._send_json(405, {"error": "GET /mcp requires Accept: text/event-stream"})
                return
            if self.path.rstrip("/") in ("", "/health"):
                tools = [t["name"] for t in active_tool_bindings(server.graph)]
                self._send_json(200, {"server": SERVER_NAME, "version": SERVER_VERSION,
                                      "graph": server.settings.graph_name, "tools": tools,
                                      "mcpEndpoint": "/mcp", "openapi": "/openapi.json",
                                      "runEnabled": run_enabled})
                return
            if self.path.split("?")[0] in ("/openapi.json", "/openapi"):
                self._send_json(200, openapi_spec(public_url, run_enabled))
                return
            self._send_json(404, {"error": "not found"})

        # ---- POST: /mcp (JSON-RPC) + REST /graph_query + /run ---------- #
        def do_POST(self):
            path = self.path.split("?")[0]
            # Read-only tools are open (honouring "no auth"); the `run` executor
            # independently requires a valid token via `authenticated`.
            authed = self._authenticated()
            try:
                payload = self._read_body()
            except (ValueError, json.JSONDecodeError) as exc:
                self._send_json(400, {"error": f"invalid json: {exc}"})
                return

            if path.rstrip("/") == "/mcp":
                self._handle_mcp(payload, authed)
                return
            if path == "/graph_query":
                self._handle_rest(payload, "graph_query", authed)
                return
            if path == "/sense":
                self._handle_rest(payload, "sense", authed)
                return
            if path == "/graph_upsert":
                self._handle_rest(payload, "graph_upsert", authed)
                return
            if path == "/graph_cypher":
                self._handle_rest(payload, "graph_cypher", authed)
                return
            if path == "/run":
                if not run_enabled:
                    self._send_json(404, {"error": "run tool is disabled"})
                    return
                self._handle_rest(payload, "run", authed)
                return
            self._send_json(404, {"error": "not found"})

        def _handle_mcp(self, payload: Any, authed: bool):
            if isinstance(payload, list):
                responses = [r for r in (server.dispatch(m, authenticated=authed) for m in payload) if r]
                self._send_json(200, responses)
                return
            if not isinstance(payload, dict):
                self._send_json(200, McpServer._error(None, -32600, "invalid request"))
                return
            response = server.dispatch(payload, authenticated=authed)
            if response is None:
                self.send_response(202)
                self.end_headers()
                return
            self._send_json(200, response)

        def _serve_sse(self):
            """MCP Streamable-HTTP server->client stream. Emits
            `notifications/tools/list_changed` when the graph tool set changes,
            with periodic heartbeat comments so a dropped peer is detected and the
            subscriber is cleaned up. Read-only; no auth required (tool discovery
            is already public via /health and POST tools/list)."""
            import queue
            q: "queue.Queue[dict[str, Any]]" = queue.Queue()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Transfer-Encoding", "chunked")  # frame-by-frame so proxies forward each event immediately
            self.send_header("X-Accel-Buffering", "no")       # ask proxies (nginx/ngrok) not to buffer
            self.end_headers()
            self.close_connection = True  # dedicated long-lived stream, not keep-alive

            def send_chunk(data: bytes) -> None:
                # HTTP/1.1 chunked frame: hex length, CRLF, payload, CRLF.
                self.wfile.write(f"{len(data):X}\r\n".encode("ascii") + data + b"\r\n")
                self.wfile.flush()

            server.subscribe(q.put)
            try:
                # Initial padding comment (~2KB) defeats proxies that hold small
                # writes until an internal buffer fills, so the stream is live at
                # once; then a frequent heartbeat keeps it flushed and detects drop.
                send_chunk(b": " + b" " * 2048 + b"\n\n: connected\n\n")
                while not server._watch_stop.is_set():
                    try:
                        msg = q.get(timeout=10)
                        send_chunk(f"data: {json.dumps(msg, ensure_ascii=False)}\n\n".encode("utf-8"))
                    except queue.Empty:
                        send_chunk(b": ping\n\n")  # heartbeat / disconnect probe
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass  # peer went away; fall through to cleanup
            finally:
                server.unsubscribe(q.put)
                try:
                    self.wfile.write(b"0\r\n\r\n")  # terminating chunk
                    self.wfile.flush()
                except OSError:
                    pass

        def _handle_rest(self, payload: Any, tool_name: str, authed: bool):
            args = payload if isinstance(payload, dict) else {}
            try:
                structured = server.call_tool(tool_name, args, authenticated=authed)
                self._send_json(200, structured)
            except ToolError as exc:
                self._send_json(400, {"error": str(exc), "code": "invalid_arguments"})
            except ForbiddenError as exc:
                self._send_json(403, {"error": str(exc), "code": "forbidden"})
            except Exception as exc:
                log("rest internal error:", repr(exc))
                self._send_json(500, {"error": f"internal error: {exc}"})

    return Handler


def serve_http(server: McpServer, host: str, port: int, token: str | None, public_url: str) -> None:
    handler = make_http_handler(server, token, public_url)
    httpd = ThreadingHTTPServer((host, port), handler)
    # Single watcher for the whole HTTP server: it fans list_changed out to every
    # subscribed SSE stream. (stdio starts its own watcher inside serve_stdio.)
    server.start_tool_watcher()
    log(f"{SERVER_NAME} {SERVER_VERSION} http://{host}:{port}  public={public_url}  "
        f"auth={'on' if token else 'OFF'}  run_enabled={server.run_enabled}")
    httpd.serve_forever()


# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mind Nodes-as-Code MCP server")
    parser.add_argument("--graph", default=None, help="FalkorDB graph (default FALKOR_GRAPH)")
    parser.add_argument("--http", action="store_true", help="serve HTTP instead of stdio")
    parser.add_argument("--host", default=os.getenv("MIND_HTTP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MIND_HTTP_PORT", "8787")))
    parser.add_argument("--public-url", default=os.getenv("MIND_PUBLIC_URL", ""))
    return parser


def settings_for(graph: str | None) -> Settings:
    from dataclasses import replace
    settings = Settings()
    return replace(settings, graph_name=graph) if graph else settings


def run_server(args: argparse.Namespace) -> None:
    settings = settings_for(args.graph)
    server = McpServer(settings)
    if args.http:
        token = os.getenv("MIND_MCP_TOKEN") or None
        public_url = args.public_url or f"http://{args.host}:{args.port}"
        serve_http(server, args.host, args.port, token, public_url)
    else:
        server.serve_stdio()


def main() -> None:
    args = build_parser().parse_args()
    decorated_run = always_up_server_loop()(run_server)
    decorated_run(args)


if __name__ == "__main__":
    main()
