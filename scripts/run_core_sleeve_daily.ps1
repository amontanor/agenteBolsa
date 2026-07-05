<#
    run_core_sleeve_daily.ps1

    Ejecucion diaria one-shot de la manga core SPY. No registra jobs en el
    scheduler operativo. La activacion depende de data\config\core_sleeve.json.
#>

param(
    [string]$Config = "",
    [string]$LogDir = ""
)

$ErrorActionPreference = "Stop"

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
$ConfigPath = if ($Config) { $Config } else { Join-Path $Repo "data\config\core_sleeve.json" }
$OutDir = if ($LogDir) { $LogDir } else { Join-Path $Repo "data\research\core_sleeve" }
$RunLog = Join-Path $Repo "data\logs\core_sleeve.log"
$ParityScript = Join-Path $Repo "scripts\core_sleeve_parity_check.py"

function Write-CoreSleeveLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "s"
    Add-Content -Path $RunLog -Value "[$timestamp] $Message" -Encoding UTF8
}

New-Item -ItemType Directory -Force -Path (Split-Path $RunLog -Parent) | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $ConfigPath -Parent) | Out-Null
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

if (-not (Test-Path $Python)) {
    Write-CoreSleeveLog "ERROR python_venv_missing path=$Python"
    exit 1
}

Push-Location $Repo
try {
    Write-CoreSleeveLog "START core_sleeve config=$ConfigPath log_dir=$OutDir"
    $output = & $Python -m agente_bolsa.strategies.core_sleeve --config $ConfigPath --log-dir $OutDir --json 2>&1
    $exitCode = $LASTEXITCODE
    Add-Content -Path $RunLog -Value ($output -join [Environment]::NewLine) -Encoding UTF8
    if ($exitCode -ne 0) {
        Write-CoreSleeveLog "ERROR core_sleeve_exit_code=$exitCode"
        exit $exitCode
    }
    Write-CoreSleeveLog "DONE core_sleeve"

    if (Test-Path $ParityScript) {
        $parityDate = Get-Date -Format "yyyy-MM-dd"
        $parityPath = Join-Path $OutDir "parity_$parityDate.md"
        Write-CoreSleeveLog "START parity_check out=$parityPath"
        $parityOutput = & $Python $ParityScript --config $ConfigPath 2>&1
        $parityExitCode = $LASTEXITCODE
        Set-Content -Path $parityPath -Value ($parityOutput -join [Environment]::NewLine) -Encoding UTF8
        Write-CoreSleeveLog "DONE parity_check exit_code=$parityExitCode out=$parityPath"
    } else {
        Write-CoreSleeveLog "WARN parity_script_missing path=$ParityScript"
    }

    exit 0
} catch {
    Write-CoreSleeveLog "ERROR unexpected $($_.Exception.Message)"
    exit 1
} finally {
    Pop-Location
}
