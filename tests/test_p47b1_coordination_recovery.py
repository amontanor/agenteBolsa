from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path

import pytest

from agente_bolsa import scheduler
from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.postmarket_coordination import (
    ACTIVE_KEY,
    LEASE_SCHEMA_VERSION,
    PostmarketCoordinator,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        DATA_DIR=tmp_path / "data",
        DATABASE_PATH=tmp_path / "data" / "state" / "test.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "data" / "logs" / "agents",
        TRADING_MODE="paper",
        ALLOW_LIVE_TRADING=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )


def _event_payloads(store: Store, event_type: str | None = None) -> list[dict]:
    with store.connect() as conn:
        if event_type:
            rows = conn.execute(
                "SELECT payload_json FROM agent_events WHERE event_type = ? ORDER BY created_at",
                (event_type,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT payload_json FROM agent_events ORDER BY created_at").fetchall()
    return [json.loads(row[0]) for row in rows]


def _process_acquire_worker(data_dir: str, database_path: str, barrier, output, index: int) -> None:
    settings = Settings(
        _env_file=None,
        DATA_DIR=Path(data_dir),
        DATABASE_PATH=Path(database_path),
        AGENT_LOGS_DIR=Path(data_dir) / "logs" / "agents",
        TRADING_MODE="paper",
        ALLOW_LIVE_TRADING=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )
    store = Store(settings.database_path, settings.agent_logs_dir)
    barrier.wait()
    lease = PostmarketCoordinator(settings, store).acquire(
        session_date="2026-07-17",
        run_id=f"pmr-process-{index}",
        trigger="scheduled",
    )
    output.put((index, lease.effective, lease.reason))
    if lease.effective:
        PostmarketCoordinator(settings, store).terminal(lease, "completed", reason="process_winner")


def test_completed_and_failed_terminals_release_active_lease(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    for status in ("completed", "failed"):
        lease = PostmarketCoordinator(settings, store).acquire(
            session_date=f"2026-07-{15 if status == 'completed' else 16}",
            run_id=f"pmr-{status}",
            trigger="scheduled",
        )
        assert lease.effective
        PostmarketCoordinator(settings, store).terminal(lease, status, reason=f"test_{status}")
        assert store.get_runtime_value(ACTIVE_KEY) is None
        assert any(
            item.get("event_type") == "lease_released" and item.get("run_id") == lease.run_id
            for item in _event_payloads(store)
        )


def test_exception_path_releases_in_finally(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    coordinator = PostmarketCoordinator(settings, store)
    lease = coordinator.acquire(session_date="2026-07-17", run_id="pmr-exception", trigger="scheduled")
    try:
        raise RuntimeError("injected_stage_failure")
    except RuntimeError as exc:
        coordinator.terminal(lease, "failed", reason="stage_failed", error=repr(exc))
    assert store.get_runtime_value(ACTIVE_KEY) is None
    terminals = _event_payloads(store, "postmarket_run")
    assert any(item.get("run_id") == "pmr-exception" and item.get("status") == "failed" for item in terminals)


def test_skipped_lease_does_not_release_foreign_owner(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    owner = PostmarketCoordinator(settings, store).acquire(
        session_date="2026-07-17", run_id="pmr-owner", trigger="scheduled"
    )
    contender = PostmarketCoordinator(settings, store).acquire(
        session_date="2026-07-17", run_id="pmr-contender", trigger="bootstrap"
    )
    assert owner.effective and not contender.effective
    PostmarketCoordinator(settings, store).terminal(contender, "skipped", reason=contender.reason)
    active = store.get_runtime_value(ACTIVE_KEY)
    assert active and active["run_id"] == "pmr-owner"
    PostmarketCoordinator(settings, store).terminal(owner, "failed", reason="cleanup")


def test_terminal_residual_is_recovered_without_rewriting_original(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.set_runtime_value(
        ACTIVE_KEY,
        {
            "lease_schema_version": LEASE_SCHEMA_VERSION,
            "status": "active",
            "session_date": "2026-07-17",
            "run_id": "pmr-terminal-residual",
            "owner_pid": 999999,
            "owner_process_token": "old",
            "owner_token": "old",
            "started_at": "2026-07-17T20:00:00+00:00",
        },
    )
    terminal = {
        "schema_version": "p-l45b1.postmarket-run.v1",
        "run_id": "pmr-terminal-residual",
        "stage": "terminal",
        "status": "completed",
        "content_hash": "terminal-hash",
    }
    store.record_append_only_event(
        event_id="pmr:pmr-terminal-residual:terminal:completed",
        event_type="postmarket_run",
        cycle_id="pmr-terminal-residual",
        payload=terminal,
    )
    lease = PostmarketCoordinator(settings, store).acquire(
        session_date="2026-07-17", run_id="pmr-replacement", trigger="scheduled"
    )
    assert lease.effective
    assert store.get_runtime_value(ACTIVE_KEY)["run_id"] == "pmr-replacement"
    with store.connect() as conn:
        original = conn.execute(
            "SELECT payload_json FROM agent_events WHERE event_id = ?",
            ("pmr:pmr-terminal-residual:terminal:completed",),
        ).fetchone()
    assert json.loads(original[0])["content_hash"] == "terminal-hash"
    assert any(item.get("event_type") == "terminal_lease_recovered" for item in _event_payloads(store))
    PostmarketCoordinator(settings, store).terminal(lease, "completed", reason="cleanup")


def test_skipped_terminal_residual_is_recovered_without_reprocessing(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.set_runtime_value(
        ACTIVE_KEY,
        {
            "status": "active",
            "session_date": "2026-07-17",
            "run_id": "pmr-skipped-residual",
            "owner_pid": 999999,
            "owner_process_token": "old",
        },
    )
    store.record_append_only_event(
        event_id="pmr:pmr-skipped-residual:terminal:skipped",
        event_type="postmarket_run",
        cycle_id="pmr-skipped-residual",
        payload={
            "schema_version": "p-l45b1.postmarket-run.v1",
            "run_id": "pmr-skipped-residual",
            "stage": "terminal",
            "status": "skipped",
            "content_hash": "skipped-hash",
        },
    )
    lease = PostmarketCoordinator(settings, store).acquire(
        session_date="2026-07-17", run_id="pmr-skipped-replacement", trigger="scheduled"
    )
    assert lease.effective and lease.reason == "terminal_lease_recovered"
    assert store.get_runtime_value(ACTIVE_KEY)["run_id"] == "pmr-skipped-replacement"
    PostmarketCoordinator(settings, store).terminal(lease, "completed", reason="cleanup")


def test_dead_owner_and_pid_reuse_are_recovered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.set_runtime_value(
        ACTIVE_KEY,
        {
            "status": "active",
            "session_date": "2026-07-17",
            "run_id": "pmr-dead",
            "owner_pid": 999999,
            "owner_process_token": "dead",
        },
    )
    lease = PostmarketCoordinator(settings, store).acquire(
        session_date="2026-07-17", run_id="pmr-recovered", trigger="scheduled"
    )
    assert lease.effective and lease.reason == "dead_owner_recovered"
    PostmarketCoordinator(settings, store).terminal(lease, "failed", reason="cleanup")

    current_pid = os.getpid()
    store.set_runtime_value(
        ACTIVE_KEY,
        {
            "status": "active",
            "session_date": "2026-07-17",
            "run_id": "pmr-reused",
            "owner_pid": current_pid,
            "owner_process_token": "old-process-token",
        },
    )
    lease = PostmarketCoordinator(settings, store).acquire(
        session_date="2026-07-17", run_id="pmr-reused-replacement", trigger="scheduled"
    )
    assert lease.effective and lease.reason == "owner_token_mismatch_recovered"
    PostmarketCoordinator(settings, store).terminal(lease, "failed", reason="cleanup")


def test_live_owner_is_never_stolen(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    first = PostmarketCoordinator(settings, store)
    owner = first.acquire(session_date="2026-07-17", run_id="pmr-live", trigger="scheduled")
    contender = PostmarketCoordinator(settings, store).acquire(
        session_date="2026-07-17", run_id="pmr-contender", trigger="scheduled"
    )
    assert owner.effective and not contender.effective and contender.reason == "postmarket_already_running"
    first.terminal(owner, "failed", reason="cleanup")


def test_twenty_five_processes_have_one_effective_owner(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    Store(settings.database_path, settings.agent_logs_dir).ensure_schema()
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(25)
    output = ctx.Queue()
    processes = [
        ctx.Process(
            target=_process_acquire_worker,
            args=(str(settings.data_dir), str(settings.database_path), barrier, output, index),
        )
        for index in range(25)
    ]
    for process in processes:
        process.start()
    results = [output.get(timeout=45) for _ in processes]
    for process in processes:
        process.join(timeout=45)
        assert process.exitcode == 0
    assert sum(bool(item[1]) for item in results) == 1
    assert all(item[2] in {"postmarket_already_running", "session_already_completed", "terminal_lease_recovered"} for item in results if not item[1])
    assert not any("database is locked" in str(item).lower() for item in results)


def test_scheduler_lock_missing_legacy_malformed_and_reused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path)
    settings.ensure_runtime_dirs()
    current_pid = 22222
    monkeypatch.setattr(scheduler.os, "getpid", lambda: current_pid)
    monkeypatch.setattr(scheduler, "_process_start_token", lambda pid: f"token-{pid}")
    monkeypatch.setattr(scheduler, "_pid_is_running", lambda pid: False)

    acquired, _ = scheduler._acquire_scheduler_lock(settings)
    assert acquired
    payload = scheduler._read_scheduler_lock(settings.state_dir / "scheduler.lock")
    assert payload["schema_version"] == scheduler.SCHEDULER_LOCK_SCHEMA_VERSION
    scheduler._release_scheduler_lock(settings)
    assert not (settings.state_dir / "scheduler.lock").exists()

    legacy = settings.state_dir / "scheduler.lock"
    legacy.write_text("11111", encoding="utf-8")
    acquired, _ = scheduler._acquire_scheduler_lock(settings)
    assert acquired
    scheduler._release_scheduler_lock(settings)

    legacy.write_text("{not-json", encoding="utf-8")
    acquired, _ = scheduler._acquire_scheduler_lock(settings)
    assert not acquired
    legacy.unlink()

    legacy.write_text(json.dumps({"pid": 33333, "token": "old", "kind": "scheduler"}), encoding="utf-8")
    monkeypatch.setattr(scheduler, "_pid_is_running", lambda pid: pid == 33333)
    acquired, _ = scheduler._acquire_scheduler_lock(settings)
    assert acquired
    scheduler._release_scheduler_lock(settings)


def test_scheduler_lock_live_owner_and_token_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path)
    settings.ensure_runtime_dirs()
    path = settings.state_dir / "scheduler.lock"
    path.write_text(json.dumps({"pid": 33333, "token": "same", "kind": "scheduler"}), encoding="utf-8")
    monkeypatch.setattr(scheduler.os, "getpid", lambda: 44444)
    monkeypatch.setattr(scheduler, "_pid_is_running", lambda pid: pid == 33333)
    monkeypatch.setattr(scheduler, "_process_start_token", lambda pid: "same")
    acquired, reason = scheduler._acquire_scheduler_lock(settings)
    assert not acquired and "Scheduler ya activo" in reason

    path.write_text(json.dumps({"pid": 33333, "token": "old", "kind": "scheduler"}), encoding="utf-8")
    monkeypatch.setattr(scheduler, "_process_start_token", lambda pid: "new")
    acquired, _ = scheduler._acquire_scheduler_lock(settings)
    assert acquired
    scheduler._release_scheduler_lock(settings)


def test_scheduler_lock_release_requires_owner_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path)
    settings.ensure_runtime_dirs()
    path = settings.state_dir / "scheduler.lock"
    path.write_text(json.dumps({"pid": 44444, "token": "owner", "kind": "scheduler"}), encoding="utf-8")
    monkeypatch.setattr(scheduler.os, "getpid", lambda: 44444)
    monkeypatch.setattr(scheduler, "_process_start_token", lambda pid: "other")
    scheduler._release_scheduler_lock(settings)
    assert path.exists()
    monkeypatch.setattr(scheduler, "_process_start_token", lambda pid: "owner")
    scheduler._release_scheduler_lock(settings)
    assert not path.exists()


def test_scheduler_status_exposes_lock_diagnosis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path)
    Store(settings.database_path, settings.agent_logs_dir).ensure_schema()
    settings.ensure_runtime_dirs()
    (settings.state_dir / "scheduler.lock").write_text("{bad", encoding="utf-8")
    status = scheduler.scheduler_status(settings)
    assert status["scheduler_lock"]["status"] == "malformed_lock"


def test_no_new_tables_are_created(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    with store.connect() as conn:
        before = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    lease = PostmarketCoordinator(settings, store).acquire(
        session_date="2026-07-17", run_id="pmr-tables", trigger="scheduled"
    )
    PostmarketCoordinator(settings, store).terminal(lease, "completed", reason="cleanup")
    with store.connect() as conn:
        after = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert after == before
