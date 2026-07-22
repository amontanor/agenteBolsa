"""P-L51BR1 combined QA, including the real persisted-object boundary."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path

import pytest
from test_p49b_data_quality_decision_shadow import (
    candidate,
    capture_data_quality_phase_a,
    finalize_data_quality_phase_b,
    observation,
    persist_data_quality_decision_shadow,
)
from test_p51b_trade_attribution_shadow import _p51a_defect_fixture, _snapshot, _valid_fixture
from test_pl49_pl50_combined_rehearsal import DECISION_AT

from agente_bolsa.storage import Store
from agente_bolsa.tools.canonical_operation_telemetry import build_canonical_operation_telemetry
from agente_bolsa.tools.canonical_trade_attribution import (
    build_canonical_trade_attribution,
    persist_canonical_trade_attribution,
)

SESSION = "2026-07-21"
CAPTURED_AT = datetime(2026, 7, 21, 16, 0, tzinfo=timezone.utc)


def _store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "state" / "combined.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    return store


def _persisted_cycle_orders(store: Store) -> None:
    """Persist the exact shapes produced by cycle_runner/scheduler order writes."""

    buy_plan = {
        "plan_id": "plan-real-buy",
        "cycle_id": "cycle-real",
        "symbol": "ACME",
        "side": "buy",
        "notional": 1000.0,
        "approved": True,
        "dry_run": True,
        "payload": {
            "qty": 10.0,
            "recommendation": {"action": "buy", "recommendation_id": "rec-real-buy"},
            "decision_lineage": {
                "cycle_id": "cycle-real",
                "signal_capture_id": "capture-real-buy",
                "signal_id": "signal-real-buy",
                "candidate_id": "candidate-real-buy",
            },
        },
    }
    buy_order = {
        "id": "buy-real-001",
        "client_order_id": "client-buy-real-001",
        "status": "filled",
        "symbol": "ACME",
        "side": "buy",
        "qty": "10",
        "filled_qty": "10",
        "filled_avg_price": "100",
        "filled_at": "2026-07-21T15:40:00+00:00",
    }
    sell_plan = {
        "plan_id": "plan-real-sell",
        "cycle_id": "cycle-real",
        "symbol": "ACME",
        "side": "sell",
        "notional": 1000.0,
        "approved": True,
        "dry_run": True,
        "payload": {
            "qty": 10.0,
            "recommendation": {"action": "exit", "recommendation_id": "rec-real-exit"},
            "risk_decision": {
                "approved": True,
                "checks": {"action": "exit", "source_plan_id": "plan-real-buy"},
            },
        },
    }
    sell_order = {
        "id": "sell-real-001",
        "client_order_id": "client-sell-real-001",
        "status": "filled",
        "symbol": "ACME",
        "side": "sell",
        "qty": "10",
        "filled_qty": "10",
        "filled_avg_price": "101",
        "filled_at": "2026-07-21T16:00:00+00:00",
    }
    for plan, order in ((buy_plan, buy_order), (sell_plan, sell_order)):
        store.save_order_plan(
            plan_id=plan["plan_id"],
            cycle_id=plan["cycle_id"],
            symbol=plan["symbol"],
            side=plan["side"],
            notional=plan["notional"],
            approved=plan["approved"],
            dry_run=plan["dry_run"],
            payload=plan,
        )
        store.save_broker_order(
            broker_order_id=order["id"],
            plan_id=plan["plan_id"],
            cycle_id=plan["cycle_id"],
            symbol=plan["symbol"],
            side=plan["side"],
            status=order["status"],
            payload={"plan": plan, "broker_order": order},
        )


def test_real_persisted_cycle_objects_cannot_claim_future_exact_attribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real persistence boundary lacks fill fragments/allocations by design."""

    store = _store(tmp_path)
    monkeypatch.setattr("agente_bolsa.storage._utc_iso", lambda: "2026-07-21T16:05:00+00:00")
    _persisted_cycle_orders(store)

    telemetry = build_canonical_operation_telemetry(store, SESSION, captured_at=CAPTURED_AT)
    attribution = build_canonical_trade_attribution(telemetry, SESSION, captured_at=CAPTURED_AT)

    assert {row["broker_order_id"] for row in telemetry["operations"]} == {"buy-real-001", "sell-real-001"}
    sell_telemetry = next(row for row in telemetry["operations"] if row["broker_order_id"] == "sell-real-001")
    assert sell_telemetry["source_plan_id"] == "plan-real-buy"
    assert "trade_attribution" not in sell_telemetry
    assert "fill_fragments" not in sell_telemetry
    assert attribution["denominators"]["sell_order_count"] == 1
    assert attribution["denominators"]["attributed_sell_count"] == 0
    assert attribution["metrics"]["net_realized_pl"] is None
    assert attribution["status"] in {"ambiguous", "unavailable"}
    assert any(
        reason in {"missing_exact_mapping", "missing_sell_fill_fragment"}
        for reason in next(row for row in attribution["operations"] if row["sell_broker_order_id"] == "sell-real-001")["reason_codes"]
    )


def test_combined_shadow_events_remain_independent_and_active_inputs_unchanged(tmp_path: Path) -> None:
    store = _store(tmp_path)
    row = observation("ACME")
    active_candidate = candidate("ACME", row)
    active_before = copy.deepcopy(active_candidate)
    quality = finalize_data_quality_phase_b(
        capture_data_quality_phase_a(
            cycle_id="cycle-real",
            market_snapshot={"observations": [row]},
            candidates=[active_candidate],
            decision_at=DECISION_AT,
            captured_at=DECISION_AT,
        ),
        cycle_id="cycle-real",
    )
    p51_snapshot = _snapshot(_valid_fixture())

    assert persist_data_quality_decision_shadow(store, quality)["status"] == "inserted"
    assert persist_canonical_trade_attribution(store, p51_snapshot)["status"] == "inserted"
    events = store.agent_events(limit=50)
    event_ids = {row["event_id"] for row in events}
    assert "data_quality_decision_shadow:cycle-real" in event_ids
    assert "canonical_trade_attribution:2026-07-21" in event_ids
    assert active_candidate == active_before


def test_real_boundary_is_not_mistaken_for_synthetic_exact_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agente_bolsa.storage._utc_iso", lambda: "2026-07-21T16:05:00+00:00")
    store = _store(tmp_path)
    _persisted_cycle_orders(store)
    telemetry = build_canonical_operation_telemetry(store, SESSION, captured_at=CAPTURED_AT)
    before = copy.deepcopy(telemetry)
    result = build_canonical_trade_attribution(telemetry, SESSION, captured_at=CAPTURED_AT)

    assert telemetry == before
    assert result["denominators"]["buy_order_count"] == 1
    assert result["denominators"]["sell_order_count"] == 1
    assert result["denominators"]["attributed_sell_count"] == 0
    assert result["net_attributable_pl"] is None


def test_p51a_descriptive_total_remains_unavailable_in_combined_candidate() -> None:
    result = _snapshot(_p51a_defect_fixture())

    assert result["denominators"]["sell_order_count"] == 18
    assert result["denominators"]["attributed_sell_count"] == 0
    assert result["metrics"]["net_realized_pl"] is None
