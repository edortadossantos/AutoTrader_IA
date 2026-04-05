@echo off
title AutoTrader IA — Instalar inicio automatico
cd /d "%~dp0"

set "TASK_NAME=AutoTraderIA_Bot"
set "BAT_PATH=%~dp0arrancar_bot.bat"

echo ========================================
echo  Registrando AutoTrader IA en el
echo  Programador de Tareas de Windows...
echo ========================================
echo.

REM Eliminar tarea anterior si existe
schtasks /Delete /TN "%TASK_NAME%" /F >nul 2>&1

REM Crear tarea: arrancar el bot al iniciar sesion del usuario actual
schtasks /Create ^
  /TN "%TASK_NAME%" ^
  /TR "\"%BAT_PATH%\"" ^
  /SC ONLOGON ^
  /RU "%USERNAME%" ^
  /RL HIGHEST ^
  /DELAY 0001:00 ^
  /F

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [OK] Tarea creada correctamente.
    echo      El bot arrancara automaticamente cada vez que
    echo      inicies sesion en Windows.
    echo.
    echo      - El bot duerme cuando la bolsa esta cerrada (0%% CPU)
    echo      - Se activa solo cuando NYSE abre (L-V 15:30-22:00 hora ES verano)
    echo      - El dashboard lo abres cuando quieras con arrancar_dashboard.bat
    echo.
    echo Para desinstalarlo: ejecuta desinstalar_inicio_automatico.bat
) else (
    echo.
    echo [ERROR] No se pudo crear la tarea. Ejecuta este archivo
    echo         como Administrador (click derecho → Ejecutar como admin).
)

echo.
pause
