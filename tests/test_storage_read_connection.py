import sqlite3
import threading

import pytest

from agente_bolsa.storage import Store


def _store(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    return store


def test_read_connection_is_reused_per_thread_and_read_only(tmp_path):
    store = _store(tmp_path)

    first = store.read_connection()
    second = store.read_connection()

    assert first is second
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        first.execute("INSERT INTO signal_outcomes (signal_id) VALUES ('forbidden')")


def test_read_connection_uses_a_distinct_connection_per_thread(tmp_path):
    store = _store(tmp_path)
    main_connection = store.read_connection()
    worker_connection_ids: list[int] = []

    def read_from_worker() -> None:
        worker_connection_ids.append(id(store.read_connection()))
        store.close_read_connection()

    worker = threading.Thread(target=read_from_worker)
    worker.start()
    worker.join()

    assert worker_connection_ids != [id(main_connection)]


def test_signal_outcomes_reader_sees_committed_writes(tmp_path):
    store = _store(tmp_path)
    assert store.signal_outcomes() == []

    store.save_signal_outcome(
        signal_id="run-1:AAPL",
        source_run_id="run-1",
        source="test",
        symbol="AAPL",
        signal_date="2026-06-20",
        decision="candidate",
        features={"setup_quality": "strong"},
    )

    assert store.signal_outcomes()[0]["signal_id"] == "run-1:AAPL"


def test_signal_outcomes_recent_query_uses_covering_order_index(tmp_path):
    store = _store(tmp_path)

    plan = store.read_connection().execute(
        """
        EXPLAIN QUERY PLAN
        SELECT signal_id, source_run_id, source, symbol, signal_date,
               decision, features_json, gate_json, outcome_json,
               created_at, updated_at
        FROM signal_outcomes
        ORDER BY signal_date DESC, created_at DESC
        LIMIT 500
        """
    ).fetchall()

    assert any("idx_signal_outcomes_recent" in str(row[3]) for row in plan)
