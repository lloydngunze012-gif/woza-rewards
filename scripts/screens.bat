@echo off
setlocal
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\screenshots.py %*
) else (
  python scripts\screenshots.py %*
)
