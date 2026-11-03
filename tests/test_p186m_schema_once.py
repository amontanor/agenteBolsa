"""P-L186M: schema bootstrap must not run on every hot-path call."""

from __future__ import annotations

import inspect

from agente_bolsa import cycle_runner, llm_usage
from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement import orchestrator, runtime
from agente_bolsa.storage import Store
from agente_bolsa.tools import learning_scoreboard, live_readiness, trade_decision


def _store(tmp_path):
    settings = Settings(DATA_DIR=tmp_path, _env_file=None)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def test_ensure_schema_seeds_once_marker(tmp_path, monkeypatch):
    store = _store(tmp_path)

    def fail():
        raise AssertionError("ensure_schema rerun on an already-ready database")

    monkeypatch.setattr(store, "ensure_schema", fail)
    store.ensure_schema_once()


def test_ensure_schema_once_runs_only_once_per_path(tmp_path, monkeypatch):
    settings = Settings(DATA_DIR=tmp_path, _env_file=None)
    store = Store(settings.database_path, settings.agent_logs_dir)
    calls = {"count": 0}

    def fake():
        calls["count"] += 1

    monkeypatch.setattr(store, "ensure_schema", fake)
    store.ensure_schema_once()
    store.ensure_schema_once()
    assert calls["count"] == 1


def test_hot_paths_use_schema_once():
    modules = (
        llm_usage,
        cycle_runner,
        runtime,
        orchestrator,
        trade_decision,
        learning_scoreboard,
        live_readiness,
    )
    for module in modules:
        source = inspect.getsource(module)
        assert "ensure_schema_once" in source, module.__name__
        assert ".ensure_schema()" not in source, module.__name__
