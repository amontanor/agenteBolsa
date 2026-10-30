"""P-L180: el panel aplica el esquema una vez por proceso y base.

Solo cambia cuando se ejecuta `ensure_schema` (escritura); el contrato de
esquema, las migraciones y el scheduler no cambian.
"""

from __future__ import annotations


def _settings(tmp_path):
    from agente_bolsa.config import Settings

    settings = Settings(DATA_DIR=tmp_path)
    settings.ensure_runtime_dirs()
    return settings


def _store(settings):
    from agente_bolsa.storage import Store

    return Store(settings.database_path, settings.agent_logs_dir)


def test_ensure_schema_once_runs_once_per_path(tmp_path, monkeypatch):
    from agente_bolsa.storage import Store

    calls = {"n": 0}
    original = Store.ensure_schema

    def counting(self):
        calls["n"] += 1
        return original(self)

    monkeypatch.setattr(Store, "ensure_schema", counting)

    settings = _settings(tmp_path)
    store = _store(settings)
    store.ensure_schema_once()
    store.ensure_schema_once()
    assert calls["n"] == 1

    same_path = _store(settings)
    same_path.ensure_schema_once()
    assert calls["n"] == 1

    other = _store(_settings(tmp_path / "otra_base"))
    other.ensure_schema_once()
    assert calls["n"] == 2


def test_ensure_schema_once_leaves_a_real_schema(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    store.ensure_schema_once()

    with store.connect() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert {"agent_events", "trade_recommendations", "learning_observations"} <= tables
    assert "idx_agent_events_created" in indexes


def test_ensure_schema_remains_available_for_the_scheduler(tmp_path, monkeypatch):
    from agente_bolsa.storage import Store

    calls = {"n": 0}
    original = Store.ensure_schema

    def counting(self):
        calls["n"] += 1
        return original(self)

    monkeypatch.setattr(Store, "ensure_schema", counting)

    store = _store(_settings(tmp_path))
    store.ensure_schema()
    store.ensure_schema()
    assert calls["n"] == 2
