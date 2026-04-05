@echo off
title AutoTrader IA — Dashboard
cd /d "%~dp0"

if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

echo Abriendo dashboard en http://localhost:5000 ...
start "" "http://localhost:5000"
python web_dashboard.py
