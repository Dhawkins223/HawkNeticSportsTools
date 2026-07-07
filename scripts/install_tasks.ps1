param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$TaskPrefix = "KalshiResearchBot",
  [string]$CryptoRunId = "crypto_private_20260704",
  [string]$SportsRunId = "sports_private_20260704",
  [string]$KalshiRunId = "stage3a_20260703_170707",
  [int]$DashboardPort = 8765,
  [int]$CryptoMinutes = 15,
  [int]$SportsMinutes = 60,
  [int]$KalshiHours = 12,
  [string]$DailyBriefTime = "07:15",
  [string]$DailyDiagnosticsTime = "07:30",
  [string]$DailyFeatureExportTime = "07:45",
  [string]$DailyQaTime = "08:00",
  [string]$DailyArchiveTime = "08:30"
)

$ErrorActionPreference = "Stop"
$daemonDir = Join-Path $RepoRoot "data\daemon"
New-Item -ItemType Directory -Force -Path $daemonDir | Out-Null

function Register-Task {
  param(
    [string]$Name,
    [string]$Schedule,
    [string]$Modifier,
    [string]$Command
  )
  $taskName = "$TaskPrefix\$Name"
  $taskRun = $Command
  schtasks.exe /Create /F /TN $taskName /SC $Schedule /MO $Modifier /TR $taskRun | Out-Host
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to create scheduled task $taskName"
  }
}

function Register-DailyTask {
  param(
    [string]$Name,
    [string]$StartTime,
    [string]$Command
  )
  $taskName = "$TaskPrefix\$Name"
  schtasks.exe /Create /F /TN $taskName /SC DAILY /ST $StartTime /TR $Command | Out-Host
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to create scheduled task $taskName"
  }
}

Register-Task `
  -Name "DashboardWatchdog" `
  -Schedule "MINUTE" `
  -Modifier "5" `
  -Command "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$RepoRoot\scripts\dashboard_watchdog.ps1`" -Port $DashboardPort"

Register-Task `
  -Name "CryptoStage3A" `
  -Schedule "MINUTE" `
  -Modifier "$CryptoMinutes" `
  -Command "`"$RepoRoot\scripts\crypto_cycle.cmd`" --run-id $CryptoRunId"

Register-Task `
  -Name "SourceHealthSentinel" `
  -Schedule "MINUTE" `
  -Modifier "15" `
  -Command "`"$RepoRoot\scripts\source_health.cmd`""

Register-Task `
  -Name "SportsScraperStage3A" `
  -Schedule "MINUTE" `
  -Modifier "$SportsMinutes" `
  -Command "`"$RepoRoot\scripts\sports_cycle.cmd`" --run-id $SportsRunId"

Register-Task `
  -Name "StatusSyncHourly" `
  -Schedule "HOURLY" `
  -Modifier "1" `
  -Command "`"$RepoRoot\scripts\status_sync.cmd`""

Register-Task `
  -Name "KalshiPassiveCheck" `
  -Schedule "HOURLY" `
  -Modifier "$KalshiHours" `
  -Command "`"$RepoRoot\scripts\kalshi_passive_check.cmd`" --run-id $KalshiRunId"

Register-DailyTask `
  -Name "CompanyBriefDaily" `
  -StartTime $DailyBriefTime `
  -Command "`"$RepoRoot\scripts\company_brief.cmd`""

Register-DailyTask `
  -Name "CryptoDiagnosticsDaily" `
  -StartTime $DailyDiagnosticsTime `
  -Command "`"$RepoRoot\scripts\crypto_diagnostics.cmd`" --run-id $CryptoRunId"

Register-DailyTask `
  -Name "FeatureExportsDaily" `
  -StartTime $DailyFeatureExportTime `
  -Command "`"$RepoRoot\scripts\feature_exports.cmd`""

Register-DailyTask `
  -Name "QualityAuditDaily" `
  -StartTime $DailyQaTime `
  -Command "`"$RepoRoot\scripts\qa_daily.cmd`""

Register-DailyTask `
  -Name "ReportArchiveDaily" `
  -StartTime $DailyArchiveTime `
  -Command "`"$RepoRoot\scripts\archive_reports.cmd`""

Write-Host "Installed private local research tasks under $TaskPrefix."
Write-Host "No auto-trading, no auto-betting, and no Kalshi order-upload task was installed."
