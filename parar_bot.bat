@echo off
title AutoTrader IA - Parar bot
echo Parando AutoTrader IA...

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_kill_processes.ps1"

echo Bot y dashboard detenidos.
pause
