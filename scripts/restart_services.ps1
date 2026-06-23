<#
.SYNOPSIS
  Reinicio LIMPIO de los servicios de agenteBolsa (scheduler + panel web).

.DESCRIPTION
  Evita el problema de procesos duplicados / fantasma que dejaba el sistema
  corriendo codigo viejo. Pasos (idempotente):
    1. Para las tareas programadas.
    2. Mata TODOS los procesos del proyecto (cualquier python: venv o runtime
       de Codex), forzado y por arbol.
    3. Borra el lock obsoleto del scheduler.
    4. Arranca las tareas programadas (que usan el python del .venv).
    5. Verifica: una sola instancia de cada servicio + HTTP del panel.

  Seguro con mercado abierto (paper, no toca ordenes). Lanzar desde la raiz del
  repo. No requiere admin (solo mata/arranca; el registro de tareas si).

.NOTES
  Lección 23-jun: Stop-ScheduledTask NO siempre mata el proceso python hijo
  (sobre todo si lo lanzo un runtime distinto, p.ej. codex-runtimes). Ese
  proceso viejo seguia vivo con codigo antiguo y acaparaba el lock, asi que los
  cambios nuevos no se cargaban. Por eso aqui se hace taskkill /F /T de TODOS.
#>
param(
    [int]$WebPort = 8501
)
$ErrorActionPreference = "Continue"
$Repo = "C:\Antonio\Bref\agenteBolsa"
Set-Location $Repo

function Get-ProjectProcs {
    Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -match 'agente_bolsa\.main (schedule|web)' }
}

Write-Host "== 1. Parando tareas programadas ==" -ForegroundColor Cyan
foreach ($t in @("AgenteBolsaScheduler", "AgenteBolsaWeb")) {
    Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue | Out-Null
}

Write-Host "== 2. Matando TODOS los procesos del proyecto (venv y runtime de Codex) ==" -ForegroundColor Cyan
foreach ($p in Get-ProjectProcs) {
    Write-Host ("  kill PID {0}: {1}" -f $p.ProcessId, $p.CommandLine)
    taskkill /F /T /PID $p.ProcessId 2>$null | Out-Null
}
Start-Sleep -Seconds 3

Write-Host "== 3. Limpiando lock obsoleto ==" -ForegroundColor Cyan
Remove-Item (Join-Path $Repo "data\state\scheduler.lock") -ErrorAction SilentlyContinue

Write-Host "== 4. Arrancando tareas (python del .venv) ==" -ForegroundColor Cyan
Start-ScheduledTask -TaskName AgenteBolsaScheduler
Start-ScheduledTask -TaskName AgenteBolsaWeb
Write-Host "   Esperando a que levanten (Streamlit tarda)..." -ForegroundColor DarkGray
Start-Sleep -Seconds 30

Write-Host "== 5. Verificacion ==" -ForegroundColor Cyan
$procs = @(Get-ProjectProcs)
$procs | Select-Object ProcessId, CommandLine | Format-Table -AutoSize -Wrap

$venvSched = @($procs | Where-Object { $_.CommandLine -match 'schedule' -and $_.CommandLine -match '\\\.venv\\' })
$rogue     = @($procs | Where-Object { $_.CommandLine -match 'codex-runtimes' })

if ($venvSched.Count -eq 1) {
    Write-Host "OK: un unico scheduler del .venv." -ForegroundColor Green
} else {
    Write-Host ("AVISO: schedulers del .venv = {0} (esperado 1). Revisa duplicados." -f $venvSched.Count) -ForegroundColor Yellow
}
if ($rogue.Count -gt 0) {
    Write-Host ("AVISO: {0} proceso(s) de codex-runtimes presentes. Solo la tarea programada debe lanzar servicios." -f $rogue.Count) -ForegroundColor Yellow
}

try {
    $code = (Invoke-WebRequest -UseBasicParsing ("http://127.0.0.1:{0}" -f $WebPort) -TimeoutSec 10).StatusCode
    Write-Host ("Panel HTTP {0} en http://127.0.0.1:{1}" -f $code, $WebPort) -ForegroundColor Green
} catch {
    Write-Host ("Panel aun no responde en :{0} (Streamlit puede tardar 30-60s; reintenta)." -f $WebPort) -ForegroundColor Yellow
}

Write-Host "`nSugerencia: valida heartbeat con:" -ForegroundColor DarkGray
Write-Host "  .\.venv\Scripts\python.exe -m agente_bolsa.main schedule-status" -ForegroundColor DarkGray
