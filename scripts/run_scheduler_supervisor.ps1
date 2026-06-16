<#
    run_scheduler_supervisor.ps1

    Supervisor simple para el scheduler. Mantiene un bucle local que vuelve a
    lanzar `python -m agente_bolsa.main schedule` si el proceso sale por
    cualquier motivo. Esto protege frente a salidas limpias inesperadas y evita
    depender de una consola manual abierta.
#>

$ErrorActionPreference = "Stop"

$Repo = "C:\Antonio\Bref\agenteBolsa"
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
$LogPath = Join-Path $Repo "data\logs\scheduler_supervisor.log"

if (-not (Test-Path $Python)) {
    throw "No existe el interprete del venv: $Python"
}

New-Item -ItemType Directory -Force -Path (Split-Path $LogPath -Parent) | Out-Null

while ($true) {
    $startedAt = Get-Date -Format "s"
    Add-Content -Path $LogPath -Value "[$startedAt] Starting scheduler"
    & $Python -m agente_bolsa.main schedule
    $exitCode = $LASTEXITCODE
    $stoppedAt = Get-Date -Format "s"
    Add-Content -Path $LogPath -Value "[$stoppedAt] Scheduler exited with code $exitCode"
    Start-Sleep -Seconds 5
}
