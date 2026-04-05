@echo off
cd /d "%~dp0"
call venv\Scripts\activate
echo Iniciando AutoTrader IA en modo PAPER TRADING...
python main.py
pause
