<#
    run_codegen_nightly_supervisor.ps1

    Supervisor sin privilegios de administrador para lanzar codegen nightly una
    vez al dia. No arranca scheduler ni aplica diffs.
#>

param(
    [string]$RunAt = "03:00",
    [string]$Config = ""
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "stack_common.ps1")

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$NightlyScript = Join-Path $Repo "scripts\run_codegen_nightly.ps1"
$LogPath = Join-Path $Repo "data\logs\codegen_nightly_supervisor.log"

function Write-CodegenNightlySupervisorLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "s"
    Add-Content -Path $LogPath -Value "[$timestamp] $Message" -Encoding UTF8
}

New-Item -ItemType Directory -Force -Path (Split-Path $LogPath -Parent) | Out-Null

if (-not (Test-Path $NightlyScript)) {
    Write-CodegenNightlySupervisorLog "ERROR nightly_script_missing path=$NightlyScript"
    exit 1
}

Write-CodegenNightlySupervisorLog "START codegen nightly supervisor run_at=$RunAt config=$Config"

$lockTaken = Acquire-StackSingleInstanceLock `
    -ServiceName "codegen_nightly_supervisor" `
    -CommandPattern "run_codegen_nightly_supervisor\.ps1" `
    -Log { param($Message) Write-CodegenNightlySupervisorLog $Message }
if (-not $lockTaken) {
    exit 0
}

try {
    while ($true) {
        $catchUp = Test-StackDailyCatchUpNeeded -TimeText $RunAt -HasTodayArtifact {
            param($RunDate)
            $runsPath = Join-Path $Repo "data\research\codegen_nightly\runs.jsonl"
            if (-not (Test-Path $runsPath)) {
                return $false
            }
            foreach ($line in Get-Content $runsPath -Encoding UTF8) {
                if ($line -match [regex]::Escape($RunDate.ToString("yyyy-MM-dd"))) {
                    return $true
                }
            }
            return $false
        }
        if ($catchUp.should_run) {
            Write-CodegenNightlySupervisorLog "CATCH_UP run_date=$($catchUp.today_run.ToString('yyyy-MM-dd'))"
            if ($Config -ne "") {
                & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $NightlyScript -Config $Config
            } else {
                & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $NightlyScript
            }
            $exitCode = $LASTEXITCODE
            Write-CodegenNightlySupervisorLog "DONE catch_up exit_code=$exitCode"
        }
        $nextRun = $catchUp.next_run
        Write-CodegenNightlySupervisorLog "NEXT_RUN $($nextRun.ToString('s'))"
        while ((Get-Date) -lt $nextRun) {
            $remaining = [int]($nextRun - (Get-Date)).TotalSeconds
            Start-Sleep -Seconds ([Math]::Min([Math]::Max($remaining, 1), 300))
        }

        Write-CodegenNightlySupervisorLog "RUN nightly_script"
        if ($Config -ne "") {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $NightlyScript -Config $Config
        } else {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $NightlyScript
        }
        $exitCode = $LASTEXITCODE
        Write-CodegenNightlySupervisorLog "DONE nightly_script exit_code=$exitCode"
    }
} finally {
    Release-StackSingleInstanceLock -ServiceName "codegen_nightly_supervisor" -Log { param($Message) Write-CodegenNightlySupervisorLog $Message }
}
