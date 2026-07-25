param(
  [string]$Project = (Resolve-Path ".").Path,
  [string]$LogonTaskName = "Mind MCP Endpoint",
  [string]$WatchdogTaskName = "Mind MCP Endpoint Watchdog"
)

# OS bootstrap only — no business logic here. The launcher is materialized from
# the graph node code:l2:mcp:endpoint-launcher:v0 and is the single authority on
# WHAT gets started. Windows merely keeps that launcher alive (mirrors
# install_mind_runtime.ps1 for the daemon).

$ErrorActionPreference = "Stop"
$Launcher = Join-Path $Project "scripts\mcp_endpoint_launcher.ps1"
if (-not (Test-Path $Launcher)) {
  throw "Launcher introuvable: $Launcher. Lancez d'abord: .\.venv\Scripts\python.exe agent1_persist_endpoint.py"
}

$LauncherArgs = "-WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File `"$Launcher`" -Project `"$Project`""

# 1. Logon task: ensure the endpoint is up when the user logs in.
$LogonAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $LauncherArgs -WorkingDirectory $Project
$LogonTrigger = New-ScheduledTaskTrigger -AtLogOn
$LogonSettings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
  -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $LogonTaskName -Action $LogonAction -Trigger $LogonTrigger `
  -Settings $LogonSettings `
  -Description "Démarre le serveur MCP public (server + ngrok + loop d'accessibilité) via le launcher matérialisé depuis le graphe." `
  -Force | Out-Null

# 2. Watchdog task: re-run the idempotent launcher every minute to self-heal.
$WatchTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
  -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Days 3650)
$WatchSettings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
  -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $WatchdogTaskName -Action $LogonAction -Trigger $WatchTrigger `
  -Settings $WatchSettings `
  -Description "Vérifie/relance le endpoint MCP chaque minute (launcher idempotent)." `
  -Force | Out-Null

Start-ScheduledTask -TaskName $LogonTaskName

Write-Host "Endpoint MCP persistant installé."
Write-Host "Logon    : $LogonTaskName"
Write-Host "Watchdog : $WatchdogTaskName"
Write-Host "Launcher : $Launcher"
Write-Host "URL      : https://trusted-magpie-social.ngrok-free.app"
