from agente_bolsa.config import Settings
from agente_bolsa.scheduler import _acquire_scheduler_lock, _release_scheduler_lock


def test_scheduler_lock_prevents_duplicate_running_pid(tmp_path, monkeypatch):
    settings = Settings(DATA_DIR=tmp_path)
    settings.ensure_runtime_dirs()
    first_pid = 12345
    second_pid = 54321

    monkeypatch.setattr("agente_bolsa.scheduler.os.getpid", lambda: first_pid)
    monkeypatch.setattr("agente_bolsa.scheduler._pid_is_running", lambda pid: pid == first_pid)

    acquired, reason = _acquire_scheduler_lock(settings)

    assert acquired is True
    assert reason == ""

    monkeypatch.setattr("agente_bolsa.scheduler.os.getpid", lambda: second_pid)
    monkeypatch.setattr("agente_bolsa.scheduler._pid_is_running", lambda pid: pid == first_pid)

    acquired_again, reason_again = _acquire_scheduler_lock(settings)

    assert acquired_again is False
    assert "Scheduler ya activo" in reason_again

    monkeypatch.setattr("agente_bolsa.scheduler.os.getpid", lambda: first_pid)
    _release_scheduler_lock(settings)


def test_scheduler_lock_replaces_stale_pid(tmp_path, monkeypatch):
    settings = Settings(DATA_DIR=tmp_path)
    settings.ensure_runtime_dirs()
    stale_pid = 11111
    current_pid = 22222
    lock_path = settings.state_dir / "scheduler.lock"
    lock_path.write_text(str(stale_pid), encoding="utf-8")

    monkeypatch.setattr("agente_bolsa.scheduler.os.getpid", lambda: current_pid)
    monkeypatch.setattr("agente_bolsa.scheduler._pid_is_running", lambda pid: False)

    acquired, reason = _acquire_scheduler_lock(settings)

    assert acquired is True
    assert reason == ""
    assert lock_path.read_text(encoding="utf-8").strip() == str(current_pid)

    _release_scheduler_lock(settings)
