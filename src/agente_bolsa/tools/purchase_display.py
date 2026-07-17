"""Deterministic, read-only purchase authority for portfolio presentation.

This module is deliberately scoped to the dashboard.  It consumes the local
history already assembled by ``trade_history`` and never calls a broker or
persists anything.  In particular, a provisional order timestamp is not an
entry-fill timestamp and must not be reused by risk, learning, or time-stop
code.
"""

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any

from .time_stop_policy import canonical_order_side

_PENDING_ORDER_STATUSES = {
    "pending",
    "pending_new",
    "new",
    "accepted",
    "accepted_for_bidding",
    "calculated",
    "held",
}


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _status(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("orderstatus."):
        text = text.split(".", 1)[1]
    return text.replace("-", "_").replace(" ", "_")


def _is_pending_order(order: dict[str, Any]) -> bool:
    values = [order.get("status")]
    payload = order.get("payload")
    if isinstance(payload, dict):
        broker = payload.get("broker_order")
        if isinstance(broker, dict):
            values.append(broker.get("status"))
        nested_order = payload.get("order")
        if isinstance(nested_order, dict):
            values.append(nested_order.get("status"))
    return any(_status(value) in _PENDING_ORDER_STATUSES for value in values)


def _order_quantity(order: dict[str, Any]) -> float | None:
    direct = _number(order.get("qty"))
    if direct is not None:
        return direct
    payload = order.get("payload")
    if not isinstance(payload, dict):
        return None
    for candidate in (
        payload.get("qty"),
        (payload.get("order") or {}).get("qty") if isinstance(payload.get("order"), dict) else None,
        (payload.get("broker_order") or {}).get("qty")
        if isinstance(payload.get("broker_order"), dict)
        else None,
        (payload.get("plan") or {}).get("payload", {}).get("qty")
        if isinstance(payload.get("plan"), dict)
        and isinstance((payload.get("plan") or {}).get("payload"), dict)
        else None,
    ):
        number = _number(candidate)
        if number is not None:
            return number
    return None


def _order_timestamp(order: dict[str, Any]) -> tuple[datetime, str, str] | None:
    payload = order.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    nested = []
    for key in ("broker_order", "order"):
        value = payload.get(key)
        if isinstance(value, dict):
            nested.append(value)
    # The local row's ``time`` is the durable broker-order created_at.  More
    # specific lifecycle timestamps always win when they are available.
    fields = (
        ("submitted_at", "submitted_at"),
        ("accepted_at", "accepted_at"),
        ("created_at", "created_at"),
    )
    sources = [order, payload, *nested]
    for field, source_name in fields:
        for source in sources:
            parsed = _timestamp(source.get(field))
            if parsed is not None:
                return parsed, source_name, str(source.get(field))
    parsed = _timestamp(order.get("time"))
    if parsed is not None:
        return parsed, "created_at", str(order.get("time"))
    return None


def _filled_buy_lot(lot: Any, symbol: str) -> bool:
    if not isinstance(lot, dict):
        return False
    if str(lot.get("symbol") or "").upper() != symbol:
        return False
    if not lot.get("broker_order_id") or canonical_order_side(lot.get("order_side")) != "buy":
        return False
    if lot.get("order_status_verified") is False:
        return False
    filled_qty = _number(lot.get("filled_qty"))
    return filled_qty is not None and filled_qty > 0


def _verified_fill_candidates(history: dict[str, Any], symbol: str) -> list[tuple[datetime, str, str, str]]:
    lots_by_symbol = history.get("executed_buy_lots_by_symbol")
    lots = lots_by_symbol.get(symbol) if isinstance(lots_by_symbol, dict) else None
    if not isinstance(lots, list):
        return []
    candidates: list[tuple[datetime, str, str, str]] = []
    for lot in lots:
        if not _filled_buy_lot(lot, symbol):
            continue
        if lot.get("closed") is True:
            continue
        open_qty = _number(lot.get("open_qty"))
        if open_qty is not None and open_qty <= 0:
            continue
        authority = str(lot.get("fill_authority") or "").strip()
        if lot.get("is_partial") and authority != "first_fill_at":
            continue
        if authority not in {"first_fill_at", "aggregated_filled_at"}:
            continue
        raw_time = str(lot.get("entry_fill_at") or "").strip()
        parsed = _timestamp(raw_time)
        if parsed is None:
            continue
        candidates.append((parsed, str(lot.get("broker_order_id")), raw_time, authority))
    return candidates


def _historical_buy_is_ambiguous(lot: Any, symbol: str) -> bool:
    """Return whether an older filled BUY could still be the open lot.

    A local history that explicitly says a lot is closed (or has zero
    ``open_qty``) is safe to ignore.  Without that evidence we do not guess
    that a pending order belongs to the current position.
    """

    if not _filled_buy_lot(lot, symbol):
        return False
    if lot.get("closed") is True:
        return False
    open_qty = _number(lot.get("open_qty"))
    if open_qty is not None and open_qty <= 0:
        return False
    return True


def resolve_position_purchase(
    history: dict[str, Any],
    symbol: str,
    position_qty: Any,
) -> dict[str, Any]:
    """Resolve the display-only purchase authority for one open position."""

    target = str(symbol or "").upper().strip()
    qty = _number(position_qty)
    unavailable = {
        "purchase_timestamp": None,
        "purchase_timestamp_status": "unavailable",
        "purchase_timestamp_source": None,
        "broker_order_id": None,
        "warning": None,
    }
    if not target or qty is None or qty <= 0:
        unavailable["warning"] = "position_identity_or_quantity_unavailable"
        return unavailable

    lots_by_symbol = history.get("executed_buy_lots_by_symbol")
    lots = lots_by_symbol.get(target) if isinstance(lots_by_symbol, dict) else []
    lots = lots if isinstance(lots, list) else []
    verified = _verified_fill_candidates(history, target)
    if verified:
        _, order_id, raw_time, authority = max(verified, key=lambda item: (item[0], item[1]))
        label = "Compra verificada"
        warning = "latest_verified_buy_lot" if len(verified) > 1 else None
        if authority == "aggregated_filled_at":
            label = "Compra verificada (fill agregado completo)"
        return {
            "purchase_timestamp": raw_time,
            "purchase_timestamp_status": "verified_fill",
            "purchase_timestamp_source": authority,
            "broker_order_id": order_id,
            "purchase_label": label,
            "warning": warning,
        }

    if any(_historical_buy_is_ambiguous(lot, target) for lot in lots):
        unavailable["warning"] = "historical_open_buy_could_be_confused"
        return unavailable

    orders = history.get("local_broker_orders")
    if not isinstance(orders, list):
        unavailable["warning"] = "no_local_buy_order_evidence"
        return unavailable

    candidates: dict[str, tuple[dict[str, Any], tuple[datetime, str, str]]] = {}
    for order in orders:
        if not isinstance(order, dict):
            continue
        if str(order.get("symbol") or "").upper().strip() != target:
            continue
        if canonical_order_side(order.get("side")) != "buy" or not _is_pending_order(order):
            continue
        order_id = str(order.get("broker_order_id") or "").strip()
        if not order_id:
            continue
        order_qty = _order_quantity(order)
        if order_qty is None or not isfinite(order_qty) or not abs(order_qty - qty) <= 1e-6:
            continue
        timestamp = _order_timestamp(order)
        if timestamp is None:
            continue
        existing = candidates.get(order_id)
        if existing is not None and existing[1] != timestamp:
            unavailable["warning"] = "conflicting_pending_order_evidence"
            return unavailable
        candidates[order_id] = (order, timestamp)

    if not candidates:
        unavailable["warning"] = "no_unique_compatible_pending_buy"
        return unavailable
    if len(candidates) != 1:
        unavailable["warning"] = "ambiguous_pending_buy_orders"
        return unavailable

    order_id, (_, (parsed, source, raw_time)) = next(iter(candidates.items()))
    return {
        "purchase_timestamp": raw_time,
        "purchase_timestamp_status": "provisional_order",
        "purchase_timestamp_source": source,
        "broker_order_id": order_id,
        "purchase_label": "Orden de compra pendiente",
        "warning": "provisional_until_filled_reconciliation",
    }
