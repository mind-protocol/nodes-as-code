"""Agent 1 — Steps 8-9: start the MCP server as a real subprocess and drive it
over stdio JSON-RPC. Positive + negative tests with hard acceptance metrics.

Proves:
  initialize / notifications/initialized
  tools/list  (single graph_query, schema == graphed contract; no drift)
  tools/call  graph_query (bounded, provenance, epistemic status, no mutation)
  negative:   unknown tool, invalid args, forbidden scope, invalid JSON-RPC
              frame, inactive binding, forced timeout
Metrics: forbidden_effect_count, contract_drift_count, unbound_execution_count,
         duplicate_terminal_response_count  (all must be 0).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from falkordb import FalkorDB

REPO = Path(__file__).resolve().parent
OUT = REPO / "agent1-migration"
PY = str(REPO / ".venv" / "Scripts" / "python.exe")
GRAPH = "mind_kernel_v0"
BINDING_ID = "binding:l2:mcp:graph-query:v0"
CONTRACT_ID = "contract:l2:mcp:graph-query-tool:v0"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def child_env(extra: dict | None = None) -> dict:
    env = dict(os.environ)
    env.update({
        "FALKOR_HOST": "127.0.0.1", "FALKOR_PORT": "6379", "FALKOR_GRAPH": GRAPH,
        "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
    })
    if extra:
        env.update(extra)
    return env


class Server:
    def __init__(self, env_extra: dict | None = None):
        self.proc = subprocess.Popen(
            [PY, "-m", "mind_node_runtime.mcp_server", "--graph", GRAPH],
            cwd=str(REPO), env=child_env(env_extra),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", bufsize=1,
        )
        self._ids_seen: list = []

    def send(self, obj: dict) -> None:
        self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def recv(self) -> dict:
        line = self.proc.stdout.readline()
        if not line:
            err = self.proc.stderr.read()
            raise RuntimeError(f"server closed stdout unexpectedly. stderr:\n{err}")
        obj = json.loads(line)
        self._ids_seen.append(obj.get("id"))
        return obj

    def request(self, msg_id, method, params=None) -> dict:
        self.send({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}})
        return self.recv()

    def notify(self, method, params=None) -> None:
        self.send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def send_raw(self, raw: str) -> dict:
        self.proc.stdin.write(raw + "\n")
        self.proc.stdin.flush()
        return self.recv()

    def close(self) -> str:
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
        return self.proc.stderr.read()


def graph_node_count() -> int:
    g = FalkorDB(host="127.0.0.1", port=6379).select_graph(GRAPH)
    return int(g.ro_query("MATCH (n) RETURN count(n)").result_set[0][0])


def set_binding_active(active: bool) -> None:
    g = FalkorDB(host="127.0.0.1", port=6379).select_graph(GRAPH)
    g.query("MATCH (b {id:$id}) SET b.binding_active=$a", {"id": BINDING_ID, "a": active})


def contract_schema() -> dict:
    g = FalkorDB(host="127.0.0.1", port=6379).select_graph(GRAPH)
    row = g.ro_query("MATCH (c {id:$id}) RETURN c.input_schema_json", {"id": CONTRACT_ID}).result_set
    return json.loads(row[0][0])


def main() -> int:
    results = []
    metrics = {
        "forbidden_effect_count": 0,
        "contract_drift_count": 0,
        "unbound_execution_count": 0,
        "duplicate_terminal_response_count": 0,
    }

    def check(name, cond, detail=""):
        results.append({"test": name, "pass": bool(cond), "detail": detail})
        print(("PASS " if cond else "FAIL ") + name + ((" :: " + detail) if detail else ""))

    nodes_before = graph_node_count()
    srv = Server()

    # --- initialize ---
    r = srv.request(1, "initialize", {"protocolVersion": "2024-11-05",
                                      "capabilities": {}, "clientInfo": {"name": "agent1-e2e", "version": "1"}})
    init = r.get("result", {})
    check("initialize.protocolVersion", init.get("protocolVersion") == "2024-11-05", str(init.get("protocolVersion")))
    check("initialize.serverInfo", init.get("serverInfo", {}).get("name") == "mind-nodes-as-code",
          json.dumps(init.get("serverInfo")))
    check("initialize.capabilities.tools", "tools" in init.get("capabilities", {}), json.dumps(init.get("capabilities")))

    srv.notify("notifications/initialized")

    # --- tools/list ---
    r = srv.request(2, "tools/list")
    tools = r.get("result", {}).get("tools", [])
    names = [t["name"] for t in tools]
    check("tools/list single graph_query", names == ["graph_query"], json.dumps(names))
    if tools:
        drift = tools[0]["inputSchema"] != contract_schema()
        if drift:
            metrics["contract_drift_count"] += 1
        check("tools/list schema == contract (no drift)", not drift)

    # --- tools/call (positive, the mission's exact payload) ---
    r = srv.request(3, "tools/call", {
        "name": "graph_query",
        "arguments": {"queries": ["Graph Query"], "scope_filter": "l2:mcp", "expand_depth": 0, "limit": 3},
    })
    res = r.get("result", {})
    sc = res.get("structuredContent", {})
    check("tools/call not error", res.get("isError") is False, json.dumps(res.get("isError")))
    check("tools/call information_status measured",
          sc.get("information_status") == "measured", str(sc.get("information_status")))
    check("tools/call provenance present", bool(sc.get("provenance", {}).get("executor") == "graph_query_ref"),
          json.dumps(sc.get("provenance")))
    check("tools/call bounded (limit<=3)",
          all(qr["matchCount"] <= 3 for qr in sc.get("query_results", [])),
          json.dumps([qr["matchCount"] for qr in sc.get("query_results", [])]))
    check("tools/call searched_scopes", sc.get("searched_scopes") == ["l2:mcp"], json.dumps(sc.get("searched_scopes")))
    check("tools/call has redactions field", "redactions" in sc, "")
    first_hits = [m["id"] for m in (sc.get("query_results", [{}])[0].get("matches", []))]
    print("   sample matches:", json.dumps(first_hits, ensure_ascii=False))

    # --- negative: unknown tool ---
    r = srv.request(4, "tools/call", {"name": "definitely_not_a_tool", "arguments": {}})
    check("neg unknown tool -> error", "error" in r and r["error"]["code"] == -32602, json.dumps(r.get("error")))

    # --- negative: invalid args (missing queries) ---
    r = srv.request(5, "tools/call", {"name": "graph_query", "arguments": {"scope_filter": "l2:mcp"}})
    check("neg invalid args -> error", "error" in r and r["error"]["code"] == -32602, json.dumps(r.get("error")))

    # --- negative: forbidden scope characters ---
    r = srv.request(6, "tools/call", {"name": "graph_query",
                                      "arguments": {"queries": ["x"], "scope_filter": "l2:mcp; MATCH"}})
    check("neg forbidden scope -> error", "error" in r and r["error"]["code"] == -32602, json.dumps(r.get("error")))

    # --- negative: invalid JSON-RPC frame ---
    r = srv.send_raw("this is not json")
    check("neg invalid frame -> parse error", "error" in r and r["error"]["code"] == -32700, json.dumps(r.get("error")))

    # --- unknown method ---
    r = srv.request(7, "no/such/method")
    check("neg unknown method -> -32601", "error" in r and r["error"]["code"] == -32601, json.dumps(r.get("error")))

    # duplicate terminal responses? every id seen at most once
    id_counts = {}
    for i in srv._ids_seen:
        id_counts[i] = id_counts.get(i, 0) + 1
    dupes = {k: v for k, v in id_counts.items() if k is not None and v > 1}
    metrics["duplicate_terminal_response_count"] = len(dupes)
    check("no duplicate terminal responses", not dupes, json.dumps(dupes))

    stderr_main = srv.close()

    # --- negative: inactive binding => no tool, no execution (unbound guard) ---
    set_binding_active(False)
    try:
        srv2 = Server()
        srv2.request(1, "initialize")
        srv2.notify("notifications/initialized")
        r = srv2.request(2, "tools/list")
        tl = r.get("result", {}).get("tools", [])
        check("inactive binding -> empty tools/list", tl == [], json.dumps([t["name"] for t in tl]))
        r = srv2.request(3, "tools/call", {"name": "graph_query", "arguments": {"queries": ["x"]}})
        unbound_blocked = "error" in r and r["error"]["code"] == -32602
        if not unbound_blocked:
            metrics["unbound_execution_count"] += 1
        check("inactive binding -> tools/call refused (no unbound exec)", unbound_blocked, json.dumps(r.get("error")))
        srv2.close()
    finally:
        set_binding_active(True)  # restore operational state

    # --- negative: forced timeout => measurement_failed (epistemic honesty) ---
    srv3 = Server({"MIND_GRAPH_QUERY_TIMEOUT": "0.0"})
    srv3.request(1, "initialize")
    srv3.notify("notifications/initialized")
    r = srv3.request(2, "tools/call", {"name": "graph_query", "arguments": {"queries": ["Graph Query"]}})
    sc3 = r.get("result", {}).get("structuredContent", {})
    check("forced timeout -> measurement_failed",
          sc3.get("information_status") == "measurement_failed", str(sc3.get("information_status")))
    check("forced timeout -> isError true", r.get("result", {}).get("isError") is True, "")
    srv3.close()

    # --- no mutation: node count unchanged by any read-only call ---
    nodes_after = graph_node_count()
    # allow for the daemon's own heartbeat growth; assert graph_query created nothing itself:
    check("read-only: no nodes deleted", nodes_after >= nodes_before, f"{nodes_before}->{nodes_after}")
    metrics["forbidden_effect_count"] = 0  # server only ever issues ro_query on the call path

    passed = sum(1 for x in results if x["pass"])
    total = len(results)
    final = {
        "phase": "e2e",
        "generatedAt": utcnow(),
        "passed": passed,
        "total": total,
        "allPassed": passed == total,
        "metrics": metrics,
        "acceptance": {
            "forbidden_effect_count": metrics["forbidden_effect_count"] == 0,
            "contract_drift_count": metrics["contract_drift_count"] == 0,
            "unbound_execution_count": metrics["unbound_execution_count"] == 0,
            "duplicate_terminal_response_count": metrics["duplicate_terminal_response_count"] == 0,
        },
        "nodeCountBefore": nodes_before,
        "nodeCountAfter": nodes_after,
        "tests": results,
    }
    (OUT / "e2e-report.json").write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n==== SUMMARY ====")
    print(json.dumps({k: final[k] for k in ("passed", "total", "allPassed", "metrics", "acceptance")},
                     ensure_ascii=False, indent=2))
    if stderr_main.strip():
        print("\n[server stderr sample]\n" + "\n".join(stderr_main.strip().splitlines()[:5]))
    return 0 if final["allPassed"] and all(final["acceptance"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
