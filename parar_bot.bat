@echo off
title AutoTrader IA — Parar bot
echo Parando AutoTrader IA bot...
taskkill /FI "WINDOWTITLE eq AutoTrader-Bot*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq AutoTrader-Dashboard*" /F >nul 2>&1
echo Bot y dashboard detenidos.
pause
