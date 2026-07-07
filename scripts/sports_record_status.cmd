@echo off
setlocal
set "REPO=%~dp0.."
set "PYTHONPATH=%REPO%\src"
if not exist "%REPO%\data\daemon" mkdir "%REPO%\data\daemon"
if "%~1"=="" (
  python -m kalshi_research_bot sports-record-status --run-id sports_private_20260704 --tail 5 >> "%REPO%\data\daemon\sports_record_status.log" 2>&1
) else (
  python -m kalshi_research_bot sports-record-status %* >> "%REPO%\data\daemon\sports_record_status.log" 2>&1
)
