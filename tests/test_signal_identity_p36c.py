import copy

from agente_bolsa.cycle_runner import _decision_context_snapshot_for_recommendation
from agente_bolsa.models import TradeRecommendation
from agente_bolsa.scheduler import _compact_scan_context
from agente_bolsa.storage import Store
from agente_bolsa.tools.decision_lineage import build_decision_lineage
from agente_bolsa.tools.signal_learning import record_signal_candidates


def test_canonical_signal_id_survives_producer_to_lineage_without_unknown(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    candidate = {
        "symbol": "FDS",
        "direction": "long",
        "strategy_name": "builtin_breakout",
        "strategy_version": "v1",
        "last_date": "2026-07-13",
        "technical_state": {"close": 100},
        "risk_plan": {"entry_price": 100, "stop_loss": 90, "take_profit": 120},
    }
    report = {"run_id": "signal-run", "all_candidates": [candidate]}
    assert record_signal_candidates(store, report, source="learning_experiment") == 1
    persisted = store.signal_outcome_by_id(candidate["signal_id"])
    recommendation = TradeRecommendation(symbol="FDS", action="buy", confidence=0.8, reason="test")
    lineage = build_decision_lineage(
        recommendation,
        {"selected_candidates": [candidate]},
        cycle_id="decision-cycle",
        policy_version="v",
    )
    assert lineage["signal_id"] == persisted["signal_id"]
    assert lineage["signal_id"] == "learning_experiment:2026-07-13:BUILTIN_BREAKOUT:FDS"
    assert lineage["signal_source_run_id"] == "signal-run"
    assert lineage["cycle_id"] == "decision-cycle"
    assert lineage["lineage_status"] == "verified"


def test_real_scheduler_compaction_preserves_identity_across_independent_buckets(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    base = {
        "symbol": "FDS", "direction": "long", "strategy_name": "builtin_breakout",
        "strategy_version": "v1", "last_date": "2026-07-13", "score": 9,
        "selection_rank": 1, "technical_state": {"close": 100},
        "risk_plan": {"entry_price": 100, "stop_loss": 90, "take_profit": 120},
    }
    all_candidate = copy.deepcopy(base)
    selected_candidate = copy.deepcopy(base)
    top_candidate = copy.deepcopy(base)
    report = {
        "run_id": "signal-run",
        "all_candidates": [all_candidate],
        "selected_candidates": [selected_candidate],
        "top_longs": [top_candidate],
        "top_shorts": [],
    }
    record_signal_candidates(store, report, source="learning_experiment")
    expected_identity = {
        "signal_id": "learning_experiment:2026-07-13:BUILTIN_BREAKOUT:FDS",
        "signal_source_run_id": "signal-run",
        "signal_strategy_name": "builtin_breakout",
        "signal_strategy_version": "v1",
    }
    for bucket_name in ("all_candidates", "selected_candidates", "top_longs"):
        assert {key: report[bucket_name][0].get(key) for key in expected_identity} == expected_identity
    compact = _compact_scan_context(report, [selected_candidate])
    lineage = build_decision_lineage(
        TradeRecommendation(symbol="FDS", action="buy", confidence=0.8, reason="test"),
        compact,
        cycle_id="decision-cycle",
        policy_version="v",
    )
    assert lineage["signal_id"] == "learning_experiment:2026-07-13:BUILTIN_BREAKOUT:FDS"
    assert lineage["signal_source_run_id"] == "signal-run"
    assert lineage["cycle_id"] == "decision-cycle"

    recommendation = TradeRecommendation(
        symbol="FDS",
        action="buy",
        confidence=0.8,
        reason="test",
        source="deterministic",
        decision_lineage=lineage,
    )
    snapshot = _decision_context_snapshot_for_recommendation(
        store,
        recommendation,
        cycle_id="decision-cycle",
        source_run_id="decision-cycle",
        market_state={
            "run_id": "decision-cycle",
            "as_of": "2026-07-13T20:00:00+00:00",
            "prompt_version": "market_state.v2",
            "market_regime": "neutral",
            "volatility_regime": "normal",
            "risk_posture": "normal",
            "data_quality": {"status": "available"},
        },
        agent_run_id=None,
    )
    assert snapshot["signal_id"] == "learning_experiment:2026-07-13:BUILTIN_BREAKOUT:FDS"
    assert snapshot["signal_link_status"] == "verified"
    assert snapshot["cycle_id"] == "decision-cycle"
    assert snapshot["market_state_ref"]["cycle_id"] == "decision-cycle"


def test_identity_without_source_run_or_with_ambiguous_strategy_is_not_verified():
    recommendation = TradeRecommendation(symbol="FDS", action="buy", confidence=0.8, reason="test")
    missing_source = build_decision_lineage(
        recommendation,
        {"selected_candidates": [{"symbol": "FDS", "signal_id": "sig", "strategy_name": "one"}]},
        cycle_id="decision-cycle",
        policy_version="v",
    )
    assert missing_source["lineage_status"] == "unavailable"
    assert missing_source["lineage_reason"] == "missing_signal_source_run_id"

    ambiguous = build_decision_lineage(
        recommendation,
        {
            "selected_candidates": [
                {"symbol": "FDS", "signal_id": "sig-1", "signal_source_run_id": "run-1", "strategy_name": "one"},
                {"symbol": "FDS", "signal_id": "sig-2", "signal_source_run_id": "run-2", "strategy_name": "two"},
            ]
        },
        cycle_id="decision-cycle",
        policy_version="v",
    )
    assert ambiguous["lineage_status"] == "unavailable"
    assert ambiguous["signal_id"] is None


def test_producer_marks_duplicate_canonical_identity_ambiguous(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    duplicate = {
        "symbol": "FDS",
        "direction": "long",
        "strategy_name": "builtin_breakout",
        "strategy_version": "v1",
        "last_date": "2026-07-13",
        "technical_state": {"close": 100},
        "risk_plan": {"entry_price": 100, "stop_loss": 90, "take_profit": 120},
    }
    report = {
        "run_id": "signal-run",
        "all_candidates": [copy.deepcopy(duplicate), copy.deepcopy(duplicate)],
        "selected_candidates": [copy.deepcopy(duplicate)],
    }
    record_signal_candidates(store, report, source="learning_experiment")
    assert report["all_candidates"][0].get("signal_id") is None
    assert report["all_candidates"][0]["signal_identity_status"] == "ambiguous"
    row = store.signal_outcome_by_id("learning_experiment:2026-07-13:BUILTIN_BREAKOUT:FDS")
    assert row["features"]["signal_identity_status"] == "ambiguous"
    assert row["features"]["signal_source_run_id"] is None
