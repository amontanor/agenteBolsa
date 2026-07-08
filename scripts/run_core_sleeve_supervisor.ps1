<#
    run_core_sleeve_supervisor.ps1

    Supervisor sin privilegios de administrador para lanzar la manga core SPY
    una vez al dia. No toca agente_bolsa.main schedule ni el runtime de trading.
#>

param(
    [string]$RunAt = "22:15",
    [string]$Config = "",
    [string]$LogDir = ""
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "stack_common.ps1")

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DailyScript = Join-Path $Repo "scripts\run_core_sleeve_daily.ps1"
$RunLog = Join-Path $Repo "data\logs\core_sleeve_supervisor.log"

function Write-CoreSleeveSupervisorLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "s"
    Add-Content -Path $RunLog -Value "[$timestamp] $Message" -Encoding UTF8
}

New-Item -ItemType Directory -Force -Path (Split-Path $RunLog -Parent) | Out-Null

if (-not (Test-Path $DailyScript)) {
    Write-CoreSleeveSupervisorLog "ERROR daily_script_missing path=$DailyScript"
    exit 1
}

Write-CoreSleeveSupervisorLog "START core sleeve supervisor run_at=$RunAt"

$lockTaken = Acquire-StackSingleInstanceLock `
    -ServiceName "core_sleeve_supervisor" `
    -CommandPattern "run_core_sleeve_supervisor\.ps1" `
    -Log { param($Message) Write-CoreSleeveSupervisorLog $Message }
if (-not $lockTaken) {
    exit 0
}

try {
    while ($true) {
        $catchUp = Test-StackDailyCatchUpNeeded -TimeText $RunAt -HasTodayArtifact {
            param($RunDate)
            $artifactDir = if ($LogDir) { $LogDir } else { Join-Path $Repo "data\research\core_sleeve" }
            $parityPath = Join-Path $artifactDir ("parity_{0}.md" -f $RunDate.ToString("yyyy-MM-dd"))
            return Test-Path $parityPath
        }
        if ($catchUp.should_run) {
            Write-CoreSleeveSupervisorLog "CATCH_UP run_date=$($catchUp.today_run.ToString('yyyy-MM-dd'))"
            $argsList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $DailyScript)
            if ($Config) {
                $argsList += @("-Config", $Config)
            }
            if ($LogDir) {
                $argsList += @("-LogDir", $LogDir)
            }
            & powershell.exe @argsList
            $exitCode = $LASTEXITCODE
            Write-CoreSleeveSupervisorLog "DONE catch_up exit_code=$exitCode"
        }
        $nextRun = $catchUp.next_run
        Write-CoreSleeveSupervisorLog "NEXT_RUN $($nextRun.ToString('s'))"
        while ((Get-Date) -lt $nextRun) {
            $remaining = [int]($nextRun - (Get-Date)).TotalSeconds
            Start-Sleep -Seconds ([Math]::Min([Math]::Max($remaining, 1), 300))
        }

        Write-CoreSleeveSupervisorLog "RUN daily_script"
        $argsList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $DailyScript)
        if ($Config) {
            $argsList += @("-Config", $Config)
        }
        if ($LogDir) {
            $argsList += @("-LogDir", $LogDir)
        }
        & powershell.exe @argsList
        $exitCode = $LASTEXITCODE
        Write-CoreSleeveSupervisorLog "DONE daily_script exit_code=$exitCode"
    }
} finally {
    Release-StackSingleInstanceLock -ServiceName "core_sleeve_supervisor" -Log { param($Message) Write-CoreSleeveSupervisorLog $Message }
}
