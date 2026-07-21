"""P-L52B-T: contrato de snapshot EOD contable y benchmark comparable.

Este modulo es deliberadamente autocontenido. Caracteriza el contrato sin
modificar ``src``, Store, agent_events, performance_daily, UI ni wiring.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import pytest

SCHEMA_VERSION = "p-l52b.canonical-eod-account-snapshot.v1"
CALENDAR = "XNYS"
COST_FIELDS = (
    "commissions",
    "regulatory_fees",
    "spread_cost",
    "slippage_cost",
    "other_costs",
)
UTC = timezone.utc
WINDOW_START = "2026-07-21T13:30:00Z"
WINDOW_END = "2026-07-21T20:00:00Z"
GENERATED_AT = "2026-07-21T20:01:00Z"
AS_OF = "2026-07-21T20:00:00Z"
CAPTURED_AT = "2026-07-21T20:02:00Z"


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
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _session(value: Any) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None
    return value


def _stable_hash(value: dict[str, Any]) -> str:
    content = copy.deepcopy(value)
    content.pop("captured_at", None)
    content.pop("content_hash", None)
    encoded = json.dumps(content, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _unique_sorted(values: set[str]) -> list[str]:
    return sorted(values)


def _sorted_rows(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    return sorted((copy.deepcopy(row) for row in rows), key=lambda row: tuple(str(row.get(key) or "") for key in keys))


def _benchmark_snapshot(
    benchmark: dict[str, Any] | None,
    *,
    window_start_at: str | None,
    window_end_at: str | None,
    warnings: set[str],
    reasons: set[str],
) -> dict[str, Any]:
    if benchmark is None:
        reasons.add("benchmark_missing")
        return {
            "symbol": "SPY",
            "start_price": None,
            "end_price": None,
            "start_at": None,
            "end_at": None,
            "price_basis": None,
            "quality": "unavailable",
            "return": None,
            "comparison_status": "unavailable",
            "comparable": False,
            "reason_codes": ["benchmark_missing"],
        }

    local_reasons: set[str] = set()
    symbol = str(benchmark.get("symbol") or "").upper() or None
    if symbol != "SPY":
        local_reasons.add("benchmark_symbol_mismatch")
    benchmark_start = _timestamp(benchmark.get("window_start_at"))
    benchmark_end = _timestamp(benchmark.get("window_end_at"))
    start_at = _timestamp(benchmark.get("start_at"))
    end_at = _timestamp(benchmark.get("end_at"))
    if benchmark_start != window_start_at or benchmark_end != window_end_at:
        local_reasons.add("benchmark_window_mismatch")
    if start_at != window_start_at or end_at != window_end_at:
        local_reasons.add("benchmark_timestamp_mismatch")
    start_price = _number(benchmark.get("start_price"))
    end_price = _number(benchmark.get("end_price"))
    if start_price is None or end_price is None or start_price <= 0 or end_price <= 0:
        local_reasons.add("benchmark_price_missing_or_invalid")
    price_basis = benchmark.get("price_basis")
    start_basis = benchmark.get("start_price_basis", price_basis)
    end_basis = benchmark.get("end_price_basis", price_basis)
    if not price_basis or start_basis != end_basis or price_basis not in {"unadjusted_close", "adjusted_close"}:
        local_reasons.add("benchmark_price_basis_unknown_or_mismatched")
    quality = str(benchmark.get("quality") or "unknown").lower()
    if quality not in {"exact", "verified"}:
        local_reasons.add(f"benchmark_quality_{quality}")
    if benchmark.get("as_of") is not None and _timestamp(benchmark.get("as_of")) != window_end_at:
        local_reasons.add("benchmark_as_of_mismatch")

    comparable = not local_reasons
    if not comparable:
        warnings.add("benchmark_comparison_degraded")
        reasons.update(local_reasons)
    benchmark_return = None
    if start_price is not None and end_price is not None and start_price > 0:
        benchmark_return = round((end_price - start_price) / start_price, 10)
    return {
        "symbol": symbol,
        "start_price": start_price,
        "end_price": end_price,
        "start_at": start_at,
        "end_at": end_at,
        "price_basis": price_basis,
        "quality": quality,
        "return": benchmark_return,
        "comparison_status": "comparable" if comparable else "degraded",
        "comparable": comparable,
        "reason_codes": sorted(local_reasons),
    }


def _cost_snapshot(
    gross_realized_pl: float | None,
    costs: dict[str, Any] | None,
    *,
    reasons: set[str],
) -> tuple[dict[str, float | None], float | None, dict[str, Any]]:
    gross = _number(gross_realized_pl)
    normalized = {key: _number((costs or {}).get(key)) for key in COST_FIELDS}
    if gross_realized_pl is not None and gross is None:
        reasons.add("gross_realized_pl_invalid")
    missing = [key for key, value in normalized.items() if value is None]
    if costs is None:
        status = "unavailable"
        reasons.add("costs_missing")
    elif missing:
        status = "partial"
        reasons.add("costs_partial")
    else:
        status = "exact"
    net = None
    if gross is not None and status == "exact":
        net = round(gross - sum(normalized.values()), 10)
    return normalized, net, {
        "status": status,
        "required_fields": list(COST_FIELDS),
        "missing_fields": missing,
    }


def _flow_snapshot(
    ledger: list[dict[str, Any]] | None,
    *,
    currency: str,
    window_start_at: str | None,
    window_end_at: str | None,
    reasons: set[str],
) -> tuple[list[dict[str, Any]] | None, float | None, dict[str, Any], float | None]:
    if ledger is None:
        reasons.add("external_flow_ledger_missing")
        return None, None, {"status": "unavailable", "count": None}, None
    normalized: list[dict[str, Any]] = []
    local_reasons: set[str] = set()
    for row in ledger:
        amount = _number(row.get("amount"))
        occurred_at = _timestamp(row.get("occurred_at"))
        if not row.get("flow_id") or amount is None or occurred_at is None:
            local_reasons.add("flow_identity_or_amount_invalid")
        if occurred_at is not None and (occurred_at < str(window_start_at) or occurred_at > str(window_end_at)):
            local_reasons.add("flow_outside_window")
        if str(row.get("currency") or "").upper() != currency:
            local_reasons.add("flow_currency_mismatch")
        normalized.append(
            {
                "flow_id": row.get("flow_id"),
                "amount": amount,
                "currency": str(row.get("currency") or "").upper() or None,
                "occurred_at": occurred_at,
                "kind": row.get("kind"),
            }
        )
    if local_reasons:
        reasons.update(local_reasons)
        status = "unavailable"
        total = None
    else:
        status = "exact"
        total = round(sum(float(row["amount"]) for row in normalized), 10)
    normalized = _sorted_rows(normalized, ("occurred_at", "flow_id"))
    return normalized, total, {"status": status, "count": len(normalized)}, total


def _position_snapshot(
    positions: list[dict[str, Any]] | None,
    *,
    currency: str,
    reasons: set[str],
) -> tuple[dict[str, float | None], dict[str, Any], list[dict[str, Any]] | None]:
    if positions is None:
        reasons.add("positions_missing")
        return (
            {
                "position_market_value_start": None,
                "position_market_value_end": None,
                "gross_exposure_start": None,
                "gross_exposure_end": None,
                "net_exposure_start": None,
                "net_exposure_end": None,
            },
            {"status": "unavailable", "count": None, "average_status": "unavailable", "gross_exposure_average": None},
            None,
        )
    normalized: list[dict[str, Any]] = []
    local_reasons: set[str] = set()
    for row in positions:
        side = str(row.get("side") or "").lower()
        start = _number(row.get("market_value_start"))
        end = _number(row.get("market_value_end"))
        if side not in {"long", "short"}:
            local_reasons.add("position_side_invalid")
        if start is None or end is None:
            local_reasons.add("position_market_value_missing")
        if str(row.get("currency") or currency).upper() != currency:
            local_reasons.add("position_currency_mismatch")
        sign = 1.0 if side == "long" else -1.0 if side == "short" else 0.0
        normalized.append(
            {
                "broker_order_id": row.get("broker_order_id"),
                "lot_identity": row.get("lot_identity"),
                "side": side or None,
                "market_value_start": start,
                "market_value_end": end,
                "signed_market_value_start": round(sign * start, 10) if start is not None else None,
                "signed_market_value_end": round(sign * end, 10) if end is not None else None,
                "currency": str(row.get("currency") or currency).upper(),
            }
        )
    if local_reasons:
        reasons.update(local_reasons)
        values = {
            "position_market_value_start": None,
            "position_market_value_end": None,
            "gross_exposure_start": None,
            "gross_exposure_end": None,
            "net_exposure_start": None,
            "net_exposure_end": None,
        }
        status = "unavailable"
    else:
        values = {
            "position_market_value_start": round(sum(row["signed_market_value_start"] for row in normalized), 10),
            "position_market_value_end": round(sum(row["signed_market_value_end"] for row in normalized), 10),
            "gross_exposure_start": round(sum(abs(row["market_value_start"]) for row in normalized), 10),
            "gross_exposure_end": round(sum(abs(row["market_value_end"]) for row in normalized), 10),
            "net_exposure_start": round(sum(row["signed_market_value_start"] for row in normalized), 10),
            "net_exposure_end": round(sum(row["signed_market_value_end"] for row in normalized), 10),
        }
        status = "exact"
    return values, {"status": status, "count": len(normalized), "average_status": "unavailable", "gross_exposure_average": None}, _sorted_rows(normalized, ("broker_order_id", "lot_identity"))


def _contribution_snapshot(
    contributions: list[dict[str, Any]] | None,
    *,
    currency: str,
    reasons: set[str],
) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    if contributions is None:
        reasons.add("contributions_missing")
        return None, {"status": "unavailable", "count": None}
    normalized = []
    local_reasons: set[str] = set()
    for row in contributions:
        amount = _number(row.get("amount"))
        if not row.get("broker_order_id") or not row.get("lot_identity"):
            local_reasons.add("contribution_identity_missing")
        if amount is None:
            local_reasons.add("contribution_amount_missing")
        if str(row.get("currency") or currency).upper() != currency:
            local_reasons.add("contribution_currency_mismatch")
        normalized.append(
            {
                "broker_order_id": row.get("broker_order_id"),
                "lot_identity": row.get("lot_identity"),
                "amount": amount,
                "currency": str(row.get("currency") or currency).upper(),
                "origin": row.get("origin"),
            }
        )
    if local_reasons:
        reasons.update(local_reasons)
    return _sorted_rows(normalized, ("broker_order_id", "lot_identity")), {
        "status": "exact" if not local_reasons else "unavailable",
        "count": len(normalized),
    }


def build_eod_snapshot(
    *,
    session_date: str,
    account_id: str,
    currency: str,
    window_start_at: Any = WINDOW_START,
    window_end_at: Any = WINDOW_END,
    generated_at: Any = GENERATED_AT,
    as_of: Any = AS_OF,
    captured_at: Any = CAPTURED_AT,
    equity_start: Any = 10_000.0,
    equity_end: Any = 10_000.0,
    cash_start: Any = 8_000.0,
    cash_end: Any = 8_000.0,
    open_pl_start: Any = 0.0,
    open_pl_end: Any = 0.0,
    gross_realized_pl: Any = 0.0,
    costs: dict[str, Any] | None = None,
    external_flow_ledger: list[dict[str, Any]] | None = None,
    positions: list[dict[str, Any]] | None = None,
    exposure_samples: list[dict[str, Any]] | None = None,
    contributions: list[dict[str, Any]] | None = None,
    open_orders: list[dict[str, Any]] | None = None,
    benchmark: dict[str, Any] | None = None,
    source_timestamps: dict[str, Any] | None = None,
    session_count: int = 1,
    comparable_session_count: int = 1,
    outcomes_matured: bool = False,
    descriptive_realized_pl: Any = None,
) -> dict[str, Any]:
    reasons: set[str] = set()
    warnings: set[str] = set()
    normalized_session = _session(session_date)
    if normalized_session is None:
        reasons.add("invalid_session_date")
    normalized_currency = str(currency or "").upper()
    if not normalized_currency or normalized_currency != "USD":
        reasons.add("multi_currency_or_unsupported_currency")
    start_at = _timestamp(window_start_at)
    end_at = _timestamp(window_end_at)
    normalized_generated = _timestamp(generated_at)
    normalized_as_of = _timestamp(as_of)
    normalized_captured = _timestamp(captured_at)
    if start_at is None or end_at is None:
        reasons.add("window_timestamp_invalid_or_naive")
    elif start_at >= end_at:
        reasons.add("window_not_strictly_ordered")
    for label, value in (("generated_at", normalized_generated), ("as_of", normalized_as_of), ("captured_at", normalized_captured)):
        if value is None:
            reasons.add(f"{label}_invalid_or_naive")
    if normalized_as_of is not None and end_at is not None and normalized_as_of != end_at:
        warnings.add("as_of_differs_from_window_end")
    normalized_sources: dict[str, str | None] = {}
    for label, value in sorted((source_timestamps or {}).items()):
        normalized_sources[label] = _timestamp(value)
        if normalized_sources[label] is None:
            reasons.add(f"source_timestamp_invalid:{label}")

    numeric = {
        "equity_start": _number(equity_start),
        "equity_end": _number(equity_end),
        "cash_start": _number(cash_start),
        "cash_end": _number(cash_end),
        "open_pl_start": _number(open_pl_start),
        "open_pl_end": _number(open_pl_end),
    }
    for label, raw in (("equity_start", equity_start), ("equity_end", equity_end), ("cash_start", cash_start), ("cash_end", cash_end), ("open_pl_start", open_pl_start), ("open_pl_end", open_pl_end)):
        if raw is not None and numeric[label] is None:
            reasons.add(f"{label}_invalid")
    delta_equity = None
    delta_open_pl = None
    if numeric["equity_start"] is not None and numeric["equity_end"] is not None:
        delta_equity = round(numeric["equity_end"] - numeric["equity_start"], 10)
    if numeric["open_pl_start"] is not None and numeric["open_pl_end"] is not None:
        delta_open_pl = round(numeric["open_pl_end"] - numeric["open_pl_start"], 10)
    if descriptive_realized_pl is not None:
        descriptive_realized = _number(descriptive_realized_pl)
        warnings.add("realized_pl_descriptive_not_canonical")
    else:
        descriptive_realized = None

    normalized_costs, net_realized_pl, cost_coverage = _cost_snapshot(gross_realized_pl, costs, reasons=reasons)
    flow_ledger, external_cash_flows, flow_coverage, _ = _flow_snapshot(
        external_flow_ledger,
        currency=normalized_currency,
        window_start_at=start_at,
        window_end_at=end_at,
        reasons=reasons,
    )
    position_values, exposure_coverage, normalized_positions = _position_snapshot(positions, currency=normalized_currency, reasons=reasons)
    if exposure_samples is not None:
        sample_values: list[tuple[float, float]] = []
        for sample in exposure_samples:
            gross = _number(sample.get("gross_exposure"))
            net = _number(sample.get("net_exposure"))
            if gross is None or net is None or gross < 0:
                reasons.add("exposure_sample_invalid")
            else:
                sample_values.append((gross, net))
        if len(sample_values) >= 2 and not any(reason == "exposure_sample_invalid" for reason in reasons):
            exposure_coverage["average_status"] = "exact"
            exposure_coverage["gross_exposure_average"] = round(sum(item[0] for item in sample_values) / len(sample_values), 10)
            exposure_coverage["net_exposure_average"] = round(sum(item[1] for item in sample_values) / len(sample_values), 10)
        else:
            exposure_coverage["average_status"] = "unavailable"
            exposure_coverage["gross_exposure_average"] = None
            exposure_coverage["net_exposure_average"] = None
    contributions_payload, contribution_coverage = _contribution_snapshot(contributions, currency=normalized_currency, reasons=reasons)
    if open_orders:
        warnings.add("open_orders_excluded_from_eod_contributions")
    benchmark_payload = _benchmark_snapshot(benchmark, window_start_at=start_at, window_end_at=end_at, warnings=warnings, reasons=reasons)

    flow_adjusted_return = None
    if flow_coverage["status"] == "exact" and external_cash_flows is not None and delta_equity is not None and numeric["equity_start"] not in (None, 0):
        flow_adjusted_return = round((delta_equity - external_cash_flows) / numeric["equity_start"], 10)
    residual_amount = None
    residual_status = "unavailable"
    if delta_equity is not None and external_cash_flows is not None and net_realized_pl is not None and delta_open_pl is not None:
        residual_amount = round(delta_equity - external_cash_flows - net_realized_pl - delta_open_pl, 10)
        residual_status = "balanced" if abs(residual_amount) <= 1e-8 else "nonzero"
        if residual_status == "nonzero":
            warnings.add("accounting_residual_nonzero")
    if session_count < 3 or not outcomes_matured:
        warnings.add("single_session_or_immature_outcomes_not_causal")
    if numeric["equity_end"] not in (None, 0) and numeric["cash_end"] is not None:
        cash_ratio_end = round(numeric["cash_end"] / numeric["equity_end"], 10)
    else:
        cash_ratio_end = None

    event_id = None
    if normalized_session and account_id and normalized_currency and start_at and end_at:
        event_id = f"canonical_eod_account_snapshot:{normalized_session}:{account_id}:{normalized_currency}:{start_at}:{end_at}"
    structural_invalid = any(
        reason.startswith(("invalid_", "window_"))
        or reason.endswith("_invalid")
        or "_invalid:" in reason
        for reason in reasons
    )
    snapshot: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "session_date": normalized_session,
        "calendar": CALENDAR,
        "account_id": account_id or None,
        "currency": normalized_currency or None,
        "window_start_at": start_at,
        "window_end_at": end_at,
        "generated_at": normalized_generated,
        "as_of": normalized_as_of,
        "source_timestamps": normalized_sources,
        "captured_at": normalized_captured,
        "equity_start": numeric["equity_start"],
        "equity_end": numeric["equity_end"],
        "delta_equity": delta_equity,
        "cash_start": numeric["cash_start"],
        "cash_end": numeric["cash_end"],
        "cash_ratio_end": cash_ratio_end,
        **position_values,
        "gross_exposure_average": exposure_coverage.get("gross_exposure_average"),
        "net_exposure_average": exposure_coverage.get("net_exposure_average"),
        "open_pl_start": numeric["open_pl_start"],
        "open_pl_end": numeric["open_pl_end"],
        "delta_open_pl": delta_open_pl,
        "gross_realized_pl": _number(gross_realized_pl),
        "descriptive_realized_pl": descriptive_realized,
        **normalized_costs,
        "net_realized_pl": net_realized_pl,
        "external_cash_flow_ledger": flow_ledger,
        "external_cash_flows": external_cash_flows,
        "flow_adjusted_return": flow_adjusted_return,
        "positions": normalized_positions,
        "contributions": contributions_payload,
        "open_order_count": len(open_orders) if open_orders is not None else None,
        "benchmark": benchmark_payload,
        "residual_amount": residual_amount,
        "residual_status": residual_status,
        "session_count": session_count,
        "comparable_session_count": comparable_session_count,
        "outcomes_matured": outcomes_matured,
        "coverage": {
            "equity_coverage": {"status": "exact" if delta_equity is not None else "unavailable"},
            "flow_coverage": flow_coverage,
            "realized_gross_coverage": {"status": "exact" if _number(gross_realized_pl) is not None else "unavailable"},
            "net_realized_coverage": {"status": "exact" if net_realized_pl is not None else "unavailable"},
            "cost_coverage": cost_coverage,
            "open_pl_coverage": {"status": "exact" if delta_open_pl is not None else "unavailable"},
            "exposure_coverage": exposure_coverage,
            "contribution_coverage": contribution_coverage,
            "benchmark_coverage": {"status": "exact" if benchmark_payload["comparable"] else "degraded"},
            "residual_coverage": {"status": residual_status},
        },
        "interpretation": {
            "absolute_loss_status": "verified" if delta_equity is not None and delta_equity < 0 else "not_applicable",
            "cash_opportunity_status": "descriptive_only" if cash_ratio_end is not None and cash_ratio_end >= 0.8 and benchmark_payload["return"] is not None else "unavailable",
            "causality_status": "unavailable" if session_count < 3 or not outcomes_matured else "descriptive",
        },
        "warnings": _unique_sorted(warnings),
        "reason_codes": _unique_sorted(reasons),
        "valid": not structural_invalid,
    }
    snapshot["content_hash"] = _stable_hash(snapshot)
    return snapshot


def record_snapshot_event(events: dict[str, dict[str, Any]], snapshot: dict[str, Any]) -> dict[str, Any]:
    event_id = snapshot.get("event_id")
    if not event_id:
        return {"status": "unavailable", "reason": "missing_event_id"}
    existing = events.get(event_id)
    if existing is None:
        events[event_id] = copy.deepcopy(snapshot)
        return {"status": "inserted", "event_id": event_id}
    if existing.get("content_hash") == snapshot.get("content_hash"):
        return {"status": "idempotent", "event_id": event_id}
    return {
        "status": "conflict",
        "event_id": event_id,
        "original_hash": existing.get("content_hash"),
        "incoming_hash": snapshot.get("content_hash"),
    }


def summarize_windows(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    frame = pd.DataFrame(
        [
            {
                "session_date": snapshot.get("session_date"),
                "equity_status": snapshot.get("coverage", {}).get("equity_coverage", {}).get("status"),
                "benchmark_comparable": snapshot.get("benchmark", {}).get("comparable") is True,
            }
            for snapshot in snapshots
        ]
    )
    if frame.empty:
        return {"session_count": 0, "comparable_session_count": 0, "equity_coverage": 0}
    return {
        "session_count": int(frame["session_date"].nunique(dropna=True)),
        "comparable_session_count": int(frame.loc[frame["benchmark_comparable"], "session_date"].nunique(dropna=True)),
        "equity_coverage": int((frame["equity_status"] == "exact").sum()),
    }


def _costs() -> dict[str, float]:
    return {key: 1.0 for key in COST_FIELDS}


def _long_position() -> dict[str, Any]:
    return {
        "broker_order_id": "buy-1",
        "lot_identity": "lot-1",
        "side": "long",
        "market_value_start": 1_000.0,
        "market_value_end": 1_010.0,
        "currency": "USD",
    }


def _benchmark(**changes: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "symbol": "SPY",
        "window_start_at": WINDOW_START,
        "window_end_at": WINDOW_END,
        "start_at": WINDOW_START,
        "end_at": WINDOW_END,
        "start_price": 500.0,
        "end_price": 505.0,
        "price_basis": "unadjusted_close",
        "quality": "exact",
        "as_of": WINDOW_END,
    }
    value.update(changes)
    return value


def _fully_reconciled(**changes: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "session_date": "2026-07-21",
        "account_id": "paper-account",
        "currency": "USD",
        "external_flow_ledger": [],
        "costs": _costs(),
        "positions": [_long_position()],
        "contributions": [{"broker_order_id": "buy-1", "lot_identity": "lot-1", "amount": 10.0}],
        "benchmark": _benchmark(),
    }
    args.update(changes)
    return build_eod_snapshot(**args)


def test_contract_full_reconciled_equation_and_serializable_result() -> None:
    snapshot = _fully_reconciled(equity_start=10_000.0, equity_end=10_004.0, open_pl_start=0.0, open_pl_end=3.0, gross_realized_pl=5.0)
    assert snapshot["schema_version"] == SCHEMA_VERSION
    assert snapshot["event_id"].startswith("canonical_eod_account_snapshot:2026-07-21")
    assert snapshot["delta_equity"] == 4.0
    assert snapshot["net_realized_pl"] == 0.0
    assert snapshot["delta_open_pl"] == 3.0
    assert snapshot["external_cash_flows"] == 0.0
    assert snapshot["residual_amount"] == 1.0
    assert snapshot["residual_status"] == "nonzero"
    assert snapshot["coverage"]["cost_coverage"]["status"] == "exact"
    json.dumps(snapshot, allow_nan=False)


def test_deposit_and_withdrawal_are_exact_flows_and_return_adjusted() -> None:
    snapshot = _fully_reconciled(
        equity_start=1_000.0,
        equity_end=1_100.0,
        external_flow_ledger=[
            {"flow_id": "deposit-1", "amount": 200.0, "currency": "USD", "occurred_at": WINDOW_START, "kind": "deposit"},
            {"flow_id": "withdraw-1", "amount": -100.0, "currency": "USD", "occurred_at": WINDOW_END, "kind": "withdrawal"},
        ],
    )
    assert snapshot["external_cash_flows"] == 100.0
    assert snapshot["flow_adjusted_return"] == pytest.approx(0.0)
    assert snapshot["coverage"]["flow_coverage"]["status"] == "exact"


def test_missing_flow_ledger_is_null_not_zero_and_blocks_neutral_return() -> None:
    snapshot = _fully_reconciled(external_flow_ledger=None)
    assert snapshot["external_cash_flows"] is None
    assert snapshot["flow_adjusted_return"] is None
    assert snapshot["residual_amount"] is None
    assert "external_flow_ledger_missing" in snapshot["reason_codes"]


def test_partial_costs_keep_net_and_residual_unavailable() -> None:
    partial = _costs()
    partial.pop("slippage_cost")
    snapshot = _fully_reconciled(costs=partial)
    assert snapshot["gross_realized_pl"] == 0.0
    assert snapshot["net_realized_pl"] is None
    assert snapshot["residual_amount"] is None
    assert snapshot["coverage"]["cost_coverage"]["status"] == "partial"


def test_open_pl_and_canonical_realized_pl_explain_equity_without_trade_history() -> None:
    snapshot = _fully_reconciled(
        equity_start=1_000.0,
        equity_end=1_030.0,
        open_pl_start=10.0,
        open_pl_end=25.0,
        gross_realized_pl=15.0,
        costs={key: 0.0 for key in COST_FIELDS},
    )
    assert snapshot["delta_equity"] == 30.0
    assert snapshot["delta_open_pl"] == 15.0
    assert snapshot["net_realized_pl"] == 15.0
    assert snapshot["residual_amount"] == 0.0
    assert snapshot["residual_status"] == "balanced"
    assert "trade_history.total_pl" not in snapshot


def test_nonzero_residual_is_explicit_warning_not_silently_zero() -> None:
    snapshot = _fully_reconciled(
        equity_start=1_000.0,
        equity_end=1_100.0,
        open_pl_start=0.0,
        open_pl_end=0.0,
        gross_realized_pl=100.0,
        costs={key: 0.0 for key in COST_FIELDS},
    )
    assert snapshot["residual_amount"] == 0.0
    assert snapshot["residual_status"] == "balanced"

    residual = _fully_reconciled(
        equity_start=1_000.0,
        equity_end=1_110.0,
        open_pl_start=0.0,
        open_pl_end=0.0,
        gross_realized_pl=100.0,
        costs={key: 0.0 for key in COST_FIELDS},
    )
    assert residual["residual_amount"] == 10.0
    assert residual["residual_status"] == "nonzero"
    assert "accounting_residual_nonzero" in residual["warnings"]


def test_benchmark_comparable_requires_same_window_timestamps_basis_and_quality() -> None:
    snapshot = _fully_reconciled()
    benchmark = snapshot["benchmark"]
    assert benchmark["symbol"] == "SPY"
    assert benchmark["comparison_status"] == "comparable"
    assert benchmark["return"] == pytest.approx(0.01)
    assert snapshot["coverage"]["benchmark_coverage"]["status"] == "exact"

    unknown_basis = _fully_reconciled(benchmark=_benchmark(price_basis=None))
    stale = _fully_reconciled(benchmark=_benchmark(end_at="2026-07-20T20:00:00Z", window_end_at="2026-07-20T20:00:00Z"))
    mismatched = _fully_reconciled(benchmark=_benchmark(window_start_at="2026-07-20T13:30:00Z"))
    for degraded in (unknown_basis, stale, mismatched):
        assert degraded["benchmark"]["comparable"] is False
        assert degraded["coverage"]["benchmark_coverage"]["status"] == "degraded"
        assert degraded["interpretation"]["causality_status"] == "unavailable"


def test_exposure_eod_only_does_not_invent_average_and_long_short_net_is_signed() -> None:
    eod = _fully_reconciled(exposure_samples=None)
    assert eod["gross_exposure_start"] == 1_000.0
    assert eod["gross_exposure_average"] is None
    assert eod["coverage"]["exposure_coverage"]["average_status"] == "unavailable"

    positions = [
        _long_position(),
        {"broker_order_id": "sell-1", "lot_identity": "lot-short", "side": "short", "market_value_start": 400.0, "market_value_end": 350.0, "currency": "USD"},
    ]
    averaged = _fully_reconciled(
        positions=positions,
        exposure_samples=[{"gross_exposure": 1_400.0, "net_exposure": 600.0}, {"gross_exposure": 1_300.0, "net_exposure": 660.0}],
    )
    assert averaged["gross_exposure_start"] == 1_400.0
    assert averaged["net_exposure_start"] == 600.0
    assert averaged["gross_exposure_average"] == 1_350.0
    assert averaged["net_exposure_average"] == 630.0

    invalid = _fully_reconciled(positions=[{**_long_position(), "side": "unknown"}])
    assert invalid["gross_exposure_start"] is None
    assert "position_side_invalid" in invalid["reason_codes"]


def test_open_orders_are_separate_and_contribution_requires_exact_ids() -> None:
    snapshot = _fully_reconciled(open_orders=[{"broker_order_id": "pending-1", "side": "BUY"}])
    assert snapshot["open_order_count"] == 1
    assert snapshot["coverage"]["contribution_coverage"]["status"] == "exact"
    assert "open_orders_excluded_from_eod_contributions" in snapshot["warnings"]

    unavailable = _fully_reconciled(contributions=[{"broker_order_id": None, "lot_identity": "lot-1", "amount": 10.0}])
    assert unavailable["coverage"]["contribution_coverage"]["status"] == "unavailable"
    assert "contribution_identity_missing" in unavailable["reason_codes"]


def test_multi_currency_without_exact_fx_is_unavailable() -> None:
    snapshot = _fully_reconciled(currency="EUR", positions=[{**_long_position(), "currency": "EUR"}])
    assert snapshot["valid"] is True
    assert "multi_currency_or_unsupported_currency" in snapshot["reason_codes"]
    assert snapshot["currency"] == "EUR"
    assert snapshot["coverage"]["flow_coverage"]["status"] == "exact"


def test_hash_excludes_captured_at_and_reordering_is_idempotent_but_content_conflict_is_separate() -> None:
    contributions = [
        {"broker_order_id": "buy-2", "lot_identity": "lot-2", "amount": 20.0},
        {"broker_order_id": "buy-1", "lot_identity": "lot-1", "amount": 10.0},
    ]
    first = _fully_reconciled(contributions=contributions, captured_at="2026-07-21T20:02:00Z")
    repeated = _fully_reconciled(contributions=list(reversed(contributions)), captured_at="2026-07-21T20:03:00Z")
    assert first["content_hash"] == repeated["content_hash"]
    events: dict[str, dict[str, Any]] = {}
    assert record_snapshot_event(events, first)["status"] == "inserted"
    assert record_snapshot_event(events, repeated)["status"] == "idempotent"
    changed = copy.deepcopy(first)
    changed["equity_end"] = 9_999.0
    changed["delta_equity"] = -1.0
    changed["content_hash"] = _stable_hash(changed)
    result = record_snapshot_event(events, changed)
    assert result["status"] == "conflict"
    assert events[first["event_id"]]["content_hash"] == first["content_hash"]


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"window_start_at": "2026-07-21T13:30:00"}, "window_timestamp_invalid_or_naive"),
        ({"window_end_at": "2026-07-21T12:00:00Z"}, "window_not_strictly_ordered"),
        ({"equity_end": float("nan")}, "equity_end_invalid"),
        ({"equity_end": float("inf")}, "equity_end_invalid"),
        ({"source_timestamps": {"broker": "2026-07-21T20:00:00"}}, "source_timestamp_invalid:broker"),
    ],
)
def test_nan_inf_and_naive_timestamps_are_unavailable_not_coerced(change: dict[str, Any], reason: str) -> None:
    snapshot = _fully_reconciled(**change)
    assert reason in snapshot["reason_codes"]
    assert snapshot["valid"] is False
    json.dumps(snapshot, allow_nan=False)


def test_p52a_sanitized_case_separates_absolute_loss_cash_opportunity_and_unavailable_attribution() -> None:
    snapshot = build_eod_snapshot(
        session_date="2026-07-21",
        account_id="paper-account",
        currency="USD",
        equity_start=10_009.87,
        equity_end=10_000.0,
        cash_start=8_920.0,
        cash_end=8_915.0,
        open_pl_start=0.0,
        open_pl_end=-18.97,
        gross_realized_pl=None,
        costs=None,
        external_flow_ledger=None,
        positions=None,
        contributions=None,
        benchmark=_benchmark(end_price=503.546, price_basis=None, quality="partial"),
        session_count=1,
        comparable_session_count=0,
        outcomes_matured=False,
        descriptive_realized_pl=9.12,
    )
    assert snapshot["delta_equity"] == pytest.approx(-9.87)
    assert snapshot["delta_open_pl"] == pytest.approx(-18.97)
    assert snapshot["cash_ratio_end"] == pytest.approx(0.8915)
    assert snapshot["interpretation"]["absolute_loss_status"] == "verified"
    assert snapshot["interpretation"]["cash_opportunity_status"] == "descriptive_only"
    assert snapshot["interpretation"]["causality_status"] == "unavailable"
    assert snapshot["descriptive_realized_pl"] == 9.12
    assert snapshot["gross_realized_pl"] is None
    assert snapshot["net_realized_pl"] is None
    assert snapshot["residual_amount"] is None
    assert snapshot["benchmark"]["return"] == pytest.approx(0.007092)
    assert snapshot["benchmark"]["comparison_status"] == "degraded"
    assert "realized_pl_descriptive_not_canonical" in snapshot["warnings"]


def test_three_and_five_session_windows_keep_distinct_denominators_and_no_single_session_causality() -> None:
    rows = []
    for index in range(5):
        date = f"2026-07-{17 + index:02d}"
        rows.append(
            _fully_reconciled(
                session_date=date,
                benchmark=_benchmark() if index != 2 else _benchmark(quality="stale"),
                session_count=1,
                comparable_session_count=1 if index != 2 else 0,
            )
        )
    three = summarize_windows(rows[-3:])
    five = summarize_windows(rows)
    assert three["session_count"] == 3
    assert three["comparable_session_count"] == 2
    assert five["session_count"] == 5
    assert five["comparable_session_count"] == 4
    assert rows[-1]["interpretation"]["causality_status"] == "unavailable"


def test_sources_and_denominators_are_explicit_and_no_active_trading_object_is_mutated() -> None:
    active = {
        "candidates": [{"candidate_id": "c1", "score": 0.8}],
        "recommendations": [{"recommendation_id": "r1", "action": "BUY"}],
        "gates": [{"name": "risk", "status": "approved"}],
        "sizing": [{"qty": 10}],
        "orders": [{"broker_order_id": "buy-1", "qty": 10}],
        "stops": [{"stop_loss": 95.0}],
        "exposure": [{"gross": 1_000.0}],
    }
    before = copy.deepcopy(active)
    snapshot = _fully_reconciled(source_timestamps={"equity": WINDOW_END, "broker": WINDOW_END, "benchmark": WINDOW_END})
    assert snapshot["source_timestamps"] == {"benchmark": WINDOW_END, "broker": WINDOW_END, "equity": WINDOW_END}
    assert active == before
    assert {"broker_order_id", "lot_identity"} <= set(snapshot["contributions"][0])
    assert "fragments" not in snapshot
    assert "signals" not in snapshot
    assert "recommendations" not in snapshot
    assert "plans" not in snapshot


def test_result_has_required_coverage_fields_and_missing_values_are_null() -> None:
    snapshot = _fully_reconciled()
    required = {
        "schema_version", "event_id", "session_date", "calendar", "window_start_at", "window_end_at",
        "generated_at", "as_of", "currency", "equity_start", "equity_end", "delta_equity", "cash_start",
        "cash_end", "gross_exposure_start", "gross_exposure_end", "net_exposure_start", "net_exposure_end",
        "position_market_value_start", "position_market_value_end", "open_pl_start", "open_pl_end",
        "delta_open_pl", "gross_realized_pl", "commissions", "regulatory_fees", "spread_cost",
        "slippage_cost", "other_costs", "net_realized_pl", "external_cash_flows", "flow_adjusted_return",
        "benchmark", "residual_amount", "residual_status", "warnings", "reason_codes", "coverage",
    }
    assert required <= set(snapshot)
    assert {"session_count", "comparable_session_count"} <= set(snapshot)
    missing = _fully_reconciled(external_flow_ledger=None, costs=None, positions=None, contributions=None, benchmark=None)
    for field in ("external_cash_flows", "flow_adjusted_return", "net_realized_pl", "residual_amount", "gross_exposure_start"):
        assert missing[field] is None


def test_contract_exposes_producer_field_gap_matrix_without_wiring_or_store() -> None:
    producer_field_gap = {
        "equity_snapshot": {"fields": {"equity_start", "equity_end", "cash_end"}, "status": "partial"},
        "performance_daily": {"fields": {"equity_end", "pnl_pct", "spy_pct"}, "status": "partial"},
        "broker_orders_and_fills": {"fields": {"broker_order_id", "costs", "fill_at"}, "status": "partial"},
        "positions": {"fields": {"position_market_value_end", "open_pl_end"}, "status": "partial"},
        "external_flow_ledger": {"fields": {"flow_id", "amount", "currency", "occurred_at"}, "status": "missing"},
        "benchmark_snapshot": {"fields": {"symbol", "start_price", "end_price", "price_basis", "timestamps"}, "status": "partial"},
    }
    assert producer_field_gap["external_flow_ledger"]["status"] == "missing"
    assert producer_field_gap["broker_orders_and_fills"]["status"] == "partial"
    assert all("trading" not in key for key in producer_field_gap)
