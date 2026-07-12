from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone

from agente_bolsa.config import Settings
from agente_bolsa.models import OrderPlan, RiskDecision, TradeRecommendation
from agente_bolsa.storage import Store
from agente_bolsa.tools.comparable_controls import (
    LEGACY_SCHEMA_VERSION,
    SCHEMA_VERSION,
    build_comparable_control_quality,
    build_comparable_control_sets,
    candidate_id_for,
)
from agente_bolsa.tools.decision_context import build_decision_context_snapshot
from agente_bolsa.tools.signal_learning import attach_comparable_control_sets


def _market(cycle: str) -> dict[str, object]:
    return {
        "run_id": cycle,
        "as_of": "2026-07-12T09:00:00+00:00",
        "prompt_version": "market_state.v2",
        "market_regime": "neutral",
        "volatility_regime": "normal",
        "risk_posture": "balanced",
        "data_quality": {"status": "GOOD"},
    }


def _rec(symbol: str, rank: int, cycle: str = "cycle-1") -> TradeRecommendation:
    signal_id = f"run:{cycle}:signal:{symbol}"
    lineage = {
        "signal_id": signal_id,
        "candidate_id": candidate_id_for(cycle, signal_id, "run-1"),
        "cycle_id": cycle,
        "source_run_id": "run-1",
        "candidate_rank": rank,
    }
    rec = TradeRecommendation(
        symbol=symbol,
        action="buy",
        confidence=0.9,
        reason="fixture",
        entry_price=100.0 + rank,
        stop_loss=95.0 + rank,
        take_profit=115.0 + rank,
        decision_lineage=lineage,
        source="deterministic",
    )
    snapshot = build_decision_context_snapshot(
        rec,
        cycle_id=cycle,
        source_run_id="run-1",
        market_state=_market(cycle),
        captured_at=datetime(2026, 7, 12, 10, tzinfo=timezone.utc),
        signal_id=signal_id,
        signal_link_status="verified",
        identity_key=f"{cycle}|{symbol}",
    )
    return replace(rec, decision_context_snapshot=snapshot)


def _plan(rec: TradeRecommendation) -> OrderPlan:
    return OrderPlan(
        symbol=rec.symbol,
        side="buy",
        notional=100.0,
        qty=1.0,
        entry_price=rec.entry_price or 0.0,
        stop_loss=rec.stop_loss or 0.0,
        take_profit=rec.take_profit or 0.0,
        recommendation=rec,
        risk_decision=RiskDecision(True, "ok", {}),
    )


def _gates(*recommendations: TradeRecommendation) -> list[dict[str, object]]:
    return [
        {
            "symbol": rec.symbol,
            "action": rec.action,
            "approved": True,
            "candidate_id": rec.decision_lineage["candidate_id"],
            "signal_id": rec.decision_lineage["signal_id"],
        }
        for rec in recommendations
    ]


def _sets(treatment: TradeRecommendation, controls: list[TradeRecommendation], rejected: list[dict[str, object]]):
    recommendations = [treatment, *controls]
    gates = _gates(*recommendations)
    return build_comparable_control_sets(
        cycle_id="cycle-1",
        recommendations=recommendations,
        plans=[_plan(treatment)],
        rejected_order_plans=rejected,
        all_recommendations=recommendations,
        deterministic_review=gates,
        adversarial_review=gates,
        entry_quality_gate=gates,
        backtest_gate=gates,
        strategy_pause_gate=gates,
        geometry_gate=gates,
        risk_eligibility_gate=gates,
        duplicate_symbol_gate=gates,
        already_held_gate=gates,
        low_sample_gate=gates,
    )


def test_final_plans_are_the_only_treatments_and_rank_does_not_create_control():
    treatment = _rec("TREAT", 1)
    alternative = _rec("ALT", 2)
    sets = _sets(treatment, [alternative], [])
    assert len(sets) == 1
    assert next(iter(sets.values()))["status"] == "unavailable"
    sets = _sets(treatment, [alternative], [{"symbol": "ALT", "reason": "max_orders_per_cycle_reached"}])
    item = next(iter(sets.values()))
    assert {item["treatment"]["signal_id"]} == {treatment.decision_lineage["signal_id"]}
    assert item["controls"][0]["signal_id"] == alternative.decision_lineage["signal_id"]


def test_plan_without_recommendation_gets_explicit_unavailable_set():
    sets = build_comparable_control_sets(
        cycle_id="cycle-1",
        recommendations=[],
        plans=[{"plan_id": "plan-1", "symbol": "AAPL", "side": "buy", "recommendation": None}],
    )
    item = next(iter(sets.values()))
    assert item["status"] == "unavailable"
    assert item["unavailable_reason"] == "treatment_identity_unavailable"
    assert item["treatment"]["plan_id"] == "plan-1"


def test_real_capacity_reason_is_required_and_free_text_is_unknown():
    treatment = _rec("TREAT", 1)
    capacity = _rec("CAP", 2)
    free_text = _rec("TEXT", 3)
    real = _sets(treatment, [capacity], [{"symbol": "CAP", "reason": "max_orders_per_cycle_reached"}])
    assert real[next(iter(real))]["controls"][0]["non_execution_reason"] == "capacity_limit"
    unknown = _sets(treatment, [free_text], [{"symbol": "TEXT", "reason": "quedó fuera por una preferencia"}])
    item = next(iter(unknown.values()))
    assert item["controls"] == []
    assert item["ineligible_candidates"][0]["reason"] == "unknown"


def test_final_plan_filters_are_not_primary_controls():
    treatment = _rec("TREAT", 1)
    for reason in ("max_daily_buy_orders_reached", "low_sample_daily_quota_exhausted", "strategy_paused_shadow_active", "risk_blocked"):
        alt = _rec(reason[:4].upper(), 2)
        item = next(iter(_sets(treatment, [alt], [{"symbol": alt.symbol, "reason": reason}]).values()))
        assert item["controls"] == []
        assert item["blocked_candidates"] or item["ineligible_candidates"]


def test_gate_identity_weak_never_verifies():
    treatment = _rec("TREAT", 1)
    control = _rec("CTRL", 2)
    weak_rows = [{"symbol": item.symbol, "action": "buy", "approved": True} for item in (treatment, control)]
    item = next(
        iter(
            build_comparable_control_sets(
                cycle_id="cycle-1",
                recommendations=[treatment, control],
                plans=[_plan(treatment)],
                rejected_order_plans=[{"symbol": "CTRL", "reason": "max_orders_per_cycle_reached"}],
                all_recommendations=[treatment, control],
                deterministic_review=weak_rows,
                adversarial_review=weak_rows,
                entry_quality_gate=weak_rows,
                backtest_gate=weak_rows,
            ).values()
        )
    )
    assert item["status"] == "partially_comparable"
    assert item["controls"][0]["gate_ledger"][0]["gate_link_status"] == "weak"


def test_signal_attachment_is_single_and_does_not_change_decision(tmp_path):
    settings = Settings(DATA_DIR=tmp_path, DATABASE_PATH=tmp_path / "state.sqlite3", AGENT_LOGS_DIR=tmp_path / "logs")
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    treatment = _rec("TREAT", 1)
    control = _rec("CTRL", 2)
    item = next(iter(_sets(treatment, [control], [{"symbol": "CTRL", "reason": "max_orders_per_cycle_reached"}]).values()))
    store.save_signal_outcome(
        signal_id=treatment.decision_lineage["signal_id"],
        source_run_id="run-1",
        source="learning_experiment",
        symbol="TREAT",
        signal_date="2026-07-12",
        decision="approved_buy",
        features={},
    )
    rec = replace(treatment, comparable_control_set=item)
    assert attach_comparable_control_sets(store, recommendations=[rec]) == {"attached": 1, "idempotent": 0, "conflict": 0, "unavailable": 0}
    assert attach_comparable_control_sets(store, recommendations=[rec]) == {"attached": 0, "idempotent": 1, "conflict": 0, "unavailable": 0}
    assert store.signal_outcome_by_id(treatment.decision_lineage["signal_id"])["decision"] == "approved_buy"


def test_v1_is_legacy_in_digest_without_rewrite(tmp_path):
    settings = Settings(DATA_DIR=tmp_path, DATABASE_PATH=tmp_path / "state.sqlite3", AGENT_LOGS_DIR=tmp_path / "logs")
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    treatment = _rec("TREAT", 1)
    item = next(iter(_sets(treatment, [], []).values()))
    item = dict(item)
    item["schema_version"] = LEGACY_SCHEMA_VERSION
    item.pop("selection_source", None)
    item["content_hash"] = hashlib.sha256(
        json.dumps({key: value for key, value in item.items() if key not in {"captured_at", "content_hash"}}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:32]
    store.save_trade_recommendation(
        recommendation_id="legacy-rec",
        cycle_id="cycle-1",
        symbol="TREAT",
        action="buy",
        confidence=0.9,
        payload={"comparable_control_set": item},
    )
    quality = build_comparable_control_quality(store)
    assert quality["legacy_v1_prospective_selection"] == 1
    assert quality["treatments_total_new"] == 0
    assert quality["schema_version"] == SCHEMA_VERSION
