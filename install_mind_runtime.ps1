param(
  [string]$Graph = "mind_kernel_v0",
  [string]$Project = (Resolve-Path ".").Path,
  [string]$DaemonTaskName = "Mind Node Runtime",
  [string]$WatchdogTaskName = "Mind Node Runtime Watchdog"
)

$ErrorActionPreference = "Stop"
$Python = Join-Path $Project ".venv\Scripts\python.exe"
$WatchdogScript = Join-Path $Project "run_daemon_watchdog.ps1"

if (-not (Test-Path $Python)) {
  throw "Python virtuel introuvable: $Python. Créez .venv puis lancez pip install -e ."
}
if (-not (Test-Path $WatchdogScript)) {
  throw "Script watchdog introuvable: $WatchdogScript"
}

$DaemonArguments = "-m mind_node_runtime daemon --graph `"$Graph`" --repo `"$Project`""
$DaemonAction = New-ScheduledTaskAction `
  -Execute $Python `
  -Argument $DaemonArguments `
  -WorkingDirectory $Project
$DaemonTrigger = New-ScheduledTaskTrigger -AtLogOn
$DaemonSettings = New-ScheduledTaskSettingsSet `
  -RestartCount 999 `
  -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit (New-TimeSpan -Days 3650) `
  -StartWhenAvailable `
  -MultipleInstances IgnoreNew

Register-ScheduledTask `
  -TaskName $DaemonTaskName `
  -Action $DaemonAction `
  -Trigger $DaemonTrigger `
  -Settings $DaemonSettings `
  -Description "Maintient le daemon Mind vivant; les cadences métier sont lues dans FalkorDB." `
  -Force | Out-Null

$WatchdogArguments = "-NoProfile -ExecutionPolicy Bypass -File `"$WatchdogScript`" -Graph `"$Graph`" -Project `"$Project`" -DaemonTaskName `"$DaemonTaskName`""
$WatchdogAction = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument $WatchdogArguments `
  -WorkingDirectory $Project
$WatchdogTrigger = New-ScheduledTaskTrigger `
  -Once `
  -At (Get-Date).AddMinutes(1) `
  -RepetitionInterval (New-TimeSpan -Minutes 1) `
  -RepetitionDuration (New-TimeSpan -Days 3650)
$WatchdogSettings = New-ScheduledTaskSettingsSet `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
  -StartWhenAvailable `
  -MultipleInstances IgnoreNew

Register-ScheduledTask `
  -TaskName $WatchdogTaskName `
  -Action $WatchdogAction `
  -Trigger $WatchdogTrigger `
  -Settings $WatchdogSettings `
  -Description "Vérifie le heartbeat graphé du daemon et redémarre la tâche si la preuve est stale." `
  -Force | Out-Null

Start-ScheduledTask -TaskName $DaemonTaskName

Write-Host "Runtime installé et démarré."
Write-Host "Daemon   : $DaemonTaskName"
Write-Host "Watchdog : $WatchdogTaskName"
Write-Host "Graphe   : $Graph"
Write-Host "Projet   : $Project"
