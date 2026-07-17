@echo off
setlocal
set "REPO=%~dp0.."
set "PYTHONPATH=%REPO%\src"
set "RUN_ID=crypto_private_20260704"
if not exist "%REPO%\data\daemon" mkdir "%REPO%\data\daemon"
if /I "%~1"=="--run-id" (
  set "RUN_ID=%~2"
)
call "%REPO%\scripts\postgres_cli.cmd" crypto-stage4-diagnostic --run-id %RUN_ID% >> "%REPO%\data\daemon\crypto_diagnostics.log" 2>&1
