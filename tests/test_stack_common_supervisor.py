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
