from __future__ import annotations

import json
from pathlib import Path

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools import postmarket_coordination as coordination
from agente_bolsa.tools.postmarket_coordination import (
    ACTIVE_KEY,
    RECONCILIATION_KEY,
    SESSION_KEY_PREFIX,
    CoordinationLease,
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


def _dead_state(*, session_date: str, run_id: str) -> dict[str, object]:
    return {
        "status": "active",
        "session_date": session_date,
        "run_id": run_id,
        "trigger": "scheduled",
        "owner_pid": 999999,
        "owner_token": "dead-token",
        "owner_process_token": "dead-token",
        "started_at": f"{session_date}T20:00:00+00:00",
    }


def _events(store: Store, event_type: str | None = None) -> list[dict[str, object]]:
    with store.connect() as conn:
        if event_type is None:
            rows = conn.execute(
                "SELECT event_id, event_type, payload_json FROM agent_events ORDER BY created_at"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT event_id, event_type, payload_json FROM agent_events "
                "WHERE event_type = ? ORDER BY created_at",
                (event_type,),
            ).fetchall()
    return [
        {
            "event_id": row["event_id"],
            "event_type": row["event_type"],
            "payload": json.loads(row["payload_json"]),
        }
        for row in rows
    ]


def test_postmarket_recovery_keeps_original_identity_and_releases_old_view(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    old_session = "2026-10-07"
    new_session = "2026-10-08"
    old_state = _dead_state(session_date=old_session, run_id="pmr-old")
    store.set_runtime_value(ACTIVE_KEY, old_state)
    store.set_runtime_value(f"{SESSION_KEY_PREFIX}{old_session}", old_state)

    lease = PostmarketCoordinator(settings, store).acquire(
        session_date=new_session, run_id="pmr-new", trigger="bootstrap"
    )

    assert lease.effective is True
    recovered = [
        item
        for item in _events(store)
        if item["event_id"] == "pmr:pmr-old:terminal:failed"
    ]
    assert recovered and recovered[0]["payload"]["session_date"] == old_session
    markers = [
        item
        for item in _events(store)
        if item["event_id"] == "stale_lease_recovered:pmr-old:pmr-new"
    ]
    assert markers and markers[0]["payload"]["session_date"] == old_session
    assert store.get_runtime_value(f"{SESSION_KEY_PREFIX}{old_session}") is None
    assert store.get_runtime_value(ACTIVE_KEY)["run_id"] == "pmr-new"


def test_reconciliation_recovery_keeps_terminal_event_append_only(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    old_session = "2026-10-07"
    new_session = "2026-10-08"
    old_state = _dead_state(session_date=old_session, run_id="pmr-old")
    store.set_runtime_value(ACTIVE_KEY, old_state)
    store.set_runtime_value(f"{SESSION_KEY_PREFIX}{old_session}", old_state)
    terminal_payload = {
        "schema_version": "p-l45b1.postmarket-run.v1",
        "session_date": old_session,
        "run_id": "pmr-old",
        "stage": "terminal",
        "status": "failed",
        "content_hash": "old-terminal-hash",
    }
    store.record_append_only_event(
        event_id="pmr:pmr-old:terminal:failed",
        event_type="postmarket_run",
        cycle_id="pmr-old",
        payload=terminal_payload,
    )

    lease = PostmarketCoordinator(settings, store).acquire_reconciliation(
        session_date=new_session, run_id="recon-new", trigger="scheduled"
    )

    assert lease.effective is True
    recovered = [
        item
        for item in _events(store)
        if item["event_id"] == "pmr:pmr-old:terminal:failed"
    ]
    assert len(recovered) == 1
    assert recovered[0]["payload"] == terminal_payload
    markers = [
        item
        for item in _events(store)
        if item["event_id"] == "terminal_lease_recovered:pmr-old:recon-new"
    ]
    assert markers and markers[0]["payload"]["session_date"] == old_session
    assert store.get_runtime_value(f"{SESSION_KEY_PREFIX}{old_session}") is None


def test_reconciliation_stale_recovery_keeps_original_session_identity(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    old_session = "2026-10-07"
    new_session = "2026-10-08"
    old_state = _dead_state(session_date=old_session, run_id="recon-old")
    store.set_runtime_value(RECONCILIATION_KEY, old_state)
    store.set_runtime_value(f"{SESSION_KEY_PREFIX}{old_session}", old_state)

    lease = PostmarketCoordinator(settings, store).acquire_reconciliation(
        session_date=new_session, run_id="recon-new", trigger="scheduled"
    )

    assert lease.effective is True
    recovered = [
        item
        for item in _events(store)
        if item["event_id"] == "recon:recon-old:terminal:failed"
    ]
    assert recovered and recovered[0]["payload"]["session_date"] == old_session
    markers = [
        item
        for item in _events(store)
        if item["event_id"] == "stale_lease_recovered:recon-old:recon-new"
    ]
    assert markers and markers[0]["payload"]["session_date"] == old_session
    assert store.get_runtime_value(f"{SESSION_KEY_PREFIX}{old_session}") is None


def test_recovery_does_not_remove_mismatched_old_session_view(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    old_session = "2026-10-07"
    active_state = _dead_state(session_date=old_session, run_id="pmr-old")
    conflicting_view = _dead_state(session_date=old_session, run_id="other-run")
    store.set_runtime_value(ACTIVE_KEY, active_state)
    store.set_runtime_value(f"{SESSION_KEY_PREFIX}{old_session}", conflicting_view)

    lease = PostmarketCoordinator(settings, store).acquire(
        session_date="2026-10-08", run_id="pmr-new", trigger="scheduled"
    )

    assert lease.effective is True
    assert store.get_runtime_value(f"{SESSION_KEY_PREFIX}{old_session}") == conflicting_view


def test_late_terminal_does_not_overwrite_new_owner_session_view(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    session = "2026-10-08"
    new_state = {
        "status": "active",
        "session_date": session,
        "run_id": "new-owner",
        "owner_pid": 222,
        "owner_process_token": "new-token",
        "owner_token": "new-token",
    }
    store.set_runtime_value(f"{SESSION_KEY_PREFIX}{session}", new_state)
    old_lease = CoordinationLease(
        run_id="old-owner",
        session_date=session,
        trigger="scheduled",
        owner_pid=111,
        owner_token="old-token",
        effective=True,
        status="started",
    )

    PostmarketCoordinator(settings, store).terminal(old_lease, "failed", reason="late")

    assert store.get_runtime_value(f"{SESSION_KEY_PREFIX}{session}") == new_state


def test_live_owner_on_old_session_is_not_recovered_or_released(
    tmp_path: Path, monkeypatch
) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    old_session = "2026-10-07"
    old_state = {
        **_dead_state(session_date=old_session, run_id="pmr-live"),
        "owner_pid": 12345,
        "owner_process_token": "live-token",
        "owner_token": "live-token",
    }
    monkeypatch.setattr(coordination, "_pid_alive", lambda pid: pid == 12345)
    store.set_runtime_value(ACTIVE_KEY, old_state)
    store.set_runtime_value(f"{SESSION_KEY_PREFIX}{old_session}", old_state)
    terminal_payload = {
        "schema_version": "p-l45b1.postmarket-run.v1",
        "session_date": old_session,
        "run_id": "pmr-live",
        "stage": "terminal",
        "status": "failed",
        "content_hash": "live-terminal-hash",
    }
    store.record_append_only_event(
        event_id="pmr:pmr-live:terminal:failed",
        event_type="postmarket_run",
        cycle_id="pmr-live",
        payload=terminal_payload,
    )

    lease = PostmarketCoordinator(settings, store).acquire(
        session_date="2026-10-08", run_id="pmr-new", trigger="scheduled"
    )

    assert lease.effective is False
    assert lease.reason == "postmarket_already_running"
    assert store.get_runtime_value(f"{SESSION_KEY_PREFIX}{old_session}") == old_state
    assert [
        item["payload"]
        for item in _events(store)
        if item["event_id"] == "pmr:pmr-live:terminal:failed"
    ] == [terminal_payload]


def test_missing_recovered_session_is_unavailable_and_old_view_is_preserved(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    old_session = "2026-10-07"
    new_session = "2026-10-08"
    active_state = _dead_state(session_date=old_session, run_id="pmr-missing-session")
    active_state.pop("session_date")
    old_view = _dead_state(session_date=old_session, run_id="pmr-missing-session")
    store.set_runtime_value(ACTIVE_KEY, active_state)
    store.set_runtime_value(f"{SESSION_KEY_PREFIX}{old_session}", old_view)

    lease = PostmarketCoordinator(settings, store).acquire(
        session_date=new_session, run_id="pmr-new", trigger="scheduled"
    )

    assert lease.effective is True
    recovered = [
        item
        for item in _events(store)
        if item["event_id"] == "pmr:pmr-missing-session:terminal:failed"
    ]
    assert recovered and recovered[0]["payload"]["session_date"] == "unavailable"
    markers = [
        item
        for item in _events(store)
        if item["event_id"] == "stale_lease_recovered:pmr-missing-session:pmr-new"
    ]
    assert markers and markers[0]["payload"]["session_date"] == "unavailable"
    assert store.get_runtime_value(f"{SESSION_KEY_PREFIX}{old_session}") == old_view


def test_terminal_of_postmarket_does_not_release_conflicting_reconciliation_lease(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    recon_state = {
        "status": "active",
        "session_date": "2026-10-08",
        "run_id": "recon-owner",
        "owner_pid": 222,
        "owner_process_token": "recon-token",
        "owner_token": "recon-token",
    }
    store.set_runtime_value(RECONCILIATION_KEY, recon_state)
    pmr_lease = CoordinationLease(
        run_id="pmr-owner",
        session_date="2026-10-08",
        trigger="scheduled",
        owner_pid=111,
        owner_token="pmr-token",
        effective=True,
        status="started",
    )

    PostmarketCoordinator(settings, store).terminal(pmr_lease, "failed", reason="late")

    assert store.get_runtime_value(RECONCILIATION_KEY) == recon_state


def test_postmarket_does_not_start_while_live_reconciliation_exists(
    tmp_path: Path, monkeypatch
) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    recon_state = {
        "status": "active",
        "session_date": "2026-10-08",
        "run_id": "recon-owner",
        "owner_pid": 12345,
        "owner_process_token": "recon-token",
        "owner_token": "recon-token",
    }
    monkeypatch.setattr(coordination, "_pid_alive", lambda pid: pid == 12345)
    store.set_runtime_value(RECONCILIATION_KEY, recon_state)

    lease = PostmarketCoordinator(settings, store).acquire(
        session_date="2026-10-08", run_id="pmr-new", trigger="scheduled"
    )

    assert lease.effective is False
    assert lease.reason == "reconciliation_already_running"
    assert store.get_runtime_value(RECONCILIATION_KEY) == recon_state
    assert store.get_runtime_value(ACTIVE_KEY) is None


def test_reconciliation_does_not_overwrite_live_reconciliation_after_terminal_pmr(
    tmp_path: Path, monkeypatch
) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    pmr_state = _dead_state(session_date="2026-10-07", run_id="pmr-terminal")
    recon_state = {
        "status": "active",
        "session_date": "2026-10-08",
        "run_id": "recon-owner",
        "owner_pid": 12345,
        "owner_process_token": "recon-token",
        "owner_token": "recon-token",
    }
    monkeypatch.setattr(coordination, "_pid_alive", lambda pid: pid == 12345)
    store.set_runtime_value(ACTIVE_KEY, pmr_state)
    store.set_runtime_value(RECONCILIATION_KEY, recon_state)
    store.record_append_only_event(
        event_id="pmr:pmr-terminal:terminal:failed",
        event_type="postmarket_run",
        cycle_id="pmr-terminal",
        payload={
            "schema_version": "p-l45b1.postmarket-run.v1",
            "session_date": "2026-10-07",
            "run_id": "pmr-terminal",
            "stage": "terminal",
            "status": "failed",
            "content_hash": "pmr-terminal-hash",
        },
    )

    lease = PostmarketCoordinator(settings, store).acquire_reconciliation(
        session_date="2026-10-08", run_id="recon-new", trigger="scheduled"
    )

    assert lease.effective is False
    assert lease.reason == "reconciliation_already_running"
    assert store.get_runtime_value(RECONCILIATION_KEY) == recon_state
    assert store.get_runtime_value(ACTIVE_KEY) == pmr_state
