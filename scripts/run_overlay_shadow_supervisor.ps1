<#
    run_overlay_shadow_supervisor.ps1

    Supervisor sin privilegios de administrador para lanzar overlay shadow una
    vez al dia. No toca agente_bolsa.main schedule ni el runtime de trading.
#>

param(
    [string]$RunAt = "22:30",
    [string]$Start = "2020-01-01"
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "stack_common.ps1")

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DailyScript = Join-Path $Repo "scripts\run_overlay_shadow_daily.ps1"
$LogPath = Join-Path $Repo "data\logs\overlay_shadow_supervisor.log"

function Write-OverlayShadowSupervisorLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "s"
    Add-Content -Path $LogPath -Value "[$timestamp] $Message" -Encoding UTF8
}

New-Item -ItemType Directory -Force -Path (Split-Path $LogPath -Parent) | Out-Null

if (-not (Test-Path $DailyScript)) {
    Write-OverlayShadowSupervisorLog "ERROR daily_script_missing path=$DailyScript"
    exit 1
}

Write-OverlayShadowSupervisorLog "START overlay shadow supervisor run_at=$RunAt start=$Start"

$lockTaken = Acquire-StackSingleInstanceLock `
    -ServiceName "overlay_shadow_supervisor" `
    -CommandPattern "run_overlay_shadow_supervisor\.ps1" `
    -Log { param($Message) Write-OverlayShadowSupervisorLog $Message }
if (-not $lockTaken) {
    exit 0
}

try {
    while ($true) {
        $catchUp = Test-StackDailyCatchUpNeeded -TimeText $RunAt -HasTodayArtifact {
            param($RunDate)
            $dailyPath = Join-Path $Repo "data\research\overlay_shadow" ("overlay_shadow_{0}.json" -f $RunDate.ToString("yyyy-MM-dd"))
            return Test-Path $dailyPath
        }
        if ($catchUp.should_run) {
            Write-OverlayShadowSupervisorLog "CATCH_UP run_date=$($catchUp.today_run.ToString('yyyy-MM-dd'))"
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $DailyScript -Start $Start
            $exitCode = $LASTEXITCODE
            Write-OverlayShadowSupervisorLog "DONE catch_up exit_code=$exitCode"
        }
        $nextRun = $catchUp.next_run
        Write-OverlayShadowSupervisorLog "NEXT_RUN $($nextRun.ToString('s'))"
        while ((Get-Date) -lt $nextRun) {
            $remaining = [int]($nextRun - (Get-Date)).TotalSeconds
            Start-Sleep -Seconds ([Math]::Min([Math]::Max($remaining, 1), 300))
        }

        Write-OverlayShadowSupervisorLog "RUN daily_script"
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $DailyScript -Start $Start
        $exitCode = $LASTEXITCODE
        Write-OverlayShadowSupervisorLog "DONE daily_script exit_code=$exitCode"
    }
} finally {
    Release-StackSingleInstanceLock -ServiceName "overlay_shadow_supervisor" -Log { param($Message) Write-OverlayShadowSupervisorLog $Message }
}
