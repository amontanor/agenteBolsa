<#
    run_codegen_nightly_supervisor.ps1

    Supervisor sin privilegios de administrador para lanzar codegen nightly una
    vez al dia. No arranca scheduler ni aplica diffs.
#>

param(
    [string]$RunAt = "03:00",
    [string]$Config = ""
)

$ErrorActionPreference = "Stop"

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$NightlyScript = Join-Path $Repo "scripts\run_codegen_nightly.ps1"
$LogPath = Join-Path $Repo "data\logs\codegen_nightly_supervisor.log"

function Write-CodegenNightlySupervisorLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "s"
    Add-Content -Path $LogPath -Value "[$timestamp] $Message" -Encoding UTF8
}

function Get-NextRunAt {
    param([string]$TimeText)
    $parts = $TimeText.Split(":")
    if ($parts.Count -ne 2) {
        throw "RunAt invalido. Usa HH:mm, por ejemplo 03:00."
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

if (-not (Test-Path $NightlyScript)) {
    Write-CodegenNightlySupervisorLog "ERROR nightly_script_missing path=$NightlyScript"
    exit 1
}

Write-CodegenNightlySupervisorLog "START codegen nightly supervisor run_at=$RunAt config=$Config"

while ($true) {
    $nextRun = Get-NextRunAt -TimeText $RunAt
    Write-CodegenNightlySupervisorLog "NEXT_RUN $($nextRun.ToString('s'))"
    while ((Get-Date) -lt $nextRun) {
        $remaining = [int]($nextRun - (Get-Date)).TotalSeconds
        Start-Sleep -Seconds ([Math]::Min([Math]::Max($remaining, 1), 300))
    }

    Write-CodegenNightlySupervisorLog "RUN nightly_script"
    if ($Config -ne "") {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $NightlyScript -Config $Config
    } else {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $NightlyScript
    }
    $exitCode = $LASTEXITCODE
    Write-CodegenNightlySupervisorLog "DONE nightly_script exit_code=$exitCode"
}
