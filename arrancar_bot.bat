@echo off
title AutoTrader IA — Bot
cd /d "%~dp0"

echo ========================================
echo  AutoTrader IA — Arrancando bot...
echo ========================================

REM Activar entorno virtual si existe
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

REM Arrancar el bot en segundo plano (minimizado)
start "AutoTrader-Bot" /MIN python main.py

echo Bot arrancado en segundo plano.
echo Para verlo: busca la ventana "AutoTrader-Bot" en la barra de tareas.
echo Para pararlo: ejecuta parar_bot.bat
echo.
pause
