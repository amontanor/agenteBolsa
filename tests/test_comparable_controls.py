from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone

from agente_bolsa.config import Settings
from agente_bolsa.models import OrderPlan, RiskDecision, TradeRecommendation
from agente_bolsa.storage import Store
from agente_bolsa.tools.comparable_controls import (
    SCHEMA_VERSION,
    build_comparable_control_quality,
    build_comparable_control_sets,
    candidate_id_for,
    comparable_control_evaluation_status,
    derive_comparable_control_outcomes,
    merge_comparable_control_set,
    validate_comparable_control_set,
)
from agente_bolsa.tools.decision_context import build_decision_context_snapshot
from agente_bolsa.tools.signal_learning import update_signal_decisions


def _market_state(cycle_id: str = "cycle-1") -> dict[str, object]:
    return {
        "run_id": cycle_id,
        "as_of": "2026-07-12T09:00:00+00:00",
        "prompt_version": "market_state.v2",
        "market_regime": "neutral",
        "volatility_regime": "normal",
        "risk_posture": "balanced",
        "data_quality": {"status": "GOOD"},
    }


def _recommendation(symbol: str, rank: int, *, cycle_id: str = "cycle-1") -> TradeRecommendation:
    signal_id = f"learning_experiment:2026-07-12:SETUP:{symbol}"
    rec = TradeRecommendation(
        symbol=symbol,
        action="buy",
        confidence=0.8,
        reason="measured candidate",
        entry_price=100.0 + rank,
        stop_loss=95.0 + rank,
        take_profit=115.0 + rank,
        source="llm",
        decision_lineage={
            "signal_id": signal_id,
            "cycle_id": cycle_id,
            "candidate_id": candidate_id_for(cycle_id, signal_id, "scan-1"),
            "candidate_rank": rank,
        },
    )
    snapshot = build_decision_context_snapshot(
        rec,
        cycle_id=cycle_id,
        source_run_id="scan-1",
        market_state=_market_state(cycle_id),
        captured_at=datetime(2026, 7, 12, 10, tzinfo=timezone.utc),
        signal_id=signal_id,
        signal_link_status="unavailable",
        identity_key=f"{cycle_id}|{symbol}",
    )
    return TradeRecommendation(**{**rec.__dict__, "decision_context_snapshot": snapshot})


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


def _sets(*, count: int = 3) -> dict[str, dict[str, object]]:
    treatment = _recommendation("TREAT", 1)
    controls = [_recommendation(f"CTRL{index}", index + 2) for index in range(count)]
    recommendations = [treatment, *controls]
    rejected = [
        {"symbol": item.symbol, "action": "buy", "stage": "cycle_order_limit", "reason": "max_orders_per_cycle_reached"}
        for item in controls
    ]
    gate_rows = [
        {"symbol": item.symbol, "action": "buy", "approved": True, "checks": {"observed_value": 1, "threshold": 0}}
        for item in recommendations
    ]
    return build_comparable_control_sets(
        cycle_id="cycle-1",
        recommendations=recommendations,
        plans=[],
        selected_recommendations=[treatment],
        rejected_order_plans=rejected,
        all_recommendations=recommendations,
        deterministic_review=gate_rows,
        adversarial_review=gate_rows,
        entry_quality_gate=gate_rows,
        backtest_gate=gate_rows,
        strategy_pause_gate=gate_rows,
        geometry_gate=gate_rows,
        risk_eligibility_gate=gate_rows,
        duplicate_symbol_gate=gate_rows,
        already_held_gate=gate_rows,
        low_sample_gate=gate_rows,
    )


def test_candidate_id_is_deterministic_and_cycle_scoped():
    first = candidate_id_for("cycle-1", "signal-1", "scan-1")
    assert first == candidate_id_for("cycle-1", "signal-1", "scan-1")
    assert first != candidate_id_for("cycle-2", "signal-1", "scan-1")
    assert first != candidate_id_for("cycle-1", "signal-1", "scan-2")
    assert first == candidate_id_for("cycle-1", "signal-1", "scan-1")
    assert candidate_id_for(None, "signal-1") is None
    assert candidate_id_for("cycle-1", None) is None


def test_same_cycle_control_set_is_verified_and_capped():
    sets = _sets(count=4)
    assert len(sets) == 1
    item = next(iter(sets.values()))
    assert item["schema_version"] == SCHEMA_VERSION
    assert item["status"] == "verified"
    assert len(item["controls"]) == 3
    assert item["eligible_controls_omitted"] == 1
    assert all(control["non_execution_reason"] == "capacity_limit" for control in item["controls"])
    assert all(control["gate_eligibility"] == "verified" for control in item["controls"])
    validate_comparable_control_set(item)


def test_rank_and_score_do_not_change_candidate_id():
    first = candidate_id_for("cycle-1", "signal-1", "scan-1")
    assert first == candidate_id_for("cycle-1", "signal-1", "scan-1")


def test_blocked_candidates_are_not_controls():
    treatment = _recommendation("TREAT", 1)
    blocked = _recommendation("BLOCKED", 2)
    sets = build_comparable_control_sets(
        cycle_id="cycle-1",
        recommendations=[treatment, blocked],
        plans=[_plan(treatment)],
        rejected_order_plans=[{"symbol": "BLOCKED", "reason": "gate_blocked", "stage": "entry_quality_gate"}],
        all_recommendations=[treatment, blocked],
    )
    item = next(iter(sets.values()))
    assert item["controls"] == []
    assert item["blocked_candidates"][0]["blocked_reason"] == "gate_blocked"
    assert item["status"] == "unavailable"


def test_different_cycle_is_not_used_as_control():
    treatment = _recommendation("TREAT", 1)
    other = _recommendation("OTHER", 2, cycle_id="cycle-2")
    sets = build_comparable_control_sets(
        cycle_id="cycle-1",
        recommendations=[treatment, other],
        plans=[_plan(treatment)],
        rejected_order_plans=[{"symbol": "OTHER", "reason": "capacity_limit"}],
        all_recommendations=[treatment, other],
    )
    assert next(iter(sets.values()))["controls"] == []


def test_idempotent_merge_and_conflict():
    item = next(iter(_sets().values()))
    assert merge_comparable_control_set(None, item) == "attached"
    assert merge_comparable_control_set(item, item) == "idempotent"
    changed = dict(item)
    changed["eligible_controls_omitted"] = 1
    payload = {key: value for key, value in changed.items() if key not in {"captured_at", "content_hash"}}
    changed["content_hash"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:32]
    assert merge_comparable_control_set(item, changed) == "conflict"


def test_quality_digest_is_collecting_without_new_sets(tmp_path):
    settings = Settings(DATA_DIR=tmp_path, DATABASE_PATH=tmp_path / "state.sqlite3", AGENT_LOGS_DIR=tmp_path / "logs")
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    quality = build_comparable_control_quality(store)
    assert quality["schema_version"] == SCHEMA_VERSION
    assert quality["status"] == "collecting"
    assert quality["average_controls_per_treatment"] is None


def test_quality_digest_counts_verified_sets(tmp_path):
    settings = Settings(DATA_DIR=tmp_path, DATABASE_PATH=tmp_path / "state.sqlite3", AGENT_LOGS_DIR=tmp_path / "logs")
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    item = next(iter(_sets().values()))
    store.save_trade_recommendation(
        recommendation_id="rec-1",
        cycle_id="cycle-1",
        symbol="TREAT",
        action="buy",
        confidence=0.8,
        payload={"comparable_control_set": item},
    )
    quality = build_comparable_control_quality(store)
    assert quality["treatments_total_new"] == 1
    assert quality["verified_control_sets"] == 1
    assert quality["primary_controls"] == 3
    assert quality["same_cycle_coverage"] == 1.0


def test_gate_ledger_is_complete_and_ordered():
    item = next(iter(_sets().values()))
    names = [row["gate_name"] for row in item["controls"][0]["gate_ledger"]]
    assert names == [
        "deterministic_review",
        "adversarial_review",
        "entry_quality",
        "backtest",
        "strategy_pause",
        "geometry",
        "risk_eligibility",
        "duplicate_symbol",
        "already_held",
        "low_sample",
        "daily_capacity",
    ]


def test_missing_gate_is_partial_not_verified():
    treatment = _recommendation("TREAT", 1)
    control = _recommendation("CTRL", 2)
    passed = [{"symbol": item, "action": "buy", "approved": True} for item in ("TREAT", "CTRL")]
    sets = build_comparable_control_sets(
        cycle_id="cycle-1",
        recommendations=[treatment, control],
        selected_recommendations=[treatment],
        plans=[],
        rejected_order_plans=[{"symbol": "CTRL", "reason": "capacity_limit"}],
        all_recommendations=[treatment, control],
        deterministic_review=passed,
        adversarial_review=passed,
        entry_quality_gate=passed,
        backtest_gate=passed,
    )
    item = next(iter(sets.values()))
    assert item["status"] == "partially_comparable"
    assert item["controls"][0]["gate_eligibility"] == "partial"


def test_market_hash_mismatch_is_not_a_primary_control():
    treatment = _recommendation("TREAT", 1)
    control = _recommendation("CTRL", 2)
    altered = dict(control.decision_context_snapshot)
    altered["market_state_ref"] = {**altered["market_state_ref"], "content_hash": "different"}
    altered["content_hash"] = hashlib.sha256(
        json.dumps({key: value for key, value in altered.items() if key not in {"captured_at", "content_hash"}}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:32]
    control = TradeRecommendation(**{**control.__dict__, "decision_context_snapshot": altered})
    sets = build_comparable_control_sets(
        cycle_id="cycle-1",
        recommendations=[treatment, control],
        selected_recommendations=[treatment],
        plans=[],
        rejected_order_plans=[{"symbol": "CTRL", "reason": "capacity_limit"}],
        all_recommendations=[treatment, control],
    )
    assert next(iter(sets.values()))["controls"] == []


def test_control_is_not_reused_across_treatments():
    first = _recommendation("TREAT1", 1)
    second = _recommendation("TREAT2", 2)
    shared = _recommendation("CTRL", 3)
    gates = [
        {"symbol": item.symbol, "action": "buy", "approved": True}
        for item in (first, second, shared)
    ]
    sets = build_comparable_control_sets(
        cycle_id="cycle-1",
        recommendations=[first, second, shared],
        selected_recommendations=[first, second],
        plans=[],
        rejected_order_plans=[{"symbol": "CTRL", "reason": "capacity_limit"}],
        all_recommendations=[first, second, shared],
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
    assert sum(len(item["controls"]) for item in sets.values()) == 1


def test_unavailable_set_does_not_invent_identity():
    rec = TradeRecommendation(symbol="TREAT", action="buy", confidence=0.8, reason="missing identity", entry_price=100.0)
    item = next(
        iter(
            build_comparable_control_sets(
                cycle_id="",
                recommendations=[rec],
                selected_recommendations=[rec],
                plans=[],
                all_recommendations=[rec],
            ).values()
        )
    )
    assert item["status"] == "unavailable"
    assert item["treatment"]["signal_id"] is None
    validate_comparable_control_set(item)


def test_post_decision_payload_and_wrong_horizon_are_rejected():
    item = next(iter(_sets().values()))
    polluted = dict(item)
    polluted["outcome"] = {"return_10d": 0.1}
    polluted["content_hash"] = hashlib.sha256(
        json.dumps({key: value for key, value in polluted.items() if key not in {"captured_at", "content_hash"}}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:32]
    try:
        validate_comparable_control_set(polluted)
    except ValueError as exc:
        assert "post_decision" in str(exc)
    else:
        raise AssertionError("post-decision fields must be rejected")
    treatment = _recommendation("TREAT", 1)
    try:
        build_comparable_control_sets(
            cycle_id="cycle-1", recommendations=[treatment], selected_recommendations=[treatment], plans=[], forward_horizon="5d"
        )
    except ValueError as exc:
        assert str(exc) == "comparable_control_horizon_invalid"
    else:
        raise AssertionError("wrong horizon must be rejected")


def test_outcome_view_resolves_exact_ids_without_mutating_capture(tmp_path):
    settings = Settings(DATA_DIR=tmp_path, DATABASE_PATH=tmp_path / "state.sqlite3", AGENT_LOGS_DIR=tmp_path / "logs")
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    item = next(iter(_sets(count=1).values()))
    treatment_id = item["treatment"]["signal_id"]
    control_id = item["controls"][0]["signal_id"]
    for signal_id in (treatment_id, control_id):
        store.save_signal_outcome(
            signal_id=signal_id,
            source_run_id="scan-1",
            source="learning_experiment",
            symbol="TREAT" if signal_id == treatment_id else "CTRL0",
            signal_date="2026-07-12",
            decision="approved_buy",
            features={},
            outcome={"matured_horizons": {"10d": True}, "return_10d": 0.1},
        )
    view = derive_comparable_control_outcomes(store, item)
    assert view["treatment"]["status"] == "evaluable"
    assert view["controls"][0]["status"] == "evaluable"
    assert "return_10d" not in item
    assert comparable_control_evaluation_status(item, view, min_sample=3) == "insufficient_sample"


def test_control_set_propagates_to_plan_and_verified_signal_only(tmp_path):
    settings = Settings(DATA_DIR=tmp_path, DATABASE_PATH=tmp_path / "state.sqlite3", AGENT_LOGS_DIR=tmp_path / "logs")
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    item = next(iter(_sets(count=1).values()))
    treatment = _recommendation("TREAT", 1)
    verified_snapshot = {**treatment.decision_context_snapshot, "signal_link_status": "verified"}
    verified_snapshot["content_hash"] = hashlib.sha256(
        json.dumps({key: value for key, value in verified_snapshot.items() if key not in {"captured_at", "content_hash"}}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:32]
    treatment = replace(
        treatment,
        decision_context_snapshot=verified_snapshot,
        comparable_control_set=item,
    )
    store.save_signal_outcome(
        signal_id=item["treatment"]["signal_id"],
        source_run_id="scan-1",
        source="learning_experiment",
        symbol="TREAT",
        signal_date="2026-07-12",
        decision="approved_buy",
        features={},
    )
    update_signal_decisions(
        store,
        source_run_id="scan-1",
        recommendations=[treatment],
        entry_quality_gate=[],
        backtest_gate=[],
        settings=settings,
    )
    row = store.signal_outcome_by_id(item["treatment"]["signal_id"])
    assert row["features"]["comparable_control_set"]["content_hash"] == item["content_hash"]
    plan = _plan(treatment)
    assert plan.recommendation.comparable_control_set["content_hash"] == item["content_hash"]

    broken = replace(treatment, decision_context_snapshot={**verified_snapshot, "signal_link_status": "broken"})
    broken_snapshot = dict(broken.decision_context_snapshot)
    broken_snapshot["content_hash"] = hashlib.sha256(
        json.dumps({key: value for key, value in broken_snapshot.items() if key not in {"captured_at", "content_hash"}}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:32]
    broken = replace(broken, decision_context_snapshot=broken_snapshot)
    store.save_signal_outcome(
        signal_id="learning_experiment:2026-07-12:SETUP:BROKEN",
        source_run_id="scan-1",
        source="learning_experiment",
        symbol="BROKEN",
        signal_date="2026-07-12",
        decision="approved_buy",
        features={},
    )
    broken_lineage = {**broken.decision_lineage, "signal_id": "learning_experiment:2026-07-12:SETUP:BROKEN"}
    broken = replace(broken, decision_lineage=broken_lineage)
    update_signal_decisions(
        store,
        source_run_id="scan-1",
        recommendations=[broken],
        entry_quality_gate=[],
        backtest_gate=[],
        settings=settings,
    )
    broken_row = store.signal_outcome_by_id("learning_experiment:2026-07-12:SETUP:BROKEN")
    assert "comparable_control_set" not in broken_row["features"]


def test_cli_parser_exposes_read_only_quality_command():
    from agente_bolsa.main import build_parser

    args = build_parser().parse_args(["comparable-control-quality", "--json", "--from", "2026-07-01"])
    assert args.func.__name__ == "command_comparable_control_quality"
    assert args.start == "2026-07-01"
    assert args.end is None
