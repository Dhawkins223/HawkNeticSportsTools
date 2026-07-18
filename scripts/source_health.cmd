@echo off
setlocal
set "REPO=%~dp0.."
set "PYTHONPATH=%REPO%\src"
if not exist "%REPO%\data\daemon" mkdir "%REPO%\data\daemon"
call "%REPO%\scripts\postgres_cli.cmd" data-quality >> "%REPO%\data\daemon\source_quality.log" 2>&1
call "%REPO%\scripts\postgres_cli.cmd" daemon-status >> "%REPO%\data\daemon\source_health.log" 2>&1
