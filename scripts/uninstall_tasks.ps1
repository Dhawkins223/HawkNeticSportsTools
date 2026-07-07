param(
  [string]$TaskPrefix = "KalshiResearchBot"
)

$taskNames = @(
  "$TaskPrefix\DashboardWatchdog",
  "$TaskPrefix\CryptoStage3A",
  "$TaskPrefix\SourceHealthSentinel",
  "$TaskPrefix\SportsScraperStage3A",
  "$TaskPrefix\StatusSyncHourly",
  "$TaskPrefix\KalshiPassiveCheck",
  "$TaskPrefix\CompanyBriefDaily",
  "$TaskPrefix\CryptoDiagnosticsDaily",
  "$TaskPrefix\FeatureExportsDaily",
  "$TaskPrefix\QualityAuditDaily",
  "$TaskPrefix\ReportArchiveDaily"
)

foreach ($taskName in $taskNames) {
  schtasks.exe /Delete /F /TN $taskName 2>$null | Out-Null
}

Write-Host "Removed private local research tasks under $TaskPrefix if they existed."
