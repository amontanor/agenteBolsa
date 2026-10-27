"""Frozen pre-streaming contract and bounded-memory regression for learning readers."""
import copy
import json
import tracemalloc
from pathlib import Path
from types import SimpleNamespace

import pytest

from agente_bolsa.storage import Store
from agente_bolsa.tools import post_market_review as review
from agente_bolsa.tools import signal_learning as learning


def metric_rows():
    rows = []
    decisions = ["candidate", "approved_buy", "blocked_entry_quality", "blocked_backtest", "executed_buy", ""]
    for i in range(42):
        contract = {
            "schema_version": learning.AGENT_CONTRACT_SCHEMA_VERSION,
            "agent_name": f"agent-{i % 3}", "agent_run_id": f"run-{i % 7}",
            "cycle_id": f"cycle-{i % 5}", "decision_source": ["llm", "fallback", "deterministic"][i % 3],
            "llm_provider": "provider", "llm_effective_model": "model",
            "parent_run_id": "parent" if i % 2 else None, "retry_of": "retry" if i % 4 else None,
            "fallback": {"used": i % 3 == 1, "reason": "funds"},
            "extra_identity_evidence": "original",
        }
        features = {
            "direction": ["long", "short", "exit", "missing"][i % 4],
            "position_direction": "short" if i % 8 == 2 else None,
            "selected_for_llm": [True, False, None, 1][i % 4],
            "score": i % 18, "rsi_14": 58 + i, "distance_sma20": (i % 5) / 20,
            "macd_diff": i % 3 - 1, "volume_zscore_20": i % 4 - 1, "return_20d": i / 100,
            "chart_patterns": {"bullish_confirmed_count": i % 2},
            "decision_context_snapshot": {"agent_contract": copy.deepcopy(contract)},
            "decision_lineage": {"recommendation_id": f"rec-{i}", "plan_id": f"plan-{i}"},
            "execution_quality_snapshot": {"broker_order_id": f"order-{i}"},
            "comparable_control_set": {"status": "verified", "cycle_id": contract["cycle_id"], "treatment": {"signal_id": f"signal-{i}"}},
            "irrelevant_large_payload": "x" * 2000,
        }
        features[["event_momentum_long", "range_expansion_breakout_long", "orderly_breakout_long", "momentum_shakeout_hold_long"][i % 4]] = i % 5 == 0
        execution = {"signal_id": f"signal-{i}", "status": "submitted", "agent_contract": copy.deepcopy(contract)}
        if i % 7 == 0:
            execution["agent_contract"]["extra_identity_evidence"] = "conflict"
        if i % 7 == 1:
            features.pop("decision_context_snapshot")
            execution.pop("agent_contract")
        if i % 7 == 2:
            features["decision_lineage"]["lineage_status"] = "legacy_unverified"
        if i % 7 == 3:
            execution["signal_id"] = "different"
        if i % 7 == 4:
            features["comparable_control_set"]["cycle_id"] = "different"
        if i % 7 == 5:
            producer = {
                "schema_version": learning.AGENT_PRODUCER_SCHEMA_VERSION,
                "raw_role": "technical_analyst", "canonical_agent_id": learning.canonical_agent_id("technical_analyst"),
                "agent_run_id": f"producer-{i % 3}", "cycle_id": contract["cycle_id"],
                "execution_kind": "deterministic", "provider": None, "model": None,
                "parent_run_id": None, "retry_of": None, "fallback_reason": None,
            }
            features["producer_agent_contract"] = producer
            execution["producer_agent_contract"] = copy.deepcopy(producer)
        outcome = {"verdict": ["pending", "winner_5d", "loser_5d", None][i % 4], "source": "trade_memory" if i % 11 == 0 else "market"}
        outcome["matured_horizons"] = {f"{h}d": [True, False, None][(i + h) % 3] for h in learning.HORIZONS}
        for h in learning.HORIZONS:
            outcome[f"return_{h}d"] = None if i % 5 == 0 else (i % 9 - 4) / 100
        outcome.update({"mfe_10d": i / 100, "mae_10d": -i / 100, "unused_capture": "y" * 2000})
        rows.append({"signal_id": f"signal-{i}", "source_run_id": f"scan-{i % 4}", "signal_date": "2026-10-12", "decision": decisions[i % 6], "features": features, "gate": {"execution": execution, "other": {"large": "z" * 2000}}, "outcome": outcome})
    return rows


class SignalStore:
    def __init__(self, rows):
        self.rows = rows

    def signal_outcomes(self, **kwargs):
        return self.rows[:kwargs["limit"]]

    def iter_signal_outcomes(self, **kwargs):
        yield from self.rows[:kwargs["limit"]]


def recommendations():
    return [
        {"recommendation_id": "r1", "cycle_id": "c1", "symbol": "AAA", "action": "buy", "created_at": "2026-10-12", "payload": {"decision_lineage": {"signal_id": "exact:2026-10-12:AAA"}, "unused": "x" * 2000}},
        {"recommendation_id": "r1", "cycle_id": "c2", "symbol": "AAA", "action": "buy", "created_at": "2026-10-12", "payload": {"decision_lineage": {"signal_id": "different"}}},
        {"recommendation_id": "r2", "cycle_id": "c2", "symbol": "BBB", "action": "buy", "created_at": "2026-10-11", "payload": {"decision_lineage": {"signal_id": "exact:2026-10-12:BBB"}}},
        {"recommendation_id": "", "cycle_id": "c3", "symbol": "CCC", "action": "buy", "created_at": "2026-10-12", "payload": {}},
        {"recommendation_id": "r3", "cycle_id": "c4", "symbol": "DDD", "action": "buy", "created_at": "2026-10-11", "payload": {}},
    ]


def ledger(monkeypatch):
    rows = recommendations()
    monkeypatch.setattr(review, "_session_event_payloads", lambda *_: [{"__event_cycle_id": "c1", "rejected_order_plans": [{"plan_id": "p1", "symbol": "AAA"}, {"plan_id": "p1", "symbol": "AAA"}, {"symbol": "BBB", "reason": "gate"}]}])
    store = SimpleNamespace(trade_recommendations=lambda **_: rows, iter_trade_recommendations=lambda **_: iter(rows))
    return review._session_candidate_attribution(store, "2026-10-12", [{"recommendation_id": "r1", "broker_order_id": "o1"}])


def test_frozen_baseline_parity(monkeypatch):
    expected = json.loads((Path(__file__).parent / "fixtures/oct13_learning_memory_baseline.json").read_text())
    assert json.loads(json.dumps(learning.build_learning_status(SignalStore(metric_rows()), limit=200000))) == expected["learning"]
    assert learning.build_learning_status(SignalStore([]), limit=200000) == expected["empty"]
    assert ledger(monkeypatch) == expected["ledger"]


def test_metric_projection_preserves_scoreboard_and_drops_large_carriers():
    for row in metric_rows():
        compact = learning._compact_learning_metric_signal(row)
        assert learning.build_agent_learning_scoreboard([compact]) == learning.build_agent_learning_scoreboard([row])
        assert learning._indicator_tags(compact) == learning._indicator_tags(row)
        assert learning._combo_key(compact) == learning._combo_key(row)
        assert learning._setup_key(compact) == learning._setup_key(row)
        assert "irrelevant_large_payload" not in compact.get("features", {})
        assert "unused_capture" not in compact.get("outcome", {})


def test_scoreboard_only_projection_preserves_malformed_and_unknown_carriers():
    rows = metric_rows() + [
        {"signal_id": "malformed", "features": ["bad"], "outcome": ["bad"], "gate": {}},
        {"signal_id": "wide", "features": {"unknown": "x" * 8192, "chart_patterns": [],
                                            "selected_for_llm": "y" * 8192}, "outcome": {}},
    ]
    compact = [learning._compact_learning_metric_signal(row, scoreboard_only=True) for row in rows]
    assert learning.build_agent_learning_scoreboard(compact) == learning.build_agent_learning_scoreboard(rows)
    assert "unknown" not in compact[-1]["features"]
    assert compact[-1]["features"]["selected_for_llm"] is None


def test_digest_scoreboard_stream_applies_date_filter_after_limit_and_closes():
    from agente_bolsa.tools.daily_learning import _digest_scoreboard_rows

    records = [
        {"signal_id": "excluded", "signal_date": "2026-10-15", "features": {}, "outcome": {}},
        {"signal_id": "retained", "signal_date": "2026-10-10", "features": {"unknown": "x" * 8192}, "outcome": {}},
    ]
    state = {"closed": False}

    class Store:
        def iter_signal_outcomes(self, **kwargs):
            assert kwargs == {"limit": 200000, "since_date": "2026-10-01"}
            try:
                yield from records
            finally:
                state["closed"] = True

    result = _digest_scoreboard_rows(Store(), since_date="2026-10-01", end_date="2026-10-12")
    assert state["closed"]
    assert learning.build_agent_learning_scoreboard(result) == learning.build_agent_learning_scoreboard(records[1:])
    assert "unknown" not in result[0]["features"]


def test_streaming_report_peak_does_not_retain_large_payloads():
    class StreamingStore:
        def signal_outcomes(self, **_):
            raise AssertionError("legacy materialization forbidden")

        def iter_signal_outcomes(self, **kwargs):
            assert kwargs == {"limit": 200000, "since_date": "2026-04-01"}
            for i in range(600):
                row = metric_rows()[i % 42]
                row["features"]["irrelevant_large_payload"] = "x" * 100000
                row["outcome"]["unused_capture"] = "y" * 100000
                yield row

    tracemalloc.start()
    try:
        report = learning.build_learning_status(StreamingStore(), limit=200000)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert report["signals"] == 600
    assert peak < 12_000_000, peak


def test_iterators_match_legacy_selection_and_close_cursor(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    original_reader = store._decision_context_read_connection
    opened = []

    class Cursor:
        def __init__(self, cursor):
            self.cursor = cursor
            self.closed = False

        def fetchmany(self, batch_size):
            return self.cursor.fetchmany(batch_size)

        def close(self):
            self.closed = True
            self.cursor.close()

    class Connection:
        def __init__(self):
            self.connection = original_reader()
            assert self.connection.execute("PRAGMA query_only").fetchone()[0] == 1
            self.closed = False
            self.cursor = None

        def execute(self, query, params):
            self.cursor = Cursor(self.connection.execute(query, params))
            return self.cursor

        def close(self):
            self.closed = True
            self.connection.close()

    def tracked_reader():
        connection = Connection()
        opened.append(connection)
        return connection

    monkeypatch.setattr(store, "_decision_context_read_connection", tracked_reader)
    with store.connect() as conn:
        for i, source in enumerate(["scan", "lab_book", "learning_experiment", "scan"]):
            conn.execute("INSERT INTO signal_outcomes(signal_id, source_run_id, source, symbol, signal_date, decision, features_json, gate_json, outcome_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (str(i), "run", source, "AAA", "2026-10-12", "candidate", '{"score":1}', '{}', '{}', f"2026-10-12T00:00:0{i}", "2026-10-12"))
        for i in range(4):
            conn.execute("INSERT INTO trade_recommendations(recommendation_id, cycle_id, symbol, action, confidence, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (str(i), "cycle", "AAA", "buy", 0.5, '{}', f"2026-10-12T00:00:0{i}"))
    for kwargs in ({"limit": 2}, {"limit": 0}, {"limit": -1, "include_lab_book": True, "include_learning_experiment": True}, {"limit": 3, "sources": ["scan"], "since_date": "2026-10-12"}):
        assert list(store.iter_signal_outcomes(**kwargs, batch_size=1)) == store.signal_outcomes(**kwargs)
    for kwargs in ({"limit": 2}, {"limit": 0}, {"cycle_id": "cycle", "limit": 4}):
        assert list(store.iter_trade_recommendations(**kwargs, batch_size=1)) == store.trade_recommendations(**kwargs)
    with store.connect() as conn:
        conn.execute("UPDATE signal_outcomes SET features_json='invalid' WHERE signal_id='3'")
    with pytest.raises(json.JSONDecodeError):
        list(store.iter_signal_outcomes(include_lab_book=True, include_learning_experiment=True, batch_size=1))
    reader = store.iter_trade_recommendations(batch_size=1)
    next(reader)
    reader.close()
    store.close_read_connection()
    assert len(opened) == 9
    assert all(connection.closed and connection.cursor.closed for connection in opened)
    # The exhausted, failed and explicitly closed generators release owned resources.
    with store.connect() as conn:
        conn.execute("BEGIN EXCLUSIVE")
        conn.rollback()


def test_producer_conflict_in_unused_evidence_remains_conflict():
    row = next(row for row in metric_rows() if "producer_agent_contract" in row["features"])
    row["gate"]["execution"]["producer_agent_contract"]["unused_evidence"] = "different"
    compact = learning._compact_learning_metric_signal(row)
    assert learning._agent_contract_from_signal(compact)[1:] == ("conflict", "producer")
    assert learning.build_agent_learning_scoreboard([compact]) == learning.build_agent_learning_scoreboard([row])


def test_report_closes_reader_when_projection_fails():
    closed = []

    def reader(**_):
        try:
            yield {"features": {"chart_patterns": ["malformed"]}, "outcome": {}, "decision": "candidate"}
        finally:
            closed.append(True)

    with pytest.raises(AttributeError):
        learning.build_learning_status(SimpleNamespace(iter_signal_outcomes=reader))
    assert closed == [True]


def test_recommendation_stream_does_not_retain_unused_payloads(monkeypatch):
    monkeypatch.setattr(review, "_session_event_payloads", lambda *_: [])

    def reader(**kwargs):
        assert kwargs == {"limit": 100000}
        for i in range(600):
            yield {"recommendation_id": f"r-{i}", "cycle_id": "c", "symbol": "AAA", "action": "buy", "created_at": "2026-10-12", "payload": {"decision_lineage": {"signal_id": f"s-{i}"}, "large": "x" * 100000}}

    tracemalloc.start()
    try:
        report = review._session_candidate_attribution(SimpleNamespace(iter_trade_recommendations=reader), "2026-10-12", [])
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert report["recommendations_raw"] == report["recommendations_unique"] == 600
    assert peak < 4_000_000, peak
