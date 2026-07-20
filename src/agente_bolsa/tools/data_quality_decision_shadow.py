"""P-L49B: data-quality decision shadow.

The module deliberately keeps the quality comparison separate from the active
decision path.  Phase A only captures the market observations already present
in memory; Phase B annotates that immutable capture with the results already
produced by the active cycle.  Neither phase downloads data, runs a reviewer,
or changes a candidate, plan, order, or risk decision.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from ..storage import Store


SCHEMA_VERSION = "p-l49b.data-quality-decision-shadow.v1"
EVENT_TYPE = "data_quality_decision_shadow"
EVENT_ID_PREFIX = "data_quality_decision_shadow:"
DEFAULT_DETAIL_LIMIT = 500
_MISSING = object()

_SHADOW_REASONS = {
    "eligible",
    "blocked_exact_quality",
    "unavailable_identity",
    "unavailable_temporal",
    "not_applicable_exit",
    "conflict",
}
_BLOCKING_QUALITY = {
    "blocking",
    "ohlc_invalid",
    "invalid",
    "stale",
    "incomplete",
    "future",
}


def _safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def canonical_content_hash(payload: Mapping[str, Any]) -> str:
    """Hash the canonical content; capture time is intentionally excluded."""

    body = copy.deepcopy(dict(payload))
    body.pop("captured_at", None)
    body.pop("content_hash", None)
    encoded = json.dumps(_safe(body), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _text(value: Any) -> str | None:
    if value is None or value is _MISSING:
        return None
    text = str(value).strip()
    return text or None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _first(mapping: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = mapping.get(name, _MISSING)
        if value is not _MISSING and value not in (None, ""):
            return value
    return None


def _parse_timestamp(value: Any) -> datetime | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _iso(value: Any) -> str | None:
    parsed = _parse_timestamp(value)
    return parsed.isoformat() if parsed is not None else None


def _candidate_identity(candidate: Mapping[str, Any]) -> tuple[str | None, str | None, str | None]:
    return (
        _text(candidate.get("signal_capture_id")),
        _text(candidate.get("signal_id")),
        _text(candidate.get("candidate_id")),
    )


def _identity_quality(candidate: Mapping[str, Any], cycle_id: str) -> str:
    capture_id, signal_id, candidate_id = _candidate_identity(candidate)
    if not (capture_id or signal_id):
        return "unavailable"
    internal_cycle = _text(candidate.get("cycle_id"))
    if internal_cycle and internal_cycle != cycle_id:
        return "ambiguous"
    # candidate_id is useful lineage but is never the sole authority.
    return "verified"


def market_data_observation_id(observation: Mapping[str, Any]) -> str | None:
    """Return deterministic observation identity, never just symbol/date."""

    provider = _text(observation.get("provider"))
    symbol = _text(observation.get("symbol"))
    interval = _text(observation.get("interval"))
    bar_timestamp = _text(observation.get("bar_timestamp") or observation.get("timestamp"))
    price_basis = _text(observation.get("price_basis"))
    if not all((provider, symbol, interval, bar_timestamp, price_basis)):
        return None
    values = _mapping(observation.get("ohlcv"))
    if not values:
        values = {key: observation.get(key) for key in ("open", "high", "low", "close", "volume")}
    normalised = {key: _number(values.get(key)) for key in ("open", "high", "low", "close", "volume")}
    if any(item is None for item in normalised.values()):
        return None
    body = {
        "contract_version": SCHEMA_VERSION,
        "provider": provider,
        "symbol": symbol.upper(),
        "interval": interval,
        "bar_timestamp": bar_timestamp,
        "price_basis": price_basis,
        "ohlcv": normalised,
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _quality_status(observation: Mapping[str, Any]) -> str | None:
    return _text(observation.get("quality_status") or observation.get("status"))


def _temporal_quality(observation: Mapping[str, Any], decision_at: datetime) -> tuple[str, list[str]]:
    warnings: list[str] = []
    bar = _parse_timestamp(observation.get("bar_timestamp") or observation.get("timestamp"))
    as_of = _parse_timestamp(observation.get("data_as_of") or observation.get("as_of"))
    if not bar or not as_of:
        warnings.append("missing_or_invalid_temporal_authority")
        return "unavailable", warnings
    decision = decision_at.astimezone(timezone.utc)
    if bar > decision or as_of > decision:
        warnings.append("observation_after_decision")
        return "unavailable", warnings
    if bar > as_of:
        warnings.append("bar_after_data_as_of")
        return "unavailable", warnings
    return "verified", warnings


def _observation_rows(
    market_snapshot: Mapping[str, Any] | None,
    market_state: Mapping[str, Any] | None,
    technical_context: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    for source in (technical_context, market_snapshot, market_state):
        if not isinstance(source, Mapping):
            continue
        for key in ("market_observations", "observations", "quality_observations", "data_quality_observations"):
            rows = source.get(key)
            if isinstance(rows, Iterable) and not isinstance(rows, (str, bytes, Mapping)):
                return [dict(item) for item in rows if isinstance(item, Mapping)]
    return []


def _candidate_rows(
    technical_context: Mapping[str, Any] | None,
    candidates: Iterable[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    if candidates is not None:
        return [dict(item) for item in candidates if isinstance(item, Mapping)]
    if isinstance(technical_context, Mapping):
        for key in ("all_candidates", "ranked_candidates", "selected_candidates", "candidates"):
            rows = technical_context.get(key)
            if isinstance(rows, Iterable) and not isinstance(rows, (str, bytes, Mapping)):
                return [dict(item) for item in rows if isinstance(item, Mapping)]
    return []


def _detail_from_candidate(
    candidate: Mapping[str, Any],
    observation: Mapping[str, Any] | None,
    *,
    cycle_id: str,
    decision_at: datetime,
) -> dict[str, Any]:
    side = str(candidate.get("side") or candidate.get("direction") or candidate.get("action") or "buy").lower()
    identity = _identity_quality(candidate, cycle_id)
    warnings: list[str] = []
    if side == "sell" or side in {"short", "exit"}:
        reason = "not_applicable_exit"
        identity = "not_applicable"
        temporal = None
        eligible = None
    elif observation is None:
        # Without the exact market observation used by the features there is
        # no safe temporal/quality attribution; symbol-only matching is not an
        # alternative.
        reason = "unavailable_identity"
        temporal = "unavailable"
        eligible = None
        warnings.append("market_observation_not_linked")
    else:
        observation_id = market_data_observation_id(observation)
        expected_id = _text(candidate.get("market_data_observation_id") or candidate.get("market_observation_id"))
        temporal, temporal_warnings = _temporal_quality(observation, decision_at)
        warnings.extend(temporal_warnings)
        if identity != "verified" or not expected_id or not observation_id or expected_id != observation_id:
            reason = "unavailable_identity" if identity != "ambiguous" else "conflict"
            eligible = None
            if expected_id and observation_id and expected_id != observation_id:
                warnings.append("observation_identity_mismatch")
                identity = "conflict"
        elif temporal != "verified":
            reason = "unavailable_temporal"
            eligible = None
        else:
            status = (_quality_status(observation) or "valid").lower()
            invalid_fields = observation.get("invalid_fields") or []
            is_blocking = status in _BLOCKING_QUALITY or bool(invalid_fields and observation.get("affects_operational_scan", True))
            reason = "blocked_exact_quality" if is_blocking else "eligible"
            eligible = False if is_blocking else True
    capture_id, signal_id, candidate_id = _candidate_identity(candidate)
    observation_id = _text((observation or {}).get("market_data_observation_id")) or market_data_observation_id(observation or {})
    detail = {
        "symbol": _text(candidate.get("symbol")),
        "market_data_observation_id": observation_id or _text(candidate.get("market_data_observation_id") or candidate.get("market_observation_id")),
        "provider": _text((observation or {}).get("provider")),
        "bar_timestamp": _text((observation or {}).get("bar_timestamp") or (observation or {}).get("timestamp")),
        "bar_date": _text((observation or {}).get("bar_date")),
        "price_basis": _text((observation or {}).get("price_basis")),
        "data_as_of": _text((observation or {}).get("data_as_of") or (observation or {}).get("as_of")),
        "quality_status": _quality_status(observation or {}),
        "invalid_fields": list((observation or {}).get("invalid_fields") or []),
        "invalidity_class": _text((observation or {}).get("invalidity_class")),
        "blocking_reason": _text((observation or {}).get("blocking_reason")),
        "signal_capture_id": capture_id,
        "signal_id": signal_id,
        "candidate_id": candidate_id,
        "cycle_id": cycle_id,
        "legacy_rank": candidate.get("legacy_rank", candidate.get("rank")),
        "legacy_selected": bool(candidate.get("legacy_selected", candidate.get("selected", False))),
        "legacy_recommended": bool(candidate.get("legacy_recommended", candidate.get("recommended", False))),
        "legacy_gate_status": candidate.get("legacy_gate_status") or candidate.get("gate_status"),
        "legacy_plan_id": _text(candidate.get("legacy_plan_id") or candidate.get("plan_id")),
        "legacy_order_id": _text(candidate.get("legacy_order_id") or candidate.get("broker_order_id")),
        "legacy_planned": bool(candidate.get("legacy_planned", candidate.get("planned", False))),
        "legacy_ordered": bool(candidate.get("legacy_ordered", candidate.get("ordered", False))),
        "side": side,
        "shadow_entry_eligible": eligible,
        "shadow_reason": reason,
        "identity_quality": identity,
        "temporal_quality": temporal,
        "warnings": sorted(set(warnings)),
    }
    if reason not in _SHADOW_REASONS:
        detail["shadow_reason"] = "conflict"
    return detail


def _empty_denominators() -> dict[str, Any]:
    return {
        key: None
        for key in (
            "universe_total", "market_observations", "exact_observations", "blocking_observations",
            "unavailable_observations", "candidates_evaluated", "candidates_with_exact_quality",
            "legacy_selected_count", "shadow_blocked_count", "shadow_unchanged_count", "shadow_unavailable_count",
            "recommended_affected", "planned_affected", "ordered_affected", "protective_exits_exempt",
        )
    }


def capture_data_quality_phase_a(
    *,
    cycle_id: str,
    market_snapshot: Mapping[str, Any] | None = None,
    market_state: Mapping[str, Any] | None = None,
    technical_context: Mapping[str, Any] | None = None,
    candidates: Iterable[Mapping[str, Any]] | None = None,
    decision_at: datetime | None = None,
    captured_at: datetime | None = None,
    session_date: str | None = None,
    detail_limit: int = DEFAULT_DETAIL_LIMIT,
) -> dict[str, Any]:
    """Capture Phase A in memory using only the cycle's existing objects."""

    capture = captured_at or datetime.now(timezone.utc)
    if capture.tzinfo is None:
        capture = capture.replace(tzinfo=timezone.utc)
    capture = capture.astimezone(timezone.utc)
    decision = decision_at or capture
    observations = _observation_rows(market_snapshot, market_state, technical_context)
    candidate_rows = _candidate_rows(technical_context, candidates)
    by_id = {}
    duplicate_ids: set[str] = set()
    for observation in observations:
        identity = market_data_observation_id(observation)
        if identity is None:
            continue
        if identity in by_id:
            duplicate_ids.add(identity)
        else:
            by_id[identity] = observation
    details = []
    for candidate in candidate_rows:
        expected_id = _text(candidate.get("market_data_observation_id") or candidate.get("market_observation_id"))
        observation = by_id.get(expected_id or "")
        detail = _detail_from_candidate(candidate, observation, cycle_id=cycle_id, decision_at=decision)
        if expected_id in duplicate_ids:
            detail["shadow_reason"] = "conflict"
            detail["shadow_entry_eligible"] = None
            detail["identity_quality"] = "ambiguous"
            detail["warnings"] = sorted(set([*detail.get("warnings", []), "duplicate_market_observation_id"]))
        details.append(detail)
    represented_observations = {item.get("market_data_observation_id") for item in details if item.get("market_data_observation_id")}
    # Every blocking observation is retained even when it has no candidate
    # link; it is explicitly unavailable rather than inferred by symbol.
    for observation in observations:
        observation_id = market_data_observation_id(observation)
        if observation_id in represented_observations:
            continue
        if (_quality_status(observation) or "").lower() not in _BLOCKING_QUALITY and not observation.get("invalid_fields"):
            continue
        detail = _detail_from_candidate(
            {"symbol": observation.get("symbol"), "side": "buy", "cycle_id": cycle_id},
            observation,
            cycle_id=cycle_id,
            decision_at=decision,
        )
        detail["shadow_reason"] = "unavailable_identity"
        detail["shadow_entry_eligible"] = None
        detail["blocking_observation"] = True
        detail["warnings"] = sorted(set([*detail.get("warnings", []), "blocking_observation_without_candidate_identity"]))
        details.append(detail)
    blocking = sum(item.get("quality_status") in _BLOCKING_QUALITY for item in observations)
    exact = len(by_id)
    denom = _empty_denominators()
    denom.update({
        "universe_total": len(market_snapshot.get("symbols", {})) if isinstance(market_snapshot, Mapping) and isinstance(market_snapshot.get("symbols"), Mapping) else (len(observations) if observations else None),
        "market_observations": len(observations) if observations else None,
        "exact_observations": exact if observations else None,
        "blocking_observations": blocking if observations else None,
        "unavailable_observations": (len(observations) - exact) if observations else None,
        "candidates_evaluated": len(candidate_rows) if candidate_rows else None,
        "candidates_with_exact_quality": sum(item.get("identity_quality") == "verified" for item in details) if details else None,
        "legacy_selected_count": sum(bool(item.get("legacy_selected")) for item in details) if details else None,
        "shadow_blocked_count": sum(item.get("shadow_reason") == "blocked_exact_quality" for item in details) if details else None,
        "shadow_unchanged_count": sum(item.get("shadow_reason") == "eligible" for item in details) if details else None,
        "shadow_unavailable_count": sum(item.get("shadow_reason") in {"unavailable_identity", "unavailable_temporal"} for item in details) if details else None,
        "protective_exits_exempt": sum(item.get("shadow_reason") == "not_applicable_exit" for item in details) if details else None,
    })
    warnings = []
    if not observations:
        warnings.append("phase_a_market_observations_unavailable")
    if duplicate_ids:
        warnings.append("duplicate_market_observation_identity")
    limit = max(0, int(detail_limit))
    forced = [item for item in details if item.get("blocking_observation") or item.get("legacy_selected") or item.get("shadow_reason") == "blocked_exact_quality"]
    included = []
    for item in details:
        if len(included) < limit or item in forced:
            included.append(item)
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "cycle_id": str(cycle_id),
        "captured_at": capture.isoformat(),
        "content_hash": None,
        "market_data_snapshot_id": _text((market_snapshot or {}).get("snapshot_id") or (market_snapshot or {}).get("id")),
        "source": _text((market_snapshot or {}).get("provider") or (market_state or {}).get("provider")) or "cycle_memory",
        "as_of": _text((market_snapshot or {}).get("as_of") or (market_state or {}).get("as_of")),
        "session_date": session_date or capture.date().isoformat(),
        "status": "available" if observations else "collecting",
        "denominators": denom,
        "details": included,
        "warnings": sorted(set(warnings)),
        "details_included": len(included),
        "details_omitted": max(0, len(details) - len(included)),
        "blocking_details_included": sum(bool(item.get("blocking_observation")) or item.get("shadow_reason") == "blocked_exact_quality" for item in included),
        "selected_details_included": sum(bool(item.get("legacy_selected")) for item in included),
        "_phase": "A",
    }
    snapshot["content_hash"] = canonical_content_hash(snapshot)
    return snapshot


def _identity_key(row: Mapping[str, Any]) -> tuple[str | None, str | None, str | None]:
    lineage = _mapping(row.get("decision_lineage") or row.get("lineage"))
    payload = _mapping(row.get("payload"))
    return tuple(
        _text(row.get(key) or lineage.get(key) or payload.get(key))
        for key in ("signal_capture_id", "signal_id", "candidate_id")
    )


def _matches(detail: Mapping[str, Any], row: Mapping[str, Any], cycle_id: str) -> bool:
    if _text(row.get("cycle_id")) and _text(row.get("cycle_id")) != cycle_id:
        return False
    detail_values = _identity_key(detail)
    row_values = _identity_key(row)
    # At least one canonical identity must match, and any identity present on
    # both sides must agree.  Symbol-only matching is intentionally forbidden.
    if not any(value and value == row_value for value, row_value in zip(detail_values, row_values, strict=True)):
        return False
    return all(not value or not row_value or value == row_value for value, row_value in zip(detail_values, row_values, strict=True))


def _as_mapping(item: Any) -> dict[str, Any]:
    if isinstance(item, Mapping):
        return dict(item)
    try:
        from dataclasses import asdict

        value = asdict(item)
        return value if isinstance(value, Mapping) else {}
    except (TypeError, ValueError):
        return {}


def finalize_data_quality_phase_b(
    phase_a: Mapping[str, Any],
    *,
    recommendations: Iterable[Any] | None = None,
    plans: Iterable[Any] | None = None,
    rejected_order_plans: Iterable[Mapping[str, Any]] | None = None,
    orders: Iterable[Mapping[str, Any]] | None = None,
    cycle_id: str | None = None,
    phase_b_available: bool = True,
    detail_limit: int | None = None,
) -> dict[str, Any]:
    """Finalize the capture without rerunning any active decision stage."""

    snapshot = copy.deepcopy(dict(phase_a))
    run_id = str(cycle_id or snapshot.get("cycle_id") or "")
    details = [dict(item) for item in snapshot.get("details", []) if isinstance(item, Mapping)]
    rows = [_as_mapping(item) for item in (recommendations or [])]
    plan_rows = [_as_mapping(item) for item in (plans or [])]
    rejection_rows = [dict(item) for item in (rejected_order_plans or []) if isinstance(item, Mapping)]
    order_rows = [dict(item) for item in (orders or []) if isinstance(item, Mapping)]
    for detail in details:
        matches = [row for row in rows if _matches(detail, row, run_id)]
        plan_matches = [row for row in plan_rows if _matches(detail, row, run_id)]
        order_matches = [row for row in order_rows if _matches(detail, row, run_id)]
        if matches:
            detail["legacy_selected"] = bool(detail.get("legacy_selected") or any(row.get("selected") or row.get("legacy_selected") for row in matches))
            detail["legacy_recommended"] = True
            detail["legacy_rank"] = next((row.get("rank") for row in matches if row.get("rank") is not None), detail.get("legacy_rank"))
            detail["legacy_gate_status"] = next((row.get("gate_status") or row.get("legacy_gate_status") for row in matches if row.get("gate_status") or row.get("legacy_gate_status")), detail.get("legacy_gate_status"))
            detail["legacy_plan_id"] = detail.get("legacy_plan_id") or _text(matches[0].get("plan_id"))
        if plan_matches:
            detail["legacy_planned"] = True
            detail["legacy_plan_id"] = _text(plan_matches[0].get("plan_id")) or detail.get("legacy_plan_id")
        if order_matches:
            detail["legacy_ordered"] = True
            detail["legacy_order_id"] = _text(order_matches[0].get("broker_order_id")) or detail.get("legacy_order_id")
        if detail.get("side") == "sell":
            detail["shadow_reason"] = "not_applicable_exit"
            detail["shadow_entry_eligible"] = None
    # Include controls/rejections only when they carry an exact identity. They
    # cannot become synthetic blockers and do not change active decisions.
    for row in rejection_rows:
        if any(_matches(detail, row, run_id) for detail in details):
            details.append({
                "symbol": _text(row.get("symbol")),
                "market_data_observation_id": None,
                "provider": None,
                "bar_timestamp": None,
                "bar_date": None,
                "price_basis": None,
                "data_as_of": None,
                "quality_status": None,
                "invalid_fields": [],
                "invalidity_class": None,
                "blocking_reason": None,
                "signal_capture_id": _text(row.get("signal_capture_id")),
                "signal_id": _text(row.get("signal_id")),
                "candidate_id": _text(row.get("candidate_id")),
                "cycle_id": run_id,
                "legacy_rank": None,
                "legacy_selected": False,
                "legacy_recommended": False,
                "legacy_gate_status": row.get("reason"),
                "legacy_plan_id": _text(row.get("plan_id")),
                "legacy_order_id": None,
                "legacy_planned": False,
                "legacy_ordered": False,
                "shadow_entry_eligible": None,
                "shadow_reason": "conflict" if row.get("identity_quality") == "ambiguous" else "unavailable_identity",
                "identity_quality": row.get("identity_quality") or "partial",
                "temporal_quality": None,
                "warnings": ["active_rejection_observed"],
            })
    limit = detail_limit if detail_limit is not None else len(details)
    forced = [item for item in details if item.get("blocking_observation") or item.get("legacy_selected") or item.get("legacy_recommended") or item.get("legacy_planned") or item.get("legacy_ordered") or item.get("shadow_reason") == "blocked_exact_quality"]
    forced_ids = {id(item) for item in forced}
    kept = []
    for item in details:
        if len(kept) < max(0, int(limit)) or id(item) in forced_ids:
            kept.append(item)
    denom = dict(snapshot.get("denominators") or _empty_denominators())
    denom.update({
        "candidates_evaluated": len(details) if details else denom.get("candidates_evaluated"),
        "candidates_with_exact_quality": sum(item.get("identity_quality") == "verified" for item in details) if details else denom.get("candidates_with_exact_quality"),
        "legacy_selected_count": sum(bool(item.get("legacy_selected")) for item in details) if details else denom.get("legacy_selected_count"),
        "shadow_blocked_count": sum(item.get("shadow_reason") == "blocked_exact_quality" for item in details) if details else denom.get("shadow_blocked_count"),
        "shadow_unchanged_count": sum(item.get("shadow_reason") == "eligible" for item in details) if details else denom.get("shadow_unchanged_count"),
        "shadow_unavailable_count": sum(item.get("shadow_reason") in {"unavailable_identity", "unavailable_temporal"} for item in details) if details else denom.get("shadow_unavailable_count"),
        "recommended_affected": sum(bool(item.get("legacy_recommended")) and item.get("shadow_reason") == "blocked_exact_quality" for item in details) if details else denom.get("recommended_affected"),
        "planned_affected": sum(bool(item.get("legacy_planned")) and item.get("shadow_reason") == "blocked_exact_quality" for item in details) if details else denom.get("planned_affected"),
        "ordered_affected": sum(bool(item.get("legacy_ordered")) and item.get("shadow_reason") == "blocked_exact_quality" for item in details) if details else denom.get("ordered_affected"),
        "protective_exits_exempt": sum(item.get("shadow_reason") == "not_applicable_exit" for item in details) if details else denom.get("protective_exits_exempt"),
    })
    snapshot["cycle_id"] = run_id
    snapshot["details"] = kept
    snapshot["denominators"] = denom
    snapshot["details_included"] = len(kept)
    snapshot["details_omitted"] = max(0, len(details) - len(kept))
    snapshot["blocking_details_included"] = sum(bool(item.get("blocking_observation")) or item.get("shadow_reason") == "blocked_exact_quality" for item in kept)
    snapshot["selected_details_included"] = sum(bool(item.get("legacy_selected")) for item in kept)
    warnings = list(snapshot.get("warnings") or [])
    if len(kept) < len(details):
        warnings.append("detail_limit_reached")
    if not phase_b_available:
        warnings.append("phase_b_unavailable")
        snapshot["status"] = "partial"
    elif not details:
        snapshot["status"] = "unavailable"
    else:
        snapshot["status"] = "available" if not any(item.get("shadow_reason") in {"unavailable_identity", "unavailable_temporal", "conflict"} for item in details) else "partial"
    snapshot.pop("_phase", None)
    snapshot["warnings"] = sorted(set(warnings))
    snapshot["content_hash"] = canonical_content_hash(snapshot)
    return snapshot


def _unavailable_snapshot(cycle_id: str, warning: str) -> dict[str, Any]:
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "cycle_id": cycle_id,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "content_hash": None,
        "market_data_snapshot_id": None,
        "source": None,
        "as_of": None,
        "session_date": datetime.now(timezone.utc).date().isoformat(),
        "status": "unavailable",
        "denominators": _empty_denominators(),
        "details": [],
        "warnings": [warning],
        "details_included": 0,
        "details_omitted": 0,
        "blocking_details_included": 0,
        "selected_details_included": 0,
    }
    snapshot["content_hash"] = canonical_content_hash(snapshot)
    return snapshot


def persist_data_quality_decision_shadow(store: Store, snapshot: Mapping[str, Any]) -> dict[str, Any]:
    event_id = EVENT_ID_PREFIX + str(snapshot.get("cycle_id") or "unknown")
    return store.record_data_quality_decision_shadow(dict(snapshot), event_id=event_id)


def read_data_quality_decision_shadow(store: Store, cycle_id: str) -> dict[str, Any]:
    event = store.data_quality_decision_shadow_event(cycle_id)
    if event is None:
        return {"schema_version": SCHEMA_VERSION, "cycle_id": cycle_id, "status": "collecting", "denominators": None, "details": [], "warnings": []}
    payload = dict(event.get("payload") or {})
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("content_hash") != canonical_content_hash(payload):
        return {"schema_version": SCHEMA_VERSION, "cycle_id": cycle_id, "status": "legacy_without_shadow", "denominators": None, "details": [], "warnings": ["invalid_canonical_event"]}
    return payload


def _events(store: Store) -> list[dict[str, Any]]:
    try:
        reader = getattr(store, "data_quality_decision_shadow_events", None)
        rows = reader(limit=50000) if callable(reader) else store.agent_events(event_type_prefix=EVENT_TYPE, limit=50000)
    finally:
        try:
            store.close_read_connection()
        except Exception:
            pass
    return rows


def data_quality_decision_shadow_digest(store: Store, cycle_id: str | None = None) -> dict[str, Any]:
    if cycle_id:
        payload = read_data_quality_decision_shadow(store, cycle_id)
        conflicts = [item for item in _events(store) if str(item.get("event_type") or "") == EVENT_TYPE + "_conflict" and str(item.get("event_id") or "").startswith(EVENT_ID_PREFIX + cycle_id + ":conflict:")]
        return {"status": payload.get("status", "collecting"), "cycle_id": cycle_id, "denominators": payload.get("denominators"), "details_included": payload.get("details_included"), "details_omitted": payload.get("details_omitted"), "conflict_events": len(conflicts), "warnings": payload.get("warnings", [])}
    events = _events(store)
    snapshots = [item for item in events if item.get("event_type") == EVENT_TYPE]
    conflicts = [item for item in events if item.get("event_type") == EVENT_TYPE + "_conflict"]
    if not snapshots:
        return {"status": "conflict" if conflicts else "collecting", "cycle_id": None, "denominators": None, "canonical_events": 0, "conflict_events": len(conflicts)}
    latest = sorted(snapshots, key=lambda item: str(item.get("created_at") or ""))[-1]
    payload = latest.get("payload") or {}
    return {"status": payload.get("status", "collecting"), "cycle_id": payload.get("cycle_id"), "denominators": payload.get("denominators"), "canonical_events": len(snapshots), "conflict_events": len(conflicts), "details_included": payload.get("details_included"), "details_omitted": payload.get("details_omitted"), "warnings": payload.get("warnings", [])}


def quality_report_freshness(
    report: Mapping[str, Any] | None,
    *,
    consumer_read_at: datetime,
    expected_session: str | None = None,
    source_path: str | None = None,
    expected_content_hash: str | None = None,
) -> dict[str, Any]:
    """Read-only freshness contract used by health consumers."""

    result = {
        "report_id": None,
        "generated_at": None,
        "as_of": None,
        "consumer_read_at": consumer_read_at.astimezone(timezone.utc).isoformat(),
        "age_seconds": None,
        "source_path": source_path,
        "session_date": expected_session,
        "freshness_status": "unavailable",
    }
    if not isinstance(report, Mapping) or not source_path:
        return result
    result.update({key: report.get(key) for key in ("report_id", "generated_at", "as_of", "session_date")})
    if expected_session and report.get("session_date") not in (None, expected_session):
        result["freshness_status"] = "stale_session"
        return result
    if expected_content_hash is not None and report.get("content_hash") != expected_content_hash:
        result["freshness_status"] = "invalid_hash"
        return result
    generated = _parse_timestamp(report.get("generated_at"))
    if generated is None:
        return result
    age = (consumer_read_at.astimezone(timezone.utc) - generated).total_seconds()
    result["age_seconds"] = round(age, 6)
    result["freshness_status"] = "fresh" if age >= 0 else "future"
    return result


# Aliases make the phase boundary explicit for callers and keep test helpers
# readable without creating a second implementation.
capture_phase_a = capture_data_quality_phase_a
finalize_phase_b = finalize_data_quality_phase_b
build_data_quality_decision_shadow = capture_data_quality_phase_a
