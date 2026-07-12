"""Append-only, prospective execution-quality snapshots.

This module observes plan, submit and reconciliation payloads already produced
by the normal flow.  It never sends an order or queries a broker.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timezone
from statistics import mean, median
from typing import Any

SCHEMA_VERSION = "p-l33b.execution-quality.v1"
LINEAGE_STATUSES = frozenset({"verified", "partial", "broken", "legacy"})
STATUSES = frozenset({"planned", "submitted", "accepted", "partially_filled", "filled", "rejected", "cancelled", "expired", "error", "unavailable"})
TERMINAL = frozenset({"filled", "rejected", "cancelled", "expired", "error"})
PROHIBITED = frozenset({"return_1d", "return_3d", "return_5d", "return_10d", "matured_horizons", "mfe", "mae", "mfe_10d", "mae_10d", "first_hit", "verdict", "realized_pnl", "unrealized_pnl", "alpha", "benchmark", "trade_memory"})


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()[:32]


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _timestamp(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _contains_prohibited(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in PROHIBITED:
                return str(key)
            found = _contains_prohibited(item)
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for item in value:
            found = _contains_prohibited(item)
            if found:
                return found
    return None


def _lineage_status(*, signal_id: str | None, candidate_id: str | None, lineage_id: str | None, recommendation_id: str | None, plan_id: str | None, broker_id: str | None = None) -> str:
    if signal_id and candidate_id and lineage_id and recommendation_id and plan_id and broker_id:
        return "verified"
    if any((signal_id, candidate_id, lineage_id, recommendation_id, plan_id, broker_id)):
        return "partial"
    return "legacy"


def _stage_hash(stage: Mapping[str, Any]) -> str:
    return _hash({key: value for key, value in stage.items() if key != "content_hash"})


def _set_bps(snapshot: dict[str, Any]) -> None:
    prices = snapshot["prices"]
    side = str(snapshot.get("side") or "").lower()
    metrics = snapshot["metrics"]
    for key in ("signal_to_plan_bps", "plan_to_fill_bps", "signal_to_fill_bps"):
        metrics[key] = None
    if side != "buy":
        return
    signal, plan, fill = (_number(prices.get(key)) for key in ("signal", "plan", "filled_average"))
    if signal and plan:
        metrics["signal_to_plan_bps"] = (plan / signal - 1.0) * 10_000.0
    if plan and fill:
        metrics["plan_to_fill_bps"] = (fill / plan - 1.0) * 10_000.0
    if signal and fill:
        metrics["signal_to_fill_bps"] = (fill / signal - 1.0) * 10_000.0


def _set_latencies(snapshot: dict[str, Any]) -> None:
    stamps = snapshot["timestamps"]
    metrics = snapshot["metrics"]
    pairs = {
        "signal_to_plan_seconds": ("signal_at", "plan_created_at"),
        "plan_to_submit_seconds": ("plan_created_at", "submitted_at"),
        "submit_to_accept_seconds": ("submitted_at", "accepted_at"),
        "submit_to_first_fill_seconds": ("submitted_at", "first_fill_at"),
        "submit_to_complete_seconds": ("submitted_at", "completed_at"),
    }
    for metric, (start, end) in pairs.items():
        metrics[metric] = None
        left, right = _timestamp(stamps.get(start)), _timestamp(stamps.get(end))
        if not left or not right:
            continue
        seconds = (datetime.fromisoformat(right) - datetime.fromisoformat(left)).total_seconds()
        if seconds < 0:
            _warning(snapshot, f"timestamp_inverted:{start}_to_{end}")
            continue
        metrics[metric] = seconds
        if seconds > 300 and metric in {"plan_to_submit_seconds", "submit_to_first_fill_seconds", "submit_to_complete_seconds"}:
            _warning(snapshot, f"latency_outlier:{metric}")


def _warning(snapshot: dict[str, Any], value: str) -> None:
    warnings = snapshot.setdefault("data_quality_warnings", [])
    if value not in warnings:
        warnings.append(value)


def _finalize(snapshot: dict[str, Any]) -> dict[str, Any]:
    _set_bps(snapshot)
    _set_latencies(snapshot)
    fill = _number(snapshot["prices"].get("filled_average"))
    for key, value in snapshot["prices"].items():
        if value is not None and _number(value) is None:
            _warning(snapshot, f"non_finite_price:{key}")
        if _number(value) == 0:
            _warning(snapshot, f"zero_price:{key}")
    submitted, filled = _number(snapshot["quantities"].get("submitted")), _number(snapshot["quantities"].get("filled"))
    if submitted is not None and filled is not None:
        snapshot["quantities"]["remaining"] = max(0.0, submitted - filled)
        if filled > submitted:
            _warning(snapshot, "filled_qty_gt_submitted")
        elif filled > 0 and filled < submitted:
            snapshot["status"] = "partially_filled" if snapshot["status"] not in TERMINAL else snapshot["status"]
    elif filled is not None:
        _warning(snapshot, "partial_fill_unavailable_submitted_qty_missing")
    if snapshot.get("side") == "buy" and _number(snapshot["metrics"].get("plan_to_fill_bps")) is not None and abs(float(snapshot["metrics"]["plan_to_fill_bps"])) > 200:
        _warning(snapshot, "slippage_outlier:plan_to_fill_bps")
    if fill is None and snapshot.get("status") in {"filled", "partially_filled"}:
        _warning(snapshot, "filled_price_unavailable")
    bad = _contains_prohibited(snapshot)
    if bad:
        raise ValueError(f"execution_quality_prohibited_field:{bad}")
    snapshot["content_hash"] = _hash({key: value for key, value in snapshot.items() if key not in {"captured_at", "content_hash"}})
    return snapshot


def build_planned_snapshot(*, plan_id: str, cycle_id: str, symbol: str, side: str, payload: Mapping[str, Any], planned_at: str, signal_price: Any = None, signal_at: str | None = None) -> dict[str, Any]:
    """Build the initial immutable snapshot from an existing OrderPlan payload."""
    plan = dict(payload)
    recommendation = dict(plan.get("recommendation") or {})
    lineage = dict(plan.get("decision_lineage") or recommendation.get("decision_lineage") or {})
    context = dict(recommendation.get("decision_context_snapshot") or {})
    signal_id = str(lineage.get("signal_id") or "").strip() or None
    candidate_id = str(lineage.get("candidate_id") or "").strip() or None
    lineage_id = str(lineage.get("lineage_id") or "").strip() or None
    recommendation_id = str(recommendation.get("recommendation_id") or plan.get("recommendation_id") or "").strip() or None
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_id": f"execq_{_hash({'plan_id': plan_id})}",
        "lineage_status": _lineage_status(signal_id=signal_id, candidate_id=candidate_id, lineage_id=lineage_id, recommendation_id=recommendation_id, plan_id=plan_id),
        "signal_id": signal_id,
        "candidate_id": candidate_id,
        "lineage_id": lineage_id,
        "cycle_id": cycle_id or lineage.get("cycle_id"),
        "recommendation_id": recommendation_id,
        "order_plan_id": plan_id,
        "broker_order_id": None,
        "client_order_id": None,
        "symbol": str(symbol or plan.get("symbol") or "").upper(),
        "side": str(side or plan.get("side") or "").lower(),
        "prices": {"signal": _number(signal_price), "recommendation": _number(recommendation.get("entry_price")), "plan": _number(plan.get("entry_price")), "submitted": None, "filled_average": None},
        "quantities": {"planned": _number(plan.get("qty")), "submitted": None, "filled": None, "remaining": None},
        "timestamps": {"signal_at": _timestamp(signal_at), "recommendation_at": _timestamp(context.get("captured_at")), "plan_created_at": _timestamp(planned_at), "submitted_at": None, "accepted_at": None, "first_fill_at": None, "completed_at": None, "cancelled_at": None},
        "status": "planned",
        "broker_status_raw": None,
        "reason_code": None,
        "broker_reason_raw": None,
        "metrics": {"signal_to_plan_bps": None, "plan_to_fill_bps": None, "signal_to_fill_bps": None, "signal_to_plan_seconds": None, "plan_to_submit_seconds": None, "submit_to_accept_seconds": None, "submit_to_first_fill_seconds": None, "submit_to_complete_seconds": None},
        "data_quality_warnings": [],
        "stage_history": [],
        "captured_at": _timestamp(planned_at) or datetime.now(timezone.utc).isoformat(),
        "content_hash": "",
    }
    return append_stage(snapshot, stage="planned", status="planned", observed_at=planned_at, source="order_plan")


def append_stage(snapshot: Mapping[str, Any], *, stage: str, status: str, observed_at: str, source: str, source_event_id: str | None = None, values: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Append one observed stage; compatible repeats are idempotent."""
    if status not in STATUSES:
        raise ValueError("execution_quality_status_invalid")
    result = copy.deepcopy(dict(snapshot))
    if result.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("execution_quality_schema_invalid")
    current = str(result.get("status") or "unavailable")
    if current in TERMINAL and status not in TERMINAL:
        _warning(result, "terminal_state_not_reverted")
        return _finalize(result)
    update = dict(values or {})
    stage_row = {"stage": stage, "status": status, "observed_at": _timestamp(observed_at), "source": source, "source_event_id": source_event_id}
    stage_row["content_hash"] = _stage_hash(stage_row)
    history = list(result.get("stage_history") or [])
    if any(
        item.get("content_hash") == stage_row["content_hash"]
        or (
            source_event_id
            and item.get("stage") == stage
            and item.get("status") == status
            and item.get("source") == source
            and item.get("source_event_id") == source_event_id
        )
        for item in history
    ):
        return _finalize(result)
    if any(item.get("stage") == stage and item.get("status") != status and item.get("source_event_id") == source_event_id and source_event_id for item in history):
        _warning(result, f"stage_conflict:{stage}")
        result["lineage_status"] = "broken"
        return _finalize(result)
    for group in ("prices", "quantities", "timestamps"):
        if isinstance(update.get(group), Mapping):
            for key, value in update[group].items():
                if key in result[group] and result[group].get(key) not in (None, value):
                    _warning(result, f"field_conflict:{group}.{key}")
                    result["lineage_status"] = "broken"
                elif key in result[group]:
                    result[group][key] = _number(value) if group != "timestamps" else _timestamp(value)
    for key in ("broker_order_id", "client_order_id"):
        if key in update and update[key] is not None:
            if result.get(key) not in (None, update[key]):
                _warning(result, f"field_conflict:{key}")
                result["lineage_status"] = "broken"
            else:
                result[key] = update[key]
    for key in ("broker_status_raw", "reason_code", "broker_reason_raw"):
        if key in update and update[key] is not None:
            result[key] = update[key]
    if result.get("broker_order_id"):
        result["lineage_status"] = _lineage_status(signal_id=result.get("signal_id"), candidate_id=result.get("candidate_id"), lineage_id=result.get("lineage_id"), recommendation_id=result.get("recommendation_id"), plan_id=result.get("order_plan_id"), broker_id=result.get("broker_order_id"))
    result["status"] = status if current not in TERMINAL else current
    history.append(stage_row)
    result["stage_history"] = history
    return _finalize(result)


def submitted_snapshot(snapshot: Mapping[str, Any], *, broker_order: Mapping[str, Any], observed_at: str) -> dict[str, Any]:
    raw = str(broker_order.get("status") or "")
    normalized = "cancelled" if raw.lower() in {"canceled", "cancelled"} else raw.lower()
    status = normalized if normalized in STATUSES else "submitted"
    return append_stage(snapshot, stage="submitted", status=status, observed_at=observed_at, source="submit_response", source_event_id=str(broker_order.get("id") or "") or None, values={"broker_order_id": broker_order.get("id"), "client_order_id": broker_order.get("client_order_id"), "broker_status_raw": raw, "prices": {"submitted": broker_order.get("limit_price")}, "quantities": {"submitted": broker_order.get("qty")}, "timestamps": {"submitted_at": broker_order.get("submitted_at")}})


def reconciled_snapshot(snapshot: Mapping[str, Any], *, broker_snapshot: Mapping[str, Any], observed_at: str, plan_status: str | None = None) -> dict[str, Any]:
    raw = str(broker_snapshot.get("status") or "")
    normalized = "cancelled" if raw.lower() in {"canceled", "cancelled"} else raw.lower()
    status = normalized if normalized in STATUSES else "unavailable"
    values = {"broker_order_id": broker_snapshot.get("id"), "client_order_id": broker_snapshot.get("client_order_id"), "broker_status_raw": raw, "prices": {"filled_average": broker_snapshot.get("filled_avg_price")}, "quantities": {"submitted": broker_snapshot.get("qty"), "filled": broker_snapshot.get("filled_qty")}, "timestamps": {"submitted_at": broker_snapshot.get("submitted_at"), "first_fill_at": broker_snapshot.get("filled_at"), "completed_at": broker_snapshot.get("filled_at") if normalized == "filled" else None, "cancelled_at": broker_snapshot.get("updated_at") if normalized in {"cancelled", "expired", "rejected"} else None}}
    result = append_stage(snapshot, stage="reconciled", status=status, observed_at=observed_at, source="broker_reconciliation", source_event_id=str(broker_snapshot.get("id") or "") or None, values=values)
    if plan_status and normalized in TERMINAL and str(plan_status).lower() != normalized:
        _warning(result, "plan_broker_status_mismatch")
        result = _finalize(result)
    if normalized in TERMINAL:
        result = append_stage(result, stage="terminal", status=status, observed_at=observed_at, source="broker_reconciliation", source_event_id=f"terminal:{broker_snapshot.get('id') or ''}")
    return result


def validate_snapshot(snapshot: Mapping[str, Any]) -> tuple[bool, str | None]:
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        return False, "schema_version"
    if snapshot.get("lineage_status") not in LINEAGE_STATUSES or snapshot.get("status") not in STATUSES:
        return False, "status"
    if not snapshot.get("snapshot_id") or not snapshot.get("order_plan_id"):
        return False, "identity"
    if _contains_prohibited(snapshot):
        return False, "prohibited"
    return True, None


def _quantile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * ratio) - 1))]


def build_execution_quality_report(snapshots: list[Mapping[str, Any]], *, start: str | None = None, end: str | None = None, status: str | None = None, lineage_status: str | None = None, legacy_orders: int = 0) -> dict[str, Any]:
    selected = [dict(item) for item in snapshots if (not start or str(item.get("captured_at", ""))[:10] >= start) and (not end or str(item.get("captured_at", ""))[:10] <= end) and (not status or item.get("status") == status) and (not lineage_status or item.get("lineage_status") == lineage_status)]
    buys = [item for item in selected if item.get("side") == "buy"]
    outliers = Counter(warning for item in selected for warning in item.get("data_quality_warnings", []))
    def coverage(predicate: Any, values: list[Mapping[str, Any]]) -> float | None:
        return sum(bool(predicate(item)) for item in values) / len(values) if values else None
    def summary(key: str) -> dict[str, float | None]:
        values = [float(item.get("metrics", {}).get(key)) for item in buys if _number(item.get("metrics", {}).get(key)) is not None]
        return {"mean": mean(values) if values else None, "median": median(values) if values else None, "p95": _quantile(values, 0.95)}
    def latency(key: str) -> dict[str, float | None]:
        values = [float(item.get("metrics", {}).get(key)) for item in selected if _number(item.get("metrics", {}).get(key)) is not None]
        return {"p50": median(values) if values else None, "p95": _quantile(values, 0.95)}
    filled = [item for item in selected if item.get("status") == "filled"]
    partial = [item for item in selected if item.get("status") == "partially_filled"]
    return {"schema_version": SCHEMA_VERSION, "status": "collecting" if not selected else "immature", "orders_total": len(selected) + legacy_orders, "snapshots": len(selected), "legacy": legacy_orders, "lineage": {key: sum(item.get("lineage_status") == key for item in selected) for key in LINEAGE_STATUSES}, "lineage_coverage": coverage(lambda item: item.get("lineage_status") == "verified", selected), "price_coverage": coverage(lambda item: _number(item.get("prices", {}).get("plan")) is not None and _number(item.get("prices", {}).get("filled_average")) is not None, buys), "timestamp_coverage": coverage(lambda item: _timestamp(item.get("timestamps", {}).get("submitted_at")) and _timestamp(item.get("timestamps", {}).get("completed_at")), selected), "fill_rate": len(filled) / len(selected) if selected else None, "partial_fill_rate": len(partial) / len(selected) if selected else None, "rejection_rate": sum(item.get("status") == "rejected" for item in selected) / len(selected) if selected else None, "cancellation_rate": sum(item.get("status") == "cancelled" for item in selected) / len(selected) if selected else None, "expiration_rate": sum(item.get("status") == "expired" for item in selected) / len(selected) if selected else None, "unfilled_rate": sum(item.get("status") in {"submitted", "accepted", "planned"} for item in selected) / len(selected) if selected else None, "plan_broker_status_mismatch": sum("plan_broker_status_mismatch" in item.get("data_quality_warnings", []) for item in selected), "bps": {key: summary(key) for key in ("signal_to_plan_bps", "plan_to_fill_bps", "signal_to_fill_bps")}, "latencies": {key: latency(key) for key in ("signal_to_plan_seconds", "plan_to_submit_seconds", "submit_to_accept_seconds", "submit_to_first_fill_seconds", "submit_to_complete_seconds")}, "outliers_by_reason": dict(sorted(outliers.items())), "unavailable_by_reason": {"no_prospective_snapshots": len(selected) == 0}}
