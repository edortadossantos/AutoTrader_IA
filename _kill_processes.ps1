$pidFile = Join-Path $PSScriptRoot "bot.pid"

# Matar bot por PID file si existe
if (Test-Path $pidFile) {
    $savedPid = [int](Get-Content $pidFile -Raw).Trim()
    $proc = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host ("Parando bot PID " + $savedPid)
        Stop-Process -Id $savedPid -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

# Matar dashboard por puerto 5000
$conn = netstat -ano | Select-String '0\.0\.0\.0:5000\s+\S+\s+LISTENING\s+(\d+)'
if ($conn) {
    $dashPid = [int]$conn.Matches[0].Groups[1].Value
    Write-Host ("Parando dashboard PID " + $dashPid)
    Stop-Process -Id $dashPid -Force -ErrorAction SilentlyContinue
}
