from __future__ import annotations

import json
import multiprocessing as mp
import os
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty

from apscheduler.events import (
    EVENT_JOB_MAX_INSTANCES,
    EVENT_JOB_MISSED,
    JobExecutionEvent,
    JobSubmissionEvent,
)

from agente_bolsa import scheduler
from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools import postmarket_coordination as coordination
from agente_bolsa.tools.postmarket_coordination import PostmarketCoordinator


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        DATA_DIR=tmp_path / "data",
        DATABASE_PATH=tmp_path / "data" / "state" / "qa.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "data" / "logs",
        TRADING_MODE="paper",
        ALLOW_LIVE_TRADING=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )


def _process_event_writer(db_path: str, logs_dir: str, barrier, queue) -> None:
    store = Store(Path(db_path), Path(logs_dir))
    payload = {
        "schema_version": "p-l45b1.postmarket-run.v1",
        "status": "completed",
        "content_hash": "process-race",
    }
    try:
        barrier.wait(timeout=30)
        result = store.record_append_only_event(
            event_id="pmr:process-race",
            event_type="postmarket_run",
            cycle_id="pmr:process-race",
            payload=payload,
        )
        queue.put(("ok", result["status"]))
    except Exception as exc:  # pragma: no cover - assertion reports child failures.
        queue.put(("error", type(exc).__name__, str(exc)))


def _process_lease_writer(db_path: str, logs_dir: str, barrier, release, queue, run_id: str) -> None:
    database_path = Path(db_path)
    settings = Settings(
        _env_file=None,
        DATA_DIR=database_path.parent.parent,
        DATABASE_PATH=database_path,
        AGENT_LOGS_DIR=Path(logs_dir),
        TRADING_MODE="paper",
        ALLOW_LIVE_TRADING=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )
    store = Store(database_path, Path(logs_dir))
    try:
        barrier.wait(timeout=30)
        lease = PostmarketCoordinator(settings, store).acquire(
            session_date="2026-07-15",
            run_id=run_id,
            trigger="scheduled",
        )
        queue.put(("ok", run_id, lease.effective, lease.reason))
        release.wait(30)
    except Exception as exc:  # pragma: no cover - assertion reports child failures.
        queue.put(("error", run_id, type(exc).__name__, str(exc)))


def _process_distinct_session_writer(db_path: str, logs_dir: str, barrier, queue, run_id: str, session_date: str) -> None:
    database_path = Path(db_path)
    settings = Settings(
        _env_file=None,
        DATA_DIR=database_path.parent.parent,
        DATABASE_PATH=database_path,
        AGENT_LOGS_DIR=Path(logs_dir),
        TRADING_MODE="paper",
        ALLOW_LIVE_TRADING=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )
    store = Store(database_path, Path(logs_dir))
    try:
        barrier.wait(timeout=30)
        lease = PostmarketCoordinator(settings, store).acquire(
            session_date=session_date,
            run_id=run_id,
            trigger="scheduled",
        )
        queue.put(("ok", run_id, lease.effective, lease.reason))
    except Exception as exc:  # pragma: no cover - assertion reports child failures.
        queue.put(("error", run_id, type(exc).__name__, str(exc)))


def _collect_process_results(processes, queue, expected: int) -> list[tuple]:
    results = []
    for _ in range(expected):
        try:
            results.append(queue.get(timeout=45))
        except Empty as exc:  # pragma: no cover - defensive timeout with diagnostics.
            raise AssertionError("un proceso no publicó resultado") from exc
    for process in processes:
        process.join(timeout=45)
        assert process.exitcode == 0
    return results


def test_pid_reuse_with_different_token_recovers_owner(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    current_pid = os.getpid()
    store.set_runtime_value(
        coordination.ACTIVE_KEY,
        {
            "status": "active",
            "session_date": "2026-07-15",
            "run_id": "old-owner",
            "owner_pid": current_pid,
            "owner_token": f"pid:{current_pid}:process:old",
            "started_at": "2026-07-15T20:00:00+00:00",
        },
    )
    monkeypatch.setattr(coordination, "_pid_alive", lambda _pid: True)

    lease = PostmarketCoordinator(settings, store).acquire(
        session_date="2026-07-15", run_id="new-owner", trigger="scheduled"
    )

    assert lease.effective is True
    assert lease.reason == "owner_token_mismatch_recovered"
    PostmarketCoordinator(settings, store).terminal(lease, "failed", reason="test_cleanup")


def test_last_session_marker_is_monotonic_and_failed_run_can_retry(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.set_runtime_value("post_market_review_last_session", "2026-07-16")

    coordinator = PostmarketCoordinator(settings, store)
    older = coordinator.acquire(
        session_date="2026-07-15", run_id="older-session", trigger="scheduled"
    )
    assert older.effective is False
    assert older.reason == "session_behind_latest"
    assert store.get_runtime_value("post_market_review_last_session") == "2026-07-16"

    # Un intento fallido de la sesión vigente puede reintentarse y solo el
    # terminal completed permite avanzar el marcador.
    store.set_runtime_value("post_market_review_last_session", None)
    first = coordinator.acquire(
        session_date="2026-07-15", run_id="failed-attempt", trigger="scheduled"
    )
    assert first.effective is True
    coordinator.terminal(first, "failed", reason="synthetic_failure")
    retry = coordinator.acquire(
        session_date="2026-07-15", run_id="retry-attempt", trigger="scheduled"
    )
    assert retry.effective is True
    coordinator.terminal(retry, "completed", reason="synthetic_success")
    assert coordinator.advance_last_session("2026-07-15") is True
    assert store.get_runtime_value("post_market_review_last_session") == "2026-07-15"


def test_scheduler_max_instances_and_missed_events_are_durable_and_idempotent(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    scheduled = datetime(2026, 7, 15, 22, 0, tzinfo=timezone.utc)
    max_event = JobSubmissionEvent(EVENT_JOB_MAX_INSTANCES, "post_market_review", "default", [scheduled])
    missed_event = JobExecutionEvent(EVENT_JOB_MISSED, "post_market_review", "default", scheduled)

    scheduler._persist_scheduler_control_event(settings, store, max_event)
    scheduler._persist_scheduler_control_event(settings, store, max_event)
    scheduler._persist_scheduler_control_event(settings, store, missed_event)
    scheduler._persist_scheduler_control_event(settings, store, missed_event)

    with store.connect() as conn:
        rows = conn.execute(
            "SELECT event_id, payload_json FROM agent_events WHERE event_type = 'scheduler_job_skipped' ORDER BY event_id"
        ).fetchall()
    payloads = [json.loads(row["payload_json"]) for row in rows]
    assert len(payloads) == 2
    assert {item["reason"] for item in payloads} == {"max_instances", "missed"}
    assert all(item["status"] == "skipped" for item in payloads)

    built = scheduler.build_scheduler(settings, store, use_crew=False, verbose=False)
    assert any(mask & (EVENT_JOB_MAX_INSTANCES | EVENT_JOB_MISSED) for _, mask in built._listeners)


def test_scheduler_control_telemetry_is_fail_open(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    event = JobExecutionEvent(
        EVENT_JOB_MISSED,
        "post_market_review",
        "default",
        datetime(2026, 7, 15, 22, 0, tzinfo=timezone.utc),
    )

    def fail(*_args, **_kwargs):
        raise RuntimeError("telemetry store unavailable")

    monkeypatch.setattr(store, "record_append_only_event", fail)
    monkeypatch.setattr(scheduler, "log_system_event", fail)
    scheduler._persist_scheduler_control_event(settings, store, event)


def test_multiprocess_append_only_event_has_one_canonical_without_lock(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    Store(settings.database_path, settings.agent_logs_dir).ensure_schema()
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(25)
    queue = ctx.Queue()
    processes = [
        ctx.Process(
            target=_process_event_writer,
            args=(str(settings.database_path), str(settings.agent_logs_dir), barrier, queue),
        )
        for _ in range(25)
    ]
    for process in processes:
        process.start()
    results = _collect_process_results(processes, queue, 25)

    assert all(item[0] == "ok" for item in results)
    assert sorted(item[1] for item in results).count("inserted") == 1
    with Store(settings.database_path, settings.agent_logs_dir).connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM agent_events WHERE event_id = 'pmr:process-race'"
        ).fetchone()[0] == 1


def test_multiprocess_lease_has_one_owner_and_no_lock(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    Store(settings.database_path, settings.agent_logs_dir).ensure_schema()
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(25)
    release = ctx.Event()
    queue = ctx.Queue()
    processes = [
        ctx.Process(
            target=_process_lease_writer,
            args=(str(settings.database_path), str(settings.agent_logs_dir), barrier, release, queue, f"pmr-{idx}"),
        )
        for idx in range(25)
    ]
    for process in processes:
        process.start()
    results = []
    for _ in range(25):
        try:
            results.append(queue.get(timeout=45))
        except Empty as exc:  # pragma: no cover - defensive timeout with diagnostics.
            raise AssertionError("un propietario no publicó resultado") from exc
    release.set()
    for process in processes:
        process.join(timeout=45)
        assert process.exitcode == 0

    assert all(item[0] == "ok" for item in results)
    assert sum(bool(item[2]) for item in results) == 1
    assert all(item[3] in {None, "postmarket_already_running"} for item in results)


def test_multiprocess_distinct_sessions_have_one_global_owner(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    Store(settings.database_path, settings.agent_logs_dir).ensure_schema()
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(2)
    queue = ctx.Queue()
    processes = [
        ctx.Process(
            target=_process_distinct_session_writer,
            args=(str(settings.database_path), str(settings.agent_logs_dir), barrier, queue, "pmr-old", "2026-07-15"),
        ),
        ctx.Process(
            target=_process_distinct_session_writer,
            args=(str(settings.database_path), str(settings.agent_logs_dir), barrier, queue, "pmr-new", "2026-07-16"),
        ),
    ]
    for process in processes:
        process.start()
    results = _collect_process_results(processes, queue, 2)

    assert all(item[0] == "ok" for item in results)
    assert sum(bool(item[2]) for item in results) == 1
    assert all(item[3] == "postmarket_already_running" for item in results if not item[2])
