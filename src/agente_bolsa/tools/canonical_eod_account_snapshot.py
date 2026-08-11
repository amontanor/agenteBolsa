"""Shadow contable EOD y benchmark comparable (P-L52B).

El productor recibe objetos ya construidos por el PMR. No consulta broker,
mercado, cartera ni outcomes y no es una autoridad de riesgo o ejecución.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "p-l52b.canonical-eod-account-snapshot.v1"
EVENT_TYPE = "canonical_eod_account_snapshot"
EVENT_ID_PREFIX = f"{EVENT_TYPE}:"
CALENDAR = "XNYS"
COST_FIELDS = ("commissions", "regulatory_fees", "spread_cost", "slippage_cost", "other_costs")


def _timestamp(value: Any) -> str | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _session(value: Any) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None
    return value


def content_hash(payload: Mapping[str, Any]) -> str:
    stable = copy.deepcopy(dict(payload))
    stable.pop("captured_at", None)
    stable.pop("content_hash", None)
    encoded = json.dumps(stable, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _sorted_rows(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    return sorted((copy.deepcopy(row) for row in rows), key=lambda row: tuple(str(row.get(key) or "") for key in keys))


def _coverage(status: str, **extra: Any) -> dict[str, Any]:
    result = {"status": status}
    result.update(extra)
    return result


def _cost_snapshot(gross_raw: Any, costs: Mapping[str, Any] | None, reasons: set[str]) -> tuple[float | None, dict[str, float | None], float | None, dict[str, Any]]:
    gross = _number(gross_raw)
    normalized = {name: _number((costs or {}).get(name)) for name in COST_FIELDS}
    if gross_raw is not None and gross is None:
        reasons.add("gross_realized_pl_invalid")
    missing = [name for name, value in normalized.items() if value is None]
    if costs is None:
        status = "unavailable"
        reasons.add("costs_missing")
    elif missing:
        status = "partial"
        reasons.add("costs_partial")
    else:
        status = "exact"
    net = round(gross - sum(normalized.values()), 10) if gross is not None and status == "exact" else None
    return gross, normalized, net, {"status": status, "required_fields": list(COST_FIELDS), "missing_fields": missing}


def _flow_snapshot(ledger: list[dict[str, Any]] | None, *, currency: str, start: str | None, end: str | None, reasons: set[str]) -> tuple[list[dict[str, Any]] | None, float | None, dict[str, Any]]:
    if ledger is None:
        reasons.add("external_flow_ledger_missing")
        return None, None, _coverage("unavailable", count=None)
    normalized: list[dict[str, Any]] = []
    local_reasons: set[str] = set()
    for item in ledger:
        occurred = _timestamp(item.get("occurred_at"))
        amount = _number(item.get("amount"))
        if not item.get("flow_id") or amount is None or occurred is None:
            local_reasons.add("flow_identity_or_amount_invalid")
        if occurred is not None and ((start is not None and occurred < start) or (end is not None and occurred > end)):
            local_reasons.add("flow_outside_window")
        if str(item.get("currency") or "").upper() != currency:
            local_reasons.add("flow_currency_mismatch")
        normalized.append({"flow_id": item.get("flow_id"), "amount": amount, "currency": str(item.get("currency") or "").upper() or None, "occurred_at": occurred, "kind": item.get("kind")})
    if local_reasons:
        reasons.update(local_reasons)
        return _sorted_rows(normalized, ("occurred_at", "flow_id")), None, _coverage("unavailable", count=len(normalized))
    return _sorted_rows(normalized, ("occurred_at", "flow_id")), round(sum(float(item["amount"]) for item in normalized), 10), _coverage("exact", count=len(normalized))


def _position_snapshot(positions: list[dict[str, Any]] | None, *, currency: str, reasons: set[str]) -> tuple[dict[str, float | None], dict[str, Any], list[dict[str, Any]] | None]:
    if positions is None:
        reasons.add("positions_missing")
        return ({name: None for name in ("position_market_value_start", "position_market_value_end", "gross_exposure_start", "gross_exposure_end", "net_exposure_start", "net_exposure_end")}, _coverage("unavailable", count=None, average_status="unavailable", gross_exposure_average=None, net_exposure_average=None), None)
    normalized: list[dict[str, Any]] = []
    errors: set[str] = set()
    for item in positions:
        side = str(item.get("side") or "").lower()
        start = _number(item.get("market_value_start"))
        end = _number(item.get("market_value_end"))
        if side not in {"long", "short"}:
            errors.add("position_side_invalid")
        if start is None or end is None:
            errors.add("position_market_value_missing")
        if str(item.get("currency") or currency).upper() != currency:
            errors.add("position_currency_mismatch")
        sign = 1.0 if side == "long" else -1.0 if side == "short" else 0.0
        normalized.append({"broker_order_id": item.get("broker_order_id"), "lot_identity": item.get("lot_identity"), "side": side or None, "market_value_start": start, "market_value_end": end, "signed_market_value_start": round(sign * start, 10) if start is not None else None, "signed_market_value_end": round(sign * end, 10) if end is not None else None, "currency": str(item.get("currency") or currency).upper()})
    if errors:
        reasons.update(errors)
        values = {name: None for name in ("position_market_value_start", "position_market_value_end", "gross_exposure_start", "gross_exposure_end", "net_exposure_start", "net_exposure_end")}
        status = "unavailable"
    else:
        values = {
            "position_market_value_start": round(sum(item["signed_market_value_start"] for item in normalized), 10),
            "position_market_value_end": round(sum(item["signed_market_value_end"] for item in normalized), 10),
            "gross_exposure_start": round(sum(abs(item["market_value_start"]) for item in normalized), 10),
            "gross_exposure_end": round(sum(abs(item["market_value_end"]) for item in normalized), 10),
            "net_exposure_start": round(sum(item["signed_market_value_start"] for item in normalized), 10),
            "net_exposure_end": round(sum(item["signed_market_value_end"] for item in normalized), 10),
        }
        status = "exact"
    return values, _coverage(status, count=len(normalized), average_status="unavailable", gross_exposure_average=None, net_exposure_average=None), _sorted_rows(normalized, ("broker_order_id", "lot_identity"))


def _contributions(contributions: list[dict[str, Any]] | None, *, currency: str, reasons: set[str]) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    if contributions is None:
        reasons.add("contributions_missing")
        return None, _coverage("unavailable", count=None)
    normalized: list[dict[str, Any]] = []
    errors: set[str] = set()
    for item in contributions:
        amount = _number(item.get("amount"))
        if not item.get("broker_order_id") or not item.get("lot_identity"):
            errors.add("contribution_identity_missing")
        if amount is None:
            errors.add("contribution_amount_missing")
        if str(item.get("currency") or currency).upper() != currency:
            errors.add("contribution_currency_mismatch")
        normalized.append({"broker_order_id": item.get("broker_order_id"), "lot_identity": item.get("lot_identity"), "amount": amount, "currency": str(item.get("currency") or currency).upper(), "origin": item.get("origin")})
    reasons.update(errors)
    return _sorted_rows(normalized, ("broker_order_id", "lot_identity")), _coverage("exact" if not errors else "unavailable", count=len(normalized))


def _benchmark(benchmark: Mapping[str, Any] | None, *, start: str | None, end: str | None, warnings: set[str], reasons: set[str]) -> dict[str, Any]:
    if benchmark is None:
        reasons.add("benchmark_missing")
        return {"symbol": "SPY", "start_price": None, "end_price": None, "start_at": None, "end_at": None, "price_basis": None, "quality": "unavailable", "return": None, "comparison_status": "unavailable", "comparable": False, "reason_codes": ["benchmark_missing"]}
    local: set[str] = set()
    symbol = str(benchmark.get("symbol") or "").upper() or None
    if symbol != "SPY":
        local.add("benchmark_symbol_mismatch")
    benchmark_start = _timestamp(benchmark.get("window_start_at"))
    benchmark_end = _timestamp(benchmark.get("window_end_at"))
    start_at = _timestamp(benchmark.get("start_at"))
    end_at = _timestamp(benchmark.get("end_at"))
    if benchmark_start != start or benchmark_end != end:
        local.add("benchmark_window_mismatch")
    if start_at != start or end_at != end:
        local.add("benchmark_timestamp_mismatch")
    first = _number(benchmark.get("start_price"))
    last = _number(benchmark.get("end_price"))
    if first is None or last is None or first <= 0 or last <= 0:
        local.add("benchmark_price_missing_or_invalid")
    basis = benchmark.get("price_basis")
    if not basis or benchmark.get("start_price_basis", basis) != benchmark.get("end_price_basis", basis) or basis not in {"unadjusted_close", "adjusted_close"}:
        local.add("benchmark_price_basis_unknown_or_mismatched")
    quality = str(benchmark.get("quality") or "unknown").lower()
    if quality not in {"exact", "verified"}:
        local.add(f"benchmark_quality_{quality}")
    if benchmark.get("as_of") is not None and _timestamp(benchmark.get("as_of")) != end:
        local.add("benchmark_as_of_mismatch")
    if local:
        warnings.add("benchmark_comparison_degraded")
        reasons.update(local)
    return {"symbol": symbol, "start_price": first, "end_price": last, "start_at": start_at, "end_at": end_at, "price_basis": basis, "quality": quality, "return": round((last - first) / first, 10) if first and last and first > 0 else None, "comparison_status": "comparable" if not local else "degraded", "comparable": not local, "reason_codes": sorted(local)}


def build_canonical_eod_account_snapshot(
    *,
    session_date: str,
    account_id: str,
    currency: str,
    window_start_at: Any,
    window_end_at: Any,
    generated_at: Any,
    as_of: Any,
    captured_at: Any,
    equity_start: Any = None,
    equity_end: Any = None,
    cash_start: Any = None,
    cash_end: Any = None,
    open_pl_start: Any = None,
    open_pl_end: Any = None,
    gross_realized_pl: Any = None,
    costs: Mapping[str, Any] | None = None,
    external_flow_ledger: list[dict[str, Any]] | None = None,
    positions: list[dict[str, Any]] | None = None,
    exposure_samples: list[dict[str, Any]] | None = None,
    contributions: list[dict[str, Any]] | None = None,
    open_orders: list[dict[str, Any]] | None = None,
    benchmark: Mapping[str, Any] | None = None,
    source_timestamps: Mapping[str, Any] | None = None,
    session_count: int | None = None,
    comparable_session_count: int | None = None,
    outcomes_matured: bool = False,
    descriptive_realized_pl: Any = None,
    account_read_at: Any = None,
    equity_start_source: str | None = None,
) -> dict[str, Any]:
    reasons: set[str] = set()
    warnings: set[str] = set()
    normalized_session = _session(session_date)
    if normalized_session is None:
        reasons.add("invalid_session_date")
    normalized_currency = str(currency or "").upper()
    if normalized_currency != "USD":
        reasons.add("multi_currency_or_unsupported_currency")
    start = _timestamp(window_start_at)
    end = _timestamp(window_end_at)
    generated = _timestamp(generated_at)
    as_of_normalized = _timestamp(as_of)
    captured = _timestamp(captured_at)
    account_read = _timestamp(account_read_at)
    if account_read_at is not None and account_read is None:
        reasons.add("account_read_at_invalid_or_naive")
    if start is None or end is None:
        reasons.add("window_timestamp_invalid_or_naive")
    elif start >= end:
        reasons.add("window_not_strictly_ordered")
    for name, value in (("generated_at", generated), ("as_of", as_of_normalized), ("captured_at", captured)):
        if value is None:
            reasons.add(f"{name}_invalid_or_naive")
    if as_of_normalized is not None and end is not None and as_of_normalized != end:
        warnings.add("as_of_differs_from_window_end")
    sources = {str(key): _timestamp(value) for key, value in sorted((source_timestamps or {}).items())}
    for key, value in sources.items():
        if value is None:
            reasons.add(f"source_timestamp_invalid:{key}")
    age_seconds: dict[str, float | None] = {}
    as_of_dt = datetime.fromisoformat(as_of_normalized.replace("Z", "+00:00")) if as_of_normalized else None
    for key, value in sources.items():
        if value is None or as_of_dt is None:
            age_seconds[key] = None
            continue
        source_dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        age = (as_of_dt - source_dt).total_seconds()
        if age < 0:
            reasons.add(f"source_timestamp_after_as_of:{key}")
        age_seconds[key] = round(age, 3)
    nums = {name: _number(value) for name, value in (("equity_start", equity_start), ("equity_end", equity_end), ("cash_start", cash_start), ("cash_end", cash_end), ("open_pl_start", open_pl_start), ("open_pl_end", open_pl_end))}
    for name, raw in (("equity_start", equity_start), ("equity_end", equity_end), ("cash_start", cash_start), ("cash_end", cash_end), ("open_pl_start", open_pl_start), ("open_pl_end", open_pl_end)):
        if raw is not None and nums[name] is None:
            reasons.add(f"{name}_invalid")
    delta_equity = round(nums["equity_end"] - nums["equity_start"], 10) if nums["equity_start"] is not None and nums["equity_end"] is not None else None
    delta_open = round(nums["open_pl_end"] - nums["open_pl_start"], 10) if nums["open_pl_start"] is not None and nums["open_pl_end"] is not None else None
    if descriptive_realized_pl is not None:
        descriptive_realized = _number(descriptive_realized_pl)
        warnings.add("realized_pl_descriptive_not_canonical")
    else:
        descriptive_realized = None
    gross, normalized_costs, net, cost_coverage = _cost_snapshot(gross_realized_pl, costs, reasons)
    flows, external_flows, flow_coverage = _flow_snapshot(external_flow_ledger, currency=normalized_currency, start=start, end=end, reasons=reasons)
    position_values, exposure_coverage, normalized_positions = _position_snapshot(positions, currency=normalized_currency, reasons=reasons)
    if exposure_samples is not None:
        samples = [(_number(item.get("gross_exposure")), _number(item.get("net_exposure"))) for item in exposure_samples]
        if len(samples) >= 2 and all(gross_value is not None and net_value is not None and gross_value >= 0 for gross_value, net_value in samples):
            exposure_coverage["average_status"] = "exact"
            exposure_coverage["gross_exposure_average"] = round(sum(float(item[0]) for item in samples) / len(samples), 10)
            exposure_coverage["net_exposure_average"] = round(sum(float(item[1]) for item in samples) / len(samples), 10)
        else:
            exposure_coverage["average_status"] = "unavailable"
            exposure_coverage["gross_exposure_average"] = None
            exposure_coverage["net_exposure_average"] = None
            if exposure_samples:
                reasons.add("exposure_sample_invalid")
    contribution_rows, contribution_coverage = _contributions(contributions, currency=normalized_currency, reasons=reasons)
    if open_orders:
        warnings.add("open_orders_excluded_from_eod_contributions")
    benchmark_payload = _benchmark(benchmark, start=start, end=end, warnings=warnings, reasons=reasons)
    flow_adjusted = round((delta_equity - external_flows) / nums["equity_start"], 10) if flow_coverage["status"] == "exact" and external_flows is not None and delta_equity is not None and nums["equity_start"] not in (None, 0) else None
    residual = round(delta_equity - external_flows - net - delta_open, 10) if delta_equity is not None and external_flows is not None and net is not None and delta_open is not None else None
    residual_status = "balanced" if residual is not None and abs(residual) <= 1e-8 else "nonzero" if residual is not None else "unavailable"
    if residual_status == "nonzero":
        warnings.add("accounting_residual_nonzero")
    if (session_count or 0) < 3 or not outcomes_matured:
        warnings.add("single_session_or_immature_outcomes_not_causal")
    cash_ratio = round(nums["cash_end"] / nums["equity_end"], 10) if nums["cash_end"] is not None and nums["equity_end"] not in (None, 0) else None
    # One canonical snapshot is scoped by session; account/window remain part
    # of the immutable payload and therefore conflicts, rather than parallel
    # canonical rows, are auditable.
    event_id = f"{EVENT_ID_PREFIX}{normalized_session}" if normalized_session else None
    structural_invalid = any(reason.startswith(("invalid_", "window_")) or reason.endswith("_invalid") or "_invalid:" in reason for reason in reasons)
    coverage = {
        "equity_coverage": _coverage("exact" if delta_equity is not None else "unavailable"),
        "flow_coverage": flow_coverage,
        "realized_gross_coverage": _coverage("exact" if gross is not None else "unavailable"),
        "net_realized_coverage": _coverage("exact" if net is not None else "unavailable"),
        "cost_coverage": cost_coverage,
        "open_pl_coverage": _coverage("exact" if delta_open is not None else "unavailable"),
        "exposure_coverage": exposure_coverage,
        "contribution_coverage": contribution_coverage,
        "benchmark_coverage": _coverage("exact" if benchmark_payload["comparable"] else "degraded"),
        "residual_coverage": _coverage(residual_status),
    }
    unavailable = sum(item.get("status") in {"unavailable", "degraded"} for item in coverage.values())
    status = "unavailable" if structural_invalid else "available" if unavailable == 0 else "partial"
    snapshot: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "session_date": normalized_session,
        "calendar": CALENDAR,
        "account_id": account_id or None,
        "currency": normalized_currency or None,
        "window_start_at": start,
        "window_end_at": end,
        "generated_at": generated,
        "as_of": as_of_normalized,
        "account_read_at": account_read,
        "equity_start_source": equity_start_source,
        "source_timestamps": sources,
        "freshness": {
            "status": "exact" if sources and all(value is not None for value in age_seconds.values()) and not any(reason.startswith("source_timestamp_after_as_of:") for reason in reasons) else "unavailable" if not sources else "partial",
            "age_seconds": age_seconds,
            "as_of": as_of_normalized,
        },
        "captured_at": captured,
        "equity_start": nums["equity_start"],
        "equity_end": nums["equity_end"],
        "delta_equity": delta_equity,
        "cash_start": nums["cash_start"],
        "cash_end": nums["cash_end"],
        "cash_ratio_end": cash_ratio,
        **position_values,
        "gross_exposure_average": exposure_coverage.get("gross_exposure_average"),
        "net_exposure_average": exposure_coverage.get("net_exposure_average"),
        "open_pl_start": nums["open_pl_start"],
        "open_pl_end": nums["open_pl_end"],
        "delta_open_pl": delta_open,
        "gross_realized_pl": gross,
        "descriptive_realized_pl": descriptive_realized,
        **normalized_costs,
        "net_realized_pl": net,
        "external_flow_ledger": flows,
        "external_cash_flows": external_flows,
        "flow_adjusted_return": flow_adjusted,
        "positions": normalized_positions,
        "contributions": contribution_rows,
        "open_order_count": len(open_orders) if open_orders is not None else None,
        "benchmark": benchmark_payload,
        "residual_amount": residual,
        "residual_status": residual_status,
        "session_count": session_count,
        "comparable_session_count": comparable_session_count,
        "outcomes_matured": outcomes_matured,
        "coverage": coverage,
        "interpretation": {
            "absolute_loss_status": "verified" if delta_equity is not None and delta_equity < 0 else "not_applicable",
            "cash_opportunity_status": "descriptive_only" if cash_ratio is not None and cash_ratio >= 0.8 and benchmark_payload["return"] is not None else "unavailable",
            "causality_status": "unavailable" if (session_count or 0) < 3 or not outcomes_matured else "descriptive",
        },
        "warnings": sorted(warnings),
        "reason_codes": sorted(reasons),
        "valid": not structural_invalid,
        "status": status,
        "received": 1,
        "unavailable": unavailable,
        "conflict": 0,
    }
    snapshot["result"] = {"received": 1, "valid": int(not structural_invalid), "unavailable": unavailable, "conflict": 0, "session_count": session_count, "comparable_session_count": comparable_session_count, **coverage, "warnings": snapshot["warnings"], "reason_codes": snapshot["reason_codes"]}
    snapshot["content_hash"] = content_hash(snapshot)
    return snapshot


def _portfolio_value(portfolio: Any, name: str) -> Any:
    return getattr(portfolio, name, None) if portfolio is not None else None


def _contributions_from_trade_attribution(
    attribution: Mapping[str, Any] | None,
) -> list[dict[str, Any]] | None:
    """Project only exact P-L51 allocations into the EOD contribution list.

    A sell-level realized amount is attributable to one lot only when the
    canonical operation has exactly one allocation.  For multi-lot exits the
    exact identities are still carried, but an amount is deliberately left
    null unless P-L51 supplied an allocation-level amount.  This prevents an
    invented split from becoming accounting evidence.
    """

    if not isinstance(attribution, Mapping):
        return None
    operations = attribution.get("operations")
    if not isinstance(operations, list):
        return None
    contributions: list[dict[str, Any]] = []
    for operation in operations:
        if not isinstance(operation, Mapping) or operation.get("status") != "attributed":
            continue
        allocations = operation.get("allocations")
        if not isinstance(allocations, list) or not allocations:
            continue
        operation_net = _number(operation.get("net_realized_pl"))
        single_allocation = len(allocations) == 1
        for allocation in allocations:
            if not isinstance(allocation, Mapping):
                continue
            buy_order_id = allocation.get("buy_broker_order_id")
            lot_identity = allocation.get("lot_identity") or allocation.get("lot_id")
            if not buy_order_id or not lot_identity:
                continue
            allocation_amount = _number(allocation.get("net_realized_pl"))
            if allocation_amount is None and single_allocation:
                allocation_amount = operation_net
            contributions.append(
                {
                    "broker_order_id": buy_order_id,
                    "lot_identity": lot_identity,
                    "amount": allocation_amount,
                    "currency": "USD",
                    "origin": "canonical_trade_attribution",
                }
            )
    return contributions or None


def build_from_postmarket_inputs(
    session_date: str,
    *,
    portfolio: Any = None,
    canonical_telemetry: Mapping[str, Any] | None = None,
    canonical_trade_attribution: Mapping[str, Any] | None = None,
    report: Mapping[str, Any] | None = None,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    """Build from PMR objects already in memory; no source is re-queried."""

    capture = captured_at or datetime.now(timezone.utc)
    capture = capture.replace(tzinfo=timezone.utc) if capture.tzinfo is None else capture.astimezone(timezone.utc)
    account_id = str(_portfolio_value(portfolio, "account_id") or "paper")
    currency = str(_portfolio_value(portfolio, "currency") or "USD").upper()
    equity = _portfolio_value(portfolio, "portfolio_value")
    cash = _portfolio_value(portfolio, "cash")
    positions = []
    open_pl = 0.0
    for position in _portfolio_value(portfolio, "positions") or []:
        value = _number(getattr(position, "market_value", None))
        pl = _number(getattr(position, "unrealized_pl", None))
        if pl is not None:
            open_pl += pl
        positions.append({"broker_order_id": None, "lot_identity": None, "side": getattr(position, "side", None), "market_value_start": None, "market_value_end": value, "currency": currency})
    metrics = (canonical_trade_attribution or {}).get("metrics") if isinstance(canonical_trade_attribution, Mapping) else None
    costs = None
    gross = None
    if isinstance(metrics, Mapping):
        gross = metrics.get("gross_realized_pl")
        costs = {name: metrics.get(name) for name in COST_FIELDS} if all(name in metrics for name in COST_FIELDS) else None
    contributions = _contributions_from_trade_attribution(canonical_trade_attribution)
    account_read_at = _timestamp(report.get("as_of")) if isinstance(report, Mapping) else None
    source_values = {
        "portfolio": account_read_at,
        "canonical_operation_telemetry": _timestamp((canonical_telemetry or {}).get("captured_at"))
        if isinstance(canonical_telemetry, Mapping)
        else None,
        "canonical_trade_attribution": _timestamp((canonical_trade_attribution or {}).get("captured_at"))
        if isinstance(canonical_trade_attribution, Mapping)
        else None,
    }
    source_values = {key: value for key, value in source_values.items() if value is not None}
    measurement_candidates = list(source_values.values()) + [capture.isoformat().replace("+00:00", "Z")]
    as_of = max(measurement_candidates, key=lambda value: _timestamp(value) or "")
    window_start = report.get("window_start_at") if isinstance(report, Mapping) else None
    # The PMR has one authorized observation time but no second EOD snapshot.
    # Preserve that limitation instead of manufacturing an opening value.
    return build_canonical_eod_account_snapshot(
        session_date=session_date,
        account_id=account_id,
        currency=currency,
        window_start_at=window_start,
        window_end_at=as_of,
        generated_at=as_of,
        as_of=as_of,
        captured_at=capture,
        equity_start=_portfolio_value(portfolio, "previous_close_equity"),
        equity_start_source=("account.previous_close_equity" if _portfolio_value(portfolio, "previous_close_equity") is not None else None),
        equity_end=equity,
        cash_start=None,
        cash_end=cash,
        open_pl_start=None,
        open_pl_end=open_pl,
        gross_realized_pl=gross,
        costs=costs,
        external_flow_ledger=None,
        positions=None if not positions or any(item["market_value_end"] is None for item in positions) else positions,
        contributions=contributions,
        open_orders=[{ "broker_order_id": getattr(item, "order_id", None) } for item in (_portfolio_value(portfolio, "open_orders") or [])],
        benchmark=(report or {}).get("benchmark") if isinstance(report, Mapping) else None,
        source_timestamps=source_values,
        account_read_at=account_read_at,
        session_count=1,
        comparable_session_count=0,
        outcomes_matured=False,
    )


def unavailable_canonical_eod_account_snapshot(session_date: str, *, warning: str | None = None, captured_at: datetime | None = None) -> dict[str, Any]:
    capture = captured_at or datetime.now(timezone.utc)
    iso = capture.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    result = build_canonical_eod_account_snapshot(session_date=session_date, account_id="paper", currency="USD", window_start_at=iso, window_end_at=iso, generated_at=iso, as_of=iso, captured_at=iso)
    result["status"] = "unavailable"
    if warning:
        result["warnings"] = sorted(set(result["warnings"]) | {warning})
        result["reason_codes"] = sorted(set(result["reason_codes"]) | {"producer_failed"})
        result["result"]["warnings"] = result["warnings"]
        result["result"]["reason_codes"] = result["reason_codes"]
    result["content_hash"] = content_hash(result)
    return result


def persist_canonical_eod_account_snapshot(store: Any, snapshot: Mapping[str, Any]) -> dict[str, Any]:
    event_id = str(snapshot.get("event_id") or "")
    if not event_id:
        return {"status": "unavailable", "reason": "missing_event_id"}
    return store.record_canonical_eod_account_snapshot(dict(snapshot), event_id=event_id)


def read_canonical_eod_account_snapshot(store: Any, session_date: str) -> dict[str, Any]:
    event = store.canonical_eod_account_snapshot_event(session_date)
    if event is None:
        return {"schema_version": SCHEMA_VERSION, "session_date": session_date, "status": "collecting", "denominators": None, "coverage": None, "metrics": None, "content_hash": None, "warnings": []}
    payload = dict(event.get("payload") or {})
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("content_hash") != content_hash(payload):
        return {"schema_version": SCHEMA_VERSION, "session_date": session_date, "status": "legacy_without_canonical_eod_account_snapshot", "coverage": None, "content_hash": None, "warnings": ["invalid_canonical_event"]}
    return payload


def canonical_eod_account_snapshot_digest(store: Any, session_date: str | None = None) -> dict[str, Any]:
    if session_date:
        payload = read_canonical_eod_account_snapshot(store, session_date)
        conflicts = store.canonical_eod_account_snapshot_conflicts(session_date)
        return {"status": "conflict" if conflicts and payload.get("status") == "collecting" else payload.get("status", "collecting"), "session_date": session_date, "coverage": payload.get("coverage"), "result": payload.get("result"), "content_hash": payload.get("content_hash"), "captured_at": payload.get("captured_at"), "conflict_events": len(conflicts)}
    events = [item for item in store.agent_events(event_type_prefix=EVENT_TYPE, limit=50000) if item.get("event_type") == EVENT_TYPE and str(item.get("event_id") or "").startswith(EVENT_ID_PREFIX)]
    conflicts = [item for item in store.agent_events(event_type_prefix=f"{EVENT_TYPE}_conflict", limit=50000)]
    if not events:
        return {"status": "conflict" if conflicts else "collecting", "session_date": None, "coverage": None, "result": None, "canonical_events": 0, "conflict_events": len(conflicts)}
    latest = sorted(events, key=lambda item: str(item.get("created_at") or ""))[-1]
    payload = latest.get("payload") or {}
    return {"status": payload.get("status", "partial"), "session_date": payload.get("session_date"), "coverage": payload.get("coverage"), "result": payload.get("result"), "content_hash": payload.get("content_hash"), "captured_at": payload.get("captured_at"), "canonical_events": len(events), "conflict_events": len(conflicts)}


# Alias used by the P-L52B-T contract fixtures when they are moved to the
# productive API.
build_eod_snapshot = build_canonical_eod_account_snapshot
