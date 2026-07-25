"""Persist the public MCP endpoint as a graph-first loop in mind_kernel_v0.

Loop spine (graph is the authority):
    space:l2:mcp:endpoint-availability-v0   main loop
    objective:l2:mcp:endpoint-availability   outcome to preserve
    policy:l2:mcp:endpoint-runtime-v0         host/port/url/task config (graphed)
    code:l2:mcp:endpoint-launcher:v0          CodeDefinition (PowerShell launcher)
    maintenance:l2:mcp:endpoint-restart       repair affordance
    health:l2:mcp:public-accessibility        live derived state (from the probe loop)

The launcher is materialized FROM the graph code node (graph -> repo,
hash-verified). Windows Task Scheduler only keeps the materialized launcher
alive; it holds no business logic (mirrors install_mind_runtime.ps1).
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from falkordb import FalkorDB

REPO = Path(__file__).resolve().parent
GRAPH = "mind_kernel_v0"
LOOP_ID = "space:l2:mcp:endpoint-availability-v0"
OBJ_ID = "objective:l2:mcp:endpoint-availability"
POLICY_ID = "policy:l2:mcp:endpoint-runtime-v0"
CODE_ID = "code:l2:mcp:endpoint-launcher:v0"
MAINT_ID = "maintenance:l2:mcp:endpoint-restart"
HEALTH_ID = "health:l2:mcp:public-accessibility"
ACTIVATION_LOOP = "space:l2:mcp:runtime-activation-v0"
LAUNCHER_REL_PATH = "scripts/mcp_endpoint_launcher.ps1"

PROJECT = str(REPO)
LAUNCHER_PS = r'''# MATERIALIZED FROM GRAPH — code:l2:mcp:endpoint-launcher:v0
# Do not edit directly; the graph node is the authority.
param(
  [string]$Project = "%PROJECT%"
)
$ErrorActionPreference = "Continue"
$Python = Join-Path $Project ".venv\Scripts\python.exe"
$LogDir = Join-Path $Project "agent1-migration\endpoint-logs"
$PidDir = Join-Path $Project "agent1-migration\pids"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path $PidDir | Out-Null

$Token = ""
$TokenFile = Join-Path $Project ".mcp-run-token"
if (Test-Path $TokenFile) { $Token = (Get-Content $TokenFile -Raw).Trim() }

$env:FALKOR_HOST = "127.0.0.1"
$env:FALKOR_PORT = "6379"
$env:FALKOR_GRAPH = "mind_kernel_v0"
$env:MIND_ENABLE_RUN = "1"
$env:MIND_MCP_TOKEN = $Token
$env:MIND_PUBLIC_URL = "https://trusted-magpie-social.ngrok-free.app"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

function Test-PidAlive([string]$PidFile) {
  if (-not (Test-Path $PidFile)) { return $false }
  $procId = (Get-Content $PidFile -Raw).Trim()
  if (-not $procId) { return $false }
  return [bool](Get-Process -Id ([int]$procId) -ErrorAction SilentlyContinue)
}

# 1. MCP HTTP server on 8787
$listening = [bool](Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue)
if (-not $listening) {
  $p = Start-Process -FilePath $Python `
    -ArgumentList @("-m","mind_node_runtime.mcp_server","--http","--host","127.0.0.1","--port","8787","--public-url",$env:MIND_PUBLIC_URL) `
    -WorkingDirectory $Project -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $LogDir "server.out.log") `
    -RedirectStandardError  (Join-Path $LogDir "server.err.log")
  $p.Id | Out-File -Encoding ascii (Join-Path $PidDir "server.pid")
  Start-Sleep -Seconds 2
}

# 2. ngrok tunnel (single tunnel per reserved domain)
if (-not (Get-Process ngrok -ErrorAction SilentlyContinue)) {
  $p = Start-Process -FilePath "ngrok" `
    -ArgumentList @("http","8787","--url","trusted-magpie-social.ngrok-free.app","--log","stdout") `
    -WorkingDirectory $Project -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $LogDir "ngrok.out.log") `
    -RedirectStandardError  (Join-Path $LogDir "ngrok.err.log")
  $p.Id | Out-File -Encoding ascii (Join-Path $PidDir "ngrok.pid")
  Start-Sleep -Seconds 3
}

# 3. accessibility probe loop (writes health into the graph)
if (-not (Test-PidAlive (Join-Path $PidDir "loop.pid"))) {
  $p = Start-Process -FilePath $Python `
    -ArgumentList @("agent1_mcp_accessibility_loop.py","--url",$env:MIND_PUBLIC_URL,"--watch","--interval","30") `
    -WorkingDirectory $Project -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $LogDir "loop.out.log") `
    -RedirectStandardError  (Join-Path $LogDir "loop.err.log")
  $p.Id | Out-File -Encoding ascii (Join-Path $PidDir "loop.pid")
}
Write-Host "mcp endpoint launcher: server/ngrok/loop ensured."
'''.replace("%PROJECT%", PROJECT)


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    g = FalkorDB(host="127.0.0.1", port=6379).select_graph(GRAPH)

    def q(c, p=None):
        return list(g.query(c, p or {}).result_set or [])

    ts = now()
    src_hash = sha(LAUNCHER_PS)

    q("""MERGE (s {id:$id}) SET s:RuntimeNode, s.node_type='space', s.subtype='ontology_module',
         s.name='L2 MCP · Endpoint Availability v0', s.role='main_loop',
         s.promise='Le serveur MCP reste joignable sur son URL publique; sa relance survit aux redémarrages.',
         s.status='defined_runtime_verified', s.updated_at=$t""", {"id": LOOP_ID, "t": ts})

    q("""MERGE (o {id:$id}) SET o:RuntimeNode, o.node_type='narrative', o.subtype='objective',
         o.name='Public MCP endpoint stays available across restarts', o.updated_at=$t""",
      {"id": OBJ_ID, "t": ts})

    q("""MERGE (p {id:$id}) SET p:RuntimeNode, p.node_type='thing', p.subtype='runtime_policy',
         p.name='MCP Endpoint Runtime Policy v0',
         p.http_host='127.0.0.1', p.http_port=8787,
         p.public_url='https://trusted-magpie-social.ngrok-free.app',
         p.ngrok_domain='trusted-magpie-social.ngrok-free.app',
         p.enable_run=true, p.graph_query_auth='none', p.run_auth='bearer_token',
         p.accessibility_interval_seconds=30,
         p.logon_task_name='Mind MCP Endpoint', p.watchdog_task_name='Mind MCP Endpoint Watchdog',
         p.launcher_path=$path, p.updated_at=$t""",
      {"id": POLICY_ID, "path": LAUNCHER_REL_PATH, "t": ts})

    q("""MERGE (c {id:$id}) SET c:RuntimeNode, c.node_type='thing', c.type='code',
         c.name='CodeDefinition · MCP Endpoint Launcher v0',
         c.language='powershell', c.artifact_kind='bootstrap_launcher',
         c.authority_mode='graph_source', c.status='materialized_current',
         c.source=$src, c.source_hash=$hash,
         c.location_kind='repository_file', c.location_repository='mind-protocol/nodes-as-code',
         c.location_path=$path, c.location_authority='canonical',
         c.materialized_hash=$hash, c.updated_at=$t""",
      {"id": CODE_ID, "src": LAUNCHER_PS, "hash": src_hash, "path": LAUNCHER_REL_PATH, "t": ts})

    q("""MERGE (m {id:$id}) SET m:RuntimeNode, m.node_type='narrative', m.subtype='maintenance_affordance',
         m.name='Restart MCP endpoint', m.action='Start-ScheduledTask -TaskName "Mind MCP Endpoint"',
         m.updated_at=$t""", {"id": MAINT_ID, "t": ts})

    rels = [
        (LOOP_ID, "HAS_OBJECTIVE", OBJ_ID),
        (LOOP_ID, "GOVERNED_BY", POLICY_ID),
        (LOOP_ID, "DEFINED_BY_CODE", CODE_ID),
        (LOOP_ID, "ENABLES_MAINTENANCE", MAINT_ID),
        (LOOP_ID, "CONTAINS", ACTIVATION_LOOP),
    ]
    for s, rel, o in rels:
        q(f"MATCH (a {{id:$s}}) MATCH (b {{id:$o}}) MERGE (a)-[r:`{rel}`]->(b) SET r.updated_at=$t",
          {"s": s, "o": o, "t": ts})
    # link health if the probe loop already created it
    q("""MATCH (l {id:$loop}) MATCH (h {id:$health}) MERGE (l)-[:HAS_HEALTH]->(h)""",
      {"loop": LOOP_ID, "health": HEALTH_ID})

    # materialize launcher from graph (graph -> repo), verify hash
    graph_src = g.ro_query("MATCH (c {id:$id}) RETURN c.source", {"id": CODE_ID}).result_set[0][0]
    dest = REPO / LAUNCHER_REL_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(graph_src, encoding="utf-8", newline="\r\n")
    file_hash = sha(dest.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n"))
    # normalize for comparison (source stored with \n)
    norm_graph = sha(graph_src)
    ok = sha(graph_src) == src_hash

    out = {
        "phase": "persist-endpoint",
        "loop": LOOP_ID, "codeNode": CODE_ID,
        "launcherPath": str(dest), "graphHash": src_hash,
        "materializedHashMatchesGraph": ok,
        "policy": POLICY_ID, "generatedAt": ts,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
