<#
.SYNOPSIS
    Ejecuta el mantenimiento de la BD de estado de forma segura:
    para el scheduler -> mantenimiento (borrado + VACUUM) -> rearranca el scheduler.

.DESCRIPTION
    VACUUM necesita un lock exclusivo, asi que el scheduler de agenteBolsa
    (tarea "AgenteBolsaScheduler") NO puede estar escribiendo. Este script
    automatiza la ventana de mantenimiento:

      1. Detiene la tarea programada AgenteBolsaScheduler.
      2. Espera a que se libere el -wal.
      3. Lanza scripts/db_maintenance.py en el modo indicado.
      4. Vuelve a arrancar AgenteBolsaScheduler.

    Hazlo idealmente con el mercado CERRADO (fuera de 09:30-16:00 ET).

.PARAMETER Mode
    apply   (defecto) -> borra filas antiguas (retencion por tabla) + VACUUM completo.
    vacuum  -> solo VACUUM completo (no borra filas).
    autovac -> one-time: activa auto_vacuum=INCREMENTAL (+VACUUM).
    dryrun  -> solo informa, no modifica nada (no hace falta parar el scheduler).

.PARAMETER Days
    Corte global de retencion en dias (sobreescribe los valores por tabla).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\run_db_maintenance.ps1 -Mode dryrun
    powershell -ExecutionPolicy Bypass -File scripts\run_db_maintenance.ps1 -Mode apply -Days 45
#>
param(
    [ValidateSet("apply", "vacuum", "autovac", "dryrun")]
    [string]$Mode = "apply",
    [int]$Days = 0,
    [switch]$SkipBackup
)

$ErrorActionPreference = "Stop"
$Repo     = "C:\Antonio\Bref\agenteBolsa"
$Python   = Join-Path $Repo ".venv\Scripts\python.exe"
$Script   = Join-Path $Repo "scripts\db_maintenance.py"
$SchedulerTask = "AgenteBolsaScheduler"
$WebTask       = "AgenteBolsaWeb"
$DbPath        = Join-Path $Repo "data\state\agente_bolsa.sqlite3"

if (-not (Test-Path $Python)) { Write-Error "No existe el venv: $Python" }

# Argumentos para db_maintenance.py segun el modo
$pyArgs = @($Script)
switch ($Mode) {
    "apply"   { $pyArgs += "--apply" }
    "vacuum"  { $pyArgs += "--vacuum-only" }
    "autovac" { $pyArgs += "--set-incremental-autovacuum" }
    "dryrun"  { }  # sin flags = dry-run
}
if ($Days -gt 0) { $pyArgs += @("--days", "$Days") }

$needsStop = $Mode -ne "dryrun"

if ($needsStop) {
    Write-Host "Deteniendo tareas de agenteBolsa ..." -ForegroundColor Yellow
    foreach ($task in @($SchedulerTask, $WebTask)) {
        try { Stop-ScheduledTask -TaskName $task -ErrorAction Stop } catch { Write-Warning "No se pudo detener ${task}: $_" }
    }

    # Las tareas pueden dejar procesos hijo desacoplados. Se filtra por linea de
    # comando para no matar otros Python del repositorio ni procesos de usuario.
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.CommandLine -like "*$Repo*" -and (
                $_.CommandLine -like "*agente_bolsa.main schedule*" -or
                $_.CommandLine -like "*run_scheduler_supervisor.ps1*" -or
                $_.CommandLine -like "*streamlit*web_app.py*"
            )
        } |
        ForEach-Object {
            Write-Host "  deteniendo $($_.Name) PID $($_.ProcessId)"
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }

    # Esperar a que el -wal se vacie (hasta 60s)
    $wal = Join-Path $Repo "data\state\agente_bolsa.sqlite3-wal"
    for ($i = 0; $i -lt 30; $i++) {
        if (-not (Test-Path $wal) -or (Get-Item $wal).Length -lt 1MB) { break }
        if ($i -eq 0) {
            & $Python -c "import sqlite3; c=sqlite3.connect(r'$DbPath', timeout=60); c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.close()"
        }
        Start-Sleep -Seconds 2
    }

    if (-not $SkipBackup) {
        $backupDir = Join-Path $Repo "data\backups"
        New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
        $backupPath = Join-Path $backupDir ("agente_bolsa-before-maintenance-{0}.sqlite3" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
        Write-Host "Creando backup consistente: $backupPath" -ForegroundColor Cyan
        & $Python -c "import sqlite3; src=sqlite3.connect(r'$DbPath', timeout=60); dst=sqlite3.connect(r'$backupPath'); src.backup(dst); dst.close(); src.close()"
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $backupPath)) { throw "No se pudo crear el backup de la BD." }
    }
}

try {
    Write-Host "Ejecutando: $Python $($pyArgs -join ' ')" -ForegroundColor Cyan
    & $Python @pyArgs
    $exit = $LASTEXITCODE
} finally {
    if ($needsStop) {
        Write-Host "Rearrancando tareas de agenteBolsa ..." -ForegroundColor Yellow
        foreach ($task in @($SchedulerTask, $WebTask)) {
            try { Start-ScheduledTask -TaskName $task -ErrorAction Stop } catch { Write-Warning "No se pudo rearrancar ${task}: $_" }
        }
    }
}

if ($exit -ne 0) { Write-Error "db_maintenance.py termino con codigo $exit" }
Write-Host "Mantenimiento completado." -ForegroundColor Green

<#
PARA PROGRAMARLO SEMANALMENTE (ej. domingos 03:00, mercado cerrado):

    $action  = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"C:\Antonio\Bref\agenteBolsa\scripts\run_db_maintenance.ps1`" -Mode apply"
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 3am
    Register-ScheduledTask -TaskName "AgenteBolsaDBMaintenance" -Action $action -Trigger $trigger `
        -Description "Retencion + VACUUM semanal de la BD de estado (para/arranca el scheduler)."
#>
