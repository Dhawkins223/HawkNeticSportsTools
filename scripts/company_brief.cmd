@echo off
setlocal
set "REPO=%~dp0.."
set "PYTHONPATH=%REPO%\src"
if not exist "%REPO%\data\daemon" mkdir "%REPO%\data\daemon"
python -m kalshi_research_bot company-status > "%REPO%\data\daemon\company_brief.txt" 2>&1
python -m kalshi_research_bot daemon-status >> "%REPO%\data\daemon\company_brief.txt" 2>&1
