"""P-L182: el panel no reescribe el esquema ni muere si SQLite esta bloqueada."""

from __future__ import annotations

from agente_bolsa.web_app import _safe_db_status


def _settings(tmp_path):
    from agente_bolsa.config import Settings

    settings = Settings(DATA_DIR=tmp_path)
    settings.ensure_runtime_dirs()
    return settings


def _store(settings):
    from agente_bolsa.storage import Store

    return Store(settings.database_path, settings.agent_logs_dir)


def test_status_keeps_introspection_without_rewriting_schema(tmp_path, monkeypatch):
    from agente_bolsa.storage import Store

    calls = {"n": 0}
    original = Store.ensure_schema

    def counting(self):
        calls["n"] += 1
        return original(self)

    monkeypatch.setattr(Store, "ensure_schema", counting)

    store = _store(_settings(tmp_path))
    first = store.status()
    second = store.status()

    assert "agent_events" in first["tables"]
    assert second["tables"]["agent_events"] >= 0
    assert calls["n"] == 1


def test_status_survives_when_schema_is_already_ready(tmp_path, monkeypatch):
    from agente_bolsa.storage import Store

    store = _store(_settings(tmp_path))
    store.status()

    def boom(self):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(Store, "ensure_schema", boom)

    assert "agent_events" in store.status()["tables"]


class _LockedStore:
    def status(self):
        raise RuntimeError("database is locked")


class _HealthyStore:
    def status(self):
        return {"tables": {"broker_orders": 7}}


def test_safe_db_status_degrades_without_raising():
    status = _safe_db_status(_LockedStore())

    assert status["available"] is False
    assert status["tables"] == {}
    assert "database is locked" in status["error"]
    assert status["tables"].get("broker_orders", 0) == 0


def test_safe_db_status_passes_through_when_available():
    status = _safe_db_status(_HealthyStore())

    assert status == {"tables": {"broker_orders": 7}, "available": True}
