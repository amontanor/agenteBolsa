<#
    run_telegram_radar_supervisor.ps1

    Supervisor sin privilegios de administrador para lanzar el radar Telegram
    una vez al dia. No toca el scheduler operativo de agente_bolsa.main schedule.
#>

param(
    [string]$RunAt = "23:00"
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "stack_common.ps1")

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DailyScript = Join-Path $Repo "scripts\run_telegram_radar_daily.ps1"
$LogPath = Join-Path $Repo "data\logs\telegram_radar_supervisor.log"

function Write-SupervisorLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "s"
    Add-Content -Path $LogPath -Value "[$timestamp] $Message" -Encoding UTF8
}

function Get-NextRunAt {
    param([string]$TimeText)
    $parts = $TimeText.Split(":")
    if ($parts.Count -ne 2) {
        throw "RunAt invalido. Usa HH:mm, por ejemplo 23:00."
    }
    $hour = [int]$parts[0]
    $minute = [int]$parts[1]
    if ($hour -lt 0 -or $hour -gt 23 -or $minute -lt 0 -or $minute -gt 59) {
        throw "RunAt invalido. Usa HH:mm en formato 24h."
    }
    $now = Get-Date
    $candidate = Get-Date -Hour $hour -Minute $minute -Second 0
    if ($candidate -le $now) {
        $candidate = $candidate.AddDays(1)
    }
    return $candidate
}

New-Item -ItemType Directory -Force -Path (Split-Path $LogPath -Parent) | Out-Null

if (-not (Test-Path $DailyScript)) {
    Write-SupervisorLog "ERROR daily_script_missing path=$DailyScript"
    exit 1
}

Write-SupervisorLog "START telegram radar supervisor run_at=$RunAt"

$lockTaken = Acquire-StackSingleInstanceLock `
    -ServiceName "telegram_radar_supervisor" `
    -CommandPattern "run_telegram_radar_supervisor\.ps1" `
    -Log { param($Message) Write-SupervisorLog $Message }
if (-not $lockTaken) {
    exit 0
}

try {
    while ($true) {
        $nextRun = Get-NextRunAt -TimeText $RunAt
        Write-SupervisorLog "NEXT_RUN $($nextRun.ToString('s'))"
        while ((Get-Date) -lt $nextRun) {
            $remaining = [int]($nextRun - (Get-Date)).TotalSeconds
            Start-Sleep -Seconds ([Math]::Min([Math]::Max($remaining, 1), 300))
        }

        Write-SupervisorLog "RUN daily_script"
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $DailyScript
        $exitCode = $LASTEXITCODE
        Write-SupervisorLog "DONE daily_script exit_code=$exitCode"
    }
} finally {
    Release-StackSingleInstanceLock -ServiceName "telegram_radar_supervisor" -Log { param($Message) Write-SupervisorLog $Message }
}
