from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

import agente_bolsa.storage as storage_module
from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.decision_context import (
    _contains_prohibited,
    _parse_utc,
    _snapshot_from_record,
    build_decision_context_quality,
)

NOW = datetime(2026, 7, 12, 12, tzinfo=timezone.utc)


def _store(tmp_path):
    settings = Settings(
        _env_file=None,
        DATA_DIR=tmp_path,
        DATABASE_PATH=tmp_path / "state" / "test.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "logs",
    )
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def _snapshot(
    snapshot_id: str,
    content_hash: str,
    *,
    signal_link_status: str = "verified",
    decision_source: str = "llm",
    fallback_reason: str | None = None,
    agent_run_id: str | None = None,
    prohibited: bool = False,
) -> dict:
    result = {
        "snapshot_id": snapshot_id,
        "content_hash": content_hash,
        "cycle_id": "cycle-fixed",
        "signal_link_status": signal_link_status,
        "decision_source": decision_source,
        "fallback_reason": fallback_reason,
        "agent_run_id": agent_run_id,
        "market_state_ref": {"status": "available", "cycle_id": "cycle-fixed"},
    }
    if prohibited:
        result["return_1d"] = 0.1
    return result


def _fixture_store(tmp_path):
    store = _store(tmp_path)
    shared = _snapshot("shared", "hash-1", agent_run_id="agent-1")
    records = {
        "r_verified": (_snapshot("rec-verified", "hash-r1"), "2026-07-12T11:59:00+00:00"),
        "r_broken": (_snapshot("rec-broken", "hash-r2", signal_link_status="broken"), "2026-07-12T11:58:00+00:00"),
        "r_unavailable": (
            _snapshot("rec-fallback", "hash-r3", signal_link_status="unavailable", decision_source="fallback", fallback_reason="quota exceeded"),
            "2026-07-12T11:57:00+00:00",
        ),
        "r_missing": (None, "2026-07-12T11:56:00+00:00"),
        "r_cutoff": (_snapshot("shared", "hash-1"), "2026-07-11T12:00:00+00:00"),
        "r_future_naive": (_snapshot("shared", "hash-9"), "2026-07-13T00:00:00"),
        "r_stale": (_snapshot("stale", "hash-stale"), "2026-07-10T23:59:00+00:00"),
        "r_invalid": (_snapshot("invalid", "hash-invalid"), "not-a-timestamp"),
    }
    for recommendation_id, (snapshot, _) in records.items():
        store.save_trade_recommendation(
            recommendation_id=recommendation_id,
            cycle_id="cycle-fixed",
            symbol="AAPL",
            action="buy",
            confidence=0.7,
            payload={"decision_context_snapshot": snapshot} if snapshot else {},
        )
    with store.connect() as conn:
        for recommendation_id, (_, created_at) in records.items():
            conn.execute(
                "UPDATE trade_recommendations SET created_at = ? WHERE recommendation_id = ?",
                (created_at, recommendation_id),
            )

    plans = [
        ("plan_shared", shared, "2026-07-12T11:55:00+00:00"),
        ("plan_missing", None, "2026-07-12T11:54:00+00:00"),
        ("plan_stale", _snapshot("plan-stale", "hash-stale"), "2026-07-10T11:54:00+00:00"),
    ]
    for plan_id, snapshot, _ in plans:
        store.save_order_plan(
            plan_id=plan_id,
            cycle_id="cycle-fixed",
            symbol="AAPL",
            side="buy",
            notional=100.0,
            approved=True,
            dry_run=True,
            payload={"decision_context_snapshot": snapshot} if snapshot else {},
        )
    with store.connect() as conn:
        for plan_id, _, created_at in plans:
            conn.execute(
                "UPDATE order_plans SET created_at = ?, status_updated_at = ? WHERE plan_id = ?",
                (created_at, created_at, plan_id),
            )

    observations = [
        ("obs_shared", shared, "2026-07-12T11:53:00+00:00"),
        ("obs_contaminated", _snapshot("obs-contaminated", "hash-o1", prohibited=True), "2026-07-12T11:52:00+00:00"),
        ("obs_invalid", _snapshot("obs-invalid", "hash-o2"), "not-a-timestamp"),
    ]
    for observation_id, snapshot, created_at in observations:
        store.upsert_learning_observation(
            {
                "observation_id": observation_id,
                "signal_date": "2026-07-12",
                "symbol": "AAPL",
                "source_family": f"fixed-{observation_id}",
                "features": {"decision_context_snapshot": snapshot} if snapshot else {},
                "created_at": created_at,
            }
        )

    outcomes = [
        ("out_shared", shared, "2026-07-12T11:51:00+00:00"),
        ("out_contaminated", _snapshot("out-contaminated", "hash-out", prohibited=True), "2026-07-12T11:50:00+00:00"),
        ("out_stale", _snapshot("out-stale", "hash-stale"), "2026-07-10T11:50:00+00:00"),
    ]
    for signal_id, snapshot, _created_at in outcomes:
        store.save_signal_outcome(
            signal_id=signal_id,
            source_run_id="source-fixed",
            source="fixed",
            symbol="AAPL",
            signal_date="2026-07-12",
            decision="candidate",
            features={"decision_context_snapshot": snapshot} if snapshot else {},
            gate={},
            outcome={},
        )
    with store.connect() as conn:
        for signal_id, _, created_at in outcomes:
            conn.execute(
                "UPDATE signal_outcomes SET created_at = ?, updated_at = ? WHERE signal_id = ?",
                (created_at, created_at, signal_id),
            )
    return store


def _oracle_quality(store, *, now: datetime, days: int = 1) -> dict:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = current.timestamp() - max(1, int(days)) * 86400

    def recent(record):
        try:
            return _parse_utc(record.get("created_at")).timestamp() >= cutoff
        except ValueError:
            return False

    recommendations = [item for item in store.trade_recommendations(limit=50000) if recent(item)]
    plans = [item for item in store.order_plans(limit=50000) if recent(item)]
    observations = [item for item in store.learning_observations(limit=200000) if recent(item)]
    outcomes = [
        item
        for item in store.signal_outcomes(limit=200000, include_lab_book=True, include_learning_experiment=True)
        if recent(item)
    ]
    records = [
        ("recommendation", item, _snapshot_from_record(item)) for item in recommendations
    ] + [("plan", item, _snapshot_from_record(item)) for item in plans]
    records += [("observation", item, _snapshot_from_record(item)) for item in observations]
    records += [("outcome", item, _snapshot_from_record(item)) for item in outcomes]
    rec_snapshots = [snapshot for _, _, snapshot in records[: len(recommendations)] if snapshot]
    snapshots = [snapshot for _, _, snapshot in records if snapshot]
    verified = sum(snapshot.get("signal_link_status") == "verified" for snapshot in rec_snapshots)
    broken = sum(snapshot.get("signal_link_status") == "broken" for snapshot in rec_snapshots)
    unavailable = sum(snapshot.get("signal_link_status") == "unavailable" for snapshot in rec_snapshots)
    same_cycle = sum(
        (snapshot.get("market_state_ref") or {}).get("status") == "unavailable"
        or (snapshot.get("market_state_ref") or {}).get("cycle_id") == snapshot.get("cycle_id")
        for snapshot in snapshots
    )
    source_counts: dict[str, int] = {}
    for snapshot in rec_snapshots:
        source = str(snapshot.get("decision_source") or "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1
    fallback_snapshots = [snapshot for snapshot in rec_snapshots if snapshot.get("decision_source") == "fallback"]
    hashes_by_id: dict[str, set[str]] = {}
    for snapshot in snapshots:
        hashes_by_id.setdefault(str(snapshot.get("snapshot_id")), set()).add(str(snapshot.get("content_hash")))
    conflict_count = sum(len(hashes) > 1 for hashes in hashes_by_id.values())
    contamination = sum(_contains_prohibited(snapshot) is not None for snapshot in snapshots)
    total = len(recommendations)
    captured = len(rec_snapshots)
    return {
        "schema_version": "p-l30b.decision-context.v1",
        "window_days": max(1, int(days)),
        "status": "collecting" if not total or not captured else "evaluable",
        "recommendations_total_new": total,
        "recommendations_with_snapshot": captured,
        "recommendation_snapshot_coverage": captured / total if total else None,
        "verified_signal_links": verified,
        "broken_signal_links": broken,
        "unavailable_signal_links": unavailable,
        "signal_snapshot_coverage_verified_links": verified / total if total else None,
        "plans_with_snapshot": sum(bool(_snapshot_from_record(item)) for item in plans),
        "observations_with_snapshot": sum(bool(_snapshot_from_record(item)) for item in observations),
        "outcomes_with_snapshot": sum(bool(_snapshot_from_record(item)) for item in outcomes),
        "agent_run_link_coverage": sum(bool(snapshot.get("agent_run_id")) for snapshot in snapshots) / len(snapshots)
        if snapshots
        else None,
        "market_state_same_cycle_coverage": same_cycle / len(snapshots) if snapshots else None,
        "decision_source_coverage": sum(snapshot.get("decision_source") != "unknown" for snapshot in rec_snapshots) / total
        if total
        else None,
        "fallback_reason_coverage": sum(bool(snapshot.get("fallback_reason")) for snapshot in fallback_snapshots) / len(fallback_snapshots)
        if fallback_snapshots
        else None,
        "post_decision_contamination_count": contamination,
        "snapshot_conflict_count": conflict_count,
        "sources": source_counts,
        "legacy_without_snapshot": total - captured,
    }


def test_streaming_quality_matches_full_legacy_oracle_on_heterogeneous_fixture(tmp_path):
    store = _fixture_store(tmp_path)

    assert build_decision_context_quality(store, now=NOW, days=1) == _oracle_quality(store, now=NOW, days=1)


def test_decision_source_coverage_preserves_raw_legacy_values(tmp_path):
    store = _fixture_store(tmp_path)
    missing = object()
    variants = {
        "r_source_missing": missing,
        "r_source_none": None,
        "r_source_empty": "",
        "r_source_zero": 0,
        "r_source_false": False,
        "r_source_unknown": "unknown",
        "r_source_list": [],
        "r_source_mapping": {"unexpected": True},
    }
    for recommendation_id, decision_source in variants.items():
        snapshot = _snapshot(f"{recommendation_id}-snapshot", "hash-source")
        if decision_source is not missing:
            snapshot["decision_source"] = decision_source
        else:
            del snapshot["decision_source"]
        payload = {"decision_context_snapshot": snapshot}
        store.save_trade_recommendation(
            recommendation_id=recommendation_id,
            cycle_id="cycle-fixed",
            symbol="AAPL",
            action="buy",
            confidence=0.7,
            payload=payload,
        )
    with store.connect() as conn:
        for recommendation_id in variants:
            conn.execute(
                "UPDATE trade_recommendations SET created_at = ? WHERE recommendation_id = ?",
                ("2026-07-12T11:40:00+00:00", recommendation_id),
            )

    actual = build_decision_context_quality(store, now=NOW, days=1)
    expected = _oracle_quality(store, now=NOW, days=1)
    assert actual == expected
    assert actual["decision_source_coverage"] == 12 / 14

    expected_records = [
        ("recommendation", item) for item in store.trade_recommendations(limit=50000)
    ]
    expected_records += [
        ("plan", item) for item in store.order_plans(limit=50000)
    ]
    expected_records += [
        ("observation", item) for item in store.learning_observations(limit=200000)
    ]
    expected_records += [
        ("outcome", item)
        for item in store.signal_outcomes(
            limit=200000,
            include_lab_book=True,
            include_learning_experiment=True,
        )
    ]
    with store.decision_context_quality_record_stream(batch_size=2) as records:
        assert list(records) == expected_records


def test_stream_records_preserve_payload_order_and_global_limits(tmp_path, monkeypatch):
    store = _fixture_store(tmp_path)
    traces: list[str] = []
    original_open = store._decision_context_read_connection

    def tracked_connection():
        connection = original_open()
        connection.set_trace_callback(traces.append)
        return connection

    monkeypatch.setattr(store, "_decision_context_read_connection", tracked_connection)
    with store.decision_context_quality_record_stream(batch_size=1) as records:
        streamed = list(records)

    expected = [
        ("recommendation", item) for item in store.trade_recommendations(limit=50000)
    ] + [("plan", item) for item in store.order_plans(limit=50000)]
    expected += [("observation", item) for item in store.learning_observations(limit=200000)]
    expected += [
        ("outcome", item)
        for item in store.signal_outcomes(limit=200000, include_lab_book=True, include_learning_experiment=True)
    ]
    assert streamed == expected
    sql = " ".join(traces).upper()
    assert sql.count("LIMIT 50000") == 2
    assert sql.count("LIMIT 200000") == 2


def test_stream_reads_at_most_one_batch_without_fetchall(tmp_path, monkeypatch):
    store = _fixture_store(tmp_path)
    fetch_sizes: list[int] = []
    original_open = store._decision_context_read_connection

    class TrackedCursor:
        def __init__(self, cursor):
            self._cursor = cursor

        def fetchmany(self, size):
            rows = self._cursor.fetchmany(size)
            fetch_sizes.append(len(rows))
            return rows

        def fetchall(self):
            raise AssertionError("stream must use fetchmany")

        def __iter__(self):
            return iter(self._cursor)

        def close(self):
            return self._cursor.close()

    class TrackedConnection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, *args, **kwargs):
            return TrackedCursor(self._connection.execute(*args, **kwargs))

        def close(self):
            return self._connection.close()

    monkeypatch.setattr(
        store,
        "_decision_context_read_connection",
        lambda: TrackedConnection(original_open()),
    )
    count = 0
    with store.decision_context_quality_record_stream(batch_size=1) as records:
        for _kind, _item in records:
            count += 1

    assert count > 0
    assert fetch_sizes
    assert max(fetch_sizes) <= 1


def test_stream_closes_current_cursor_and_connection_when_consumer_aborts(tmp_path, monkeypatch):
    store = _fixture_store(tmp_path)
    closed_connections: list[bool] = []
    closed_cursors: list[bool] = []
    original_open = store._decision_context_read_connection

    class TrackedCursor:
        def __init__(self, cursor):
            self._cursor = cursor

        def fetchmany(self, size):
            return self._cursor.fetchmany(size)

        def close(self):
            closed_cursors.append(True)
            self._cursor.close()

    class TrackedConnection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, *args, **kwargs):
            return TrackedCursor(self._connection.execute(*args, **kwargs))

        def close(self):
            closed_connections.append(True)
            self._connection.close()

    monkeypatch.setattr(
        store,
        "_decision_context_read_connection",
        lambda: TrackedConnection(original_open()),
    )
    with pytest.raises(RuntimeError, match="stop stream"):
        with store.decision_context_quality_record_stream(batch_size=1) as records:
            next(iter(records))
            raise RuntimeError("stop stream")
    assert closed_connections == [True]
    assert closed_cursors == [True]


def test_stream_connection_setup_closes_after_pragma_error(tmp_path, monkeypatch):
    store = _store(tmp_path)
    closed: list[bool] = []
    executed: list[str] = []

    class BrokenConnection:
        def execute(self, statement, *_args):
            executed.append(statement)
            if len(executed) == 2:
                raise sqlite3.OperationalError("query_only setup failed")
            return self

        def close(self):
            closed.append(True)

    connection = BrokenConnection()
    monkeypatch.setattr(storage_module.sqlite3, "connect", lambda *args, **kwargs: connection)
    with pytest.raises(sqlite3.OperationalError, match="query_only setup failed"):
        store._decision_context_read_connection()
    assert executed == ["PRAGMA busy_timeout=30000", "PRAGMA query_only=ON"]
    assert closed == [True]


def test_legacy_store_without_stream_api_keeps_list_fallback(tmp_path):
    store = _fixture_store(tmp_path)
    class LegacyStore:
        def trade_recommendations(self, *, limit):
            return store.trade_recommendations(limit=limit)

        def order_plans(self, *, limit):
            return store.order_plans(limit=limit)

        def learning_observations(self, *, limit):
            return store.learning_observations(limit=limit)

        def signal_outcomes(self, *, limit, include_lab_book, include_learning_experiment):
            return store.signal_outcomes(
                limit=limit,
                include_lab_book=include_lab_book,
                include_learning_experiment=include_learning_experiment,
            )

    legacy_store = LegacyStore()
    assert build_decision_context_quality(legacy_store, now=NOW, days=1) == _oracle_quality(legacy_store, now=NOW, days=1)
