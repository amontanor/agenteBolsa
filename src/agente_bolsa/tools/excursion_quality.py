"""Observational MFE/MAE and stop/take geometry report.

This module is deliberately read-only. It never updates signal outcomes, orders,
proposals, or promotion state.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter
from collections.abc import Iterable
from datetime import date, datetime, timezone
from typing import Any

from ..storage import Store

HORIZONS = ("1d", "3d", "5d", "10d")
MIN_SAMPLE_DEFAULT = 300
STOP_BUCKETS = ((0.0, 0.25), (0.25, 0.50), (0.50, 0.75), (0.75, 1.0), (1.0, 1.5), (1.5, math.inf))
TARGET_BUCKETS = STOP_BUCKETS
RR_BUCKETS = ((-math.inf, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 3.0), (3.0, math.inf))


def build_excursion_quality_report(
    store: Store,
    *,
    start: str | None = None,
    end: str | None = None,
    horizon: str = "all",
    min_sample: int = MIN_SAMPLE_DEFAULT,
    historical: bool = False,
) -> dict[str, Any]:
    """Build a deterministic observational report from existing outcomes."""
    if horizon not in {*HORIZONS, "all"}:
        return _unavailable("horizon_invalid", {"horizon": horizon})
    try:
        min_sample = int(min_sample)
    except (TypeError, ValueError):
        return _unavailable("min_sample_invalid", {"min_sample": min_sample})
    if min_sample < 1:
        return _unavailable("min_sample_invalid", {"min_sample": min_sample})

    rows = store.signal_outcomes(limit=500_000)
    dates = sorted({str(item.get("signal_date")) for item in rows if _parse_date(item.get("signal_date"))})
    if not dates:
        return _unavailable("sin_signal_outcomes", {"historical": historical})
    try:
        resolved_end = _resolve_end(end, dates)
        resolved_start = _resolve_start(start, resolved_end, dates, historical)
    except ValueError as exc:
        return _unavailable(str(exc), {"start": start, "end": end, "historical": historical})
    selected = [
        item
        for item in rows
        if resolved_start <= str(item.get("signal_date")) <= resolved_end
    ]
    selected_horizons = HORIZONS if horizon == "all" else (horizon,)
    prepared, quality = _prepare_rows(selected, selected_horizons)
    report = {
        "schema_version": "p-l27b.excursion-quality.v1",
        "observational_only": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "parameters": {
            "from": resolved_start,
            "to": resolved_end,
            "horizon": horizon,
            "min_sample": min_sample,
            "historical": historical,
        },
        "definitions": _definitions(),
        "status": "available" if prepared else "unavailable",
        "data_quality": quality,
        "horizons": {item: _horizon_report(prepared, item, min_sample) for item in selected_horizons},
        "groups": {
            "stop_consumption": _bucket_report(prepared, "stop_consumption", STOP_BUCKETS, min_sample),
            "target_attainment": _bucket_report(prepared, "target_attainment", TARGET_BUCKETS, min_sample),
            "reward_risk_ratio": _bucket_report(prepared, "reward_risk_ratio", RR_BUCKETS, min_sample),
            "setup_quality": _categorical_report(prepared, "setup_quality", min_sample),
            "first_hit": _categorical_report(prepared, "first_hit", min_sample),
            "verdict": _categorical_report(prepared, "verdict", min_sample),
        },
        "concentration": _concentration(selected),
        "warnings": [
            "Los retornos son forward de senales, no P&L ejecutado.",
            "MFE/MAE disponibles son horizonte 10d; no se reinterpretan como excursiones 1d/3d/5d.",
            "La geometria se evalua solo para direction=long; direction no-long queda excluida porque el productor actual no publica excursiones direccionales comparables.",
            "Observaciones del mismo dia y simbolo pueden depender entre si; no se calcula significancia independiente.",
            "No se calculan alpha, SPY, causalidad ni drawdown de cartera: datos no disponibles para este informe.",
        ],
    }
    report["content_hash"] = _content_hash(report)
    return report


def _prepare_rows(rows: Iterable[dict[str, Any]], horizons: tuple[str, ...]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    reasons = Counter()
    maturity = Counter()
    for item in rows:
        features = item.get("features") if isinstance(item.get("features"), dict) else None
        outcome = item.get("outcome") if isinstance(item.get("outcome"), dict) else None
        if features is None or outcome is None:
            reasons["outcome_corrupt"] += 1
            continue
        direction = str(features.get("direction") or "").lower()
        if direction != "long":
            reasons["direction_not_long"] += 1
            continue
        entry, stop, take = features.get("entry_price"), features.get("stop_loss"), features.get("take_profit")
        mfe, mae = outcome.get("mfe_10d"), outcome.get("mae_10d")
        for item_horizon in horizons:
            forward = outcome.get(f"return_{item_horizon}")
            if not isinstance(forward, (int, float)) or isinstance(forward, bool):
                maturity[f"immature_{item_horizon}"] += 1
                continue
            maturity[f"matured_{item_horizon}"] += 1
            reason = _geometry_reason(entry, stop, take, mfe, mae)
            if reason:
                reasons[reason] += 1
                continue
            risk = float(entry) - float(stop)
            reward = float(take) - float(entry)
            stop_distance = risk / float(entry)
            take_distance = reward / float(entry)
            rr = reward / risk
            mae_r = abs(min(float(mae), 0.0)) / risk
            mfe_r = max(float(mfe), 0.0) / risk
            first_hit = _first_hit(item, outcome)
            prepared.append(
                {
                    "horizon": item_horizon,
                    "signal_date": item.get("signal_date"),
                    "symbol": item.get("symbol"),
                    "return": float(forward),
                    "mfe": float(mfe),
                    "mae": float(mae),
                    "risk_distance": risk,
                    "reward_distance": reward,
                    "stop_distance_pct": stop_distance,
                    "take_distance_pct": take_distance,
                    "reward_risk_ratio": rr,
                    "mae_r": mae_r,
                    "mfe_r": mfe_r,
                    "target_r": rr,
                    "stop_consumption": mae_r,
                    "target_attainment": mfe_r / rr if rr > 0 else None,
                    "setup_quality": str(features.get("setup_quality") or "unknown"),
                    "first_hit": first_hit,
                    "verdict": str(outcome.get("verdict") or "unknown"),
                    "lineage_status": "verified" if _has_lineage(item) else "legacy_unverified",
                }
            )
    total = sum(maturity.values()) + sum(reasons.values())
    quality = {
        "source": "signal_outcomes",
        "selected_rows": total,
        "matured_count": sum(value for key, value in maturity.items() if key.startswith("matured_")),
        "immature_count": sum(value for key, value in maturity.items() if key.startswith("immature_")),
        "valid_count": len(prepared),
        "excluded_count": sum(reasons.values()),
        "exclusions_by_reason": dict(sorted(reasons.items())),
        "maturity_by_horizon": dict(sorted(maturity.items())),
        "legacy_unverified_count": sum(1 for item in prepared if item["lineage_status"] == "legacy_unverified"),
        "verified_count": sum(1 for item in prepared if item["lineage_status"] == "verified"),
        "imputation_count": 0,
        "alpha": "unavailable",
        "spy_excess": "unavailable",
        "portfolio_drawdown": "unavailable",
    }
    quality["coverage"] = round(len(prepared) / quality["matured_count"], 4) if quality["matured_count"] else None
    return prepared, quality


def _horizon_report(rows: list[dict[str, Any]], horizon: str, min_sample: int) -> dict[str, Any]:
    subset = [item for item in rows if item["horizon"] == horizon]
    return _metrics(subset, min_sample)


def _bucket_report(rows: list[dict[str, Any]], key: str, buckets: tuple[tuple[float, float], ...], min_sample: int) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for low, high in buckets:
        label = _bucket_label(low, high)
        subset = [item for item in rows if _in_bucket(item.get(key), low, high)]
        output[label] = _metrics(subset, min_sample)
    return output


def _categorical_report(rows: list[dict[str, Any]], key: str, min_sample: int) -> dict[str, Any]:
    values = sorted({str(item.get(key) or "unknown") for item in rows})
    return {value: _metrics([item for item in rows if str(item.get(key) or "unknown") == value], min_sample) for value in values}


def _metrics(rows: list[dict[str, Any]], min_sample: int) -> dict[str, Any]:
    size = len(rows)
    returns = [item["return"] for item in rows]
    mfe = [item["mfe"] for item in rows]
    mae = [item["mae"] for item in rows]
    mfe_r = [item["mfe_r"] for item in rows]
    mae_r = [item["mae_r"] for item in rows]
    rr = [item["reward_risk_ratio"] for item in rows]
    stop_hits = [item for item in rows if item["first_hit"] == "stop"]
    take_hits = [item for item in rows if item["first_hit"] == "take_profit"]
    neither = [item for item in rows if item["first_hit"] == "neither"]
    return {
        "sample_size": size,
        "matured_count": size,
        "excluded_count": 0,
        "coverage": 1.0 if size else 0.0,
        "mean_return": _mean(returns),
        "median_return": _median(returns),
        "positive_rate": round(sum(value > 0 for value in returns) / size, 4) if size else None,
        "mean_mfe": _mean(mfe), "median_mfe": _median(mfe),
        "mean_mae": _mean(mae), "median_mae": _median(mae),
        "mean_mfe_r": _mean(mfe_r), "median_mfe_r": _median(mfe_r),
        "mean_mae_r": _mean(mae_r), "median_mae_r": _median(mae_r),
        "stop_hit_rate": round(len(stop_hits) / size, 4) if size else None,
        "take_hit_rate": round(len(take_hits) / size, 4) if size else None,
        "neither_hit_rate": round(len(neither) / size, 4) if size else None,
        "first_hit_stop_rate": round(len(stop_hits) / size, 4) if size else None,
        "first_hit_take_rate": round(len(take_hits) / size, 4) if size else None,
        "mean_reward_risk_ratio": _mean(rr), "median_reward_risk_ratio": _median(rr),
        "status": "evaluable" if size >= min_sample else "insufficient_sample",
        "lineage_status": _lineage_status(rows),
        "data_quality_warnings": ["mfe_mae_horizon_is_10d"] if size else [],
    }


def _geometry_reason(entry: Any, stop: Any, take: Any, mfe: Any, mae: Any) -> str | None:
    for name, value in (("entry", entry), ("stop", stop), ("take", take), ("mfe", mfe), ("mae", mae)):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return f"{name}_non_numeric_or_missing"
    if entry <= 0:
        return "entry_zero_or_negative"
    if stop >= entry:
        return "stop_ge_entry"
    if take <= entry:
        return "take_le_entry"
    return None


def _first_hit(item: dict[str, Any], outcome: dict[str, Any]) -> str:
    first = outcome.get("first_hit")
    if isinstance(first, dict):
        hit_type = str(first.get("type") or "").lower()
        if hit_type in {"stop", "stop_loss"}:
            return "stop"
        if hit_type in {"take", "take_profit"}:
            return "take_profit"
    verdict = str(outcome.get("verdict") or "")
    if verdict in {"winner_open", "loser_open", "flat"}:
        return "neither"
    return "unknown"


def _has_lineage(item: dict[str, Any]) -> bool:
    features = item.get("features") or {}
    outcome = item.get("outcome") or {}
    return bool(features.get("decision_lineage") or features.get("lineage_id") or outcome.get("decision_lineage"))


def _concentration(rows: list[dict[str, Any]]) -> dict[str, Any]:
    dates = Counter(str(item.get("signal_date")) for item in rows)
    symbols = Counter(str(item.get("symbol")) for item in rows)
    return {
        "unique_signal_dates": len(dates),
        "unique_symbols": len(symbols),
        "top_date": dates.most_common(1)[0] if dates else None,
        "top_symbol": symbols.most_common(1)[0] if symbols else None,
        "dependency_warning": "mismo dia/simbolo puede contener observaciones dependientes",
    }


def _resolve_end(value: str | None, dates: list[str]) -> str:
    if value:
        _parse_date(value, strict=True)
        return value
    today = date.today().isoformat()
    return max((item for item in dates if item <= today), default=dates[-1])


def _resolve_start(value: str | None, end: str, dates: list[str], historical: bool) -> str:
    if value:
        _parse_date(value, strict=True)
        return value
    if historical:
        return dates[0]
    eligible = [item for item in dates if item <= end]
    return eligible[max(0, len(eligible) - 30)] if eligible else end


def _parse_date(value: Any, *, strict: bool = False) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        if strict:
            raise ValueError(f"Fecha invalida: {value}") from None
        return None


def _bucket_label(low: float, high: float) -> str:
    if low == 1.5 and math.isinf(high):
        return ">=1.50"
    if math.isinf(low):
        return "<1"
    if high == math.inf:
        return f">={low:g}"
    return f"[{low:.2f},{high:.2f})"


def _in_bucket(value: Any, low: float, high: float) -> bool:
    return isinstance(value, (int, float)) and value >= low and value < high


def _lineage_status(rows: list[dict[str, Any]]) -> str:
    statuses = {item["lineage_status"] for item in rows}
    return next(iter(statuses)) if len(statuses) == 1 else ("mixed" if statuses else "unavailable")


def _mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 6) if values else None


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 6) if values else None


def _content_hash(report: dict[str, Any]) -> str:
    stable = {key: value for key, value in report.items() if key not in {"generated_at", "content_hash"}}
    encoded = json.dumps(stable, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _definitions() -> dict[str, str]:
    return {
        "units": "mfe_10d y mae_10d son fracciones decimales respecto a entry_price, calculadas por signal_learning.py",
        "risk_distance": "entry_price - stop_loss",
        "reward_distance": "take_profit - entry_price",
        "stop_distance_pct": "risk_distance / entry_price",
        "take_distance_pct": "reward_distance / entry_price",
        "reward_risk_ratio": "reward_distance / risk_distance",
        "mae_r": "abs(min(mae, 0)) / risk_distance",
        "mfe_r": "max(mfe, 0) / risk_distance",
        "target_r": "reward_risk_ratio",
        "stop_consumption": "mae_r",
        "target_attainment": "mfe_r / target_r si target_r > 0",
    }


def _unavailable(reason: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "p-l27b.excursion-quality.v1",
        "observational_only": True,
        "status": "unavailable",
        "reason": reason,
        "parameters": parameters,
        "content_hash": hashlib.sha256(reason.encode("utf-8")).hexdigest(),
    }
