"""Post-route allocation observation over already loaded exact carriers."""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any

from .capital_allocation_policy import cap_allocation_notional, policy_fingerprint
from .opportunity_quality_shadow import build_opportunity_quality_carrier

SCHEMA_VERSION = "capital-allocation-shadow.v1"
EVENT_TYPE = "capital_allocation_shadow"


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return asdict(value) if is_dataclass(value) and not isinstance(value, type) else {}


def _numeric(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (ValueError, TypeError):
        return None
    return n if math.isfinite(n) else None


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def _action(value: Any) -> str | None:
    raw = _mapping(value)
    lineage = _mapping(raw.get("decision_lineage"))
    action = _text(raw.get("action") or raw.get("side") or lineage.get("action"))
    if action is None:
        return None
    action = action.lower()
    if action in {"sell", "reduce", "exit"}:
        return "exit"
    return "buy" if action == "buy" else None


def _exact_value(sources: Sequence[Mapping[str, Any]], *keys: str) -> str | None:
    values: list[str] = []
    for source in sources:
        for key in keys:
            value = _text(source.get(key))
            if value is not None:
                values.append(value)
    return values[0] if values and len(set(values)) == 1 else None


def _identity(value: Any, cycle_id: str) -> dict[str, str] | None:
    """Return the exact compact funnel key plus its candidate binding.

    Funnel identity is ``cycle|action|signal_capture|recommendation``.  A
    symbol/date join is never a substitute for this key.  Candidate identity
    remains a separate exact binding because it is not part of the compact
    funnel key.
    """
    raw = _mapping(value)
    payload = _mapping(raw.get("payload"))
    rec = _mapping(payload.get("recommendation") or raw.get("recommendation"))
    lineage = _mapping(raw.get("decision_lineage") or payload.get("decision_lineage") or rec.get("decision_lineage"))
    rec_lineage = _mapping(rec.get("decision_lineage"))
    sources = (raw, payload, rec, lineage, rec_lineage)
    for field in ("cycle_id", "candidate_id", "signal_capture_id", "recommendation_id"):
        values = {_text(source.get(field)) for source in sources if _text(source.get(field)) is not None}
        if len(values) > 1:
            return None
    actions = {_action(source) for source in sources if _action(source) is not None}
    if len(actions) > 1:
        return None
    declared_key = _text(raw.get("identity_key") or payload.get("identity_key"))
    declared_parts: tuple[str, str, str, str] | None = None
    if declared_key is not None:
        parts = tuple(part.strip() for part in declared_key.split("|"))
        if len(parts) != 4 or any(not part for part in parts):
            return None
        declared_parts = parts  # type: ignore[assignment]
    embedded_cycle = _exact_value(sources, "cycle_id")
    if embedded_cycle is not None and embedded_cycle != str(cycle_id):
        return None
    action = _action(raw) or _action(payload) or _action(rec) or _action(lineage)
    capture = _exact_value(sources, "signal_capture_id")
    recommendation = _exact_value(sources, "recommendation_id")
    candidate = _exact_value(sources, "candidate_id")
    if declared_parts is not None:
        declared_cycle, declared_action, declared_capture, declared_recommendation = declared_parts
        if declared_cycle != str(cycle_id):
            return None
        if action is not None and action != declared_action:
            return None
        if capture is not None and capture != declared_capture:
            return None
        if recommendation is not None and recommendation != declared_recommendation:
            return None
        action, capture, recommendation = declared_action, declared_capture, declared_recommendation
    if not action or not capture or not recommendation or not candidate:
        return None
    if any("|" in value for value in (str(cycle_id), action, capture, recommendation, candidate)):
        return None
    if embedded_cycle is None and declared_parts is None:
        return None
    identity_key = "|".join((str(cycle_id), action, capture, recommendation))
    return {
        "identity_key": identity_key,
        "cycle_id": str(cycle_id),
        "action": action,
        "candidate_id": candidate,
        "signal_capture_id": capture,
        "recommendation_id": recommendation,
    }


def _quality_identity(identity: Mapping[str, Any], symbol: Any) -> dict[str, Any]:
    result = {key: value for key, value in identity.items() if key != "identity_key"}
    result["symbol"] = _text(symbol).upper() if _text(symbol) else None
    return result


def _quality_unavailable(identity: Mapping[str, Any], reason: str) -> dict[str, Any]:
    components = {name: None for name in ("technical", "news", "empirical_llm_reliability", "setup")}
    return {
        "status": "unavailable",
        "score": None,
        "combined_score": None,
        "challenger_score": None,
        "score_type": "calibrated_challenger",
        "components": components,
        "coverage": {
            "available_components": [],
            "missing_components": list(components),
            "component_count": 0,
            "component_total": len(components),
            "ratio": 0.0,
            "weights_redistributed": False,
        },
        "identity": dict(identity),
        "carrier_identity": dict(identity),
        "reason_codes": [reason],
        "authority": {
            "mode": "shadow",
            "shadow_only": True,
            "can_authorize_size": False,
            "size_authorized": False,
            "can_change_orders": False,
            "can_select_candidate": False,
            "can_promote_policy": False,
        },
    }


def _aware_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _quality_observation(
    recommendation: Mapping[str, Any],
    identity: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if identity is None:
        return _quality_unavailable({}, "identity_unavailable")
    snapshot = _mapping(recommendation.get("decision_context_snapshot"))
    expected_identity = _quality_identity(identity, recommendation.get("symbol"))
    existing = snapshot.get("opportunity_quality_shadow")
    if isinstance(existing, Mapping):
        existing_identity = _mapping(existing.get("identity") or existing.get("carrier_identity"))
        required = ("candidate_id", "signal_capture_id", "recommendation_id", "symbol")
        if all(_text(existing_identity.get(key)) == _text(expected_identity.get(key)) for key in required):
            return dict(existing)
        return _quality_unavailable(expected_identity, "quality_identity_mismatch")

    source = snapshot.get("opportunity_quality_input")
    if not isinstance(source, Mapping):
        source = snapshot.get("opportunity_quality")
    quality = dict(source) if isinstance(source, Mapping) else {}
    explicit_fields = (
        "technical", "setup", "news", "news_evidence", "news_ids", "model_id", "model_version",
        "prompt_version", "llm", "llm_calibration", "empirical_llm_calibration", "calibration_receipt",
        "validated_net_expectancy", "net_expectancy_evidence", "higher_tier_evidence", "hard_gates",
        "horizon_sessions", "currency", "policy_hash", "current_selection_score",
        "current_selection_components", "selection_components", "champion_calibration",
    )
    for field in explicit_fields:
        if field not in quality and field in snapshot:
            quality[field] = snapshot[field]
    declared_identity = _mapping(quality.get("identity"))
    if any(key in declared_identity and _text(declared_identity[key]) != _text(value)
           for key, value in expected_identity.items()):
        return _quality_unavailable(expected_identity, "quality_identity_mismatch")
    quality["identity"] = {
        **_mapping(quality.get("identity")),
        **expected_identity,
    }
    decision_at = _aware_datetime(snapshot.get("decision_at") or snapshot.get("captured_at"))
    if decision_at is None:
        return _quality_unavailable(expected_identity, "quality_decision_at_unavailable")
    return build_opportunity_quality_carrier(quality, decision_at=decision_at)


def shadow_content_hash(payload: Mapping[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key not in {"captured_at", "content_hash"}}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def build_capital_allocation_shadow(
    *, cycle_id: str, policy: Mapping[str, Any], portfolio: Any, recommendations: Sequence[Any] | None,
    plans: Sequence[Any] | None, funnel: Mapping[str, Any], captured_at: datetime | None = None,
    allocation_observations: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Hypothetical amounts are observations, never executable opportunities."""
    observed = captured_at or datetime.now(timezone.utc)
    if observed.utcoffset() is None:
        raise ValueError("shadow_clock_timezone_required")
    account = _mapping(portfolio)
    equity = _numeric(account.get("portfolio_value"))
    positions = account.get("positions")
    orders = account.get("open_orders")
    positions_complete = isinstance(positions, list)
    current_value = 0.0
    for item in positions or []:
        position = _mapping(item)
        value = _numeric(position.get("market_value"))
        if value is None:
            positions_complete = False
            break
        current_value += abs(value)
    current_exposure = current_value / equity if positions_complete and equity and equity > 0 else None
    pending_cash = 0.0 if isinstance(orders, list) else None
    for item in orders or []:
        order = _mapping(item)
        if str(order.get("side", "")).lower() != "buy":
            continue
        amount = _numeric(order.get("notional"))
        if amount is None or amount < 0:
            pending_cash = None
            break
        pending_cash += amount
    observations = list(allocation_observations or [])[:601]
    reserves = [row for row in observations if row.get("kind") == "portfolio_reservations"]
    local_complete = len(reserves) == 1 and reserves[0].get("pending_plan_reservations_complete") is True
    local_cash = _numeric(reserves[0].get("pending_buy_notional")) if local_complete else None
    if local_complete and local_cash is not None and local_cash >= 0 and pending_cash is not None:
        pending_cash += local_cash
    elif reserves:
        pending_cash = None
    pending_exposure = pending_cash / equity if pending_cash is not None and equity and equity > 0 else None
    sizing_index = {}
    for observation in observations:
        if observation.get("kind") != "sizing":
            continue
        observed_identity = _identity({"action": "buy", "decision_lineage": observation.get("identity")}, cycle_id)
        if observed_identity:
            sizing_index[observed_identity["identity_key"]] = observation

    recs = list(recommendations or [])
    rec_identities = [_identity(r, cycle_id) for r in recs]
    rec_keys = [identity["identity_key"] if identity else None for identity in rec_identities]
    duplicate_keys = {key for key, count in Counter(k for k in rec_keys if k).items() if count > 1}
    plan_index: dict[str, dict[str, Any]] = {}
    for item in plans or []:
        identity = _identity(item, cycle_id)
        raw = _mapping(item)
        key = identity["identity_key"] if identity else None
        if key:
            if key in plan_index:
                duplicate_keys.add(key)
            plan_index[key] = {"payload": _mapping(raw.get("payload")) or raw, "identity": identity}
    frontier: dict[str, dict[str, Any]] = {}
    for item in funnel.get("details", []):
        identity = _identity(item, cycle_id)
        key = identity["identity_key"] if identity else None
        if key:
            frontier[key] = {**_mapping(item), "_identity": identity}
    rows = []
    stage_planned_cash = {str(stage): 0.0 for stage in (2, 3, 4)}
    stage_planned_exposure = {str(stage): 0.0 for stage in (2, 3, 4)}
    for item, identity, key in zip(recs[:600], rec_identities[:600], rec_keys[:600], strict=True):
        rec = _mapping(item)
        if _action(rec) != "buy":
            continue
        identity = identity or {}
        plan_entry = plan_index.get(key, {}) if key and key not in duplicate_keys else {}
        plan_identity = plan_entry.get("identity") if isinstance(plan_entry, Mapping) else None
        if (
            plan_identity is not None
            and plan_identity.get("candidate_id") != identity.get("candidate_id")
        ):
            plan_entry = {}
            duplicate_keys.add(key)
        plan = plan_entry.get("payload", {}) if isinstance(plan_entry, Mapping) else {}
        checks = _mapping(_mapping(plan.get("risk_decision")).get("checks"))
        sizing = _mapping(checks.get("position_sizing"))
        amounts = [_numeric(sizing.get(field)) for field in (
            "max_risk_notional", "adjusted_target_notional", "available_position_room", "available_buying_power"
        )]
        requested = min(amounts) if all(value is not None and value >= 0 for value in amounts) else None
        sizing_observation = sizing_index.get(key, {}) if key and key not in duplicate_keys else {}
        if sizing_observation:
            requested = _numeric(sizing_observation.get("requested_before_learning_cap"))
            sizing = _mapping(sizing_observation.get("sizing"))
        f = frontier.get(key, {}) if key else {}
        frontier_identity = f.get("_identity") if isinstance(f, Mapping) else None
        if (
            frontier_identity is not None
            and frontier_identity.get("candidate_id") != identity.get("candidate_id")
        ):
            f = {}
            duplicate_keys.add(key)
        variants = {}
        for stage in (2, 3, 4):
            variant = {**policy, "stage": stage}
            variant["policy_hash"] = policy_fingerprint(variant)
            stage_key = str(stage)
            planned_cash_before = stage_planned_cash[stage_key]
            planned_exposure_before = stage_planned_exposure[stage_key]
            capped, projection = cap_allocation_notional(
                variant, desired_notional=requested, equity=equity, cash=account.get("cash"),
                buying_power=account.get("buying_power"), current_exposure=current_exposure,
                pending_exposure=pending_exposure, planned_exposure=planned_exposure_before,
                pending_buy_notional=pending_cash, planned_buy_notional=planned_cash_before,
            )
            hypothetical = capped if projection.get("status") == "verified" else None
            if hypothetical is not None and equity and equity > 0:
                stage_planned_cash[stage_key] += hypothetical
                stage_planned_exposure[stage_key] += hypothetical / equity
            variants[stage_key] = {
                **projection,
                "hypothetical_notional": hypothetical,
                "executable": False,
                "batch_reservations": "observed_local_and_broker" if local_complete else "unavailable",
                "budget_projection_status": "non_executable",
                "planned_buy_notional_before": planned_cash_before,
                "planned_exposure_before": planned_exposure_before,
                "pending_local": local_cash if local_complete else "unavailable",
                "batch_remaining": "unavailable" if requested is None else "projected_only",
            }
        quality = _quality_observation(rec, identity)
        row = {"identity": identity or {},
               "identity_status": "verified" if key and key not in duplicate_keys else "unavailable",
               "identity_key": key,
               "symbol": rec.get("symbol"), "action": "buy", "variants": variants,
               "baseline_notional": _numeric(plan.get("notional")), "requested_before_learning_cap": requested,
               "first_effective_boundary": f.get("primary_drop_reason"), "sizing": sizing,
               "quality": quality,
               "daily_risk_budget": {"configured_pct": None, "enforcement": "unavailable"},
               "broker_protection": "unavailable", "future_returns": "unavailable"}
        rows.append(row)
    portfolio_available = bool(
        equity is not None
        and _numeric(account.get("cash")) is not None
        and _numeric(account.get("buying_power")) is not None
        and positions_complete
        and isinstance(orders, list)
    )
    payload = {"schema_version": SCHEMA_VERSION, "event_type": EVENT_TYPE, "cycle_id": cycle_id,
               "policy_hash": policy.get("policy_hash") or policy_fingerprint(policy),
               "policy_registered_at": policy.get("registered_at"), "source_funnel_hash": funnel.get("content_hash"),
               "captured_at": observed.astimezone(timezone.utc).isoformat(),
               "authority": "shadow_only", "can_authorize_size": False, "can_change_orders": False,
               "status": "collecting", "denominators": {"recommendations": len(recs),
                   "buy_recommendations": sum(_action(rec) == "buy" for rec in recs),
                   "verified_buy_identities": sum(identity is not None and identity["action"] == "buy" and key not in duplicate_keys for identity, key in zip(rec_identities, rec_keys, strict=True)),
                   "verified_identities_persisted": sum(row["identity_status"] == "verified" for row in rows),
                   "rows_persisted": len(rows), "rows_omitted": max(0, len(recs) - 600),
                   "portfolio_coverage": "available" if portfolio_available else "unavailable"},
               "account": {"equity": equity, "cash": account.get("cash"), "current_exposure": current_exposure,
                           "pending_buy_notional": pending_cash}, "details": rows}
    payload["event_id"] = f"{EVENT_TYPE}:{payload['policy_hash']}:{cycle_id}"
    payload["content_hash"] = shadow_content_hash(payload)
    return payload


def persist_capital_allocation_shadow(store: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
    if shadow_content_hash(payload) != payload.get("content_hash"):
        raise ValueError("allocation_shadow_content_hash_mismatch")
    return store.record_append_only_event(event_id=payload["event_id"], event_type=EVENT_TYPE,
        cycle_id=payload["cycle_id"], payload=dict(payload), lock_timeout_seconds=0.05,
        idempotent_on_content_hash=True)
