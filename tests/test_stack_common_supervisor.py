import subprocess

import pytest


def _powershell(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        text=True,
        capture_output=True,
    )


pytestmark = pytest.mark.skipif(
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"], capture_output=True).returncode != 0,
    reason="powershell no disponible",
)


def test_stack_daily_catch_up_needed_when_run_at_passed_and_artifact_missing():
    command = r"""
    . .\scripts\stack_common.ps1
    $result = Test-StackDailyCatchUpNeeded -TimeText '08:30' -Now ([datetime]'2026-07-08T10:00:00') -HasTodayArtifact { param($RunDate) $false }
    Write-Output ($result.should_run.ToString().ToLowerInvariant())
    Write-Output $result.next_run.ToString('yyyy-MM-dd HH:mm')
    """
    proc = _powershell(command)

    assert proc.returncode == 0, proc.stderr
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    assert lines == ["true", "2026-07-09 08:30"]


def test_stack_daily_catch_up_skips_when_today_artifact_exists():
    command = r"""
    . .\scripts\stack_common.ps1
    $result = Test-StackDailyCatchUpNeeded -TimeText '08:30' -Now ([datetime]'2026-07-08T10:00:00') -HasTodayArtifact { param($RunDate) $true }
    Write-Output ($result.should_run.ToString().ToLowerInvariant())
    """
    proc = _powershell(command)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "false"


def test_restart_services_script_does_not_use_reserved_pid_parameter():
    command = r"""
    $content = Get-Content .\scripts\restart_services.ps1 -Raw
    if ($content -match 'param\(\[int\]\$Pid\)') {
        Write-Error 'reserved_pid_parameter_found'
        exit 1
    }
    [void][scriptblock]::Create($content)
    Write-Output 'ok'
    """
    proc = _powershell(command)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"


def test_check_services_script_parses_in_windows_powershell_51():
    command = r"""
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile(
        (Resolve-Path .\scripts\check_services.ps1),
        [ref]$tokens,
        [ref]$errors
    )
    if ($errors.Count -gt 0) {
        $errors | ForEach-Object { Write-Error $_.Message }
        exit 1
    }
    $content = Get-Content .\scripts\check_services.ps1 -Raw
    if ($content -notmatch '\$processRows\s*=\s*@\(') {
        Write-Error 'process_rows_are_not_materialized_before_formatting'
        exit 1
    }
    Write-Output 'ok'
    """
    proc = _powershell(command)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"


def test_scheduler_lock_accepts_managed_venv_launcher_runtime_chain():
    command = r"""
    . .\scripts\stack_common.ps1
    $root = Join-Path ([IO.Path]::GetTempPath()) ("stack-lock-" + [guid]::NewGuid().ToString())
    New-Item -ItemType Directory -Force -Path (Join-Path $root 'data\state') | Out-Null
    [IO.File]::WriteAllText(
        (Join-Path $root 'data\state\scheduler.lock'),
        '{"pid":42,"kind":"scheduler"}'
    )

    function Get-StackRepoRoot { return $root }
    function Get-StackManagedPythonPath { return 'C:\repo\.venv\Scripts\python.exe' }
    $runtime = [pscustomobject]@{
        ProcessId = 42
        ParentProcessId = 41
        CommandLine = 'C:\Python311\python.exe -m agente_bolsa.main schedule'
        ExecutablePath = 'C:\Python311\python.exe'
        CreationDate = $null
    }
    $launcher = [pscustomobject]@{
        ProcessId = 41
        ParentProcessId = 40
        CommandLine = 'C:\repo\.venv\Scripts\python.exe -m agente_bolsa.main schedule'
        ExecutablePath = 'C:\repo\.venv\Scripts\python.exe'
        CreationDate = $null
    }
    function Get-StackProcessByPid {
        param([int]$ProcessId)
        if ($ProcessId -eq 42) { return $runtime }
        if ($ProcessId -eq 41) { return $launcher }
        return $null
    }

    $info = Get-StackSchedulerLockInfo
    Write-Output ($info.compatible.ToString().ToLowerInvariant())
    Write-Output ($info.orphan.ToString().ToLowerInvariant())
    Write-Output ($info.managed_ancestry.ToString().ToLowerInvariant())
    Remove-Item -LiteralPath $root -Recurse -Force
    """
    proc = _powershell(command)

    assert proc.returncode == 0, proc.stderr
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    assert lines[-3:] == ["true", "false", "true"]


def test_scheduler_lock_matches_datetime_creation_date_on_modern_powershell():
    command = r"""
    . .\scripts\stack_common.ps1
    $root = Join-Path ([IO.Path]::GetTempPath()) ("stack-lock-datetime-" + [guid]::NewGuid().ToString())
    New-Item -ItemType Directory -Force -Path (Join-Path $root 'data\state') | Out-Null
    $created = [datetime]'2026-08-12T21:50:29Z'
    $token = ([DateTimeOffset]$created.ToUniversalTime()).ToFileTime() + 3
    [IO.File]::WriteAllText(
        (Join-Path $root 'data\state\scheduler.lock'),
        ('{"pid":42,"kind":"scheduler","token":"' + $token + '"}')
    )

    function Get-StackRepoRoot { return $root }
    function Get-StackManagedPythonPath { return 'C:\repo\.venv\Scripts\python.exe' }
    $runtime = [pscustomobject]@{
        ProcessId = 42
        ParentProcessId = 41
        CommandLine = 'C:\Python311\python.exe -m agente_bolsa.main schedule'
        ExecutablePath = 'C:\Python311\python.exe'
        CreationDate = $created
    }
    $launcher = [pscustomobject]@{
        ProcessId = 41
        ParentProcessId = 40
        CommandLine = 'C:\repo\.venv\Scripts\python.exe -m agente_bolsa.main schedule'
        ExecutablePath = 'C:\repo\.venv\Scripts\python.exe'
        CreationDate = $null
    }
    function Get-StackProcessByPid {
        param([int]$ProcessId)
        if ($ProcessId -eq 42) { return $runtime }
        if ($ProcessId -eq 41) { return $launcher }
        return $null
    }

    $info = Get-StackSchedulerLockInfo
    Write-Output ($info.compatible.ToString().ToLowerInvariant())
    Write-Output ($info.token_match.ToString().ToLowerInvariant())
    Remove-Item -LiteralPath $root -Recurse -Force
    """
    proc = _powershell(command)

    assert proc.returncode == 0, proc.stderr
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    assert lines[-2:] == ["true", "true"]
