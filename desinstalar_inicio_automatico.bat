@echo off
title AutoTrader IA — Desinstalar inicio automatico

set "TASK_NAME=AutoTraderIA_Bot"

echo Eliminando tarea del Programador de Tareas...
schtasks /Delete /TN "%TASK_NAME%" /F

if %ERRORLEVEL% EQU 0 (
    echo [OK] Tarea eliminada. El bot ya no arrancara automaticamente.
) else (
    echo [INFO] La tarea no existia o ya estaba eliminada.
)

echo.
pause
