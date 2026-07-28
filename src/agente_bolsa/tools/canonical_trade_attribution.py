"""Shadow contract for exact BUY -> SELL attribution (P-L51B).

This module consumes an already-built canonical operation snapshot.  It does
not query a broker, reconcile orders, rebuild outcomes, infer lots by symbol or
date, or influence any trading decision.  Missing provenance is intentionally
published as unavailable/ambiguous.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from ..storage import Store


SCHEMA_VERSION = "p-l51b.canonical-trade-attribution.v1"
EVENT_TYPE = "canonical_trade_attribution"
EVENT_ID_PREFIX = "canonical_trade_attribution:"
FILLED_STATUSES = {"filled", "partially_filled"}
COST_FIELDS = (
    "commissions",
    "regulatory_fees",
    "spread_cost",
    "slippage_cost",
    "other_costs",
)


def _safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _stable_hash(payload: Mapping[str, Any]) -> str:
    body = copy.deepcopy(dict(payload))
    body.pop("captured_at", None)
    body.pop("content_hash", None)
    encoded = json.dumps(_safe(body), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _coverage(available: int, total: int) -> dict[str, Any]:
    return {"available": available, "total": total, "ratio": available / total if total else None}


def _add_reason(result: dict[str, Any], code: str) -> None:
    if code and code not in result["reason_codes"]:
        result["reason_codes"].append(code)


def _is_filled(operation: Mapping[str, Any]) -> bool:
    status = str(operation.get("status") or "").strip().lower()
    reconciliation = str(operation.get("reconciliation_status") or "").strip().lower()
    return status in FILLED_STATUSES or reconciliation == "reconciled_filled"


def _deduplicate(
    rows: list[Mapping[str, Any]],
    key: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    unique: dict[str, dict[str, Any]] = {}
    issues: list[str] = []
    for raw in rows:
        identifier = _text(raw.get(key))
        if not identifier:
            issues.append(f"missing_{key}")
            continue
        row = copy.deepcopy(dict(raw))
        previous = unique.get(identifier)
        if previous is None:
            unique[identifier] = row
        elif previous == row:
            issues.append(f"duplicate_{key}:{identifier}")
        else:
            issues.append(f"conflicting_{key}:{identifier}")
    return list(unique.values()), issues


def _coverage_value(costs: Mapping[str, Any] | None, name: str) -> float | None:
    return _number(costs.get(name)) if costs else None


def _complete_costs(costs: Mapping[str, Any] | None) -> bool:
    if not costs or _number(costs.get("gross_realized_pl")) is None:
        return False
    return all(_coverage_value(costs, name) is not None for name in COST_FIELDS)


def _net_costs(costs: Mapping[str, Any]) -> float | None:
    if not _complete_costs(costs):
        return None
    gross = float(costs["gross_realized_pl"])
    return gross - sum(float(costs[name]) for name in COST_FIELDS)


def _timestamp(value: Any) -> datetime | None:
    raw = _text(value)
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def calculate_slippage(
    *,
    side: str,
    benchmark_price: Any,
    fill_price: Any,
    benchmark_at: Any,
    filled_at: Any,
) -> dict[str, Any]:
    """Calculate adverse bps only from explicit benchmark data."""

    benchmark = _number(benchmark_price)
    fill = _number(fill_price)
    if benchmark is None or fill is None or benchmark <= 0:
        return {"slippage_bps": None, "status": "unavailable", "reason_code": "missing_benchmark_or_fill"}
    benchmark_time = _timestamp(benchmark_at)
    filled_time = _timestamp(filled_at)
    if benchmark_time is None or filled_time is None:
        return {"slippage_bps": None, "status": "unavailable", "reason_code": "invalid_timestamp"}
    if filled_time < benchmark_time:
        return {"slippage_bps": None, "status": "unavailable", "reason_code": "inverted_timestamp"}
    signed = (fill - benchmark) / benchmark
    if side.upper() == "BUY":
        adverse = signed
    elif side.upper() == "SELL":
        adverse = -signed
    else:
        return {"slippage_bps": None, "status": "unavailable", "reason_code": "invalid_side"}
    return {"slippage_bps": adverse * 10_000.0, "status": "available", "reason_code": None}


def calculate_risk_metrics(inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Return only metrics with exact, explicit inputs."""

    result = {
        "initial_risk": None,
        "realized_r_multiple": None,
        "holding_seconds": None,
        "holding_sessions": None,
        "mae": None,
        "mfe": None,
    }
    entry = _number(inputs.get("entry_price"))
    stop = _number(inputs.get("stop_price"))
    quantity = _number(inputs.get("entry_qty"))
    if entry is not None and stop is not None and quantity is not None and quantity > 0:
        result["initial_risk"] = abs(entry - stop) * quantity
    net = _number(inputs.get("net_realized_pl"))
    if result["initial_risk"] and net is not None:
        result["realized_r_multiple"] = net / result["initial_risk"]
    entry_at = _timestamp(inputs.get("entry_at"))
    exit_at = _timestamp(inputs.get("exit_at"))
    if entry_at is not None and exit_at is not None and exit_at >= entry_at:
        result["holding_seconds"] = (exit_at - entry_at).total_seconds()
    sessions = inputs.get("completed_sessions")
    if isinstance(sessions, int) and sessions >= 0:
        result["holding_sessions"] = sessions
    if _number(inputs.get("mae")) is not None:
        result["mae"] = _number(inputs.get("mae"))
    if _number(inputs.get("mfe")) is not None:
        result["mfe"] = _number(inputs.get("mfe"))
    return result


def _empty_snapshot(session_date: str, captured_at: datetime, *, status: str = "unavailable") -> dict[str, Any]:
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "session_date": session_date,
        "captured_at": captured_at.isoformat(),
        "revision": 1,
        "status": status,
        "content_hash": None,
        "received": None,
        "valid": None,
        "attributed": None,
        "unavailable": None,
        "ambiguous": None,
        "conflict": None,
        "broker_order_count": None,
        "operation_count": None,
        "denominators": {
            "buy_order_count": None,
            "sell_order_count": None,
            "fill_fragment_count": None,
            "attributed_sell_count": None,
            "unavailable_sell_count": None,
            "ambiguous_sell_count": None,
            "conflict_count": None,
            "closed_lot_count": None,
            "partially_closed_lot_count": None,
            "open_lot_count": None,
        },
        "coverage": {
            "gross_pl_coverage": _coverage(0, 0),
            "cost_coverage": _coverage(0, 0),
            "net_pl_coverage": _coverage(0, 0),
        },
        "metrics": {
            "gross_realized_pl": None,
            "commissions": None,
            "regulatory_fees": None,
            "spread_cost": None,
            "slippage_cost": None,
            "other_costs": None,
            "net_realized_pl": None,
            "initial_risk": None,
            "realized_r_multiple": None,
            "holding_seconds": None,
            "holding_sessions": None,
            "mae": None,
            "mfe": None,
        },
        "gross_attributed_pl": None,
        "net_attributable_pl": None,
        "operations": [],
        "warnings": [],
        "reason_codes": [],
    }
    snapshot["content_hash"] = _stable_hash(snapshot)
    return snapshot


def unavailable_canonical_trade_attribution(
    session_date: str,
    *,
    captured_at: datetime | None = None,
    status: str = "unavailable",
    warning: str | None = None,
) -> dict[str, Any]:
    """Return a durable-shape fail-open result without rebuilding any input."""

    capture = captured_at or datetime.now(timezone.utc)
    if capture.tzinfo is None:
        capture = capture.replace(tzinfo=timezone.utc)
    snapshot = _empty_snapshot(session_date, capture.astimezone(timezone.utc), status=status)
    if warning:
        snapshot["warnings"].append(warning)
        snapshot["reason_codes"].append("producer_failed")
    snapshot["content_hash"] = _stable_hash(snapshot)
    return snapshot


def _raw_fragments(telemetry: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = [
        item for item in telemetry.get("fill_fragments", []) if isinstance(item, Mapping)
    ]
    for operation in telemetry.get("operations", []) or []:
        if not isinstance(operation, Mapping):
            continue
        for key in ("fill_fragments", "fills"):
            rows.extend(item for item in operation.get(key, []) if isinstance(item, Mapping))
    return rows


def build_canonical_trade_attribution(
    canonical_telemetry: Mapping[str, Any] | None,
    session_date: str,
    *,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    """Build one exact shadow snapshot from the already-built P-L48 object."""

    capture = captured_at or datetime.now(timezone.utc)
    if capture.tzinfo is None:
        capture = capture.replace(tzinfo=timezone.utc)
    capture = capture.astimezone(timezone.utc)
    if not isinstance(canonical_telemetry, Mapping):
        return _empty_snapshot(session_date, capture, status="collecting")

    try:
        raw_operations = [item for item in canonical_telemetry.get("operations", []) if isinstance(item, Mapping)]
        operations, order_issues = _deduplicate(raw_operations, "broker_order_id")
        fragments, fragment_issues = _deduplicate(_raw_fragments(canonical_telemetry), "fill_fragment_id")
        result = _empty_snapshot(session_date, capture)
        result["denominators"]["buy_order_count"] = sum(
            str(item.get("side") or "").lower() == "buy" for item in operations
        )
        sell_operations = [item for item in operations if str(item.get("side") or "").lower() == "sell"]
        result["denominators"]["sell_order_count"] = len(sell_operations)
        explicit_fill_count = (canonical_telemetry.get("denominators") or {}).get("fill_fragment_count")
        result["denominators"]["fill_fragment_count"] = (
            int(explicit_fill_count) if isinstance(explicit_fill_count, int) else len(fragments)
        )
        result["denominators"]["conflict_count"] = sum(
            issue.startswith("conflicting_") for issue in order_issues + fragment_issues
        )
        for issue in order_issues + fragment_issues:
            _add_reason(result, issue.split(":", 1)[0])

        buy_by_id = {
            str(item.get("broker_order_id")): item
            for item in operations
            if str(item.get("side") or "").lower() == "buy" and _text(item.get("broker_order_id"))
        }
        fragment_by_id = {
            str(item.get("fill_fragment_id")): item for item in fragments if _text(item.get("fill_fragment_id"))
        }
        lots: dict[tuple[str, str], dict[str, float]] = {}
        for fragment in fragments:
            if str(fragment.get("side") or "").upper() != "BUY":
                continue
            order_id = _text(fragment.get("broker_order_id"))
            lot_id = _text(fragment.get("lot_id"))
            quantity = _number(fragment.get("qty"))
            if order_id and lot_id and quantity is not None and quantity > 0:
                lot = lots.setdefault((order_id, lot_id), {"qty": 0.0, "sold_qty": 0.0})
                lot["qty"] += quantity

        costs_by_sell = canonical_telemetry.get("execution_costs") or {}
        attributed = unavailable = ambiguous = conflicts = 0
        gross_available = cost_complete = net_available = 0
        gross_values: list[float] = []
        net_values: list[float] = []
        output_operations: list[dict[str, Any]] = []

        for sell in sorted(sell_operations, key=lambda item: (str(item.get("filled_at") or ""), str(item.get("broker_order_id") or ""))):
            sell_id = _text(sell.get("broker_order_id")) or ""
            operation_output: dict[str, Any] = {
                "sell_broker_order_id": sell_id,
                "status": "unavailable",
                "allocations": [],
                "gross_realized_pl": None,
                "net_realized_pl": None,
                "reason_codes": [],
            }
            if not _is_filled(sell):
                unavailable += 1
                operation_output["reason_codes"].append("sell_status_not_terminal")
                output_operations.append(operation_output)
                continue
            attribution = sell.get("trade_attribution") or sell.get("canonical_trade_attribution")
            if isinstance(attribution, list):
                if len(attribution) != 1:
                    conflicts += 1
                    operation_output["status"] = "conflict"
                    operation_output["reason_codes"].append("duplicate_trade_attribution")
                    output_operations.append(operation_output)
                    continue
                attribution = attribution[0]
            if not isinstance(attribution, Mapping):
                ambiguous += 1
                operation_output["status"] = "ambiguous"
                operation_output["reason_codes"].append("missing_exact_mapping")
                output_operations.append(operation_output)
                continue
            allocations = attribution.get("allocations")
            if not isinstance(allocations, list) or not allocations:
                ambiguous += 1
                operation_output["status"] = "ambiguous"
                operation_output["reason_codes"].append("missing_exact_mapping")
                output_operations.append(operation_output)
                continue
            sell_qty = _number(sell.get("filled_qty"))
            if sell_qty is None or sell_qty <= 0:
                unavailable += 1
                operation_output["reason_codes"].append("missing_sell_qty")
                output_operations.append(operation_output)
                continue
            sell_fragments = [
                fragment
                for fragment in fragments
                if _text(fragment.get("broker_order_id")) == sell_id
                and str(fragment.get("side") or "").upper() == "SELL"
            ]
            if not sell_fragments:
                unavailable += 1
                operation_output["reason_codes"].append("missing_sell_fill_fragment")
                output_operations.append(operation_output)
                continue
            sell_fragment_qty = sum(_number(fragment.get("qty")) or 0.0 for fragment in sell_fragments)
            if not math.isclose(sell_fragment_qty, sell_qty, rel_tol=0.0, abs_tol=1e-9):
                conflicts += 1
                operation_output["status"] = "conflict"
                operation_output["reason_codes"].append("sell_qty_fragment_mismatch")
                output_operations.append(operation_output)
                continue
            seen_allocations: set[tuple[str, str, str]] = set()
            allocated_qty = 0.0
            local_error: str | None = None
            normalized_allocations: list[dict[str, Any]] = []
            for allocation in allocations:
                if not isinstance(allocation, Mapping):
                    local_error = "incomplete_provenance"
                    break
                buy_id = _text(allocation.get("buy_broker_order_id"))
                lot_id = _text(allocation.get("lot_id"))
                fragment_id = _text(allocation.get("fill_fragment_id"))
                quantity = _number(allocation.get("qty"))
                key = (buy_id or "", lot_id or "", fragment_id or "")
                if key in seen_allocations:
                    local_error = "duplicate_allocation"
                    break
                seen_allocations.add(key)
                if not buy_id or not lot_id or not fragment_id or quantity is None or quantity <= 0:
                    local_error = "incomplete_provenance"
                    break
                buy = buy_by_id.get(buy_id)
                if buy is None or not _is_filled(buy):
                    local_error = "buy_order_not_filled_or_unknown"
                    break
                source_plan_id = _text(attribution.get("source_plan_id") or allocation.get("source_plan_id"))
                if source_plan_id is None:
                    local_error = "missing_source_plan_id"
                    break
                entry_plan_id = _text(attribution.get("entry_plan_id") or allocation.get("entry_plan_id"))
                buy_plan_id = _text(buy.get("plan_id"))
                buy_source_plan_id = _text(buy.get("source_plan_id"))
                if entry_plan_id and entry_plan_id != buy_plan_id:
                    local_error = "entry_plan_mismatch"
                    break
                if source_plan_id not in {buy_plan_id, buy_source_plan_id}:
                    local_error = "source_plan_mismatch"
                    break
                fragment = fragment_by_id.get(fragment_id)
                if fragment is None or _text(fragment.get("broker_order_id")) != buy_id:
                    local_error = "unknown_fill_fragment"
                    break
                if _text(fragment.get("lot_id")) != lot_id or str(fragment.get("side") or "").upper() != "BUY":
                    local_error = "fill_fragment_identity_mismatch"
                    break
                fragment_qty = _number(fragment.get("qty"))
                if fragment_qty is None or quantity > fragment_qty + 1e-9:
                    local_error = "allocation_exceeds_fill"
                    break
                lot = lots.get((buy_id, lot_id))
                if lot is None or lot["sold_qty"] + quantity > lot["qty"] + 1e-9:
                    local_error = "sell_exceeds_open_qty"
                    break
                normalized_allocations.append(
                    {
                        "buy_broker_order_id": buy_id,
                        "lot_id": lot_id,
                        "fill_fragment_id": fragment_id,
                        "source_plan_id": source_plan_id,
                        "qty": quantity,
                    }
                )
                allocated_qty += quantity
            if local_error is None and not math.isclose(allocated_qty, sell_qty, rel_tol=0.0, abs_tol=1e-9):
                local_error = "mapping_qty_mismatch"
            if local_error:
                if local_error in {"missing_source_plan_id", "incomplete_provenance"}:
                    unavailable += 1
                elif local_error in {"buy_order_not_filled_or_unknown", "unknown_fill_fragment"}:
                    ambiguous += 1
                else:
                    conflicts += 1
                operation_output["status"] = "unavailable" if local_error in {"missing_source_plan_id", "incomplete_provenance"} else "ambiguous" if local_error in {"buy_order_not_filled_or_unknown", "unknown_fill_fragment"} else "conflict"
                operation_output["reason_codes"].append(local_error)
                output_operations.append(operation_output)
                continue
            for allocation in normalized_allocations:
                lots[(allocation["buy_broker_order_id"], allocation["lot_id"])]["sold_qty"] += allocation["qty"]
            attributed += 1
            operation_output.update({"status": "attributed", "allocations": normalized_allocations})
            costs = (costs_by_sell.get(sell_id) if isinstance(costs_by_sell, Mapping) else None) or sell.get("execution_costs")
            gross = _number(costs.get("gross_realized_pl")) if isinstance(costs, Mapping) else _number(sell.get("gross_realized_pl"))
            if gross is not None:
                gross_available += 1
                gross_values.append(gross)
                operation_output["gross_realized_pl"] = gross
            if isinstance(costs, Mapping) and _complete_costs(costs):
                cost_complete += 1
                net = _net_costs(costs)
                if net is not None:
                    net_available += 1
                    net_values.append(net)
                    operation_output["net_realized_pl"] = net
                operation_output["costs"] = {name: _number(costs.get(name)) for name in COST_FIELDS}
            else:
                _add_reason(result, "costs_unavailable")
            risk_inputs = sell.get("risk_metrics") or sell.get("attribution_metrics")
            if isinstance(risk_inputs, Mapping):
                operation_output["risk_metrics"] = calculate_risk_metrics(risk_inputs | {"net_realized_pl": operation_output["net_realized_pl"]})
            output_operations.append(operation_output)

        result["denominators"].update(
            {
                "attributed_sell_count": attributed,
                "unavailable_sell_count": unavailable,
                "ambiguous_sell_count": ambiguous,
                "conflict_count": result["denominators"]["conflict_count"] + conflicts,
            }
        )
        closed = sum(math.isclose(item["sold_qty"], item["qty"], rel_tol=0.0, abs_tol=1e-9) for item in lots.values())
        partial = sum(0.0 < item["sold_qty"] < item["qty"] for item in lots.values())
        open_lots = sum(item["sold_qty"] == 0.0 for item in lots.values())
        result["denominators"].update(
            {"closed_lot_count": closed, "partially_closed_lot_count": partial, "open_lot_count": open_lots}
        )
        result["coverage"] = {
            "gross_pl_coverage": _coverage(gross_available, attributed),
            "cost_coverage": _coverage(cost_complete, attributed),
            "net_pl_coverage": _coverage(net_available, attributed),
        }
        if attributed and gross_available == attributed:
            result["metrics"]["gross_realized_pl"] = sum(gross_values)
        if attributed and net_available == attributed:
            result["metrics"]["net_realized_pl"] = sum(net_values)
        if attributed and cost_complete == attributed:
            for name in COST_FIELDS:
                result["metrics"][name] = sum(float(output.get("costs", {}).get(name) or 0.0) for output in output_operations if output["status"] == "attributed")
        result["operations"] = output_operations
        result.update(
            {
                "received": len(sell_operations),
                "valid": attributed,
                "attributed": attributed,
                "unavailable": unavailable,
                "ambiguous": ambiguous,
                "conflict": result["denominators"]["conflict_count"],
                "broker_order_count": len(operations),
                "operation_count": len(operations),
                "gross_attributed_pl": result["metrics"]["gross_realized_pl"],
                "net_attributable_pl": result["metrics"]["net_realized_pl"],
            }
        )
        result["status"] = "available" if attributed and attributed == len(sell_operations) else "partial" if attributed else "unavailable"
        if not sell_operations:
            result["status"] = "unavailable"
        result["content_hash"] = _stable_hash(result)
        return result
    except Exception as exc:  # shadow producer must never block PMR
        return unavailable_canonical_trade_attribution(
            session_date,
            captured_at=capture,
            warning=f"producer_failed:{type(exc).__name__}",
        )


def persist_canonical_trade_attribution(store: Store, snapshot: Mapping[str, Any]) -> dict[str, Any]:
    event_id = EVENT_ID_PREFIX + str(snapshot.get("session_date") or "unknown")
    return store.record_canonical_trade_attribution(dict(snapshot), event_id=event_id)


def read_canonical_trade_attribution(store: Store, session_date: str) -> dict[str, Any]:
    event = store.canonical_trade_attribution_event(session_date)
    if event is None:
        snapshot = _empty_snapshot(session_date, datetime.now(timezone.utc), status="collecting")
        snapshot.update({"denominators": None, "coverage": None, "metrics": None, "content_hash": None})
        return snapshot
    payload = dict(event.get("payload") or {})
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("content_hash") != _stable_hash(payload):
        return {
            "schema_version": SCHEMA_VERSION,
            "session_date": session_date,
            "status": "legacy_without_canonical_trade_attribution",
            "denominators": None,
            "coverage": None,
            "metrics": None,
            "operations": [],
            "warnings": ["invalid_canonical_event"],
        }
    return payload


def canonical_trade_attribution_digest(store: Store, session_date: str | None = None) -> dict[str, Any]:
    if session_date:
        payload = read_canonical_trade_attribution(store, session_date)
        conflicts = store.canonical_trade_attribution_conflicts(session_date)
        return {
            "status": payload.get("status", "collecting"),
            "session_date": session_date,
            "denominators": payload.get("denominators"),
            "coverage": payload.get("coverage"),
            "metrics": payload.get("metrics"),
            "content_hash": payload.get("content_hash"),
            "conflict_events": len(conflicts),
        }
    events = store.agent_events(event_type_prefix=EVENT_TYPE, limit=50000)
    snapshots = [item for item in events if item.get("event_type") == EVENT_TYPE and str(item.get("event_id") or "").startswith(EVENT_ID_PREFIX)]
    conflicts = [item for item in events if item.get("event_type") == f"{EVENT_TYPE}_conflict"]
    if not snapshots:
        return {"status": "conflict" if conflicts else "collecting", "session_date": None, "denominators": None, "coverage": None, "metrics": None, "canonical_events": 0, "conflict_events": len(conflicts)}
    latest = sorted(snapshots, key=lambda item: str(item.get("created_at") or ""))[-1]
    payload = latest.get("payload") or {}
    return {
        "status": payload.get("status", "collecting"),
        "session_date": payload.get("session_date"),
        "denominators": payload.get("denominators"),
        "coverage": payload.get("coverage"),
        "metrics": payload.get("metrics"),
        "canonical_events": len(snapshots),
        "conflict_events": len(conflicts),
        "content_hash": payload.get("content_hash"),
    }
