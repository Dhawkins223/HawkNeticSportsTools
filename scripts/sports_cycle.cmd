@echo off
setlocal
set "REPO=%~dp0.."
set "PYTHONPATH=%REPO%\src"
if not exist "%REPO%\data\daemon" mkdir "%REPO%\data\daemon"
if "%~1"=="" (
  python -m kalshi_research_bot sports-cycle --run-id sports_private_20260704 >> "%REPO%\data\daemon\sports_cycle.log" 2>&1
) else (
  python -m kalshi_research_bot sports-cycle %* >> "%REPO%\data\daemon\sports_cycle.log" 2>&1
)
