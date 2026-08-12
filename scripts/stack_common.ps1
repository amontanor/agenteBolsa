$ErrorActionPreference = "Stop"

function Get-StackRepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Get-StackRunSchedule {
    param(
        [string]$TimeText,
        [datetime]$Now = (Get-Date)
    )
    $parts = $TimeText.Split(":")
    if ($parts.Count -ne 2) {
        throw "RunAt invalido. Usa HH:mm."
    }
    $hour = 0
    $minute = 0
    if (-not [int]::TryParse($parts[0], [ref]$hour) -or -not [int]::TryParse($parts[1], [ref]$minute)) {
        throw "RunAt invalido. Usa HH:mm."
    }
    if ($hour -lt 0 -or $hour -gt 23 -or $minute -lt 0 -or $minute -gt 59) {
        throw "RunAt invalido. Usa HH:mm en formato 24h."
    }
    $todayRun = Get-Date -Date $Now.Date -Hour $hour -Minute $minute -Second 0
    $nextRun = if ($todayRun -le $Now) { $todayRun.AddDays(1) } else { $todayRun }
    return @{
        today_run = $todayRun
        next_run = $nextRun
    }
}

function Test-StackDailyCatchUpNeeded {
    param(
        [string]$TimeText,
        [scriptblock]$HasTodayArtifact,
        [datetime]$Now = (Get-Date)
    )
    $schedule = Get-StackRunSchedule -TimeText $TimeText -Now $Now
    $artifactExists = $false
    if ($HasTodayArtifact) {
        $artifactExists = [bool](& $HasTodayArtifact $schedule.today_run.Date)
    }
    return @{
        should_run = ($Now -ge $schedule.today_run) -and (-not $artifactExists)
        artifact_exists = $artifactExists
        today_run = $schedule.today_run
        next_run = $schedule.next_run
    }
}

function Get-StackRunDir {
    $repo = Get-StackRepoRoot
    $runDir = Join-Path $repo "data\run"
    New-Item -ItemType Directory -Force -Path $runDir | Out-Null
    return $runDir
}

function Get-StackProcessByPid {
    param([int]$ProcessId)
    try {
        return Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction Stop
    } catch {
        return $null
    }
}

function Test-StackProcessCompatible {
    param(
        [int]$ProcessId,
        [string]$CommandPattern
    )
    $proc = Get-StackProcessByPid -ProcessId $ProcessId
    if ($null -eq $proc) {
        return $false
    }
    return [bool]($proc.CommandLine -match $CommandPattern)
}

function ConvertTo-StackProcessCreationDate {
    param([object]$Process)
    if ($null -eq $Process -or -not $Process.CreationDate) {
        return $null
    }
    if ($Process.CreationDate -is [datetime]) {
        return [datetime]$Process.CreationDate
    }
    try {
        return [Management.ManagementDateTimeConverter]::ToDateTime([string]$Process.CreationDate)
    } catch {
        return $null
    }
}

function Get-StackProcessStartText {
    param([object]$Process)
    $start = ConvertTo-StackProcessCreationDate -Process $Process
    if ($null -eq $start) {
        return "hora desconocida"
    }
    return $start.ToString("HH:mm")
}

function Acquire-StackSingleInstanceLock {
    param(
        [string]$ServiceName,
        [string]$CommandPattern,
        [scriptblock]$Log
    )
    $runDir = Get-StackRunDir
    $lockPath = Join-Path $runDir "$ServiceName.pid"
    if (Test-Path $lockPath) {
        $raw = (Get-Content $lockPath -Raw).Trim()
        $existingPid = 0
        if ([int]::TryParse($raw, [ref]$existingPid) -and $existingPid -gt 0) {
            $proc = Get-StackProcessByPid -ProcessId $existingPid
            if ($null -ne $proc -and $proc.CommandLine -match $CommandPattern) {
                $started = Get-StackProcessStartText -Process $proc
                $message = "ya corriendo (PID $existingPid desde $started)"
                if ($Log) { & $Log $message }
                Write-Host "$ServiceName $message"
                return $false
            }
        }
        if ($Log) { & $Log "lock_huerfano path=$lockPath previous=$raw" }
    }
    Set-Content -Path $lockPath -Value ([string]$PID) -Encoding ASCII
    if ($Log) { & $Log "LOCK service=$ServiceName pid=$PID path=$lockPath" }
    return $true
}

function Release-StackSingleInstanceLock {
    param(
        [string]$ServiceName,
        [scriptblock]$Log
    )
    $lockPath = Join-Path (Get-StackRunDir) "$ServiceName.pid"
    if (-not (Test-Path $lockPath)) {
        return
    }
    $raw = (Get-Content $lockPath -Raw).Trim()
    if ($raw -eq [string]$PID) {
        Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
        if ($Log) { & $Log "UNLOCK service=$ServiceName pid=$PID" }
    }
}

function Get-StackExpectedServices {
    return @(
        @{ name = "scheduler"; kind = "task"; task = "AgenteBolsaScheduler"; pattern = "agente_bolsa\.main schedule(\s|$)|run_scheduler_supervisor\.ps1"; lock = "scheduler" },
        @{ name = "web"; kind = "web"; task = "AgenteBolsaWeb"; pattern = "agente_bolsa\.main web|streamlit.*web_app\.py"; port = 8501; lock = "web" },
        @{ name = "telegram_radar_supervisor"; kind = "supervisor"; script = "scripts\run_telegram_radar_supervisor.ps1"; pattern = "run_telegram_radar_supervisor\.ps1"; lock = "telegram_radar_supervisor" },
        @{ name = "overlay_shadow_supervisor"; kind = "supervisor"; script = "scripts\run_overlay_shadow_supervisor.ps1"; pattern = "run_overlay_shadow_supervisor\.ps1"; lock = "overlay_shadow_supervisor" },
        @{ name = "ci_digest_supervisor"; kind = "supervisor"; script = "scripts\run_ci_digest_supervisor.ps1"; pattern = "run_ci_digest_supervisor\.ps1"; lock = "ci_digest_supervisor" },
        @{ name = "codegen_nightly_supervisor"; kind = "supervisor"; script = "scripts\run_codegen_nightly_supervisor.ps1"; pattern = "run_codegen_nightly_supervisor\.ps1"; lock = "codegen_nightly_supervisor" },
        @{ name = "core_sleeve_supervisor"; kind = "supervisor"; script = "scripts\run_core_sleeve_supervisor.ps1"; pattern = "run_core_sleeve_supervisor\.ps1"; lock = "core_sleeve_supervisor" }
    )
}

function Get-StackMatchingProcesses {
    param([string]$Pattern)
    return @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -match $Pattern })
}

function Get-StackManagedPythonPath {
    return (Join-Path (Get-StackRepoRoot) ".venv\Scripts\python.exe")
}

function Test-StackManagedProcessAncestry {
    param(
        [object]$Process,
        [string]$CommandPattern
    )
    if ($null -eq $Process) {
        return $false
    }
    if ([string]$Process.CommandLine -notmatch $CommandPattern) {
        return $false
    }

    $managedPython = Get-StackManagedPythonPath
    $seen = @{}
    $current = $Process
    while ($null -ne $current) {
        $currentPid = [int]$current.ProcessId
        if ($seen.ContainsKey($currentPid)) {
            return $false
        }
        $seen[$currentPid] = $true

        if ([string]$current.ExecutablePath -eq $managedPython) {
            return $true
        }
        if ([string]$current.CommandLine -match "run_scheduler_supervisor\.ps1") {
            return $true
        }

        $parentPid = [int]$current.ParentProcessId
        if ($parentPid -le 0 -or $parentPid -eq $currentPid) {
            return $false
        }
        $current = Get-StackProcessByPid -ProcessId $parentPid
    }
    return $false
}

function Get-StackRootProcesses {
    param([object[]]$Processes)
    if ($null -eq $Processes -or $Processes.Count -eq 0) {
        return @()
    }
    $processIds = @{}
    foreach ($process in $Processes) {
        $processIds[[int]$process.ProcessId] = $true
    }
    return @($Processes | Where-Object { -not $processIds.ContainsKey([int]$_.ParentProcessId) })
}

function Test-StackForeignServiceRoot {
    param(
        [hashtable]$Service,
        [object]$Process
    )
    if ($null -eq $Process) {
        return $false
    }
    $managedPython = Get-StackManagedPythonPath
    $commandLine = [string]$Process.CommandLine
    $executable = [string]$Process.ExecutablePath
    if ($Service.name -eq "scheduler") {
        if ($commandLine -match "run_scheduler_supervisor\.ps1") {
            return $false
        }
        return -not ($executable -eq $managedPython)
    }
    if ($Service.name -eq "web") {
        return -not ($executable -eq $managedPython)
    }
    return $false
}

function Get-StackForeignProcesses {
    $foreign = @()
    foreach ($service in Get-StackExpectedServices) {
        if ($service.name -notin @("scheduler", "web")) {
            continue
        }
        $roots = @(Get-StackRootProcesses -Processes (Get-StackMatchingProcesses -Pattern $service.pattern))
        foreach ($proc in $roots) {
            if (Test-StackForeignServiceRoot -Service $service -Process $proc) {
                $foreign += [pscustomobject]@{
                    service = $service.name
                    pid = [int]$proc.ProcessId
                    parent_pid = [int]$proc.ParentProcessId
                    executable = [string]$proc.ExecutablePath
                    command_line = [string]$proc.CommandLine
                }
            }
        }
    }
    return @($foreign | Sort-Object service, pid -Unique)
}

function Stop-StackForeignProcesses {
    $foreign = @(Get-StackForeignProcesses)
    foreach ($proc in $foreign) {
        try {
            taskkill /F /T /PID $proc.pid 2>$null | Out-Null
        } catch {
        }
    }
    return $foreign
}

function Get-StackLockInfo {
    param(
        [string]$ServiceName,
        [string]$Pattern
    )
    $path = Join-Path (Get-StackRunDir) "$ServiceName.pid"
    if (-not (Test-Path $path)) {
        return @{ path = $path; pid = $null; alive = $false; compatible = $false; orphan = $false }
    }
    $raw = (Get-Content $path -Raw).Trim()
    $pidValue = 0
    if (-not [int]::TryParse($raw, [ref]$pidValue)) {
        return @{ path = $path; pid = $null; alive = $false; compatible = $false; orphan = $true }
    }
    $proc = Get-StackProcessByPid -ProcessId $pidValue
    $compatible = $null -ne $proc -and $proc.CommandLine -match $Pattern
    return @{ path = $path; pid = $pidValue; alive = $null -ne $proc; compatible = $compatible; orphan = -not $compatible }
}

function Get-StackSchedulerLockInfo {
    $repo = Get-StackRepoRoot
    $path = Join-Path $repo "data\state\scheduler.lock"
    if (-not (Test-Path $path)) {
        return @{ path = $path; pid = $null; alive = $false; compatible = $false; orphan = $false; status = "missing_lock"; token_match = $false }
    }
    $raw = ""
    try { $raw = (Get-Content $path -Raw).Trim() } catch {
        return @{ path = $path; pid = $null; alive = $false; compatible = $false; orphan = $true; status = "malformed_lock"; token_match = $false }
    }
    $payload = $null
    try { $payload = $raw | ConvertFrom-Json } catch {
        $legacyPid = 0
        if (-not [int]::TryParse($raw, [ref]$legacyPid)) {
            return @{ path = $path; pid = $null; alive = $false; compatible = $false; orphan = $true; status = "malformed_lock"; token_match = $false }
        }
        $payload = [pscustomobject]@{ pid = $legacyPid; token = $null; kind = "legacy" }
    }
    if ($payload -is [int] -or $payload -is [long]) {
        $payload = [pscustomobject]@{ pid = [int]$payload; token = $null; kind = "legacy" }
    }
    $pidValue = 0
    if (-not [int]::TryParse([string]$payload.pid, [ref]$pidValue) -or $pidValue -le 0) {
        return @{ path = $path; pid = $null; alive = $false; compatible = $false; orphan = $true; status = "malformed_lock"; token_match = $false }
    }
    $proc = Get-StackProcessByPid -ProcessId $pidValue
    $alive = $null -ne $proc
    $compatible = $alive -and (Test-StackManagedProcessAncestry -Process $proc -CommandPattern "agente_bolsa\.main schedule(s|$)")
    $expected = [string]($payload.owner_process_token)
    if ([string]::IsNullOrWhiteSpace($expected)) { $expected = [string]($payload.token) }
    $actual = $null
    if ($alive -and $proc.CreationDate) {
        $start = ConvertTo-StackProcessCreationDate -Process $proc
        if ($null -ne $start) {
            $actual = ([DateTimeOffset]$start.ToUniversalTime()).ToFileTime()
        }
    }
    $tokenMatch = $false
    $expectedTicks = 0L
    $actualTicks = 0L
    if (
        -not [string]::IsNullOrWhiteSpace($expected) -and
        $null -ne $actual -and
        [long]::TryParse($expected, [ref]$expectedTicks) -and
        [long]::TryParse([string]$actual, [ref]$actualTicks)
    ) {
        # CIM and the Python runtime can round the same FILETIME by a few
        # 100-ns ticks. One second still rejects a genuinely reused PID.
        $tokenMatch = [math]::Abs([decimal]$actualTicks - [decimal]$expectedTicks) -le 10000000
    }
    if (-not $alive) { $status = "stale_dead_owner" }
    elseif ($expected -and $actual -and -not $tokenMatch) { $status = "pid_reused" }
    elseif (-not $compatible) { $status = "owner_alive" }
    else { $status = "owner_alive" }
    return @{
        path = $path
        pid = $pidValue
        alive = $alive
        compatible = ($compatible -and ($tokenMatch -or [string]::IsNullOrWhiteSpace($expected)))
        orphan = (-not $alive) -or (-not $compatible)
        status = $status
        token = $expected
        token_match = $tokenMatch
        managed_ancestry = [bool]$compatible
    }
}

function Test-StackPort {
    param([int]$Port)
    try {
        $response = Invoke-WebRequest -UseBasicParsing ("http://127.0.0.1:{0}" -f $Port) -TimeoutSec 3
        return @{ ok = ($response.StatusCode -eq 200); status = $response.StatusCode }
    } catch {
        return @{ ok = $false; status = $null }
    }
}

function Get-StackServiceStatus {
    param([hashtable]$Service)
    $processes = @(Get-StackMatchingProcesses -Pattern $Service.pattern)
    $rootProcesses = @(Get-StackRootProcesses -Processes $processes)
    $lockInfo = if ($Service.name -eq "scheduler") {
        Get-StackSchedulerLockInfo
    } else {
        Get-StackLockInfo -ServiceName $Service.lock -Pattern $Service.pattern
    }
    $portInfo = $null
    if ($Service.kind -eq "web") {
        $portInfo = Test-StackPort -Port ([int]$Service.port)
    }
    $state = "PARADO"
    if ($rootProcesses.Count -gt 1) {
        $state = "DUPLICADO"
    } elseif ($rootProcesses.Count -eq 1 -or ($portInfo -and $portInfo.ok) -or $lockInfo.compatible) {
        $state = "CORRIENDO"
    }
    $foreignRoots = @($rootProcesses | Where-Object { Test-StackForeignServiceRoot -Service $Service -Process $_ })
    if ($foreignRoots.Count -gt 0) {
        $state = "FOREIGN"
    }
    [pscustomobject]@{
        service = $Service.name
        state = $state
        pids = @($rootProcesses | ForEach-Object { $_.ProcessId })
        process_pids = @($processes | ForEach-Object { $_.ProcessId })
        foreign_pids = @($foreignRoots | ForEach-Object { $_.ProcessId })
        lock_pid = $lockInfo.pid
        lock_ok = [bool]$lockInfo.compatible
        lock_orphan = [bool]$lockInfo.orphan
        lock_status = $lockInfo.status
        port = $Service.port
        http_ok = if ($null -eq $portInfo) { $null } else { [bool]$portInfo.ok }
        command_lines = @($rootProcesses | ForEach-Object { $_.CommandLine })
        foreign_command_lines = @($foreignRoots | ForEach-Object { $_.CommandLine })
        process_command_lines = @($processes | ForEach-Object { $_.CommandLine })
    }
}

function Get-StackStatus {
    $services = @(Get-StackExpectedServices | ForEach-Object { Get-StackServiceStatus -Service $_ })
    $foreign = @(Get-StackForeignProcesses)
    return [pscustomobject]@{
        services = $services
        foreign_processes = $foreign
    }
}

function Start-StackSupervisor {
    param([hashtable]$Service)
    $repo = Get-StackRepoRoot
    $scriptPath = Join-Path $repo $Service.script
    Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $scriptPath) -WorkingDirectory $repo -WindowStyle Hidden
}
