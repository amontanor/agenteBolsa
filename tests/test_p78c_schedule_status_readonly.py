from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.main import build_parser, command_schedule_status
from agente_bolsa.scheduler import _job_state_key, scheduler_status
from agente_bolsa.storage import Store


def _settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, DATA_DIR=tmp_path, MARKET_CALENDAR="XNYS", LOCAL_TIMEZONE="Europe/Madrid")


def _disk_snapshot(database_path: Path) -> dict[str, object]:
    files: dict[str, object] = {}
    for path in (database_path, Path(f"{database_path}-wal"), Path(f"{database_path}-shm")):
        if not path.exists():
            files[path.name] = None
            continue
        data = path.read_bytes()
        stat = path.stat()
        files[path.name] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }

    sidecar_present = Path(f"{database_path}-wal").exists() or Path(f"{database_path}-shm").exists()
    database_header = database_path.read_bytes()[:20] if database_path.exists() else b""
    wal_mode = len(database_header) >= 19 and database_header[18] == 2
    if database_path.exists() and not sidecar_present and not wal_mode:
        uri = database_path.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            connection.execute("PRAGMA query_only=ON")
            schema = connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
            ).fetchall()
            files["schema_version"] = connection.execute("PRAGMA schema_version").fetchone()[0]
            files["schema"] = [tuple(row) for row in schema]
    return files


def test_missing_data_dir_is_read_only_and_reports_unavailable(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "missing")

    status = scheduler_status(settings)

    assert status["runtime_state"] == {
        "available": False,
        "reason": "database_missing",
        "source": "sqlite_read_only",
    }
    assert all(value is None for value in status["job_runtime"].values())
    assert not (tmp_path / "missing").exists()


def test_cli_missing_data_dir_does_not_create_logging_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path / "missing")
    captured: list[dict[str, object]] = []
    monkeypatch.setattr("agente_bolsa.main._get_schedule_status_settings", lambda: settings)
    monkeypatch.setattr("agente_bolsa.main._print_json", captured.append)

    command_schedule_status(type("Args", (), {"json": True})())

    assert captured[0]["runtime_state"]["reason"] == "database_missing"
    assert not settings.data_dir.exists()


def test_existing_database_uses_read_only_runtime_and_preserves_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    settings.database_path.parent.mkdir(parents=True)
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            "CREATE TABLE runtime_state (key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT)"
        )
        connection.execute(
            "INSERT INTO runtime_state(key, value_json, updated_at) VALUES (?, ?, ?)",
            (
                _job_state_key("market_cycle"),
                json.dumps(
                    {
                        "job": "market_cycle",
                        "status": "completed",
                        "run_id": "p78c-test",
                        "detail": "ok",
                    }
                ),
                "2026-08-01T00:00:00+00:00",
            ),
        )
    before = _disk_snapshot(settings.database_path)

    def fail_if_called(_self: Store) -> None:
        raise AssertionError("schedule_status must not call ensure_schema")

    monkeypatch.setattr(Store, "ensure_schema", fail_if_called)
    status = scheduler_status(settings)
    after = _disk_snapshot(settings.database_path)

    assert status["runtime_state"] == {
        "available": True,
        "reason": None,
        "source": "sqlite_read_only",
    }
    assert status["job_runtime"]["market_cycle"]["run_id"] == "p78c-test"
    assert before == after


def test_wal_backed_database_is_unavailable_without_touching_sidecars(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.database_path.parent.mkdir(parents=True)
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            "CREATE TABLE runtime_state (key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT)"
        )
    before = _disk_snapshot(settings.database_path)

    status = scheduler_status(settings)
    after = _disk_snapshot(settings.database_path)

    assert status["runtime_state"] == {
        "available": False,
        "reason": "wal_mode_or_sidecar_present",
        "source": "sqlite_read_only",
    }
    assert before == after


def test_legacy_schema_is_unavailable_without_migration(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.database_path.parent.mkdir(parents=True)
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute("CREATE TABLE legacy_runtime (value TEXT)")
    before = _disk_snapshot(settings.database_path)

    status = scheduler_status(settings)
    after = _disk_snapshot(settings.database_path)

    assert status["runtime_state"] == {
        "available": False,
        "reason": "schema_incompatible",
        "source": "sqlite_read_only",
    }
    assert before == after
    assert all(value is None for value in status["job_runtime"].values())


def test_partial_runtime_schema_is_unavailable_without_alter(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.database_path.parent.mkdir(parents=True)
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute("CREATE TABLE runtime_state (key TEXT PRIMARY KEY)")
    before = _disk_snapshot(settings.database_path)

    status = scheduler_status(settings)
    after = _disk_snapshot(settings.database_path)

    assert status["runtime_state"]["available"] is False
    assert status["runtime_state"]["reason"] == "schema_incompatible"
    assert before == after


def test_readonly_open_error_is_stable_and_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path)
    settings.database_path.parent.mkdir(parents=True)
    settings.database_path.touch()

    def fail_open(_self: Store):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(Store, "read_connection", fail_open)
    status = scheduler_status(settings)

    assert status["runtime_state"] == {
        "available": False,
        "reason": "access_denied",
        "source": "sqlite_read_only",
    }
    assert all(value is None for value in status["job_runtime"].values())


def test_scheduler_status_closes_read_connection_on_unexpected_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    closed: list[bool] = []
    original_close = Store.close_read_connection

    def tracking_close(self: Store) -> None:
        closed.append(True)
        original_close(self)

    def explode(_self: Store, _keys: list[str]):
        raise RuntimeError("test failure")

    monkeypatch.setattr(Store, "close_read_connection", tracking_close)
    monkeypatch.setattr(Store, "read_runtime_values", explode)

    with pytest.raises(RuntimeError, match="test failure"):
        scheduler_status(settings)

    assert closed == [True]


def test_schedule_status_accepts_json_flag_without_changing_default_contract() -> None:
    parser = build_parser()

    args = parser.parse_args(["schedule-status", "--json"])

    assert args.json is True
    assert args.func.__name__ == "command_schedule_status"


def test_schedule_status_preserves_calendar_and_job_contract(tmp_path: Path) -> None:
    status = scheduler_status(_settings(tmp_path))

    assert status["market"]["calendar"] == "XNYS"
    assert status["market"]["is_open"] is False
    assert {job["id"] for job in status["jobs"]} >= {
        "portfolio_watch_1m",
        "market_cycle_15m",
        "broker_reconciliation",
        "agents_healthcheck",
    }
    assert set(status["job_runtime"]) >= {
        "portfolio_watch",
        "market_cycle",
        "broker_reconciliation",
        "agents_healthcheck",
    }
