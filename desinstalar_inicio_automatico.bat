@echo off
title AutoTrader IA — Desinstalar inicio automatico

echo Eliminando tareas del Programador de Tareas...
schtasks /Delete /TN "AutoTraderIA_Bot" /F >nul 2>&1
schtasks /Delete /TN "AutoTraderIA_Dashboard" /F >nul 2>&1

echo [OK] Tareas eliminadas. Bot y dashboard ya no arrancan automaticamente.
echo.
pause
