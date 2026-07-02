<#
    run_ci_digest_daily.ps1

    Ejecucion diaria one-shot del digest de mejora continua. Escribe un informe
    markdown bajo data\reports sin tocar el scheduler operativo de trading.
#>

param(
    [int]$Days = 1
)

$ErrorActionPreference = "Stop"

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
$LogPath = Join-Path $Repo "data\logs\ci_digest.log"
$ReportDir = Join-Path $Repo "data\reports"
$ReportDate = Get-Date -Format "yyyy-MM-dd"
$ReportPath = Join-Path $ReportDir "ci_digest_$ReportDate.md"

function Write-CiDigestLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "s"
    Add-Content -Path $LogPath -Value "[$timestamp] $Message" -Encoding UTF8
}

New-Item -ItemType Directory -Force -Path (Split-Path $LogPath -Parent) | Out-Null
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null

if (-not (Test-Path $Python)) {
    Write-CiDigestLog "ERROR python_venv_missing path=$Python"
    exit 1
}

Push-Location $Repo
try {
    Write-CiDigestLog "START ci digest days=$Days report=$ReportPath"
    $output = & $Python -m agente_bolsa.main continuous-improvement-lab digest --days $Days --out $ReportPath --json 2>&1
    $exitCode = $LASTEXITCODE
    Add-Content -Path $LogPath -Value ($output -join [Environment]::NewLine) -Encoding UTF8
    if ($exitCode -ne 0) {
        Write-CiDigestLog "ERROR digest_exit_code=$exitCode"
        exit $exitCode
    }
    if (-not (Test-Path $ReportPath)) {
        Write-CiDigestLog "ERROR report_missing path=$ReportPath"
        exit 1
    }
    Write-CiDigestLog "DONE ci digest report=$ReportPath"
    exit 0
} catch {
    Write-CiDigestLog "ERROR unexpected $($_.Exception.Message)"
    exit 1
} finally {
    Pop-Location
}
