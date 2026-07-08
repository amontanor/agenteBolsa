<#
    stack_status.ps1

    Diagnostico legible o JSON del stack persistente local.
#>

param(
    [switch]$Json
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "stack_common.ps1")

$status = Get-StackStatus
$services = @($status.services)
$foreign = @($status.foreign_processes)

if ($Json) {
    [pscustomobject]@{
        ok = -not [bool]($services | Where-Object { $_.state -in @("DUPLICADO", "FOREIGN") -or $_.lock_orphan }) -and $foreign.Count -eq 0
        generated_at = (Get-Date).ToString("s")
        services = $services
        foreign_processes = $foreign
    } | ConvertTo-Json -Depth 8
    exit 0
}

Write-Host "Stack agenteBolsa - $((Get-Date).ToString('s'))"
Write-Host ""
$services |
    Select-Object `
        service,
        state,
        @{ Name = "pids"; Expression = { ($_.pids -join ",") } },
        lock_pid,
        lock_ok,
        lock_orphan,
        @{ Name = "foreign_pids"; Expression = { ($_.foreign_pids -join ",") } },
        port,
        http_ok |
    Format-Table -AutoSize

$duplicates = @($services | Where-Object { $_.state -eq "DUPLICADO" })
if ($duplicates.Count -gt 0) {
    Write-Host ""
    Write-Host "Duplicados detectados:"
    foreach ($service in $duplicates) {
        Write-Host ("- {0}: PIDs {1}" -f $service.service, ($service.pids -join ", "))
    }
}

if ($foreign.Count -gt 0) {
    Write-Host ""
    Write-Host "Procesos ajenos al .venv detectados:"
    foreach ($proc in $foreign) {
        Write-Host ("- {0}: PID {1} | {2}" -f $proc.service, $proc.pid, $proc.command_line)
    }
}

$orphans = @($services | Where-Object { $_.lock_orphan })
if ($orphans.Count -gt 0) {
    Write-Host ""
    Write-Host "Locks huerfanos:"
    foreach ($service in $orphans) {
        Write-Host ("- {0}: lock_pid={1}" -f $service.service, $service.lock_pid)
    }
}
