[CmdletBinding()]
param(
    [Parameter(Mandatory, Position = 0)]
    [string]$Command,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CommandArguments
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot

& (Join-Path $PSScriptRoot 'use_local_postgres_runtime.ps1')
$env:PYTHONPATH = Join-Path $repo 'src'

Push-Location $repo
try {
    if ($Command -ne 'database-migrate') {
        & python -m kalshi_research_bot database-migrate
        if ($LASTEXITCODE -ne 0) {
            throw 'PostgreSQL migration check failed.'
        }
    }

    & python -m kalshi_research_bot $Command @CommandArguments
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}
