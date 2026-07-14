from __future__ import annotations

import copy
import json
from dataclasses import asdict
from types import SimpleNamespace

from agente_bolsa.cycle_runner import _decision_context_snapshot_for_recommendation
from agente_bolsa.models import TradeRecommendation
from agente_bolsa.scheduler import _compact_scan_context
from agente_bolsa.storage import Store
from agente_bolsa.tools.comparable_controls import build_comparable_control_sets
from agente_bolsa.tools.decision_lineage import build_decision_lineage
from agente_bolsa.tools.gate_evaluation import collect_gate_path
from agente_bolsa.tools.signal_identity import (
    build_signal_capture,
    merge_signal_identity_blocks,
    resolve_signal_capture,
    signal_identity_block,
)
from agente_bolsa.tools.signal_learning import record_signal_candidates


def _store(tmp_path):
    store = Store(tmp_path / "state" / "test.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    return store


def _candidate(strategy: str = "builtin_breakout", *, candidate_id: str | None = None) -> dict:
    item = {
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
    }
    if candidate_id:
        item["candidate_id"] = candidate_id
    return item


def _report(run_id: str, candidates: list[dict]) -> dict:
    return {
        "run_id": run_id,
        "as_of": "2026-07-13T20:00:00+00:00",
        "all_candidates": copy.deepcopy(candidates),
        "selected_candidates": copy.deepcopy(candidates),
        "top_longs": copy.deepcopy(candidates),
        "top_shorts": [],
        "symbols_scanned": len(candidates),
        "symbols_with_data": len(candidates),
        "analysis_plan_counts": {},
        "warnings": [],
    }


def _recommendation(lineage: dict) -> TradeRecommendation:
    return TradeRecommendation(
        symbol="FDS",
        action="buy",
        confidence=0.8,
        reason="contract test",
        source="deterministic",
        strategy_name="builtin_breakout",
        entry_price=100.0,
        stop_loss=90.0,
        take_profit=120.0,
        decision_lineage=lineage,
    )


def test_capture_id_is_stable_and_two_source_runs_are_distinct():
    candidate = _candidate()
    first = build_signal_capture(candidate | {"signal_id": "sig-1"}, source_run_id="run-A", captured_at="2026-07-13T20:00:00+00:00")
    same = build_signal_capture(candidate | {"signal_id": "sig-1"}, source_run_id="run-A", captured_at="2026-07-13T20:01:00+00:00")
    second = build_signal_capture(candidate | {"signal_id": "sig-1"}, source_run_id="run-B", captured_at="2026-07-13T20:00:00+00:00")
    assert first and same and second
    assert first["signal_capture_id"] == same["signal_capture_id"]
    assert first["content_hash"] == same["content_hash"]
    assert first["signal_capture_id"] != second["signal_capture_id"]


def test_incomplete_producer_identity_does_not_fabricate_capture_or_unknown():
    missing_source = build_signal_capture(
        _candidate() | {"signal_id": "sig-1"},
        source_run_id=None,
        captured_at="2026-07-13T20:00:00+00:00",
    )
    missing_date = build_signal_capture(
        _candidate() | {"signal_id": "sig-1", "last_date": None, "technical_state": {}},
        source_run_id="run-A",
        captured_at="2026-07-13T20:00:00+00:00",
    )
    assert missing_source is None
    assert missing_date is None
    assert "UNKNOWN" not in str(missing_source).upper()


def test_merge_is_idempotent_and_conflict_preserves_original_capture():
    capture = build_signal_capture(_candidate() | {"signal_id": "sig-1"}, source_run_id="run-A", captured_at="2026-07-13T20:00:00+00:00")
    assert capture
    block = signal_identity_block(capture)
    merged, status = merge_signal_identity_blocks(None, block)
    assert status == "attached"
    repeated, status = merge_signal_identity_blocks(merged, block)
    assert status == "idempotent"
    assert repeated["captures"] == merged["captures"]

    conflicting = copy.deepcopy(capture)
    conflicting["symbol"] = "OTHER"
    conflicting["content_hash"] = "different"
    conflict_block = signal_identity_block(conflicting)
    final, status = merge_signal_identity_blocks(merged, conflict_block)
    assert status == "conflict"
    assert final["captures"][capture["signal_capture_id"]]["symbol"] == "FDS"
    assert final["conflicts"]
    repeated, status = merge_signal_identity_blocks(final, conflict_block)
    assert status == "conflict"
    assert repeated["conflicts"] == final["conflicts"]


def test_legacy_row_resolves_as_legacy_without_capture_history(tmp_path):
    store = _store(tmp_path)
    store.save_signal_outcome(
        signal_id="legacy-signal",
        source_run_id="legacy-run",
        source="legacy",
        symbol="FDS",
        signal_date="2026-07-13",
        decision="candidate",
        features={"strategy_name": "builtin_breakout", "strategy_version": "v1"},
    )
    result = resolve_signal_capture(store, "capture_not_in_legacy", signal_id="legacy-signal")
    assert result["status"] == "legacy_without_capture_history"


def test_deep_copies_keep_all_identity_fields_after_producer(tmp_path):
    store = _store(tmp_path)
    report = _report("run-A", [_candidate(candidate_id="cand-cycle-A")])
    assert len({id(report[name][0]) for name in ("all_candidates", "selected_candidates", "top_longs")}) == 3
    assert record_signal_candidates(store, report, source="learning_experiment") == 1
    expected = {
        "signal_id": "learning_experiment:2026-07-13:BUILTIN_BREAKOUT:FDS",
        "signal_source_run_id": "run-A",
        "candidate_id": "cand-cycle-A",
        "signal_date": "2026-07-13",
        "signal_strategy_name": "builtin_breakout",
        "signal_strategy_version": "v1",
    }
    for bucket in ("all_candidates", "selected_candidates", "top_longs"):
        assert {key: report[bucket][0].get(key) for key in expected} == expected
    compact = _compact_scan_context(report, report["selected_candidates"])
    for bucket in ("selected_candidates", "top_longs"):
        assert {key: compact[bucket][0].get(key) for key in ("signal_id", "signal_capture_id", "signal_source_run_id", "candidate_id", "signal_date")} == {
            "signal_id": expected["signal_id"],
            "signal_capture_id": report[bucket][0]["signal_capture_id"],
            "signal_source_run_id": expected["signal_source_run_id"],
            "candidate_id": expected["candidate_id"],
            "signal_date": expected["signal_date"],
        }


def test_ambiguous_duplicate_identity_is_unavailable_without_unknown(tmp_path):
    store = _store(tmp_path)
    duplicate = _candidate()
    report = _report("run-A", [copy.deepcopy(duplicate), copy.deepcopy(duplicate)])
    assert record_signal_candidates(store, report, source="learning_experiment") == 2
    assert all(item.get("signal_identity_status") == "ambiguous" for item in report["all_candidates"])
    assert all(item.get("signal_capture_id") is None for item in report["all_candidates"])
    rows = store.signal_outcomes(include_learning_experiment=True)
    assert all("UNKNOWN" not in str(row["features"]).upper() for row in rows)


def test_capture_identity_propagates_through_context_gate_control_plan_and_broker(tmp_path):
    store = _store(tmp_path)
    report = _report("source-run-A", [_candidate(candidate_id="cand-cycle-A")])
    record_signal_candidates(store, report, source="learning_experiment")
    candidate = report["selected_candidates"][0]
    compact = _compact_scan_context(report, [candidate])
    lineage = build_decision_lineage(
        _recommendation({}),
        compact,
        cycle_id="cycle-A",
        policy_version="test",
        source_run_id="cycle-A",
    )
    # The recommendation object is rebuilt with the producer lineage, not a
    # symbol/date lookup.
    recommendation = _recommendation(lineage)
    context = _decision_context_snapshot_for_recommendation(
        store,
        recommendation,
        cycle_id="cycle-A",
        source_run_id="cycle-A",
        market_state={
            "run_id": "cycle-A",
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
    assert context["signal_capture_id"] == lineage["signal_capture_id"]
    assert context["signal_link_status"] == "verified"

    gate = collect_gate_path(
        cycle_id="cycle-A",
        candidates=[recommendation],
        stage_rows={},
        final_plans=[SimpleNamespace(recommendation=recommendation)],
        captured_at="2026-07-13T20:01:00+00:00",
    )[lineage["candidate_id"]]
    assert gate["signal_capture_id"] == lineage["signal_capture_id"]

    plan_dict = {
        "plan_id": "plan-A",
        "symbol": "FDS",
        "side": "buy",
        "recommendation": recommendation,
    }
    control = build_comparable_control_sets(
        cycle_id="cycle-A",
        recommendations=[recommendation],
        plans=[plan_dict],
    )[lineage["signal_id"]]
    assert control["treatment"]["signal_capture_id"] == lineage["signal_capture_id"]

    store.save_trade_recommendation(
        recommendation_id="rec-A",
        cycle_id="cycle-A",
        symbol="FDS",
        action="buy",
        confidence=0.8,
        payload={**asdict(recommendation), "decision_lineage": lineage},
    )
    store.save_order_plan(
        plan_id="plan-A",
        cycle_id="cycle-A",
        symbol="FDS",
        side="buy",
        notional=100.0,
        approved=True,
        dry_run=True,
        payload={
            "recommendation": {**asdict(recommendation), "decision_lineage": lineage},
            "decision_lineage": lineage,
            "entry_price": 100.0,
            "stop_loss": 90.0,
            "take_profit": 120.0,
            "qty": 1.0,
            "recommendation_id": "rec-A",
        },
    )
    plan = store.order_plans(cycle_id="cycle-A")[0]
    assert plan["payload"]["execution_quality_snapshot"]["signal_capture_id"] == lineage["signal_capture_id"]
    signal_row = store.signal_outcome_by_id(lineage["signal_id"])
    assert signal_row
    store.upsert_learning_observation(
        {
            "observation_id": "obs-A",
            "signal_date": signal_row["signal_date"],
            "symbol": signal_row["symbol"],
            "source_family": "learning_experiment",
            "source_run_ids": [lineage["signal_source_run_id"]],
            "best_signal_id": lineage["signal_id"],
            "decision": "candidate",
            "features": signal_row["features"],
        }
    )
    observation = store.learning_observations(limit=1)[0]
    assert observation["features"]["signal_identity"]["latest_signal_capture_id"] == lineage["signal_capture_id"]
    store.save_broker_order(
        broker_order_id="broker-A",
        plan_id="plan-A",
        cycle_id="cycle-A",
        symbol="FDS",
        side="buy",
        status="submitted",
        payload={
            "plan": plan,
            "broker_order": {"id": "broker-A", "client_order_id": "client-A", "status": "submitted", "qty": "1"},
        },
    )
    with store.connect() as conn:
        broker_row = conn.execute(
            "SELECT payload_json FROM broker_orders WHERE broker_order_id = ?",
            ("broker-A",),
        ).fetchone()
    assert broker_row
    broker_payload = json.loads(broker_row["payload_json"])
    assert broker_payload["execution_quality_snapshot"]["signal_capture_id"] == lineage["signal_capture_id"]
