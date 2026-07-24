param(
  [string]$Graph = "mind_kernel_v0",
  [string]$Project = (Resolve-Path ".").Path,
  [string]$DaemonTaskName = "Mind Node Runtime"
)

$Python = Join-Path $Project ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
  exit 3
}

& $Python -m mind_node_runtime watchdog --graph $Graph
$Code = $LASTEXITCODE

if ($Code -eq 2) {
  Stop-ScheduledTask -TaskName $DaemonTaskName -ErrorAction SilentlyContinue
  Start-ScheduledTask -TaskName $DaemonTaskName
  exit 0
}

exit $Code
