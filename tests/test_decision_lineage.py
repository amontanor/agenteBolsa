from dataclasses import replace

from agente_bolsa.models import TradeRecommendation
from agente_bolsa.tools.decision_lineage import (
    build_decision_lineage,
    legacy_unverified_lineage,
    normalized_decision_source,
)


def _recommendation(**updates):
    base = TradeRecommendation(
        symbol="AAPL",
        action="buy",
        confidence=0.8,
        reason="test",
        cohort="learning_experiment",
        strategy_name="builtin_breakout",
    )
    return replace(base, **updates)


def test_verified_lineage_is_stable_and_complete():
    context = {
        "selected_candidates": [
            {
                "symbol": "AAPL",
                "last_date": "2026-07-10",
                "selection_rank": 2,
                "strategy_name": "builtin_breakout",
                "strategy_version": "1",
            }
        ]
    }

    first = build_decision_lineage(
        _recommendation(),
        context,
        cycle_id="cycle-1",
        policy_version="0.4.141",
    )
    second = build_decision_lineage(
        _recommendation(),
        context,
        cycle_id="cycle-1",
        policy_version="0.4.141",
    )

    assert first == second
    assert first["lineage_status"] == "verified"
    assert first["signal_id"] == "learning_experiment:2026-07-10:BUILTIN_BREAKOUT:AAPL"
    assert first["candidate_rank"] == 2
    assert first["decision_source"] == "llm"


def test_lineage_distinguishes_deterministic_capacity_and_low_sample():
    deterministic = _recommendation(
        source="deterministic_fallback",
        decision_origin="deterministic_fallback_llm_failed",
    )
    capacity = _recommendation(capacity_fill_reason_code="capacity_fill_tras_llm_ok")
    low_sample = _recommendation(tags=["low_sample_exploration"])
    context = {
        "selected_candidates": [
            {"symbol": "AAPL", "last_date": "2026-07-10", "strategy_name": "builtin_breakout"}
        ]
    }

    assert normalized_decision_source(deterministic) == "deterministic"
    assert normalized_decision_source(capacity) == "capacity_fill"
    assert build_decision_lineage(
        low_sample,
        context,
        cycle_id="cycle",
        policy_version="v",
    )["low_sample_exploration"] is True


def test_legacy_lineage_never_infers_strategy():
    lineage = legacy_unverified_lineage(cycle_id="old", signal_id="signal")

    assert lineage["lineage_status"] == "legacy_unverified"
    assert lineage["strategy_name"] is None
    assert lineage["policy_version"] is None
