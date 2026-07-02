<#
    run_overlay_shadow_daily.ps1

    Ejecucion diaria one-shot del overlay shadow SPY. Calcula exposiciones
    objetivo read-only y persiste JSON/JSONL bajo data\research\overlay_shadow.
#>

param(
    [string]$Start = "2020-01-01"
)

$ErrorActionPreference = "Stop"

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
$LogPath = Join-Path $Repo "data\logs\overlay_shadow.log"
$OutDir = Join-Path $Repo "data\research\overlay_shadow"

function Write-OverlayShadowLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "s"
    Add-Content -Path $LogPath -Value "[$timestamp] $Message" -Encoding UTF8
}

New-Item -ItemType Directory -Force -Path (Split-Path $LogPath -Parent) | Out-Null
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

if (-not (Test-Path $Python)) {
    Write-OverlayShadowLog "ERROR python_venv_missing path=$Python"
    exit 1
}

Push-Location $Repo
try {
    Write-OverlayShadowLog "START overlay shadow start=$Start out_dir=$OutDir"
    $output = & $Python -m agente_bolsa.research.overlay_shadow --start $Start --out-dir $OutDir --json 2>&1
    $exitCode = $LASTEXITCODE
    Add-Content -Path $LogPath -Value ($output -join [Environment]::NewLine) -Encoding UTF8
    if ($exitCode -ne 0) {
        Write-OverlayShadowLog "ERROR overlay_shadow_exit_code=$exitCode"
        exit $exitCode
    }
    Write-OverlayShadowLog "DONE overlay shadow"
    exit 0
} catch {
    Write-OverlayShadowLog "ERROR unexpected $($_.Exception.Message)"
    exit 1
} finally {
    Pop-Location
}
