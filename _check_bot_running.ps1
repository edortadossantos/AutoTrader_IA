$pidFile = Join-Path $PSScriptRoot "bot.pid"

if (Test-Path $pidFile) {
    $savedPid = [int](Get-Content $pidFile -Raw).Trim()
    $proc = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
    if ($proc -and $proc.Name -match 'python') {
        exit 1  # bot corriendo
    }
    # PID obsoleto — limpiar
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}
exit 0  # no hay bot
