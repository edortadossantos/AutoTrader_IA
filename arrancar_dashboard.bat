@echo off
title AutoTrader-Dashboard
cd /d "%~dp0"

REM Si ya está corriendo, no arrancar otra instancia
tasklist /FI "WINDOWTITLE eq AutoTrader-Dashboard" 2>nul | find "python.exe" >nul
if %ERRORLEVEL% EQU 0 (
    exit /b 0
)

if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

python web_dashboard.py
