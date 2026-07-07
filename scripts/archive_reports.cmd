@echo off
setlocal
set "REPO=%~dp0.."
set "PYTHONPATH=%REPO%\src"
if not exist "%REPO%\data\daemon" mkdir "%REPO%\data\daemon"
python -m kalshi_research_bot archive-reports >> "%REPO%\data\daemon\archive_reports.log" 2>&1
