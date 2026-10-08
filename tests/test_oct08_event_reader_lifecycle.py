import json
import sqlite3
from contextlib import closing

import pytest

from agente_bolsa.storage import Store


@pytest.fixture
def reader(tmp_path, monkeypatch):
    store = Store(tmp_path / "events.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    with closing(store.connect()) as conn, conn:
        for event_id, cycle, stamp, payload in (
            ("b", "cycle-1", "2026-10-07T20:00:00+00:00", '{"agent_run_id":"agent-1"}'),
            ("a", "cycle-1", "2026-10-07T20:00:00+00:00", '{"agent_run_id":"agent-1"}'),
            ("c", "cycle-2", "2026-10-07T21:00:00+00:00", "{}"),
        ):
            conn.execute(
                "INSERT INTO agent_events VALUES (?, ?, ?, ?, ?, ?)",
                (event_id, "test", "capture_prediction", cycle, payload, stamp),
            )
    connect = store.connect
    opened = []

    def tracked_connect(**kwargs):
        conn = connect(**kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(store, "connect", tracked_connect)
    return store, opened


def assert_closed(opened):
    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")


def test_exhaustion_closes_reader_preserving_order_and_payload(reader):
    store, opened = reader
    events = list(store.iter_agent_events(limit=None, batch_size=1))
    assert [event["event_id"] for event in events] == ["a", "b", "c"]
    assert events[0] == {
        "event_id": "a", "agent": "test", "event_type": "capture_prediction",
        "cycle_id": "cycle-1", "payload": {"agent_run_id": "agent-1"},
        "created_at": "2026-10-07T20:00:00+00:00",
    }
    assert_closed(opened)


def test_early_generator_close_releases_connection(reader):
    store, opened = reader
    iterator = store.iter_agent_events(limit=None, batch_size=1)
    assert next(iterator)["event_id"] == "a"
    iterator.close()
    assert_closed(opened)


def test_decode_failure_closes_connection(reader):
    store, opened = reader
    with closing(store.connect()) as conn, conn:
        conn.execute("UPDATE agent_events SET payload_json='invalid' WHERE event_id='a'")
    opened.clear()
    with pytest.raises(json.JSONDecodeError):
        list(store.iter_agent_events(limit=None))
    assert_closed(opened)


def test_empty_selection_closes_connection(reader):
    store, opened = reader
    assert list(store.iter_agent_events(cycle_id="absent")) == []
    assert_closed(opened)


def test_filters_limits_and_batch_size_preserved(reader):
    store, opened = reader
    result = list(store.iter_agent_events(
        event_type_prefix="capture_", cycle_id="cycle-1", agent_run_id="agent-1",
        limit=1, batch_size=2,
    ))
    assert [event["event_id"] for event in result] == ["a"]
    assert_closed(opened)


def test_sql_failure_closes_connection(reader, monkeypatch):
    store, opened = reader
    with closing(store.connect()) as conn, conn:
        conn.execute("DROP TABLE agent_events")
    opened.clear()
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        list(store.iter_agent_events())
    assert_closed(opened)
