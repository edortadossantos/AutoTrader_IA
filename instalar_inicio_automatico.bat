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

REM Usar PowerShell para crear tarea con multiples triggers:
REM   1. Al iniciar sesion
REM   2. Al desbloquear pantalla (cubre vuelta de suspension/hibernacion)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$action = New-ScheduledTaskAction -Execute '\"%~dp0arrancar_bot.bat\"';" ^
  "$t1 = New-ScheduledTaskTrigger -AtLogOn;" ^
  "$t1.Delay = 'PT1M';" ^
  "$t2 = New-ScheduledTaskTrigger -AtLogOn;" ^
  "$t2.StateChange = 8;" ^
  "$t2.GetType().GetProperty('CimInstanceProperties') | Out-Null;" ^
  "$xml = @'" ^
  "<?xml version='1.0' encoding='UTF-16'?>" ^
  "<Task version='1.2' xmlns='http://schemas.microsoft.com/windows/2004/02/mit/task'>" ^
  "  <Triggers>" ^
  "    <LogonTrigger><Delay>PT1M</Delay><UserId>%USERNAME%</UserId></LogonTrigger>" ^
  "    <SessionStateChangeTrigger><StateChange>SessionUnlock</StateChange><UserId>%USERNAME%</UserId></SessionStateChangeTrigger>" ^
  "  </Triggers>" ^
  "  <Principals><Principal id='Author'><UserId>%USERNAME%</UserId><RunLevel>HighestAvailable</RunLevel></Principal></Principals>" ^
  "  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><ExecutionTimeLimit>PT0S</ExecutionTimeLimit><Priority>7</Priority></Settings>" ^
  "  <Actions Context='Author'><Exec><Command>%~dp0arrancar_bot.bat</Command></Exec></Actions>" ^
  "</Task>" ^
  "'@;" ^
  "Register-ScheduledTask -TaskName '%TASK_NAME%' -Xml $xml -Force | Out-Null;" ^
  "Write-Host 'OK'"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [OK] Tarea creada con 2 triggers:
    echo      1. Al iniciar sesion en Windows
    echo      2. Al desbloquear la pantalla (cubre suspension e hibernacion)
    echo.
    echo      El bot no arranca doble — si ya esta corriendo, lo detecta y sale.
    echo.
    echo Para desinstalarlo: ejecuta desinstalar_inicio_automatico.bat
) else (
    echo.
    echo [ERROR] Ejecuta este archivo como Administrador
    echo         (click derecho → Ejecutar como administrador)
)

echo.
pause
