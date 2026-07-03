<#
    run_codegen_nightly.ps1

    Ejecucion one-shot del codegen nightly de mejora continua. Genera diffs para
    revision humana, nunca aplica cambios.
#>

param(
    [string]$Config = ""
)

$ErrorActionPreference = "Stop"

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
$LogPath = Join-Path $Repo "data\logs\codegen_nightly.log"

function Write-CodegenNightlyLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "s"
    Add-Content -Path $LogPath -Value "[$timestamp] $Message" -Encoding UTF8
}

New-Item -ItemType Directory -Force -Path (Split-Path $LogPath -Parent) | Out-Null

if (-not (Test-Path $Python)) {
    Write-CodegenNightlyLog "ERROR python_venv_missing path=$Python"
    exit 1
}

Push-Location $Repo
try {
    $argsList = @("-m", "agente_bolsa.main", "continuous-improvement-lab", "codegen-nightly", "--json")
    if ($Config -ne "") {
        $argsList += @("--config", $Config)
    }
    Write-CodegenNightlyLog "START codegen nightly config=$Config"
    $output = & $Python @argsList 2>&1
    $exitCode = $LASTEXITCODE
    Add-Content -Path $LogPath -Value ($output -join [Environment]::NewLine) -Encoding UTF8
    if ($exitCode -ne 0) {
        Write-CodegenNightlyLog "ERROR codegen_nightly_exit_code=$exitCode"
        exit $exitCode
    }
    Write-CodegenNightlyLog "DONE codegen nightly"
    exit 0
} catch {
    Write-CodegenNightlyLog "ERROR unexpected $($_.Exception.Message)"
    exit 1
} finally {
    Pop-Location
}
