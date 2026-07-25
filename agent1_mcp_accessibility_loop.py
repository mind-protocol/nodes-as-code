"""Accessibility loop — ensures the MCP server is reachable on its public ngrok
URL and records the result as a graph-native health node in mind_kernel_v0.

Loop spine (created idempotently in the graph):
    objective:l2:mcp:public-accessibility   (outcome to preserve)
    observer:l2:mcp:public-accessibility     (independent probe procedure)
    health:l2:mcp:public-accessibility        (live derived state: score 100 or 0)
    problem:l2:mcp:public-accessibility       (single persistent error node)

Epistemic honesty: silence never becomes `healthy`.
    reachable + tools present -> score 100, healthy (problem resolved)
    error / unreachable       -> score 0, unhealthy (error persisted in single problem node + auto-relaunch attempted)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from falkordb import FalkorDB

DEFAULT_URL = "https://trusted-magpie-social.ngrok-free.app"
GRAPH = "mind_kernel_v0"
OBJ_ID = "objective:l2:mcp:public-accessibility"
OBSERVER_ID = "observer:l2:mcp:public-accessibility"
HEALTH_ID = "health:l2:mcp:public-accessibility"
PROBLEM_ID = "problem:l2:mcp:public-accessibility"
LOOP_ID = "space:l2:mcp:runtime-activation-v0"
PROJECT_ROOT = Path(__file__).resolve().parent
HDR = {"Content-Type": "application/json", "ngrok-skip-browser-warning": "true",
       "User-Agent": "mcp-accessibility-loop/1"}


def utcnow_ms() -> int:
    return int(time.time() * 1000)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _post(url, path, body, timeout=20):
    req = urllib.request.Request(url.rstrip("/") + path, data=json.dumps(body).encode("utf-8"),
                                 headers=HDR, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def _get(url, path, timeout=20):
    req = urllib.request.Request(url.rstrip("/") + path, headers=HDR, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def probe(url: str) -> dict:
    """Independent observer: hits the public URL and inspects real evidence."""
    started = time.monotonic()
    try:
        st, health = _get(url, "/")
        tools = health.get("tools", [])
        st2, r = _post(url, "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        listed = sorted(t["name"] for t in r.get("result", {}).get("tools", []))
        latency_ms = round((time.monotonic() - started) * 1000, 1)
        reachable = st == 200 and st2 == 200
        has_tools = "graph_query" in listed
        if reachable and has_tools:
            status, info, score = "healthy", "measured", 100
        elif reachable:
            status, info, score = "degraded", "measured", 0
        else:
            status, info, score = "unhealthy", "measurement_failed", 0
        return {"status": status, "score": score, "information_status": info, "reachable": reachable,
                "httpStatus": st, "tools": listed, "latencyMs": latency_ms, "error": None}
    except Exception as exc:
        return {"status": "unhealthy", "score": 0, "information_status": "measurement_failed",
                "reachable": False, "httpStatus": None, "tools": [],
                "latencyMs": round((time.monotonic() - started) * 1000, 1), "error": repr(exc)[:300]}


def ensure_loop_spine(g, url: str) -> None:
    ts = utcnow()
    g.query("""MERGE (o {id:$id}) SET o:RuntimeNode, o.node_type='narrative', o.subtype='objective',
               o.name='MCP server stays reachable on its public URL', o.target_url=$url, o.updated_at=$t""",
            {"id": OBJ_ID, "url": url, "t": ts})
    g.query("""MERGE (ob {id:$id}) SET ob:RuntimeNode, ob.node_type='thing', ob.subtype='observer',
               ob.name='Public MCP accessibility probe', ob.method='GET / + POST /mcp tools/list',
               ob.target_url=$url, ob.updated_at=$t""", {"id": OBSERVER_ID, "url": url, "t": ts})
    g.query("""MERGE (p {id:$id}) SET p:RuntimeNode, p.node_type='narrative', p.subtype='problem',
               p.name='MCP Public Server Endpoint Errors', p.expected_behavior='MCP server reachable with 200 OK',
               p.updated_at=$t""", {"id": PROBLEM_ID, "t": ts})
    for s, rel, o in [(LOOP_ID, "HAS_OBJECTIVE", OBJ_ID), (LOOP_ID, "OBSERVED_BY", OBSERVER_ID),
                      (OBSERVER_ID, "OBSERVES", OBJ_ID), (OBSERVER_ID, "DETECTS", PROBLEM_ID),
                      (HEALTH_ID, "EXPLAINS_WITH", PROBLEM_ID)]:
        g.query(f"MATCH (a {{id:$s}}) MATCH (b {{id:$o}}) MERGE (a)-[r:`{rel}`]->(b)", {"s": s, "o": o})


def relaunch_server() -> bool:
    """Attempt auto-relaunch of the MCP server endpoint."""
    try:
        launcher = PROJECT_ROOT / "scripts" / "mcp_endpoint_launcher.ps1"
        if launcher.exists():
            subprocess.run(["powershell.exe", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass",
                            "-File", str(launcher), "-Project", str(PROJECT_ROOT)],
                           capture_output=True, timeout=15)
            return True
    except Exception as exc:
        print(json.dumps({"at": utcnow(), "relaunchError": repr(exc)[:200]}), flush=True)
    return False


def write_health_and_problem(g, url: str, result: dict) -> None:
    now = utcnow_ms()
    is_healthy = (result["status"] == "healthy" and result["score"] == 100)
    health_status = "healthy" if is_healthy else "unhealthy"
    health_score = 100 if is_healthy else 0
    valid_until = now + 90_000 if is_healthy else now

    g.query("""MERGE (h {id:$id})
               SET h:RuntimeNode, h.node_type='narrative', h.subtype='health',
                   h.name='Health · MCP public accessibility',
                   h.status=$status, h.score=$score, h.information_status=$info,
                   h.target_url=$url, h.http_status=$http, h.latency_ms=$lat,
                   h.tools_json=$tools, h.last_checked_at=$now, h.valid_until=$vu,
                   h.last_error=$err
               WITH h MATCH (ob {id:$obs}) MERGE (ob)-[:PRODUCES_HEALTH]->(h)""",
            {"id": HEALTH_ID, "status": health_status, "score": health_score, "info": result["information_status"],
             "url": url, "http": result["httpStatus"], "lat": result["latencyMs"],
             "tools": json.dumps(result["tools"]), "now": now, "vu": valid_until,
             "err": result["error"], "obs": OBSERVER_ID})

    # Persist all error history and status into the SINGLE problem node
    if not is_healthy:
        err_msg = result["error"] or f"HTTP status {result['httpStatus']} (tools: {result['tools']})"
        relaunch_done = relaunch_server()
        g.query("""MATCH (p {id:$pid})
                   SET p.status='open',
                       p.information_status='measured',
                       p.last_error=$err,
                       p.last_detected_at=$now,
                       p.error_count = coalesce(p.error_count, 0) + 1,
                       p.relaunch_attempted = $relaunch,
                       p.last_relaunch_at = $now""",
                {"pid": PROBLEM_ID, "err": err_msg, "now": now, "relaunch": relaunch_done})
    else:
        g.query("""MATCH (p {id:$pid})
                   SET p.status='resolved',
                       p.resolved_at=$now""",
                {"pid": PROBLEM_ID, "now": now})


def tick(g, url: str) -> dict:
    result = probe(url)
    write_health_and_problem(g, url, result)
    out = {"at": utcnow(), "url": url, **result}
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--interval", type=float, default=30.0)
    args = ap.parse_args()

    g = FalkorDB(host="127.0.0.1", port=6379).select_graph(GRAPH)
    ensure_loop_spine(g, args.url)

    if not args.watch:
        result = tick(g, args.url)
        return 0 if result["status"] == "healthy" else 1

    while True:
        try:
            tick(g, args.url)
        except Exception as exc:  # never let the loop die silently
            print(json.dumps({"at": utcnow(), "loopError": repr(exc)[:300]}), flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
