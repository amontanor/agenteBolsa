import json
import random
import sqlite3
from datetime import datetime, timezone

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.counterfactual_analysis import (
    _compare_policy_rows,
    _iter_signal_rows_spooled,
    _rebuild_signal_cohorts,
    _signal_rows,
)
from agente_bolsa.tools.daily_learning import (
    _build_digest,
    _build_health,
    _build_same_session_opportunity_ledger,
    _compact_cohort_for_daily_analytics,
    _compact_observation_for_digest,
    _materialize_observations,
    _materialize_observations_spooled,
    _observation_payload,
    _observation_payload_from_spool,
    build_learning_daily_run,
    build_learning_digest_report,
)
from agente_bolsa.tools.learning_spool import LearningSpool


def test_spool_preserves_order_and_unknown_nested_fields(tmp_path):
    records = [
        {"signal_id": "b", "features": {"unknown": {"items": [None, 0, False, "á"]}}},
        {"signal_id": "a", "features": {"payload": "x" * 8192}},
    ]
    with LearningSpool(directory=tmp_path) as spool:
        spool_path = spool.path
        for record in records:
            spool.append(record)
        assert list(spool) == records
        assert list(spool) == records
    assert not spool_path.exists()


def test_spool_cleans_up_when_consumer_raises(tmp_path):
    with pytest.raises(ValueError, match="failure"):
        with LearningSpool(directory=tmp_path) as spool:
            spool_path = spool.path
            spool.append({"features": {"unexpected": 1}})
            raise ValueError("failure")
    assert not spool_path.exists()
    with pytest.raises(RuntimeError, match="closed"):
        spool.append({})


def test_spooled_signal_order_matches_legacy_and_closes_on_interrupt():
    records = [
        {"signal_id": "z", "signal_date": "2026-10-15", "created_at": "2", "features": {"unknown": "wide"}},
        {"signal_id": "b", "signal_date": "2026-10-10", "created_at": "1", "features": {"unknown": [1, 2]}},
        {"signal_id": "a", "signal_date": "2026-10-10", "created_at": "1", "features": {"unknown": {"x": 2}}},
        {"signal_id": "older", "signal_date": "2026-10-01", "created_at": "0", "features": {}},
    ]
    state = {"closed": False}

    class Store:
        def signal_outcomes(self, **kwargs):
            return records[:kwargs["limit"]]

        def iter_signal_outcomes(self, **kwargs):
            try:
                yield from records[:kwargs["limit"]]
            finally:
                state["closed"] = True

    kwargs = {"since_date": "2026-10-01", "end_date": "2026-10-12", "limit": 3}
    assert list(_iter_signal_rows_spooled(Store(), **kwargs)) == _signal_rows(Store(), **kwargs)
    assert state["closed"]
    stream = _iter_signal_rows_spooled(Store(), **kwargs)
    next(stream)
    stream.close()
    assert state["closed"]


def test_experimental_spooled_cohorts_match_legacy_with_unknown_fields(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    for i, score in enumerate([10.0, 15.0, 15.0, 3.0]):
        store.save_signal_outcome(
            signal_id=f"signal-{i}", source_run_id="run-a" if i < 3 else "run-b",
            source="test", symbol="SYM0" if i < 3 else "SYM1", signal_date="2026-10-10",
            decision="blocked_backtest" if i == 1 else "candidate",
            features={"score": score, "unknown": {"wide": "x" * 8192}},
            outcome={"return_3d": 0.02, "matured_horizons": {"3d": True}},
        )
    kwargs = {"since_date": "2026-10-01", "end_date": "2026-10-15"}
    expected = _rebuild_signal_cohorts(store, **kwargs)
    compact_rows = [_compact_cohort_for_daily_analytics(row) for row in expected]
    assert _compare_policy_rows(compact_rows, "proposed") == _compare_policy_rows(expected, "proposed")
    assert _compare_policy_rows(compact_rows, "proposed", streaming=True) == _compare_policy_rows(expected, "proposed")
    assert _build_same_session_opportunity_ledger(compact_rows, store, "2026-10-10") == (
        _build_same_session_opportunity_ledger(expected, store, "2026-10-10")
    )
    with LearningSpool(directory=tmp_path) as spool:
        result = _rebuild_signal_cohorts(store, cohort_spool=spool, **kwargs)
        assert result is spool
        assert list(spool) == expected
        expected_observations = _materialize_observations(store, expected)
        assert list(store.iter_learning_observations(limit=10, batch_size=1)) == store.learning_observations(limit=10)
        with LearningSpool(directory=tmp_path) as output:
            batch = _materialize_observations_spooled(store, spool, output)
            assert batch["written"] == len(expected_observations)
            assert list(output.rows_in_observation_order()) == expected_observations
    store.close_read_connection()


def test_spooled_cohort_ranks_match_legacy_with_nan(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    for i, score in enumerate([2.0, float("nan"), 100.0, -3.0]):
        store.save_signal_outcome(
            signal_id=f"s-{i}", source_run_id="run", source="test", symbol=f"S{i}",
            signal_date="2026-10-10", decision="candidate", features={"score": score},
        )
    kwargs = {"since_date": "2026-10-01", "end_date": "2026-10-15"}
    expected = _rebuild_signal_cohorts(store, **kwargs)
    with LearningSpool(directory=tmp_path) as spool:
        _rebuild_signal_cohorts(store, cohort_spool=spool, **kwargs)
        assert [(r["signal_id"], r["rank_context"]) for r in spool] == [
            (r["signal_id"], r["rank_context"]) for r in expected
        ]
    store.close_read_connection()


def test_spooled_materialization_does_not_write_if_later_group_fails(tmp_path, monkeypatch):
    from agente_bolsa.tools import daily_learning

    class Store:
        def upsert_learning_observations_batch(self, _items):
            raise AssertionError("must not write if building any group fails")

    with LearningSpool(directory=tmp_path) as rows, LearningSpool(directory=tmp_path) as observations:
        rows.append({"signal_date": "2026-10-10", "symbol": "A", "source": "test"})
        rows.append({"signal_date": "2026-10-10", "symbol": "B", "source": "test"})
        calls = []

        def fail_on_second(group, *, load_row):
            calls.append(next(iter(group)))
            if len(calls) == 2:
                raise ValueError("second group failed")
            return {"signal_date": "2026-10-10", "symbol": "A", "source_family": "test"}

        monkeypatch.setattr(daily_learning, "_observation_payload_stream", fail_on_second)
        with pytest.raises(ValueError, match="second group failed"):
            _materialize_observations_spooled(Store(), rows, observations)


def test_spooled_materialization_cleans_up_on_disk_full_before_database_write(tmp_path, monkeypatch):
    from agente_bolsa.tools import daily_learning

    class Store:
        def upsert_learning_observations_batch(self, _items):
            raise AssertionError("must not write after disk-full failure")

    paths = []

    class DiskFullSpool(LearningSpool):
        def __init__(self):
            super().__init__(directory=tmp_path)
            paths.append(self.path.parent)
            self.calls = 0

        def append(self, record, *, group_key=""):
            self.calls += 1
            if self.calls == 2:
                raise sqlite3.OperationalError("database or disk is full")
            return super().append(record, group_key=group_key)

    with LearningSpool(directory=tmp_path) as rows, LearningSpool(directory=tmp_path) as observations:
        rows.append({"signal_date": "2026-10-10", "symbol": "A", "source": "test"})
        rows.append({"signal_date": "2026-10-10", "symbol": "B", "source": "test"})
        monkeypatch.setattr(daily_learning, "LearningSpool", DiskFullSpool)
        with pytest.raises(sqlite3.OperationalError, match="disk is full"):
            _materialize_observations_spooled(Store(), rows, observations)
    assert paths and all(not path.exists() for path in paths)


def test_spooled_materialization_reports_disk_full_after_committed_chunk(tmp_path, monkeypatch):
    from agente_bolsa import storage

    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    original = storage._execute_learning_observation_upsert
    calls = 0

    def fail_in_second_chunk(cursor, parameters):
        nonlocal calls
        calls += 1
        if calls == storage.DEFAULT_LEARNING_OBSERVATION_BATCH_SIZE + 1:
            raise sqlite3.OperationalError("database or disk is full")
        return original(cursor, parameters)

    monkeypatch.setattr(storage, "_execute_learning_observation_upsert", fail_in_second_chunk)
    with LearningSpool(directory=tmp_path) as rows, LearningSpool(directory=tmp_path) as observations:
        for i in range(storage.DEFAULT_LEARNING_OBSERVATION_BATCH_SIZE + 1):
            rows.append({
                "signal_id": f"id-{i}", "signal_date": "2026-10-10", "symbol": f"S{i}",
                "source": "test", "source_run_id": "run", "created_at": "2026-10-10",
                "decision": "candidate", "score": 1, "features": {"unknown": i}, "gate": {},
                "outcome": {}, "flags": {}, "rank_context": {}, "executed_buy": False,
            })
        with pytest.raises(storage.LearningObservationBatchError) as raised:
            _materialize_observations_spooled(store, rows, observations)
    result = raised.value.result
    assert result["status"] == "failed"
    assert result["failed_chunk"] == 1
    assert result["written"] == storage.DEFAULT_LEARNING_OBSERVATION_BATCH_SIZE
    assert result["retry_possible"] is False
    assert len(store.learning_observations(limit=1000)) == storage.DEFAULT_LEARNING_OBSERVATION_BATCH_SIZE


def test_streaming_observation_reader_closes_after_invalid_json(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.upsert_learning_observation({
        "observation_id": "id", "signal_date": "2026-10-10", "symbol": "A", "source_family": "test",
        "source_run_ids": [], "rank_path": [], "features": {}, "gate": {}, "outcome": {}, "execution": {},
    })
    with store.connect() as conn:
        conn.execute("UPDATE learning_observations SET features_json = '{invalid' WHERE observation_id = 'id'")
    with pytest.raises(json.JSONDecodeError):
        list(store.iter_learning_observations())
    with store.connect() as conn:
        conn.execute("UPDATE learning_observations SET features_json = '{}' WHERE observation_id = 'id'")


def test_streamed_observation_keeps_execution_lineage_and_best_features(tmp_path):
    base = {
        "signal_date": "2026-10-10", "symbol": "ABC", "source": "scan",
        "source_run_id": "run-1", "created_at": "2026-10-10T12:00:00",
        "considered_by_llm": False, "orders_same_day": 0, "rank_context": {},
        "gate": {}, "outcome": {"matured": False}, "flags": {},
    }
    rows = [
        {**base, "signal_id": "a", "decision": "candidate", "score": 99,
         "features": {"unknown": {"bytes": "x" * 8192}}, "executed_buy": False},
        {**base, "signal_id": "b", "decision": "approved_buy", "score": 2,
         "features": {"unknown": {"bytes": "y" * 8192}, "decision_lineage": {"origin": "exact"}},
         "executed_buy": True, "orders_same_day": 1, "execution_snapshot": {"p": 2}},
        {**base, "signal_id": "c", "decision": "blocked_backtest", "score": 3,
         "features": {"unknown": "z"}, "executed_buy": False, "gate": {"reason": "x"}},
    ]
    with LearningSpool(directory=tmp_path) as spool:
        for row in rows:
            spool.append(row, group_key="group")
        expected = _observation_payload(rows)
        actual = _observation_payload_from_spool(spool, "group")
        assert actual == expected
        assert actual["features"]["unknown"]["bytes"] == "y" * 8192
        assert actual["features"]["decision_lineage"] == {"origin": "exact"}


def test_streamed_observation_keeps_python_sort_semantics_for_nan(tmp_path):
    rows = [
        {"signal_id": f"s{i}", "signal_date": "2026-10-10", "symbol": "ABC", "source": "test",
         "source_run_id": "run", "created_at": "2026-10-10", "score": score,
         "decision": "candidate", "features": {"unknown": f"row-{i}"}, "outcome": {}, "gate": {},
         "executed_buy": False, "orders_same_day": 0, "rank_context": {}, "flags": {}}
        for i, score in enumerate([1.0, float("nan"), 3.0])
    ]
    with LearningSpool(directory=tmp_path) as spool:
        for row in rows:
            spool.append(row, group_key="x")
        actual = _observation_payload_from_spool(spool, "x")
        expected = _observation_payload(rows)
        assert actual["best_signal_id"] == expected["best_signal_id"]
        assert actual["features"] == expected["features"]
        assert [item["signal_id"] for item in actual["rank_path"]] == [item["signal_id"] for item in expected["rank_path"]]


def test_streamed_observation_matches_legacy_for_varied_groups(tmp_path):
    rng = random.Random(17)
    decisions = ["candidate", "hold", "approved_buy", "blocked_backtest", "blocked_entry_quality"]
    with LearningSpool(directory=tmp_path) as spool:
        groups = {}
        for i in range(180):
            key = str(i % 12)
            row = {
                "signal_id": f"id-{i:03}", "signal_date": "2026-10-10", "symbol": f"S{key}",
                "source": "scan", "source_run_id": f"run-{i % 4}",
                "created_at": f"2026-10-10T12:{i % 8:02}:00", "score": rng.choice([0, 2, 5, 9]),
                "decision": rng.choice(decisions), "executed_buy": bool(rng.randrange(3) == 0),
                "considered_by_llm": bool(rng.randrange(2)), "orders_same_day": rng.randrange(3),
                "features": {"unknown": {"payload": f"opaque-{i}"}, "selection_score": rng.choice([0, 1, 2]),
                             "decision_lineage": {"explicit": i}},
                "gate": {"selected": i}, "outcome": {"return_3d": i / 1000},
                "flags": {"duplicate_execution": bool(rng.randrange(2))},
                "rank_context": {"score_rank": i}, "execution_snapshot": {"index": i},
            }
            groups.setdefault(key, []).append(row)
            spool.append(row, group_key=key)
        for key, rows in groups.items():
            assert _observation_payload_from_spool(spool, key) == _observation_payload(rows)


def test_digest_projection_matches_full_observations():
    observations = []
    for i in range(48):
        observations.append({
            "observation_id": f"id-{i}", "signal_date": "2026-10-10", "symbol": f"S{i % 8}",
            "source_family": "scan", "decision": "blocked_backtest" if i % 4 == 0 else "candidate",
            "best_score": i, "best_selection_score": i / 10, "best_rank_priority_score": i / 100,
            "best_selection_rank": i, "duplicate_count": i % 3, "executed_buy": i % 5 == 0,
            "blocked_entry_quality": i % 7 == 0, "blocked_backtest": i % 4 == 0,
            "explanation": "reason", "rank_path": [{"unknown": "x" * 8192}],
            "features": {"unknown": "y" * 8192, "score": i, "rsi_14": 55 + i % 20,
                         "chart_patterns": {"bullish_confirmed_count": i % 2, "unknown": "z" * 1024},
                         "volume_zscore_20": i % 3 - 1, "return_20d": 0.1},
            "gate": {"entry_quality_gate": {"reason": "entry", "unknown": "k" * 1024},
                     "backtest_gate": {"reason": "test"}, "llm": {"confidence": 0.8}},
            "outcome": {"available": True, "matured_horizons": {"1d": True, "3d": True, "5d": True},
                        "return_1d": (i % 3 - 1) / 100, "return_3d": (i % 7 - 3) / 100,
                        "return_5d": (i % 5 - 2) / 100, "unknown": "q" * 8192},
        })
    compact = [_compact_observation_for_digest(item) for item in observations]
    health = _build_health(observations, observations)
    assert _build_health(compact, compact) == health
    original = _build_digest(observations, health, [], {"status_line": "ok"})
    projected = _build_digest(compact, health, [], {"status_line": "ok"})
    original.pop("as_of")
    projected.pop("as_of")
    assert projected == original
    assert "unknown" not in compact[0]["features"]


def test_policy_stream_matches_legacy_with_replacements_and_source_order():
    rows = []
    for source, symbol, executed, score, decision, ret in [
        ("a", "A0", False, 1, "blocked_backtest", 0.00),
        ("b", "B1", True, 1, "approved_buy", -0.04),
        ("a", "A1", True, 1, "approved_buy", -0.03),
        ("a", "A2", False, 30, "candidate", 0.05),
        ("b", "B2", False, 30, "candidate", 0.06),
    ]:
        rows.append({
            "signal_id": symbol, "signal_date": "2026-10-10", "symbol": symbol,
            "source_run_id": source, "decision": decision, "executed_buy": executed,
            "score": score, "features": {"score": score, "volume_zscore_20": 2,
                                          "chart_patterns": {"bullish_confirmed_count": 1}},
            "outcome": {"matured": True, "return_5d": ret}, "outcome_label": "test",
            "regime": {"key": source}, "explanation": "sample",
        })
    baseline = _compare_policy_rows(rows, "proposed")
    assert baseline["rank_shadow"]["candidate_replacements"] == 2
    assert _compare_policy_rows(rows, "proposed", streaming=True) == baseline


def test_policy_stream_matches_legacy_on_varied_rows():
    rng = random.Random(23)
    rows = []
    for i in range(240):
        score = rng.choice([2.0, 12.0, 15.0, 30.0])
        rows.append({
            "signal_id": f"id-{i:03}", "signal_date": f"2026-10-{10 + i % 3}",
            "symbol": f"SYM{i % 11}", "source_run_id": f"run-{i % 8}",
            "decision": rng.choice(["candidate", "hold", "approved_buy", "blocked_backtest"]),
            "executed_buy": bool(rng.randrange(4) == 0), "score": score,
            "features": {"score": score, "rsi_14": rng.choice([55, 65, 80]),
                         "return_20d": rng.choice([-0.1, 0, 0.1]), "volume_zscore_20": rng.choice([-1, 0, 2]),
                         "chart_patterns": {"bullish_confirmed_count": rng.randrange(2)}},
            "outcome": {"matured": bool(rng.randrange(2)), "return_5d": rng.choice([-0.04, 0, 0.05])},
            "outcome_label": "test", "regime": {"key": f"regime-{i % 4}"}, "explanation": "sample",
        })
    assert _compare_policy_rows(rows, "proposed", streaming=True) == _compare_policy_rows(rows, "proposed")


def test_full_daily_spool_matches_legacy_and_persists_unknown_fields(tmp_path, monkeypatch):
    from agente_bolsa.tools import counterfactual_analysis, daily_learning, rr_cohort

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2026, 10, 27, 16, 0, tzinfo=timezone.utc)
            return value if tz is not None else value.replace(tzinfo=None)

    for module in (counterfactual_analysis, daily_learning, rr_cohort):
        monkeypatch.setattr(module, "datetime", Frozen)
    monkeypatch.setattr(daily_learning, "_llm_status_snapshot", lambda _store: {"status_line": "ok"})
    reports = []
    persisted = []
    for use_spool in (False, True):
        root = tmp_path / str(use_spool)
        store = Store(root / "state.sqlite3", root / "logs")
        store.ensure_schema()
        for i in range(24):
            store.save_signal_outcome(
                signal_id=f"id-{i:02}", source_run_id=f"run-{i % 3}", source="test",
                symbol=f"SYM{i % 6}", signal_date="2026-10-10",
                decision="approved_buy" if i in {2, 3} else "blocked_backtest" if i % 4 == 0 else "candidate",
                features={"score": i, "unknown": {"payload": f"{i}:" + "x" * 8192},
                          "rsi_14": 55 + i % 20, "volume_zscore_20": i % 3 - 1},
                outcome={"available": True, "matured_horizons": {"3d": True}, "return_3d": (i % 5 - 2) / 100},
            )
        for i in (2, 3):
            store.save_broker_order(
                broker_order_id=f"bo-{i}", plan_id=f"plan-{i}", cycle_id="cycle-1",
                symbol=f"SYM{i}", side="buy", status="filled",
                payload={"plan": {"payload": {"decision_lineage": {"signal_id": f"id-{i:02}"}}}},
            )
        with store.connect() as conn:
            conn.execute("UPDATE signal_outcomes SET created_at = '2026-10-10T12:00:00+00:00'")
            conn.execute("UPDATE broker_orders SET created_at = '2026-10-10T14:00:00+00:00'")
        report = build_learning_daily_run(
            Settings(DATA_DIR=root / "data", _env_file=None), store, root / "reports", "test",
            since_date="2026-10-01", end_date="2026-10-15", update_result={"updated": 0},
            use_spool=use_spool,
        )
        reports.append(report)
        persisted.append(store.learning_observations(limit=100))
        store.close_read_connection()
    for field in ("health", "digest", "policy_comparison", "observations_summary"):
        assert reports[0][field] == reports[1][field]
    for rows in persisted:
        for row in rows:
            row.pop("created_at", None)
            row.pop("updated_at", None)
    assert persisted[0] == persisted[1]
    assert all(len(row["features"]["unknown"]["payload"]) > 8192 for row in persisted[1])


def test_digest_stream_matches_legacy_with_learning_experiment(tmp_path, monkeypatch):
    from agente_bolsa.tools import counterfactual_analysis, daily_learning, rr_cohort
    from agente_bolsa.tools.learning_mode import LEARNING_EXPERIMENT_SOURCE

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2026, 10, 27, 16, 0, tzinfo=timezone.utc)
            return value if tz is not None else value.replace(tzinfo=None)

    for module in (counterfactual_analysis, daily_learning, rr_cohort):
        monkeypatch.setattr(module, "datetime", Frozen)
    monkeypatch.setattr(daily_learning, "_llm_status_snapshot", lambda _store: {"status_line": "ok"})
    results = []
    for streaming in (False, True):
        root = tmp_path / str(streaming)
        store = Store(root / "state.sqlite3", root / "logs")
        store.ensure_schema()
        for i in range(12):
            store.save_signal_outcome(
                signal_id=f"id-{i}", source_run_id="run", source=LEARNING_EXPERIMENT_SOURCE,
                symbol=f"S{i % 3}", signal_date="2026-10-10", decision="candidate",
                features={"score": i, "unknown": "x" * 8192, "backtest_soft_override": True},
                outcome={"available": True, "matured_horizons": {"3d": True}, "return_3d": -0.03},
            )
        with store.connect() as conn:
            conn.execute("UPDATE signal_outcomes SET created_at = '2026-10-10T12:00:00+00:00'")

        class LegacyStore:
            def __init__(self, wrapped):
                self.wrapped = wrapped

            def __getattr__(self, name):
                if name in {"iter_learning_observations", "iter_signal_outcomes"}:
                    raise AttributeError(name)
                return getattr(self.wrapped, name)

        target = store if streaming else LegacyStore(store)
        results.append(build_learning_digest_report(target, root / "reports", "test", since_date="2026-10-01"))
        store.close_read_connection()
    assert results[0]["digest"] == results[1]["digest"]
