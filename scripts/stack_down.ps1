<#
    stack_down.ps1

    Detiene supervisores. Scheduler y web solo se tocan con -IncludeScheduled.
#>

param(
    [switch]$IncludeScheduled,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "stack_common.ps1")

$results = @()

foreach ($service in Get-StackExpectedServices) {
    if ($service.kind -ne "supervisor" -and -not $IncludeScheduled) {
        $results += [pscustomobject]@{
            service = $service.name
            action = "skipped"
            pids = @()
            detail = "scheduled_service"
        }
        continue
    }

    if (($service.kind -eq "task" -or $service.kind -eq "web") -and $IncludeScheduled) {
        $task = Get-ScheduledTask -TaskName $service.task -ErrorAction SilentlyContinue
        if ($null -ne $task) {
            Stop-ScheduledTask -TaskName $service.task -ErrorAction SilentlyContinue
        }
    }

    $processes = Get-StackMatchingProcesses -Pattern $service.pattern
    foreach ($process in $processes) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }

    $lock = Get-StackLockInfo -ServiceName $service.lock -Pattern $service.pattern
    if ($lock.orphan -or $processes.Count -gt 0) {
        $lockPath = Join-Path (Get-StackRunDir) "$($service.lock).pid"
        Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
    }

    $results += [pscustomobject]@{
        service = $service.name
        action = if ($processes.Count -gt 0) { "stopped" } else { "already_stopped" }
        pids = @($processes | ForEach-Object { $_.ProcessId })
        detail = if ($service.kind -eq "supervisor") { $service.script } else { $service.task }
    }
}

if ($Json) {
    [pscustomobject]@{
        generated_at = (Get-Date).ToString("s")
        include_scheduled = [bool]$IncludeScheduled
        results = $results
        status = Get-StackStatus
    } | ConvertTo-Json -Depth 8
    exit 0
}

Write-Host "Stack down agenteBolsa - $((Get-Date).ToString('s'))"
$results | Format-Table -AutoSize
