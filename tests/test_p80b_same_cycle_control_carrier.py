from __future__ import annotations

import json
from types import SimpleNamespace

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.daily_learning import _materialize_observations
from agente_bolsa.tools.learning_scoreboard import _cohort_rows
from agente_bolsa.tools.signal_learning import (
    update_signal_decisions,
    update_signal_execution_status,
)


def _store(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    return store


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


def _raw_observation(row: dict, *, executed: bool) -> dict:
    return {
        "signal_id": row["signal_id"],
        "source_run_id": row["source_run_id"],
        "source": row["source"],
        "symbol": row["symbol"],
        "signal_date": row["signal_date"],
        "decision": row["decision"],
        "features": row["features"],
        "gate": row["gate"],
        "outcome": {},
        "score": row["features"].get("score"),
        "considered_by_llm": False,
        "executed_buy": executed,
        "orders_same_day": int(executed),
        "created_at": "2026-08-03T13:30:00+00:00",
    }


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


def test_exact_signal_id_prevents_same_symbol_contamination(tmp_path):
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
        settings=Settings(DATA_DIR=tmp_path),
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
            _raw_observation(treatment, executed=True),
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
