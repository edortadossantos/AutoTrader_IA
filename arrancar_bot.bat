@echo off
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_check_bot_running.ps1" >nul 2>&1
if %ERRORLEVEL% EQU 1 (
    exit /b 0
)

powershell -NoProfile -Command "Start-Process '%~dp0venv\Scripts\python.exe' -ArgumentList 'main.py' -WorkingDirectory '%~dp0' -WindowStyle Hidden"
powershell -NoProfile -Command "Start-Process '%~dp0venv\Scripts\python.exe' -ArgumentList 'web_dashboard.py' -WorkingDirectory '%~dp0' -WindowStyle Hidden"
