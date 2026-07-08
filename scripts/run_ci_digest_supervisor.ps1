<#
    run_ci_digest_supervisor.ps1

    Supervisor sin privilegios de administrador para lanzar el digest de mejora
    continua una vez al dia. No toca agente_bolsa.main schedule ni el runtime de
    trading.
#>

param(
    [string]$RunAt = "08:30",
    [int]$Days = 1
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "stack_common.ps1")

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DailyScript = Join-Path $Repo "scripts\run_ci_digest_daily.ps1"
$LogPath = Join-Path $Repo "data\logs\ci_digest_supervisor.log"
$ReportDir = Join-Path $Repo "data\reports"

function Write-CiDigestSupervisorLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "s"
    Add-Content -Path $LogPath -Value "[$timestamp] $Message" -Encoding UTF8
}

New-Item -ItemType Directory -Force -Path (Split-Path $LogPath -Parent) | Out-Null

if (-not (Test-Path $DailyScript)) {
    Write-CiDigestSupervisorLog "ERROR daily_script_missing path=$DailyScript"
    exit 1
}

Write-CiDigestSupervisorLog "START ci digest supervisor run_at=$RunAt days=$Days"

$lockTaken = Acquire-StackSingleInstanceLock `
    -ServiceName "ci_digest_supervisor" `
    -CommandPattern "run_ci_digest_supervisor\.ps1" `
    -Log { param($Message) Write-CiDigestSupervisorLog $Message }
if (-not $lockTaken) {
    exit 0
}

try {
    while ($true) {
        $catchUp = Test-StackDailyCatchUpNeeded -TimeText $RunAt -HasTodayArtifact {
            param($RunDate)
            $reportPath = Join-Path $ReportDir ("ci_digest_{0}.md" -f $RunDate.ToString("yyyy-MM-dd"))
            return Test-Path $reportPath
        }
        if ($catchUp.should_run) {
            Write-CiDigestSupervisorLog "CATCH_UP run_date=$($catchUp.today_run.ToString('yyyy-MM-dd'))"
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $DailyScript -Days $Days
            $exitCode = $LASTEXITCODE
            Write-CiDigestSupervisorLog "DONE catch_up exit_code=$exitCode"
        }
        $nextRun = $catchUp.next_run
        Write-CiDigestSupervisorLog "NEXT_RUN $($nextRun.ToString('s'))"
        while ((Get-Date) -lt $nextRun) {
            $remaining = [int]($nextRun - (Get-Date)).TotalSeconds
            Start-Sleep -Seconds ([Math]::Min([Math]::Max($remaining, 1), 300))
        }

        Write-CiDigestSupervisorLog "RUN daily_script"
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $DailyScript -Days $Days
        $exitCode = $LASTEXITCODE
        Write-CiDigestSupervisorLog "DONE daily_script exit_code=$exitCode"
    }
} finally {
    Release-StackSingleInstanceLock -ServiceName "ci_digest_supervisor" -Log { param($Message) Write-CiDigestSupervisorLog $Message }
}
