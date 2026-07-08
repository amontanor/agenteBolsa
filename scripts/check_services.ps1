<#
.SYNOPSIS
  Veredicto fiable del estado de agenteBolsa (scheduler + panel web).

.DESCRIPTION
  Verifica que scheduler y web esten lanzados desde el .venv gestionado del repo.
  Cualquier proceso raiz `agente_bolsa.main schedule`, `agente_bolsa.main web` o
  `streamlit ... web_app.py` cuyo ejecutable no sea `.\.venv\Scripts\python.exe`
  se considera AJENO al stack gestionado y hace fallar el check.
#>
param(
    [int]$WebPort = 8501
)
$ErrorActionPreference = "Continue"
$Repo = "C:\Antonio\Bref\agenteBolsa"
. (Join-Path $Repo "scripts\stack_common.ps1")
$status = Get-StackStatus
$services = @($status.services)
$foreign = @($status.foreign_processes)

# Lock del scheduler: la fuente de verdad de "quien esta activo".
$lockPath = Join-Path $Repo "data\state\scheduler.lock"
$lockPid = $null
if (Test-Path $lockPath) {
    try { $lockPid = [int]((Get-Content $lockPath -Raw | ConvertFrom-Json).pid) } catch { $lockPid = $null }
}
$lockAlive = $false
if ($lockPid) { $lockAlive = [bool](Get-Process -Id $lockPid -ErrorAction SilentlyContinue) }

# Panel.
$http = $null
try { $http = (Invoke-WebRequest -UseBasicParsing ("http://127.0.0.1:{0}" -f $WebPort) -TimeoutSec 8).StatusCode } catch { $http = $null }

Write-Host "Procesos agenteBolsa:" -ForegroundColor Cyan
foreach ($service in $services) {
    foreach ($line in $service.process_command_lines) {
        [pscustomobject]@{ service = $service.service; command_line = $line }
    }
} | Format-Table -AutoSize -Wrap

if ($lockAlive) {
    Write-Host ("Scheduler activo (lock): PID {0} -> VIVO" -f $lockPid) -ForegroundColor Green
} elseif ($lockPid) {
    Write-Host ("Scheduler activo (lock): PID {0} -> MUERTO (lock huerfano)" -f $lockPid) -ForegroundColor Yellow
} else {
    Write-Host "Scheduler activo (lock): ninguno (no hay lock)" -ForegroundColor Yellow
}

$problemas = @()
if ($foreign.Count -gt 0) { $problemas += ("Hay {0} proceso(s) ajenos al .venv." -f $foreign.Count) }
if (-not $lockAlive)    { $problemas += "No hay un scheduler activo con lock vivo." }
if (($services | Where-Object { $_.service -eq "scheduler" -and $_.state -eq "DUPLICADO" }).Count -gt 0) { $problemas += "Mas de un scheduler logico." }
if (($services | Where-Object { $_.service -eq "web" -and $_.state -eq "DUPLICADO" }).Count -gt 0) { $problemas += "Mas de un web logico." }
if ($http -ne 200)      { $problemas += ("El panel no responde HTTP 200 en :{0}." -f $WebPort) }

Write-Host ""
if ($problemas.Count -eq 0) {
    Write-Host "OK: sistema sano." -ForegroundColor Green
    Write-Host ("  - 1 scheduler activo (PID {0}, con el lock)." -f $lockPid) -ForegroundColor Green
    Write-Host ("  - Panel HTTP {0} en :{1}." -f $http, $WebPort) -ForegroundColor Green
    Write-Host "  - Sin procesos ajenos al .venv." -ForegroundColor Green
} else {
    Write-Host "ATENCION: hay algo que revisar:" -ForegroundColor Yellow
    foreach ($p in $problemas) { Write-Host ("  -> {0}" -f $p) -ForegroundColor Yellow }
    foreach ($proc in $foreign) { Write-Host ("  -> FOREIGN PID {0}: {1}" -f $proc.pid, $proc.command_line) -ForegroundColor Yellow }
    Write-Host "ACCION sugerida: scripts\restart_services.ps1 para dejar una sola instancia limpia." -ForegroundColor Yellow
}
