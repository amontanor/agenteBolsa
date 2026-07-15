"""Canonical XNYS time-stop policy.

The policy deliberately keeps the legacy calendar-day comparison as shadow
telemetry while making completed exchange sessions the only active temporal
criterion.  This module never submits orders and does not mutate trading
configuration.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from typing import Any

from ..market_calendar import MarketCalendar

SCHEMA_VERSION = "p-l43b.time-stop-xnys.v1"
POLICY_VERSION = "time_stop_xnys.v1"
TEMPORAL_SEMANTICS = "completed_xnys_sessions_after_fill"


def _parse_timestamp(value: Any) -> tuple[datetime | None, list[str]]:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None, ["invalid_timestamp"]
    else:
        return None, ["missing_timestamp"]
    warnings: list[str] = []
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
        warnings.append("timestamp_naive_assumed_utc")
    return parsed.astimezone(timezone.utc), warnings


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _schedule(calendar: MarketCalendar, start: date, end: date):
    """Return the real exchange schedule, never the weekday fallback."""

    return calendar.session_schedule(start.isoformat(), end.isoformat())


def _session_rows(calendar: MarketCalendar, start: date, end: date) -> list[tuple[date, datetime]] | None:
    schedule = _schedule(calendar, start, end)
    if schedule is None:
        return None
    rows: list[tuple[date, datetime]] = []
    for session_date, row in schedule.iterrows():
        close = row.get("market_close")
        if close is None:
            continue
        close_dt = close.to_pydatetime() if hasattr(close, "to_pydatetime") else close
        if close_dt.tzinfo is None:
            close_dt = close_dt.replace(tzinfo=timezone.utc)
        rows.append((session_date.date() if hasattr(session_date, "date") else session_date, close_dt.astimezone(timezone.utc)))
    return rows


def _content_hash(payload: Mapping[str, Any]) -> str:
    stable = {key: value for key, value in payload.items() if key not in {"content_hash", "generated_at"}}
    raw = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return sha256(raw).hexdigest()


def evaluate_time_stop(
    *,
    entry_fill_at: Any,
    evaluation_at: Any,
    required_completed_sessions: int,
    calendar: MarketCalendar,
) -> dict[str, Any]:
    """Evaluate one verified fill using completed XNYS sessions only."""

    entry, entry_warnings = _parse_timestamp(entry_fill_at)
    evaluation, evaluation_warnings = _parse_timestamp(evaluation_at)
    warnings = [*entry_warnings, *evaluation_warnings]
    required = int(required_completed_sessions)
    base: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "time_stop_semantics": TEMPORAL_SEMANTICS,
        "entry_fill_at": _iso(entry),
        "evaluation_at": _iso(evaluation),
        "entry_session": None,
        "completed_xnys_sessions_after_entry": None,
        "required_sessions": required,
        "first_eligible_session": None,
        "xnys_eligible": None,
        "legacy_calendar_elapsed_days": None,
        "legacy_calendar_eligible": None,
        "comparison": None,
        "status": "unavailable",
        "warnings": warnings,
    }
    if required <= 0:
        base["warnings"].append("required_sessions_invalid")
        base["content_hash"] = _content_hash(base)
        return base
    if entry is None or evaluation is None:
        base["content_hash"] = _content_hash(base)
        return base
    if evaluation < entry:
        base["warnings"].append("evaluation_before_entry")
        base["content_hash"] = _content_hash(base)
        return base
    if calendar is None:
        base["warnings"].append("calendar_unavailable")
        base["content_hash"] = _content_hash(base)
        return base

    entry_market_date = entry.astimezone(calendar.market_tz).date()
    evaluation_market_date = evaluation.astimezone(calendar.market_tz).date()
    entry_rows = _session_rows(calendar, entry_market_date, entry_market_date)
    if entry_rows is None:
        base["warnings"].append("calendar_unavailable")
        base["content_hash"] = _content_hash(base)
        return base
    if not entry_rows:
        base["warnings"].append("entry_not_xnys_session")
        base["content_hash"] = _content_hash(base)
        return base
    base["entry_session"] = entry_market_date.isoformat()

    # Give the schedule enough room for holidays and weekends while keeping
    # the lookup bounded and deterministic.
    end = max(evaluation_market_date, entry_market_date) + timedelta(days=max(30, required * 10))
    rows = _session_rows(calendar, entry_market_date + timedelta(days=1), end)
    if rows is None:
        base["warnings"].append("calendar_unavailable")
        base["content_hash"] = _content_hash(base)
        return base
    posterior = [(session_date, close) for session_date, close in rows if session_date > entry_market_date]
    if len(posterior) < required:
        base["warnings"].append("calendar_window_insufficient")
        base["content_hash"] = _content_hash(base)
        return base

    eligible_session = posterior[required - 1][0]
    completed = sum(1 for session_date, close in posterior if session_date <= evaluation_market_date and close <= evaluation)
    legacy_days = (evaluation - entry).days
    legacy_eligible = legacy_days >= required
    xnys_eligible = completed >= required
    comparison = "same"
    if legacy_eligible and not xnys_eligible:
        comparison = "legacy_only"
    elif xnys_eligible and not legacy_eligible:
        comparison = "xnys_only"
    base.update(
        {
            "completed_xnys_sessions_after_entry": completed,
            "first_eligible_session": eligible_session.isoformat(),
            "xnys_eligible": xnys_eligible,
            "legacy_calendar_elapsed_days": legacy_days,
            "legacy_calendar_eligible": legacy_eligible,
            "comparison": comparison,
            "status": "available",
        }
    )
    base["content_hash"] = _content_hash(base)
    return base


def evaluate_position_time_stop(
    *,
    lots: Sequence[Mapping[str, Any]],
    position_qty: Any,
    side: Any = "long",
    evaluation_at: Any,
    required_completed_sessions: int,
    calendar: MarketCalendar,
) -> dict[str, Any]:
    """Evaluate lots without silently choosing the latest order.

    A full-position time-stop is eligible only when every open lot is
    individually verified and eligible.  Multiple lots require explicit
    ``remaining_qty`` values; otherwise the inventory is ambiguous and the
    time-stop remains unavailable.
    """

    raw_lots = [dict(lot) for lot in lots if isinstance(lot, Mapping)]
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "time_stop_semantics": TEMPORAL_SEMANTICS,
        "status": "unavailable",
        "xnys_eligible": None,
        "legacy_calendar_eligible": None,
        "comparison": None,
        "lots": [],
        "warnings": [],
    }
    if str(side or "long").lower() not in {"long", "buy"}:
        result["warnings"].append("unsupported_side")
        return result
    if not raw_lots:
        result["warnings"].append("missing_verified_buy_lot")
        return result
    target_qty = _number(position_qty)
    if len(raw_lots) > 1:
        remaining = [
            _number(lot.get("open_qty"))
            if lot.get("open_qty") is not None
            else (_number(lot.get("remaining_qty")) if lot.get("remaining_qty_scope") == "position" else None)
            for lot in raw_lots
        ]
        if target_qty is None or any(value is None for value in remaining) or abs(sum(remaining) - target_qty) > 1e-8:
            result["status"] = "ambiguous"
            result["warnings"].append("ambiguous_lots")
            return result
    elif target_qty is not None:
        lot_qty = _number(raw_lots[0].get("open_qty"))
        if lot_qty is None and raw_lots[0].get("remaining_qty_scope") == "position":
            lot_qty = _number(raw_lots[0].get("remaining_qty"))
        if lot_qty is None:
            lot_qty = _number(raw_lots[0].get("filled_qty"))
        if lot_qty is not None and abs(lot_qty - target_qty) > 1e-8:
            result["status"] = "ambiguous"
            result["warnings"].append("position_lot_quantity_mismatch")
            return result

    evaluations: list[dict[str, Any]] = []
    for lot in raw_lots:
        fill_at = lot.get("entry_fill_at") or lot.get("filled_at")
        evaluation = evaluate_time_stop(
            entry_fill_at=fill_at,
            evaluation_at=evaluation_at,
            required_completed_sessions=required_completed_sessions,
            calendar=calendar,
        )
        for identity_key in ("broker_order_id", "order_plan_id", "source_plan_id", "cycle_id", "symbol"):
            evaluation[identity_key] = lot.get(identity_key)
        evaluations.append(evaluation)
    result["lots"] = evaluations
    if any(item.get("status") != "available" for item in evaluations):
        result["warnings"].append("lot_temporal_evidence_unavailable")
        return result
    result.update(
        {
            "status": "available",
            "xnys_eligible": all(bool(item.get("xnys_eligible")) for item in evaluations),
            "legacy_calendar_eligible": all(bool(item.get("legacy_calendar_eligible")) for item in evaluations),
        }
    )
    comparisons = {item.get("comparison") for item in evaluations}
    result["comparison"] = next(iter(comparisons)) if len(comparisons) == 1 else "mixed"
    return result


__all__ = [
    "POLICY_VERSION",
    "SCHEMA_VERSION",
    "TEMPORAL_SEMANTICS",
    "evaluate_position_time_stop",
    "evaluate_time_stop",
]
