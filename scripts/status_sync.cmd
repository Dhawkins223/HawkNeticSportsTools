@echo off
setlocal
set "REPO=%~dp0.."
set "PYTHONPATH=%REPO%\src"
if not exist "%REPO%\data\daemon" mkdir "%REPO%\data\daemon"
call "%REPO%\scripts\postgres_cli.cmd" sync-status --asset-class crypto --run-id crypto_private_20260704 --stage "Stage 3A/4 Diagnosis" >> "%REPO%\data\daemon\status_sync.log" 2>&1
call "%REPO%\scripts\postgres_cli.cmd" sync-status --asset-class sports --run-id sports_private_20260704 --stage "Stage 3A" >> "%REPO%\data\daemon\status_sync.log" 2>&1
call "%REPO%\scripts\postgres_cli.cmd" sync-status --asset-class kalshi --run-id stage3a_20260703_170707 --stage "Stage 3B Passive" >> "%REPO%\data\daemon\status_sync.log" 2>&1
