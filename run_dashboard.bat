@echo off
cd /d "%~dp0"
call venv\Scripts\activate
echo Abriendo dashboard en http://localhost:5000 ...
python web_dashboard.py
pause
