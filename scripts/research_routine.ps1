param(
  [ValidateSet("status", "once")]
  [string]$Action = "status",
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [switch]$IncludeExternalSources
)

$ErrorActionPreference = "Stop"
$runtimeScript = Join-Path $PSScriptRoot "use_local_postgres_runtime.ps1"
& $runtimeScript
$ErrorActionPreference = "Continue"
$env:PYTHONPATH = Join-Path $RepoRoot "src"

function Invoke-ResearchCommand {
  param([string[]]$Arguments)
  & python -m kalshi_research_bot @Arguments | Out-Host
  $exitCode = $LASTEXITCODE
  return [int]$exitCode
}

Push-Location $RepoRoot
try {
  if ($Action -eq "status") {
    Write-Host "=== Worker and research status ==="
    Invoke-ResearchCommand @("worker-status") | Out-Null
    Write-Host "`n=== Connector status ==="
    Invoke-ResearchCommand @("connectors-status") | Out-Null
    Write-Host "`n=== Queued operator messages ==="
    Invoke-ResearchCommand @("operator-message-list", "--status", "queued", "--limit", "20") | Out-Null
    exit 0
  }

  $services = @(
    "kalshi-market-ingestion",
    "crypto-research",
    "sports-research",
    "settlement-worker",
    "reporting-evaluation"
  )
  if ($IncludeExternalSources) {
    $services = @("external-source-ingestion") + $services
  }

  $failures = @()
  foreach ($service in $services) {
    Write-Host "`n=== $service ==="
    $exitCode = Invoke-ResearchCommand @("worker", "--service", $service, "--once")
    if ($exitCode -ne 0) {
      $failures += $service
      Write-Warning "$service failed or was blocked; remaining services will continue."
    }
  }

  Write-Host "`n=== Final status ==="
  Invoke-ResearchCommand @("worker-status") | Out-Null
  if ($failures.Count -gt 0) {
    Write-Warning ("Routine completed with blocked/failed services: " + ($failures -join ", "))
    exit 1
  }
  Write-Host "Research routine completed. No trading or order-upload action was available."
  exit 0
}
finally {
  Pop-Location
}
