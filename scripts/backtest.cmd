@echo off
set PYTHONPATH=%~dp0..\src
python -m kalshi_research_bot backtest %*
