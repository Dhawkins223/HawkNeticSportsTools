[CmdletBinding()]
param(
    [switch]$TestMode,
    [string]$TestSchema = ""
)

$ErrorActionPreference = 'Stop'

$platformRoot = if ($env:GOOSE_PLATFORM_ROOT) {
    $env:GOOSE_PLATFORM_ROOT
}
else {
    Join-Path $env:USERPROFILE 'goose-ai-platform'
}
$startScript = Join-Path $platformRoot 'scripts\start-postgres.ps1'
$runtimeEnv = Join-Path $platformRoot '.state\postgres\goose-postgres.env'

if (-not (Test-Path -LiteralPath $startScript)) {
    throw "Local PostgreSQL launcher is missing: $startScript"
}

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $startScript | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'Local PostgreSQL startup failed.'
}
if (-not (Test-Path -LiteralPath $runtimeEnv)) {
    throw 'Local PostgreSQL credentials were not created.'
}

Get-Content -LiteralPath $runtimeEnv | ForEach-Object {
    if ($_ -match '^(?<name>[^=]+)=(?<value>.*)$') {
        Set-Item -Path ("Env:" + $Matches.name) -Value $Matches.value
    }
}

$urlNames = @{
    Write = if ($env:HAWKNETIC_POSTGRES_WRITE_URL) { 'HAWKNETIC_POSTGRES_WRITE_URL' } else { 'POSTGRES_WRITE_URL' }
    Migration = if ($env:HAWKNETIC_POSTGRES_MIGRATION_URL) { 'HAWKNETIC_POSTGRES_MIGRATION_URL' } else { 'POSTGRES_MIGRATION_URL' }
    ReadOnly = if ($env:HAWKNETIC_POSTGRES_READONLY_URL) { 'HAWKNETIC_POSTGRES_READONLY_URL' } else { 'POSTGRES_READONLY_URL' }
}

foreach ($required in $urlNames.Values) {
    if (-not (Get-Item -Path ("Env:" + $required) -ErrorAction SilentlyContinue).Value) {
        throw "Local PostgreSQL runtime is missing $required."
    }
}

$env:DATABASE_BACKEND = 'postgres'
$env:DATABASE_URL = (Get-Item -Path ("Env:" + $urlNames.Write)).Value
$env:DATABASE_MIGRATION_URL = (Get-Item -Path ("Env:" + $urlNames.Migration)).Value
$env:DATABASE_SCHEMA = 'public'
$env:DATABASE_MIGRATION_MODE = 'apply'

if ($TestMode) {
    $env:DATABASE_URL = (Get-Item -Path ("Env:" + $urlNames.Migration)).Value
    if (-not $TestSchema) {
        $TestSchema = "test_suite_$PID"
    }
    if ($TestSchema -notmatch '^[a-z][a-z0-9_]{0,62}$') {
        throw 'Test PostgreSQL schema name is invalid.'
    }
    $env:DATABASE_SCHEMA = $TestSchema
    $env:HAWKNETIC_TEST_POSTGRES_SCHEMAS = 'true'
}
else {
    Remove-Item Env:HAWKNETIC_TEST_POSTGRES_SCHEMAS -ErrorAction SilentlyContinue
}

Write-Output 'Local PostgreSQL runtime: ready.'
