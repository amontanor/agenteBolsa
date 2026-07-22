"""Shadow contract for causal authority of legacy time-stop exits.

The active exit path remains authoritative.  This module only captures the
inputs available before submission and links the result after submission.  It
never supplies a fallback identity based on symbol, date, or latest order.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

SCHEMA_DECISION = "p-l43c.time-stop-exit-authority.v1"
SCHEMA_LINK = "p-l43c.time-stop-exit-order-link.v1"
DECISION_EVENT_TYPE = "time_stop_exit_authority"
LINK_EVENT_TYPE = "time_stop_exit_order_link"
SHADOW_AUTHORITY = "time_stop_xnys.v1"
ACTIVE_AUTHORITY = "legacy_calendar_days"
_VOLATILE_FIELDS = {"captured_at", "observed_at", "content_hash"}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hashable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _hashable(item)
            for key, item in value.items()
            if str(key) not in _VOLATILE_FIELDS
        }
    if isinstance(value, list):
        return [_hashable(item) for item in value]
    return value


def content_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(_hashable(value)).encode("utf-8")).hexdigest()


def _identity_hash(
    *,
    cycle_id: str | None,
    watch_id: str | None,
    position_identity: str | None,
    plan_id: str | None,
    action: str,
) -> str:
    identity = {
        "cycle_id": cycle_id,
        "watch_id": watch_id,
        "position_identity": position_identity,
        "plan_id": plan_id,
        "action": action,
    }
    return hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _lot_value(lot: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _as_text(lot.get(key))
        if value:
            return value
    return None


def _resolve_exact_lot(
    lots: list[Mapping[str, Any]],
    *,
    source_plan: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Resolve one exact open lot, or explicitly return unavailable/ambiguous."""

    broker_ids = [_lot_value(lot, "broker_order_id", "buy_broker_order_id") for lot in lots]
    present_ids = [value for value in broker_ids if value]
    unique_ids = set(present_ids)
    reasons: list[str] = []
    if not present_ids:
        reasons.append("missing_buy_broker_order_id")
    elif len(present_ids) != len(unique_ids):
        reasons.append("duplicate_buy_broker_order_id")
    elif len(unique_ids) > 1:
        reasons.append("multiple_open_lots_no_exact_allocation")

    selected: Mapping[str, Any] | None = None
    if len(unique_ids) == 1 and len(present_ids) == 1 and len(lots) == 1:
        selected = lots[0]
    elif len(unique_ids) == 1 and len(present_ids) == 1 and len(lots) > 1:
        reasons.append("duplicate_lot_records")

    if selected is None:
        return {
            "authority_status": "ambiguous"
            if any("multiple" in reason or "duplicate" in reason for reason in reasons)
            else "unavailable",
            "reason_codes": reasons or ["exact_lot_unavailable"],
            "buy_broker_order_id": None,
            "buy_plan_id": None,
            "source_plan_id": None,
            "fill_authority": None,
            "buy_fill_at": None,
        }

    buy_id = _lot_value(selected, "broker_order_id", "buy_broker_order_id")
    buy_plan_id = _lot_value(selected, "buy_plan_id", "order_plan_id", "plan_id")
    source_plan_id = _lot_value(selected, "source_plan_id", "source_plan")
    if source_plan_id is None and source_plan is not None:
        source_plan_id = _as_text(source_plan.get("plan_id"))
    fill_authority = _lot_value(selected, "fill_authority")
    buy_fill_at = _lot_value(selected, "entry_fill_at", "first_fill_at", "filled_at")
    if source_plan_id is None:
        reasons.append("missing_source_plan_id")
    if fill_authority in {None, "unavailable"} or buy_fill_at is None:
        reasons.append("fill_authority_unavailable")
    status = "available" if not reasons else "unavailable"
    return {
        "authority_status": status,
        "reason_codes": reasons,
        "buy_broker_order_id": buy_id,
        "buy_plan_id": buy_plan_id,
        "source_plan_id": source_plan_id,
        "fill_authority": fill_authority,
        "buy_fill_at": buy_fill_at,
    }


def build_time_stop_exit_authority_capture(
    *,
    cycle_id: str | None,
    watch_id: str | None,
    position_identity: str | None,
    plan_id: str | None,
    symbol: str,
    qty: float,
    trigger: str,
    time_stop_evidence: Mapping[str, Any] | None,
    lots: list[Mapping[str, Any]] | None,
    source_plan: Mapping[str, Any] | None,
    decided_at: str | None = None,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Create the immutable pre-submit capture without touching SQLite."""

    evidence = dict(time_stop_evidence or {})
    if trigger in {"stop_loss", "take_profit"}:
        active_authority = "other"
        authority_status = "not_applicable"
        reason_codes = ["not_a_time_stop"]
        resolved = {
            "buy_broker_order_id": None,
            "buy_plan_id": None,
            "source_plan_id": None,
            "fill_authority": None,
            "buy_fill_at": None,
        }
    else:
        active_authority = ACTIVE_AUTHORITY
        resolved = _resolve_exact_lot(list(lots or []), source_plan=source_plan)
        authority_status = str(resolved["authority_status"])
        reason_codes = list(resolved["reason_codes"])
        if _as_text(evidence.get("active_policy_version")) is None:
            reason_codes.append("active_policy_version_unavailable")
        if not position_identity:
            reason_codes.append("missing_position_identity")
            authority_status = "unavailable"
        if evidence.get("legacy_eligible") is False:
            reason_codes.append("active_policy_not_eligible_or_unavailable")
            authority_status = "not_generated"
        elif evidence.get("legacy_eligible") is not True:
            reason_codes.append("active_policy_not_eligible_or_unavailable")
            authority_status = "unavailable"

    decision_id = "decision_" + _identity_hash(
        cycle_id=cycle_id,
        watch_id=watch_id,
        position_identity=position_identity,
        plan_id=plan_id,
        action="exit",
    )[:32]
    shadow_eligible = evidence.get("xnys_eligible")
    decision_policy_version = _as_text(evidence.get("active_policy_version"))
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_DECISION,
        "revision": 1,
        "decision_id": decision_id,
        "decided_at": decided_at or _iso_now(),
        "cycle_id": cycle_id,
        "watch_id": watch_id,
        "position_identity": position_identity,
        "lot_id": position_identity,
        "buy_broker_order_id": resolved.get("buy_broker_order_id"),
        "buy_plan_id": resolved.get("buy_plan_id"),
        "source_plan_id": resolved.get("source_plan_id"),
        "plan_id": plan_id,
        "symbol": symbol,
        "action": "exit",
        "qty": qty,
        "active_authority": active_authority,
        "active_policy_version": decision_policy_version,
        "active_result": "eligible" if evidence.get("legacy_eligible") is True else "ineligible" if evidence.get("legacy_eligible") is False else "unavailable",
        "active_eligible": evidence.get("legacy_eligible"),
        "active_reason_code": "legacy_time_stop_activated" if evidence.get("legacy_eligible") is True else None,
        "trigger": trigger,
        "shadow_authority": _as_text(evidence.get("shadow_authority")) or SHADOW_AUTHORITY,
        "shadow_policy_version": _as_text(evidence.get("policy_version")) or SHADOW_AUTHORITY,
        "shadow_only": bool(evidence.get("shadow_only", True)),
        "shadow_result": "eligible" if shadow_eligible is True else "ineligible" if shadow_eligible is False else "unavailable",
        "shadow_eligible": shadow_eligible,
        "comparison_status": evidence.get("comparison_status"),
        "fill_authority": resolved.get("fill_authority") or evidence.get("fill_authority"),
        "buy_fill_at": resolved.get("buy_fill_at") or evidence.get("fill_timestamp"),
        "legacy_inputs": {
            "calendar": "legacy_calendar_days",
            "elapsed_days": evidence.get("legacy_calendar_elapsed_days"),
            "return_condition_met": evidence.get("legacy_return_condition_met"),
        },
        "xnys_inputs": {
            "completed_sessions": evidence.get("completed_sessions"),
            "required_sessions": evidence.get("required_xnys_sessions"),
            "logical_eligibility_at": evidence.get("logical_eligibility_at"),
            "first_actionable_market_time": evidence.get("first_actionable_market_time"),
        },
        "data_quality": "verified"
        if authority_status == "available" and decision_policy_version
        else "partial",
        "reason_codes": sorted(set(reason_codes)),
        "authority_status": authority_status,
        "status": "captured" if authority_status == "available" else authority_status,
    }
    payload["content_hash"] = content_hash(payload)
    payload["captured_at"] = captured_at or _iso_now()
    return payload


def _safe_request_fingerprint(request_descriptor: Mapping[str, Any]) -> str:
    allowed = {
        key: request_descriptor.get(key)
        for key in ("operation", "method", "symbol", "side", "client_order_id", "qty")
        if request_descriptor.get(key) is not None
    }
    return hashlib.sha256(_canonical_json(allowed).encode("utf-8")).hexdigest()


def build_time_stop_exit_order_link(
    capture: Mapping[str, Any],
    *,
    broker_order_id: str | None,
    client_order_id: str | None,
    submitted_at: str | None,
    completed_at: str | None,
    submission_status: str,
    request_descriptor: Mapping[str, Any],
    error_reason: Mapping[str, Any] | None = None,
    attempt_ordinal: int = 1,
    captured_at: str | None = None,
) -> dict[str, Any]:
    decision_id = _as_text(capture.get("decision_id"))
    if not decision_id:
        raise ValueError("time-stop order link requires decision_id")
    order_identity = _as_text(broker_order_id) or _as_text(client_order_id)
    if not order_identity:
        attempt_digest = hashlib.sha256(
            _canonical_json({"decision_id": decision_id, "attempt_ordinal": attempt_ordinal}).encode("utf-8")
        ).hexdigest()[:32]
        order_identity = f"attempt_{attempt_digest}"
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_LINK,
        "revision": 1,
        "event_id": f"time_stop_exit_order_link:{order_identity}",
        "order_identity": order_identity,
        "decision_id": decision_id,
        "decision_content_hash": capture.get("content_hash"),
        "plan_id": capture.get("plan_id"),
        "source_plan_id": capture.get("source_plan_id"),
        "position_identity": capture.get("position_identity"),
        "broker_order_id": broker_order_id,
        "client_order_id": client_order_id,
        "submitted_at": submitted_at,
        "completed_at": completed_at,
        "submission_status": submission_status,
        "error_reason": dict(error_reason) if error_reason else None,
        "active_authority": capture.get("active_authority"),
        "request_fingerprint": _safe_request_fingerprint(request_descriptor),
    }
    payload["content_hash"] = content_hash(payload)
    payload["captured_at"] = captured_at or _iso_now()
    return payload


def attach_time_stop_exit_authority_reference(plan: dict[str, Any], capture: Mapping[str, Any]) -> dict[str, Any]:
    """Attach only local reference metadata; execution payload stays unchanged."""

    payload = plan.setdefault("payload", {})
    risk_decision = payload.setdefault("risk_decision", {})
    checks = risk_decision.setdefault("checks", {})
    checks["time_stop_exit_authority"] = {
        "schema_version": capture.get("schema_version"),
        "decision_id": capture.get("decision_id"),
        "content_hash": capture.get("content_hash"),
        "active_authority": capture.get("active_authority"),
    }
    return plan


def persist_time_stop_exit_authority(store: Any, capture: Mapping[str, Any], link: Mapping[str, Any]) -> dict[str, Any]:
    return store.record_time_stop_exit_authority(dict(capture), dict(link), cycle_id=_as_text(capture.get("cycle_id")))


def submit_with_time_stop_exit_authority(
    *,
    submit: Callable[[], Mapping[str, Any]],
    store: Any,
    capture: Mapping[str, Any] | None,
    client_order_id: str,
    request_descriptor: Mapping[str, Any],
    attempt_ordinal: int = 1,
) -> tuple[Mapping[str, Any], dict[str, Any] | None]:
    """Run the active submit unchanged and persist telemetry only afterwards."""

    if capture is None:
        return submit(), None
    try:
        order = submit()
    except Exception as exc:
        link = build_time_stop_exit_order_link(
            capture,
            broker_order_id=None,
            client_order_id=client_order_id,
            submitted_at=None,
            completed_at=None,
            submission_status="failed",
            request_descriptor=request_descriptor,
            error_reason={"code": "submission_exception", "error_type": type(exc).__name__},
            attempt_ordinal=attempt_ordinal,
        )
        try:
            persist_time_stop_exit_authority(store, capture, link)
        except Exception:  # noqa: BLE001 - shadow telemetry is fail-open.
            pass
        raise
    order_dict = dict(order)
    broker_order_id = _as_text(order_dict.get("id"))
    actual_client_order_id = _as_text(order_dict.get("client_order_id")) or client_order_id
    submitted_at = _as_text(order_dict.get("submitted_at")) or _iso_now()
    completed_at = _as_text(order_dict.get("filled_at")) or _as_text(order_dict.get("updated_at"))
    link = build_time_stop_exit_order_link(
        capture,
        broker_order_id=broker_order_id,
        client_order_id=actual_client_order_id,
        submitted_at=submitted_at,
        completed_at=completed_at,
        submission_status=_as_text(order_dict.get("status")) or "submitted",
        request_descriptor=request_descriptor,
        attempt_ordinal=attempt_ordinal,
    )
    try:
        persist_time_stop_exit_authority(store, capture, link)
    except Exception:  # noqa: BLE001 - shadow telemetry is fail-open.
        pass
    return order, link


def _event_payload(event: Mapping[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    return dict(payload) if isinstance(payload, Mapping) else {}


def time_stop_exit_authority_digest(store: Any, *, limit: int = 50000) -> dict[str, Any]:
    """Read only canonical P-L43C events; never rebuilds an order lineage."""

    events = store.time_stop_exit_authority_events(limit=limit)
    canonical_decisions = [event for event in events if event.get("event_type") == DECISION_EVENT_TYPE]
    canonical_links = [event for event in events if event.get("event_type") == LINK_EVENT_TYPE]
    conflicts = [event for event in events if str(event.get("event_type") or "").endswith("_conflict")]
    if not canonical_decisions and not canonical_links and not conflicts:
        return {
            "status": "collecting",
            "schema_version": SCHEMA_DECISION,
            "canonical_decisions": None,
            "linked_orders": None,
            "unlinked_decisions": None,
            "unlinked_orders": None,
            "legacy_authority": None,
            "shadow_authority": None,
            "ambiguous": None,
            "unavailable": None,
            "conflicts": None,
            "events": [],
        }
    decisions = {_event_payload(event).get("decision_id"): _event_payload(event) for event in canonical_decisions}
    links = [_event_payload(event) for event in canonical_links]
    linked_decisions = {str(link.get("decision_id")) for link in links if link.get("decision_id")}
    return {
        "status": "available",
        "schema_version": SCHEMA_DECISION,
        "canonical_decisions": len(decisions),
        "linked_orders": len(links),
        "unlinked_decisions": len(set(decisions) - linked_decisions),
        "unlinked_orders": sum(1 for link in links if not link.get("decision_id")),
        "legacy_authority": sum(1 for item in decisions.values() if item.get("active_authority") == ACTIVE_AUTHORITY),
        "shadow_authority": sum(1 for item in decisions.values() if item.get("shadow_authority") == SHADOW_AUTHORITY),
        "ambiguous": sum(1 for item in decisions.values() if item.get("authority_status") == "ambiguous"),
        "unavailable": sum(1 for item in decisions.values() if item.get("authority_status") == "unavailable"),
        "conflicts": len(conflicts),
        "coverage": {
            "decision_to_order": len(linked_decisions) / len(decisions) if decisions else None,
        },
        "events": [*canonical_decisions, *canonical_links],
    }


__all__ = [
    "ACTIVE_AUTHORITY",
    "DECISION_EVENT_TYPE",
    "LINK_EVENT_TYPE",
    "SCHEMA_DECISION",
    "SCHEMA_LINK",
    "SHADOW_AUTHORITY",
    "attach_time_stop_exit_authority_reference",
    "build_time_stop_exit_authority_capture",
    "build_time_stop_exit_order_link",
    "content_hash",
    "persist_time_stop_exit_authority",
    "submit_with_time_stop_exit_authority",
    "time_stop_exit_authority_digest",
]
