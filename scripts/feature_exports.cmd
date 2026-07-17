@echo off
setlocal
set "REPO=%~dp0.."
set "PYTHONPATH=%REPO%\src"
if not exist "%REPO%\data\daemon" mkdir "%REPO%\data\daemon"
call "%REPO%\scripts\postgres_cli.cmd" crypto-export-features --run-id crypto_private_20260704 >> "%REPO%\data\daemon\feature_exports.log" 2>&1
call "%REPO%\scripts\postgres_cli.cmd" sports-export-features --run-id sports_private_20260704 >> "%REPO%\data\daemon\feature_exports.log" 2>&1
