@echo off
setlocal
set "REPO=%~dp0.."
if not exist "%REPO%\data\daemon" mkdir "%REPO%\data\daemon"
call "%REPO%\scripts\test.cmd" >> "%REPO%\data\daemon\qa_daily.log" 2>&1
