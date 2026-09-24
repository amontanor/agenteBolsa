"""Small deterministic evaluator for supplied, point-in-time backtest rows."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from datetime import date, datetime, timezone
from typing import Any

WINDOW_CONTRACT_VERSION = "p-l117d1.windows.v1"


def _number(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _date_value(value: Any) -> date | None:
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ValueError("backtest_date_invalid") from exc


def _utc_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"backtest_{field}_required")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"backtest_{field}_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"backtest_{field}_timezone_required")
    return parsed.astimezone(timezone.utc)


def _metadata_text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _validated_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("backtest_row_mapping_required")
        signal_date = _date_value(row.get("signal_date"))
        as_of = _date_value(row.get("as_of"))
        if signal_date and as_of and as_of < signal_date:
            raise ValueError("backtest_as_of_before_signal")
        gross = _number(row.get("gross_return"))
        if gross is None:
            raise ValueError("backtest_gross_return_required")
        result.append({**row, "gross_return": gross})
    return result


def validate_window_descriptors(
    rows: Iterable[dict[str, Any]], *, require_summary: bool = False
) -> dict[str, Any]:
    """Validate and canonically order strict, half-open window descriptors."""

    validated = list(rows)
    groups: dict[str, list[dict[str, Any]]] = {}
    intervals: dict[str, tuple[datetime, datetime]] = {}
    dataset_hash: str | None = None
    contract_version: str | None = None
    for row in validated:
        if not isinstance(row, dict):
            raise ValueError("backtest_row_mapping_required")
        window_id = str(row.get("window_id") or "").strip()
        if not window_id:
            raise ValueError("backtest_window_id_required")
        start = _utc_datetime(row.get("window_start"), "window_start")
        end = _utc_datetime(row.get("window_end"), "window_end")
        if end <= start:
            raise ValueError("backtest_window_interval_invalid")
        interval = (start, end)
        if window_id in intervals:
            if require_summary:
                raise ValueError("backtest_window_id_duplicate")
            if intervals[window_id] != interval:
                raise ValueError("backtest_window_id_interval_conflict")
        intervals[window_id] = interval
        row_dataset = _metadata_text(row.get("dataset_hash"))
        row_contract = _metadata_text(row.get("evaluation_contract_version"))
        if not row_dataset or not row_contract:
            raise ValueError("backtest_window_metadata_required")
        if dataset_hash is None:
            dataset_hash = row_dataset
            contract_version = row_contract
        elif (row_dataset, row_contract) != (dataset_hash, contract_version):
            raise ValueError("backtest_window_metadata_mismatch")
        if require_summary:
            count = row.get("count")
            if type(count) is not int or count <= 0:
                raise ValueError("backtest_summary_count_required")
            for field in ("expectancy_net", "hit_rate", "profit_factor", "max_drawdown", "p10_net"):
                value = row.get(field)
                if _number(value) is None and not (field == "profit_factor" and value == math.inf):
                    raise ValueError("backtest_summary_metric_required")
        groups.setdefault(window_id, []).append(row)

    ordered_intervals = sorted(
        intervals.items(), key=lambda item: (item[1][0], item[1][1], item[0])
    )
    previous_end: datetime | None = None
    for _, (start, end) in ordered_intervals:
        if previous_end is not None and start < previous_end:
            raise ValueError("backtest_windows_overlap")
        previous_end = end

    ordered_rows = [dict(groups[window_id][0]) for window_id, _ in ordered_intervals]
    return {
        "rows": ordered_rows,
        "groups": groups,
        "intervals": dict(ordered_intervals),
        "dataset_hash": dataset_hash,
        "evaluation_contract_version": contract_version,
    }


def validate_window_contract(
    rows: Iterable[dict[str, Any]], *, require_summary: bool = False
) -> dict[str, Any]:
    """Backward-compatible alias for the shared descriptor validator."""

    return validate_window_descriptors(rows, require_summary=require_summary)


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


def evaluate_variant(
    rows: Iterable[dict[str, Any]],
    *,
    cost_bps: int = 20,
    slippage_bps: int = 0,
    variant: str | None = None,
) -> dict[str, Any]:
    """Evaluate only supplied returns; future outcome fields never become features."""

    selected = _validated_rows(rows)
    if variant is not None:
        selected = [row for row in selected if str(row.get("variant") or "") == variant]
    friction = (float(cost_bps) + float(slippage_bps)) / 10000.0
    net_returns = [float(row["gross_return"]) - friction for row in selected]
    positive = [value for value in net_returns if value > 0]
    negative = [value for value in net_returns if value < 0]
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for value in net_returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak if peak else 0.0)
    benchmark = [_number(row.get("benchmark_return")) for row in selected]
    benchmark = [value for value in benchmark if value is not None]
    return {
        "variant": variant,
        "count": len(net_returns),
        "cost_bps": cost_bps,
        "slippage_bps": slippage_bps,
        "expectancy_net": round(sum(net_returns) / len(net_returns), 8) if net_returns else None,
        "hit_rate": round(len(positive) / len(net_returns), 6) if net_returns else None,
        "profit_factor": round(sum(positive) / abs(sum(negative)), 6) if negative and sum(negative) else (math.inf if positive else None),
        "max_drawdown": round(max_drawdown, 8),
        "p10_net": round(_p10(net_returns), 8) if net_returns else None,
        "benchmark_expectancy": round(sum(benchmark) / len(benchmark), 8) if benchmark else None,
        "alpha_vs_benchmark": round(sum(net_returns) / len(net_returns) - sum(benchmark) / len(benchmark), 8)
        if net_returns and benchmark and len(benchmark) == len(net_returns)
        else None,
        **_metadata(selected),
    }


def _metadata(rows: list[dict[str, Any]]) -> dict[str, str]:
    values = {
        (
            _metadata_text(row.get("dataset_hash")),
            _metadata_text(row.get("evaluation_contract_version")),
        )
        for row in rows
    }
    if len(values) != 1:
        return {}
    dataset_hash, contract_version = next(iter(values))
    if not dataset_hash or not contract_version:
        return {}
    return {
        "dataset_hash": dataset_hash,
        "evaluation_contract_version": contract_version,
    }


def evaluate_non_overlapping_windows(
    rows: Iterable[dict[str, Any]],
    *,
    cost_bps: int = 20,
    slippage_bps: int = 0,
    variant: str | None = None,
) -> list[dict[str, Any]]:
    selected = _validated_rows(rows)
    if variant is not None:
        selected = [row for row in selected if str(row.get("variant") or "") == variant]
    contract = validate_window_descriptors(selected)
    intervals = contract["intervals"]
    output = []
    for window_id, (start, end) in intervals.items():
        group = [row for row in contract["groups"][window_id]]
        group.sort(
            key=lambda row: (
                _utc_datetime(row["signal_at"], "signal_at"),
                str(row.get("signal_id") or ""),
                json.dumps(row, sort_keys=True, default=str),
            )
        )
        for row in group:
            signal_at = _utc_datetime(row.get("signal_at"), "signal_at")
            if not start <= signal_at < end:
                raise ValueError("backtest_signal_at_outside_window")
        result = evaluate_variant(group, cost_bps=cost_bps, slippage_bps=slippage_bps, variant=variant)
        output.append(
            {
                "window_id": window_id,
                "window_start": start.isoformat().replace("+00:00", "Z"),
                "window_end": end.isoformat().replace("+00:00", "Z"),
                "dataset_hash": contract["dataset_hash"],
                "evaluation_contract_version": contract["evaluation_contract_version"],
                **result,
            }
        )
    return output
