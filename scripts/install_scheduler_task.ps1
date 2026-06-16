<#
    install_scheduler_task.ps1

    Registra (y arranca) una Tarea Programada de Windows que mantiene el scheduler
    de agenteBolsa corriendo de forma persistente, sobreviviendo al cierre de la
    ventana y al cierre de sesion de cualquier agente. Resuelve el problema de que
    el proceso lanzado en background moria tras el bootstrap por quedar colgado de
    una sesion transitoria (NO era un bug del codigo: `run_scheduler_forever`
    bloquea correctamente con un bucle).

    Uso (PowerShell, en tu sesion de usuario normal):
        cd C:\Antonio\Bref\agenteBolsa
        powershell -ExecutionPolicy Bypass -File scripts\install_scheduler_task.ps1

    Para desinstalar:
        Unregister-ScheduledTask -TaskName "AgenteBolsaScheduler" -Confirm:$false

    Notas:
    - Se ejecuta en TU sesion al iniciar sesion (LogonType Interactive). Asi tiene
      acceso al .venv, red y al mismo entorno que cuando lo lanzas a mano.
    - Reinicio automatico si el proceso cae. Sin limite de tiempo de ejecucion.
    - Una sola instancia (no arranca otra si ya hay una).
#>

$ErrorActionPreference = "Stop"

$Repo    = "C:\Antonio\Bref\agenteBolsa"
$Python  = Join-Path $Repo ".venv\Scripts\python.exe"
$Supervisor = Join-Path $Repo "scripts\run_scheduler_supervisor.ps1"
$TaskName = "AgenteBolsaScheduler"

if (-not (Test-Path $Python)) {
    Write-Error "No existe el interprete del venv: $Python"
    exit 1
}
if (-not (Test-Path $Supervisor)) {
    Write-Error "No existe el supervisor del scheduler: $Supervisor"
    exit 1
}

# Accion: lanzar un supervisor PowerShell que reintenta el scheduler si sale.
$action = New-ScheduledTaskAction `
    -Execute "C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Supervisor`"" `
    -WorkingDirectory $Repo

# Disparador: al iniciar sesion el usuario actual.
$trigger = New-ScheduledTaskTrigger -AtLogOn

# Ajustes: reinicio ante fallo, sin limite de tiempo, una sola instancia,
# arrancar aunque la hora prevista se haya pasado, no parar con bateria.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -MultipleInstances IgnoreNew

# Ejecutar como el usuario actual, en su sesion interactiva.
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Mantiene vivo el scheduler de agenteBolsa (analisis, aprendizaje, healthchecks y vigilancia de oportunidades)." `
    -Force | Out-Null

Write-Host "Tarea '$TaskName' registrada." -ForegroundColor Green

# Arrancar ya mismo (sin esperar al proximo inicio de sesion).
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 3
$info = Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo
Write-Host ("Estado: LastTaskResult={0}  LastRun={1}" -f $info.LastTaskResult, $info.LastRunTime)
Write-Host ""
Write-Host "Verifica que el scheduler esta vivo con:" -ForegroundColor Cyan
Write-Host "  .\.venv\Scripts\python.exe -m agente_bolsa.main schedule-status"
