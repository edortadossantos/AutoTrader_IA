@echo off
title AutoTrader IA — Bot
cd /d "%~dp0"

REM Si ya hay una instancia de main.py corriendo, no arrancar otra
tasklist /FI "IMAGENAME eq python.exe" /FI "WINDOWTITLE eq AutoTrader-Bot*" 2>nul | find "python.exe" >nul
if %ERRORLEVEL% EQU 0 (
    echo Bot ya en ejecucion. No se arranca una segunda instancia.
    exit /b 0
)

REM Comprobacion alternativa por nombre de ventana
tasklist /FI "WINDOWTITLE eq AutoTrader-Bot" 2>nul | find "python.exe" >nul
if %ERRORLEVEL% EQU 0 (
    exit /b 0
)

if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

start "AutoTrader-Bot" /MIN python main.py
