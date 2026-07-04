<#
    run_core_sleeve_supervisor.ps1

    Supervisor sin privilegios de administrador para lanzar la manga core SPY
    una vez al dia. No toca agente_bolsa.main schedule ni el runtime de trading.
#>

param(
    [string]$RunAt = "15:45",
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

function Get-NextRunAt {
    param([string]$TimeText)
    $parts = $TimeText.Split(":")
    if ($parts.Count -ne 2) {
        throw "RunAt invalido. Usa HH:mm, por ejemplo 15:45."
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
        $nextRun = Get-NextRunAt -TimeText $RunAt
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
