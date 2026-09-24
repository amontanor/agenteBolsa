"""Chronological probability calibration over a point-in-time artifact.

The boundary is intentionally offline.  It consumes a validated D2 dataset and
an explicit session-date mapping supplied by the data adapter; it does not read
Store, calendar providers, scheduler state, broker data or active decisions.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping
from datetime import date
from typing import Any

from .point_in_time_replay import (
    PointInTimeContractError,
    validate_point_in_time_dataset,
)

CALIBRATION_SCHEMA_VERSION = "p-l117i.calibration.v1"
DEFAULT_PURGE_SESSIONS = 5
DEFAULT_EMBARGO_SESSIONS = 1
DEFAULT_MIN_ROWS_PER_SPLIT = 3


class CalibrationContractError(PointInTimeContractError):
    """Raised when a calibration input cannot prove chronological isolation."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _positive_int(value: Any, field: str, *, allow_zero: bool = False) -> int:
    if type(value) is not int or (value < 0 if allow_zero else value <= 0):
        raise CalibrationContractError(f"cal_{field}_invalid")
    return value


def _session_date(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CalibrationContractError("cal_session_date_required")
    normalised = value.strip()
    try:
        parsed = date.fromisoformat(normalised)
    except ValueError as exc:
        raise CalibrationContractError("cal_session_date_invalid") from exc
    if parsed.isoformat() != normalised:
        raise CalibrationContractError("cal_session_date_invalid")
    return normalised


def _round(value: float | None) -> float | None:
    return round(value, 8) if value is not None else None


def _mean_ci95(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "estimate": None, "lower": None, "upper": None}
    estimate = sum(values) / len(values)
    if len(values) < 2:
        return {"n": len(values), "estimate": _round(estimate), "lower": None, "upper": None}
    variance = sum((value - estimate) ** 2 for value in values) / (len(values) - 1)
    margin = 1.96 * math.sqrt(variance / len(values))
    return {
        "n": len(values),
        "estimate": _round(estimate),
        "lower": _round(estimate - margin),
        "upper": _round(estimate + margin),
    }


def _brier(probabilities: list[float], outcomes: list[int]) -> float | None:
    if not probabilities:
        return None
    return sum((probability - outcome) ** 2 for probability, outcome in zip(probabilities, outcomes, strict=True)) / len(
        probabilities
    )


def _target(row: Mapping[str, Any], *, cost_bps: float, slippage_bps: float) -> int:
    friction = (cost_bps + slippage_bps) / 10000.0
    return int(float(row["gross_return"]) - friction > 0.0)


def _bin_index(probability: float, bin_count: int) -> int:
    return min(int(probability * bin_count), bin_count - 1)


def _fit_binned_calibrator(
    rows: list[Mapping[str, Any]],
    *,
    bin_count: int,
    fallback_rate: float,
    cost_bps: float,
    slippage_bps: float,
) -> dict[str, Any]:
    counts = [0] * bin_count
    positives = [0] * bin_count
    for row in rows:
        probability = float(row["predicted_probability"])
        index = _bin_index(probability, bin_count)
        counts[index] += 1
        positives[index] += _target(row, cost_bps=cost_bps, slippage_bps=slippage_bps)
    bins = []
    for index, count in enumerate(counts):
        probability = (positives[index] + 1.0) / (count + 2.0) if count else fallback_rate
        bins.append(
            {
                "bin": index,
                "lower": round(index / bin_count, 8),
                "upper": round((index + 1) / bin_count, 8),
                "count": count,
                "positive_count": positives[index],
                "probability": round(probability, 8),
            }
        )
    return {"bin_count": bin_count, "bins": bins, "fallback_rate": round(fallback_rate, 8), "fit_rows": len(rows)}


def _predict(model: Mapping[str, Any], probability: float) -> float:
    bin_count = int(model["bin_count"])
    return float(model["bins"][_bin_index(probability, bin_count)]["probability"])


def _rows_with_sessions(
    artifact: Mapping[str, Any],
    *,
    session_dates: Mapping[str, Any],
    variant: str,
) -> list[dict[str, Any]]:
    try:
        validated = validate_point_in_time_dataset(artifact)
    except PointInTimeContractError as exc:
        raise CalibrationContractError(str(exc)) from exc
    if not isinstance(session_dates, Mapping):
        raise CalibrationContractError("cal_session_dates_mapping_required")
    normalised_session_dates = {str(key): value for key, value in session_dates.items()}
    rows = [row for row in validated["rows"] if row["variant"] == variant]
    if not rows:
        return []
    row_ids = {str(row["signal_id"]) for row in rows}
    mapping_ids = set(normalised_session_dates)
    missing = sorted(row_ids - mapping_ids)
    if missing:
        raise CalibrationContractError("cal_session_date_missing:" + ",".join(missing))
    extras = sorted(mapping_ids - row_ids)
    if extras:
        raise CalibrationContractError("cal_session_date_extra:" + ",".join(extras))
    enriched = []
    for row in rows:
        enriched.append(
            {
                **copy.deepcopy(row),
                "session_date": _session_date(normalised_session_dates[row["signal_id"]]),
            }
        )
    enriched.sort(key=lambda row: (row["session_date"], row["prediction_at"], row["signal_id"]))
    return enriched


def _split_rows(
    rows: list[dict[str, Any]],
    *,
    train_sessions: int,
    calibration_sessions: int,
    test_sessions: int,
    purge_sessions: int,
    embargo_sessions: int,
) -> dict[str, Any] | None:
    sessions = sorted({row["session_date"] for row in rows})
    cursor = 0

    def take(count: int) -> list[str]:
        nonlocal cursor
        selected = sessions[cursor : cursor + count]
        cursor += count
        return selected

    train = take(train_sessions)
    purge_train_calibration = take(purge_sessions)
    calibration = take(calibration_sessions)
    purge_calibration_test = take(purge_sessions)
    embargo = take(embargo_sessions)
    test = take(test_sessions)
    if len(train) != train_sessions or len(calibration) != calibration_sessions or len(test) != test_sessions:
        return None
    if (
        len(purge_train_calibration) != purge_sessions
        or len(purge_calibration_test) != purge_sessions
        or len(embargo) != embargo_sessions
    ):
        return None

    membership = {
        "train": set(train),
        "calibration": set(calibration),
        "test": set(test),
        "purge_train_calibration": set(purge_train_calibration),
        "purge_calibration_test": set(purge_calibration_test),
        "embargo": set(embargo),
    }
    split_rows = {
        name: [row for row in rows if row["session_date"] in session_set]
        for name, session_set in membership.items()
    }
    return {
        "sessions": {
            "train": train,
            "purge_train_calibration": purge_train_calibration,
            "calibration": calibration,
            "purge_calibration_test": purge_calibration_test,
            "embargo": embargo,
            "test": test,
        },
        "rows": split_rows,
    }


def _split_summary(split: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "sessions": copy.deepcopy(split["sessions"]),
        "rows": {name: len(rows) for name, rows in split["rows"].items()},
    }


def _dataset_hash_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    return {key: report[key] for key in report if key != "report_hash"}


def _status_report(
    *,
    variant: str,
    dataset_hash: str,
    evaluation_as_of: str,
    parameters: Mapping[str, Any],
    split: Mapping[str, Any] | None,
    reasons: list[str],
    input_rows: int,
    available_rows: int,
) -> dict[str, Any]:
    status = "unavailable" if available_rows == 0 else ("collecting" if reasons else "ready")
    report: dict[str, Any] = {
        "schema_version": CALIBRATION_SCHEMA_VERSION,
        "dataset_hash": dataset_hash,
        "evaluation_as_of": evaluation_as_of,
        "variant": variant,
        "parameters": dict(parameters),
        "split": _split_summary(split) if split is not None else None,
        "denominators": {"input_rows": input_rows, "available_rows": available_rows},
        "status": status,
        "reasons": sorted(set(reasons)),
    }
    report["report_hash"] = _hash_payload(_dataset_hash_payload(report))
    return report


def build_point_in_time_calibration(
    artifact: Mapping[str, Any],
    *,
    session_dates: Mapping[str, Any],
    variant: str = "champion",
    train_sessions: int = 3,
    calibration_sessions: int = 2,
    test_sessions: int = 2,
    purge_sessions: int = DEFAULT_PURGE_SESSIONS,
    embargo_sessions: int = DEFAULT_EMBARGO_SESSIONS,
    min_rows_per_split: int = DEFAULT_MIN_ROWS_PER_SPLIT,
    candidate_bin_counts: tuple[int, ...] = (2, 3, 5),
) -> dict[str, Any]:
    """Fit a simple binned calibrator chronologically and score a blocked test.

    ``session_dates`` is an explicit adapter output.  This function does not
    infer exchange sessions from timestamps, which prevents a UTC date from
    being silently treated as an XNYS session.
    """

    try:
        validated = validate_point_in_time_dataset(artifact)
    except PointInTimeContractError as exc:
        raise CalibrationContractError(str(exc)) from exc
    normalised_variant = variant.strip().lower() if isinstance(variant, str) else ""
    if not normalised_variant:
        raise CalibrationContractError("cal_variant_required")
    train_sessions = _positive_int(train_sessions, "train_sessions")
    calibration_sessions = _positive_int(calibration_sessions, "calibration_sessions")
    test_sessions = _positive_int(test_sessions, "test_sessions")
    purge_sessions = _positive_int(purge_sessions, "purge_sessions", allow_zero=True)
    embargo_sessions = _positive_int(embargo_sessions, "embargo_sessions", allow_zero=True)
    min_rows_per_split = _positive_int(min_rows_per_split, "min_rows_per_split")
    if not candidate_bin_counts or any(
        type(value) is not int or value < 2 for value in candidate_bin_counts
    ):
        raise CalibrationContractError("cal_candidate_bins_invalid")
    rows = _rows_with_sessions(validated, session_dates=session_dates, variant=normalised_variant)
    parameters = {
        "train_sessions": train_sessions,
        "calibration_sessions": calibration_sessions,
        "test_sessions": test_sessions,
        "purge_sessions": purge_sessions,
        "embargo_sessions": embargo_sessions,
        "min_rows_per_split": min_rows_per_split,
        "candidate_bin_counts": list(candidate_bin_counts),
    }
    if not rows:
        return _status_report(
            variant=normalised_variant,
            dataset_hash=validated["dataset_hash"],
            evaluation_as_of=validated["evaluation_as_of"],
            parameters=parameters,
            split=None,
            reasons=["variant_unavailable"],
            input_rows=len(validated["rows"]),
            available_rows=0,
        )
    missing_probability = sum("predicted_probability" not in row for row in rows)
    if missing_probability:
        return _status_report(
            variant=normalised_variant,
            dataset_hash=validated["dataset_hash"],
            evaluation_as_of=validated["evaluation_as_of"],
            parameters=parameters,
            split=None,
            reasons=["predicted_probability_unavailable"],
            input_rows=len(validated["rows"]),
            available_rows=len(rows) - missing_probability,
        )

    split = _split_rows(
        rows,
        train_sessions=train_sessions,
        calibration_sessions=calibration_sessions,
        test_sessions=test_sessions,
        purge_sessions=purge_sessions,
        embargo_sessions=embargo_sessions,
    )
    if split is None:
        return _status_report(
            variant=normalised_variant,
            dataset_hash=validated["dataset_hash"],
            evaluation_as_of=validated["evaluation_as_of"],
            parameters=parameters,
            split=None,
            reasons=["insufficient_sessions"],
            input_rows=len(validated["rows"]),
            available_rows=len(rows),
        )
    short_rows = [name for name in ("train", "calibration", "test") if len(split["rows"][name]) < min_rows_per_split]
    if short_rows:
        return _status_report(
            variant=normalised_variant,
            dataset_hash=validated["dataset_hash"],
            evaluation_as_of=validated["evaluation_as_of"],
            parameters=parameters,
            split=split,
            reasons=["insufficient_rows:" + ",".join(short_rows)],
            input_rows=len(validated["rows"]),
            available_rows=len(rows),
        )

    train_rows = split["rows"]["train"]
    calibration_rows = split["rows"]["calibration"]
    test_rows = split["rows"]["test"]
    train_outcomes = [_target(row, cost_bps=validated["cost_bps"], slippage_bps=validated["slippage_bps"]) for row in train_rows]
    calibration_outcomes = [
        _target(row, cost_bps=validated["cost_bps"], slippage_bps=validated["slippage_bps"])
        for row in calibration_rows
    ]
    test_outcomes = [_target(row, cost_bps=validated["cost_bps"], slippage_bps=validated["slippage_bps"]) for row in test_rows]
    base_rate = (sum(train_outcomes) + 1.0) / (len(train_outcomes) + 2.0)
    calibration_probabilities = [float(row["predicted_probability"]) for row in calibration_rows]
    selection = []
    for bin_count in candidate_bin_counts:
        candidate = _fit_binned_calibrator(
            train_rows,
            bin_count=bin_count,
            fallback_rate=base_rate,
            cost_bps=validated["cost_bps"],
            slippage_bps=validated["slippage_bps"],
        )
        candidate_predictions = [_predict(candidate, probability) for probability in calibration_probabilities]
        selection.append(
            {
                "bin_count": bin_count,
                "brier": _round(_brier(candidate_predictions, calibration_outcomes)),
            }
        )
    selected_bin_count = min(selection, key=lambda item: (float(item["brier"]), item["bin_count"]))["bin_count"]
    fitted_rows = train_rows + calibration_rows
    final_model = _fit_binned_calibrator(
        fitted_rows,
        bin_count=selected_bin_count,
        fallback_rate=base_rate,
        cost_bps=validated["cost_bps"],
        slippage_bps=validated["slippage_bps"],
    )
    champion_probabilities = [float(row["predicted_probability"]) for row in test_rows]
    calibrated_probabilities = [_predict(final_model, probability) for probability in champion_probabilities]
    base_probabilities = [base_rate] * len(test_rows)
    signal_deltas = [
        (calibrated - outcome) ** 2 - (champion - outcome) ** 2
        for calibrated, champion, outcome in zip(calibrated_probabilities, champion_probabilities, test_outcomes, strict=True)
    ]
    session_deltas: dict[str, list[float]] = defaultdict(list)
    for row, delta in zip(test_rows, signal_deltas, strict=True):
        session_deltas[row["session_date"]].append(delta)
    metrics = {
        "sample_unit": "signal",
        "train_rows": len(train_rows),
        "calibration_rows": len(calibration_rows),
        "test_rows": len(test_rows),
        "test_sessions": len({row["session_date"] for row in test_rows}),
        "positive_rate_test": _round(sum(test_outcomes) / len(test_outcomes)),
        "brier_champion_test": _round(_brier(champion_probabilities, test_outcomes)),
        "brier_base_rate_test": _round(_brier(base_probabilities, test_outcomes)),
        "brier_calibrated_test": _round(_brier(calibrated_probabilities, test_outcomes)),
        "brier_delta_calibrated_vs_champion": _round(sum(signal_deltas) / len(signal_deltas)),
        "brier_delta_ci95_by_signal": _mean_ci95(signal_deltas),
        "brier_delta_ci95_by_session": _mean_ci95(
            [sum(values) / len(values) for values in session_deltas.values()]
        ),
    }
    report: dict[str, Any] = {
        "schema_version": CALIBRATION_SCHEMA_VERSION,
        "dataset_hash": validated["dataset_hash"],
        "evaluation_as_of": validated["evaluation_as_of"],
        "variant": normalised_variant,
        "parameters": parameters,
        "split": _split_summary(split),
        "denominators": {
            "input_rows": len(validated["rows"]),
            "available_rows": len(rows),
            "train_rows": len(train_rows),
            "calibration_rows": len(calibration_rows),
            "test_rows": len(test_rows),
            "purged_rows": len(split["rows"]["purge_train_calibration"])
            + len(split["rows"]["purge_calibration_test"]),
            "embargoed_rows": len(split["rows"]["embargo"]),
        },
        "status": "ready",
        "reasons": [],
        "model": {
            "method": "laplace_smoothed_equal_width_bins",
            "baseline_fit_scope": "train_only",
            "calibrator_fit_scope": "train_plus_calibration",
            "selected_bin_count": selected_bin_count,
            "selection_on": "calibration_only",
            "selection": selection,
            "base_rate": round(base_rate, 8),
            "bins": final_model["bins"],
        },
        "metrics": metrics,
    }
    report["report_hash"] = _hash_payload(_dataset_hash_payload(report))
    return report


def validate_point_in_time_calibration(report: Mapping[str, Any]) -> dict[str, Any]:
    """Verify the calibration report's schema and tamper-evident hash."""

    if not isinstance(report, Mapping):
        raise CalibrationContractError("cal_report_mapping_required")
    if report.get("schema_version") != CALIBRATION_SCHEMA_VERSION:
        raise CalibrationContractError("cal_schema_version_mismatch")
    expected = _hash_payload(_dataset_hash_payload(report))
    if report.get("report_hash") != expected:
        raise CalibrationContractError("cal_report_hash_mismatch")
    return copy.deepcopy(dict(report))
