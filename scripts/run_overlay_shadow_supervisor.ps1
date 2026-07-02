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

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DailyScript = Join-Path $Repo "scripts\run_overlay_shadow_daily.ps1"
$LogPath = Join-Path $Repo "data\logs\overlay_shadow_supervisor.log"

function Write-OverlayShadowSupervisorLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "s"
    Add-Content -Path $LogPath -Value "[$timestamp] $Message" -Encoding UTF8
}

function Get-NextRunAt {
    param([string]$TimeText)
    $parts = $TimeText.Split(":")
    if ($parts.Count -ne 2) {
        throw "RunAt invalido. Usa HH:mm, por ejemplo 22:30."
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
    Write-OverlayShadowSupervisorLog "ERROR daily_script_missing path=$DailyScript"
    exit 1
}

Write-OverlayShadowSupervisorLog "START overlay shadow supervisor run_at=$RunAt start=$Start"

while ($true) {
    $nextRun = Get-NextRunAt -TimeText $RunAt
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
