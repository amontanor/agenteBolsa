"""Point-in-time dataset contract and deterministic offline replay.

This module is deliberately detached from Store, scheduler, broker and active
decision paths. It accepts already captured rows and makes temporal evidence
explicit before any outcome is used for replay metrics.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

DATASET_SCHEMA_VERSION = "p-l117d2.point-in-time-dataset.v1"
REPLAY_SCHEMA_VERSION = "p-l117d2.replay.v1"
DEFAULT_HORIZON_SESSIONS = 5


def _portfolio_metrics_unavailable() -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": "portfolio_replay_required",
        "sample_unit": "portfolio",
        "required_inputs": ["fills", "marks", "cash_flows", "costs"],
    }

_ALLOWED_FIELDS = {
    "signal_id",
    "signal_capture_id",
    "variant",
    "direction",
    "horizon_sessions",
    "feature_as_of",
    "prediction_at",
    "outcome_matured_at",
    "gross_return",
    "benchmark_return",
    "features",
    "predicted_probability",
    "predicted_return",
    "abstained",
    "model_version",
    "prompt_version",
    "memory_version",
}
_FUTURE_FEATURE_KEYS = {
    "benchmark_return",
    "exit_price",
    "fill_price",
    "filled_at",
    "gross_return",
    "mae",
    "mfe",
    "net_return",
    "outcome",
    "pnl",
    "return_1d",
    "return_3d",
    "return_5d",
    "return_10d",
}


class PointInTimeContractError(ValueError):
    """Raised when a row or artifact cannot prove its contract."""


class PointInTimeConflictError(PointInTimeContractError):
    """Raised when one canonical identity carries different content."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PointInTimeContractError(f"pit_{field}_required")
    return value.strip()


def _optional_text(value: Any, field: str) -> str | None:
    if value is None or value == "":
        return None
    return _text(value, field)


def _utc(value: Any, field: str, *, required: bool = True) -> datetime | None:
    if value is None or value == "":
        if required:
            raise PointInTimeContractError(f"pit_{field}_required")
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise PointInTimeContractError(f"pit_{field}_invalid") from exc
    else:
        raise PointInTimeContractError(f"pit_{field}_invalid")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PointInTimeContractError(f"pit_{field}_timezone_required")
    return parsed.astimezone(timezone.utc)


def _utc_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def _number(value: Any, field: str, *, required: bool = False) -> float | None:
    if value is None or value == "":
        if required:
            raise PointInTimeContractError(f"pit_{field}_required")
        return None
    if isinstance(value, bool):
        raise PointInTimeContractError(f"pit_{field}_invalid")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PointInTimeContractError(f"pit_{field}_invalid") from exc
    if not math.isfinite(number):
        raise PointInTimeContractError(f"pit_{field}_invalid")
    return number


def _strict_int(value: Any, field: str) -> int:
    if type(value) is not int:
        raise PointInTimeContractError(f"pit_{field}_required")
    return value


def _features_contain_future_value(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).strip().lower() in _FUTURE_FEATURE_KEYS:
                return True
            if _features_contain_future_value(nested):
                return True
    elif isinstance(value, list):
        return any(_features_contain_future_value(item) for item in value)
    return False


def _normalised_row(row: Mapping[str, Any], *, evaluation_as_of: datetime, horizon_sessions: int) -> dict[str, Any]:
    unknown = sorted(set(row) - _ALLOWED_FIELDS, key=str)
    if unknown:
        raise PointInTimeContractError(f"pit_unknown_fields:{','.join(str(item) for item in unknown)}")
    signal_id = _text(row.get("signal_id"), "signal_id")
    signal_capture_id = _text(row.get("signal_capture_id"), "signal_capture_id")
    variant = _text(row.get("variant"), "variant").lower()
    direction = _text(row.get("direction"), "direction").lower()
    if direction != "long":
        raise PointInTimeContractError("pit_direction_unsupported")
    row_horizon = _strict_int(row.get("horizon_sessions"), "horizon_sessions")
    if row_horizon != horizon_sessions:
        raise PointInTimeContractError("pit_horizon_mismatch")

    feature_as_of = _utc(row.get("feature_as_of"), "feature_as_of")
    prediction_at = _utc(row.get("prediction_at"), "prediction_at")
    if feature_as_of > prediction_at:
        raise PointInTimeContractError("pit_feature_after_prediction")
    features = row.get("features")
    if features is None:
        features = {}
    if not isinstance(features, Mapping):
        raise PointInTimeContractError("pit_features_mapping_required")
    if _features_contain_future_value(features):
        raise PointInTimeContractError("pit_features_contain_outcome")

    outcome_matured_at = _utc(row.get("outcome_matured_at"), "outcome_matured_at", required=False)
    if outcome_matured_at is not None and outcome_matured_at <= prediction_at:
        raise PointInTimeContractError("pit_outcome_before_prediction")
    gross_return = _number(row.get("gross_return"), "gross_return")
    benchmark_return = _number(row.get("benchmark_return"), "benchmark_return")
    probability = _number(row.get("predicted_probability"), "predicted_probability")
    if probability is not None and not 0.0 <= probability <= 1.0:
        raise PointInTimeContractError("pit_predicted_probability_invalid")
    predicted_return = _number(row.get("predicted_return"), "predicted_return")
    abstained = row.get("abstained", False)
    if type(abstained) is not bool:
        raise PointInTimeContractError("pit_abstained_invalid")

    normalised: dict[str, Any] = {
        "signal_id": signal_id,
        "signal_capture_id": signal_capture_id,
        "variant": variant,
        "direction": direction,
        "horizon_sessions": row_horizon,
        "feature_as_of": _utc_text(feature_as_of),
        "prediction_at": _utc_text(prediction_at),
        "outcome_matured_at": _utc_text(outcome_matured_at),
        "gross_return": gross_return,
        "features": copy.deepcopy(dict(features)),
        "abstained": abstained,
    }
    if benchmark_return is not None:
        normalised["benchmark_return"] = benchmark_return
    if probability is not None:
        normalised["predicted_probability"] = probability
    if predicted_return is not None:
        normalised["predicted_return"] = predicted_return
    for field in ("model_version", "prompt_version", "memory_version"):
        value = _optional_text(row.get(field), field)
        if value is not None:
            normalised[field] = value
    return normalised


def _exclusion(row: Mapping[str, Any], *, reason: str) -> dict[str, Any]:
    return {
        "signal_id": row["signal_id"],
        "signal_capture_id": row["signal_capture_id"],
        "prediction_at": row["prediction_at"],
        "outcome_matured_at": row.get("outcome_matured_at"),
        "reason": reason,
    }


def _dataset_hash_payload(artifact: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": artifact["schema_version"],
        "evaluation_contract_version": artifact["evaluation_contract_version"],
        "evaluation_as_of": artifact["evaluation_as_of"],
        "horizon_sessions": artifact["horizon_sessions"],
        "cost_bps": artifact["cost_bps"],
        "slippage_bps": artifact["slippage_bps"],
        "rows": artifact["rows"],
        "exclusions": artifact["exclusions"],
    }


def _status(*, rows: list[dict[str, Any]], exclusions: list[dict[str, Any]]) -> str:
    if rows and not exclusions:
        return "ready"
    if rows or exclusions:
        return "collecting"
    return "unavailable"


def build_point_in_time_dataset(
    rows: Iterable[Mapping[str, Any]],
    *,
    evaluation_as_of: Any,
    cost_bps: int | float,
    slippage_bps: int | float = 0,
    horizon_sessions: int = DEFAULT_HORIZON_SESSIONS,
) -> dict[str, Any]:
    """Build a deterministic, immutable-in-practice point-in-time artifact.

    Rows without a mature, available outcome remain visible in ``exclusions``.
    Identity conflicts and temporal-contract violations fail closed instead of
    silently selecting one row.
    """

    evaluation = _utc(evaluation_as_of, "evaluation_as_of")
    if type(horizon_sessions) is not int or horizon_sessions <= 0:
        raise PointInTimeContractError("pit_horizon_sessions_invalid")
    normalised_cost = _number(cost_bps, "cost_bps", required=True)
    normalised_slippage = _number(slippage_bps, "slippage_bps", required=True)
    if normalised_cost < 0 or normalised_slippage < 0:
        raise PointInTimeContractError("pit_cost_invalid")

    eligible: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    seen_by_signal: dict[str, str] = {}
    seen_by_capture: dict[str, str] = {}
    seen_fingerprints: set[str] = set()
    duplicate_count = 0

    input_rows = list(rows)
    for raw in input_rows:
        if not isinstance(raw, Mapping):
            raise PointInTimeContractError("pit_row_mapping_required")
        candidate = _normalised_row(raw, evaluation_as_of=evaluation, horizon_sessions=horizon_sessions)
        fingerprint = _canonical_json(candidate)
        signal_id = candidate["signal_id"]
        capture_id = candidate["signal_capture_id"]
        if signal_id in seen_by_signal and seen_by_signal[signal_id] != fingerprint:
            raise PointInTimeConflictError("pit_signal_id_conflict")
        if capture_id in seen_by_capture and seen_by_capture[capture_id] != fingerprint:
            raise PointInTimeConflictError("pit_signal_capture_id_conflict")
        if fingerprint in seen_fingerprints:
            duplicate_count += 1
            continue
        seen_by_signal[signal_id] = fingerprint
        seen_by_capture[capture_id] = fingerprint
        seen_fingerprints.add(fingerprint)

        matured_at = _utc(candidate.get("outcome_matured_at"), "outcome_matured_at", required=False)
        prediction_at = _utc(candidate["prediction_at"], "prediction_at")
        if prediction_at >= evaluation:
            exclusions.append(_exclusion(candidate, reason="prediction_after_evaluation_as_of"))
        elif matured_at is None:
            exclusions.append(_exclusion(candidate, reason="outcome_not_mature"))
        elif matured_at > evaluation:
            exclusions.append(_exclusion(candidate, reason="outcome_not_mature_as_of_evaluation"))
        elif candidate.get("gross_return") is None:
            exclusions.append(_exclusion(candidate, reason="outcome_unavailable"))
        else:
            eligible.append(candidate)

    eligible.sort(key=lambda item: (item["prediction_at"], item["signal_id"], item["signal_capture_id"]))
    exclusions.sort(key=lambda item: (item["prediction_at"], item["signal_id"], item["reason"]))
    warnings: list[str] = []
    missing_predictions = sum("predicted_probability" not in item for item in eligible)
    if missing_predictions:
        warnings.append("predicted_probability_unavailable")
    benchmark_available = sum("benchmark_return" in item for item in eligible)
    artifact: dict[str, Any] = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "evaluation_contract_version": DATASET_SCHEMA_VERSION,
        "evaluation_as_of": _utc_text(evaluation),
        "horizon_sessions": horizon_sessions,
        "cost_bps": normalised_cost,
        "slippage_bps": normalised_slippage,
        "rows": eligible,
        "exclusions": exclusions,
        "status": _status(rows=eligible, exclusions=exclusions),
        "warnings": warnings,
        "denominators": {
            "input_rows": len(input_rows),
            "unique_rows": len(eligible) + len(exclusions),
            "idempotent_duplicates": duplicate_count,
            "eligible_rows": len(eligible),
            "excluded_rows": len(exclusions),
            "benchmark_available_rows": benchmark_available,
            "prediction_available_rows": len(eligible) - missing_predictions,
            "exclusions_by_reason": dict(sorted(Counter(item["reason"] for item in exclusions).items())),
        },
    }
    artifact["dataset_hash"] = _hash_payload(_dataset_hash_payload(artifact))
    return artifact


def _validate_artifact_rows(artifact: Mapping[str, Any]) -> None:
    evaluation = _utc(artifact.get("evaluation_as_of"), "evaluation_as_of")
    horizon = artifact.get("horizon_sessions")
    if type(horizon) is not int or horizon <= 0:
        raise PointInTimeContractError("pit_horizon_sessions_invalid")
    rows = artifact.get("rows")
    if not isinstance(rows, list):
        raise PointInTimeContractError("pit_rows_list_required")
    seen_signal: set[str] = set()
    seen_capture: set[str] = set()
    previous_key: tuple[str, str, str] | None = None
    for row in rows:
        if not isinstance(row, Mapping):
            raise PointInTimeContractError("pit_row_mapping_required")
        normalised = _normalised_row(row, evaluation_as_of=evaluation, horizon_sessions=horizon)
        if _canonical_json(normalised) != _canonical_json(dict(row)):
            raise PointInTimeContractError("pit_row_not_canonical")
        signal_id = _text(row.get("signal_id"), "signal_id")
        capture_id = _text(row.get("signal_capture_id"), "signal_capture_id")
        if signal_id in seen_signal:
            raise PointInTimeConflictError("pit_signal_id_conflict")
        if capture_id in seen_capture:
            raise PointInTimeConflictError("pit_signal_capture_id_conflict")
        seen_signal.add(signal_id)
        seen_capture.add(capture_id)
        feature_as_of = _utc(row.get("feature_as_of"), "feature_as_of")
        prediction_at = _utc(row.get("prediction_at"), "prediction_at")
        matured_at = _utc(row.get("outcome_matured_at"), "outcome_matured_at")
        if feature_as_of > prediction_at or prediction_at >= matured_at or matured_at > evaluation:
            raise PointInTimeContractError("pit_temporal_order_invalid")
        if _number(row.get("gross_return"), "gross_return", required=True) is None:
            raise PointInTimeContractError("pit_gross_return_required")
        key = (str(row["prediction_at"]), signal_id, capture_id)
        if previous_key is not None and key < previous_key:
            raise PointInTimeContractError("pit_rows_not_canonically_ordered")
        previous_key = key


def validate_point_in_time_dataset(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Validate artifact identity, hash, temporal order and unique IDs."""

    if not isinstance(artifact, Mapping):
        raise PointInTimeContractError("pit_artifact_mapping_required")
    if artifact.get("schema_version") != DATASET_SCHEMA_VERSION:
        raise PointInTimeContractError("pit_schema_version_mismatch")
    if artifact.get("evaluation_contract_version") != DATASET_SCHEMA_VERSION:
        raise PointInTimeContractError("pit_contract_version_mismatch")
    _validate_artifact_rows(artifact)
    expected_hash = _hash_payload(_dataset_hash_payload(artifact))
    if artifact.get("dataset_hash") != expected_hash:
        raise PointInTimeContractError("pit_dataset_hash_mismatch")
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


def _signal_sequence_drawdown(values: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    drawdown = 0.0
    for value in values:
        equity *= 1.0 + value
        peak = max(peak, equity)
        if peak > 0:
            drawdown = max(drawdown, (peak - equity) / peak)
    return drawdown


def replay_point_in_time_dataset(
    artifact: Mapping[str, Any], *, variant: str | None = None
) -> dict[str, Any]:
    """Replay mature rows in canonical order without changing the artifact."""

    validated = validate_point_in_time_dataset(artifact)
    selected = validated["rows"]
    if variant is not None:
        selected = [row for row in selected if row["variant"] == _text(variant, "variant").lower()]
    friction = (validated["cost_bps"] + validated["slippage_bps"]) / 10000.0
    net_returns = [float(row["gross_return"]) - friction for row in selected]
    positive = [value for value in net_returns if value > 0]
    negative = [value for value in net_returns if value < 0]
    benchmark_pairs = [
        (net, float(row["benchmark_return"]))
        for row, net in zip(selected, net_returns, strict=True)
        if "benchmark_return" in row
    ]
    benchmark_values = [item[1] for item in benchmark_pairs]
    metrics = {
        "sample_unit": "signal",
        "count": len(net_returns),
        "abstained_count": sum(row["abstained"] for row in selected),
        "expectancy_net": round(sum(net_returns) / len(net_returns), 8) if net_returns else None,
        "hit_rate": round(len(positive) / len(net_returns), 6) if net_returns else None,
        "profit_factor": round(sum(positive) / abs(sum(negative)), 6)
        if negative and sum(negative)
        else (math.inf if positive else None),
        "signal_sequence_max_drawdown": round(_signal_sequence_drawdown(net_returns), 8),
        "p10_net": round(_p10(net_returns), 8) if net_returns else None,
        "benchmark_pairs": len(benchmark_pairs),
        "benchmark_coverage": round(len(benchmark_pairs) / len(net_returns), 6) if net_returns else None,
        "benchmark_expectancy": round(sum(benchmark_values) / len(benchmark_values), 8)
        if benchmark_values
        else None,
        "alpha_vs_benchmark": round(
            sum(net - benchmark for net, benchmark in benchmark_pairs) / len(benchmark_pairs), 8
        )
        if benchmark_pairs
        else None,
    }
    result: dict[str, Any] = {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "dataset_hash": validated["dataset_hash"],
        "evaluation_contract_version": validated["evaluation_contract_version"],
        "evaluation_as_of": validated["evaluation_as_of"],
        "horizon_sessions": validated["horizon_sessions"],
        "variant": variant.lower() if variant is not None else None,
        "status": "ready" if selected else "unavailable",
        "metric_scope": "signal",
        "metrics": metrics,
        "signal_metrics": dict(metrics),
        "portfolio_metrics": _portfolio_metrics_unavailable(),
    }
    result["replay_hash"] = _hash_payload(result)
    return result


def replay_all_variants(artifact: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Replay every variant in stable order for baseline/control comparison."""

    validated = validate_point_in_time_dataset(artifact)
    variants = sorted({row["variant"] for row in validated["rows"]})
    return [replay_point_in_time_dataset(validated, variant=variant) for variant in variants]
