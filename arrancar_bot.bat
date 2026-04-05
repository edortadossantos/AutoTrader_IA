@echo off
title AutoTrader-Bot
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_check_bot_running.ps1" >nul 2>&1
if %ERRORLEVEL% EQU 1 (
    exit /b 0
)

if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

start "AutoTrader-Bot" /MIN python main.py
