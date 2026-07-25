# MATERIALIZED FROM GRAPH — code:l2:mcp:endpoint-launcher:v0
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
