@echo off
title AutoTrader IA — Instalar inicio automatico
cd /d "%~dp0"

echo ========================================
echo  Registrando AutoTrader IA en el
echo  Programador de Tareas de Windows...
echo ========================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_install_task.ps1" -BotBat "%~dp0arrancar_bot.bat" -DashBat "%~dp0arrancar_dashboard.bat" 2>&1 | find "TASK_OK" >nul

if %ERRORLEVEL% EQU 0 (
    echo [OK] Dos tareas creadas:
    echo      - AutoTraderIA_Bot       arranca 1 min tras inicio de sesion
    echo      - AutoTraderIA_Dashboard arranca 1.5 min tras inicio de sesion
    echo.
    echo      Ambas se reactivan al desbloquear pantalla si se cerraron.
    echo      El dashboard estara siempre disponible desde el movil via Tailscale.
    echo.
    echo Para desinstalar: ejecuta desinstalar_inicio_automatico.bat
) else (
    echo [ERROR] Ejecuta como Administrador: click derecho -^> Ejecutar como administrador
)

echo.
pause
