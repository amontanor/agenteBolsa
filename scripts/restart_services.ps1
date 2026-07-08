<#
.SYNOPSIS
  Reinicio LIMPIO de la pila persistente de agenteBolsa.

.DESCRIPTION
  Evita el problema de procesos duplicados / fantasma que dejaba el sistema
  corriendo codigo viejo. Pasos (idempotente):
    1. Para las tareas programadas.
    2. Mata TODOS los procesos del proyecto (cualquier python: venv o runtime
       de Codex), forzado y por arbol.
    3. Borra el lock obsoleto del scheduler.
    4. Arranca scheduler + web por tarea programada.
    5. Completa la pila con stack_up.ps1.
    6. Verifica: estado final del stack + HTTP del panel.

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
$StackUpScript = Join-Path $Repo "scripts\stack_up.ps1"
$StackStatusScript = Join-Path $Repo "scripts\stack_status.ps1"
. (Join-Path $Repo "scripts\stack_common.ps1")

function Get-ProjectProcs {
    Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -and ($_.CommandLine -match 'agente_bolsa\.main (schedule|web)' -or $_.CommandLine -match 'streamlit.*web_app\.py') }
}

function Get-ProjectRootProcs {
    $procs = @(Get-ProjectProcs)
    $projectPids = @{}
    foreach ($proc in $procs) {
        $projectPids[[int]$proc.ProcessId] = $true
    }
    @(
        $procs |
            Where-Object { -not $projectPids.ContainsKey([int]$_.ParentProcessId) } |
            Sort-Object ProcessId -Unique
    )
}

function Invoke-TaskKill {
    param([int]$TargetPid)
    $taskkill = Start-Process -FilePath "taskkill.exe" -ArgumentList @("/F", "/T", "/PID", $TargetPid) -NoNewWindow -PassThru -Wait
    if ($taskkill.ExitCode -notin @(0, 128)) {
        Write-Host ("AVISO: taskkill devolvio codigo {0} para PID {1}." -f $taskkill.ExitCode, $TargetPid) -ForegroundColor Yellow
    }
}

Write-Host "== 1. Parando tareas programadas ==" -ForegroundColor Cyan
foreach ($t in @("AgenteBolsaScheduler", "AgenteBolsaWeb")) {
    Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue | Out-Null
}

Write-Host "== 2. Matando TODOS los procesos del proyecto (venv y runtime de Codex) ==" -ForegroundColor Cyan
foreach ($p in Get-ProjectRootProcs) {
    Write-Host ("  kill PID {0}: {1}" -f $p.ProcessId, $p.CommandLine)
    Invoke-TaskKill -TargetPid $p.ProcessId
}
$foreignKilled = @(Stop-StackForeignProcesses)
foreach ($proc in $foreignKilled) {
    Write-Host ("  kill foreign PID {0}: {1}" -f $proc.pid, $proc.command_line)
}
Start-Sleep -Seconds 3

Write-Host "== 3. Limpiando lock obsoleto ==" -ForegroundColor Cyan
Remove-Item (Join-Path $Repo "data\state\scheduler.lock") -ErrorAction SilentlyContinue

Write-Host "== 4. Arrancando tareas (python del .venv) ==" -ForegroundColor Cyan
Start-ScheduledTask -TaskName AgenteBolsaScheduler
Start-ScheduledTask -TaskName AgenteBolsaWeb
Write-Host "   Esperando a que levanten (Streamlit tarda)..." -ForegroundColor DarkGray
Start-Sleep -Seconds 30

Write-Host "== 5. Levantando supervisores ausentes con stack_up ==" -ForegroundColor Cyan
if (Test-Path $StackUpScript) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $StackUpScript
    if ($LASTEXITCODE -ne 0) {
        Write-Host ("AVISO: stack_up.ps1 devolvio codigo {0}." -f $LASTEXITCODE) -ForegroundColor Yellow
    }
    Start-Sleep -Seconds 10
} else {
    Write-Host "AVISO: no existe scripts\\stack_up.ps1; no se pudo completar la pila." -ForegroundColor Yellow
}

Write-Host "== 6. Verificacion base scheduler/web ==" -ForegroundColor Cyan
$procs = @(Get-ProjectProcs)
$procs | Select-Object ProcessId, CommandLine | Format-Table -AutoSize -Wrap

$venvSched = @($procs | Where-Object { $_.CommandLine -match 'agente_bolsa\.main schedule' -and $_.CommandLine -match '\\\.venv\\' })
$foreignNow = @(Get-StackForeignProcesses)

if ($venvSched.Count -eq 1 -and $foreignNow.Count -eq 0) {
    Write-Host "OK: un unico scheduler del .venv." -ForegroundColor Green
} else {
    Write-Host ("AVISO: schedulers del .venv = {0} y procesos ajenos = {1} (esperado 1 y 0)." -f $venvSched.Count, $foreignNow.Count) -ForegroundColor Yellow
}
if ($foreignNow.Count -gt 0) {
    foreach ($proc in $foreignNow) {
        Write-Host ("AVISO: proceso ajeno detectado PID {0}: {1}" -f $proc.pid, $proc.command_line) -ForegroundColor Yellow
    }
}

try {
    $code = (Invoke-WebRequest -UseBasicParsing ("http://127.0.0.1:{0}" -f $WebPort) -TimeoutSec 10).StatusCode
    Write-Host ("Panel HTTP {0} en http://127.0.0.1:{1}" -f $code, $WebPort) -ForegroundColor Green
} catch {
    Write-Host ("Panel aun no responde en :{0} (Streamlit puede tardar 30-60s; reintenta)." -f $WebPort) -ForegroundColor Yellow
}

Write-Host "`n== 7. Estado final del stack ==" -ForegroundColor Cyan
if (Test-Path $StackStatusScript) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $StackStatusScript
    if ($LASTEXITCODE -ne 0) {
        Write-Host ("AVISO: stack_status.ps1 devolvio codigo {0}." -f $LASTEXITCODE) -ForegroundColor Yellow
    }
} else {
    Write-Host "AVISO: no existe scripts\\stack_status.ps1; no se pudo mostrar el estado final." -ForegroundColor Yellow
}

Write-Host "`nSugerencia: valida heartbeat con:" -ForegroundColor DarkGray
Write-Host "  .\.venv\Scripts\python.exe -m agente_bolsa.main schedule-status" -ForegroundColor DarkGray
