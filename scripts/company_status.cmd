@echo off
setlocal
set "REPO=%~dp0.."
set "PYTHONPATH=%REPO%\src"
call "%REPO%\scripts\postgres_cli.cmd" company-status %*
