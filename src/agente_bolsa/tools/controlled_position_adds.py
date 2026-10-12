"""Fail-closed, non-executing guard for controlled position-add sublots.

This module consumes provider-neutral carriers.  It deliberately does not
import the broker or execution boundaries and never returns order authority.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

from ..market_calendar import MarketCalendar

SCHEMA_VERSION = "controlled_position_add.v1"
AUTHORITY = "guard_only"
SUPPORTED_PROVIDER = "alpaca"
DEFAULT_POLICY: dict[str, Any] = {
    "enabled": False,
    "mode": "shadow",
    "max_symbol_exposure_pct": 0.05,
    "max_add_pct_equity": 0.025,
    "max_total_risk_pct": 0.03,
    "max_add_risk_pct": 0.01,
    "max_add_trade_risk_pct": 0.01,
}

_IMMUTABLE_POLICY_MAXIMA = {
    "max_symbol_exposure_pct": 0.05,
    "max_add_pct_equity": 0.025,
    "max_total_risk_pct": 0.03,
    "max_add_risk_pct": 0.01,
    "max_add_trade_risk_pct": 0.01,
}
_ADD_ACTIONS = frozenset({"add", "position_add", "controlled_position_add", "buy", "buy_to_open"})
_UNFILLED_CANCEL_STATUSES = frozenset({"rejected", "cancelled", "canceled"})

_ACTIVE_STATUSES = frozenset(
    {
        "accepted",
        "held",
        "new",
        "open",
        "partially_filled",
        "pending_new",
        "pending_replace",
        "pending",
        "queued",
        "submitted",
        "working",
    }
)
_TERMINAL_STATUSES = frozenset(
    {"cancelled", "canceled", "done_for_day", "expired", "filled", "rejected", "stopped"}
)
_VALID_PROTECTION_STATUSES = frozenset({"accepted", "active", "confirmed", "held", "new", "open", "working"})
_VALID_LINEAGE_STATUSES = frozenset({"complete", "confirmed", "verified"})
_XNYS_TZ = ZoneInfo("America/New_York")


def _as_mapping(value: Any) -> dict[str, Any]:
    """Read mappings and simple domain carriers without provider imports."""

    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    as_dict = getattr(value, "as_dict", None)
    if callable(as_dict):
        result = as_dict()
        return dict(result) if isinstance(result, Mapping) else {}
    raw = getattr(value, "__dict__", None)
    return dict(raw) if isinstance(raw, Mapping) else {}


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = _text(value)
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in {"true", "yes", "valid", "passed", "verified", "confirmed"}:
            return True
        if raw in {"false", "no", "invalid", "failed", "unavailable"}:
            return False
    return None


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None and value != "":
            return value
    return None


def _lineage(item: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("lineage", "decision_lineage", "fill_authority"):
        nested = item.get(key)
        if isinstance(nested, Mapping):
            result.update(nested)
    result.update({key: value for key, value in item.items() if key not in {"lineage", "decision_lineage"}})
    return result


_LINEAGE_ID_FIELDS = frozenset(
    {
        "broker_order_id",
        "candidate_id",
        "capture_id",
        "cycle_id",
        "lineage_id",
        "lineage_status",
        "plan_id",
        "recommendation_id",
        "signal_capture_id",
        "signal_id",
    }
)


def _lineage_conflicts(item: Mapping[str, Any]) -> set[str]:
    """Return identity fields whose root and nested lineage disagree."""

    nested_values: dict[str, set[str]] = {}
    for key in ("lineage", "decision_lineage", "fill_authority"):
        nested = item.get(key)
        if not isinstance(nested, Mapping):
            continue
        for field in _LINEAGE_ID_FIELDS:
            value = _text(nested.get(field))
            if value:
                nested_values.setdefault(field, set()).add(value)
    conflicts = {field for field, values in nested_values.items() if len(values) > 1}
    for field in _LINEAGE_ID_FIELDS:
        root = _text(item.get(field))
        nested = nested_values.get(field, set())
        if root and nested and root not in nested:
            conflicts.add(field)
    return conflicts


def _symbol(item: Mapping[str, Any]) -> str:
    return _text(_first(item, "symbol", "ticker")).upper()


def _status(item: Mapping[str, Any]) -> str:
    return _text(_first(item, "status", "order_status", "state")).lower().rsplit(".", 1)[-1]


def _items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [_as_mapping(item) for item in value]


def _add_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _policy(policy: Mapping[str, Any] | None) -> dict[str, Any]:
    result = dict(DEFAULT_POLICY)
    if isinstance(policy, Mapping):
        result.update(policy)
    return result


def _session_carrier(context: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("session_carrier", "calendar_carrier", "xnys_session_carrier"):
        carrier = context.get(key)
        if isinstance(carrier, Mapping):
            return dict(carrier)
    calendar = context.get("calendar")
    if isinstance(calendar, Mapping) and (
        "completed_sessions" in calendar or "sessions" in calendar or "current_session_date" in calendar
    ):
        return dict(calendar)
    return {}


def _session_key(carrier: Mapping[str, Any], signal: Mapping[str, Any]) -> str:
    return _text(
        _first(
            carrier,
            "current_session_id",
            "current_session_date",
            "session_id",
            "session_date",
        )
        or _first(signal, "session_id", "session_date")
    )


def _session_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(_XNYS_TZ).date().isoformat()
    raw = _text(value)
    if not raw:
        return ""
    parsed = _datetime(raw)
    if parsed is not None:
        return parsed.astimezone(_XNYS_TZ).date().isoformat()
    return raw[:10] if len(raw) >= 10 else ""


def _prior_fill_check(
    prior_fill: Mapping[str, Any],
    reasons: list[str],
) -> tuple[dict[str, Any], datetime | None, str]:
    data = _lineage(prior_fill)
    side = _text(_first(data, "side", "action")).lower()
    if side not in {"buy", "long", "buy_to_open"}:
        _add_reason(reasons, "prior_fill_not_buy")
    status = _status(data)
    if status not in {"filled", "partially_filled", "complete", "completed"}:
        _add_reason(reasons, "prior_fill_not_confirmed")

    required = {
        "broker_order_id": _first(data, "broker_order_id", "order_id", "id"),
        "signal_id": _first(data, "signal_id"),
        "signal_capture_id": _first(data, "signal_capture_id", "capture_id"),
        "filled_at": _first(data, "filled_at", "completed_at", "timestamp"),
    }
    if any(not _text(value) for value in required.values()):
        _add_reason(reasons, "fill_lineage_missing_exact_ids")

    lineage_status = _text(
        _first(data, "fill_authority_status", "linkage_status", "lineage_status", "authority_status")
    ).lower()
    if not lineage_status:
        _add_reason(reasons, "fill_lineage_authority_status_unavailable")
    elif lineage_status not in _VALID_LINEAGE_STATUSES:
        _add_reason(reasons, "fill_lineage_unverified")

    filled_at = _datetime(required["filled_at"])
    if filled_at is None:
        _add_reason(reasons, "prior_fill_timestamp_unavailable_or_naive")
    filled_qty = _number(_first(data, "filled_qty", "qty", "quantity"))
    if filled_qty is None or filled_qty <= 0:
        _add_reason(reasons, "prior_fill_quantity_unavailable")
    return data, filled_at, _session_date(_first(data, "session_date", "fill_session_date"))


def _new_signal_check(
    context: Mapping[str, Any],
    prior: Mapping[str, Any],
    prior_filled_at: datetime | None,
    reasons: list[str],
) -> tuple[dict[str, Any], datetime | None]:
    raw_signal = context.get("new_signal") or context.get("candidate") or context.get("signal")
    signal = _lineage(_as_mapping(raw_signal))
    new_signal_id = _text(_first(signal, "signal_id"))
    new_capture_id = _text(_first(signal, "signal_capture_id", "capture_id"))
    if not new_signal_id or not new_capture_id:
        _add_reason(reasons, "new_signal_lineage_missing_exact_ids")
    if new_signal_id and new_signal_id == _text(_first(prior, "signal_id")):
        _add_reason(reasons, "new_signal_id_reused")
    if new_capture_id and new_capture_id == _text(_first(prior, "signal_capture_id", "capture_id")):
        _add_reason(reasons, "new_signal_capture_id_reused")

    side = _text(_first(signal, "side", "action")).lower()
    if side not in {"buy", "long", "buy_to_open"}:
        _add_reason(reasons, "controlled_add_requires_buy_signal")
    captured_at = _datetime(
        _first(signal, "captured_at", "signal_captured_at", "created_at", "decision_at", "timestamp")
    )
    if captured_at is None:
        _add_reason(reasons, "new_signal_timestamp_unavailable_or_naive")
    elif prior_filled_at is not None and captured_at <= prior_filled_at:
        _add_reason(reasons, "new_signal_not_after_prior_fill")
    return signal, captured_at


def _completed_session_check(
    carrier: Mapping[str, Any],
    prior_filled_at: datetime | None,
    prior_session_date: str,
    as_of: datetime | None,
    reasons: list[str],
) -> str:
    calendar_name = _text(_first(carrier, "calendar", "calendar_name", "venue")).upper()
    if calendar_name != "XNYS":
        _add_reason(reasons, "xnys_calendar_carrier_unavailable")
    current_session_date = _session_date(_first(carrier, "current_session_date", "session_date"))
    current_key = _session_key(carrier, {})
    if not prior_session_date:
        _add_reason(reasons, "prior_fill_session_unavailable")
    if not current_session_date:
        _add_reason(reasons, "current_xnys_session_unavailable")
    if as_of is None:
        _add_reason(reasons, "session_as_of_unavailable")
    if not current_key:
        _add_reason(reasons, "current_xnys_session_unavailable")

    records = _first(carrier, "completed_sessions", "sessions_completed", "sessions")
    sessions = _items(records)
    record_dates = {
        _session_date(_first(record, "session_date", "date"))
        for record in sessions
        if _session_date(_first(record, "session_date", "date"))
    }
    if prior_session_date:
        record_dates.add(prior_session_date)
    if current_session_date:
        record_dates.add(current_session_date)
    schedule_closes: dict[str, datetime] = {}
    if record_dates:
        try:
            schedule = MarketCalendar("XNYS").session_schedule(
                min(record_dates),
                max(record_dates),
            )
        except Exception:
            schedule = None
        if schedule is None:
            _add_reason(reasons, "xnys_calendar_schedule_unavailable")
        else:
            for index, row in schedule.iterrows():
                date_value = index.date() if hasattr(index, "date") else index
                date_key = date_value.isoformat() if hasattr(date_value, "isoformat") else _text(date_value)
                close_value = row.get("market_close") if hasattr(row, "get") else None
                close_dt = _datetime(
                    close_value.to_pydatetime() if hasattr(close_value, "to_pydatetime") else close_value
                )
                if date_key and close_dt is not None:
                    schedule_closes[date_key] = close_dt
    if current_session_date and current_session_date not in schedule_closes:
        _add_reason(reasons, "current_xnys_session_not_in_calendar")
    if prior_session_date and prior_session_date not in schedule_closes:
        _add_reason(reasons, "prior_fill_session_not_in_calendar")
    if current_session_date and as_of is not None:
        decision_session_date = as_of.astimezone(_XNYS_TZ).date().isoformat()
        if current_session_date > decision_session_date:
            _add_reason(reasons, "current_xnys_session_after_decision")

    completed_after = False
    for record in sessions:
        status = _status(record)
        if status not in {"completed", "closed", "settled"}:
            continue
        record_date = _session_date(_first(record, "session_date", "date"))
        supplied_close = _datetime(
            _first(record, "completed_at", "close_utc", "market_close", "closed_at", "ended_at")
        )
        actual_close = schedule_closes.get(record_date)
        if not record_date or actual_close is None:
            if record_date:
                _add_reason(reasons, "xnys_session_not_in_calendar")
            continue
        if supplied_close is None:
            _add_reason(reasons, "xnys_session_close_unavailable")
            continue
        if supplied_close != actual_close:
            _add_reason(reasons, "xnys_session_close_mismatch")
            continue
        if prior_filled_at is None or as_of is None:
            continue
        if actual_close > as_of:
            _add_reason(reasons, "xnys_session_close_after_decision")
            continue
        if actual_close > prior_filled_at and prior_session_date and record_date > prior_session_date:
            completed_after = True
    if not completed_after:
        _add_reason(reasons, "missing_completed_xnys_session_after_prior_fill")
    return current_key


def _valid_bool_carrier(value: Any, *, field: str, reasons: list[str]) -> None:
    data = _as_mapping(value)
    if not data:
        _add_reason(reasons, f"{field}_unavailable")
        return
    candidate = _first(data, "valid", "is_valid", "passed", "all_passed", "status")
    parsed = _bool(candidate)
    if parsed is not True:
        _add_reason(reasons, f"{field}_invalid")


def _capability_supported(context: Mapping[str, Any], reasons: list[str]) -> bool:
    broker = _as_mapping(context.get("broker"))
    provider = _text(_first(context, "broker_provider", "provider") or _first(broker, "provider", "name")).lower()
    capabilities = context.get("broker_capabilities") or context.get("broker_carrier") or broker
    capability_data = _as_mapping(capabilities)
    bracket = _first(capability_data, "canonical_bracket", "canonical_bracket_capability", "bracket_capability")
    bracket_data = _as_mapping(bracket)
    if provider != SUPPORTED_PROVIDER:
        _add_reason(reasons, "unsupported_broker")
    proven = _bool(_first(bracket_data, "verified", "confirmed", "demonstrated")) is True
    if _text(_first(bracket_data, "status", "verification")).lower() in {"available", "confirmed", "verified"}:
        proven = True
    supports_parent_legs = _bool(
        _first(bracket_data, "supports_parent_legs", "parent_legs_supported", "legs_supported")
    ) is True
    route = _text(_first(bracket_data, "route", "canonical_route", "kind")).lower()
    if not (
        provider == SUPPORTED_PROVIDER
        and _bool(_first(bracket_data, "supported", "available")) is True
        and proven
        and supports_parent_legs
        and route in {"canonical_bracket", "bracket", "oco_bracket"}
    ):
        _add_reason(reasons, "controlled_add_protection_unavailable")
        return False
    return True


def _protection_check(
    context: Mapping[str, Any],
    position: Mapping[str, Any],
    prior_fill: Mapping[str, Any],
    reasons: list[str],
) -> set[str]:
    capability_ok = _capability_supported(context, reasons)
    protection = _as_mapping(
        context.get("existing_protection") or context.get("protection") or context.get("existing_bracket")
    )
    if not protection:
        _add_reason(reasons, "existing_protection_evidence_unavailable")
        return set()
    validation_start = len(reasons)
    status = _text(_first(protection, "status", "state")).lower()
    if status not in _VALID_PROTECTION_STATUSES:
        _add_reason(reasons, "existing_protection_not_confirmed")
    symbol = _symbol(position)
    if not symbol:
        _add_reason(reasons, "position_symbol_unavailable")
    if not _symbol(protection):
        _add_reason(reasons, "existing_protection_symbol_unavailable")
    elif _symbol(protection) != symbol:
        _add_reason(reasons, "existing_protection_symbol_mismatch")
    position_qty = _number(_first(position, "qty", "quantity"))
    protected_qty = _number(_first(protection, "protected_qty", "existing_qty", "qty", "quantity"))
    prior_qty = _number(_first(prior_fill, "filled_qty", "qty", "quantity"))
    if position_qty is None or position_qty <= 0 or protected_qty is None or protected_qty != position_qty:
        _add_reason(reasons, "existing_protection_qty_mismatch")
    lot_filled_qty = _number(_first(protection, "lot_filled_qty", "filled_qty", "matched_filled_qty"))
    if prior_qty is None or lot_filled_qty is None or lot_filled_qty != prior_qty:
        _add_reason(reasons, "existing_protection_fill_qty_mismatch")

    parent_id = _text(_first(protection, "parent_order_id", "parent_id"))
    oco_id = _text(_first(protection, "oco_group_id", "oco_id", "group_id"))
    prior_order_id = _text(_first(prior_fill, "broker_order_id", "order_id", "id"))
    if not prior_order_id:
        _add_reason(reasons, "prior_fill_broker_order_id_unavailable")
    if not parent_id or parent_id != prior_order_id:
        _add_reason(reasons, "existing_protection_parent_mismatch")
    if not oco_id:
        _add_reason(reasons, "existing_protection_oco_unavailable")
    legs = _items(_first(protection, "legs", "children", "orders"))
    if not legs or len(legs) < 2:
        _add_reason(reasons, "existing_protection_parent_legs_unavailable")
        return set()
    leg_ids: set[str] = set()
    leg_roles: set[str] = set()
    for leg in legs:
        leg_symbol = _symbol(leg)
        if not leg_symbol or leg_symbol != symbol:
            _add_reason(reasons, "existing_protection_leg_symbol_mismatch")
        leg_side = _text(_first(leg, "side", "action")).lower()
        if leg_side not in {"sell", "sell_to_close"}:
            _add_reason(reasons, "existing_protection_leg_side_mismatch")
        leg_status = _status(leg)
        if leg_status not in _VALID_PROTECTION_STATUSES:
            _add_reason(reasons, "existing_protection_leg_not_confirmed")
        leg_parent = _text(_first(leg, "parent_order_id", "parent_id"))
        leg_oco = _text(_first(leg, "oco_group_id", "oco_id", "group_id"))
        if not prior_order_id or leg_parent != prior_order_id:
            _add_reason(reasons, "existing_protection_parent_mismatch")
        if not oco_id or leg_oco != oco_id:
            _add_reason(reasons, "existing_protection_oco_mismatch")
        leg_qty = _number(_first(leg, "qty", "quantity", "protected_qty"))
        if position_qty is None or leg_qty is None or leg_qty != position_qty:
            _add_reason(reasons, "existing_protection_leg_qty_mismatch")
        leg_id = _text(_first(leg, "broker_order_id", "order_id", "id"))
        if not leg_id:
            _add_reason(reasons, "existing_protection_leg_id_unavailable")
        elif leg_id in leg_ids or leg_id == parent_id:
            _add_reason(reasons, "existing_protection_duplicate_leg_id")
        else:
            leg_ids.add(leg_id)
        leg_roles.add(_text(_first(leg, "role", "order_role", "leg_type")).lower())
    has_stop = bool(leg_roles & {"stop", "stop_loss", "protective_stop"})
    has_take = bool(leg_roles & {"take", "take_profit", "protective_take_profit"})
    if not has_stop or not has_take:
        _add_reason(reasons, "existing_protection_stop_take_roles_unavailable")
    if not capability_ok or len(reasons) != validation_start:
        return set()
    return leg_ids


def _orders(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for key in ("open_orders", "pending_orders"):
        result.extend(_items(context.get(key)))
    return result


def _active_order_checks(
    context: Mapping[str, Any],
    symbol: str,
    protected_ids: set[str],
    reasons: list[str],
) -> None:
    for order in _orders(context):
        order_symbol = _symbol(order)
        if not order_symbol:
            _add_reason(reasons, "open_order_symbol_unavailable")
            continue
        if order_symbol != symbol:
            continue
        status = _status(order)
        if status not in _ACTIVE_STATUSES and status not in _TERMINAL_STATUSES:
            _add_reason(reasons, "open_order_status_unknown")
            continue
        if status in _TERMINAL_STATUSES:
            continue
        side = _text(_first(order, "side", "action")).lower()
        order_id = _text(_first(order, "broker_order_id", "order_id", "id"))
        if not side:
            _add_reason(reasons, "open_order_side_unavailable")
            continue
        protective = bool(order_id) and order_id in protected_ids
        if side in {"buy", "long", "buy_to_open"}:
            _add_reason(reasons, "pending_buy")
        elif side in {"sell", "short", "sell_to_close"} and not protective:
            _add_reason(reasons, "active_exit")


def _same_session_record(record: Mapping[str, Any], symbol: str, session_key: str) -> bool:
    if _symbol(record) != symbol:
        return False
    record_key = _text(_first(record, "session_id", "session_key", "session_date"))
    if not record_key or not session_key:
        return False
    return record_key == session_key


def _add_occupies_session_slot(record: Mapping[str, Any]) -> bool:
    """Treat successful terminal adds as occupying the one-add session slot."""

    status = _status(record)
    filled_qty = _number(_first(record, "filled_qty", "executed_qty", "filled_quantity"))
    if status in _UNFILLED_CANCEL_STATUSES and (filled_qty is None or filled_qty <= 0):
        return False
    # Unknown/malformed status is conservative: an ambiguous add must block.
    return True


def _duplicate_checks(
    context: Mapping[str, Any],
    symbol: str,
    session_key: str,
    reasons: list[str],
) -> None:
    for record in _items(context.get("position_adds") or context.get("add_history") or context.get("adds")):
        action = _text(_first(record, "action", "side", "kind", "type")).lower()
        if action not in _ADD_ACTIONS:
            continue
        if _add_occupies_session_slot(record) and _same_session_record(record, symbol, session_key):
            _add_reason(reasons, "duplicate_add_same_session")
    for record in _items(context.get("pending_plans") or context.get("pending_order_plans")):
        action = _text(_first(record, "action", "side", "kind", "type")).lower()
        if action not in _ADD_ACTIONS:
            continue
        if _add_occupies_session_slot(record) and _same_session_record(record, symbol, session_key):
            _add_reason(reasons, "duplicate_planned_add")


def _pending_plan_is_active(record: Mapping[str, Any]) -> bool:
    status = _status(record)
    if status in _UNFILLED_CANCEL_STATUSES:
        filled_qty = _number(_first(record, "filled_qty", "executed_qty", "filled_quantity"))
        return filled_qty is not None and filled_qty > 0
    if status in {"expired", "done_for_day", "stopped", "filled", "completed", "complete"}:
        return False
    # Unknown pending status is active for a fail-closed cash/risk reservation.
    return True


def _capital_checks(
    context: Mapping[str, Any],
    policy: Mapping[str, Any],
    position: Mapping[str, Any],
    symbol: str,
    add_qty: float | None,
    add_price: float | None,
    reasons: list[str],
) -> dict[str, float | None]:
    account = _as_mapping(context.get("account"))
    equity_raw = _first(context, "equity", "portfolio_value", "account_equity")
    if equity_raw is None:
        equity_raw = _first(account, "equity", "portfolio_value")
    equity = _number(equity_raw)
    if equity is None or equity <= 0:
        _add_reason(reasons, "equity_unavailable")
    elif equity < 0:
        _add_reason(reasons, "negative_value_rejected")

    add_notional = add_qty * add_price if add_qty is not None and add_price is not None else None
    if add_notional is None or add_notional <= 0:
        _add_reason(reasons, "add_notional_unavailable")
    elif add_notional < 0:
        _add_reason(reasons, "negative_value_rejected")

    position_value = _number(_first(position, "market_value", "notional", "value"))
    if position_value is None:
        position_qty = _number(_first(position, "qty"))
        position_price = _number(_first(position, "current_price", "price"))
        if position_qty is not None and position_price is not None:
            position_value = position_qty * position_price
    if position_value is None:
        _add_reason(reasons, "existing_symbol_exposure_unavailable")
    elif position_value < 0:
        _add_reason(reasons, "negative_value_rejected")

    pending_value = 0.0
    pending_cash_reserved = 0.0
    pending_risk_pct = 0.0
    pending_risk_unknown = False
    for record in _items(context.get("pending_plans") or context.get("pending_order_plans")):
        if not _pending_plan_is_active(record):
            continue
        side = _text(_first(record, "side", "action", "kind", "type")).lower()
        if side not in _ADD_ACTIONS:
            continue
        value_raw = _first(
            record,
            "notional",
            "planned_notional",
            "value",
            "limit_notional",
            "estimated_notional",
        )
        value = _number(value_raw)
        if value is None or value <= 0:
            _add_reason(reasons, "pending_plan_notional_unavailable")
        else:
            pending_cash_reserved += value
            if _symbol(record) == symbol:
                pending_value += value
        risk_raw = _first(
            record,
            "risk_pct",
            "planned_risk_pct",
            "add_risk_pct",
            "position_add_risk_pct",
        )
        pending_risk = _number(risk_raw)
        if pending_risk is None:
            pending_risk_unknown = True
            _add_reason(reasons, "pending_plan_risk_unavailable")
        elif pending_risk < 0:
            pending_risk_unknown = True
            _add_reason(reasons, "negative_risk_rejected")
        else:
            pending_risk_pct += pending_risk

    symbol_value = (position_value or 0.0) + pending_value + (add_notional or 0.0)
    symbol_pct = symbol_value / equity if equity and equity > 0 else None
    max_symbol_pct = _number(policy.get("max_symbol_exposure_pct"))
    if max_symbol_pct is None:
        _add_reason(reasons, "symbol_exposure_limit_unavailable")
    elif max_symbol_pct < 0:
        _add_reason(reasons, "policy_limit_invalid")
    elif symbol_pct is None:
        _add_reason(reasons, "symbol_exposure_limit_unavailable")
    elif symbol_pct > max_symbol_pct + 1e-12:
        _add_reason(reasons, "symbol_exposure_limit_exceeded")

    add_pct = add_notional / equity if add_notional is not None and equity and equity > 0 else None
    max_add_pct = _number(policy.get("max_add_pct_equity"))
    if max_add_pct is None:
        _add_reason(reasons, "add_size_limit_unavailable")
    elif max_add_pct < 0:
        _add_reason(reasons, "policy_limit_invalid")
    elif add_pct is None:
        _add_reason(reasons, "add_size_limit_unavailable")
    elif add_pct > max_add_pct + 1e-12:
        _add_reason(reasons, "add_size_limit_exceeded")

    # Buying power is deliberately excluded: only explicitly available cash
    # can fund a candidate add, and pending plans reserve it first.
    cash_raw = _first(context, "cash_available", "available_cash")
    if cash_raw is None:
        cash_raw = _first(account, "cash_available", "cash")
    cash = _number(cash_raw)
    if cash is None:
        _add_reason(reasons, "cash_available_unavailable")
    elif cash < 0:
        _add_reason(reasons, "negative_value_rejected")
    elif add_notional is not None and cash - pending_cash_reserved + 1e-12 < add_notional:
        _add_reason(reasons, "cash_available_insufficient")

    risk_data = _as_mapping(context.get("risk"))
    add_risk_raw = _first(context, "add_risk_pct", "position_add_risk_pct")
    if add_risk_raw is None:
        add_risk_raw = _first(risk_data, "add_risk_pct", "position_add_risk_pct")
    add_risk_pct = _number(add_risk_raw)
    if add_risk_pct is None:
        _add_reason(reasons, "add_risk_unavailable")
    elif add_risk_pct < 0:
        _add_reason(reasons, "negative_risk_rejected")

    after_raw = _first(context, "total_risk_after_add_pct", "total_open_risk_after_add_pct")
    if after_raw is None:
        after_raw = _first(risk_data, "total_risk_after_add_pct", "total_open_risk_after_add_pct")
    total_risk_pct = _number(after_raw)
    if total_risk_pct is not None:
        if total_risk_pct < 0:
            _add_reason(reasons, "negative_risk_rejected")
        elif not pending_risk_unknown:
            includes_pending = _bool(
                _first(context, "after_add_includes_pending_risk")
                if "after_add_includes_pending_risk" in context
                else _first(risk_data, "after_add_includes_pending_risk")
            ) is True
            if not includes_pending:
                total_risk_pct += pending_risk_pct
    else:
        baseline_pct_raw = _first(context, "total_risk_pct", "total_open_risk_pct", "open_risk_pct")
        if baseline_pct_raw is None:
            baseline_pct_raw = _first(risk_data, "total_risk_pct", "total_open_risk_pct", "open_risk_pct")
        baseline_pct = _number(baseline_pct_raw)
        if baseline_pct is not None and baseline_pct < 0:
            _add_reason(reasons, "negative_risk_rejected")
        if baseline_pct is None:
            total_risk_raw = _first(context, "total_risk", "total_open_risk")
            if total_risk_raw is None:
                total_risk_raw = _first(risk_data, "total_risk", "total_open_risk")
            total_risk = _number(total_risk_raw)
            baseline_pct = total_risk / equity if total_risk is not None and equity and equity > 0 else None
        if baseline_pct is not None and add_risk_pct is not None and not pending_risk_unknown:
            total_risk_pct = baseline_pct + add_risk_pct + pending_risk_pct
        elif baseline_pct is None:
            _add_reason(reasons, "total_risk_unavailable")

    if pending_risk_unknown:
        _add_reason(reasons, "total_risk_unavailable")

    max_risk_pct = _number(policy.get("max_total_risk_pct"))
    if max_risk_pct is None:
        _add_reason(reasons, "total_risk_unavailable")
    elif max_risk_pct < 0:
        _add_reason(reasons, "policy_limit_invalid")
    elif total_risk_pct is None:
        _add_reason(reasons, "total_risk_unavailable")
    elif total_risk_pct > max_risk_pct + 1e-12:
        _add_reason(reasons, "total_risk_limit_exceeded")

    max_add_risk_pct = _number(policy.get("max_add_risk_pct"))
    if max_add_risk_pct is None:
        max_add_risk_pct = _number(policy.get("max_add_trade_risk_pct"))
    if max_add_risk_pct is None:
        max_add_risk_pct = _IMMUTABLE_POLICY_MAXIMA["max_add_risk_pct"]
    if max_add_risk_pct < 0:
        _add_reason(reasons, "policy_limit_invalid")
    elif add_risk_pct is not None and add_risk_pct > max_add_risk_pct + 1e-12:
        _add_reason(reasons, "add_risk_limit_exceeded")

    return {
        "equity": equity,
        "add_notional": add_notional,
        "symbol_value_after_add": symbol_value,
        "symbol_exposure_pct_after_add": symbol_pct,
        "add_pct_equity": add_pct,
        "cash_available": cash,
        "pending_cash_reserved": pending_cash_reserved,
        "pending_risk_pct": pending_risk_pct,
        "add_risk_pct": add_risk_pct,
        "total_risk_pct_after_add": total_risk_pct,
    }


def _policy_limit_checks(policy: Mapping[str, Any], reasons: list[str]) -> None:
    validated = _bool(
        _first(policy, "validated_higher_guard", "higher_guard_validated", "validated_higher_limits")
    ) is True
    evidence = _as_mapping(_first(policy, "validation_evidence", "higher_guard_evidence"))
    evidence_ok = _text(_first(evidence, "status", "result")).lower() in {
        "validated",
        "verified",
        "confirmed",
    }
    for field, ceiling in _IMMUTABLE_POLICY_MAXIMA.items():
        raw = policy.get(field)
        if raw is None:
            continue
        value = _number(raw)
        if value is None or value < 0:
            _add_reason(reasons, "policy_limit_invalid")
        elif value > ceiling and not (validated and evidence_ok):
            _add_reason(reasons, "policy_exceeds_immutable_maximum")


def evaluate_controlled_position_add(
    context: Mapping[str, Any],
    *,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate one controlled add and return guard evidence only.

    ``context`` is intentionally duck-typed so the coordinator can pass its
    existing canonical carriers without importing this policy into protected
    broker or execution modules.  Missing or ambiguous evidence blocks.
    """

    raw_context = _as_mapping(context)
    selected_policy = _policy(policy)
    reasons: list[str] = []
    _policy_limit_checks(selected_policy, reasons)
    symbol = _symbol(raw_context)
    position = _as_mapping(raw_context.get("position") or raw_context.get("position_snapshot"))
    prior_fill = _as_mapping(raw_context.get("prior_fill") or raw_context.get("fill_authority"))
    raw_signal = raw_context.get("new_signal") or raw_context.get("candidate") or raw_context.get("signal")
    raw_signal_mapping = _as_mapping(raw_signal)
    if _lineage_conflicts(prior_fill) or _lineage_conflicts(raw_signal_mapping):
        _add_reason(reasons, "lineage_conflict")
    prior, prior_filled_at, prior_session_date = _prior_fill_check(prior_fill, reasons)
    signal, captured_at = _new_signal_check(raw_context, prior, prior_filled_at, reasons)
    decision_raw = signal.get("decision_at")
    decision_at = _datetime(decision_raw) if decision_raw is not None else captured_at
    if decision_raw is not None and decision_at is None:
        _add_reason(reasons, "decision_timestamp_unavailable_or_naive")
    if not symbol:
        _add_reason(reasons, "symbol_unavailable")
    if not position:
        _add_reason(reasons, "position_unavailable")
    elif _symbol(position) and _symbol(position) != symbol:
        _add_reason(reasons, "position_symbol_mismatch")

    pnl = _number(_first(position, "unrealized_pl", "unrealized_pnl", "open_pl"))
    if pnl is None or pnl <= 0:
        _add_reason(reasons, "position_unrealized_pl_not_positive")
    _valid_bool_carrier(raw_context.get("thesis") or raw_context.get("thesis_carrier"), field="thesis", reasons=reasons)
    _valid_bool_carrier(raw_context.get("gates") or raw_context.get("gate_carrier"), field="gates", reasons=reasons)

    carrier = _session_carrier(raw_context)
    current_session = _completed_session_check(
        carrier,
        prior_filled_at,
        prior_session_date,
        decision_at,
        reasons,
    )
    if not current_session:
        current_session = _session_key(carrier, signal)
    _duplicate_checks(raw_context, symbol, current_session, reasons)

    protected_ids = _protection_check(raw_context, position, prior, reasons)
    _active_order_checks(raw_context, symbol, protected_ids, reasons)

    add_qty = _number(_first(raw_context, "add_qty", "quantity", "qty"))
    add_price = _number(_first(raw_context, "add_price", "entry_price", "current_price"))
    capital = _capital_checks(raw_context, selected_policy, position, symbol, add_qty, add_price, reasons)

    if _text(_first(signal, "side", "action")).lower() in {"sell", "sell_to_close", "short"}:
        _add_reason(reasons, "sell_side_forbidden")

    policy_enabled = _bool(selected_policy.get("enabled")) is True
    policy_mode = _text(selected_policy.get("mode")).lower() or "shadow"
    policy_reasons: list[str] = []
    if not policy_enabled:
        policy_reasons.append("policy_disabled")
    if policy_mode == "shadow":
        policy_reasons.append("policy_shadow_only")
    for reason in policy_reasons:
        _add_reason(reasons, reason)

    guard_reasons = [reason for reason in reasons if reason not in {"policy_disabled", "policy_shadow_only"}]
    guard_eligible = not guard_reasons
    eligible = guard_eligible and policy_enabled and policy_mode not in {"shadow", "disabled"}
    status = "shadow" if not policy_enabled or policy_mode == "shadow" else ("guarded" if guard_eligible else "blocked")
    return {
        "schema_version": SCHEMA_VERSION,
        "authority": AUTHORITY,
        "execution_authority": False,
        "action": "BUY" if not any(reason == "sell_side_forbidden" for reason in reasons) else None,
        "symbol": symbol or None,
        "eligible": eligible,
        "guard_eligible": guard_eligible,
        "status": status,
        "policy_enabled": policy_enabled,
        "policy_mode": policy_mode,
        "reason_codes": reasons,
        "eligibility_reasons": list(reasons),
        "signal_id": _text(_first(signal, "signal_id")) or None,
        "signal_capture_id": _text(_first(signal, "signal_capture_id", "capture_id")) or None,
        "prior_fill_broker_order_id": _text(_first(prior, "broker_order_id", "order_id", "id")) or None,
        "prior_fill_at": prior_filled_at.isoformat() if prior_filled_at else None,
        "new_signal_at": captured_at.isoformat() if captured_at else None,
        "session_key": current_session or None,
        "add_qty": add_qty,
        "add_price": add_price,
        "capital": capital,
        "preserve_existing_protection": True,
        "cancel_existing_orders": False,
    }


def build_controlled_position_add_carrier(
    context: Mapping[str, Any],
    *,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return stable coordinator payload without adding execution authority."""

    result = evaluate_controlled_position_add(context, policy=policy)
    return {
        "schema_version": result["schema_version"],
        "authority": result["authority"],
        "execution_authority": False,
        "controlled_position_add": result,
    }
