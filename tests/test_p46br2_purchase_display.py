from __future__ import annotations

from agente_bolsa.tools.purchase_display import resolve_position_purchase
from agente_bolsa.web_app import _position_purchase_sort_key, _position_rows


def _lot(
    order_id: str,
    *,
    symbol: str = "AAPL",
    timestamp: str = "2026-07-17T14:00:00Z",
    authority: str = "first_fill_at",
    partial: bool = False,
    closed: bool | None = None,
    open_qty: float | None = None,
) -> dict:
    row = {
        "broker_order_id": order_id,
        "symbol": symbol,
        "order_side": "OrderSide.BUY",
        "order_status_verified": True,
        "filled_qty": 1,
        "is_partial": partial,
        "fill_authority": authority,
        "entry_fill_at": timestamp,
    }
    if closed is not None:
        row["closed"] = closed
    if open_qty is not None:
        row["open_qty"] = open_qty
    return row


def _pending(
    order_id: str,
    *,
    symbol: str = "AAPL",
    qty: float = 1,
    status: str = "OrderStatus.PENDING_NEW",
    created_at: str | None = "2026-07-17T14:00:00Z",
    side: str = "OrderSide.BUY",
    payload: dict | None = None,
) -> dict:
    return {
        "broker_order_id": order_id,
        "symbol": symbol,
        "side": side,
        "status": status,
        "qty": qty,
        "time": created_at,
        "payload": payload or {},
    }


def _history(symbol: str = "AAPL", qty: float = 1, **kwargs) -> dict:
    return {
        "open_positions": [{"symbol": symbol, "qty": qty}],
        "executed_buy_lots_by_symbol": {},
        "local_broker_orders": [],
        **kwargs,
    }


def test_filled_first_fill_is_verified_and_precedes_pending_order():
    history = _history(
        executed_buy_lots_by_symbol={"AAPL": [_lot("filled", timestamp="2026-07-17T13:00:00Z")]},
        local_broker_orders=[_pending("pending", created_at="2026-07-17T14:00:00Z")],
    )

    result = resolve_position_purchase(history, "AAPL", 1)

    assert result["purchase_timestamp_status"] == "verified_fill"
    assert result["purchase_timestamp_source"] == "first_fill_at"
    assert result["broker_order_id"] == "filled"


def test_full_aggregate_fill_is_verified():
    history = _history(
        executed_buy_lots_by_symbol={
            "AAPL": [_lot("aggregate", authority="aggregated_filled_at")]
        }
    )

    result = resolve_position_purchase(history, "AAPL", 1)

    assert result["purchase_timestamp_status"] == "verified_fill"
    assert "fill agregado" in result["purchase_label"]


def test_unique_pending_and_accepted_orders_are_provisional():
    for status, source in (("PENDING_NEW", "created_at"), ("accepted", "created_at")):
        history = _history(local_broker_orders=[_pending("pending", status=status)])
        result = resolve_position_purchase(history, "AAPL", 1)
        assert result["purchase_timestamp_status"] == "provisional_order"
        assert result["purchase_timestamp_source"] == source
        assert result["broker_order_id"] == "pending"


def test_pending_timestamp_precedence_and_timezone_conversion():
    history = _history(
        local_broker_orders=[
            _pending(
                "pending",
                created_at="2026-07-17T12:00:00Z",
                payload={
                    "submitted_at": "2026-07-17T13:00:00+00:00",
                    "accepted_at": "2026-07-17T13:01:00+00:00",
                },
            )
        ]
    )

    row = _position_rows(history, local_timezone="Europe/Madrid")[0]

    assert row["Compra estado"] == "provisional_order"
    assert row["Compra etiqueta"] == "Orden de compra pendiente"
    assert row["Compra fecha"] == "17/07/2026"
    assert row["Compra hora"] == "15:00"


def test_multiple_pending_orders_or_quantity_mismatch_are_unavailable():
    history = _history(
        local_broker_orders=[
            _pending("one"),
            _pending("two"),
        ]
    )
    assert resolve_position_purchase(history, "AAPL", 1)["warning"] == "ambiguous_pending_buy_orders"

    mismatch = _history(local_broker_orders=[_pending("one", qty=2)])
    assert resolve_position_purchase(mismatch, "AAPL", 1)["purchase_timestamp_status"] == "unavailable"

    mixed = _history(
        local_broker_orders=[_pending("one", qty=1), _pending("other", qty=2)]
    )
    assert resolve_position_purchase(mixed, "AAPL", 1)["warning"] == "ambiguous_pending_buy_orders"


def test_pending_without_position_or_invalid_timestamp_is_unavailable():
    history = {"local_broker_orders": [_pending("one", created_at="not-a-time")]}
    assert resolve_position_purchase(history, "AAPL", None)["purchase_timestamp_status"] == "unavailable"
    assert resolve_position_purchase(_history(local_broker_orders=history["local_broker_orders"]), "AAPL", 1)[
        "purchase_timestamp_status"
    ] == "unavailable"


def test_historical_open_buy_blocks_weak_pending_attribution_but_closed_lot_allows_it():
    blocked = _history(
        executed_buy_lots_by_symbol={"AAPL": [_lot("old", authority="unavailable", timestamp="invalid")]},
        local_broker_orders=[_pending("new")],
    )
    assert resolve_position_purchase(blocked, "AAPL", 1)["warning"] == "historical_open_buy_could_be_confused"

    closed = _history(
        executed_buy_lots_by_symbol={"AAPL": [_lot("old", closed=True, open_qty=0)]},
        local_broker_orders=[_pending("new")],
    )
    assert resolve_position_purchase(closed, "AAPL", 1)["broker_order_id"] == "new"


def test_pending_to_filled_reconciliation_replaces_provisional_without_mutation():
    pending = _history(local_broker_orders=[_pending("order", created_at="2026-07-17T14:00:00Z")])
    provisional = resolve_position_purchase(pending, "AAPL", 1)
    filled = _history(
        executed_buy_lots_by_symbol={"AAPL": [_lot("order", timestamp="2026-07-17T14:02:00Z")]},
        local_broker_orders=pending["local_broker_orders"],
    )

    verified = resolve_position_purchase(filled, "AAPL", 1)

    assert provisional["purchase_timestamp_status"] == "provisional_order"
    assert verified["purchase_timestamp_status"] == "verified_fill"
    assert verified["purchase_timestamp"] != provisional["purchase_timestamp"]
    assert pending["local_broker_orders"][0]["status"] == "OrderStatus.PENDING_NEW"


def test_side_and_pending_without_fill_are_strictly_local_buy_only():
    history = _history(
        local_broker_orders=[
            _pending("sell", side="OrderSide.SELL"),
            _pending("cancelled", status="cancelled"),
            _pending("buy", status="PENDING_NEW"),
        ]
    )
    assert resolve_position_purchase(history, "AAPL", 1)["broker_order_id"] == "buy"


def test_sort_is_descending_and_tie_breaks_by_broker_order_id():
    rows = [
        {"Simbolo": "OLD", "Compra ISO": "2026-07-17T12:00:00Z", "Compra broker_order_id": "z"},
        {"Simbolo": "NEW", "Compra ISO": "2026-07-17T13:00:00Z", "Compra broker_order_id": "b"},
        {"Simbolo": "TIE-Z", "Compra ISO": "2026-07-17T14:00:00Z", "Compra broker_order_id": "z"},
        {"Simbolo": "TIE-A", "Compra ISO": "2026-07-17T14:00:00Z", "Compra broker_order_id": "a"},
        {"Simbolo": "UNKNOWN", "Compra ISO": None, "Compra broker_order_id": "a"},
    ]
    assert [row["Simbolo"] for row in sorted(rows, key=_position_purchase_sort_key)] == [
        "TIE-A",
        "TIE-Z",
        "NEW",
        "OLD",
        "UNKNOWN",
    ]


def test_provisional_authority_is_display_only_and_no_extra_fields_are_added():
    history = _history(local_broker_orders=[_pending("order")])
    before = repr(history)
    result = resolve_position_purchase(history, "AAPL", 1)
    after = repr(history)

    assert result["purchase_timestamp_status"] == "provisional_order"
    assert before == after
    assert "time_stop" not in result
    assert "unrealized_pl" not in result
    assert "filled_at" not in result


def test_recent_open_positions_get_unique_provisional_order_dates():
    positions = [
        ("BBY", 11, "bby-id", "2026-07-17T16:08:37.458720+00:00"),
        ("MTB", 3, "mtb-id", "2026-07-17T16:08:40.591962+00:00"),
        ("VTR", 10, "vtr-id", "2026-07-17T16:08:35.793221+00:00"),
        ("VTRS", 57, "vtrs-id", "2026-07-17T16:08:39.012575+00:00"),
    ]
    history = {
        "open_positions": [{"symbol": symbol, "qty": qty} for symbol, qty, _, _ in positions],
        "executed_buy_lots_by_symbol": {},
        "local_broker_orders": [
            _pending(order_id, symbol=symbol, qty=qty, created_at=created_at)
            for symbol, qty, order_id, created_at in positions
        ],
    }

    rows = _position_rows(history, local_timezone="Europe/Madrid")
    rows_by_symbol = {row["Simbolo"]: row for row in rows}

    assert all(row["Compra estado"] == "provisional_order" for row in rows)
    assert rows_by_symbol["BBY"]["Compra hora"] == "18:08"
    assert rows_by_symbol["MTB"]["Compra broker_order_id"] == "mtb-id"
    assert [row["Simbolo"] for row in sorted(rows, key=_position_purchase_sort_key)] == [
        "MTB",
        "VTRS",
        "BBY",
        "VTR",
    ]
