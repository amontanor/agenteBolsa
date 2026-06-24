<#
.SYNOPSIS
  Veredicto fiable del estado de agenteBolsa (scheduler + panel web).

.DESCRIPTION
  En esta maquina cada servicio aparece como DOS procesos: el lanzador del venv
  (.venv\Scripts\python.exe) y su interprete base (...\Python311\python.exe), que
  es el que de verdad ejecuta el codigo y tiene el lock. Eso NO es un duplicado:
  es una sola instancia logica (lanzador + worker).

  Por eso este script no cuenta procesos a ciegas. El criterio de salud es:
    - existe UN lock de scheduler y su PID esta vivo (= un scheduler activo),
    - el panel responde HTTP 200,
    - no hay un SEGUNDO scheduler logico compitiendo (mas de un par),
    - no hay procesos del runtime de la herramienta (codex-runtimes), que ya no
      deberian existir tras recrear el venv sobre el Python estable.
  Solo lee; no mata ni arranca nada.
#>
param(
    [int]$WebPort = 8501
)
$ErrorActionPreference = "Continue"
$Repo = "C:\Antonio\Bref\agenteBolsa"

$procs = @(Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match 'agente_bolsa\.main (schedule|web)' })

$sched = @($procs | Where-Object { $_.CommandLine -match 'agente_bolsa\.main schedule' })
$web   = @($procs | Where-Object { $_.CommandLine -match 'agente_bolsa\.main web' })
$rogue = @($procs | Where-Object { $_.CommandLine -match 'codex-runtimes' })

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
$procs | Select-Object ProcessId, CreationDate, CommandLine | Format-Table -AutoSize -Wrap

if ($lockAlive) {
    Write-Host ("Scheduler activo (lock): PID {0} -> VIVO" -f $lockPid) -ForegroundColor Green
} elseif ($lockPid) {
    Write-Host ("Scheduler activo (lock): PID {0} -> MUERTO (lock huerfano)" -f $lockPid) -ForegroundColor Yellow
} else {
    Write-Host "Scheduler activo (lock): ninguno (no hay lock)" -ForegroundColor Yellow
}

# --- Veredicto ---
# Cada servicio logico = hasta 2 procesos (lanzador + base). Mas de 2 = duplicado real.
$problemas = @()
if ($rogue.Count -gt 0) { $problemas += "Hay procesos de codex-runtimes (deberian ser 0 tras recrear el venv)." }
if (-not $lockAlive)    { $problemas += "No hay un scheduler activo con lock vivo." }
if ($sched.Count -gt 2) { $problemas += ("Mas de un scheduler logico: {0} procesos (esperado 1-2)." -f $sched.Count) }
if ($web.Count   -gt 2) { $problemas += ("Mas de un web logico: {0} procesos (esperado 1-2)." -f $web.Count) }
if ($http -ne 200)      { $problemas += ("El panel no responde HTTP 200 en :{0}." -f $WebPort) }

Write-Host ""
if ($problemas.Count -eq 0) {
    Write-Host "OK: sistema sano." -ForegroundColor Green
    Write-Host ("  - 1 scheduler activo (PID {0}, con el lock)." -f $lockPid) -ForegroundColor Green
    Write-Host ("  - Panel HTTP {0} en :{1}." -f $http, $WebPort) -ForegroundColor Green
    Write-Host ("  - {0} proc. scheduler y {1} web = parejas lanzador+base normales (NO es duplicado)." -f $sched.Count, $web.Count) -ForegroundColor DarkGray
} else {
    Write-Host "ATENCION: hay algo que revisar:" -ForegroundColor Yellow
    foreach ($p in $problemas) { Write-Host ("  -> {0}" -f $p) -ForegroundColor Yellow }
    Write-Host "ACCION sugerida: scripts\restart_services.ps1 para dejar una sola instancia limpia." -ForegroundColor Yellow
}
