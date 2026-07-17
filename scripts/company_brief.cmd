@echo off
setlocal
set "REPO=%~dp0.."
set "PYTHONPATH=%REPO%\src"
if not exist "%REPO%\data\daemon" mkdir "%REPO%\data\daemon"
call "%REPO%\scripts\postgres_cli.cmd" company-status > "%REPO%\data\daemon\company_brief.txt" 2>&1
call "%REPO%\scripts\postgres_cli.cmd" daemon-status >> "%REPO%\data\daemon\company_brief.txt" 2>&1
