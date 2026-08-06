<#
    Registra la pagina Kindle read-only como tarea gestionada.

    No modifica el firewall. Por defecto registra y arranca el servicio; usa
    -NoStart durante una integracion para dejar que stack_up.ps1 lo arranque.
#>

param(
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
$Repo = "C:\Antonio\Bref\agenteBolsa"
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
$TaskName = "AgenteBolsaKindle"

if (-not (Test-Path -LiteralPath $Python)) {
    Write-Error "No existe el interprete del venv: $Python"
    exit 1
}

$snapshot = Join-Path $Repo "data\state\kindle_snapshot.json"
$action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument "-m agente_bolsa.kindle_server --host 0.0.0.0 --port 8502 --snapshot `"$snapshot`"" `
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
    -Description "Pagina Kindle read-only de cartera en 0.0.0.0:8502." `
    -Force | Out-Null

Write-Host "Tarea '$TaskName' registrada; bind 0.0.0.0:8502; sin cambios de firewall." -ForegroundColor Green
if (-not $NoStart) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Tarea '$TaskName' iniciada." -ForegroundColor Cyan
}
