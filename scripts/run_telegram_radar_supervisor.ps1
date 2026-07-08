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
        $catchUp = Test-StackDailyCatchUpNeeded -TimeText $RunAt -HasTodayArtifact {
            param($RunDate)
            $reportPath = Join-Path $Repo "data\research\telegram\reports" ("radar_{0}.md" -f $RunDate.ToString("yyyy-MM-dd"))
            return Test-Path $reportPath
        }
        if ($catchUp.should_run) {
            Write-SupervisorLog "CATCH_UP run_date=$($catchUp.today_run.ToString('yyyy-MM-dd'))"
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $DailyScript
            $exitCode = $LASTEXITCODE
            Write-SupervisorLog "DONE catch_up exit_code=$exitCode"
        }
        $nextRun = $catchUp.next_run
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
