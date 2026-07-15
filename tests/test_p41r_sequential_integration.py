from __future__ import annotations

import copy
from dataclasses import asdict
from datetime import datetime, timezone
from types import SimpleNamespace

from agente_bolsa.cycle_runner import _decision_context_snapshot_for_recommendation
from agente_bolsa.models import TradeRecommendation
from agente_bolsa.scheduler import _compact_scan_context
from agente_bolsa.storage import Store
from agente_bolsa.tools.comparable_controls import build_comparable_control_sets
from agente_bolsa.tools.decision_lineage import build_decision_lineage
from agente_bolsa.tools.execution_quality import build_planned_snapshot
from agente_bolsa.tools.gate_evaluation import collect_gate_path
from agente_bolsa.tools.performance_benchmark import (
    benchmark_summary,
    build_daily_performance_item,
)
from agente_bolsa.tools.signal_identity import resolve_signal_capture
from agente_bolsa.tools.signal_learning import record_signal_candidates


def _store(tmp_path):
    store = Store(tmp_path / "state" / "integration.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    return store


def _settings(tmp_path):
    return SimpleNamespace(
        data_dir=tmp_path,
        market_data_provider="auto",
        fmp_api_key=None,
        benchmark_symbol="SPY",
    )


def _candidate(*, candidate_id: str, strategy: str = "builtin_breakout") -> dict:
    return {
        "symbol": "FDS",
        "direction": "long",
        "action": "buy",
        "score": 9.25,
        "selection_rank": 1,
        "strategy_name": strategy,
        "strategy_version": "v1",
        "setup_name": "breakout",
        "setup_quality": "strong",
        "last_date": "2026-07-13",
        "technical_state": {"close": 100.0, "sma_20": 97.0},
        "risk_plan": {"entry_price": 100.0, "stop_loss": 90.0, "take_profit": 120.0, "quantity": 3},
        "candidate_id": candidate_id,
    }


def _report(run_id: str, candidate: dict) -> dict:
    return {
        "run_id": run_id,
        "as_of": "2026-07-13T20:00:00+00:00",
        "all_candidates": [copy.deepcopy(candidate)],
        "selected_candidates": [copy.deepcopy(candidate)],
        "top_longs": [copy.deepcopy(candidate)],
        "top_shorts": [],
        "symbols_scanned": 1,
        "symbols_with_data": 1,
        "warnings": [],
    }


def _recommendation(lineage: dict) -> TradeRecommendation:
    return TradeRecommendation(
        symbol="FDS",
        action="buy",
        confidence=0.8,
        reason="P-L41R integration",
        source="deterministic",
        strategy_name="builtin_breakout",
        entry_price=100.0,
        stop_loss=90.0,
        take_profit=120.0,
        decision_lineage=lineage,
    )


def test_sequential_capture_then_benchmark_preserves_both_contracts(tmp_path):
    store = _store(tmp_path)
    report_a = _report("source-run-A", _candidate(candidate_id="candidate-A"))
    report_b = _report("source-run-B", _candidate(candidate_id="candidate-B"))
    assert record_signal_candidates(store, report_a, source="learning_experiment") == 1
    capture_a = report_a["all_candidates"][0]["signal_capture_id"]
    assert record_signal_candidates(store, report_b, source="learning_experiment") == 1
    signal_id = report_a["all_candidates"][0]["signal_id"]
    resolved = resolve_signal_capture(store, capture_a, signal_id=signal_id)
    assert resolved["status"] == "exact_match"
    assert resolved["capture"]["signal_source_run_id"] == "source-run-A"
    assert report_b["all_candidates"][0]["signal_id"] == signal_id

    store.upsert_performance_daily({"session_date": "2026-07-10", "equity": 100.0, "payload": {}})
    item = build_daily_performance_item(
        store,
        _settings(tmp_path),
        "2026-07-13",
        portfolio=None,
        now=datetime(2026, 7, 14, 22, 0, tzinfo=timezone.utc),
        spy_observation={"status": "unavailable", "warnings": ["synthetic_missing"]},
    )
    assert store.upsert_performance_benchmark(item)["status"] == "inserted"
    assert store.signal_outcome_by_id(signal_id)["features"]["signal_identity"]["captures"]
    assert benchmark_summary(store.performance_daily(limit=0))["rows"] == 1


def test_sequential_cycle_path_reaches_context_gates_controls_plan_and_broker(tmp_path):
    store = _store(tmp_path)
    report = _report("source-run-A", _candidate(candidate_id="candidate-A"))
    assert record_signal_candidates(store, report, source="learning_experiment") == 1
    compact = _compact_scan_context(report, report["selected_candidates"])
    lineage = build_decision_lineage(
        _recommendation({}),
        compact,
        cycle_id="cycle-A",
        policy_version="p-l41r",
        source_run_id="cycle-A",
    )
    recommendation = _recommendation(lineage)
    context = _decision_context_snapshot_for_recommendation(
        store,
        recommendation,
        cycle_id="cycle-A",
        source_run_id="cycle-A",
        market_state={
            "run_id": "cycle-A",
            "cycle_id": "cycle-A",
            "as_of": "2026-07-13T18:00:00+00:00",
            "prompt_version": "market_state.v2",
            "market_regime": "neutral",
            "volatility_regime": "normal",
            "risk_posture": "normal",
            "data_quality": {"status": "available"},
        },
        agent_run_id="agent-run-A",
    )
    recommendation = recommendation.__class__(**{**asdict(recommendation), "decision_context_snapshot": context})
    gate = collect_gate_path(
        cycle_id="cycle-A",
        candidates=[recommendation],
        stage_rows={},
        final_plans=[SimpleNamespace(recommendation=recommendation)],
        captured_at="2026-07-13T20:01:00+00:00",
    )[lineage["candidate_id"]]
    control = build_comparable_control_sets(
        cycle_id="cycle-A",
        recommendations=[recommendation],
        plans=[{"plan_id": "plan-A", "symbol": "FDS", "side": "buy", "recommendation": recommendation}],
    )[lineage["signal_id"]]
    execution = build_planned_snapshot(
        plan_id="plan-A",
        cycle_id="cycle-A",
        symbol="FDS",
        side="buy",
        payload={"recommendation": asdict(recommendation), "decision_lineage": lineage, "entry_price": 100.0, "qty": 1.0},
        planned_at="2026-07-13T20:02:00+00:00",
        signal_price=100.0,
    )
    assert lineage["signal_capture_id"] == context["signal_capture_id"]
    assert gate["signal_capture_id"] == lineage["signal_capture_id"]
    assert control["treatment"]["signal_capture_id"] == lineage["signal_capture_id"]
    assert execution["signal_capture_id"] == lineage["signal_capture_id"]


def test_legacy_writers_preserve_signal_history_and_performance_contract(tmp_path):
    store = _store(tmp_path)
    report = _report("source-run-A", _candidate(candidate_id="candidate-A"))
    record_signal_candidates(store, report, source="learning_experiment")
    signal_id = report["all_candidates"][0]["signal_id"]
    capture_id = report["all_candidates"][0]["signal_capture_id"]
    store.save_signal_outcome(
        signal_id=signal_id,
        source_run_id="legacy-run",
        source="legacy",
        symbol="FDS",
        signal_date="2026-07-13",
        decision="candidate",
        features={"legacy_branch": {"kept": True}},
    )
    store.upsert_performance_daily({"session_date": "2026-07-10", "equity": 100.0, "payload": {}})
    item = build_daily_performance_item(
        store,
        _settings(tmp_path),
        "2026-07-13",
        portfolio=None,
        now=datetime(2026, 7, 14, 22, 0, tzinfo=timezone.utc),
        spy_observation={"status": "unavailable", "warnings": ["synthetic_missing"]},
    )
    store.upsert_performance_benchmark(item)
    store.upsert_performance_daily({"session_date": "2026-07-13", "payload": {"legacy_note": "kept"}})
    signal_row = store.signal_outcome_by_id(signal_id)
    performance_row = store.performance_daily(limit=0)[-1]
    assert capture_id in signal_row["features"]["signal_identity"]["captures"]
    assert signal_row["features"]["legacy_branch"] == {"kept": True}
    assert performance_row["payload"]["performance_benchmark"]["schema_version"] == "p-l40b.performance-benchmark.v1"
    assert performance_row["payload"]["legacy_note"] == "kept"


def test_benchmark_failure_is_fail_open_and_does_not_capture_again(tmp_path, monkeypatch):
    from agente_bolsa import scheduler

    store = _store(tmp_path)
    settings = _settings(tmp_path)
    settings.logs_dir = tmp_path / "logs"
    calls: list[str] = []

    class Client:
        def alpaca_portfolio_snapshot(self):
            calls.append("portfolio")
            raise AssertionError("provided snapshot must not be recaptured")

    class Reporter:
        def emit(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(scheduler, "BrokerClientFactory", lambda _settings: Client())
    monkeypatch.setattr(scheduler, "build_daily_performance_item", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("benchmark failure")))
    scheduler._persist_daily_performance(
        settings,
        store,
        "2026-07-13",
        Reporter(),
        "run-integration",
        portfolio=None,
    )
    assert calls == []
