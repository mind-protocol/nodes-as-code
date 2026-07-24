param(
  [string]$DaemonTaskName = "Mind Node Runtime",
  [string]$WatchdogTaskName = "Mind Node Runtime Watchdog"
)

Unregister-ScheduledTask -TaskName $WatchdogTaskName -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $DaemonTaskName -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Tâches Mind supprimées."
