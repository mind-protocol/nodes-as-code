"""Probe the MCP HTTP server (local or public ngrok URL) and report accessibility.

Usage:  python agent1_http_probe.py <base_url>
Checks: GET /  and /openapi.json, POST /mcp (initialize, tools/list, tools/call
graph_query), graph_query REST (open), and run gating (403 without token, ok
with token). The token is read from .mcp-run-token if present.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8787").rstrip("/")
TOKEN = Path(".mcp-run-token").read_text(encoding="utf-8").strip() if Path(".mcp-run-token").exists() else ""
HDR = {"Content-Type": "application/json", "ngrok-skip-browser-warning": "true", "User-Agent": "agent1-probe/1"}


def http(method, path, body=None, token=None, timeout=25):
    headers = dict(HDR)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def j(s):
    try:
        return json.loads(s)
    except Exception:
        return {"_raw": s[:300]}


def main() -> int:
    print(f"probing {BASE}")
    results = []

    def check(name, ok, detail=""):
        results.append(ok)
        print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:200]) if detail else ""))

    st, body = http("GET", "/")
    health = j(body)
    check("GET / health", st == 200 and health.get("server") == "mind-nodes-as-code",
          f"{st} tools={health.get('tools')}")

    st, body = http("GET", "/openapi.json")
    spec = j(body)
    check("GET /openapi.json", st == 200 and "paths" in spec, f"{st} paths={list(spec.get('paths',{}))}")

    st, body = http("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    r = j(body)
    check("POST /mcp initialize", st == 200 and r.get("result", {}).get("serverInfo", {}).get("name") == "mind-nodes-as-code",
          st)

    st, body = http("POST", "/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    r = j(body)
    names = sorted(t["name"] for t in r.get("result", {}).get("tools", []))
    check("POST /mcp tools/list has graph_query+run", names == ["graph_query", "run"], names)

    st, body = http("POST", "/mcp", {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                     "arguments": None,
                                     "params": {"name": "graph_query",
                                                "arguments": {"queries": ["Graph Query"],
                                                              "scope_filter": "l2:mcp", "limit": 2}}})
    r = j(body)
    sc = r.get("result", {}).get("structuredContent", {})
    check("tools/call graph_query (open)", st == 200 and sc.get("information_status") == "measured",
          sc.get("information_status"))

    st, body = http("POST", "/graph_query", {"queries": ["binding"], "scope_filter": "l2:mcp", "limit": 2})
    check("REST /graph_query (no auth)", st == 200 and j(body).get("information_status") in ("measured", "known_absent"), st)

    # run gating: without token must be refused; with token must execute
    st, body = http("POST", "/mcp", {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                     "params": {"name": "run", "arguments": {"command": "echo probe-noauth"}}})
    r = j(body)
    check("run WITHOUT token -> forbidden", "error" in r and r["error"].get("code") == -32001, r.get("error"))

    st, body = http("POST", "/mcp", {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                                     "params": {"name": "run", "arguments": {"command": "echo probe-withtoken"}}},
                    token=TOKEN)
    r = j(body)
    sc = r.get("result", {}).get("structuredContent", {})
    ok_run = st == 200 and sc.get("returncode") == 0 and "probe-withtoken" in (sc.get("stdout") or "")
    check("run WITH token -> executes", ok_run, {"rc": sc.get("returncode"), "out": (sc.get("stdout") or "").strip()[:60]})

    allp = all(results)
    print(f"\n{sum(results)}/{len(results)} checks passed  ({'ACCESSIBLE' if allp else 'PROBLEM'})")
    return 0 if allp else 1


if __name__ == "__main__":
    sys.exit(main())
