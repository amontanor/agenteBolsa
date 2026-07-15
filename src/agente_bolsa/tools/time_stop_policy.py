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


def _session_rows(calendar: MarketCalendar, start: date, end: date) -> list[tuple[date, datetime, datetime]] | None:
    schedule = _schedule(calendar, start, end)
    if schedule is None:
        return None
    rows: list[tuple[date, datetime, datetime]] = []
    for session_date, row in schedule.iterrows():
        market_open = row.get("market_open")
        close = row.get("market_close")
        if market_open is None or close is None:
            continue
        open_dt = market_open.to_pydatetime() if hasattr(market_open, "to_pydatetime") else market_open
        close_dt = close.to_pydatetime() if hasattr(close, "to_pydatetime") else close
        if open_dt.tzinfo is None:
            open_dt = open_dt.replace(tzinfo=timezone.utc)
        if close_dt.tzinfo is None:
            close_dt = close_dt.replace(tzinfo=timezone.utc)
        rows.append(
            (
                session_date.date() if hasattr(session_date, "date") else session_date,
                open_dt.astimezone(timezone.utc),
                close_dt.astimezone(timezone.utc),
            )
        )
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
        "required_xnys_sessions": required,
        "first_eligible_session": None,
        "logical_eligibility_at": None,
        "first_actionable_market_time": None,
        "xnys_eligible": None,
        "legacy_calendar_elapsed_days": None,
        "legacy_calendar_eligible": None,
        "legacy_eligible": None,
        "comparison": None,
        "comparison_status": "xnys_unavailable",
        "fill_authority": None,
        "fill_timestamp": _iso(entry),
        "shadow_only": True,
        "active_policy": "legacy_calendar_days",
        "shadow_policy": POLICY_VERSION,
        "unavailable_reason": None,
        "ambiguity_reason": None,
        "status": "unavailable",
        "warnings": warnings,
    }
    if required <= 0:
        base["warnings"].append("required_sessions_invalid")
        base["unavailable_reason"] = "required_sessions_invalid"
        base["content_hash"] = _content_hash(base)
        return base
    if entry is None or evaluation is None:
        base["unavailable_reason"] = "missing_or_invalid_timestamp"
        base["content_hash"] = _content_hash(base)
        return base
    if evaluation < entry:
        base["warnings"].append("evaluation_before_entry")
        base["unavailable_reason"] = "evaluation_before_entry"
        base["content_hash"] = _content_hash(base)
        return base
    if calendar is None:
        base["warnings"].append("calendar_unavailable")
        base["unavailable_reason"] = "calendar_unavailable"
        base["content_hash"] = _content_hash(base)
        return base

    entry_market_date = entry.astimezone(calendar.market_tz).date()
    evaluation_market_date = evaluation.astimezone(calendar.market_tz).date()
    entry_rows = _session_rows(calendar, entry_market_date, entry_market_date)
    if entry_rows is None:
        base["warnings"].append("calendar_unavailable")
        base["unavailable_reason"] = "calendar_unavailable"
        base["content_hash"] = _content_hash(base)
        return base
    if not entry_rows:
        base["warnings"].append("entry_not_xnys_session")
        base["unavailable_reason"] = "entry_not_xnys_session"
        base["content_hash"] = _content_hash(base)
        return base
    base["entry_session"] = entry_market_date.isoformat()

    # Give the schedule enough room for holidays and weekends while keeping
    # the lookup bounded and deterministic.
    end = max(evaluation_market_date, entry_market_date) + timedelta(days=max(30, required * 10))
    rows = _session_rows(calendar, entry_market_date + timedelta(days=1), end)
    if rows is None:
        base["warnings"].append("calendar_unavailable")
        base["unavailable_reason"] = "calendar_unavailable"
        base["content_hash"] = _content_hash(base)
        return base
    posterior = [(session_date, open_dt, close) for session_date, open_dt, close in rows if session_date > entry_market_date]
    if len(posterior) < required:
        base["warnings"].append("calendar_window_insufficient")
        base["unavailable_reason"] = "calendar_window_insufficient"
        base["content_hash"] = _content_hash(base)
        return base

    eligible_session, _eligible_open, eligible_close = posterior[required - 1]
    completed = sum(
        1
        for session_date, _open_dt, close in posterior
        if session_date <= evaluation_market_date and close <= evaluation
    )
    next_session = next(
        ((session_date, open_dt) for session_date, open_dt, _close in posterior if session_date > eligible_session),
        None,
    )
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
            "logical_eligibility_at": eligible_close.isoformat(),
            "first_actionable_market_time": next_session[1].isoformat() if next_session else None,
            "xnys_eligible": xnys_eligible,
            "legacy_calendar_elapsed_days": legacy_days,
            "legacy_calendar_eligible": legacy_eligible,
            "legacy_eligible": legacy_eligible,
            "comparison": comparison,
            "comparison_status": (
                "both_eligible"
                if legacy_eligible and xnys_eligible
                else "legacy_only"
                if legacy_eligible
                else "xnys_only"
                if xnys_eligible
                else "both_ineligible"
            ),
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
        "legacy_eligible": None,
        "comparison": None,
        "comparison_status": "xnys_unavailable",
        "required_xnys_sessions": int(required_completed_sessions),
        "fill_authority": None,
        "fill_timestamp": None,
        "shadow_only": True,
        "active_policy": "legacy_calendar_days",
        "shadow_policy": POLICY_VERSION,
        "unavailable_reason": None,
        "ambiguity_reason": None,
        "lots": [],
        "warnings": [],
    }
    if str(side or "long").lower() not in {"long", "buy"}:
        result["warnings"].append("unsupported_side")
        result["unavailable_reason"] = "unsupported_side"
        return result
    if not raw_lots:
        result["warnings"].append("missing_verified_buy_lot")
        result["unavailable_reason"] = "missing_verified_buy_lot"
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
            result["ambiguity_reason"] = "open_lot_quantities_not_verifiable"
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
            result["ambiguity_reason"] = "position_lot_quantity_mismatch"
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
        evaluation["fill_authority"] = lot.get("fill_authority") or (
            "first_fill_at" if lot.get("entry_fill_at") else "unavailable"
        )
        evaluation["fill_timestamp"] = evaluation.get("entry_fill_at")
        for identity_key in ("broker_order_id", "order_plan_id", "source_plan_id", "cycle_id", "symbol"):
            evaluation[identity_key] = lot.get(identity_key)
        evaluations.append(evaluation)
    result["lots"] = evaluations
    if any(item.get("status") != "available" for item in evaluations):
        result["warnings"].append("lot_temporal_evidence_unavailable")
        result["unavailable_reason"] = "lot_temporal_evidence_unavailable"
        return result
    result.update(
        {
            "status": "available",
            "xnys_eligible": all(bool(item.get("xnys_eligible")) for item in evaluations),
            "legacy_calendar_eligible": all(bool(item.get("legacy_calendar_eligible")) for item in evaluations),
            "legacy_eligible": all(bool(item.get("legacy_calendar_eligible")) for item in evaluations),
        }
    )
    if len(evaluations) == 1:
        result["fill_authority"] = evaluations[0].get("fill_authority")
        result["fill_timestamp"] = evaluations[0].get("fill_timestamp")
    else:
        result["fill_authority"] = "multiple_verified_fills"
    comparisons = {item.get("comparison") for item in evaluations}
    result["comparison"] = next(iter(comparisons)) if len(comparisons) == 1 else "mixed"
    statuses = {item.get("comparison_status") for item in evaluations}
    result["comparison_status"] = next(iter(statuses)) if len(statuses) == 1 else "mixed"
    result["logical_eligibility_at"] = max(
        (item.get("logical_eligibility_at") for item in evaluations if item.get("logical_eligibility_at")),
        default=None,
    )
    result["first_actionable_market_time"] = max(
        (item.get("first_actionable_market_time") for item in evaluations if item.get("first_actionable_market_time")),
        default=None,
    )
    return result


def shadow_time_stop_digest_summary(store: Any) -> dict[str, Any]:
    """Summarize persisted shadow observations without affecting trading."""

    try:
        connection = store.read_connection()
        try:
            rows = connection.execute(
                "SELECT key, value_json, updated_at FROM runtime_state WHERE key LIKE 'time_stop_v2_evidence:%'"
            ).fetchall()
        finally:
            close_reader = getattr(store, "close_read_connection", None)
            if callable(close_reader):
                close_reader()
    except Exception as exc:  # noqa: BLE001 - observability must fail open.
        return {
            "status": "unavailable",
            "shadow_only": True,
            "evaluations": None,
            "error": "shadow_summary_unavailable",
            "warnings": [type(exc).__name__],
        }
    observations: list[dict[str, Any]] = []
    for row in rows:
        try:
            value = json.loads(row["value_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            observations.append(value)
    if not observations:
        return {
            "status": "collecting",
            "shadow_only": True,
            "evaluations": None,
            "both_eligible": None,
            "legacy_only": None,
            "xnys_only": None,
            "both_ineligible": None,
            "unavailable": None,
            "discrepancies": None,
            "fill_coverage": None,
            "freshness": "collecting",
        }
    counts = {
        status: sum(1 for item in observations if item.get("comparison_status") == status)
        for status in ("both_eligible", "legacy_only", "xnys_only", "both_ineligible")
    }
    unavailable = sum(1 for item in observations if item.get("status") != "available")
    fill_verified = sum(1 for item in observations if item.get("fill_authority") not in {None, "unavailable"})
    evaluations = len(observations)
    return {
        "status": "available",
        "shadow_only": True,
        "evaluations": evaluations,
        **counts,
        "unavailable": unavailable,
        "discrepancies": counts["legacy_only"] + counts["xnys_only"],
        "fill_coverage": {"numerator": fill_verified, "denominator": evaluations},
        "freshness": "available",
        "last_evaluation_at": max(
            (str(item.get("evaluation_at")) for item in observations if item.get("evaluation_at")),
            default=None,
        ),
    }


__all__ = [
    "POLICY_VERSION",
    "SCHEMA_VERSION",
    "TEMPORAL_SEMANTICS",
    "evaluate_position_time_stop",
    "evaluate_time_stop",
    "shadow_time_stop_digest_summary",
]
