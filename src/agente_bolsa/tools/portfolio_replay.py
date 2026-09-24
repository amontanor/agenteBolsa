"""Deterministic offline portfolio replay over explicit fills and cash events.

This module is a research boundary.  It requires normalized fills, marks, cash
flows and optional benchmark points, then computes account-level metrics without
reading Store, a broker, a provider or the active execution path.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

PORTFOLIO_SCHEMA_VERSION = "p-l117k.portfolio-dataset.v1"
PORTFOLIO_REPLAY_SCHEMA_VERSION = "p-l117k.portfolio-replay.v1"


def _signal_metrics_unavailable() -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": "signal_replay_required",
        "sample_unit": "signal",
        "required_inputs": ["signal_captures", "outcomes", "point_in_time_contract"],
    }

_FILL_FIELDS = {
    "fill_id",
    "order_id",
    "signal_id",
    "variant",
    "symbol",
    "side",
    "filled_qty",
    "fill_price",
    "fee",
    "filled_at",
    "currency",
}
_MARK_FIELDS = {"mark_id", "symbol", "mark_at", "price", "currency"}
_FLOW_FIELDS = {"flow_id", "flow_at", "amount", "kind", "currency"}
_BENCHMARK_FIELDS = {"point_id", "at", "value"}
_FLOW_KINDS = {"deposit", "withdrawal", "dividend", "fee"}
_EPSILON = 1e-10


class PortfolioContractError(ValueError):
    """Raised when portfolio input is incomplete, inconsistent or leaky."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PortfolioContractError(f"portfolio_{field}_required")
    return value.strip()


def _number(value: Any, field: str, *, required: bool = True) -> float | None:
    if value is None or value == "":
        if required:
            raise PortfolioContractError(f"portfolio_{field}_required")
        return None
    if isinstance(value, bool):
        raise PortfolioContractError(f"portfolio_{field}_invalid")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise PortfolioContractError(f"portfolio_{field}_invalid") from exc
    if not math.isfinite(parsed):
        raise PortfolioContractError(f"portfolio_{field}_invalid")
    return parsed


def _utc(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise PortfolioContractError(f"portfolio_{field}_invalid") from exc
    else:
        raise PortfolioContractError(f"portfolio_{field}_required")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PortfolioContractError(f"portfolio_{field}_timezone_required")
    return parsed.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _currency(value: Any) -> str:
    currency = _text(value if value is not None else "USD", "currency").upper()
    if currency != "USD":
        raise PortfolioContractError("portfolio_currency_unsupported")
    return currency


def _validate_fields(row: Mapping[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(row) - allowed, key=str)
    if unknown:
        raise PortfolioContractError(f"portfolio_{field}_unknown_fields:{','.join(str(item) for item in unknown)}")


def _normalise_fill(row: Mapping[str, Any]) -> dict[str, Any]:
    _validate_fields(row, _FILL_FIELDS, "fill")
    quantity = _number(row.get("filled_qty"), "filled_qty")
    price = _number(row.get("fill_price"), "fill_price")
    fee = _number(row.get("fee"), "fee")
    if quantity is None or quantity <= 0:
        raise PortfolioContractError("portfolio_filled_qty_invalid")
    if price is None or price <= 0:
        raise PortfolioContractError("portfolio_fill_price_invalid")
    if fee is None or fee < 0:
        raise PortfolioContractError("portfolio_fee_invalid")
    side = _text(row.get("side"), "side").lower()
    if side not in {"buy", "sell"}:
        raise PortfolioContractError("portfolio_side_unsupported")
    return {
        "fill_id": _text(row.get("fill_id"), "fill_id"),
        "order_id": _text(row.get("order_id"), "order_id"),
        "signal_id": _text(row.get("signal_id"), "signal_id"),
        "variant": _text(row.get("variant"), "variant").lower(),
        "symbol": _text(row.get("symbol"), "symbol").upper(),
        "side": side,
        "filled_qty": quantity,
        "fill_price": price,
        "fee": fee,
        "filled_at": _utc_text(_utc(row.get("filled_at"), "filled_at")),
        "currency": _currency(row.get("currency")),
    }


def _normalise_mark(row: Mapping[str, Any]) -> dict[str, Any]:
    _validate_fields(row, _MARK_FIELDS, "mark")
    price = _number(row.get("price"), "mark_price")
    if price is None or price <= 0:
        raise PortfolioContractError("portfolio_mark_price_invalid")
    return {
        "mark_id": _text(row.get("mark_id"), "mark_id"),
        "symbol": _text(row.get("symbol"), "symbol").upper(),
        "mark_at": _utc_text(_utc(row.get("mark_at"), "mark_at")),
        "price": price,
        "currency": _currency(row.get("currency")),
    }


def _normalise_flow(row: Mapping[str, Any]) -> dict[str, Any]:
    _validate_fields(row, _FLOW_FIELDS, "flow")
    amount = _number(row.get("amount"), "flow_amount")
    kind = _text(row.get("kind"), "flow_kind").lower()
    if amount is None or abs(amount) <= _EPSILON:
        raise PortfolioContractError("portfolio_flow_amount_invalid")
    if kind not in _FLOW_KINDS:
        raise PortfolioContractError("portfolio_flow_kind_unsupported")
    if kind in {"deposit", "dividend"} and amount <= 0:
        raise PortfolioContractError("portfolio_flow_sign_invalid")
    if kind in {"withdrawal", "fee"} and amount >= 0:
        raise PortfolioContractError("portfolio_flow_sign_invalid")
    return {
        "flow_id": _text(row.get("flow_id"), "flow_id"),
        "flow_at": _utc_text(_utc(row.get("flow_at"), "flow_at")),
        "amount": amount,
        "kind": kind,
        "currency": _currency(row.get("currency")),
    }


def _normalise_benchmark(row: Mapping[str, Any]) -> dict[str, Any]:
    _validate_fields(row, _BENCHMARK_FIELDS, "benchmark")
    value = _number(row.get("value"), "benchmark_value")
    if value is None or value <= 0:
        raise PortfolioContractError("portfolio_benchmark_value_invalid")
    return {
        "point_id": _text(row.get("point_id"), "point_id"),
        "at": _utc_text(_utc(row.get("at"), "benchmark_at")),
        "value": value,
    }


def _normalise_collection(
    rows: Iterable[Mapping[str, Any]] | None,
    *,
    normaliser: Any,
    identity: str,
    collection: str,
) -> tuple[list[dict[str, Any]], int]:
    result: list[dict[str, Any]] = []
    by_identity: dict[str, str] = {}
    fingerprints: set[str] = set()
    duplicates = 0
    for raw in rows or []:
        if not isinstance(raw, Mapping):
            raise PortfolioContractError(f"portfolio_{collection}_mapping_required")
        normalised = normaliser(raw)
        key = normalised[identity]
        fingerprint = _canonical_json(normalised)
        if key in by_identity and by_identity[key] != fingerprint:
            raise PortfolioContractError(f"portfolio_{collection}_identity_conflict")
        if fingerprint in fingerprints:
            duplicates += 1
            continue
        by_identity[key] = fingerprint
        fingerprints.add(fingerprint)
        result.append(normalised)
    result.sort(key=lambda row: (row.get("filled_at") or row.get("mark_at") or row.get("flow_at") or row.get("at"), row[identity]))
    return result, duplicates


def _artifact_hash_payload(artifact: Mapping[str, Any]) -> dict[str, Any]:
    return {key: artifact[key] for key in artifact if key != "portfolio_hash"}


def _attach_metric_scope(result: dict[str, Any]) -> dict[str, Any]:
    result["metric_scope"] = "portfolio"
    result["signal_metrics"] = _signal_metrics_unavailable()
    if result.get("status") == "ready" and isinstance(result.get("metrics"), dict):
        result["portfolio_metrics"] = dict(result["metrics"])
    else:
        result["portfolio_metrics"] = {
            "status": result.get("status", "unavailable"),
            "reason": "portfolio_replay_not_ready",
            "sample_unit": "portfolio",
            "required_inputs": ["fills", "marks", "cash_flows", "costs"],
        }
    return result


def build_portfolio_dataset(
    *,
    fills: Iterable[Mapping[str, Any]],
    marks: Iterable[Mapping[str, Any]] | None = None,
    cash_flows: Iterable[Mapping[str, Any]] | None = None,
    benchmark_points: Iterable[Mapping[str, Any]] | None = None,
    initial_cash: int | float,
    evaluation_as_of: Any,
) -> dict[str, Any]:
    """Normalize an explicit portfolio event set without replaying it."""

    evaluation = _utc(evaluation_as_of, "evaluation_as_of")
    cash = _number(initial_cash, "initial_cash")
    if cash is None or cash <= 0:
        raise PortfolioContractError("portfolio_initial_cash_invalid")
    normalised_fills, fill_duplicates = _normalise_collection(
        fills, normaliser=_normalise_fill, identity="fill_id", collection="fills"
    )
    normalised_marks, mark_duplicates = _normalise_collection(
        marks, normaliser=_normalise_mark, identity="mark_id", collection="marks"
    )
    normalised_flows, flow_duplicates = _normalise_collection(
        cash_flows, normaliser=_normalise_flow, identity="flow_id", collection="cash_flows"
    )
    normalised_benchmark, benchmark_duplicates = _normalise_collection(
        benchmark_points,
        normaliser=_normalise_benchmark,
        identity="point_id",
        collection="benchmark_points",
    )
    all_rows = [*normalised_fills, *normalised_marks, *normalised_flows, *normalised_benchmark]
    time_fields = [
        (row, "filled_at") for row in normalised_fills
    ] + [
        (row, "mark_at") for row in normalised_marks
    ] + [
        (row, "flow_at") for row in normalised_flows
    ] + [(row, "at") for row in normalised_benchmark]
    for row, field in time_fields:
        if _utc(row[field], field) > evaluation:
            raise PortfolioContractError("portfolio_event_after_evaluation_as_of")
    variants = sorted({row["variant"] for row in normalised_fills})
    artifact: dict[str, Any] = {
        "schema_version": PORTFOLIO_SCHEMA_VERSION,
        "evaluation_as_of": _utc_text(evaluation),
        "initial_cash": cash,
        "fills": normalised_fills,
        "marks": normalised_marks,
        "cash_flows": normalised_flows,
        "benchmark_points": normalised_benchmark,
        "variants": variants,
        "status": "ready" if normalised_fills else "unavailable",
        "warnings": [] if normalised_benchmark else ["benchmark_unavailable"],
        "denominators": {
            "fill_count": len(normalised_fills),
            "mark_count": len(normalised_marks),
            "cash_flow_count": len(normalised_flows),
            "benchmark_point_count": len(normalised_benchmark),
            "idempotent_duplicates": fill_duplicates
            + mark_duplicates
            + flow_duplicates
            + benchmark_duplicates,
            "variant_count": len(variants),
        },
    }
    if not all_rows:
        artifact["status"] = "unavailable"
    artifact["portfolio_hash"] = _hash_payload(_artifact_hash_payload(artifact))
    return artifact


def _validate_canonical_collection(
    rows: Any, *, normaliser: Any, identity: str, collection: str, evaluation: datetime
) -> None:
    if not isinstance(rows, list):
        raise PortfolioContractError(f"portfolio_{collection}_list_required")
    seen: set[str] = set()
    previous: tuple[str, str] | None = None
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise PortfolioContractError(f"portfolio_{collection}_mapping_required")
        normalised = normaliser(raw)
        if _canonical_json(normalised) != _canonical_json(dict(raw)):
            raise PortfolioContractError(f"portfolio_{collection}_not_canonical")
        key = str(raw[identity])
        if key in seen:
            raise PortfolioContractError(f"portfolio_{collection}_identity_conflict")
        seen.add(key)
        time_field = "filled_at" if collection == "fills" else "mark_at" if collection == "marks" else "flow_at" if collection == "cash_flows" else "at"
        timestamp = _utc(raw[time_field], time_field)
        if timestamp > evaluation:
            raise PortfolioContractError("portfolio_event_after_evaluation_as_of")
        order_key = (str(raw[time_field]), key)
        if previous is not None and order_key < previous:
            raise PortfolioContractError(f"portfolio_{collection}_not_canonically_ordered")
        previous = order_key


def validate_portfolio_dataset(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Validate canonical event rows and the artifact hash."""

    if not isinstance(artifact, Mapping):
        raise PortfolioContractError("portfolio_artifact_mapping_required")
    if artifact.get("schema_version") != PORTFOLIO_SCHEMA_VERSION:
        raise PortfolioContractError("portfolio_schema_version_mismatch")
    evaluation = _utc(artifact.get("evaluation_as_of"), "evaluation_as_of")
    cash = _number(artifact.get("initial_cash"), "initial_cash")
    if cash is None or cash <= 0:
        raise PortfolioContractError("portfolio_initial_cash_invalid")
    _validate_canonical_collection(artifact.get("fills"), normaliser=_normalise_fill, identity="fill_id", collection="fills", evaluation=evaluation)
    _validate_canonical_collection(artifact.get("marks"), normaliser=_normalise_mark, identity="mark_id", collection="marks", evaluation=evaluation)
    _validate_canonical_collection(artifact.get("cash_flows"), normaliser=_normalise_flow, identity="flow_id", collection="cash_flows", evaluation=evaluation)
    _validate_canonical_collection(artifact.get("benchmark_points"), normaliser=_normalise_benchmark, identity="point_id", collection="benchmark_points", evaluation=evaluation)
    expected_variants = sorted({row["variant"] for row in artifact["fills"]})
    if artifact.get("variants") != expected_variants:
        raise PortfolioContractError("portfolio_variants_not_canonical")
    if artifact.get("portfolio_hash") != _hash_payload(_artifact_hash_payload(artifact)):
        raise PortfolioContractError("portfolio_hash_mismatch")
    return copy.deepcopy(dict(artifact))


def _p10(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = 0.10 * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _max_adverse_excursion(
    artifact: Mapping[str, Any],
    fills: list[dict[str, Any]],
) -> float | None:
    """Compute worst marked adverse excursion for FIFO long lots."""

    marks_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for mark in artifact.get("marks", []):
        if isinstance(mark, dict):
            marks_by_symbol[str(mark["symbol"])].append(mark)
    for rows in marks_by_symbol.values():
        rows.sort(key=lambda row: (str(row["mark_at"]), str(row["mark_id"])))

    open_lots: dict[str, list[dict[str, Any]]] = defaultdict(list)
    windows: list[tuple[str, float, str, str]] = []
    evaluation_as_of = str(artifact.get("evaluation_as_of") or "")
    for fill in fills:
        symbol = str(fill["symbol"])
        filled_at = str(fill["filled_at"])
        if fill["side"] == "buy":
            open_lots[symbol].append(
                {
                    "quantity": float(fill["filled_qty"]),
                    "entry_price": float(fill["fill_price"]),
                    "entry_at": filled_at,
                }
            )
            continue
        remaining = float(fill["filled_qty"])
        while remaining > _EPSILON and open_lots[symbol]:
            lot = open_lots[symbol][0]
            matched = min(remaining, float(lot["quantity"]))
            windows.append((symbol, float(lot["entry_price"]), str(lot["entry_at"]), filled_at))
            remaining -= matched
            lot["quantity"] = float(lot["quantity"]) - matched
            if lot["quantity"] <= _EPSILON:
                open_lots[symbol].pop(0)
    for symbol, lots in open_lots.items():
        for lot in lots:
            windows.append((symbol, float(lot["entry_price"]), str(lot["entry_at"]), evaluation_as_of))

    excursions: list[float] = []
    for symbol, entry_price, entry_at, close_at in windows:
        prices = [
            float(mark["price"])
            for mark in marks_by_symbol.get(symbol, [])
            if entry_at <= str(mark["mark_at"]) <= close_at
        ]
        if not prices or entry_price <= 0:
            continue
        excursions.append(max(0.0, (entry_price - min(prices)) / entry_price))
    return round(max(excursions), 8) if excursions else None


def _equity(cash: float, positions: Mapping[str, float], marks: Mapping[str, float]) -> tuple[float, float, int]:
    gross = sum(abs(quantity * marks[symbol]) for symbol, quantity in positions.items() if abs(quantity) > _EPSILON)
    value = cash + sum(quantity * marks[symbol] for symbol, quantity in positions.items())
    concurrent = sum(abs(quantity) > _EPSILON for quantity in positions.values())
    return value, gross, concurrent


def _normalise_variant(value: str | None) -> str | None:
    if value is None:
        return None
    variant = _text(value, "variant").lower()
    return variant


def replay_portfolio_dataset(
    artifact: Mapping[str, Any], *, variant: str | None = None
) -> dict[str, Any]:
    """Replay fills, cash flows and marks in timestamp/type/id order."""

    validated = validate_portfolio_dataset(artifact)
    selected_variant = _normalise_variant(variant)
    if selected_variant is not None and selected_variant not in validated["variants"]:
        result = {
            "schema_version": PORTFOLIO_REPLAY_SCHEMA_VERSION,
            "portfolio_hash": validated["portfolio_hash"],
            "variant": selected_variant,
            "status": "unavailable",
            "reasons": ["variant_unavailable"],
            "metrics": {"fill_count": 0},
        }
        _attach_metric_scope(result)
        result["replay_hash"] = _hash_payload(result)
        return result
    fills = [
        row
        for row in validated["fills"]
        if selected_variant is None or row["variant"] == selected_variant
    ]
    if not fills:
        result = {
            "schema_version": PORTFOLIO_REPLAY_SCHEMA_VERSION,
            "portfolio_hash": validated["portfolio_hash"],
            "variant": selected_variant,
            "status": "unavailable",
            "reasons": ["fills_unavailable"],
            "metrics": {"fill_count": 0},
        }
        _attach_metric_scope(result)
        result["replay_hash"] = _hash_payload(result)
        return result

    events: list[tuple[str, str, str, dict[str, Any]]] = []
    for row in validated["cash_flows"]:
        events.append((row["flow_at"], "cash_flow", row["flow_id"], row))
    for row in fills:
        events.append((row["filled_at"], "fill", row["fill_id"], row))
    for row in validated["marks"]:
        events.append((row["mark_at"], "mark", row["mark_id"], row))
    type_order = {"cash_flow": 0, "fill": 1, "mark": 2}
    events.sort(key=lambda item: (item[0], type_order[item[1]], item[2]))

    cash = float(validated["initial_cash"])
    positions: dict[str, float] = defaultdict(float)
    marks: dict[str, float] = {}
    last_fill_price: dict[str, float] = {}
    last_fill_at: dict[str, str] = {}
    lots: dict[str, list[list[float]]] = defaultdict(list)
    order_counts = Counter(row["order_id"] for row in fills)
    total_fill_notional = 0.0
    total_fill_fees = 0.0
    realized_gross = 0.0
    closed_trade_count = 0
    external_flow_total = 0.0
    flow_fee_total = 0.0
    wealth = 1.0
    previous_equity = cash
    peak_wealth = wealth
    max_drawdown = 0.0
    min_cash = cash
    snapshots: list[dict[str, Any]] = []
    wealth_points: list[float] = [wealth]
    subperiod_returns: list[float] = []
    reasons: list[str] = []

    for timestamp, event_type, event_id, row in events:
        was_external_flow = False
        if event_type == "cash_flow":
            amount = float(row["amount"])
            cash += amount
            if row["kind"] in {"deposit", "withdrawal"}:
                external_flow_total += amount
                was_external_flow = True
            if row["kind"] == "fee":
                flow_fee_total += abs(amount)
        elif event_type == "fill":
            quantity = float(row["filled_qty"])
            notional = quantity * float(row["fill_price"])
            fee = float(row["fee"])
            total_fill_notional += notional
            total_fill_fees += fee
            sign = 1.0 if row["side"] == "buy" else -1.0
            cash -= sign * notional + fee
            symbol = row["symbol"]
            last_fill_price[symbol] = float(row["fill_price"])
            last_fill_at[symbol] = row["filled_at"]
            if row["side"] == "buy":
                positions[symbol] += quantity
                lots[symbol].append([quantity, float(row["fill_price"])])
            else:
                if positions[symbol] + _EPSILON < quantity:
                    raise PortfolioContractError("portfolio_short_not_supported")
                positions[symbol] -= quantity
                remaining = quantity
                while remaining > _EPSILON:
                    if not lots[symbol]:
                        raise PortfolioContractError("portfolio_fifo_lot_missing")
                    lot_quantity, lot_price = lots[symbol][0]
                    matched = min(remaining, lot_quantity)
                    realized_gross += matched * (float(row["fill_price"]) - lot_price)
                    closed_trade_count += 1
                    remaining -= matched
                    lot_quantity -= matched
                    if lot_quantity <= _EPSILON:
                        lots[symbol].pop(0)
                    else:
                        lots[symbol][0][0] = lot_quantity
        else:
            marks[row["symbol"]] = float(row["price"])

        for symbol, price in last_fill_price.items():
            marks.setdefault(symbol, price)
        current_equity, gross_exposure, concurrent_symbols = _equity(cash, positions, marks)
        if cash < -_EPSILON:
            raise PortfolioContractError("portfolio_cash_negative")
        if current_equity <= 0:
            raise PortfolioContractError("portfolio_equity_non_positive")
        if was_external_flow:
            wealth = wealth
        else:
            if previous_equity <= 0:
                raise PortfolioContractError("portfolio_previous_equity_non_positive")
            wealth *= current_equity / previous_equity
            subperiod_returns.append(current_equity / previous_equity - 1.0)
        peak_wealth = max(peak_wealth, wealth)
        max_drawdown = max(max_drawdown, (peak_wealth - wealth) / peak_wealth)
        min_cash = min(min_cash, cash)
        wealth_points.append(wealth)
        snapshots.append(
            {
                "at": timestamp,
                "event_type": event_type,
                "event_id": event_id,
                "cash": cash,
                "equity": current_equity,
                "gross_exposure": gross_exposure,
                "concurrent_symbols": concurrent_symbols,
                "wealth_index": wealth,
            }
        )
        previous_equity = current_equity

    open_symbols = sorted(symbol for symbol, quantity in positions.items() if quantity > _EPSILON)
    for symbol in open_symbols:
        if symbol not in marks or last_fill_at.get(symbol, "") > max(
            (row["mark_at"] for row in validated["marks"] if row["symbol"] == symbol), default=""
        ):
            reasons.append("terminal_mark_unavailable:" + symbol)
    if reasons:
        result = {
            "schema_version": PORTFOLIO_REPLAY_SCHEMA_VERSION,
            "portfolio_hash": validated["portfolio_hash"],
            "variant": selected_variant,
            "status": "collecting",
            "reasons": sorted(reasons),
            "denominators": {"fill_count": len(fills), "mark_count": len(validated["marks"])},
        }
        _attach_metric_scope(result)
        result["replay_hash"] = _hash_payload(result)
        return result

    final_equity, final_gross_exposure, final_concurrent_symbols = _equity(cash, positions, marks)
    benchmark = validated["benchmark_points"]
    benchmark_return = None
    warnings: list[str] = []
    if len(benchmark) >= 2:
        benchmark_return = float(benchmark[-1]["value"]) / float(benchmark[0]["value"]) - 1.0
    else:
        warnings.append("benchmark_unavailable")
    portfolio_mae = _max_adverse_excursion(validated, fills)
    metrics: dict[str, Any] = {
        "initial_cash": float(validated["initial_cash"]),
        "final_cash": round(cash, 8),
        "final_equity": round(final_equity, 8),
        "external_flow_total": round(external_flow_total, 8),
        "flow_adjusted_profit": round(final_equity - float(validated["initial_cash"]) - external_flow_total, 8),
        "flow_adjusted_return": round(
            (final_equity - float(validated["initial_cash"]) - external_flow_total)
            / float(validated["initial_cash"]),
            8,
        ),
        "time_weighted_return": round(wealth - 1.0, 8),
        "realized_gross_pnl": round(realized_gross, 8),
        "fill_notional": round(total_fill_notional, 8),
        "fill_fees": round(total_fill_fees, 8),
        "cash_flow_fees": round(flow_fee_total, 8),
        "min_cash": round(min_cash, 8),
        "max_gross_exposure": round(max(snapshot["gross_exposure"] for snapshot in snapshots), 8),
        "terminal_gross_exposure": round(final_gross_exposure, 8),
        "max_gross_exposure_ratio": round(
            max(snapshot["gross_exposure"] / snapshot["equity"] for snapshot in snapshots), 8
        ),
        "terminal_concurrent_symbols": final_concurrent_symbols,
        "max_concurrent_symbols": max(snapshot["concurrent_symbols"] for snapshot in snapshots),
        "max_drawdown": round(max_drawdown, 8),
        "p10_subperiod_return": round(_p10(subperiod_returns), 8) if subperiod_returns else None,
        "portfolio_max_drawdown": round(max_drawdown, 8),
        "p10_capital_return": round(_p10(subperiod_returns), 8) if subperiod_returns else None,
        "max_concentration_ratio": round(
            max(snapshot["gross_exposure"] / snapshot["equity"] for snapshot in snapshots), 8
        ),
        "portfolio_mae": portfolio_mae,
        "max_adverse_excursion": portfolio_mae,
        "closed_trade_count": closed_trade_count,
        "benchmark_points": len(benchmark),
        "benchmark_return": round(benchmark_return, 8) if benchmark_return is not None else None,
        "alpha_vs_benchmark": round(wealth - 1.0 - benchmark_return, 8)
        if benchmark_return is not None
        else None,
        "partial_fill_orders": sum(count > 1 for count in order_counts.values()),
        "max_fills_per_order": max(order_counts.values()),
        "equity_snapshot_count": len(snapshots),
    }
    result = {
        "schema_version": PORTFOLIO_REPLAY_SCHEMA_VERSION,
        "portfolio_hash": validated["portfolio_hash"],
        "variant": selected_variant,
        "status": "ready",
        "warnings": warnings,
        "metrics": metrics,
    }
    _attach_metric_scope(result)
    result["replay_hash"] = _hash_payload(result)
    return result


def replay_all_portfolio_variants(artifact: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Replay each captured policy variant in stable order."""

    validated = validate_portfolio_dataset(artifact)
    return [replay_portfolio_dataset(validated, variant=variant) for variant in validated["variants"]]
