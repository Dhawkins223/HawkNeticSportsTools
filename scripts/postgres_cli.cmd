@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_postgres_cli.ps1" %*
exit /b %ERRORLEVEL%
