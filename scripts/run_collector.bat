@echo off
REM Single-shot collection for Windows Task Scheduler.
REM Schedule this to run every 1–5 minutes.
cd /d "%~dp0\.."
".venv\Scripts\python.exe" -m hl_swing_bot.collector --once
