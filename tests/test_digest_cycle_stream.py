from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import pytest

from agente_bolsa.continuous_improvement.digest import build_research_mode_usage
from agente_bolsa.storage import Store


def test_cycle_stream_matches_legacy_rows_order_limit_and_payload(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    for i in range(25):
        store.create_continuous_improvement_cycle({
            "cycle_id": f"cycle-{i}", "trace_id": "trace", "job_id": "job",
            "status": "COMPLETED", "mode": "research" if i % 2 else "active",
            "dry_run": True, "started_at": "2026-10-11T12:00:00+00:00",
            "context": {"padding": "X" * 10000},
        })
    assert list(store.iter_continuous_improvement_cycles(limit=17)) == store.continuous_improvement_cycles(limit=17)

    class Legacy:
        continuous_improvement_cycles = store.continuous_improvement_cycles
        connect = store.connect

    now = datetime(2026, 10, 11, 14, tzinfo=timezone.utc)
    assert build_research_mode_usage(store, now=now) == build_research_mode_usage(Legacy(), now=now)


def test_cycle_stream_closes_reader_on_decode_error_and_early_close(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.create_continuous_improvement_cycle({"cycle_id": "broken", "trace_id": "trace", "job_id": "job", "mode": "active"})
    with store.connect() as conn:
        conn.execute("UPDATE continuous_improvement_cycles SET context_json = '{bad'")
    real = store._decision_context_read_connection
    connections = []

    def reader():
        conn = real()
        connections.append(conn)
        return conn

    monkeypatch.setattr(store, "_decision_context_read_connection", reader)
    with pytest.raises(json.JSONDecodeError):
        list(store.iter_continuous_improvement_cycles())
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connections[-1].execute("SELECT 1")
    with store.connect() as conn:
        conn.execute("UPDATE continuous_improvement_cycles SET context_json = '{}'")
    iterator = store.iter_continuous_improvement_cycles()
    next(iterator)
    iterator.close()
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connections[-1].execute("SELECT 1")

