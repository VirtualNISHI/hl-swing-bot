@echo off
REM Continuous loop mode (polls every 60s by default). Keep this window open.
cd /d "%~dp0\.."
".venv\Scripts\python.exe" -m hl_swing_bot.collector --interval 60
