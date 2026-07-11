"""Read-only observational audit of forward MFE/MAE and stop/take geometry."""

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
EXCURSION_HORIZON = "10d"
MIN_SAMPLE_DEFAULT = 300
STOP_BUCKETS = ((0.0, 0.25), (0.25, 0.50), (0.50, 0.75), (0.75, 1.0), (1.0, 1.5), (1.5, math.inf))
TARGET_BUCKETS = STOP_BUCKETS
RR_BUCKETS = ((0.0, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 3.0), (3.0, math.inf))


def build_excursion_quality_report(
    store: Store,
    *,
    start: str | None = None,
    end: str | None = None,
    horizon: str = "all",
    min_sample: int = MIN_SAMPLE_DEFAULT,
    historical: bool = False,
) -> dict[str, Any]:
    """Build a deterministic report without mutating ``signal_outcomes``."""
    if horizon not in {*HORIZONS, "all"}:
        return _unavailable("horizon_invalid", {"horizon": horizon})
    if not isinstance(min_sample, int) or isinstance(min_sample, bool) or min_sample < 1:
        return _unavailable("min_sample_invalid", {"min_sample": min_sample})

    rows = store.signal_outcomes(limit=500_000)
    dates = sorted({str(row.get("signal_date")) for row in rows if _parse_date(row.get("signal_date"))})
    if not dates:
        return _unavailable("sin_signal_outcomes", {"historical": historical})
    try:
        resolved_end = _resolve_end(end, dates)
        resolved_start = _resolve_start(start, resolved_end, dates, historical)
    except ValueError as exc:
        return _unavailable(str(exc), {"start": start, "end": end, "historical": historical})

    selected = [row for row in rows if resolved_start <= str(row.get("signal_date")) <= resolved_end]
    selected_horizons = HORIZONS if horizon == "all" else (horizon,)
    prepared, quality = _prepare_rows(selected, selected_horizons)
    horizon_reports = {item: _horizon_report(prepared, item, min_sample) for item in selected_horizons}
    group_reports = {item: _groups_for_horizon(prepared, item, min_sample) for item in selected_horizons}
    primary_horizon = EXCURSION_HORIZON if EXCURSION_HORIZON in selected_horizons else selected_horizons[0]
    report = {
        "schema_version": "p-l27b.excursion-quality.v2",
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
        "horizons": horizon_reports,
        "groups_by_return_horizon": group_reports,
        "primary_excursion_groups": group_reports[primary_horizon],
        "primary_return_horizon": primary_horizon,
        "concentration": _concentration(selected),
        "warnings": [
            "Informe descriptivo: retornos forward de senales, no P&L ejecutado ni evidencia causal.",
            "MFE/MAE son fracciones decimales respecto a entry_price y solo existen para excursion_horizon=10d.",
            "Las vistas return_horizon=1d/3d/5d relacionan retorno temprano con excursion_10d posterior; son observational_mismatched_horizon y no generan recomendaciones.",
            "Solo direction=long tiene geometria dimensionalmente verificada; short, ausente e invalida se excluyen explicitamente.",
            "No se calculan alpha, SPY, causalidad, significancia ni drawdown de cartera.",
        ],
    }
    report["content_hash"] = _content_hash(report)
    return report


def _prepare_rows(rows: Iterable[dict[str, Any]], horizons: tuple[str, ...]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    source_reasons: Counter[str] = Counter()
    horizon_reasons: Counter[str] = Counter()
    direction_counts: Counter[str] = Counter()
    maturity_by_horizon = {horizon: Counter() for horizon in horizons}
    selected_source_rows = 0
    selected_long_source_rows = 0
    valid_geometry_source_rows = 0

    for row in rows:
        selected_source_rows += 1
        features = row.get("features") if isinstance(row.get("features"), dict) else None
        outcome = row.get("outcome") if isinstance(row.get("outcome"), dict) else None
        source_reason = None
        direction_kind = "unknown_or_missing"
        if features is None or outcome is None:
            source_reason = "outcome_corrupt"
            direction_counts["unknown_or_missing"] += 1
        else:
            direction_kind = _direction_kind(features.get("direction"))
            direction_counts[direction_kind] += 1
            if direction_kind != "long":
                source_reason = f"direction_{direction_kind}"
            else:
                selected_long_source_rows += 1
                source_reason = _geometry_reason(
                    features.get("entry_price"),
                    features.get("stop_loss"),
                    features.get("take_profit"),
                    outcome.get("mfe_10d"),
                    outcome.get("mae_10d"),
                )
                if source_reason is None:
                    valid_geometry_source_rows += 1
        if source_reason is not None:
            source_reasons[source_reason] += 1

        for return_horizon in horizons:
            counts = maturity_by_horizon[return_horizon]
            counts["selected"] += 1
            forward = outcome.get(f"return_{return_horizon}") if outcome is not None else None
            if not _number(forward):
                counts["immature"] += 1
                continue
            counts["matured"] += 1
            if source_reason is not None:
                counts["excluded_matured"] += 1
                horizon_reasons[source_reason] += 1
                continue
            counts["valid_matured"] += 1
            prepared.append(_prepared_observation(row, features, outcome, return_horizon, float(forward)))

    selected_horizon_observations = selected_source_rows * len(horizons)
    matured_horizon_observations = sum(item["matured"] for item in maturity_by_horizon.values())
    immature_horizon_observations = sum(item["immature"] for item in maturity_by_horizon.values())
    valid_matured_horizon_observations = len(prepared)
    excluded_matured_horizon_observations = sum(item["excluded_matured"] for item in maturity_by_horizon.values())
    quality = {
        "source": "signal_outcomes",
        "selected_source_rows": selected_source_rows,
        "selected_long_source_rows": selected_long_source_rows,
        "direction_source_rows": dict(sorted(direction_counts.items())),
        "valid_geometry_source_rows": valid_geometry_source_rows,
        "excluded_source_rows": sum(source_reasons.values()),
        "exclusions_by_reason_source_rows": dict(sorted(source_reasons.items())),
        "geometry_coverage": _ratio(valid_geometry_source_rows, selected_long_source_rows),
        "selected_horizon_observations": selected_horizon_observations,
        "matured_horizon_observations": matured_horizon_observations,
        "immature_horizon_observations": immature_horizon_observations,
        "valid_matured_horizon_observations": valid_matured_horizon_observations,
        "excluded_matured_horizon_observations": excluded_matured_horizon_observations,
        "exclusions_by_reason_horizon_observations": dict(sorted(horizon_reasons.items())),
        "matured_valid_coverage": _ratio(valid_matured_horizon_observations, matured_horizon_observations),
        "maturity_by_horizon": {key: dict(value) for key, value in maturity_by_horizon.items()},
        "legacy_unverified_horizon_observations": sum(item["lineage_status"] == "legacy_unverified" for item in prepared),
        "verified_horizon_observations": sum(item["lineage_status"] == "verified" for item in prepared),
        "imputation_count": 0,
        "alpha": "unavailable",
        "spy_excess": "unavailable",
        "portfolio_drawdown": "unavailable",
    }
    return prepared, quality


def _prepared_observation(
    row: dict[str, Any], features: dict[str, Any], outcome: dict[str, Any], return_horizon: str, forward: float
) -> dict[str, Any]:
    entry = float(features["entry_price"])
    stop = float(features["stop_loss"])
    take = float(features["take_profit"])
    mfe = float(outcome["mfe_10d"])
    mae = float(outcome["mae_10d"])
    risk_distance = entry - stop
    reward_distance = take - entry
    stop_distance_pct = risk_distance / entry
    take_distance_pct = reward_distance / entry
    reward_risk_ratio = reward_distance / risk_distance
    mae_r = abs(min(mae, 0.0)) / stop_distance_pct
    mfe_r = max(mfe, 0.0) / stop_distance_pct
    target_attainment = max(mfe, 0.0) / take_distance_pct
    if not math.isclose(target_attainment, mfe_r / reward_risk_ratio, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError("target_attainment_invariant_failed")
    return {
        "return_horizon": return_horizon,
        "excursion_horizon": EXCURSION_HORIZON,
        "signal_date": row.get("signal_date"),
        "symbol": row.get("symbol"),
        "return": forward,
        "mfe_decimal": mfe,
        "mae_decimal": mae,
        "risk_distance_price": risk_distance,
        "reward_distance_price": reward_distance,
        "stop_distance_pct": stop_distance_pct,
        "take_distance_pct": take_distance_pct,
        "reward_risk_ratio": reward_risk_ratio,
        "mae_r": mae_r,
        "mfe_r": mfe_r,
        "target_r": reward_risk_ratio,
        "stop_consumption": mae_r,
        "target_attainment": target_attainment,
        "setup_quality": str(features.get("setup_quality") or "unknown"),
        "first_hit": _first_hit(outcome),
        "verdict": str(outcome.get("verdict") or "unknown"),
        "lineage_status": "verified" if _has_lineage(row) else "legacy_unverified",
    }


def _horizon_report(rows: list[dict[str, Any]], horizon: str, min_sample: int) -> dict[str, Any]:
    return _metrics([row for row in rows if row["return_horizon"] == horizon], min_sample, horizon)


def _groups_for_horizon(rows: list[dict[str, Any]], horizon: str, min_sample: int) -> dict[str, Any]:
    subset = [row for row in rows if row["return_horizon"] == horizon]
    return {
        "sample_unit": "source_row_x_return_horizon",
        "return_horizon": horizon,
        "excursion_horizon": EXCURSION_HORIZON,
        "stop_consumption": _bucket_report(subset, "stop_consumption", STOP_BUCKETS, min_sample, horizon),
        "target_attainment": _bucket_report(subset, "target_attainment", TARGET_BUCKETS, min_sample, horizon),
        "reward_risk_ratio": _bucket_report(subset, "reward_risk_ratio", RR_BUCKETS, min_sample, horizon),
        "setup_quality": _categorical_report(subset, "setup_quality", min_sample, horizon),
        "first_hit": _categorical_report(subset, "first_hit", min_sample, horizon),
        "verdict": _categorical_report(subset, "verdict", min_sample, horizon),
    }


def _bucket_report(rows: list[dict[str, Any]], key: str, buckets: tuple[tuple[float, float], ...], min_sample: int, horizon: str) -> dict[str, Any]:
    return {_bucket_label(low, high): _metrics([row for row in rows if _in_bucket(row.get(key), low, high)], min_sample, horizon) for low, high in buckets}


def _categorical_report(rows: list[dict[str, Any]], key: str, min_sample: int, horizon: str) -> dict[str, Any]:
    values = sorted({str(row.get(key) or "unknown") for row in rows})
    return {value: _metrics([row for row in rows if str(row.get(key) or "unknown") == value], min_sample, horizon) for value in values}


def _metrics(rows: list[dict[str, Any]], min_sample: int, return_horizon: str) -> dict[str, Any]:
    size = len(rows)
    if size == 0:
        status = "unavailable"
    elif size < min_sample:
        status = "insufficient_sample"
    else:
        status = "evaluable"
    def values(key: str) -> list[float]:
        return [row[key] for row in rows]
    stop_hits = sum(row["first_hit"] == "stop" for row in rows)
    take_hits = sum(row["first_hit"] == "take_profit" for row in rows)
    neither_hits = sum(row["first_hit"] == "neither" for row in rows)
    warnings = ["legacy_unverified_observations" if _lineage_status(rows) != "verified" else ""]
    if return_horizon != EXCURSION_HORIZON and size:
        warnings.append("observational_mismatched_horizon")
    return {
        "sample_size": size,
        "sample_unit": "source_row_x_return_horizon",
        "return_horizon": return_horizon,
        "excursion_horizon": EXCURSION_HORIZON,
        "mean_return": _mean(values("return")), "median_return": _median(values("return")),
        "positive_rate": _ratio(sum(value > 0 for value in values("return")), size),
        "mean_mfe_decimal": _mean(values("mfe_decimal")), "median_mfe_decimal": _median(values("mfe_decimal")),
        "mean_mae_decimal": _mean(values("mae_decimal")), "median_mae_decimal": _median(values("mae_decimal")),
        "mean_mfe_r": _mean(values("mfe_r")), "median_mfe_r": _median(values("mfe_r")),
        "mean_mae_r": _mean(values("mae_r")), "median_mae_r": _median(values("mae_r")),
        "mean_stop_consumption": _mean(values("stop_consumption")),
        "mean_target_attainment": _mean(values("target_attainment")),
        "stop_hit_rate": _ratio(stop_hits, size), "take_hit_rate": _ratio(take_hits, size),
        "neither_hit_rate": _ratio(neither_hits, size),
        "mean_reward_risk_ratio": _mean(values("reward_risk_ratio")), "median_reward_risk_ratio": _median(values("reward_risk_ratio")),
        "status": status,
        "evidence_status": "descriptive_only",
        "lineage_status": _lineage_status(rows),
        "data_quality_warnings": [warning for warning in warnings if warning],
    }


def _geometry_reason(entry: Any, stop: Any, take: Any, mfe: Any, mae: Any) -> str | None:
    for name, value in (("entry", entry), ("stop", stop), ("take", take), ("mfe", mfe), ("mae", mae)):
        if not _number(value):
            return f"{name}_non_numeric_or_missing"
    if entry <= 0:
        return "entry_zero_or_negative"
    if stop >= entry:
        return "stop_ge_entry"
    if take <= entry:
        return "take_le_entry"
    return None


def _direction_kind(value: Any) -> str:
    if value is None or not str(value).strip():
        return "unknown_or_missing"
    normalized = str(value).strip().lower()
    if normalized == "long":
        return "long"
    if normalized == "short":
        return "short"
    return "invalid"


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _first_hit(outcome: dict[str, Any]) -> str:
    first = outcome.get("first_hit")
    if isinstance(first, dict):
        hit_type = str(first.get("type") or "").lower()
        if hit_type in {"stop", "stop_loss"}:
            return "stop"
        if hit_type in {"take", "take_profit"}:
            return "take_profit"
    if str(outcome.get("verdict") or "") in {"winner_open", "loser_open", "flat"}:
        return "neither"
    return "unknown"


def _has_lineage(row: dict[str, Any]) -> bool:
    features, outcome = row.get("features") or {}, row.get("outcome") or {}
    return bool(features.get("decision_lineage") or features.get("lineage_id") or outcome.get("decision_lineage"))


def _concentration(rows: list[dict[str, Any]]) -> dict[str, Any]:
    dates, symbols = Counter(str(row.get("signal_date")) for row in rows), Counter(str(row.get("symbol")) for row in rows)
    return {"unique_signal_dates": len(dates), "unique_symbols": len(symbols), "top_date": dates.most_common(1)[0] if dates else None, "top_symbol": symbols.most_common(1)[0] if symbols else None, "dependency_warning": "mismo dia/simbolo puede contener observaciones dependientes"}


def _resolve_end(value: str | None, dates: list[str]) -> str:
    if value:
        _parse_date(value, strict=True)
        return value
    return max((item for item in dates if item <= date.today().isoformat()), default=dates[-1])


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
    if math.isinf(high):
        return f">={low:g}"
    return f"[{low:.2f},{high:.2f})"


def _in_bucket(value: Any, low: float, high: float) -> bool:
    return _number(value) and value >= low and value < high


def _lineage_status(rows: list[dict[str, Any]]) -> str:
    statuses = {row["lineage_status"] for row in rows}
    return next(iter(statuses)) if len(statuses) == 1 else ("mixed" if statuses else "unavailable")


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 6) if values else None


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 6) if values else None


def _content_hash(report: dict[str, Any]) -> str:
    stable = {key: value for key, value in report.items() if key not in {"generated_at", "content_hash"}}
    return hashlib.sha256(json.dumps(stable, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _definitions() -> dict[str, str]:
    return {
        "entry_price_stop_loss_take_profit": "precios absolutos",
        "mfe_10d_mae_10d": "fracciones decimales respecto a entry_price, producidas por signal_learning.py",
        "risk_distance_price": "precio absoluto: entry_price - stop_loss",
        "reward_distance_price": "precio absoluto: take_profit - entry_price",
        "stop_distance_pct": "fraccion decimal: risk_distance_price / entry_price",
        "take_distance_pct": "fraccion decimal: reward_distance_price / entry_price",
        "reward_risk_ratio": "multiplo R: reward_distance_price / risk_distance_price",
        "mae_r": "multiplo R: abs(min(mae_decimal, 0)) / stop_distance_pct",
        "mfe_r": "multiplo R: max(mfe_decimal, 0) / stop_distance_pct",
        "target_attainment": "fraccion del target: max(mfe_decimal, 0) / take_distance_pct; igual a mfe_r / target_r",
        "v1_invalid": "Los mae_r, mfe_r y target_attainment de schema v1 mezclaban fraccion decimal con precio absoluto y no son comparables ni utilizables.",
    }


def _unavailable(reason: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": "p-l27b.excursion-quality.v2", "observational_only": True, "status": "unavailable", "reason": reason, "parameters": parameters, "content_hash": hashlib.sha256(reason.encode("utf-8")).hexdigest()}
