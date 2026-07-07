@echo off
setlocal
set "REPO=%~dp0.."
set "PYTHONPATH=%REPO%\src"
if not exist "%REPO%\data\daemon" mkdir "%REPO%\data\daemon"
if "%~1"=="" (
  python -m kalshi_research_bot crypto-cycle --run-id crypto_private_20260704 >> "%REPO%\data\daemon\crypto_cycle.log" 2>&1
) else (
  python -m kalshi_research_bot crypto-cycle %* >> "%REPO%\data\daemon\crypto_cycle.log" 2>&1
)
