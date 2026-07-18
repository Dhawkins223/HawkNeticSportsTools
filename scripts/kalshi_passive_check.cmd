@echo off
setlocal
set "REPO=%~dp0.."
set "PYTHONPATH=%REPO%\src"
set "RUN_ID=stage3a_20260703_170707"
if not exist "%REPO%\data\daemon" mkdir "%REPO%\data\daemon"
if /I "%~1"=="--run-id" (
  set "RUN_ID=%~2"
)
python -m kalshi_research_bot paper-settle-kalshi --run-id %RUN_ID% >> "%REPO%\data\daemon\kalshi_passive_check.log" 2>&1
python -m kalshi_research_bot paper-report --run-id %RUN_ID% >> "%REPO%\data\daemon\kalshi_passive_check.log" 2>&1
python -m kalshi_research_bot paper-stage3b-audit --run-id %RUN_ID% >> "%REPO%\data\daemon\kalshi_passive_check.log" 2>&1
