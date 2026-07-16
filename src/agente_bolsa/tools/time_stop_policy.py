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
SHADOW_EVENT_TYPE = "time_stop_shadow_observation"


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


def canonical_order_side(value: Any) -> str | None:
    """Normalise only verified order-side representations.

    Alpaca serialises its enum as ``OrderSide.BUY`` while the execution
    snapshot stores ``buy``.  ``long`` is deliberately not accepted here:
    position direction is not proof that the authoritative order was a buy.
    """

    if value is None:
        return None
    raw = getattr(value, "value", value)
    text = str(raw).strip().lower()
    if text in {"buy", "orderside.buy"}:
        return "buy"
    if text in {"sell", "orderside.sell"}:
        return "sell"
    return None


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
    lot_side_values = [
        canonical_order_side(lot.get("order_side"))
        for lot in raw_lots
        if "order_side" in lot
    ]
    if lot_side_values:
        if any(value is None for value in lot_side_values):
            result["warnings"].append("unsupported_order_side")
            result["unavailable_reason"] = "unsupported_order_side"
            return result
        if any(value != "buy" for value in lot_side_values):
            result["warnings"].append("unsupported_order_side")
            result["unavailable_reason"] = "unsupported_order_side"
            return result
        effective_side = "buy"
    else:
        # Direct callers predating verified order authority retain their
        # helper compatibility.  The production shadow path always supplies
        # ``order_side`` from the exact broker order via Store.
        effective_side = side
    if str(effective_side or "long").lower() not in {"long", "buy"}:
        result["warnings"].append("unsupported_side")
        result["unavailable_reason"] = "unsupported_side"
        return result
    if not raw_lots:
        result["warnings"].append("missing_verified_buy_lot")
        result["unavailable_reason"] = "missing_verified_buy_lot"
        return result
    strict_order_authority = any(
        "order_side" in lot or "order_status_verified" in lot for lot in raw_lots
    )
    if strict_order_authority:
        if any(not str(lot.get("broker_order_id") or "").strip() for lot in raw_lots):
            result["warnings"].append("missing_broker_order_id")
            result["unavailable_reason"] = "missing_broker_order_id"
            return result
        for lot in raw_lots:
            if "filled_qty" in lot:
                filled_qty = _number(lot.get("filled_qty"))
                if filled_qty is None or filled_qty <= 0:
                    result["warnings"].append("invalid_filled_qty")
                    result["unavailable_reason"] = "invalid_filled_qty"
                    return result
            if lot.get("is_partial") and lot.get("fill_authority") != "first_fill_at":
                result["warnings"].append("fill_authority_unavailable")
                result["unavailable_reason"] = "fill_authority_unavailable"
                return result
    if any("order_status_verified" in lot and lot.get("order_status_verified") is not True for lot in raw_lots):
        result["warnings"].append("order_not_filled")
        result["unavailable_reason"] = "order_not_filled"
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


def build_position_identity(
    *,
    symbol: str,
    lots: Sequence[Mapping[str, Any]],
    position_qty: Any = None,
    policy_version: str = POLICY_VERSION,
) -> tuple[str | None, str | None]:
    """Build a stable identity from verified open lots, never symbol alone."""

    raw_lots = [dict(lot) for lot in lots if isinstance(lot, Mapping)]
    if not raw_lots:
        return None, "missing_verified_lots"
    records: list[dict[str, Any]] = []
    seen_order_ids: set[str] = set()
    for lot in raw_lots:
        order_id = str(lot.get("broker_order_id") or "").strip()
        if not order_id:
            return None, "missing_broker_order_id"
        if order_id in seen_order_ids:
            return None, "duplicate_broker_order_id"
        seen_order_ids.add(order_id)
        if "order_side" in lot and canonical_order_side(lot.get("order_side")) != "buy":
            return None, "unsupported_order_side"
        if "order_status_verified" in lot and lot.get("order_status_verified") is not True:
            return None, "order_not_filled"
        fill_at = lot.get("entry_fill_at") or lot.get("filled_at")
        fill_dt, _warnings = _parse_timestamp(fill_at)
        authority = str(lot.get("fill_authority") or "").strip()
        if not authority and lot.get("entry_fill_at"):
            authority = "first_fill_at"
        elif not authority and lot.get("filled_at") and not lot.get("is_partial"):
            authority = "aggregated_filled_at"
        if fill_dt is None or authority in {"", "unavailable", "unknown"}:
            return None, "fill_authority_unavailable"
        filled_qty = _number(lot.get("filled_qty"))
        open_qty = _number(lot.get("open_qty"))
        if open_qty is None and lot.get("remaining_qty_scope") == "position":
            open_qty = _number(lot.get("remaining_qty"))
        if open_qty is None and len(raw_lots) == 1:
            open_qty = _number(position_qty) or filled_qty
        if open_qty is None or open_qty <= 0:
            return None, "open_quantity_unavailable"
        records.append(
            {
                "broker_order_id": order_id,
                "order_plan_id": str(lot.get("order_plan_id") or lot.get("source_plan_id") or "") or None,
                "source_plan_id": str(lot.get("source_plan_id") or "") or None,
                "cycle_id": str(lot.get("cycle_id") or "") or None,
                "symbol": str(lot.get("symbol") or symbol or "").upper() or None,
                "open_qty": open_qty,
                "filled_qty": filled_qty,
                "fill_authority": authority,
                "fill_timestamp": _iso(fill_dt),
            }
        )
    records.sort(key=lambda item: item["broker_order_id"])
    canonical = {
        "policy_version": policy_version,
        "symbol": str(symbol or "").upper(),
        "lots": records,
    }
    raw = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return f"position_{sha256(raw.encode('utf-8')).hexdigest()[:32]}", None


def _observation_session(evaluation_at: Any, calendar: MarketCalendar | None) -> str:
    parsed, _warnings = _parse_timestamp(evaluation_at)
    if parsed is None:
        return "unavailable"
    if calendar is not None:
        try:
            market_date = parsed.astimezone(calendar.market_tz).date()
            rows = _session_rows(calendar, market_date, market_date)
            if rows:
                return market_date.isoformat()
            return "unavailable"
        except Exception:
            pass
    return parsed.date().isoformat()


def _shadow_stable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _shadow_stable(item)
            for key, item in value.items()
            if key not in {"evaluation_at", "captured_at", "generated_at", "created_at"}
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_shadow_stable(item) for item in value]
    return value


def _shadow_observation_payload(
    *,
    symbol: str,
    evidence: Mapping[str, Any],
    position_identity: str | None,
    identity_reason: str | None,
    observation_session: str,
    observation_reason: str,
) -> dict[str, Any]:
    """Create the bounded, pre-decision-only historical payload."""

    allowed = {
        "schema_version",
        "policy_version",
        "time_stop_semantics",
        "status",
        "comparison",
        "comparison_status",
        "xnys_eligible",
        "legacy_eligible",
        "legacy_calendar_eligible",
        "completed_xnys_sessions_after_entry",
        "required_xnys_sessions",
        "first_eligible_session",
        "logical_eligibility_at",
        "first_actionable_market_time",
        "fill_authority",
        "fill_timestamp",
        "unavailable_reason",
        "ambiguity_reason",
        "warnings",
        "shadow_only",
        "active_policy",
        "shadow_policy",
    }
    temporal = {key: _shadow_stable(evidence.get(key)) for key in allowed if key in evidence}
    stable = {
        "schema_version": SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "symbol": str(symbol or "").upper(),
        "position_identity": position_identity,
        "identity_reason": identity_reason,
        "observation_session": observation_session,
        "observation_reason": observation_reason,
        "temporal": temporal,
    }
    content_hash = _content_hash(stable)
    id_raw = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    observation_id = f"shadow_{sha256(id_raw.encode('utf-8')).hexdigest()[:32]}"
    return {
        **stable,
        "shadow_observation_id": observation_id,
        "content_hash": content_hash,
        "evaluation_at": evidence.get("evaluation_at"),
    }


def _observation_value(item: Mapping[str, Any], key: str) -> Any:
    if key in item:
        return item.get(key)
    temporal = item.get("temporal")
    return temporal.get(key) if isinstance(temporal, Mapping) else None


def _same_observation_state(previous: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    return all(_observation_value(previous, key) == _observation_value(current, key) for key in (
        "position_identity",
        "observation_session",
        "comparison_status",
        "status",
        "completed_xnys_sessions_after_entry",
        "fill_authority",
        "unavailable_reason",
        "ambiguity_reason",
        "xnys_eligible",
        "legacy_eligible",
        "logical_eligibility_at",
    ))


def record_shadow_time_stop_observation(
    store: Any,
    *,
    symbol: str,
    evidence: Mapping[str, Any],
    lots: Sequence[Mapping[str, Any]],
    position_qty: Any,
    calendar: MarketCalendar | None,
    evaluation_at: Any,
    observation_reason: str = "session_observation",
    cycle_id: str | None = None,
    force_reason: bool = False,
) -> dict[str, Any]:
    """Append a state change and return the latest-view metadata.

    The function performs no trading action.  It is deliberately safe to call
    on every portfolio-watch tick: unchanged state in the same XNYS session is
    a no-op in the event ledger.
    """

    position_identity, identity_reason = build_position_identity(
        symbol=symbol,
        lots=lots,
        position_qty=position_qty,
    )
    session = _observation_session(evaluation_at, calendar)
    current = _shadow_observation_payload(
        symbol=symbol,
        evidence=evidence,
        position_identity=position_identity,
        identity_reason=identity_reason,
        observation_session=session,
        observation_reason=observation_reason,
    )
    prior_rows = []
    try:
        if position_identity:
            prior_rows = store.time_stop_shadow_observations(position_identity=position_identity)
        else:
            prior_rows = store.time_stop_shadow_observations()
    except Exception:
        prior_rows = []
    prior_for_position = [
        row for row in prior_rows
        if row.get("position_identity") == position_identity
        and row.get("symbol") == str(symbol or "").upper()
    ]
    latest = prior_for_position[-1] if prior_for_position else None
    if latest is not None and not force_reason:
        if _same_observation_state(latest, current):
            return {
                "position_identity": position_identity,
                "shadow_observation_id": latest.get("shadow_observation_id"),
                "content_hash": latest.get("content_hash"),
                "observation_session": latest.get("observation_session"),
                "observation_reason": latest.get("observation_reason"),
                "history_status": "idempotent",
            }
        if _observation_value(current, "xnys_eligible") is True and _observation_value(latest, "xnys_eligible") is not True:
            current["observation_reason"] = "logical_eligibility"
        elif _observation_value(latest, "comparison_status") != _observation_value(current, "comparison_status"):
            current["observation_reason"] = "comparison_transition"
        elif _observation_value(latest, "completed_xnys_sessions_after_entry") != _observation_value(current, "completed_xnys_sessions_after_entry"):
            current["observation_reason"] = "session_progress"
        elif _observation_value(latest, "fill_authority") != _observation_value(current, "fill_authority"):
            current["observation_reason"] = "fill_authority_change"
        elif _observation_value(latest, "unavailable_reason") != _observation_value(current, "unavailable_reason") or _observation_value(latest, "ambiguity_reason") != _observation_value(current, "ambiguity_reason"):
            current["observation_reason"] = "availability_change"
        else:
            current["observation_reason"] = "session_observation"
        current = _shadow_observation_payload(
            symbol=symbol,
            evidence=evidence,
            position_identity=position_identity,
            identity_reason=identity_reason,
            observation_session=session,
            observation_reason=current["observation_reason"],
        )
    try:
        result = store.record_time_stop_shadow_observation(
            current,
            event_id=str(current["shadow_observation_id"]),
            cycle_id=cycle_id,
        )
    except Exception as exc:  # noqa: BLE001 - observability must fail open.
        result = {"status": "unavailable", "error": type(exc).__name__}
    return {
        "position_identity": position_identity,
        "identity_reason": identity_reason,
        "shadow_observation_id": current["shadow_observation_id"],
        "content_hash": current["content_hash"],
        "observation_session": session,
        "observation_reason": current["observation_reason"],
        "history_status": result.get("status"),
        "history_error": result.get("error"),
    }


def shadow_time_stop_digest_summary(store: Any) -> dict[str, Any]:
    """Summarize the append-only ledger, not the mutable runtime latest view."""

    try:
        observations = list(store.time_stop_shadow_observations())
    except Exception as exc:  # noqa: BLE001 - observability must fail open.
        return {
            "status": "unavailable",
            "shadow_only": True,
            "evaluations": None,
            "unique_positions": None,
            "unique_observations": None,
            "current_positions": None,
            "error": "shadow_summary_unavailable",
            "warnings": [type(exc).__name__],
        }
    if not observations:
        return {
            "status": "collecting",
            "shadow_only": True,
            "evaluations": None,
            "unique_positions": None,
            "unique_observations": None,
            "current_positions": None,
            "both_eligible": None,
            "legacy_only": None,
            "xnys_only": None,
            "both_ineligible": None,
            "unavailable": None,
            "ambiguity": None,
            "comparison_transitions": None,
            "legacy_exits_observed": None,
            "xnys_logical_eligibility_events": None,
            "sessions_covered": None,
            "fill_coverage": None,
            "freshness": "collecting",
        }
    counts = {
        status: sum(1 for item in observations if item.get("temporal", {}).get("comparison_status") == status)
        for status in ("both_eligible", "legacy_only", "xnys_only", "both_ineligible")
    }
    # Payload fields are nested under ``temporal`` to make the event bounded.
    unavailable = sum(1 for item in observations if item.get("temporal", {}).get("status") != "available")
    ambiguity = sum(1 for item in observations if item.get("identity_reason") or item.get("temporal", {}).get("ambiguity_reason"))
    fill_verified = sum(
        1
        for item in observations
        if item.get("temporal", {}).get("fill_authority") not in {None, "unavailable"}
    )
    identities = {item.get("position_identity") for item in observations if item.get("position_identity")}
    sessions = {item.get("observation_session") for item in observations if item.get("observation_session") != "unavailable"}
    transitions = sum(1 for item in observations if item.get("observation_reason") == "comparison_transition")
    legacy_exits = sum(1 for item in observations if item.get("observation_reason") == "legacy_time_stop_activated")
    logical = sum(1 for item in observations if item.get("observation_reason") == "logical_eligibility")
    current_positions = None
    try:
        connection = store.read_connection()
        try:
            rows = connection.execute(
                "SELECT value_json FROM runtime_state WHERE key LIKE 'time_stop_v2_evidence:%'"
            ).fetchall()
        finally:
            close_reader = getattr(store, "close_read_connection", None)
            if callable(close_reader):
                close_reader()
        current_ids: set[str] = set()
        for row in rows:
            try:
                value = json.loads(row["value_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(value, dict) and value.get("position_identity"):
                current_ids.add(str(value["position_identity"]))
        current_positions = len(current_ids)
    except Exception:
        current_positions = None
    return {
        "status": "available",
        "shadow_only": True,
        "evaluations": len(observations),
        "unique_positions": len(identities) or None,
        "unique_observations": len(observations),
        "current_positions": current_positions,
        **counts,
        "unavailable": unavailable,
        "ambiguity": ambiguity,
        "discrepancies": counts["legacy_only"] + counts["xnys_only"],
        "comparison_transitions": transitions,
        "legacy_exits_observed": legacy_exits,
        "xnys_logical_eligibility_events": logical,
        "sessions_covered": sorted(sessions),
        "fill_coverage": {"numerator": fill_verified, "denominator": len(observations)},
        "freshness": "available",
        "last_observation_session": max(sessions, default=None),
        "last_evaluation_at": max(
            (str(item.get("evaluation_at")) for item in observations if item.get("evaluation_at")),
            default=None,
        ),
    }


__all__ = [
    "POLICY_VERSION",
    "SCHEMA_VERSION",
    "TEMPORAL_SEMANTICS",
    "canonical_order_side",
    "evaluate_position_time_stop",
    "evaluate_time_stop",
    "build_position_identity",
    "record_shadow_time_stop_observation",
    "shadow_time_stop_digest_summary",
]
