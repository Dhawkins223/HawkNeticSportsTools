param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [int]$Port = 8765,
  [int]$MaxDataAgeSeconds = 900,
  [string]$HostName = "127.0.0.1",
  [string]$PublicIntel = "config\public_intel.local.json"
)

$ErrorActionPreference = "Stop"
$daemonDir = Join-Path $RepoRoot "data\daemon"
New-Item -ItemType Directory -Force -Path $daemonDir | Out-Null
$logPath = Join-Path $daemonDir "dashboard_watchdog.log"

function Write-WatchdogLog {
  param([string]$Message)
  $timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:sszzz"
  Add-Content -Path $logPath -Value "$timestamp $Message"
}

function Get-Listener {
  Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalAddress -in @("127.0.0.1", "0.0.0.0", "::", "::1") } |
    Select-Object -First 1
}

function Start-Dashboard {
  $script = Join-Path $RepoRoot "scripts\live.cmd"
  $publicIntelPath = Join-Path $RepoRoot $PublicIntel
  $args = "/c `"$script`" --host $HostName --port $Port --refresh-seconds 300 --leverage-target 0.75"
  if (Test-Path $publicIntelPath) {
    $args = "$args --public-intel `"$publicIntelPath`""
  }
  Start-Process -FilePath "cmd.exe" -ArgumentList $args -WorkingDirectory $RepoRoot -WindowStyle Hidden | Out-Null
  Write-WatchdogLog "started_dashboard port=$Port host=$HostName"
}

$listener = Get-Listener
if (-not $listener) {
  Start-Dashboard
  exit 0
}

$qualityUrl = "http://127.0.0.1:$Port/quality.json"
$refreshUrl = "http://127.0.0.1:$Port/refresh"
try {
  $quality = Invoke-RestMethod -Uri $qualityUrl -TimeoutSec 10
  $age = [int]($quality.data_age_seconds)
  if ($quality.status -ne "OK" -or $age -gt $MaxDataAgeSeconds) {
    Invoke-RestMethod -Uri $refreshUrl -Method Post -Body '{"reason":"watchdog_stale_data"}' -ContentType "application/json" -TimeoutSec 15 | Out-Null
    Write-WatchdogLog "refresh_requested status=$($quality.status) age_seconds=$age"
  } else {
    Write-WatchdogLog "healthy status=$($quality.status) age_seconds=$age"
  }
} catch {
  Write-WatchdogLog "quality_check_failed $($_.Exception.Message)"
  Start-Dashboard
}
