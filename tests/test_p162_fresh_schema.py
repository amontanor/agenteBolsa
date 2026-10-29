"""P-L162: ``Store.ensure_schema`` must build a usable database from scratch.

The schema script created ``idx_ci_cycles_created`` before
``continuous_improvement_cycles`` existed, so every fresh database raised
``sqlite3.OperationalError: no such table: main.continuous_improvement_cycles``
and 858 suite identifiers failed on the same line. The index now ships next to
its table; this test freezes creation, idempotency and the index itself.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        DATA_DIR=tmp_path / "data",
        DATABASE_PATH=tmp_path / "data" / "state" / "fresh.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "data" / "logs" / "agents",
        TRADING_MODE="paper",
        ALLOW_LIVE_TRADING=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )


def test_fresh_database_is_created_with_the_cycles_index(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)

    store.ensure_schema()
    store.ensure_schema()

    with sqlite3.connect(settings.database_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        indexes = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
        }
    assert "continuous_improvement_cycles" in tables
    assert "agent_events" in tables
    assert "idx_ci_cycles_created" in indexes


def test_ensure_schema_keeps_existing_events(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.set_runtime_value("p162_probe", "kept")

    store.ensure_schema()

    assert store.get_runtime_value("p162_probe") == "kept"
