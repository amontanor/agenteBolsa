"""Fail-open shadow contract for the capital-deployment funnel.

The active decision path supplies already-made observations to this module.
This module never calls a gate, selector, RiskManager, broker or data source.
It only projects exact identities and the transitions that the active path has
already produced into one bounded, append-only event.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from ..storage import Store


SCHEMA_VERSION = "p-l54b.capital-deployment-funnel-shadow.v1"
EVENT_TYPE = "capital_deployment_funnel_shadow"
EVENT_ID_PREFIX = "capital_deployment_funnel_shadow:"
DEFAULT_DETAIL_LIMIT = 600
STAGE_ORDER = ("selection", "gates", "capacity", "sizing", "risk", "plans", "orders", "fills")
DROP_REASONS = {
    "not_selected",
    "gate_rejected",
    "gate_unavailable",
    "capacity_exhausted",
    "sizing_zero",
    "sizing_unavailable",
    "cap_limited",
    "risk_rejected",
    "risk_unavailable",
    "post_plan_filtered",
    "quota_duplicate_guard",
    "identity_unavailable",
    "identity_ambiguous",
    "temporal_unavailable",
    "not_generated",
    "execution_rejected_cancelled",
    "execution_unavailable",
    "not_applicable_exit",
}
_STAGE_ALIASES = {
    "gate": "gates",
    "gate_pre": "gates",
    "capacity_check": "capacity",
    "execution_sizing": "sizing",
    "risk_manager": "risk",
    "plan": "plans",
    "order": "orders",
    "fill": "fills",
}


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    return {}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _finite(value: Any, *, allow_negative: bool = True) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or (not allow_negative and number < 0):
        return None
    return round(number, 8)


def _safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def content_hash(payload: Mapping[str, Any]) -> str:
    body = copy.deepcopy(dict(payload))
    body.pop("captured_at", None)
    body.pop("content_hash", None)
    encoded = json.dumps(_safe(body), ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _action(value: Any) -> str | None:
    row = _mapping(value)
    lineage = _mapping(row.get("decision_lineage"))
    raw = _text(row.get("action") or row.get("side") or lineage.get("action"))
    if raw is None:
        return None
    raw = raw.lower()
    if raw in {"sell", "reduce", "exit"}:
        return "exit"
    if raw == "buy":
        return "buy"
    return None


def _identity_info(value: Any, cycle_id: str) -> dict[str, Any]:
    row = _mapping(value)
    lineage = _mapping(row.get("decision_lineage"))
    external_cycle = _text(cycle_id)
    embedded_cycle = _text(row.get("cycle_id")) or _text(lineage.get("cycle_id"))
    action = _action(row)
    capture = _text(row.get("signal_capture_id") or lineage.get("signal_capture_id"))
    signal = _text(row.get("signal_id") or lineage.get("signal_id"))
    canonical_signal = capture or signal
    recommendation = _text(row.get("recommendation_id") or lineage.get("recommendation_id"))
    cycle_mismatch = bool(embedded_cycle and external_cycle and embedded_cycle != external_cycle)
    signal_key = (external_cycle, action, canonical_signal) if external_cycle and action and canonical_signal and not cycle_mismatch else None
    decision_key = signal_key + (recommendation,) if signal_key and recommendation else None
    signal_quality = "verified" if signal_key else "unavailable"
    if cycle_mismatch:
        reason = "cycle_mismatch"
    elif not action or not canonical_signal or not external_cycle:
        reason = "identity_unavailable"
    else:
        reason = None
    decision_quality = "verified" if decision_key else "partial" if signal_key else "unavailable"
    return {
        "external_cycle": external_cycle,
        "embedded_cycle": embedded_cycle,
        "cycle_mismatch": cycle_mismatch,
        "action": action,
        "signal_capture_id": capture,
        "signal_id": signal,
        "canonical_signal": canonical_signal,
        "recommendation_id": recommendation,
        "signal_key": signal_key,
        "decision_key": decision_key,
        "signal_quality": signal_quality,
        "decision_quality": decision_quality,
        "reason": reason,
    }


def _identity(value: Any, cycle_id: str) -> tuple[str, str, str, str] | None:
    return _identity_info(value, cycle_id)["decision_key"]


def _identity_text(key: tuple[str, ...] | None) -> str | None:
    return "|".join(key) if key else None


def _timestamp(value: Any, captured_at: datetime, warnings: list[str], field: str) -> str | None:
    raw = _text(value)
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        warnings.append(f"invalid_timestamp:{field}")
        return None
    if parsed.tzinfo is None:
        warnings.append(f"naive_timestamp:{field}")
        return None
    parsed = parsed.astimezone(timezone.utc)
    if parsed > captured_at:
        warnings.append(f"future_timestamp:{field}")
        return None
    return parsed.isoformat()


def _stage_status(value: Any) -> str:
    text = _text(value)
    if text in {"passed", "approved", "success", "filled", "submitted", "planned"}:
        return "passed"
    if text in {"rejected", "failed", "cancelled", "canceled"}:
        return "rejected"
    if text in {"unavailable", "ambiguous", "conflict", "unknown", "pending"}:
        return "unavailable" if text != "pending" else "passed"
    if text in {"not_generated", "not_reached"}:
        return "not_generated"
    return "not_generated"


def _normalise_stage_map(row: Mapping[str, Any]) -> dict[str, str]:
    raw = row.get("stage_statuses")
    result: dict[str, str] = {}
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            stage = _STAGE_ALIASES.get(str(key), str(key))
            if stage in STAGE_ORDER:
                result[stage] = _stage_status(value)
    if not result and _text(row.get("stage")):
        stage = _STAGE_ALIASES.get(str(row.get("stage")), str(row.get("stage")))
        if stage in STAGE_ORDER:
            reason = str(row.get("reason") or row.get("reason_code") or "").lower()
            result[stage] = "unavailable" if "unavailable" in reason else "rejected"
    # Structured rejection records are allowed to provide a single transition;
    # the active path remains the authority for the other stages.
    if not result:
        if _action(row) == "exit":
            return {stage: "not_applicable" for stage in STAGE_ORDER}
        if row.get("identity_status") in {
            "identity_unavailable",
            "identity_ambiguous",
            "decision_identity_partial",
            "decision_identity_ambiguous",
            "cycle_mismatch",
        }:
            return {stage: "unavailable" if stage == "selection" else "not_generated" for stage in STAGE_ORDER}
        result["selection"] = "passed" if row.get("eligible_at_selection", row.get("eligible", True)) is not False else "rejected"
        if row.get("selected_for_llm") is False and row.get("recommended") is not True:
            result["selection"] = "rejected"
        for stage, field in (("gates", "gate_status"), ("capacity", "capacity_status"), ("sizing", "sizing_status"), ("risk", "risk_status")):
            if field in row:
                result[stage] = _stage_status(row.get(field))
        result.setdefault("gates", "passed")
        result.setdefault("capacity", "passed")
        result.setdefault("sizing", "passed")
        result.setdefault("risk", "passed" if row.get("risk_approved", row.get("planned", False)) else "not_generated")
        result["plans"] = "passed" if row.get("plan_id") or row.get("planned") is True else "not_generated"
        result["orders"] = "passed" if row.get("broker_order_id") or row.get("ordered") is True else "not_generated"
        status = str(row.get("order_status") or row.get("status") or "").lower()
        result["fills"] = "passed" if status in {"filled", "partial", "partially_filled"} else "not_generated"
    for stage in STAGE_ORDER:
        result.setdefault(stage, "not_generated")
    return result


def _primary_reason(row: Mapping[str, Any], stages: Mapping[str, str]) -> str | None:
    explicit = _text(row.get("primary_drop_reason"))
    if explicit in DROP_REASONS:
        return explicit
    if _action(row) == "exit":
        return "not_applicable_exit"
    for stage in STAGE_ORDER:
        status = stages.get(stage)
        if status == "rejected":
            return {
                "selection": "not_selected",
                "gates": "gate_rejected",
                "capacity": "capacity_exhausted",
                "sizing": "sizing_zero",
                "risk": "risk_rejected",
                "orders": "execution_rejected_cancelled",
            }.get(stage, "not_generated")
        if status == "unavailable":
            return {
                "selection": "identity_unavailable",
                "gates": "gate_unavailable",
                "capacity": "capacity_exhausted",
                "sizing": "sizing_unavailable",
                "risk": "risk_unavailable",
                "orders": "execution_unavailable",
            }.get(stage, "not_generated")
        if status == "not_generated":
            return "not_generated"
    return None


def _compact_detail(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "identity_key": row.get("identity_key"),
        "signal_identity_key": row.get("signal_identity_key")
        if row.get("decision_identity_quality") != "verified"
        else None,
        "identity_status": row.get("identity_status"),
        "action": row.get("action"),
        "candidate_id": row.get("candidate_id"),
        "recommendation_id": row.get("recommendation_id"),
        "plan_id": row.get("plan_id"),
        "broker_order_id": row.get("broker_order_id"),
        "primary_drop_reason": row.get("primary_drop_reason"),
        "stage_statuses": row.get("stage_statuses"),
        "requested_notional": row.get("requested_notional"),
        "risk_approved_notional": row.get("risk_approved_notional"),
        "planned_notional": row.get("planned_notional"),
        "submitted_notional": row.get("submitted_notional"),
        "filled_notional": row.get("filled_notional"),
        "order_status": row.get("order_status"),
    }


def _normalise_row(value: Any, *, cycle_id: str, captured_at: datetime, warnings: list[str]) -> dict[str, Any]:
    raw = _mapping(value)
    lineage = _mapping(raw.get("decision_lineage"))
    info = _identity_info(raw, cycle_id)
    identity_status = "verified" if info["decision_quality"] == "verified" else (
        "cycle_mismatch" if info["cycle_mismatch"] else "decision_identity_partial" if info["signal_key"] else "identity_unavailable"
    )
    if raw.get("identity_ambiguous") is True:
        identity_status = "identity_ambiguous"
    identity_reasons = [info["reason"]] if info["reason"] else []
    if identity_status == "identity_ambiguous":
        identity_reasons.append("identity_ambiguous")
    row = {
        "cycle_id": info["external_cycle"] or cycle_id,
        "source_cycle_id": info["embedded_cycle"],
        "cycle_identity_status": "mismatch" if info["cycle_mismatch"] else "verified",
        "action": info["action"],
        "signal_capture_id": info["signal_capture_id"],
        "signal_id": info["signal_id"],
        "candidate_id": _text(raw.get("candidate_id") or lineage.get("candidate_id")),
        "recommendation_id": info["recommendation_id"],
        "plan_id": _text(raw.get("plan_id")),
        "broker_order_id": _text(raw.get("broker_order_id")),
        "client_order_id": _text(raw.get("client_order_id")),
        "order_status": _text(raw.get("order_status") or raw.get("status")),
        "currency": _text(raw.get("currency")) or "USD",
        "strategy": _text(raw.get("strategy") or raw.get("strategy_name")),
        "setup": _text(raw.get("setup") or raw.get("setup_name")),
        "data_quality": _safe(raw.get("data_quality")),
        "freshness": _safe(raw.get("freshness")),
        "as_of": _timestamp(raw.get("as_of"), captured_at, warnings, "as_of"),
        "cycle_started_at": _timestamp(raw.get("cycle_started_at"), captured_at, warnings, "cycle_started_at"),
        "decision_at": _timestamp(raw.get("decision_at"), captured_at, warnings, "decision_at"),
        "plan_at": _timestamp(raw.get("plan_at"), captured_at, warnings, "plan_at"),
        "submitted_at": _timestamp(raw.get("submitted_at"), captured_at, warnings, "submitted_at"),
        "filled_at": _timestamp(raw.get("filled_at"), captured_at, warnings, "filled_at"),
        "identity_status": identity_status,
        "signal_identity_quality": "ambiguous" if raw.get("signal_identity_ambiguous") is True else info["signal_quality"],
        "decision_identity_quality": info["decision_quality"] if identity_status != "identity_ambiguous" else "ambiguous",
        "identity_reason_codes": sorted(set(identity_reasons)),
        "signal_identity_key": _identity_text(info["signal_key"]),
        "identity_key": _identity_text(info["decision_key"]),
        "stage_statuses": _normalise_stage_map({**raw, "identity_status": identity_status}),
        "primary_drop_reason": None,
        "secondary_reasons": sorted({_text(item) for item in (raw.get("secondary_reasons") or []) if _text(item)}),
        "requested_notional": _finite(raw.get("requested_notional", raw.get("notional")), allow_negative=False),
        "gate_eligible_notional": _finite(raw.get("gate_eligible_notional"), allow_negative=False),
        "capacity_eligible_notional": _finite(raw.get("capacity_eligible_notional"), allow_negative=False),
        "sizing_approved_notional": _finite(raw.get("sizing_approved_notional"), allow_negative=False),
        "risk_approved_notional": _finite(raw.get("risk_approved_notional"), allow_negative=False),
        "planned_notional": _finite(raw.get("planned_notional", raw.get("plan_notional")), allow_negative=False),
        "submitted_notional": _finite(raw.get("submitted_notional"), allow_negative=False),
        "filled_notional": _finite(raw.get("filled_notional"), allow_negative=False),
        "size_multiplier": _finite(raw.get("size_multiplier"), allow_negative=False),
        "per_order_cap": _finite(raw.get("per_order_cap"), allow_negative=False),
        "micro_experiment": raw.get("micro_experiment") if isinstance(raw.get("micro_experiment"), bool) else None,
        "notional_authority": _text(raw.get("notional_authority")),
    }
    row["primary_drop_reason"] = _primary_reason(raw, row["stage_statuses"])
    return row


def _key(value: Any, cycle_id: str) -> tuple[str, str, str, str] | None:
    return _identity(value, cycle_id)


def _merge_exact(
    rows: list[dict[str, Any]],
    exact_index: dict[tuple[str, str, str, str], int],
    values: Sequence[Any] | None,
    *,
    cycle_id: str,
    warnings: list[str],
    label: str,
    attachment_counts: dict[str, int],
) -> None:
    for value in values or []:
        info = _identity_info(value, cycle_id)
        key = info["decision_key"]
        if key is None:
            warnings.append(f"{label}_{info['reason'] or 'identity_unavailable'}")
            attachment_counts[f"{label}_attachment_unavailable"] += 1
            continue
        target_index = exact_index.get(key)
        if target_index is None:
            warnings.append(f"{label}_without_candidate")
            attachment_counts[f"{label}_attachment_unavailable"] += 1
            continue
        target = rows[target_index]
        if target.get("identity_status") != "verified":
            warnings.append(f"{label}_identity_conflict")
            attachment_counts[f"{label}_attachment_ambiguous"] += 1
            continue
        raw = _mapping(value)
        raw_payload = _mapping(raw.get("payload"))
        for field in ("recommendation_id", "plan_id", "broker_order_id", "client_order_id", "order_status"):
            if raw.get(field) is not None:
                target[field] = _text(raw.get(field))
        target["recommendation_id"] = target.get("recommendation_id") or info["recommendation_id"]
        explicit_stages = raw.get("stage_statuses")
        if isinstance(explicit_stages, Mapping):
            target["stage_statuses"].update(_normalise_stage_map({"stage_statuses": explicit_stages}))
        elif _text(raw.get("stage")):
            stage = _STAGE_ALIASES.get(str(raw.get("stage")), str(raw.get("stage")))
            if stage in STAGE_ORDER:
                reason = str(raw.get("reason") or raw.get("reason_code") or "").lower()
                target["stage_statuses"][stage] = "unavailable" if "unavailable" in reason else "rejected"
        elif label == "plan":
            target["stage_statuses"]["plans"] = "passed"
            for stage in ("selection", "gates", "capacity", "sizing", "risk"):
                if target["stage_statuses"].get(stage) == "not_generated":
                    target["stage_statuses"][stage] = "passed"
        elif label == "submitted":
            target["stage_statuses"]["orders"] = "passed"
            status = str(raw.get("order_status") or raw.get("status") or "").lower()
            target["stage_statuses"]["fills"] = "passed" if status in {"filled", "partial", "partially_filled"} else "unavailable"
        for field in ("requested_notional", "planned_notional", "submitted_notional", "filled_notional", "risk_approved_notional", "sizing_approved_notional"):
            source_value = raw.get(field)
            if source_value is None and field in {"planned_notional", "submitted_notional"}:
                source_value = raw_payload.get("notional")
            if field in raw or source_value is not None:
                parsed = _finite(source_value, allow_negative=False)
                if parsed is not None:
                    target[field] = parsed
        if raw.get("source") is not None:
            target["decision_source"] = _text(raw.get("source"))
        if label in {"plan", "rejection"}:
            attachment_counts["plan_attachment_verified"] += 1 if target.get("plan_id") else 0
        if label == "submitted":
            attachment_counts["order_attachment_verified"] += 1 if target.get("broker_order_id") or target.get("client_order_id") else 0
        target["primary_drop_reason"] = _primary_reason(target, target["stage_statuses"])


def _stage_counts(
    rows: Sequence[Mapping[str, Any]],
    *,
    identity_unavailable_count: int = 0,
    identity_ambiguous_count: int = 0,
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for stage in STAGE_ORDER:
        statuses = [(_mapping(row).get("stage_statuses") or {}).get(stage, "not_generated") for row in rows]
        result[stage] = {
            "population_total": len(rows),
            "reached_count": sum(status != "not_generated" for status in statuses),
            "evaluated_count": sum(status != "not_generated" for status in statuses),
            "passed_count": sum(status == "passed" for status in statuses),
            "approved_count": sum(status == "passed" for status in statuses),
            "rejected_count": sum(status == "rejected" for status in statuses),
            "unavailable_count": sum(status in {"unavailable", "ambiguous"} for status in statuses),
            "not_generated_count": sum(status == "not_generated" for status in statuses),
            "identity_unavailable_count": identity_unavailable_count if stage == "selection" else 0,
            "identity_ambiguous_count": identity_ambiguous_count if stage == "selection" else 0,
        }
    return result


def _waterfall(rows: Sequence[Mapping[str, Any]], field: str) -> dict[str, Any]:
    values = [_mapping(row).get(field) for row in rows]
    numeric = [value for value in values if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))]
    currencies = sorted({_text(_mapping(row).get("currency")) for row in rows if _mapping(row).get(field) is not None})
    return {
        "value": round(sum(float(value) for value in numeric), 8) if numeric else None,
        "available_count": len(numeric),
        "unavailable_count": len(rows) - len(numeric),
        "denominator_count": len(rows),
        "currency": currencies[0] if len(currencies) == 1 else None,
        "status": "complete" if numeric and len(numeric) == len(rows) else "partial" if numeric else "unavailable",
    }


def _invariants(
    rows: Sequence[Mapping[str, Any]],
    stages: Mapping[str, Mapping[str, int]],
    *,
    excluded_identity_count: int = 0,
    observed_count: int | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    for left, right in zip(STAGE_ORDER, STAGE_ORDER[1:], strict=False):
        if stages[right]["reached_count"] > stages[left]["passed_count"]:
            errors.append(f"non_monotonic:{left}->{right}")
    success = 0
    dropped = 0
    for row in rows:
        statuses = _mapping(row).get("stage_statuses") or {}
        is_success = all(statuses.get(stage) == "passed" for stage in STAGE_ORDER)
        reason = _mapping(row).get("primary_drop_reason")
        if is_success and reason is not None:
            errors.append("primary_reason_on_success")
        elif not is_success and reason is None:
            errors.append("missing_primary_drop_reason")
        elif is_success:
            success += 1
        else:
            dropped += 1
    if success + dropped != len(rows):
        errors.append("terminal_partition_not_closed")
    if stages["plans"]["reached_count"] > stages["risk"]["passed_count"]:
        errors.append("plans_not_subset_risk_approved")
    if stages["orders"]["reached_count"] > stages["plans"]["passed_count"]:
        errors.append("orders_not_subset_plans")
    if stages["fills"]["reached_count"] > stages["orders"]["passed_count"]:
        errors.append("fills_not_subset_orders")
    if observed_count is not None and success + dropped + excluded_identity_count != observed_count:
        errors.append("identity_exclusion_partition_not_closed")
    return {
        "valid": not errors,
        "errors": sorted(set(errors)),
        "terminal_count": success + dropped,
        "successful_count": success,
        "dropped_count": dropped,
        "denominator_count": len(rows),
        "excluded_identity_count": excluded_identity_count,
        "observed_count": observed_count,
    }


def build_capital_deployment_funnel_shadow(
    cycle_id: str,
    candidates: Sequence[Any] | None,
    *,
    recommendations: Sequence[Any] | None = None,
    gated_recommendations: Sequence[Any] | None = None,
    plans: Sequence[Any] | None = None,
    rejected_order_plans: Sequence[Mapping[str, Any]] | None = None,
    submitted: Sequence[Mapping[str, Any]] | None = None,
    account: Mapping[str, Any] | None = None,
    captured_at: datetime | None = None,
    detail_limit: int = DEFAULT_DETAIL_LIMIT,
) -> dict[str, Any]:
    """Build one bounded event from active-path observations only."""

    if not _text(cycle_id):
        raise ValueError("cycle_id_required")
    capture = captured_at or datetime.now(timezone.utc)
    if capture.tzinfo is None:
        capture = capture.replace(tzinfo=timezone.utc)
    capture = capture.astimezone(timezone.utc)
    warnings: list[str] = []
    rows: list[dict[str, Any]] = []
    exact_index: dict[tuple[str, str, str, str], int] = {}
    missing_recommendation_groups: dict[tuple[str, str, str], list[int]] = {}
    identity_conflicts: list[dict[str, Any]] = []
    attachment_counts = {
        "plan_attachment_verified": 0,
        "plan_attachment_unavailable": 0,
        "plan_attachment_ambiguous": 0,
        "order_attachment_verified": 0,
        "order_attachment_unavailable": 0,
        "order_attachment_ambiguous": 0,
    }
    raw_count = None if candidates is None else len(candidates)
    for value in candidates or []:
        info = _identity_info(value, cycle_id)
        row = _normalise_row(value, cycle_id=cycle_id, captured_at=capture, warnings=warnings)
        key = info["decision_key"]
        if key is None:
            rows.append(row)
            row_index = len(rows) - 1
            if info["signal_key"] and not info["recommendation_id"] and not info["cycle_mismatch"]:
                missing_recommendation_groups.setdefault(info["signal_key"], []).append(row_index)
            else:
                warnings.append(f"candidate_{info['reason'] or 'identity_unavailable'}")
            continue
        existing_index = exact_index.get(key)
        if existing_index is None:
            exact_index[key] = len(rows)
            rows.append(row)
            continue
        existing = rows[existing_index]
        if content_hash(existing) == content_hash(row):
            # Exact retries are idempotent at the row projection boundary.
            continue
        existing_hash = content_hash(existing)
        conflicting_hash = content_hash(row)
        for conflicted in (existing, row):
            conflicted["identity_status"] = "identity_ambiguous"
            conflicted["decision_identity_quality"] = "ambiguous"
            conflicted["identity_reason_codes"] = sorted(
                set(conflicted.get("identity_reason_codes") or []) | {"identity_conflict"}
            )
            conflicted["stage_statuses"] = {
                stage: "unavailable" if stage == "selection" else "not_generated" for stage in STAGE_ORDER
            }
            conflicted["primary_drop_reason"] = "identity_ambiguous"
        rows.append(row)
        exact_index.pop(key, None)
        identity_conflicts.append(
            {
                "decision_identity": _identity_text(key),
                "original_content_hash": existing_hash,
                "conflicting_content_hash": conflicting_hash,
            }
        )
        warnings.append("candidate_identity_conflict")

    for _signal_key, indexes in missing_recommendation_groups.items():
        if len(indexes) == 1:
            row = rows[indexes[0]]
            row["identity_status"] = "decision_identity_partial"
            row["decision_identity_quality"] = "partial"
            row["identity_reason_codes"] = sorted(
                set(row.get("identity_reason_codes") or []) | {"recommendation_id_unavailable"}
            )
        else:
            for index in indexes:
                row = rows[index]
                row["identity_status"] = "identity_ambiguous"
                row["decision_identity_quality"] = "ambiguous"
                row["identity_reason_codes"] = sorted(
                    set(row.get("identity_reason_codes") or []) | {"recommendation_id_collision"}
                )
                row["stage_statuses"] = {
                    stage: "unavailable" if stage == "selection" else "not_generated" for stage in STAGE_ORDER
                }
                row["primary_drop_reason"] = "identity_ambiguous"
            warnings.append("candidate_recommendation_id_collision")

    _merge_exact(
        rows,
        exact_index,
        recommendations,
        cycle_id=cycle_id,
        warnings=warnings,
        label="recommendation",
        attachment_counts=attachment_counts,
    )
    _merge_exact(
        rows,
        exact_index,
        gated_recommendations,
        cycle_id=cycle_id,
        warnings=warnings,
        label="gate",
        attachment_counts=attachment_counts,
    )
    _merge_exact(
        rows,
        exact_index,
        plans,
        cycle_id=cycle_id,
        warnings=warnings,
        label="plan",
        attachment_counts=attachment_counts,
    )
    _merge_exact(
        rows,
        exact_index,
        rejected_order_plans,
        cycle_id=cycle_id,
        warnings=warnings,
        label="rejection",
        attachment_counts=attachment_counts,
    )
    _merge_exact(
        rows,
        exact_index,
        submitted,
        cycle_id=cycle_id,
        warnings=warnings,
        label="submitted",
        attachment_counts=attachment_counts,
    )
    attachment_counts["plan_attachment_verified"] = sum(
        row.get("identity_status") == "verified" and row.get("plan_id") is not None for row in rows
    )
    attachment_counts["order_attachment_verified"] = sum(
        row.get("identity_status") == "verified" and (row.get("broker_order_id") or row.get("client_order_id")) is not None
        for row in rows
    )
    ordered_rows = sorted(rows, key=lambda row: (str(row.get("identity_key") or ""), str(row.get("candidate_id") or "")))
    stages = _stage_counts(ordered_rows)
    buy_rows = [row for row in ordered_rows if row.get("action") == "buy"]
    exact_buy_rows = [
        row
        for row in buy_rows
        if row.get("identity_status") == "verified" and row.get("decision_identity_quality") == "verified"
    ]
    excluded_identity_count = len(buy_rows) - len(exact_buy_rows)
    identity_unavailable_count = sum(
        row.get("signal_identity_quality") == "unavailable" or row.get("identity_status") == "cycle_mismatch"
        for row in buy_rows
    )
    identity_ambiguous_count = sum(row.get("identity_status") == "identity_ambiguous" for row in buy_rows)
    stages = _stage_counts(
        exact_buy_rows,
        identity_unavailable_count=identity_unavailable_count,
        identity_ambiguous_count=identity_ambiguous_count,
    )
    signal_identity_verified = sum(row.get("signal_identity_quality") == "verified" for row in ordered_rows)
    signal_identity_unavailable = sum(row.get("signal_identity_quality") == "unavailable" for row in ordered_rows)
    signal_identity_ambiguous = sum(row.get("signal_identity_quality") == "ambiguous" for row in ordered_rows)
    decision_identity_verified = sum(row.get("decision_identity_quality") == "verified" for row in ordered_rows)
    decision_identity_partial = sum(row.get("decision_identity_quality") == "partial" for row in ordered_rows)
    decision_identity_unavailable = sum(row.get("decision_identity_quality") == "unavailable" for row in ordered_rows)
    decision_identity_ambiguous = sum(row.get("decision_identity_quality") == "ambiguous" for row in ordered_rows)
    denominators = {
        "raw_count": raw_count,
        "canonical_count": decision_identity_verified if candidates is not None else None,
        "identity_unavailable": identity_unavailable_count if candidates is not None else None,
        "identity_ambiguous": identity_ambiguous_count if candidates is not None else None,
        "buy_population_total": len(buy_rows) if candidates is not None else None,
        "buy_population_identity_verified": len(exact_buy_rows) if candidates is not None else None,
        "candidates_observed": raw_count,
        "technically_eligible": sum(row.get("stage_statuses", {}).get("selection") == "passed" for row in exact_buy_rows) if candidates is not None else None,
        "recommendations_generated": len([row for row in exact_buy_rows if row.get("recommendation_id")]) if candidates is not None else None,
        "plans_generated": sum(row.get("stage_statuses", {}).get("plans") == "passed" for row in exact_buy_rows) if candidates is not None else None,
        "orders_submitted": sum(row.get("stage_statuses", {}).get("orders") == "passed" for row in exact_buy_rows) if candidates is not None else None,
        "orders_filled": sum(row.get("stage_statuses", {}).get("fills") == "passed" for row in exact_buy_rows) if candidates is not None else None,
        "pending_orders": sum(str(row.get("order_status") or "").lower() == "pending" for row in exact_buy_rows) if candidates is not None else None,
        "conflict_count": len(identity_conflicts),
        "truncated_count": 0,
        "signal_identity_verified": signal_identity_verified if candidates is not None else None,
        "signal_identity_unavailable": signal_identity_unavailable if candidates is not None else None,
        "signal_identity_ambiguous": signal_identity_ambiguous if candidates is not None else None,
        "decision_identity_verified": decision_identity_verified if candidates is not None else None,
        "decision_identity_partial": decision_identity_partial if candidates is not None else None,
        "decision_identity_unavailable": decision_identity_unavailable if candidates is not None else None,
        "decision_identity_ambiguous": decision_identity_ambiguous if candidates is not None else None,
        "recommendation_id_available": sum(row.get("recommendation_id") is not None for row in ordered_rows) if candidates is not None else None,
        "recommendation_id_unavailable": sum(row.get("recommendation_id") is None for row in ordered_rows) if candidates is not None else None,
        "cycle_mismatch_count": sum(row.get("cycle_identity_status") == "mismatch" for row in ordered_rows) if candidates is not None else None,
        "plan_attachment_verified": attachment_counts["plan_attachment_verified"] if candidates is not None else None,
        "plan_attachment_unavailable": attachment_counts["plan_attachment_unavailable"] if candidates is not None else None,
        "plan_attachment_ambiguous": attachment_counts["plan_attachment_ambiguous"] if candidates is not None else None,
        "order_attachment_verified": attachment_counts["order_attachment_verified"] if candidates is not None else None,
        "order_attachment_unavailable": attachment_counts["order_attachment_unavailable"] if candidates is not None else None,
        "order_attachment_ambiguous": attachment_counts["order_attachment_ambiguous"] if candidates is not None else None,
    }
    notional = {
        "requested": _waterfall(exact_buy_rows, "requested_notional"),
        "gate_eligible": _waterfall([row for row in exact_buy_rows if row.get("stage_statuses", {}).get("gates") == "passed"], "gate_eligible_notional"),
        "capacity_eligible": _waterfall([row for row in exact_buy_rows if row.get("stage_statuses", {}).get("capacity") == "passed"], "capacity_eligible_notional"),
        "sizing_approved": _waterfall([row for row in exact_buy_rows if row.get("stage_statuses", {}).get("sizing") == "passed"], "sizing_approved_notional"),
        "risk_approved": _waterfall([row for row in exact_buy_rows if row.get("stage_statuses", {}).get("risk") == "passed"], "risk_approved_notional"),
        "planned": _waterfall([row for row in exact_buy_rows if row.get("stage_statuses", {}).get("plans") == "passed"], "planned_notional"),
        "submitted": _waterfall([row for row in exact_buy_rows if row.get("stage_statuses", {}).get("orders") == "passed"], "submitted_notional"),
        "filled": _waterfall([row for row in exact_buy_rows if row.get("stage_statuses", {}).get("fills") == "passed"], "filled_notional"),
    }
    limit = max(0, int(detail_limit))
    details = [_compact_detail(row) for row in ordered_rows[:limit]]
    omitted = max(0, len(ordered_rows) - len(details))
    invariants = _invariants(
        exact_buy_rows,
        stages,
        excluded_identity_count=excluded_identity_count,
        observed_count=len(buy_rows),
    )
    account_projection = {}
    for field in ("equity", "cash", "buying_power", "gross_exposure", "net_exposure", "target_account_exposure", "target_min_exposure", "target_max_exposure"):
        account_projection[field] = _finite((account or {}).get(field), allow_negative=True) if isinstance(account, Mapping) else None
    status = "collecting" if candidates is None else "verified"
    if warnings or omitted or excluded_identity_count or not invariants["valid"]:
        status = "invalid" if not invariants["valid"] else "partial"
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "revision": 1,
        "event_id": f"{EVENT_ID_PREFIX}{cycle_id}",
        "event_type": EVENT_TYPE,
        "cycle_id": cycle_id,
        "status": status,
        "policy_mode": "shadow_only",
        "captured_at": capture.isoformat(),
        "denominators": denominators,
        "stages": stages,
        "notional_waterfall": notional,
        "account": account_projection,
        "target_exposure_status": "available" if account_projection["target_account_exposure"] is not None else "unavailable",
        "primary_drop_reason_counts": {
            reason: sum(row.get("primary_drop_reason") == reason for row in buy_rows)
            for reason in sorted(DROP_REASONS)
            if any(row.get("primary_drop_reason") == reason for row in buy_rows)
        },
        "detail_total": len(ordered_rows),
        "detail_persisted": len(details),
        "detail_omitted": omitted,
        "truncated": bool(omitted),
        "details": details,
        "invariants": invariants,
        "identity_conflicts": identity_conflicts,
        "attachment_coverage": attachment_counts,
        "warnings": sorted(set(warnings)),
        "conflicts": len(identity_conflicts),
    }
    payload["content_hash"] = content_hash(payload)
    return _safe(payload)


class CapitalDeploymentFunnelObserver:
    """Small fail-open observer used by the active cycle boundary."""

    def __init__(self, cycle_id: str) -> None:
        self.cycle_id = cycle_id
        self._observations: list[dict[str, Any]] = []
        self.warnings: list[str] = []

    def observe(self, value: Any) -> None:
        try:
            row = _mapping(value)
            if row:
                self._observations.append(copy.deepcopy(row))
        except Exception as exc:  # noqa: BLE001 - shadow must never block.
            self.warnings.append(f"observe_failed:{type(exc).__name__}")

    def finalize(self, candidates: Sequence[Any] | None, **kwargs: Any) -> dict[str, Any]:
        try:
            observed = list(candidates or []) + list(self._observations)
            return build_capital_deployment_funnel_shadow(self.cycle_id, observed, **kwargs)
        except Exception as exc:  # noqa: BLE001 - caller can persist unavailable.
            self.warnings.append(f"finalize_failed:{type(exc).__name__}")
            return unavailable_capital_deployment_funnel(self.cycle_id, reason="finalize_failed")


def unavailable_capital_deployment_funnel(cycle_id: str, *, reason: str = "shadow_inputs_unavailable") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": 1,
        "event_id": f"{EVENT_ID_PREFIX}{cycle_id}",
        "event_type": EVENT_TYPE,
        "cycle_id": cycle_id,
        "status": "collecting",
        "policy_mode": "shadow_only",
        "denominators": None,
        "stages": None,
        "notional_waterfall": None,
        "account": None,
        "target_exposure_status": "unavailable",
        "detail_total": None,
        "detail_persisted": None,
        "detail_omitted": None,
        "truncated": None,
        "details": [],
        "invariants": None,
        "warnings": [reason],
        "conflicts": 0,
    }


def persist_capital_deployment_funnel_shadow(store: Store, payload: Mapping[str, Any]) -> dict[str, Any]:
    event_id = _text(payload.get("event_id"))
    if not event_id:
        raise ValueError("capital_funnel_event_id_required")
    return store.record_capital_deployment_funnel_shadow(dict(payload), event_id=event_id)


def read_capital_deployment_funnel_shadow(store: Store, cycle_id: str | None = None) -> dict[str, Any]:
    event = store.capital_deployment_funnel_shadow_event(cycle_id) if cycle_id else store.latest_capital_deployment_funnel_shadow_event()
    if event is None:
        return unavailable_capital_deployment_funnel(cycle_id or "") | {"warnings": ["no_canonical_capital_funnel"]}
    payload = dict(event.get("payload") or {})
    expected = f"{EVENT_ID_PREFIX}{payload.get('cycle_id')}"
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("event_id") != expected:
        return unavailable_capital_deployment_funnel(cycle_id or "") | {"status": "unavailable", "warnings": ["invalid_canonical_capital_funnel"]}
    if content_hash(payload) != payload.get("content_hash"):
        return unavailable_capital_deployment_funnel(cycle_id or "") | {"status": "unavailable", "warnings": ["content_hash_mismatch"]}
    return payload


def capital_deployment_funnel_digest(store: Store, cycle_id: str | None = None) -> dict[str, Any]:
    try:
        payload = read_capital_deployment_funnel_shadow(store, cycle_id)
    except Exception as exc:  # noqa: BLE001 - read-only consumer is fail-open.
        return unavailable_capital_deployment_funnel(cycle_id or "", reason=f"read_failed:{type(exc).__name__}") | {
            "status": "unavailable"
        }
    event_cycle = payload.get("cycle_id")
    conflicts = store.capital_deployment_funnel_shadow_conflicts(event_cycle) if event_cycle else []
    payload["conflict_events"] = len(conflicts)
    if conflicts and payload.get("status") == "verified":
        payload["status"] = "partial"
    return payload
