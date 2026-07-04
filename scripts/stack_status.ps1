<#
    stack_status.ps1

    Diagnostico legible o JSON del stack persistente local.
#>

param(
    [switch]$Json
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "stack_common.ps1")

$services = Get-StackStatus

if ($Json) {
    [pscustomobject]@{
        ok = -not [bool]($services | Where-Object { $_.state -eq "DUPLICADO" -or $_.lock_orphan })
        generated_at = (Get-Date).ToString("s")
        services = $services
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

$orphans = @($services | Where-Object { $_.lock_orphan })
if ($orphans.Count -gt 0) {
    Write-Host ""
    Write-Host "Locks huerfanos:"
    foreach ($service in $orphans) {
        Write-Host ("- {0}: lock_pid={1}" -f $service.service, $service.lock_pid)
    }
}
