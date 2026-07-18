@echo off
setlocal
set "REPO=%~dp0.."
set "PYTHONPATH=%REPO%\src"
python -m kalshi_research_bot paper --refresh-seconds 300 %*
