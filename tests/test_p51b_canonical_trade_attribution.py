"""Caracterizacion aislada del contrato P-L51B de atribucion BUY -> SELL.

El helper deliberadamente vive en ``tests/``. No implementa Store, persistencia,
reconciliacion ni wiring operativo. Las fixtures usan IDs sanitizados y separan
ordenes, fills, lotes, planes, recomendaciones y senales.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import pytest

SCHEMA_VERSION = "p-l51b.canonical-trade-attribution.v1"
COST_FIELDS = (
    "commissions",
    "regulatory_fees",
    "spread_cost",
    "slippage_cost",
    "other_costs",
)
FILLED_STATUSES = {"filled", "partially_filled"}
POST_DECISION_FIELDS = {
    "fills",
    "fill_fragments",
    "realized_pl",
    "net_realized_pl",
    "first_fill_at",
    "filled_at",
    "exit_origin",
    "mae",
    "mfe",
    "future_return",
}


def _copy(value: Any) -> Any:
    return copy.deepcopy(value)


def _utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _reason_codes(*codes: str) -> list[str]:
    return list(dict.fromkeys(code for code in codes if code))


def _coverage(available: int, total: int) -> dict[str, Any]:
    return {
        "available": available,
        "total": total,
        "ratio": available / total if total else None,
    }


def _stable_json_hash(payload: Mapping[str, Any]) -> str:
    """Hash canonical content; captured_at is observation metadata, not content."""

    content = _copy(dict(payload))
    content.pop("captured_at", None)
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def append_only_capture(
    existing: Mapping[str, Mapping[str, Any]] | None,
    incoming: Mapping[str, Any],
) -> dict[str, Any]:
    """Modela no-op idempotente y conflicto sin mutar el evento original."""

    event = _copy(dict(incoming))
    event_id = str(event["event_id"])
    event_hash = _stable_json_hash(event)
    previous = dict(existing or {}).get(event_id)
    if previous is None:
        return {"status": "inserted", "event_id": event_id, "content_hash": event_hash}
    previous_hash = _stable_json_hash(previous)
    status = "idempotent" if previous_hash == event_hash else "conflict"
    return {"status": status, "event_id": event_id, "content_hash": event_hash}


def _deduplicate_records(
    records: list[Mapping[str, Any]],
    key: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    unique: dict[str, dict[str, Any]] = {}
    conflicts: list[str] = []
    for raw in records:
        identifier = raw.get(key)
        if not identifier:
            conflicts.append(f"missing_{key}")
            continue
        identifier = str(identifier)
        record = _copy(dict(raw))
        previous = unique.get(identifier)
        if previous is None:
            unique[identifier] = record
        elif previous != record:
            conflicts.append(f"conflicting_{key}:{identifier}")
        else:
            conflicts.append(f"duplicate_{key}:{identifier}")
    return list(unique.values()), conflicts


def _valid_cost_vector(costs: Mapping[str, Any] | None) -> bool:
    if not costs or costs.get("gross_realized_pl") is None:
        return False
    values = [costs.get(name) for name in COST_FIELDS]
    return all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in values)


def _net_value(costs: Mapping[str, Any]) -> float | None:
    if not _valid_cost_vector(costs):
        return None
    gross = float(costs["gross_realized_pl"])
    return gross - sum(float(costs[name]) for name in COST_FIELDS)


def _empty_result(fixture: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "received": 0,
        "valid": 0,
        "attributed": 0,
        "unavailable": 0,
        "ambiguous": 0,
        "conflict": 0,
        "broker_order_count": 0,
        "operation_count": 0,
        "buy_order_count": 0,
        "sell_order_count": 0,
        "fill_fragment_count": 0,
        "closed_lot_count": 0,
        "partially_closed_lot_count": 0,
        "open_lot_count": 0,
        "gross_pl_coverage": _coverage(0, 0),
        "net_pl_coverage": _coverage(0, 0),
        "cost_coverage": _coverage(0, 0),
        "gross_attributed_pl": None,
        "net_attributable_pl": None,
        "denominators": {
            "signal_count": fixture.get("signal_count"),
            "candidate_count": fixture.get("candidate_count"),
            "recommendation_count": fixture.get("recommendation_count"),
            "plan_count": fixture.get("plan_count"),
            "trade_memory_fragment_count": len(fixture.get("trade_memory") or []),
            "signal_outcome_count": len(fixture.get("signal_outcomes") or []),
        },
        "warnings": [],
        "reason_codes": [],
    }


def characterize_attribution(fixture: Mapping[str, Any]) -> dict[str, Any]:
    """Validates only exact provenance and returns a JSON-serializable result.

    A SELL mapping is valid only when its allocations declare the BUY order, lot,
    source plan and quantity, and the quantities reconcile with canonical fills.
    No symbol/date, FIFO, approximate signal, trade-memory or outcome fallback is
    consulted.
    """

    source = _copy(dict(fixture))
    result = _empty_result(source)
    orders, order_issues = _deduplicate_records(list(source.get("broker_orders") or []), "broker_order_id")
    fragments, fragment_issues = _deduplicate_records(
        list(source.get("fill_fragments") or []), "fill_fragment_id"
    )
    result["broker_order_count"] = len(orders)
    result["fill_fragment_count"] = len(fragments)
    result["conflict"] += sum(issue.startswith("conflicting_") for issue in order_issues)
    result["conflict"] += sum(issue.startswith("conflicting_") for issue in fragment_issues)
    result["reason_codes"] = _reason_codes(
        *[issue.split(":", 1)[0] for issue in order_issues + fragment_issues]
    )

    by_order = {str(order["broker_order_id"]): order for order in orders if order.get("broker_order_id")}
    buy_orders = [order for order in orders if str(order.get("side", "")).upper() == "BUY"]
    sell_orders = [order for order in orders if str(order.get("side", "")).upper() == "SELL"]
    result["buy_order_count"] = len(buy_orders)
    result["sell_order_count"] = len(sell_orders)
    result["received"] = len(sell_orders)
    result["operation_count"] = len(orders)

    fragments_by_order: dict[str, list[dict[str, Any]]] = {}
    lots: dict[str, dict[str, Any]] = {}
    for fragment in fragments:
        order_id = str(fragment.get("broker_order_id") or "")
        fragments_by_order.setdefault(order_id, []).append(fragment)
        order = by_order.get(order_id)
        if str(fragment.get("side", order.get("side") if order else "")).upper() != "BUY":
            continue
        lot_id = fragment.get("lot_id")
        qty = fragment.get("qty")
        if not lot_id or not isinstance(qty, (int, float)) or float(qty) <= 0:
            result["conflict"] += 1
            result["reason_codes"] = _reason_codes(*result["reason_codes"], "invalid_buy_fill")
            continue
        if not order or str(order.get("status", "")).lower() not in FILLED_STATUSES:
            result["unavailable"] += 1
            result["reason_codes"] = _reason_codes(*result["reason_codes"], "buy_status_not_filled")
            continue
        lot = lots.setdefault(
            str(lot_id),
            {
                "buy_broker_order_id": order_id,
                "source_plan_id": order.get("source_plan_id"),
                "qty": 0.0,
                "sold_qty": 0.0,
            },
        )
        if lot["buy_broker_order_id"] != order_id:
            result["conflict"] += 1
            result["reason_codes"] = _reason_codes(*result["reason_codes"], "lot_identity_conflict")
            continue
        lot["qty"] += float(qty)

    mappings_by_sell: dict[str, list[Mapping[str, Any]]] = {}
    for mapping in list(source.get("attributions") or []):
        sell_id = mapping.get("sell_broker_order_id")
        if sell_id:
            mappings_by_sell.setdefault(str(sell_id), []).append(mapping)

    execution_costs = source.get("execution_costs") or {}
    gross_available = 0
    cost_complete = 0
    net_available = 0
    net_values: list[float] = []
    gross_values: list[float] = []

    for sell in sell_orders:
        sell_id = str(sell.get("broker_order_id") or "")
        status = str(sell.get("status", "")).lower()
        if status not in FILLED_STATUSES:
            result["unavailable"] += 1
            result["reason_codes"] = _reason_codes(
                *result["reason_codes"], f"sell_status_not_terminal:{status or 'missing'}"
            )
            continue
        mappings = mappings_by_sell.get(sell_id, [])
        if not mappings:
            result["ambiguous"] += 1
            result["reason_codes"] = _reason_codes(*result["reason_codes"], "missing_exact_mapping")
            continue
        if len(mappings) != 1:
            result["conflict"] += 1
            result["reason_codes"] = _reason_codes(*result["reason_codes"], "duplicate_sell_mapping")
            continue
        mapping = mappings[0]
        declared_source_plans = mapping.get("source_plan_ids")
        if declared_source_plans and len(declared_source_plans) != len(set(declared_source_plans)):
            result["conflict"] += 1
            result["reason_codes"] = _reason_codes(*result["reason_codes"], "duplicate_source_plan_provenance")
            continue
        allocations = mapping.get("allocations")
        if not isinstance(allocations, list) or not allocations:
            result["ambiguous"] += 1
            result["reason_codes"] = _reason_codes(*result["reason_codes"], "missing_exact_mapping")
            continue
        allocation_keys: set[tuple[str, str, str]] = set()
        allocated_qty = 0.0
        allocation_error: str | None = None
        for allocation in allocations:
            buy_id = str(allocation.get("buy_broker_order_id") or "")
            lot_id = str(allocation.get("lot_id") or "")
            fragment_id = str(allocation.get("fill_fragment_id") or "")
            key = (buy_id, lot_id, fragment_id)
            if key in allocation_keys:
                allocation_error = "duplicate_allocation"
                break
            allocation_keys.add(key)
            qty = allocation.get("qty")
            if not buy_id or not lot_id or not fragment_id or not isinstance(qty, (int, float)) or float(qty) <= 0:
                allocation_error = "incomplete_provenance"
                break
            lot = lots.get(lot_id)
            buy = by_order.get(buy_id)
            if lot is None or buy is None or lot["buy_broker_order_id"] != buy_id:
                allocation_error = "unknown_lot_or_buy_order"
                break
            if not allocation.get("source_plan_id"):
                allocation_error = "missing_source_plan_id"
                break
            if allocation["source_plan_id"] != buy.get("source_plan_id"):
                allocation_error = "source_plan_mismatch"
                break
            canonical_fragment = next(
                (
                    item
                    for item in fragments_by_order.get(buy_id, [])
                    if str(item.get("fill_fragment_id")) == fragment_id
                    and str(item.get("lot_id")) == lot_id
                ),
                None,
            )
            if canonical_fragment is None:
                allocation_error = "unknown_fill_fragment"
                break
            quantity = float(qty)
            if lot["sold_qty"] + quantity > lot["qty"]:
                allocation_error = "sell_exceeds_open_qty"
                break
            allocated_qty += quantity
        if allocation_error:
            if allocation_error in {"missing_source_plan_id", "incomplete_provenance"}:
                result["unavailable"] += 1
            elif allocation_error == "unknown_lot_or_buy_order":
                result["ambiguous"] += 1
            else:
                result["conflict"] += 1
            result["reason_codes"] = _reason_codes(*result["reason_codes"], allocation_error)
            continue
        sell_qty = sell.get("filled_qty")
        if not isinstance(sell_qty, (int, float)) or float(sell_qty) <= 0:
            result["unavailable"] += 1
            result["reason_codes"] = _reason_codes(*result["reason_codes"], "missing_sell_qty")
            continue
        sell_fragments_qty = sum(
            float(item.get("qty") or 0.0) for item in fragments_by_order.get(sell_id, [])
        )
        if not math.isclose(sell_fragments_qty, float(sell_qty), rel_tol=0.0, abs_tol=1e-9):
            result["conflict"] += 1
            result["reason_codes"] = _reason_codes(*result["reason_codes"], "sell_qty_fragment_mismatch")
            continue
        if not math.isclose(allocated_qty, float(sell_qty), rel_tol=0.0, abs_tol=1e-9):
            result["conflict"] += 1
            result["reason_codes"] = _reason_codes(*result["reason_codes"], "mapping_qty_mismatch")
            continue
        for allocation in allocations:
            lots[str(allocation["lot_id"])]["sold_qty"] += float(allocation["qty"])
        result["valid"] += 1
        result["attributed"] += 1
        costs = execution_costs.get(sell_id)
        if costs and costs.get("gross_realized_pl") is not None:
            gross_available += 1
            gross_values.append(float(costs["gross_realized_pl"]))
        if costs and _valid_cost_vector(costs):
            cost_complete += 1
            net_value = _net_value(costs)
            if net_value is not None:
                net_available += 1
                net_values.append(net_value)
        else:
            result["warnings"].append(f"costs_unavailable:{sell_id}")

    result["closed_lot_count"] = sum(
        math.isclose(lot["sold_qty"], lot["qty"], rel_tol=0.0, abs_tol=1e-9) for lot in lots.values()
    )
    result["partially_closed_lot_count"] = sum(
        0.0 < lot["sold_qty"] < lot["qty"] for lot in lots.values()
    )
    result["open_lot_count"] = sum(lot["sold_qty"] == 0.0 for lot in lots.values())
    result["gross_pl_coverage"] = _coverage(gross_available, result["attributed"])
    result["cost_coverage"] = _coverage(cost_complete, result["attributed"])
    result["net_pl_coverage"] = _coverage(net_available, result["attributed"])
    if result["attributed"] and gross_available == result["attributed"]:
        result["gross_attributed_pl"] = sum(gross_values)
    if result["attributed"] and net_available == result["attributed"]:
        result["net_attributable_pl"] = sum(net_values)
    if source.get("trade_memory"):
        result["warnings"].append("trade_memory_not_provenance")
        result["reason_codes"] = _reason_codes(*result["reason_codes"], "trade_memory_not_provenance")
    if source.get("signal_outcomes"):
        result["warnings"].append("signal_outcomes_not_operations")
        result["reason_codes"] = _reason_codes(*result["reason_codes"], "signal_outcomes_not_operations")
    result["warnings"] = list(dict.fromkeys(result["warnings"]))
    result["reason_codes"] = _reason_codes(*result["reason_codes"])
    return result


def descriptive_exit_ledger(sell_orders: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Keeps a raw exit ledger separate from exact closed-lot attribution."""

    values = [float(order["realized_pl"]) for order in sell_orders if order.get("realized_pl") is not None]
    return {"count": len(values), "total": sum(values) if values else None, "kind": "exit_ledger_descriptive"}


def calculate_slippage(
    *,
    side: str,
    benchmark_price: float | None,
    fill_price: float | None,
    benchmark_at: str | datetime | None,
    filled_at: str | datetime | None,
) -> dict[str, Any]:
    """Returns adverse slippage bps only from explicit benchmark and timestamps."""

    if benchmark_price is None or fill_price is None:
        return {"slippage_bps": None, "status": "unavailable", "reason_code": "missing_benchmark_or_fill"}
    if benchmark_price <= 0 or not all(math.isfinite(float(value)) for value in (benchmark_price, fill_price)):
        return {"slippage_bps": None, "status": "unavailable", "reason_code": "invalid_price"}
    if benchmark_at is None or filled_at is None:
        return {"slippage_bps": None, "status": "unavailable", "reason_code": "missing_timestamps"}
    try:
        benchmark_time = _utc(benchmark_at)
        fill_time = _utc(filled_at)
    except (TypeError, ValueError):
        return {"slippage_bps": None, "status": "unavailable", "reason_code": "invalid_timestamp"}
    if fill_time < benchmark_time:
        return {"slippage_bps": None, "status": "unavailable", "reason_code": "inverted_timestamp"}
    signed = (float(fill_price) - benchmark_price) / benchmark_price
    adverse = signed if side.upper() == "BUY" else -signed if side.upper() == "SELL" else None
    if adverse is None:
        return {"slippage_bps": None, "status": "unavailable", "reason_code": "invalid_side"}
    return {"slippage_bps": adverse * 10_000.0, "status": "available", "reason_code": None}


def calculate_risk_metrics(inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Calculates only metrics whose exact required inputs are present."""

    result: dict[str, Any] = {
        "initial_risk": None,
        "realized_r_multiple": None,
        "holding_seconds": None,
        "holding_sessions": None,
        "mae": None,
        "mfe": None,
    }
    entry_price = inputs.get("entry_price")
    stop_price = inputs.get("stop_price")
    qty = inputs.get("entry_qty")
    if all(isinstance(value, (int, float)) for value in (entry_price, stop_price, qty)) and float(qty) > 0:
        result["initial_risk"] = abs(float(entry_price) - float(stop_price)) * float(qty)
    if result["initial_risk"] and inputs.get("net_realized_pl") is not None:
        result["realized_r_multiple"] = float(inputs["net_realized_pl"]) / result["initial_risk"]
    try:
        if inputs.get("entry_at") is not None and inputs.get("exit_at") is not None:
            result["holding_seconds"] = (_utc(inputs["exit_at"]) - _utc(inputs["entry_at"])).total_seconds()
            if result["holding_seconds"] < 0:
                result["holding_seconds"] = None
    except (TypeError, ValueError):
        result["holding_seconds"] = None
    if isinstance(inputs.get("completed_sessions"), int) and inputs["completed_sessions"] >= 0:
        result["holding_sessions"] = inputs["completed_sessions"]
    if isinstance(inputs.get("mae"), (int, float)):
        result["mae"] = float(inputs["mae"])
    if isinstance(inputs.get("mfe"), (int, float)):
        result["mfe"] = float(inputs["mfe"])
    return result


def validate_predecision_features(features: Mapping[str, Any]) -> None:
    leaked = sorted(set(features).intersection(POST_DECISION_FIELDS))
    if leaked:
        raise ValueError(f"post-decision fields in features: {', '.join(leaked)}")


def _buy(
    order_id: str = "buy-1",
    *,
    symbol: str = "ACME",
    plan_id: str = "plan-1",
    source_plan_id: str | None = "source-plan-1",
    status: str = "filled",
) -> dict[str, Any]:
    return {
        "broker_order_id": order_id,
        "client_order_id": f"client-{order_id}",
        "side": "BUY",
        "status": status,
        "symbol": symbol,
        "plan_id": plan_id,
        "source_plan_id": source_plan_id,
        "recommendation_id": f"rec-{order_id}",
        "candidate_id": f"candidate-{order_id}",
        "signal_capture_id": f"capture-{order_id}",
        "signal_id": f"signal-{order_id}",
        "cycle_id": f"cycle-{order_id}",
    }


def _sell(
    order_id: str = "sell-1",
    *,
    qty: float = 10.0,
    status: str = "filled",
    symbol: str = "ACME",
    realized_pl: float | None = None,
) -> dict[str, Any]:
    return {
        "broker_order_id": order_id,
        "client_order_id": f"client-{order_id}",
        "side": "SELL",
        "status": status,
        "symbol": symbol,
        "filled_qty": qty,
        "realized_pl": realized_pl,
    }


def _fill(
    order_id: str,
    fragment_id: str,
    *,
    lot_id: str | None,
    qty: float,
    side: str,
) -> dict[str, Any]:
    return {
        "fill_fragment_id": fragment_id,
        "broker_order_id": order_id,
        "lot_id": lot_id,
        "qty": qty,
        "side": side,
        "price": 100.0,
        "filled_at": "2026-07-21T15:31:00+00:00",
    }


def _mapping(
    sell_id: str = "sell-1",
    *,
    buy_id: str = "buy-1",
    lot_id: str = "lot-1",
    fragment_id: str = "buy-fill-1",
    qty: float = 10.0,
    source_plan_id: str | None = "source-plan-1",
) -> dict[str, Any]:
    return {
        "sell_broker_order_id": sell_id,
        "allocations": [
            {
                "buy_broker_order_id": buy_id,
                "lot_id": lot_id,
                "fill_fragment_id": fragment_id,
                "qty": qty,
                "source_plan_id": source_plan_id,
            }
        ],
    }


def _full_costs(sell_id: str = "sell-1") -> dict[str, dict[str, float]]:
    return {
        sell_id: {
            "gross_realized_pl": 100.0,
            "commissions": 1.0,
            "regulatory_fees": 0.5,
            "spread_cost": 2.0,
            "slippage_cost": 1.5,
            "other_costs": 0.25,
        }
    }


def _valid_fixture() -> dict[str, Any]:
    return {
        "broker_orders": [_buy(), _sell()],
        "fill_fragments": [
            _fill("buy-1", "buy-fill-1", lot_id="lot-1", qty=10.0, side="BUY"),
            _fill("sell-1", "sell-fill-1", lot_id="lot-1", qty=10.0, side="SELL"),
        ],
        "attributions": [_mapping()],
        "execution_costs": _full_costs(),
        "signal_count": 1,
        "candidate_count": 1,
        "recommendation_count": 1,
        "plan_count": 1,
    }


def test_complete_buy_sell_mapping_is_serializable_and_net_is_explicit() -> None:
    result = characterize_attribution(_valid_fixture())
    assert result["schema_version"] == SCHEMA_VERSION
    assert result["received"] == result["valid"] == result["attributed"] == 1
    assert result["closed_lot_count"] == 1
    assert result["partially_closed_lot_count"] == 0
    assert result["open_lot_count"] == 0
    assert result["gross_attributed_pl"] == 100.0
    assert result["net_attributable_pl"] == pytest.approx(94.75)
    assert json.loads(json.dumps(result, sort_keys=True))["net_attributable_pl"] == pytest.approx(94.75)


def test_duplicate_memory_fragments_do_not_duplicate_canonical_fill_or_operation() -> None:
    fixture = _valid_fixture()
    fixture["fill_fragments"].insert(1, _copy(fixture["fill_fragments"][0]))
    result = characterize_attribution(fixture)
    assert result["fill_fragment_count"] == 2
    assert result["operation_count"] == 2
    assert result["closed_lot_count"] == 1
    assert "duplicate_fill_fragment_id" in result["reason_codes"]


def test_partial_entry_and_exit_keeps_lot_partially_closed() -> None:
    fixture = _valid_fixture()
    fixture["broker_orders"][0]["status"] = "partially_filled"
    fixture["broker_orders"][1]["filled_qty"] = 2.0
    fixture["fill_fragments"][0]["qty"] = 3.0
    fixture["fill_fragments"][1]["qty"] = 2.0
    fixture["attributions"][0]["allocations"][0]["qty"] = 2.0
    result = characterize_attribution(fixture)
    assert result["attributed"] == 1
    assert result["closed_lot_count"] == 0
    assert result["partially_closed_lot_count"] == 1
    assert result["open_lot_count"] == 0


def test_multiple_exits_can_consume_one_lot_without_fifo() -> None:
    fixture = _valid_fixture()
    fixture["broker_orders"] = [_buy(), _sell("sell-1", qty=4.0), _sell("sell-2", qty=6.0)]
    fixture["fill_fragments"] = [
        _fill("buy-1", "buy-fill-1", lot_id="lot-1", qty=10.0, side="BUY"),
        _fill("sell-1", "sell-fill-1", lot_id="lot-1", qty=4.0, side="SELL"),
        _fill("sell-2", "sell-fill-2", lot_id="lot-1", qty=6.0, side="SELL"),
    ]
    fixture["attributions"] = [_mapping("sell-1", qty=4.0), _mapping("sell-2", qty=6.0)]
    fixture["execution_costs"] = {**_full_costs("sell-1"), **_full_costs("sell-2")}
    result = characterize_attribution(fixture)
    assert result["attributed"] == 2
    assert result["closed_lot_count"] == 1
    assert result["net_pl_coverage"]["total"] == 2


def test_rebuys_same_symbol_are_distinct_lots_and_explicit_multi_lot_exit_is_allowed() -> None:
    fixture = {
        "broker_orders": [_buy(), _buy("buy-2", plan_id="plan-2", source_plan_id="source-plan-2"), _sell("sell-1", qty=6.0)],
        "fill_fragments": [
            _fill("buy-1", "buy-fill-1", lot_id="lot-1", qty=4.0, side="BUY"),
            _fill("buy-2", "buy-fill-2", lot_id="lot-2", qty=4.0, side="BUY"),
            _fill("sell-1", "sell-fill-1", lot_id="lot-1", qty=4.0, side="SELL"),
            _fill("sell-1", "sell-fill-2", lot_id="lot-2", qty=2.0, side="SELL"),
        ],
        "attributions": [
            {
                "sell_broker_order_id": "sell-1",
                "allocations": [
                    {"buy_broker_order_id": "buy-1", "lot_id": "lot-1", "fill_fragment_id": "buy-fill-1", "qty": 4.0, "source_plan_id": "source-plan-1"},
                    {"buy_broker_order_id": "buy-2", "lot_id": "lot-2", "fill_fragment_id": "buy-fill-2", "qty": 2.0, "source_plan_id": "source-plan-2"},
                ],
            }
        ],
        "execution_costs": _full_costs(),
    }
    result = characterize_attribution(fixture)
    assert result["attributed"] == 1
    assert result["closed_lot_count"] == 1
    assert result["partially_closed_lot_count"] == 1
    assert result["open_lot_count"] == 0


def test_same_symbol_and_date_without_mapping_is_ambiguous_not_fifo() -> None:
    fixture = _valid_fixture()
    fixture["broker_orders"].append(_buy("buy-2", symbol="ACME"))
    fixture["fill_fragments"].append(_fill("buy-2", "buy-fill-2", lot_id="lot-2", qty=10.0, side="BUY"))
    fixture["attributions"] = []
    result = characterize_attribution(fixture)
    assert result["attributed"] == 0
    assert result["ambiguous"] == 1
    assert result["closed_lot_count"] == 0
    assert "missing_exact_mapping" in result["reason_codes"]


@pytest.mark.parametrize(
    ("change", "field", "expected_state", "reason"),
    [
        (lambda mapping: mapping["allocations"][0].update(source_plan_id=None), "unavailable", "unavailable", "missing_source_plan_id"),
        (lambda mapping: mapping.update(source_plan_ids=["source-plan-1", "source-plan-1"]), "conflict", "conflict", "duplicate_source_plan_provenance"),
        (lambda mapping: mapping["allocations"][0].update(source_plan_id="wrong-plan"), "conflict", "conflict", "source_plan_mismatch"),
    ],
)
def test_source_plan_provenance_is_required_and_exact(change: Any, field: str, expected_state: str, reason: str) -> None:
    fixture = _valid_fixture()
    change(fixture["attributions"][0])
    result = characterize_attribution(fixture)
    assert result[field] == 1
    assert result["attributed"] == 0
    assert reason in result["reason_codes"]


def test_duplicate_sell_mapping_is_conflict_not_double_count() -> None:
    fixture = _valid_fixture()
    fixture["attributions"].append(_copy(fixture["attributions"][0]))
    result = characterize_attribution(fixture)
    assert result["conflict"] == 1
    assert result["attributed"] == 0
    assert "duplicate_sell_mapping" in result["reason_codes"]


def test_sell_quantity_cannot_exceed_open_quantity() -> None:
    fixture = _valid_fixture()
    fixture["broker_orders"][1]["filled_qty"] = 11.0
    fixture["fill_fragments"][1]["qty"] = 11.0
    fixture["attributions"][0]["allocations"][0]["qty"] = 11.0
    result = characterize_attribution(fixture)
    assert result["conflict"] == 1
    assert result["attributed"] == 0
    assert "sell_exceeds_open_qty" in result["reason_codes"]


@pytest.mark.parametrize("status", ["pending", "rejected", "cancelled"])
def test_non_terminal_sell_is_unavailable_and_never_a_fill(status: str) -> None:
    fixture = _valid_fixture()
    fixture["broker_orders"][1]["status"] = status
    result = characterize_attribution(fixture)
    assert result["received"] == 1
    assert result["unavailable"] == 1
    assert result["attributed"] == 0
    assert result["closed_lot_count"] == 0


@pytest.mark.parametrize(
    ("costs", "gross_coverage", "cost_coverage", "net_coverage", "net"),
    [
        (_full_costs(), 1, 1, 1, 94.75),
        ({"sell-1": {"gross_realized_pl": 100.0, "commissions": 1.0}}, 1, 0, 0, None),
        ({}, 0, 0, 0, None),
    ],
)
def test_missing_costs_never_become_zero_or_gross_net(
    costs: dict[str, Any],
    gross_coverage: int,
    cost_coverage: int,
    net_coverage: int,
    net: float | None,
) -> None:
    fixture = _valid_fixture()
    fixture["execution_costs"] = costs
    result = characterize_attribution(fixture)
    assert result["gross_pl_coverage"]["available"] == gross_coverage
    assert result["cost_coverage"]["available"] == cost_coverage
    assert result["net_pl_coverage"]["available"] == net_coverage
    assert result["net_attributable_pl"] == net
    if net is None:
        assert result["net_pl_coverage"]["ratio"] == 0.0


def test_slippage_requires_explicit_benchmark_side_price_and_ordered_timestamps() -> None:
    buy = calculate_slippage(
        side="BUY",
        benchmark_price=100.0,
        fill_price=100.25,
        benchmark_at="2026-07-21T15:30:00+00:00",
        filled_at="2026-07-21T15:31:00+00:00",
    )
    sell = calculate_slippage(
        side="SELL",
        benchmark_price=100.0,
        fill_price=99.75,
        benchmark_at="2026-07-21T15:30:00+00:00",
        filled_at="2026-07-21T15:31:00+00:00",
    )
    assert buy["slippage_bps"] == pytest.approx(25.0)
    assert sell["slippage_bps"] == pytest.approx(25.0)
    assert calculate_slippage(side="BUY", benchmark_price=None, fill_price=100.0, benchmark_at=None, filled_at=None)["status"] == "unavailable"
    assert calculate_slippage(side="BUY", benchmark_price=100.0, fill_price=100.0, benchmark_at="2026-07-21T15:31:00+00:00", filled_at="2026-07-21T15:30:00+00:00")["reason_code"] == "inverted_timestamp"
    assert calculate_slippage(side="BUY", benchmark_price=100.0, fill_price=100.0, benchmark_at="2026-07-21T15:30:00", filled_at="2026-07-21T15:31:00+00:00")["reason_code"] == "invalid_timestamp"


def test_risk_metrics_require_exact_inputs_and_do_not_impute_missing_values() -> None:
    complete = calculate_risk_metrics(
        {
            "entry_price": 100.0,
            "stop_price": 95.0,
            "entry_qty": 10.0,
            "net_realized_pl": 25.0,
            "entry_at": "2026-07-20T15:30:00+00:00",
            "exit_at": "2026-07-21T15:30:00+00:00",
            "completed_sessions": 1,
            "mae": -12.0,
            "mfe": 35.0,
        }
    )
    assert complete == {
        "initial_risk": 50.0,
        "realized_r_multiple": 0.5,
        "holding_seconds": 86400.0,
        "holding_sessions": 1,
        "mae": -12.0,
        "mfe": 35.0,
    }
    incomplete = calculate_risk_metrics({"entry_price": 100.0, "stop_price": 95.0, "entry_qty": 10.0})
    assert incomplete["initial_risk"] == 50.0
    assert incomplete["realized_r_multiple"] is None
    assert incomplete["holding_seconds"] is None
    assert incomplete["holding_sessions"] is None
    assert incomplete["mae"] is None
    assert incomplete["mfe"] is None


def test_future_fill_and_pl_are_rejected_from_predecision_features() -> None:
    validate_predecision_features({"score": 0.5, "data_quality": "fresh"})
    with pytest.raises(ValueError, match="realized_pl"):
        validate_predecision_features({"score": 0.5, "realized_pl": 10.0})


def test_hash_excludes_captured_at_and_capture_is_idempotent_or_conflict() -> None:
    event = {
        "event_id": "event-1",
        "schema": SCHEMA_VERSION,
        "operations": [{"broker_order_id": "buy-1", "qty": 1}],
        "captured_at": "2026-07-21T15:35:00+00:00",
    }
    existing = {"event-1": _copy(event)}
    repeated = _copy(event)
    repeated["captured_at"] = "2026-07-21T15:36:00+00:00"
    reordered = {
        "captured_at": "2026-07-21T15:37:00+00:00",
        "operations": [{"qty": 1, "broker_order_id": "buy-1"}],
        "schema": SCHEMA_VERSION,
        "event_id": "event-1",
    }
    conflict = {**repeated, "operations": [{"broker_order_id": "buy-1", "qty": 2}]}
    assert append_only_capture(existing, repeated)["status"] == "idempotent"
    assert append_only_capture(existing, reordered)["status"] == "idempotent"
    assert append_only_capture(existing, conflict)["status"] == "conflict"
    assert _stable_json_hash(event) == _stable_json_hash(repeated) == _stable_json_hash(reordered)
    assert existing["event-1"]["operations"][0]["qty"] == 1


def test_identity_conflict_and_fragment_conflict_are_auditable() -> None:
    fixture = _valid_fixture()
    fixture["broker_orders"].append({**_copy(fixture["broker_orders"][0]), "side": "SELL"})
    fixture["fill_fragments"].append({**_copy(fixture["fill_fragments"][0]), "qty": 9.0})
    result = characterize_attribution(fixture)
    assert result["conflict"] >= 2
    assert "conflicting_broker_order_id" in result["reason_codes"]
    assert "conflicting_fill_fragment_id" in result["reason_codes"]


def _p51a_defect_fixture() -> dict[str, Any]:
    realized = [-179.73, 637.65, -28.02, -78.32, -43.77, -4.62, 0.19, -2.75, -0.36, -0.57, -0.18, -32.32, -106.88, -11.66, -8.40, -14.86, -11.42, -38.36]
    sells = [_sell(f"sell-{index}", qty=1.0, realized_pl=value) for index, value in enumerate(realized, 1)]
    return {
        "broker_orders": sells,
        "fill_fragments": [],
        "attributions": [],
        "execution_costs": {},
        "trade_memory": [
            {"broker_order_id": order["broker_order_id"], "signal_id": f"approximate-{order['broker_order_id']}"}
            for order in sells
        ],
        "signal_outcomes": [{"signal_id": "signal-1", "return_10d": 0.01}],
        "signal_count": 1,
        "candidate_count": 1,
        "recommendation_count": 1,
        "plan_count": 1,
    }


def test_p51a_defect_stays_descriptive_and_not_net_attributable_profit() -> None:
    fixture = _p51a_defect_fixture()
    result = characterize_attribution(fixture)
    ledger = descriptive_exit_ledger(fixture["broker_orders"])
    assert ledger == {"count": 18, "total": pytest.approx(75.62), "kind": "exit_ledger_descriptive"}
    assert result["sell_order_count"] == 18
    assert result["attributed"] == 0
    assert result["closed_lot_count"] == 0
    assert result["net_attributable_pl"] is None
    assert result["gross_pl_coverage"] == {"available": 0, "total": 0, "ratio": None}
    assert "trade_memory_not_provenance" in result["reason_codes"]
    assert "signal_outcomes_not_operations" in result["reason_codes"]


def test_denominators_remain_separate_and_trade_memory_fragments_are_not_operations() -> None:
    fixture = _valid_fixture()
    fixture["trade_memory"] = [
        {"broker_order_id": "sell-1"},
        {"broker_order_id": "sell-1"},
        {"broker_order_id": "sell-1"},
    ]
    fixture["signal_outcomes"] = [{"signal_id": "signal-1"}, {"signal_id": "signal-2"}]
    fixture["signal_count"] = 2
    result = characterize_attribution(fixture)
    assert result["operation_count"] == 2
    assert result["fill_fragment_count"] == 2
    assert result["denominators"] == {
        "signal_count": 2,
        "candidate_count": 1,
        "recommendation_count": 1,
        "plan_count": 1,
        "trade_memory_fragment_count": 3,
        "signal_outcome_count": 2,
    }
    assert result["operation_count"] != result["denominators"]["trade_memory_fragment_count"]


def test_active_input_objects_are_not_mutated() -> None:
    fixture = _valid_fixture()
    before = _copy(fixture)
    characterize_attribution(fixture)
    assert fixture == before


def test_partial_and_absent_identity_stays_unavailable_not_zero() -> None:
    fixture = _valid_fixture()
    fixture["attributions"][0]["allocations"][0].pop("source_plan_id")
    result = characterize_attribution(fixture)
    assert result["unavailable"] == 1
    assert result["net_attributable_pl"] is None
    assert result["net_pl_coverage"]["ratio"] is None


def test_event_id_and_schema_are_explicit_in_serialized_capture() -> None:
    event = {
        "event_id": "trade-attribution:cycle-1",
        "schema": SCHEMA_VERSION,
        "cycle_id": "cycle-1",
        "operations": [],
        "captured_at": "2026-07-21T15:35:00+00:00",
    }
    assert append_only_capture({}, event)["status"] == "inserted"
    assert event["schema"] == SCHEMA_VERSION
    assert event["cycle_id"] == "cycle-1"
