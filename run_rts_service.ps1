# Coruscant RTS — resilient background runner.
# Keeps the simulation alive for days/weeks: restarts the server if it
# crashes, appends everything to a log, writes the chronicle.
#
# Foreground test:
#   powershell -ExecutionPolicy Bypass -File run_rts_service.ps1
#
# Auto-start at logon (run once, from this folder):
#   schtasks /Create /TN "CoruscantRTS" /SC ONLOGON /TR `
#     "powershell -WindowStyle Hidden -ExecutionPolicy Bypass -File '$PSScriptRoot\run_rts_service.ps1'"
#
# Remove:  schtasks /Delete /TN "CoruscantRTS" /F

$simDir = $PSScriptRoot
$logPath = Join-Path $simDir "rts_service.log"
$savePath = Join-Path $simDir "rts_save.json"

while ($true) {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logPath -Value "[$stamp] starting rts_server"

    $args = @(
        (Join-Path $simDir "rts_server.py"),
        "--port", "8780",
        "--speed", "3",
        "--chronicle", (Join-Path $simDir "chronicle.md")
    )
    # Discord/Telegram: set CORUSCANT_DISCORD_WEBHOOK / CORUSCANT_TELEGRAM_TOKEN /
    # CORUSCANT_TELEGRAM_CHAT as user environment variables and they are picked up.

    & python @args 2>&1 | ForEach-Object { Add-Content -Path $logPath -Value $_ }

    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logPath -Value "[$stamp] server exited, restarting in 10 s"
    Start-Sleep -Seconds 10
}
