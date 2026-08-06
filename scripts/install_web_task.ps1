<#
    install_web_task.ps1

    Registra (y arranca) una Tarea Programada que mantiene el panel web de
    agenteBolsa (Streamlit) corriendo de forma persistente en 0.0.0.0:8501.
    La exposicion LAN queda limitada por Firewall a perfil Private/LocalSubnet.
    Complementa a install_scheduler_task.ps1.

    Uso:
        cd C:\Antonio\Bref\agenteBolsa
        powershell -ExecutionPolicy Bypass -File scripts\install_web_task.ps1

    Desinstalar:
        Unregister-ScheduledTask -TaskName "AgenteBolsaWeb" -Confirm:$false
#>

$ErrorActionPreference = "Stop"

$Repo     = "C:\Antonio\Bref\agenteBolsa"
$Python   = Join-Path $Repo ".venv\Scripts\python.exe"
$TaskName = "AgenteBolsaWeb"

if (-not (Test-Path $Python)) {
    Write-Error "No existe el interprete del venv: $Python"
    exit 1
}

$action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument "-m agente_bolsa.main web --host 0.0.0.0 --port 8501" `
    -WorkingDirectory $Repo

$trigger = New-ScheduledTaskTrigger -AtLogOn

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -MultipleInstances IgnoreNew

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
    -Description "Panel agenteBolsa en 0.0.0.0:8501; acceso LAN solo por Firewall Private/LocalSubnet." `
    -Force | Out-Null

Write-Host "Tarea '$TaskName' registrada." -ForegroundColor Green
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 3
Write-Host "Panel local: http://127.0.0.1:8501; LAN: http://<IPv4-privada>:8501" -ForegroundColor Cyan
