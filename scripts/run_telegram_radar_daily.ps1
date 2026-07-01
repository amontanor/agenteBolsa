<#
    run_telegram_radar_daily.ps1

    Ejecucion diaria one-shot del radar Telegram research-only. Ingiere la vista
    publica del canal y escribe un informe markdown UTF-8 bajo
    data\research\telegram\reports.
#>

param(
    [int]$Backfill = 1,
    [int]$Days = 7
)

$ErrorActionPreference = "Stop"

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
$LogPath = Join-Path $Repo "data\logs\telegram_radar.log"
$ReportDir = Join-Path $Repo "data\research\telegram\reports"
$ReportDate = Get-Date -Format "yyyy-MM-dd"
$ReportPath = Join-Path $ReportDir "radar_$ReportDate.md"

function Write-RadarLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "s"
    Add-Content -Path $LogPath -Value "[$timestamp] $Message" -Encoding UTF8
}

New-Item -ItemType Directory -Force -Path (Split-Path $LogPath -Parent) | Out-Null
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null

if (-not (Test-Path $Python)) {
    Write-RadarLog "ERROR python_venv_missing path=$Python"
    exit 1
}

Push-Location $Repo
try {
    Write-RadarLog "START telegram radar daily backfill=$Backfill days=$Days"

    $ingestOutput = & $Python -m agente_bolsa.main telegram-radar ingest --backfill $Backfill --json 2>&1
    $ingestExit = $LASTEXITCODE
    Add-Content -Path $LogPath -Value ($ingestOutput -join [Environment]::NewLine) -Encoding UTF8
    if ($ingestExit -ne 0) {
        Write-RadarLog "ERROR ingest_exit_code=$ingestExit"
        exit $ingestExit
    }

    try {
        $ingestJson = $ingestOutput -join [Environment]::NewLine | ConvertFrom-Json
    } catch {
        Write-RadarLog "ERROR ingest_json_invalid $($_.Exception.Message)"
        exit 1
    }

    if (-not $ingestJson.ok) {
        $warnings = ""
        if ($null -ne $ingestJson.ingest -and $null -ne $ingestJson.ingest.warnings) {
            $warnings = ($ingestJson.ingest.warnings | ConvertTo-Json -Compress)
        }
        Write-RadarLog "ERROR ingest_failed_cleanly warnings=$warnings"
        exit 2
    }

    $reportOutput = & $Python -m agente_bolsa.main telegram-radar report --days $Days --out $ReportPath --json 2>&1
    $reportExit = $LASTEXITCODE
    Add-Content -Path $LogPath -Value ($reportOutput -join [Environment]::NewLine) -Encoding UTF8
    if ($reportExit -ne 0) {
        Write-RadarLog "ERROR report_exit_code=$reportExit"
        exit $reportExit
    }

    if (-not (Test-Path $ReportPath)) {
        Write-RadarLog "ERROR report_missing path=$ReportPath"
        exit 1
    }

    Write-RadarLog "DONE telegram radar daily report=$ReportPath"
    exit 0
} catch {
    Write-RadarLog "ERROR unexpected $($_.Exception.Message)"
    exit 1
} finally {
    Pop-Location
}
