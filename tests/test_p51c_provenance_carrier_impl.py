"""P-L51C-W product tests for the future BUY -> SELL provenance carrier."""

from __future__ import annotations

import copy
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.scheduler import _risk_exit_plan
from agente_bolsa.storage import Store
from agente_bolsa.tools.broker_reconciliation import reconcile_broker_orders
from agente_bolsa.tools.canonical_operation_telemetry import build_canonical_operation_telemetry
from agente_bolsa.tools.canonical_trade_attribution import build_canonical_trade_attribution
from agente_bolsa.tools.execution import build_market_order_request
from agente_bolsa.tools.exit_lot_provenance import (
    CARRIER_FIELD,
    SCHEMA_VERSION,
    build_exit_lot_provenance,
    carrier_to_trade_attribution,
)

SESSION = "2026-07-21"
CAPTURED_AT = datetime(2026, 7, 21, 17, 0, tzinfo=timezone.utc)


def _lot(order_id: str, plan_id: str, qty: float, *, fill_id: str | None = None, lot_id: str | None = None) -> dict[str, Any]:
    return {
        "broker_order_id": order_id,
        "order_plan_id": plan_id,
        "source_plan_id": plan_id,
        "filled_qty": qty,
        "open_qty": qty,
        "position_identity": "position-ACME",
        "lot_identity": lot_id,
        "canonical_buy_fill_ids": [{"fill_id": fill_id, "qty": qty}] if fill_id else None,
    }


def _plan(qty: float = 10.0, *, trigger: str = "stop_loss") -> dict[str, Any]:
    return _risk_exit_plan(
        symbol="ACME",
        notional=qty * 100.0,
        qty=qty,
        current_price=99.0,
        trigger=trigger,
        level=95.0,
        source_plan={"plan_id": "buy-plan-1", "payload": {"stop_loss": 95.0, "take_profit": 110.0}},
        time_stop_evidence={"status": "available", "completed_sessions": 5} if trigger == "time_stop_v2" else None,
    )


def _explicit_allocation(order_id: str, plan_id: str, qty: float, *, fill_id: str | None = None, lot_id: str | None = "lot-1") -> dict[str, Any]:
    return {
        "buy_broker_order_id": order_id,
        "buy_plan_id": plan_id,
        "allocated_qty": qty,
        "available_open_qty_at_decision": qty,
        "canonical_buy_fill_ids": [{"fill_id": fill_id, "qty": qty}] if fill_id else None,
        "lot_identity": lot_id,
    }


def test_product_builder_schema_and_missing_fields_are_explicit() -> None:
    plan = _plan()
    carrier = build_exit_lot_provenance(plan, [_lot("buy-1", "buy-plan-1", 10, lot_id="lot-1")])
    assert carrier["schema_version"] == SCHEMA_VERSION
    assert carrier["provenance_quality"] == "exact"
    assert carrier["allocations"][0]["buy_broker_order_id"] == "buy-1"
    assert carrier["allocations"][0]["canonical_buy_fill_ids"] is None
    assert carrier["content_hash"]

    unavailable = build_exit_lot_provenance(plan, [], explicit_allocations=[])
    assert unavailable["provenance_quality"] == "unavailable"
    assert unavailable["allocations"] is None
    assert "missing_allocations" in unavailable["reason_codes"]


def test_partial_buy_sell_and_remainder_use_explicit_allocation() -> None:
    carrier = build_exit_lot_provenance(
        _plan(4),
        [_lot("buy-1", "buy-plan-1", 10, fill_id="buy-fill-1", lot_id="lot-1")],
        explicit_allocations=[_explicit_allocation("buy-1", "buy-plan-1", 4, fill_id="buy-fill-1", lot_id="lot-1")],
    )
    assert carrier["provenance_quality"] == "exact"
    assert carrier["allocations"][0]["allocated_qty"] == 4
    assert carrier_to_trade_attribution(carrier)["allocations"][0]["qty"] == 4


def test_rebuys_and_multilot_never_use_fifo() -> None:
    lots = [_lot("buy-old", "buy-plan-old", 5, lot_id="lot-old"), _lot("buy-new", "buy-plan-new", 5, lot_id="lot-new")]
    rebuy_plan = _plan(5)
    rebuy_plan["payload"]["risk_decision"]["checks"]["source_plan_id"] = "buy-plan-new"
    rebuy = build_exit_lot_provenance(
        rebuy_plan,
        lots,
        explicit_allocations=[_explicit_allocation("buy-new", "buy-plan-new", 5, lot_id="lot-new")],
    )
    assert [item["buy_broker_order_id"] for item in rebuy["allocations"]] == ["buy-new"]

    multilot = build_exit_lot_provenance(
        _plan(6),
        lots,
        explicit_allocations=[
            _explicit_allocation("buy-old", "buy-plan-old", 3, lot_id="lot-old"),
            _explicit_allocation("buy-new", "buy-plan-new", 3, lot_id="lot-new"),
        ],
    )
    assert multilot["provenance_quality"] == "exact"
    assert multilot["source_plan_id"] is None
    assert {item["buy_plan_id"] for item in multilot["allocations"]} == {"buy-plan-old", "buy-plan-new"}


@pytest.mark.parametrize(
    ("allocation", "reason"),
    [
        ([], "missing_allocations"),
        ({"buy_broker_order_id": None, "buy_plan_id": "buy-plan-1", "allocated_qty": 10, "available_open_qty_at_decision": 10}, "incomplete_allocation"),
        ({"buy_broker_order_id": "buy-unknown", "buy_plan_id": "buy-plan-1", "allocated_qty": 10, "available_open_qty_at_decision": 10}, "unknown_buy_broker_order_id"),
        ({"buy_broker_order_id": "buy-1", "buy_plan_id": "buy-plan-1", "allocated_qty": 11, "available_open_qty_at_decision": 10}, "allocation_exceeds_open_qty"),
    ],
)
def test_invalid_or_missing_provenance_is_not_promoted(allocation: dict[str, Any] | list[Any], reason: str) -> None:
    allocations = allocation if isinstance(allocation, list) else [allocation]
    result = build_exit_lot_provenance(_plan(), [_lot("buy-1", "buy-plan-1", 10)], explicit_allocations=allocations)
    assert result["provenance_quality"] in {"unavailable", "conflict"}
    assert reason in result["reason_codes"]
    assert result["allocations"] is None


@pytest.mark.parametrize("status", ["pending", "pending_new", "rejected", "cancelled"])
def test_pending_rejected_cancelled_are_unavailable(status: str) -> None:
    result = build_exit_lot_provenance(
        _plan(),
        [_lot("buy-1", "buy-plan-1", 10)],
        order_status=status,
    )
    assert result["provenance_quality"] == "unavailable"
    assert "sell_order_not_filled" in result["reason_codes"]


def test_duplicate_allocation_and_content_conflict_are_auditable(tmp_path: Path) -> None:
    duplicate = _explicit_allocation("buy-1", "buy-plan-1", 10)
    result = build_exit_lot_provenance(_plan(), [_lot("buy-1", "buy-plan-1", 10)], explicit_allocations=[duplicate, duplicate])
    assert result["provenance_quality"] == "conflict"
    assert "duplicate_allocation" in result["reason_codes"]

    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    first = build_exit_lot_provenance(_plan(), [_lot("buy-1", "buy-plan-1", 10)], explicit_allocations=[_explicit_allocation("buy-1", "buy-plan-1", 10)])
    repeated = copy.deepcopy(first)
    repeated["captured_at"] = "2026-07-21T18:00:00+00:00"
    changed = copy.deepcopy(first)
    changed["allocations"][0]["allocated_qty"] = 9
    assert store.record_exit_lot_provenance(first, event_id="exit_lot_provenance:sell-1")["status"] == "inserted"
    assert store.record_exit_lot_provenance(repeated, event_id="exit_lot_provenance:sell-1")["status"] == "idempotent"
    assert store.record_exit_lot_provenance(changed, event_id="exit_lot_provenance:sell-1")["status"] == "conflict"


def test_stop_loss_and_time_stop_keep_exit_structure_and_request_parity() -> None:
    stop = _plan(trigger="stop_loss")
    time_stop = _plan(trigger="time_stop_v2")
    assert stop["payload"]["risk_decision"]["checks"]["trigger"] == "stop_loss"
    assert time_stop["payload"]["risk_decision"]["checks"]["trigger"] == "time_stop_v2"
    assert stop["payload"]["qty"] == time_stop["payload"]["qty"] == 10

    with_carrier = copy.deepcopy(stop)
    with_carrier["payload"][CARRIER_FIELD] = build_exit_lot_provenance(stop, [_lot("buy-1", "buy-plan-1", 10, lot_id="lot-1")])
    baseline_request = build_market_order_request(stop, client_order_id="client-sell", use_bracket_orders=False)
    carrier_request = build_market_order_request(with_carrier, client_order_id="client-sell", use_bracket_orders=False)
    assert repr(baseline_request) == repr(carrier_request)


def _save_filled_buy(store: Store) -> list[dict[str, Any]]:
    buy_plan = {
        "plan_id": "buy-plan-1",
        "cycle_id": "cycle-buy",
        "symbol": "ACME",
        "side": "buy",
        "payload": {"qty": 10, "entry_price": 100, "lot_identity": "lot-1", "position_identity": "position-ACME"},
    }
    buy_fill = {"fill_fragment_id": "buy-fill-1", "broker_order_id": "buy-1", "side": "BUY", "lot_id": "lot-1", "qty": 10}
    store.save_order_plan(plan_id="buy-plan-1", cycle_id="cycle-buy", symbol="ACME", side="buy", notional=1000, approved=True, dry_run=True, payload=buy_plan)
    store.save_broker_order(
        broker_order_id="buy-1",
        plan_id="buy-plan-1",
        cycle_id="cycle-buy",
        symbol="ACME",
        side="buy",
        status="filled",
        payload={"plan": buy_plan, "broker_order": {"id": "buy-1", "status": "filled", "qty": 10, "filled_qty": 10, "filled_at": "2026-07-21T15:40:00+00:00"}, "canonical_fill_fragments": [buy_fill]},
    )
    return store.executed_open_buy_lots_by_symbol(position_quantities={"ACME": 10})["ACME"]


def test_real_store_chain_reconciliation_p48_p51_attributes_one_sell(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(DATA_DIR=tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    monkeypatch.setattr("agente_bolsa.storage._utc_iso", lambda: "2026-07-21T16:00:00+00:00")
    lots = _save_filled_buy(store)
    assert lots[0]["broker_order_id"] == "buy-1"
    assert lots[0]["canonical_buy_fill_ids"] == [{"fill_id": "buy-fill-1", "qty": 10.0}]

    sell_plan = _risk_exit_plan(
        symbol="ACME",
        notional=1000,
        qty=10,
        current_price=99,
        trigger="stop_loss",
        level=95,
        source_plan={"plan_id": "buy-plan-1", "payload": {"stop_loss": 95, "take_profit": 110}},
        open_buy_lots=lots,
    )
    carrier = sell_plan["payload"][CARRIER_FIELD]
    assert carrier["provenance_quality"] == "exact"
    assert carrier["allocations"][0]["lot_identity"] == "lot-1"
    store.record_exit_lot_provenance(carrier, event_id=f"exit_lot_provenance:{sell_plan['plan_id']}")
    store.save_order_plan(plan_id=sell_plan["plan_id"], cycle_id=sell_plan["cycle_id"], symbol="ACME", side="sell", notional=1000, approved=True, dry_run=True, payload=sell_plan)
    sell_fill = {"fill_fragment_id": "sell-fill-1", "broker_order_id": "sell-1", "side": "SELL", "lot_id": "lot-1", "qty": 10}
    costs = {"gross_realized_pl": 100.0, "commissions": 0.5, "regulatory_fees": 0.2, "spread_cost": 0.1, "slippage_cost": 0.3, "other_costs": 0.4}
    store.save_broker_order(
        broker_order_id="sell-1",
        plan_id=sell_plan["plan_id"],
        cycle_id="cycle-exit",
        symbol="ACME",
        side="sell",
        status="pending_new",
        payload={"plan": sell_plan, "broker_order": {"id": "sell-1", "status": "pending_new", "qty": 10}, "canonical_fill_fragments": [sell_fill], "execution_costs": costs},
    )

    remote = type(
        "RemoteOrder",
        (),
        {"id": "sell-1", "client_order_id": "", "status": "filled", "filled_qty": 10, "filled_avg_price": 101, "qty": 10, "notional": None, "submitted_at": None, "filled_at": "2026-07-21T16:00:00+00:00", "updated_at": "2026-07-21T16:00:00+00:00"},
    )()

    class _Factory:
        def __init__(self, _settings: Settings) -> None:
            pass

        def alpaca_trading_client(self) -> Any:
            return type("FakeClient", (), {"get_order_by_id": lambda _self, _id: remote})()

    monkeypatch.setattr("agente_bolsa.tools.broker_reconciliation.BrokerClientFactory", _Factory)
    reconciliation = reconcile_broker_orders(settings, store, apply=True, update_learning=False)
    assert reconciliation["changes"][0]["new"] == "filled"

    telemetry = build_canonical_operation_telemetry(store, SESSION, captured_at=CAPTURED_AT)
    sell_operation = next(item for item in telemetry["operations"] if item["broker_order_id"] == "sell-1")
    assert sell_operation["trade_attribution"]["allocations"][0]["buy_broker_order_id"] == "buy-1"
    assert sell_operation["execution_costs"] == costs
    attribution = build_canonical_trade_attribution(telemetry, SESSION, captured_at=CAPTURED_AT)
    assert attribution["status"] == "available"
    assert attribution["denominators"] == {
        "buy_order_count": 1,
        "sell_order_count": 1,
        "fill_fragment_count": 2,
        "attributed_sell_count": 1,
        "unavailable_sell_count": 0,
        "ambiguous_sell_count": 0,
        "conflict_count": 0,
        "closed_lot_count": 1,
        "partially_closed_lot_count": 0,
        "open_lot_count": 0,
    }
    assert attribution["metrics"]["gross_realized_pl"] == 100.0
    assert attribution["metrics"]["net_realized_pl"] == pytest.approx(98.5)
    assert attribution["coverage"]["net_pl_coverage"]["ratio"] == 1.0


def test_partial_costs_keep_net_null_and_historical_without_carrier_unavailable() -> None:
    source = {
        "schema_version": "p-l48b.canonical-operation-telemetry.v1",
        "session_date": SESSION,
        "denominators": {"fill_fragment_count": 2},
        "fill_fragments": [
            {"fill_fragment_id": "buy-fill-1", "broker_order_id": "buy-1", "side": "BUY", "lot_id": "lot-1", "qty": 10},
            {"fill_fragment_id": "sell-fill-1", "broker_order_id": "sell-1", "side": "SELL", "lot_id": "lot-1", "qty": 10},
        ],
        "operations": [
            {"broker_order_id": "buy-1", "plan_id": "buy-plan-1", "source_plan_id": "buy-plan-1", "side": "buy", "status": "filled", "filled_qty": 10, "fill_fragments": [{"fill_fragment_id": "buy-fill-1", "broker_order_id": "buy-1", "side": "BUY", "lot_id": "lot-1", "qty": 10}]},
            {"broker_order_id": "sell-1", "plan_id": "sell-plan-1", "source_plan_id": "buy-plan-1", "side": "sell", "status": "filled", "filled_qty": 10, "fill_fragments": [{"fill_fragment_id": "sell-fill-1", "broker_order_id": "sell-1", "side": "SELL", "lot_id": "lot-1", "qty": 10}], "trade_attribution": {"source_plan_id": "buy-plan-1", "allocations": [{"buy_broker_order_id": "buy-1", "buy_plan_id": "buy-plan-1", "entry_plan_id": "buy-plan-1", "source_plan_id": "buy-plan-1", "lot_id": "lot-1", "fill_fragment_id": "buy-fill-1", "qty": 10}]}, "execution_costs": {"gross_realized_pl": 100, "commissions": 0.5, "regulatory_fees": None, "spread_cost": 0.1, "slippage_cost": 0.2, "other_costs": 0.1}},
        ],
    }
    result = build_canonical_trade_attribution(source, SESSION, captured_at=CAPTURED_AT)
    assert result["attributed"] == 1
    assert result["metrics"]["gross_realized_pl"] == 100.0
    assert result["metrics"]["net_realized_pl"] is None

    legacy = copy.deepcopy(source)
    legacy["operations"][1].pop("trade_attribution")
    legacy_result = build_canonical_trade_attribution(legacy, SESSION, captured_at=CAPTURED_AT)
    assert legacy_result["denominators"]["attributed_sell_count"] == 0
    assert legacy_result["metrics"]["net_realized_pl"] is None


def test_build_failure_is_fail_open_and_does_not_change_protective_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    baseline = _plan()

    def _boom(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("carrier unavailable")

    monkeypatch.setattr("agente_bolsa.scheduler.build_exit_lot_provenance", _boom)
    result = _risk_exit_plan(
        symbol="ACME",
        notional=baseline["notional"],
        qty=baseline["payload"]["qty"],
        current_price=99,
        trigger="stop_loss",
        level=95,
        source_plan={"plan_id": "buy-plan-1", "payload": {"stop_loss": 95, "take_profit": 110}},
        open_buy_lots=[],
    )
    assert result["side"] == baseline["side"] == "sell"
    assert result["payload"]["qty"] == baseline["payload"]["qty"]
    assert result["payload"]["risk_decision"]["checks"]["trigger"] == "stop_loss"
    assert result["payload"][CARRIER_FIELD]["provenance_quality"] == "unavailable"
    assert "carrier_build_failed:RuntimeError" in result["payload"][CARRIER_FIELD]["reason_codes"]


def test_concurrent_identical_carrier_persistence_is_inserted_or_idempotent(tmp_path: Path) -> None:
    carrier = build_exit_lot_provenance(_plan(), [_lot("buy-1", "buy-plan-1", 10)], explicit_allocations=[_explicit_allocation("buy-1", "buy-plan-1", 10)])
    results: list[str] = []
    barrier = threading.Barrier(2)

    def _write() -> None:
        store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
        store.ensure_schema()
        barrier.wait()
        results.append(store.record_exit_lot_provenance(carrier, event_id="exit_lot_provenance:sell-concurrent")["status"])

    threads = [threading.Thread(target=_write) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["idempotent", "inserted"]


def test_carrier_input_is_not_mutated() -> None:
    plan = _plan()
    lots = [_lot("buy-1", "buy-plan-1", 10, fill_id="buy-fill-1", lot_id="lot-1")]
    before = copy.deepcopy((plan, lots))
    build_exit_lot_provenance(plan, lots)
    assert (plan, lots) == before
