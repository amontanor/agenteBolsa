<#
.SYNOPSIS
  Chequeo rapido de los servicios de agenteBolsa: detecta duplicados/fantasmas.

.DESCRIPTION
  Lista los procesos del proyecto, avisa si hay mas de un scheduler/web o si hay
  procesos del runtime de Codex (que no deberian existir: solo la tarea
  programada del .venv debe lanzar servicios). Muestra el lock y el HTTP del panel.
  Solo lee; no mata ni arranca nada.
#>
param(
    [int]$WebPort = 8501
)
$ErrorActionPreference = "Continue"
$Repo = "C:\Antonio\Bref\agenteBolsa"

$procs = @(Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match 'agente_bolsa\.main (schedule|web)' })

Write-Host "Procesos agenteBolsa:" -ForegroundColor Cyan
$procs | Select-Object ProcessId, CreationDate, CommandLine | Format-Table -AutoSize -Wrap

$sched = @($procs | Where-Object { $_.CommandLine -match 'schedule' })
$web   = @($procs | Where-Object { $_.CommandLine -match 'web' })
$rogue = @($procs | Where-Object { $_.CommandLine -match 'codex-runtimes' })

Write-Host ("Schedulers: {0} | Webs: {1} | de codex-runtimes: {2}" -f $sched.Count, $web.Count, $rogue.Count)

$problema = $false
if ($sched.Count -gt 1) { Write-Host "  -> DUPLICADO: mas de un scheduler." -ForegroundColor Yellow; $problema = $true }
if ($web.Count   -gt 1) { Write-Host "  -> DUPLICADO: mas de un web." -ForegroundColor Yellow; $problema = $true }
if ($rogue.Count -gt 0) { Write-Host "  -> ROGUE: proceso(s) de codex-runtimes (solo la tarea programada debe lanzar)." -ForegroundColor Yellow; $problema = $true }
if ($sched.Count -eq 0) { Write-Host "  -> Scheduler NO esta corriendo." -ForegroundColor Yellow; $problema = $true }

if ($problema) {
    Write-Host "ACCION: ejecuta  scripts\restart_services.ps1  para dejar una sola instancia limpia." -ForegroundColor Yellow
} else {
    Write-Host "OK: una sola instancia de cada servicio." -ForegroundColor Green
}

Write-Host "`nLock del scheduler:" -ForegroundColor Cyan
Get-Content (Join-Path $Repo "data\state\scheduler.lock") -ErrorAction SilentlyContinue

try {
    $code = (Invoke-WebRequest -UseBasicParsing ("http://127.0.0.1:{0}" -f $WebPort) -TimeoutSec 8).StatusCode
    Write-Host ("`nPanel HTTP {0}" -f $code) -ForegroundColor Green
} catch {
    Write-Host ("`nPanel no responde en :{0}" -f $WebPort) -ForegroundColor Yellow
}
