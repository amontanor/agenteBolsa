from __future__ import annotations

from agente_bolsa.market_calendar import MarketCalendar
from agente_bolsa.storage import Store
from agente_bolsa.tools.time_stop_policy import (
    build_position_identity,
    evaluate_position_time_stop,
)


def _calendar() -> MarketCalendar:
    calendar = MarketCalendar("XNYS", "Europe/Madrid")
    assert calendar._calendar is not None
    return calendar


def _save_order(
    store: Store,
    *,
    order_id: str,
    plan_id: str,
    symbol: str,
    side: str,
    qty: float,
    filled_at: str,
    status: str = "filled",
    partial: bool = False,
    source_plan_id: str | None = None,
) -> None:
    broker_status = "OrderStatus.PARTIALLY_FILLED" if partial else f"OrderStatus.{status.upper()}"
    payload = {
        "broker_order": {
            "id": order_id,
            "side": f"OrderSide.{side.upper()}",
            "status": broker_status,
            "qty": qty,
            "filled_qty": qty,
            "filled_at": filled_at,
            "first_fill_at": None if partial else filled_at,
        },
        "broker_order_reconciled": {
            "id": order_id,
            "status": status if not partial else "partially_filled",
            "qty": qty,
            "filled_qty": qty,
            "filled_at": filled_at,
        },
        "plan": {"plan_id": plan_id, "payload": {}},
    }
    if source_plan_id:
        payload["plan"]["payload"] = {
            "risk_decision": {"checks": {"source_plan_id": source_plan_id}}
        }
    store.save_broker_order(
        broker_order_id=order_id,
        plan_id=plan_id,
        cycle_id=f"cycle-{order_id}",
        symbol=symbol,
        side=side,
        status=status,
        payload=payload,
    )


def _evaluate(lots: list[dict], qty: float) -> dict:
    return evaluate_position_time_stop(
        lots=lots,
        position_qty=qty,
        side="PositionSide.LONG",
        evaluation_at="2026-07-17T15:00:00+00:00",
        required_completed_sessions=5,
        calendar=_calendar(),
    )


def test_single_open_buy_is_resolved_by_exact_quantity(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    _save_order(
        store,
        order_id="buy-a",
        plan_id="plan-a",
        symbol="AAPL",
        side="buy",
        qty=5,
        filled_at="2026-07-14T14:00:00+00:00",
    )

    lots = store.executed_open_buy_lots_by_symbol(position_quantities={"AAPL": 5})
    assert lots["AAPL"][0]["open_qty"] == 5
    assert lots["AAPL"][0]["open_qty_authority"] == "exact_source_plan_sell_reconciliation"
    assert _evaluate(lots["AAPL"], 5)["status"] == "available"


def test_two_buys_and_partial_sell_keep_independent_open_lots(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    _save_order(store, order_id="buy-a", plan_id="plan-a", symbol="AAPL", side="buy", qty=5, filled_at="2026-07-14T14:00:00+00:00")
    _save_order(store, order_id="buy-b", plan_id="plan-b", symbol="AAPL", side="buy", qty=5, filled_at="2026-07-15T14:00:00+00:00")
    _save_order(
        store,
        order_id="sell-a",
        plan_id="sell-a",
        symbol="AAPL",
        side="sell",
        qty=2,
        filled_at="2026-07-16T14:00:00+00:00",
        source_plan_id="plan-a",
    )

    lots = store.executed_open_buy_lots_by_symbol(position_quantities={"AAPL": 8})["AAPL"]
    assert [(lot["broker_order_id"], lot["open_qty"]) for lot in lots] == [("buy-a", 3), ("buy-b", 5)]
    result = _evaluate(lots, 8)
    assert result["status"] == "available"
    assert [item["broker_order_id"] for item in result["lots"]] == ["buy-a", "buy-b"]


def test_exact_sell_closes_one_lot_and_rebuy_gets_new_identity(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    _save_order(store, order_id="buy-old", plan_id="plan-old", symbol="AAPL", side="buy", qty=5, filled_at="2026-07-14T14:00:00+00:00")
    _save_order(
        store,
        order_id="sell-old",
        plan_id="sell-old",
        symbol="AAPL",
        side="sell",
        qty=5,
        filled_at="2026-07-15T14:00:00+00:00",
        source_plan_id="plan-old",
    )
    _save_order(store, order_id="buy-new", plan_id="plan-new", symbol="AAPL", side="buy", qty=2, filled_at="2026-07-16T14:00:00+00:00")

    lots = store.executed_open_buy_lots_by_symbol(position_quantities={"AAPL": 2})["AAPL"]
    assert [lot["broker_order_id"] for lot in lots] == ["buy-new"]
    identity, reason = build_position_identity(symbol="AAPL", lots=lots, position_qty=2)
    assert identity is not None and reason is None


def test_crwd_and_well_sanitized_history_resolves_current_lot(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    _save_order(store, order_id="crwd-old-a", plan_id="crwd-plan-a", symbol="CRWD", side="buy", qty=2, filled_at="2026-06-05T14:00:00+00:00")
    _save_order(store, order_id="crwd-sell-a", plan_id="crwd-sell-a", symbol="CRWD", side="sell", qty=2, filled_at="2026-06-10T14:00:00+00:00", source_plan_id="crwd-plan-a")
    _save_order(store, order_id="crwd-old-b", plan_id="crwd-plan-b", symbol="CRWD", side="buy", qty=5, filled_at="2026-07-08T14:00:00+00:00")
    _save_order(store, order_id="crwd-sell-b", plan_id="crwd-sell-b", symbol="CRWD", side="sell", qty=5, filled_at="2026-07-13T14:00:00+00:00", source_plan_id="crwd-plan-b")
    _save_order(store, order_id="crwd-current", plan_id="crwd-plan-current", symbol="CRWD", side="buy", qty=4, filled_at="2026-07-16T14:00:00+00:00")
    _save_order(store, order_id="well-old", plan_id="well-plan-old", symbol="WELL", side="buy", qty=16, filled_at="2026-04-30T14:00:00+00:00")
    _save_order(store, order_id="well-sell-old", plan_id="well-sell-old", symbol="WELL", side="sell", qty=16, filled_at="2026-05-29T14:00:00+00:00", source_plan_id="well-plan-old")
    _save_order(store, order_id="well-current", plan_id="well-plan-current", symbol="WELL", side="buy", qty=4, filled_at="2026-07-16T14:00:00+00:00")

    lots = store.executed_open_buy_lots_by_symbol(position_quantities={"CRWD": 4, "WELL": 4})
    assert [lot["broker_order_id"] for lot in lots["CRWD"]] == ["crwd-current"]
    assert [lot["broker_order_id"] for lot in lots["WELL"]] == ["well-current"]
    assert _evaluate(lots["CRWD"], 4)["status"] == "available"
    assert _evaluate(lots["WELL"], 4)["status"] == "available"


def test_partial_buy_without_first_fill_remains_unavailable(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    _save_order(store, order_id="partial", plan_id="partial-plan", symbol="AAPL", side="buy", qty=2, filled_at="2026-07-16T14:00:00+00:00", partial=True)
    lots = store.executed_open_buy_lots_by_symbol(position_quantities={"AAPL": 2})["AAPL"]
    result = _evaluate(lots, 2)
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "fill_authority_unavailable"


def test_filled_sell_without_source_plan_keeps_lot_ambiguous(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    _save_order(store, order_id="buy-a", plan_id="plan-a", symbol="AAPL", side="buy", qty=5, filled_at="2026-07-14T14:00:00+00:00")
    _save_order(store, order_id="sell-unlinked", plan_id="sell-unlinked", symbol="AAPL", side="sell", qty=1, filled_at="2026-07-16T14:00:00+00:00")
    lots = store.executed_open_buy_lots_by_symbol(position_quantities={"AAPL": 4})["AAPL"]
    assert lots[0]["open_qty_authority"] == "unavailable"
    result = _evaluate(lots, 4)
    assert result["status"] == "ambiguous"
    assert result["ambiguity_reason"] == "open_lot_quantities_not_verifiable"
    identity, reason = build_position_identity(symbol="AAPL", lots=lots, position_qty=4)
    assert identity is None and reason == "open_quantity_unavailable"


def test_pending_rejected_and_cancelled_sells_do_not_consume_open_qty(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    _save_order(store, order_id="buy-a", plan_id="plan-a", symbol="AAPL", side="buy", qty=5, filled_at="2026-07-14T14:00:00+00:00")
    for status in ("pending", "rejected", "cancelled"):
        _save_order(store, order_id=f"sell-{status}", plan_id=f"sell-{status}", symbol="AAPL", side="sell", qty=5, filled_at="2026-07-16T14:00:00+00:00", status=status)
    lots = store.executed_open_buy_lots_by_symbol(position_quantities={"AAPL": 5})["AAPL"]
    assert lots[0]["open_qty"] == 5
    assert _evaluate(lots, 5)["status"] == "available"
