from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.cycle_runner import _rejection_payload_for_plan
from agente_bolsa.models import OrderPlan, RiskDecision, TradeRecommendation
from agente_bolsa.storage import Store
from agente_bolsa.tools.comparable_controls import (
    build_comparable_control_sets,
    candidate_id_for,
    validate_comparable_control_set,
)
from agente_bolsa.tools.daily_learning import _materialize_observations
from agente_bolsa.tools.decision_context import build_decision_context_snapshot
from agente_bolsa.tools.learning_scoreboard import _cohort_rows
from agente_bolsa.tools.signal_learning import (
    update_signal_decisions,
    update_signal_execution_status,
)

_FILL_WATCH_ENV_KEYS = (
    "TRADE_FILL_WATCH_ENABLED",
    "TRADE_FILL_WATCH_CADENCE_SECONDS",
    "TRADE_FILL_WATCH_MAX_PENDING_PER_RUN",
    "TRADE_FILL_WATCH_REQUEST_TIMEOUT_SECONDS",
    "TRADE_FILL_WATCH_BACKOFF_SECONDS",
    "TRADE_FILL_WATCH_MAX_BACKOFF_SECONDS",
)


def _store(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    return store


def _isolated_settings(tmp_path, monkeypatch):
    for key in _FILL_WATCH_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    return Settings(_env_file=None, DATA_DIR=tmp_path)


def _recommendation(signal_id: str, symbol: str) -> SimpleNamespace:
    return SimpleNamespace(
        symbol=symbol,
        action="buy",
        confidence=0.8,
        reason="contract fixture",
        micro_experiment=False,
        source="deterministic_fixture",
        decision_origin="fixture",
        capacity_fill_reason_code=None,
        tags=[],
        soft_override_reasons=[],
        comparable_control_set={},
        decision_context_snapshot={},
        decision_lineage={
            "signal_id": signal_id,
            "signal_source_run_id": "cycle-1",
            "cycle_id": "cycle-1",
            "lineage_status": "verified",
        },
    )


def _save_signal(
    store: Store,
    *,
    signal_id: str,
    symbol: str,
    signal_date: str = "2026-08-03",
    source_run_id: str = "cycle-1",
    decision: str = "approved_buy",
    gate: dict | None = None,
    score: float = 0.8,
) -> None:
    store.save_signal_outcome(
        signal_id=signal_id,
        source_run_id=source_run_id,
        source="learning_experiment",
        symbol=symbol,
        signal_date=signal_date,
        decision=decision,
        features={
            "score": score,
            "selection_rank": 1,
            "decision_lineage": {
                "signal_id": signal_id,
                "signal_source_run_id": source_run_id,
                "cycle_id": source_run_id,
                "candidate_rank": 1,
                "lineage_status": "verified",
            },
        },
        gate=gate or {},
    )


def _raw_observation(
    row: dict,
    *,
    executed: bool,
    verified_control_ids=(),
    comparable_control_set: dict | None = None,
) -> dict:
    features = dict(row["features"])
    if comparable_control_set is not None:
        features["comparable_control_set"] = comparable_control_set
    elif verified_control_ids:
        # Fixture explícito de comparabilidad; capacidad por sí sola no basta.
        features["comparable_control_set"] = {
            "status": "verified",
            "cycle_id": row["features"]["decision_lineage"]["cycle_id"],
            "treatment": {"signal_id": row["signal_id"]},
            "controls": [{"signal_id": control_id, "gate_eligibility": "verified"}
                         for control_id in verified_control_ids],
        }
    return {
        "signal_id": row["signal_id"],
        "source_run_id": row["source_run_id"],
        "source": row["source"],
        "symbol": row["symbol"],
        "signal_date": row["signal_date"],
        "decision": row["decision"],
        "features": features,
        "gate": row["gate"],
        "outcome": {},
        "score": row["features"].get("score"),
        "considered_by_llm": False,
        "executed_buy": executed,
        "orders_same_day": int(executed),
        "created_at": "2026-08-03T13:30:00+00:00",
    }


def _canonical_market_state(cycle_id: str = "cycle-1") -> dict[str, object]:
    return {
        "run_id": cycle_id,
        "as_of": "2026-08-03T13:30:00+00:00",
        "prompt_version": "market_state.v2",
        "market_regime": "neutral",
        "volatility_regime": "normal",
        "risk_posture": "balanced",
        "data_quality": {"status": "GOOD"},
    }


def _canonical_recommendation(
    symbol: str,
    rank: int,
    *,
    cycle_id: str = "cycle-1",
    signal_date: str = "2026-08-03",
) -> TradeRecommendation:
    signal_id = f"learning_experiment:{signal_date}:CONTROL_CONTRACT:{symbol}"
    recommendation = TradeRecommendation(
        symbol=symbol,
        action="buy",
        confidence=0.8,
        reason="contract fixture",
        entry_price=100.0 + rank,
        stop_loss=95.0 + rank,
        take_profit=115.0 + rank,
        source="deterministic_fixture",
        decision_lineage={
            "signal_id": signal_id,
            "cycle_id": cycle_id,
            "candidate_id": candidate_id_for(cycle_id, signal_id, "scan-1"),
            "candidate_rank": rank,
        },
    )
    snapshot = build_decision_context_snapshot(
        recommendation,
        cycle_id=cycle_id,
        source_run_id="scan-1",
        market_state=_canonical_market_state(cycle_id),
        captured_at=datetime(2026, 8, 3, 13, 30, tzinfo=timezone.utc),
        signal_id=signal_id,
        signal_link_status="verified",
        identity_key=f"{cycle_id}|{symbol}",
    )
    return replace(recommendation, decision_context_snapshot=snapshot)


def _canonical_plan(recommendation: TradeRecommendation) -> OrderPlan:
    return OrderPlan(
        symbol=recommendation.symbol,
        side="buy",
        notional=100.0,
        qty=1.0,
        entry_price=recommendation.entry_price or 0.0,
        stop_loss=recommendation.stop_loss or 0.0,
        take_profit=recommendation.take_profit or 0.0,
        recommendation=recommendation,
        risk_decision=RiskDecision(True, "ok", {}),
    )


def _canonical_verified_pair() -> tuple[TradeRecommendation, TradeRecommendation, dict]:
    treatment = _canonical_recommendation("TREATMENT", 1)
    control = _canonical_recommendation("CONTROL", 2)
    recommendations = [treatment, control]
    gate_rows = [
        {
            "symbol": item.symbol,
            "action": "buy",
            "approved": True,
            "candidate_id": item.decision_lineage.get("candidate_id"),
            "signal_id": item.decision_lineage.get("signal_id"),
            "checks": {"observed_value": 1, "threshold": 0},
        }
        for item in recommendations
    ]
    rejected = [
        {
            "symbol": control.symbol,
            "action": "buy",
            "stage": "cycle_order_limit",
            "reason": "max_orders_per_cycle_reached",
            "candidate_id": control.decision_lineage.get("candidate_id"),
            "signal_id": control.decision_lineage.get("signal_id"),
        }
    ]
    control_sets = build_comparable_control_sets(
        cycle_id="cycle-1",
        recommendations=recommendations,
        plans=[_canonical_plan(treatment)],
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
        captured_at=datetime(2026, 8, 3, 13, 30, tzinfo=timezone.utc),
    )
    control_set = control_sets[treatment.decision_lineage["signal_id"]]
    validate_comparable_control_set(control_set)
    assert control_set["status"] == "verified"
    assert [item["signal_id"] for item in control_set["controls"]] == [
        control.decision_lineage["signal_id"]
    ]
    return treatment, control, control_set


def test_execution_carrier_requires_exact_recommendation_identity(tmp_path):
    """Characterization: the base API cannot carry a signal_id to the writer.

    The production call currently accepts only approved_symbols.  This test is
    intentionally red against the P-L80A base and records the missing
    producer-to-storage contract before the implementation is added.
    """

    store = _store(tmp_path)
    signal_id = "learning_experiment:2026-08-03:BUILTIN_BREAKOUT:CONTROL"
    store.save_signal_outcome(
        signal_id=signal_id,
        source_run_id="cycle-1",
        source="learning_experiment",
        symbol="CONTROL",
        signal_date="2026-08-03",
        decision="approved_buy",
        features={
            "decision_lineage": {
                "signal_id": signal_id,
                "signal_source_run_id": "cycle-1",
                "cycle_id": "cycle-1",
                "lineage_status": "verified",
            }
        },
        gate={},
    )

    updated = update_signal_execution_status(
        store,
        source_run_id="cycle-1",
        approved_recommendations=[_recommendation(signal_id, "CONTROL")],
        cycle_id="cycle-1",
        effective_max_orders_per_cycle=1,
        effective_max_daily_buy_orders=1,
    )

    assert updated == 1
    row = store.signal_outcome_by_id(signal_id)
    assert row["gate"]["execution"]["status"] == "approved_not_planned"


def test_settings_fixture_ignores_external_fill_watch_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_FILL_WATCH_ENABLED", "true")
    settings = _isolated_settings(tmp_path, monkeypatch)

    assert settings.trade_fill_watch_enabled is False


def test_exact_signal_id_prevents_same_symbol_contamination(tmp_path, monkeypatch):
    store = _store(tmp_path)
    first_id = "learning_experiment:2026-08-03:BREAKOUT:FIRST"
    second_id = "learning_experiment:2026-08-03:BREAKOUT:SECOND"
    _save_signal(store, signal_id=first_id, symbol="SAME", decision="candidate")
    _save_signal(store, signal_id=second_id, symbol="SAME", decision="candidate")

    decision_updates = update_signal_decisions(
        store,
        source_run_id="cycle-1",
        recommendations=[_recommendation(first_id, "SAME")],
        entry_quality_gate=[{"symbol": "SAME", "approved": True}],
        backtest_gate=[{"symbol": "SAME", "approved": True}],
        settings=_isolated_settings(tmp_path, monkeypatch),
    )
    assert decision_updates == 1
    assert store.signal_outcome_by_id(first_id)["decision"] == "approved_buy"
    assert store.signal_outcome_by_id(second_id)["decision"] == "candidate"

    updated = update_signal_execution_status(
        store,
        source_run_id="cycle-1",
        approved_recommendations=[_recommendation(first_id, "SAME")],
        cycle_id="cycle-1",
        effective_max_orders_per_cycle=1,
        effective_max_daily_buy_orders=1,
    )

    assert updated == 1
    first = store.signal_outcome_by_id(first_id)
    second = store.signal_outcome_by_id(second_id)
    assert first["gate"]["execution"]["signal_id"] == first_id
    assert second["gate"] == {}


def test_capacity_rejection_carrier_is_allowlisted_and_identity_exact(tmp_path):
    store = _store(tmp_path)
    treatment_id = "learning_experiment:2026-08-03:CAPACITY:TREATMENT"
    allowlisted_id = "learning_experiment:2026-08-03:CAPACITY:ALLOWLISTED"
    rejected_id = "learning_experiment:2026-08-03:CAPACITY:NOT_ALLOWLISTED"
    _save_signal(store, signal_id=treatment_id, symbol="TREAT")
    _save_signal(store, signal_id=allowlisted_id, symbol="ALLOW")
    _save_signal(store, signal_id=rejected_id, symbol="REJECT")

    updated = update_signal_execution_status(
        store,
        source_run_id="cycle-1",
        approved_recommendations=[
            _recommendation(treatment_id, "TREAT"),
            _recommendation(allowlisted_id, "ALLOW"),
            _recommendation(rejected_id, "REJECT"),
        ],
        submitted=[{"signal_id": treatment_id, "symbol": "TREAT", "status": "accepted"}],
        rejected_order_plans=[
            {
                "signal_id": allowlisted_id,
                "symbol": "ALLOW",
                "cycle_id": "cycle-1",
                "stage": "daily_buy_limit",
                "reason": "max_daily_buy_orders_reached",
                "checks": {"effective_max_daily_buy_orders": 1},
            },
            {
                "signal_id": rejected_id,
                "symbol": "REJECT",
                "cycle_id": "cycle-1",
                "stage": "manual",
                "reason": "operator_note",
                "checks": {},
            },
        ],
        cycle_id="cycle-1",
        effective_max_orders_per_cycle=1,
        effective_max_daily_buy_orders=1,
    )
    assert updated == 3

    treatment = store.signal_outcome_by_id(treatment_id)
    allowlisted = store.signal_outcome_by_id(allowlisted_id)
    rejected = store.signal_outcome_by_id(rejected_id)
    assert treatment["decision"].startswith("approved_buy")
    assert allowlisted["decision"].startswith("approved_buy")
    assert allowlisted["gate"]["execution"] == {
        "effective_max_orders_per_cycle": 1,
        "effective_max_daily_buy_orders": 1,
        "source_run_id": "cycle-1",
        "cycle_id": "cycle-1",
        "signal_id": allowlisted_id,
        "decision_lineage": _recommendation(allowlisted_id, "ALLOW").decision_lineage,
        "status": "plan_rejected",
        "stage": "daily_buy_limit",
        "reason": "max_daily_buy_orders_reached",
        "checks": {"effective_max_daily_buy_orders": 1},
    }
    assert rejected["gate"]["execution"]["reason"] == "operator_note"

    _materialize_observations(
        store,
        [
            _raw_observation(treatment, executed=True, verified_control_ids=[allowlisted_id, rejected_id]),
            _raw_observation(allowlisted, executed=False),
            _raw_observation(rejected, executed=False),
        ],
    )
    executed, matched_controls, matches, _all_controls = _cohort_rows(
        store,
        since_date="2026-08-03",
        end_date="2026-08-03",
    )
    assert len(executed) == 1
    assert [row["symbol"] for row in matched_controls] == ["ALLOW"]
    assert matches[executed[0]["observation_id"]] == [
        "2026-08-03:ALLOW:learning_experiment"
    ]
    assert all(row["symbol"] != "REJECT" for row in matched_controls)


def test_rejection_payload_preserves_signal_and_cycle_identity_for_capacity_routes():
    plan = SimpleNamespace(
        recommendation=SimpleNamespace(
            decision_lineage={
                "signal_id": "learning_experiment:2026-08-03:CAPACITY",
                "cycle_id": "cycle-1",
            }
        )
    )
    payload = _rejection_payload_for_plan(plan, {"reason": "max_daily_buy_orders_reached"})

    assert payload["signal_id"] == "learning_experiment:2026-08-03:CAPACITY"
    assert payload["cycle_id"] == "cycle-1"


def test_carrier_materializes_and_unlocks_only_exact_same_cycle_control(tmp_path):
    store = _store(tmp_path)
    treatment_id = "learning_experiment:2026-08-03:TREATMENT"
    control_id = "learning_experiment:2026-08-03:CONTROL"
    _save_signal(store, signal_id=treatment_id, symbol="TREAT")
    _save_signal(store, signal_id=control_id, symbol="CONTROL")

    update_signal_execution_status(
        store,
        source_run_id="cycle-1",
        approved_recommendations=[
            _recommendation(treatment_id, "TREAT"),
            _recommendation(control_id, "CONTROL"),
        ],
        submitted=[
            {
                "signal_id": treatment_id,
                "symbol": "TREAT",
                "status": "accepted",
                "notional": 100.0,
            }
        ],
        planned_signal_ids=[treatment_id],
        cycle_id="cycle-1",
        effective_max_orders_per_cycle=1,
        effective_max_daily_buy_orders=1,
    )
    treatment = store.signal_outcome_by_id(treatment_id)
    control = store.signal_outcome_by_id(control_id)
    assert treatment["gate"]["execution"]["status"] == "submitted"
    assert control["gate"]["execution"]["status"] == "approved_not_planned"
    assert control["gate"]["execution"]["signal_id"] == control_id
    assert control["gate"]["execution"]["source_run_id"] == "cycle-1"

    materialized = _materialize_observations(
        store,
        [
            _raw_observation(treatment, executed=True, verified_control_ids=[control_id]),
            _raw_observation(control, executed=False),
        ],
    )
    assert {item["observation_id"] for item in materialized} == {
        "2026-08-03:TREAT:learning_experiment",
        "2026-08-03:CONTROL:learning_experiment",
    }

    executed, matched_controls, matches, _all_controls = _cohort_rows(
        store,
        since_date="2026-08-03",
        end_date="2026-08-03",
    )
    assert [row["symbol"] for row in executed] == ["TREAT"]
    assert [row["symbol"] for row in matched_controls] == ["CONTROL"]
    assert matches["2026-08-03:TREAT:learning_experiment"] == [
        "2026-08-03:CONTROL:learning_experiment"
    ]
    persisted_control = store.learning_observations(since_date="2026-08-03", end_date="2026-08-03")[0]
    assert persisted_control["gate"]["execution"]["status"] == "approved_not_planned"


def test_same_cycle_matcher_rejects_date_source_decision_and_identity_mismatches(tmp_path):
    store = _store(tmp_path)
    rows = []
    for suffix, symbol, signal_date, source_run_id, decision, execution in (
        ("DATE", "DATE", "2026-08-04", "cycle-1", "approved_buy", {"status": "approved_not_planned"}),
        ("SOURCE", "SOURCE", "2026-08-03", "cycle-2", "approved_buy", {"status": "approved_not_planned"}),
        ("REASON", "REASON", "2026-08-03", "cycle-1", "approved_buy", {"status": "plan_rejected", "reason": "manual"}),
        ("DECISION", "DECISION", "2026-08-03", "cycle-1", "candidate", {"status": "approved_not_planned"}),
    ):
        signal_id = f"learning_experiment:{signal_date}:{suffix}"
        _save_signal(
            store,
            signal_id=signal_id,
            symbol=symbol,
            signal_date=signal_date,
            source_run_id=source_run_id,
            decision=decision,
            gate={"execution": {**execution, "signal_id": signal_id}},
        )
        row = store.signal_outcome_by_id(signal_id)
        rows.append(_raw_observation(row, executed=False))

    executed_id = "learning_experiment:2026-08-03:EXECUTED"
    _save_signal(store, signal_id=executed_id, symbol="EXECUTED")
    executed_row = store.signal_outcome_by_id(executed_id)
    rows.append(_raw_observation(executed_row, executed=True))
    _materialize_observations(store, rows)

    executed, matched_controls, matches, _all_controls = _cohort_rows(
        store,
        since_date="2026-08-03",
        end_date="2026-08-04",
    )
    assert len(executed) == 1
    assert matched_controls == []
    assert matches[executed[0]["observation_id"]] == []


def test_missing_identity_is_unavailable_and_does_not_fall_back_to_symbol(tmp_path):
    store = _store(tmp_path)
    signal_id = "learning_experiment:2026-08-03:NO_ID"
    _save_signal(store, signal_id=signal_id, symbol="NOID")
    recommendation = _recommendation(signal_id, "NOID")
    recommendation.decision_lineage = {}

    updated = update_signal_execution_status(
        store,
        source_run_id="cycle-1",
        approved_recommendations=[recommendation],
        cycle_id="cycle-1",
        effective_max_orders_per_cycle=1,
        effective_max_daily_buy_orders=1,
    )

    assert updated == 0
    assert store.signal_outcome_by_id(signal_id)["gate"] == {}


def test_exact_carrier_is_idempotent_and_conflicts_are_append_only(tmp_path):
    store = _store(tmp_path)
    signal_id = "learning_experiment:2026-08-03:IDEMPOTENT"
    _save_signal(store, signal_id=signal_id, symbol="IDEMP")
    recommendation = _recommendation(signal_id, "IDEMP")
    kwargs = {
        "store": store,
        "source_run_id": "cycle-1",
        "approved_recommendations": [recommendation],
        "submitted": [{"signal_id": signal_id, "symbol": "IDEMP", "status": "accepted"}],
        "cycle_id": "cycle-1",
        "effective_max_orders_per_cycle": 1,
        "effective_max_daily_buy_orders": 1,
    }

    assert update_signal_execution_status(**kwargs) == 1
    before = store.signal_outcome_by_id(signal_id)
    assert update_signal_execution_status(**kwargs) == 1
    after = store.signal_outcome_by_id(signal_id)
    assert after["gate"]["execution"] == before["gate"]["execution"]

    equivalent = _recommendation(signal_id, "IDEMP")
    equivalent.decision_lineage = dict(reversed(list(equivalent.decision_lineage.items())))
    equivalent_kwargs = dict(kwargs)
    equivalent_kwargs["approved_recommendations"] = [equivalent]
    assert update_signal_execution_status(**equivalent_kwargs) == 1

    conflict_kwargs = dict(kwargs)
    conflict_kwargs["submitted"] = []
    conflict_kwargs["planned_signal_ids"] = []
    assert update_signal_execution_status(**conflict_kwargs) == 0
    preserved = store.signal_outcome_by_id(signal_id)
    assert preserved["gate"]["execution"] == before["gate"]["execution"]
    with store.connect() as conn:
        conflicts = conn.execute(
            "SELECT event_id, payload_json FROM agent_events WHERE event_type = ?",
            ("signal_execution_carrier_conflict",),
        ).fetchall()
    assert len(conflicts) == 1
    assert json.loads(conflicts[0]["payload_json"])["status"] == "conflict"


def _local_learning_observation(row: dict, *, signal_date: str | None) -> dict:
    observation = dict(row)
    observation["signal_date"] = signal_date
    observation["source_family"] = "learning_experiment"
    observation["observation_id"] = f"{signal_date}:{row['symbol']}:learning_experiment"
    return observation


@pytest.mark.parametrize(
    "case",
    ["POSITIVE", "DATE", "SOURCE", "REASON", "DECISION", "IDENTITY", "MISSING_DATE", "INVALID_DATE"],
)
def test_canonical_control_contract_is_one_to_one(tmp_path, case, monkeypatch):
    """Use one valid producer set, changing exactly one consumer field per negative."""

    assert _isolated_settings(tmp_path, monkeypatch).data_dir == tmp_path
    treatment, control, control_set = _canonical_verified_pair()
    store = _store(tmp_path)
    treatment_id = treatment.decision_lineage["signal_id"]
    canonical_control_id = control.decision_lineage["signal_id"]
    actual_control_id = canonical_control_id
    control_date = "2026-08-03"
    control_source_run_id = "cycle-1"
    control_decision = "approved_buy"
    execution = {
        "status": "approved_not_planned",
        "signal_id": canonical_control_id,
        "source_run_id": control_source_run_id,
        "cycle_id": control_source_run_id,
    }
    if case == "DATE":
        control_date = "2026-08-04"
    elif case == "SOURCE":
        control_source_run_id = "cycle-2"
        execution["source_run_id"] = control_source_run_id
        execution["cycle_id"] = control_source_run_id
    elif case == "REASON":
        execution = {
            "status": "plan_rejected",
            "reason": "operator_note",
            "signal_id": canonical_control_id,
            "source_run_id": control_source_run_id,
            "cycle_id": control_source_run_id,
        }
    elif case == "DECISION":
        control_decision = "candidate"
    elif case == "IDENTITY":
        actual_control_id = f"{canonical_control_id}:OTHER"
        execution["signal_id"] = actual_control_id

    _save_signal(store, signal_id=treatment_id, symbol=treatment.symbol)
    _save_signal(
        store,
        signal_id=actual_control_id,
        symbol=control.symbol,
        signal_date=control_date,
        source_run_id=control_source_run_id,
        decision=control_decision,
        gate={"execution": execution},
    )
    treatment_row = store.signal_outcome_by_id(treatment_id)
    control_row = store.signal_outcome_by_id(actual_control_id)
    if case in {"MISSING_DATE", "INVALID_DATE"}:
        treatment_observation = _local_learning_observation(
            _raw_observation(
                treatment_row,
                executed=True,
                comparable_control_set=control_set,
            ),
            signal_date="2026-08-03",
        )
        control_observation = _local_learning_observation(
            _raw_observation(control_row, executed=False),
            signal_date=None if case == "MISSING_DATE" else "not-a-date",
        )
        observation_store = SimpleNamespace(
            learning_observations=lambda **_kwargs: [treatment_observation, control_observation]
        )
    else:
        _materialize_observations(
            store,
            [
                _raw_observation(
                    treatment_row,
                    executed=True,
                    comparable_control_set=control_set,
                ),
                _raw_observation(control_row, executed=False),
            ],
        )
        observation_store = store

    executed, matched_controls, matches, _all_controls = _cohort_rows(
        observation_store,
        since_date="2026-08-03",
        end_date="2026-08-05",
    )
    assert len(executed) == 1
    assert len(_all_controls) == 1
    assert _all_controls[0]["symbol"] == "CONTROL"
    treatment_observation_id = executed[0]["observation_id"]
    if case == "POSITIVE":
        assert [row["symbol"] for row in matched_controls] == ["CONTROL"]
        assert matched_controls[0] == _all_controls[0]
        assert matches[treatment_observation_id] == [
            "2026-08-03:CONTROL:learning_experiment"
        ]
    else:
        assert matched_controls == []
        assert matches[treatment_observation_id] == []
