<# Registra el mantenimiento semanal seguro de SQLite. #>

$ErrorActionPreference = "Stop"

$Repo       = "C:\Antonio\Bref\agenteBolsa"
$Runner     = Join-Path $Repo "scripts\run_db_maintenance.ps1"
$TaskName   = "AgenteBolsaDBMaintenance"

if (-not (Test-Path $Runner)) {
    Write-Error "No existe el wrapper de mantenimiento: $Runner"
    exit 1
}

$action = New-ScheduledTaskAction `
    -Execute "C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`" -Mode apply" `
    -WorkingDirectory $Repo

# Domingo 03:00 hora local: mercado cerrado y fuera del ciclo post-market.
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 3am
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Backup, retencion, compactacion y VACUUM semanal de agenteBolsa." `
    -Force | Out-Null

$task = Get-ScheduledTask -TaskName $TaskName
$info = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Host "Tarea '$TaskName' registrada." -ForegroundColor Green
Write-Host ("Estado={0} Proxima={1}" -f $task.State, $info.NextRunTime)
