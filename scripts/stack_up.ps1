<#
    stack_up.ps1

    Arranca solo las piezas ausentes del stack local. No duplica procesos vivos.
#>

param(
    [switch]$Json
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "stack_common.ps1")

$repo = Get-StackRepoRoot
$results = @()

foreach ($service in Get-StackExpectedServices) {
    $status = Get-StackServiceStatus -Service $service
    if ($status.state -eq "CORRIENDO" -or $status.state -eq "DUPLICADO") {
        $results += [pscustomobject]@{
            service = $service.name
            action = "already"
            state = $status.state
            pids = $status.pids
            detail = ""
        }
        continue
    }

    if ($service.kind -eq "supervisor") {
        Start-StackSupervisor -Service $service
        $results += [pscustomobject]@{
            service = $service.name
            action = "started"
            state = $status.state
            pids = @()
            detail = $service.script
        }
        continue
    }

    if ($service.kind -eq "task" -or $service.kind -eq "web") {
        $task = Get-ScheduledTask -TaskName $service.task -ErrorAction SilentlyContinue
        if ($null -eq $task) {
            $results += [pscustomobject]@{
                service = $service.name
                action = "missing_task"
                state = $status.state
                pids = @()
                detail = $service.task
            }
            continue
        }
        Start-ScheduledTask -TaskName $service.task
        $results += [pscustomobject]@{
            service = $service.name
            action = "started"
            state = $status.state
            pids = @()
            detail = $service.task
        }
    }
}

if ($Json) {
    [pscustomobject]@{
        generated_at = (Get-Date).ToString("s")
        results = $results
        status = Get-StackStatus
    } | ConvertTo-Json -Depth 8
    exit 0
}

Write-Host "Stack up agenteBolsa - $((Get-Date).ToString('s'))"
$results | Format-Table -AutoSize
