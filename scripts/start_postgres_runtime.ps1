[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot

& (Join-Path $PSScriptRoot 'use_local_postgres_runtime.ps1')

$env:PYTHONPATH = Join-Path $repo 'src'
Push-Location $repo
try {
    python -m kalshi_research_bot database-migrate
    if ($LASTEXITCODE -ne 0) {
        throw 'PostgreSQL migration check failed.'
    }
    python -m kalshi_research_bot database-status
    if ($LASTEXITCODE -ne 0) {
        throw 'PostgreSQL readiness check failed.'
    }
}
finally {
    Pop-Location
}
