$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
& (Join-Path $PSScriptRoot 'run_postgres_cli.ps1') demo
exit $LASTEXITCODE
