@echo off
title AutoTrader-Dashboard
cd /d "%~dp0"

REM Si el puerto 5000 ya está escuchando, ya hay una instancia corriendo
netstat -ano | find "0.0.0.0:5000" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    exit /b 0
)

if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

python web_dashboard.py
