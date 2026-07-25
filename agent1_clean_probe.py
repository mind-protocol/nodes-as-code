"""Agent 1 — Step 10 verification: launch the MCP server from a CLEAN environment
using ONLY the fields in mcp-client-config.json (no inherited FALKOR_* / cwd),
then re-run the three probes: initialize, tools/list, tools/call.

This proves the published client configuration is self-sufficient.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent
CONFIG = json.loads((REPO / "mcp-client-config.json").read_text(encoding="utf-8"))


def clean_env(cfg_env: dict) -> dict:
    # Minimal Windows essentials so the interpreter can load; NO FALKOR_* leak.
    keep = {}
    for k in ("SystemRoot", "windir", "TEMP", "TMP", "PATHEXT", "NUMBER_OF_PROCESSORS", "COMSPEC"):
        if k in os.environ:
            keep[k] = os.environ[k]
    keep["PATH"] = os.environ.get("SystemRoot", "C:\\Windows") + "\\System32"
    keep["PYTHONUTF8"] = "1"
    keep["PYTHONIOENCODING"] = "utf-8"
    keep.update(cfg_env)  # the config's declared env is the ONLY source of FALKOR_*
    assert "FALKOR_GRAPH" in keep and keep["FALKOR_GRAPH"] == "mind_kernel_v0"
    return keep


def main() -> int:
    proc = subprocess.Popen(
        [CONFIG["command"], *CONFIG["args"]],
        cwd=CONFIG["cwd"], env=clean_env(CONFIG["env"]),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", bufsize=1,
    )

    def rpc(mid, method, params=None):
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": mid, "method": method,
                                     "params": params or {}}) + "\n")
        proc.stdin.flush()
        return json.loads(proc.stdout.readline())

    def notify(method):
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        proc.stdin.flush()

    probes = {}
    r = rpc(1, "initialize")
    probes["initialize"] = {
        "ok": r.get("result", {}).get("serverInfo", {}).get("name") == "mind-nodes-as-code",
        "serverInfo": r.get("result", {}).get("serverInfo"),
        "protocolVersion": r.get("result", {}).get("protocolVersion"),
    }
    notify("notifications/initialized")

    r = rpc(2, "tools/list")
    names = sorted(t["name"] for t in r.get("result", {}).get("tools", []))
    expected_tools = sorted(["graph_query", "graph_write", "graph_upsert", "graph_cypher", "run", "sense"])
    probes["tools/list"] = {"ok": set(expected_tools).issubset(set(names)), "tools": names}

    r = rpc(3, "tools/call", {"name": "graph_query",
                              "arguments": {"queries": ["Graph Query"], "scope_filter": "l2:mcp",
                                            "expand_depth": 0, "limit": 3}})
    sc = r.get("result", {}).get("structuredContent", {})
    probes["tools/call"] = {
        "ok": r.get("result", {}).get("isError") is False and sc.get("information_status") == "measured",
        "information_status": sc.get("information_status"),
        "matchCounts": [q["matchCount"] for q in sc.get("query_results", [])],
        "provenanceExecutor": sc.get("provenance", {}).get("executor"),
        "sampleMatches": [m["id"] for m in (sc.get("query_results", [{}])[0].get("matches", []))],
    }

    try:
        proc.stdin.close(); proc.wait(timeout=5)
    except Exception:
        proc.kill()

    all_ok = all(p["ok"] for p in probes.values())
    report = {"phase": "clean-env-probe", "generatedAt": datetime.now(timezone.utc).isoformat(),
              "cleanEnv": True, "inheritedFalkorVars": False, "allProbesPassed": all_ok, "probes": probes}
    (REPO / "agent1-migration" / "clean-probe-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
