@echo off
title AutoTrader IA — Instalar inicio automatico
cd /d "%~dp0"

echo ========================================
echo  Registrando AutoTrader IA en el
echo  Programador de Tareas de Windows...
echo ========================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_install_task.ps1" -BatPath "%~dp0arrancar_bot.bat" 2>&1 | find "TASK_OK" >nul

if %ERRORLEVEL% EQU 0 (
    echo [OK] Tarea creada con 2 triggers:
    echo      1. Al iniciar sesion en Windows (con 1 min de espera)
    echo      2. Al desbloquear pantalla (cubre suspension e hibernacion)
    echo.
    echo      Si el bot ya esta corriendo no arranca una segunda instancia.
    echo.
    echo Para desinstalarlo: ejecuta desinstalar_inicio_automatico.bat
) else (
    echo [ERROR] Ejecuta este archivo como Administrador:
    echo         click derecho -^> Ejecutar como administrador
)

echo.
pause
