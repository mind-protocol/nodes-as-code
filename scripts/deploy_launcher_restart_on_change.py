"""Graph ChangeSet: teach the MCP endpoint launcher to restart on code change.

Authority is the CodeDefinition node `code:l2:mcp:endpoint-launcher:v0`
(authority_mode=graph_source, materialized to scripts/mcp_endpoint_launcher.ps1).
We author the new launcher source INTO the node, recompute hashes, record a
materialization Moment, then materialize the .ps1 from node.source and verify
the file hash-matches the node.

New behavior added to the launcher (still idempotent, still run every minute by
the "Mind MCP Endpoint Watchdog" scheduled task):

  * The MCP server is restarted not only when :8787 is dead, but also when the
    MCP runtime code changes. The launcher hashes the server's dependency set
    (mcp_server.py + always_up.py + config.py + graph.py) and compares it to the
    hash recorded when the running server was last started; on mismatch it kills
    and relaunches the server, then records the new hash.
  * ngrok and the accessibility loop remain ensured (always up).
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from falkordb import FalkorDB

GRAPH = "mind_kernel_v0"
LAUNCHER_CODE_ID = "code:l2:mcp:endpoint-launcher:v0"
REPO = Path(__file__).resolve().parents[1]
LAUNCHER_PATH = REPO / "scripts" / "mcp_endpoint_launcher.ps1"
PID_DIR = REPO / "agent1-migration" / "pids"
MCP_CODE_FILES = ["always_up.py", "config.py", "graph.py", "mcp_server.py"]

# The launcher source. Uses LF line endings; materialized verbatim (newline="").
LAUNCHER_SOURCE = r"""# MATERIALIZED FROM GRAPH — code:l2:mcp:endpoint-launcher:v0
# Do not edit directly; the graph node is the authority.
#
# Idempotent. Run every minute by the "Mind MCP Endpoint Watchdog" scheduled
# task. Responsibilities:
#   1. Keep the MCP HTTP server on :8787 alive AND current — restart it whenever
#      the MCP runtime code changes (hash of the server's dependency set).
#   2. Keep the ngrok tunnel up on the reserved domain.
#   3. Keep the accessibility probe loop up (writes health into the graph).
param(
  [string]$Project = "C:\Users\reyno\OneDrive\Documents\nodes-as-code"
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

# The MCP server's runtime code = mcp_server plus its direct dependency modules.
# Extend this list if mcp_server.py grows new intra-package imports.
$McpCodeFiles = @("always_up.py","config.py","graph.py","mcp_server.py") |
  ForEach-Object { Join-Path $Project ("src\mind_node_runtime\" + $_) }

function Get-McpCodeHash {
  $sha = [System.Security.Cryptography.SHA256]::Create()
  $ms = New-Object System.IO.MemoryStream
  foreach ($file in ($McpCodeFiles | Sort-Object)) {
    if (-not (Test-Path $file)) { continue }
    $nameBytes = [System.Text.Encoding]::UTF8.GetBytes(([System.IO.Path]::GetFileName($file)) + "`n")
    $ms.Write($nameBytes, 0, $nameBytes.Length)
    $contentBytes = [System.IO.File]::ReadAllBytes($file)
    $ms.Write($contentBytes, 0, $contentBytes.Length)
  }
  $digest = $sha.ComputeHash($ms.ToArray())
  $ms.Dispose()
  return (($digest | ForEach-Object { $_.ToString("x2") }) -join "")
}

function Stop-McpServer {
  Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    try { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue } catch {}
  }
  Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "mind_node_runtime\.mcp_server" } |
    ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {} }
  Start-Sleep -Milliseconds 700
}

function Start-McpServer {
  $p = Start-Process -FilePath $Python `
    -ArgumentList @("-u","-m","mind_node_runtime.mcp_server","--http","--host","127.0.0.1","--port","8787","--public-url",$env:MIND_PUBLIC_URL) `
    -WorkingDirectory $Project -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $LogDir "server.out.log") `
    -RedirectStandardError  (Join-Path $LogDir "server.err.log")
  $p.Id | Out-File -Encoding ascii (Join-Path $PidDir "server.pid")
  Start-Sleep -Seconds 2
}

# 1. MCP HTTP server on 8787 — alive AND current (restart on code change).
$HashFile = Join-Path $PidDir "server.codehash"
$CurrentHash = Get-McpCodeHash
$RunningHash = ""
if (Test-Path $HashFile) { $RunningHash = (Get-Content $HashFile -Raw).Trim() }
$listening = [bool](Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue)
$codeChanged = ($CurrentHash -ne $RunningHash)

if ((-not $listening) -or $codeChanged) {
  if ($listening) { Stop-McpServer }
  Start-McpServer
  Set-Content -Path $HashFile -Value $CurrentHash -Encoding ascii -NoNewline
  $reason = if (-not $listening) { "not-listening" } else { "code-changed" }
  Write-Host ("mcp server (re)started [" + $reason + "] codehash=" + $CurrentHash.Substring(0, 12))
} else {
  Write-Host "mcp server current; no restart needed."
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
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def mcp_code_hash() -> str:
    """Replicate the launcher's Get-McpCodeHash exactly (for the baseline marker)."""
    h = hashlib.sha256()
    src = REPO / "src" / "mind_node_runtime"
    for name in sorted(MCP_CODE_FILES):
        p = src / name
        if not p.exists():
            continue
        h.update((name + "\n").encode("utf-8"))
        h.update(p.read_bytes())
    return h.hexdigest()


def main() -> int:
    source = LAUNCHER_SOURCE
    graph_hash = sha256_text(source)
    revision = f"rev:{graph_hash[:16]}"
    now = utcnow()

    g = FalkorDB(host="127.0.0.1", port=6379).select_graph(GRAPH)

    def q(c, p=None):
        return list(g.query(c, p or {}).result_set or [])

    def qro(c, p=None):
        return list(g.ro_query(c, p or {}).result_set or [])

    prev = qro("MATCH (n {id:$id}) RETURN n.source_hash, n.revision_id", {"id": LAUNCHER_CODE_ID})
    prev_hash = prev[0][0] if prev else None
    prev_rev = prev[0][1] if prev else None

    # 1. Author the new source INTO the node (graph authority).
    updated = q(
        """
        MATCH (n {id:$id})
        SET n.source = $source,
            n.source_hash = $hash,
            n.language = 'powershell',
            n.artifact_kind = 'bootstrap_launcher',
            n.authority_mode = 'graph_source',
            n.status = 'materialized_current',
            n.location_kind = 'repository_file',
            n.location_repository = 'mind-protocol/nodes-as-code',
            n.location_path = 'scripts/mcp_endpoint_launcher.ps1',
            n.location_authority = 'canonical',
            n.materialized_hash = $hash,
            n.revision_id = $rev,
            n.materialized_at = $now
        RETURN n.id
        """,
        {"id": LAUNCHER_CODE_ID, "source": source, "hash": graph_hash, "rev": revision, "now": now},
    )
    if not updated:
        print(json.dumps({"status": "aborted", "reason": f"launcher node not found: {LAUNCHER_CODE_ID}"}, indent=2))
        return 2

    # 2. Provenance Moment.
    rec_id = f"moment:l2:mcp:materialization:{revision}"
    q(
        """
        MERGE (m {id:$id})
        SET m:RuntimeNode, m.node_type = 'moment', m.subtype = 'materialization_record',
            m.name = 'Materialization · MCP endpoint launcher restart-on-code-change',
            m.code_node_id = $code, m.location_path = 'scripts/mcp_endpoint_launcher.ps1',
            m.graph_hash = $hash, m.materialized_hash = $hash, m.status = 'materialized_current',
            m.previous_revision = $prev_rev, m.produced_at = $now
        WITH m
        MATCH (c {id:$code}) MERGE (m)-[:MATERIALIZES]->(c)
        RETURN m.id
        """,
        {"id": rec_id, "code": LAUNCHER_CODE_ID, "hash": graph_hash, "prev_rev": prev_rev, "now": now},
    )

    # 3. Materialize node.source -> the repository file (LF preserved).
    tmp = LAUNCHER_PATH.with_name(LAUNCHER_PATH.name + ".tmp")
    tmp.write_text(source, encoding="utf-8", newline="")
    tmp.replace(LAUNCHER_PATH)

    # 4. Seed the running-server code hash so the already-current server is not
    #    needlessly restarted on the next watchdog tick.
    PID_DIR.mkdir(parents=True, exist_ok=True)
    baseline = mcp_code_hash()
    (PID_DIR / "server.codehash").write_text(baseline, encoding="ascii", newline="")

    # 5. Independent readback.
    file_hash = sha256_text(LAUNCHER_PATH.read_text(encoding="utf-8"))
    rows = qro(
        "MATCH (n {id:$id}) RETURN n.source_hash, n.materialized_hash, n.revision_id, size(n.source)",
        {"id": LAUNCHER_CODE_ID},
    )
    r = rows[0]
    node_source_has_restart = qro(
        "MATCH (n {id:$id}) WHERE n.source CONTAINS 'Get-McpCodeHash' "
        "AND n.source CONTAINS 'code-changed' RETURN count(n)",
        {"id": LAUNCHER_CODE_ID},
    )[0][0]

    proof = {
        "phase": "deploy-launcher-restart-on-change",
        "generatedAt": now,
        "previous": {"source_hash": prev_hash, "revision_id": prev_rev},
        "current": {"source_hash": r[0], "materialized_hash": r[1], "revision_id": r[2], "node_source_chars": r[3]},
        "file_hash": file_hash,
        "node_source_hash_equals_file": r[0] == file_hash,
        "node_source_has_restart_logic": int(node_source_has_restart) == 1,
        "server_codehash_baseline": baseline,
        "materialization_moment": rec_id,
        "changed": prev_hash != r[0],
    }
    print(json.dumps(proof, ensure_ascii=False, indent=2))
    ok = proof["node_source_hash_equals_file"] and proof["node_source_has_restart_logic"]
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
