$ErrorActionPreference = "Stop"

function Get-StackRepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
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

function Get-StackProcessStartText {
    param([object]$Process)
    if ($null -eq $Process -or -not $Process.CreationDate) {
        return "hora desconocida"
    }
    try {
        return ([Management.ManagementDateTimeConverter]::ToDateTime($Process.CreationDate)).ToString("HH:mm")
    } catch {
        return "hora desconocida"
    }
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
    $lockInfo = Get-StackLockInfo -ServiceName $Service.lock -Pattern $Service.pattern
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
    [pscustomobject]@{
        service = $Service.name
        state = $state
        pids = @($rootProcesses | ForEach-Object { $_.ProcessId })
        process_pids = @($processes | ForEach-Object { $_.ProcessId })
        lock_pid = $lockInfo.pid
        lock_ok = [bool]$lockInfo.compatible
        lock_orphan = [bool]$lockInfo.orphan
        port = $Service.port
        http_ok = if ($null -eq $portInfo) { $null } else { [bool]$portInfo.ok }
        command_lines = @($rootProcesses | ForEach-Object { $_.CommandLine })
        process_command_lines = @($processes | ForEach-Object { $_.CommandLine })
    }
}

function Get-StackStatus {
    return @(Get-StackExpectedServices | ForEach-Object { Get-StackServiceStatus -Service $_ })
}

function Start-StackSupervisor {
    param([hashtable]$Service)
    $repo = Get-StackRepoRoot
    $scriptPath = Join-Path $repo $Service.script
    Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $scriptPath) -WorkingDirectory $repo -WindowStyle Hidden
}
