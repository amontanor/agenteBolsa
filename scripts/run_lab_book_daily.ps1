<#
    run_lab_book_daily.ps1

    Ejecucion diaria one-shot del libro laboratorio. Solo registra candidatos
    hipoteticos en modo log_only; no envia ordenes paper ni reales.
#>

param(
    [string]$Config = ""
)

$ErrorActionPreference = "Stop"

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
$ConfigPath = if ($Config) { $Config } else { Join-Path $Repo "data\config\lab_book.json" }
$RunLog = Join-Path $Repo "data\logs\lab_book.log"

function Write-LabBookLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "s"
    Add-Content -Path $RunLog -Value "[$timestamp] $Message" -Encoding UTF8
}

New-Item -ItemType Directory -Force -Path (Split-Path $RunLog -Parent) | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $ConfigPath -Parent) | Out-Null

if (-not (Test-Path $Python)) {
    Write-LabBookLog "ERROR python_venv_missing path=$Python"
    exit 1
}

Push-Location $Repo
try {
    Write-LabBookLog "START lab_book config=$ConfigPath"
    $output = & $Python -m agente_bolsa.main lab-book run --config $ConfigPath --json 2>&1
    $exitCode = $LASTEXITCODE
    Add-Content -Path $RunLog -Value ($output -join [Environment]::NewLine) -Encoding UTF8
    if ($exitCode -ne 0) {
        Write-LabBookLog "ERROR lab_book_exit_code=$exitCode"
        exit $exitCode
    }
    Write-LabBookLog "DONE lab_book"
    exit 0
} catch {
    Write-LabBookLog "ERROR unexpected $($_.Exception.Message)"
    exit 1
} finally {
    Pop-Location
}
