param(
  [string]$Graph = "mind_kernel_v0",
  [string]$Project = (Resolve-Path ".").Path,
  [string]$DaemonTaskName = "Mind Node Runtime"
)

# Hide console window immediately if running interactively
try {
  $Async = '[DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);'
  $Type = Add-Type -MemberDefinition $Async -Name "Win32ShowWindowAsyncWatchdog" -Namespace Win32Functions -PassThru -ErrorAction SilentlyContinue
  $hwnd = (Get-Process -Id $pid).MainWindowHandle
  if ($hwnd -ne [IntPtr]::Zero) {
    $Type::ShowWindow($hwnd, 0)
  }
} catch {}

$Python = Join-Path $Project ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
  exit 3
}

& $Python -m mind_node_runtime watchdog --graph $Graph
$Code = $LASTEXITCODE

if ($Code -eq 2) {
  try {
    Stop-ScheduledTask -TaskName $DaemonTaskName -ErrorAction Stop
    Start-ScheduledTask -TaskName $DaemonTaskName -ErrorAction Stop
  } catch {
    $running = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match "mind_node_runtime daemon" }
    if (-not $running) {
      Start-Process -FilePath $Python -ArgumentList "-m mind_node_runtime daemon --graph `"$Graph`" --repo `"$Project`"" -WorkingDirectory $Project -WindowStyle Hidden
    }
  }
  exit 0
}

exit $Code
