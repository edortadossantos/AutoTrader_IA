param([string]$BotBat, [string]$DashBat)

function Register-AutoTraderTask {
    param([string]$TaskName, [string]$BatPath, [string]$DelayBot)

    $xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <LogonTrigger>
      <Delay>$DelayBot</Delay>
      <UserId>$env:USERNAME</UserId>
    </LogonTrigger>
    <SessionStateChangeTrigger>
      <StateChange>SessionUnlock</StateChange>
      <UserId>$env:USERNAME</UserId>
    </SessionStateChangeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$env:USERNAME</UserId>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$BatPath</Command>
    </Exec>
  </Actions>
</Task>
"@
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $TaskName -Xml $xml -Force | Out-Null
}

Register-AutoTraderTask -TaskName "AutoTraderIA_Bot"       -BatPath $BotBat  -DelayBot "PT1M"
Register-AutoTraderTask -TaskName "AutoTraderIA_Dashboard" -BatPath $DashBat -DelayBot "PT1M30S"

Write-Host "TASK_OK"
