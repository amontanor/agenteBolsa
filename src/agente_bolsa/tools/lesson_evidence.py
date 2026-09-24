"""Offline, versioned evidence and consumption records for useful lessons.

This module is an observation boundary only.  It does not write Store state,
promote a lesson, alter prompts, or grant authority to a consumer.  A lesson
can become promotion-eligible only after an independent validator has supplied
versioned evidence; inconclusive and weakened results remain explicit.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

LESSON_EVIDENCE_SCHEMA_VERSION = "p-l117h.lesson-evidence.v1"
LESSON_CONSUMPTION_SCHEMA_VERSION = "p-l117h.lesson-consumption.v1"
_VALIDATION_STATUSES = frozenset({"hypothesis", "validated", "inconclusive", "weakened", "retired"})
_OUTCOME_STATUSES = frozenset({"matured", "collecting", "unavailable"})
_EPSILON = 1e-12


class LessonEvidenceError(ValueError):
    """Raised when lesson evidence or consumption cannot be compared safely."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _text(value: Any, field: str, *, required: bool = True) -> str | None:
    if value is None or isinstance(value, bool):
        if required:
            raise LessonEvidenceError(f"lesson_{field}_required")
        return None
    text = str(value).strip()
    if not text:
        if required:
            raise LessonEvidenceError(f"lesson_{field}_required")
        return None
    if len(text) > 500:
        raise LessonEvidenceError(f"lesson_{field}_too_long")
    return text


def _utc(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise LessonEvidenceError(f"lesson_{field}_invalid") from exc
    else:
        raise LessonEvidenceError(f"lesson_{field}_required")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LessonEvidenceError(f"lesson_{field}_timezone_required")
    return parsed.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _finite_number(value: Any, field: str) -> float:
    if value is None or isinstance(value, bool):
        raise LessonEvidenceError(f"lesson_{field}_required")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise LessonEvidenceError(f"lesson_{field}_invalid") from exc
    if not math.isfinite(parsed):
        raise LessonEvidenceError(f"lesson_{field}_invalid")
    return parsed


def _probability(value: Any, field: str) -> float:
    parsed = _finite_number(value, field)
    if not -_EPSILON <= parsed <= 1.0 + _EPSILON:
        raise LessonEvidenceError(f"lesson_{field}_out_of_range")
    return min(1.0, max(0.0, parsed))


def _nonnegative_int(value: Any, field: str) -> int:
    if type(value) is not int or value < 0:
        raise LessonEvidenceError(f"lesson_{field}_invalid")
    return value


def _refs(value: Any, field: str, *, required: bool = True) -> list[str]:
    if value is None:
        if required:
            raise LessonEvidenceError(f"lesson_{field}_required")
        return []
    if isinstance(value, (str, bytes, Mapping)):
        raise LessonEvidenceError(f"lesson_{field}_invalid")
    try:
        items = list(value)
    except TypeError as exc:
        raise LessonEvidenceError(f"lesson_{field}_invalid") from exc
    result: list[str] = []
    for item in items:
        text = _text(item, field)
        if text is not None:
            result.append(text)
    result = sorted(set(result))
    if required and not result:
        raise LessonEvidenceError(f"lesson_{field}_required")
    return result


def _scope(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise LessonEvidenceError("lesson_scope_mapping_required")
    allowed = {"scope_type", "scope_key", "regime", "strategy", "horizon", "symbols"}
    unknown = sorted(set(value) - allowed, key=str)
    if unknown:
        raise LessonEvidenceError("lesson_scope_unknown_fields:" + ",".join(str(item) for item in unknown))
    result = {
        "scope_type": _text(value.get("scope_type"), "scope_type"),
        "scope_key": _text(value.get("scope_key"), "scope_key"),
    }
    for field in ("regime", "strategy", "horizon"):
        parsed = _text(value.get(field), field, required=False)
        if parsed is not None:
            result[field] = parsed
    if "symbols" in value:
        result["symbols"] = _refs(value.get("symbols"), "scope_symbols")
    return result


def _counterexamples(value: Any, *, evaluation_as_of: datetime) -> list[dict[str, Any]]:
    if value is None or isinstance(value, (str, bytes, Mapping)):
        raise LessonEvidenceError("lesson_counterexamples_required")
    try:
        items = list(value)
    except TypeError as exc:
        raise LessonEvidenceError("lesson_counterexamples_invalid") from exc
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    allowed = {"case_id", "evidence_refs", "reason", "observed_at"}
    for item in items:
        if not isinstance(item, Mapping):
            raise LessonEvidenceError("lesson_counterexample_mapping_required")
        unknown = sorted(set(item) - allowed, key=str)
        if unknown:
            raise LessonEvidenceError("lesson_counterexample_unknown_fields:" + ",".join(str(key) for key in unknown))
        case_id = _text(item.get("case_id"), "counterexample_case_id")
        if case_id in seen:
            raise LessonEvidenceError("lesson_counterexample_duplicate")
        seen.add(case_id)
        observed_at = _utc(item.get("observed_at"), "counterexample_observed_at")
        if observed_at > evaluation_as_of:
            raise LessonEvidenceError("lesson_counterexample_after_evaluation_as_of")
        result.append(
            {
                "case_id": case_id,
                "evidence_refs": _refs(item.get("evidence_refs"), "counterexample_evidence_refs"),
                "reason": _text(item.get("reason"), "counterexample_reason"),
                "observed_at": _utc_text(observed_at),
            }
        )
    return sorted(result, key=lambda item: item["case_id"])


def _validation(value: Any, *, origin_run_id: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise LessonEvidenceError("lesson_validation_mapping_required")
    allowed = {
        "status",
        "validation_run_id",
        "validator_id",
        "independent",
        "evidence_refs",
        "supporting_cases",
        "contradicting_cases",
    }
    unknown = sorted(set(value) - allowed, key=str)
    if unknown:
        raise LessonEvidenceError("lesson_validation_unknown_fields:" + ",".join(str(item) for item in unknown))
    status = (_text(value.get("status"), "validation_status") or "").lower()
    if status not in _VALIDATION_STATUSES:
        raise LessonEvidenceError("lesson_validation_status_invalid")
    validation_run_id = _text(value.get("validation_run_id"), "validation_run_id", required=False)
    validator_id = _text(value.get("validator_id"), "validator_id", required=False)
    independent = value.get("independent")
    if type(independent) is not bool:
        raise LessonEvidenceError("lesson_validation_independent_invalid")
    evidence_refs = _refs(value.get("evidence_refs"), "validation_evidence_refs", required=False)
    supporting = _nonnegative_int(value.get("supporting_cases", 0), "validation_supporting_cases")
    contradicting = _nonnegative_int(value.get("contradicting_cases", 0), "validation_contradicting_cases")
    if status == "validated":
        if not validation_run_id or not validator_id or not independent:
            raise LessonEvidenceError("lesson_validation_not_independent")
        if validation_run_id == origin_run_id:
            raise LessonEvidenceError("lesson_validation_same_as_origin")
        if not evidence_refs or supporting <= 0:
            raise LessonEvidenceError("lesson_validation_evidence_insufficient")
    elif status in {"inconclusive", "weakened", "retired"} and not validation_run_id:
        raise LessonEvidenceError("lesson_validation_run_id_required")
    return {
        "status": status,
        "validation_run_id": validation_run_id,
        "validator_id": validator_id,
        "independent": independent,
        "evidence_refs": evidence_refs,
        "supporting_cases": supporting,
        "contradicting_cases": contradicting,
    }


def _artifact_without_hash(artifact: Mapping[str, Any]) -> dict[str, Any]:
    return {key: artifact[key] for key in artifact if key != "lesson_hash"}


def build_lesson_evidence(
    lesson: Mapping[str, Any],
    *,
    evaluation_as_of: Any,
) -> dict[str, Any]:
    """Build a strict, hashed lesson artifact without activating it."""

    if not isinstance(lesson, Mapping):
        raise LessonEvidenceError("lesson_mapping_required")
    allowed = {
        "lesson_id",
        "lesson_version",
        "origin_run_id",
        "cause",
        "evidence_refs",
        "counterexamples",
        "scope",
        "valid_from",
        "valid_until",
        "validation",
    }
    unknown = sorted(set(lesson) - allowed, key=str)
    if unknown:
        raise LessonEvidenceError("lesson_unknown_fields:" + ",".join(str(item) for item in unknown))
    evaluation = _utc(evaluation_as_of, "evaluation_as_of")
    valid_from = _utc(lesson.get("valid_from"), "valid_from")
    valid_until = _utc(lesson.get("valid_until"), "valid_until")
    if valid_until <= valid_from:
        raise LessonEvidenceError("lesson_validity_interval_invalid")
    if valid_from > evaluation:
        raise LessonEvidenceError("lesson_valid_from_after_evaluation_as_of")
    origin_run_id = _text(lesson.get("origin_run_id"), "origin_run_id")
    validation = _validation(lesson.get("validation"), origin_run_id=origin_run_id)
    counterexamples = _counterexamples(lesson.get("counterexamples"), evaluation_as_of=evaluation)
    if validation["status"] == "validated" and not counterexamples:
        raise LessonEvidenceError("lesson_counterexamples_required_for_validation")
    artifact = {
        "schema_version": LESSON_EVIDENCE_SCHEMA_VERSION,
        "lesson_id": _text(lesson.get("lesson_id"), "lesson_id"),
        "lesson_version": _text(lesson.get("lesson_version"), "lesson_version"),
        "origin_run_id": origin_run_id,
        "cause": _text(lesson.get("cause"), "cause"),
        "evidence_refs": _refs(lesson.get("evidence_refs"), "evidence_refs"),
        "counterexamples": counterexamples,
        "scope": _scope(lesson.get("scope")),
        "valid_from": _utc_text(valid_from),
        "valid_until": _utc_text(valid_until),
        "evaluation_as_of": _utc_text(evaluation),
        "validation": validation,
    }
    artifact["lesson_hash"] = _hash_payload(_artifact_without_hash(artifact))
    return artifact


def validate_lesson_evidence(artifact: Mapping[str, Any], *, as_of: Any) -> dict[str, Any]:
    """Validate a lesson and state why it can or cannot be promoted."""

    if not isinstance(artifact, Mapping):
        raise LessonEvidenceError("lesson_artifact_mapping_required")
    supplied_hash = artifact.get("lesson_hash")
    payload = {key: artifact[key] for key in artifact if key != "lesson_hash"}
    if payload.get("schema_version") != LESSON_EVIDENCE_SCHEMA_VERSION:
        raise LessonEvidenceError("lesson_schema_version_mismatch")
    lesson_payload = {
        key: payload[key] for key in payload if key not in {"schema_version", "evaluation_as_of"}
    }
    rebuilt = build_lesson_evidence(lesson_payload, evaluation_as_of=payload.get("evaluation_as_of"))
    if supplied_hash != rebuilt["lesson_hash"]:
        raise LessonEvidenceError("lesson_hash_mismatch")
    current = _utc(as_of, "as_of")
    expired = current > _utc(rebuilt["valid_until"], "valid_until")
    validation = rebuilt["validation"]
    blockers: list[str] = []
    if validation["status"] != "validated":
        blockers.append(f"validation_status:{validation['status']}")
    if not validation["independent"]:
        blockers.append("independent_validation_required")
    if expired:
        blockers.append("lesson_expired")
    if current < _utc(rebuilt["valid_from"], "valid_from"):
        blockers.append("lesson_not_yet_valid")
    if not rebuilt["counterexamples"]:
        blockers.append("counterexamples_required")
    return {
        "valid": True,
        "lesson_id": rebuilt["lesson_id"],
        "lesson_version": rebuilt["lesson_version"],
        "lesson_hash": rebuilt["lesson_hash"],
        "status": validation["status"],
        "expired": expired,
        "promotion_eligible": not blockers,
        "promotion_blockers": blockers,
        "artifact": copy.deepcopy(rebuilt),
    }


def _consumption_without_hash(record: Mapping[str, Any]) -> dict[str, Any]:
    return {key: record[key] for key in record if key != "consumption_hash"}


def _normalise_outcomes(value: Any, *, consumed_at: datetime, evaluation_as_of: datetime) -> tuple[list[dict[str, Any]], int]:
    if value is None or isinstance(value, (str, bytes, Mapping)):
        raise LessonEvidenceError("lesson_outcomes_required")
    try:
        items = list(value)
    except TypeError as exc:
        raise LessonEvidenceError("lesson_outcomes_invalid") from exc
    result: list[dict[str, Any]] = []
    by_signal: dict[str, str] = {}
    duplicates = 0
    allowed = {
        "signal_id",
        "prediction_at",
        "predicted_probability",
        "outcome_status",
        "outcome_matured_at",
        "outcome_value",
        "prediction_error",
        "absolute_error",
    }
    for item in items:
        if not isinstance(item, Mapping):
            raise LessonEvidenceError("lesson_outcome_mapping_required")
        unknown = sorted(set(item) - allowed, key=str)
        if unknown:
            raise LessonEvidenceError("lesson_outcome_unknown_fields:" + ",".join(str(key) for key in unknown))
        prediction_at = _utc(item.get("prediction_at"), "prediction_at")
        if prediction_at > consumed_at:
            raise LessonEvidenceError("lesson_prediction_after_consumption")
        status = (_text(item.get("outcome_status"), "outcome_status") or "").lower()
        if status not in _OUTCOME_STATUSES:
            raise LessonEvidenceError("lesson_outcome_status_invalid")
        matured_value = item.get("outcome_matured_at")
        matured_at = _utc(matured_value, "outcome_matured_at") if matured_value is not None else None
        if status == "matured":
            if matured_at is None or matured_at <= prediction_at or matured_at <= consumed_at:
                raise LessonEvidenceError("lesson_matured_outcome_not_posterior")
            if matured_at > evaluation_as_of:
                raise LessonEvidenceError("lesson_outcome_after_evaluation_as_of")
            outcome_value = _probability(item.get("outcome_value"), "outcome_value")
        else:
            if matured_at is not None and matured_at <= prediction_at:
                raise LessonEvidenceError("lesson_outcome_maturity_invalid")
            if matured_at is not None and matured_at <= evaluation_as_of:
                raise LessonEvidenceError("lesson_unresolved_matured_outcome")
            if item.get("outcome_value") is not None:
                raise LessonEvidenceError("lesson_unresolved_outcome_value")
            outcome_value = None
        predicted = _probability(item.get("predicted_probability"), "predicted_probability")
        signal_id = _text(item.get("signal_id"), "signal_id")
        expected_error = round(outcome_value - predicted, 8) if outcome_value is not None else None
        expected_absolute_error = abs(expected_error) if expected_error is not None else None
        for field, expected in (
            ("prediction_error", expected_error),
            ("absolute_error", expected_absolute_error),
        ):
            if field not in item:
                continue
            supplied = item.get(field)
            if expected is None:
                if supplied is not None:
                    raise LessonEvidenceError(f"lesson_{field}_mismatch")
            elif not math.isclose(_finite_number(supplied, field), expected, abs_tol=_EPSILON):
                raise LessonEvidenceError(f"lesson_{field}_mismatch")
        normalised = {
            "signal_id": signal_id,
            "prediction_at": _utc_text(prediction_at),
            "predicted_probability": predicted,
            "outcome_status": status,
            "outcome_matured_at": _utc_text(matured_at) if matured_at is not None else None,
            "outcome_value": outcome_value,
            "prediction_error": expected_error,
            "absolute_error": round(expected_absolute_error, 8) if expected_absolute_error is not None else None,
        }
        fingerprint = _canonical_json(normalised)
        previous = by_signal.get(signal_id)
        if previous is not None:
            if previous != fingerprint:
                raise LessonEvidenceError("lesson_signal_outcome_conflict")
            duplicates += 1
            continue
        by_signal[signal_id] = fingerprint
        result.append(normalised)
    return sorted(result, key=lambda row: (row["prediction_at"], row["signal_id"])), duplicates


def record_lesson_consumption(
    *,
    run_id: Any,
    consumed_at: Any,
    outcomes: Iterable[Mapping[str, Any]],
    lesson_artifact: Mapping[str, Any],
    evaluation_as_of: Any,
) -> dict[str, Any]:
    """Record one run's exact lesson version and later error observations."""

    artifact_check = validate_lesson_evidence(lesson_artifact, as_of=evaluation_as_of)
    consumed = _utc(consumed_at, "consumed_at")
    evaluation = _utc(evaluation_as_of, "evaluation_as_of")
    if consumed > evaluation:
        raise LessonEvidenceError("lesson_consumed_after_evaluation_as_of")
    normalised_outcomes, duplicates = _normalise_outcomes(
        outcomes,
        consumed_at=consumed,
        evaluation_as_of=evaluation,
    )
    record = {
        "schema_version": LESSON_CONSUMPTION_SCHEMA_VERSION,
        "run_id": _text(run_id, "run_id"),
        "lesson_id": artifact_check["lesson_id"],
        "lesson_version": artifact_check["lesson_version"],
        "lesson_hash": artifact_check["lesson_hash"],
        "consumed_at": _utc_text(consumed),
        "evaluation_as_of": _utc_text(evaluation),
        "outcomes": normalised_outcomes,
        "denominators": {
            "input_rows": len(normalised_outcomes) + duplicates,
            "unique_rows": len(normalised_outcomes),
            "idempotent_duplicates": duplicates,
            "matured_rows": sum(row["outcome_status"] == "matured" for row in normalised_outcomes),
            "collecting_rows": sum(row["outcome_status"] == "collecting" for row in normalised_outcomes),
            "unavailable_rows": sum(row["outcome_status"] == "unavailable" for row in normalised_outcomes),
        },
    }
    mature = [row for row in normalised_outcomes if row["outcome_status"] == "matured"]
    pending = [row for row in normalised_outcomes if row["outcome_status"] != "matured"]
    if not normalised_outcomes:
        status = "unavailable"
    elif pending:
        status = "collecting"
    else:
        status = "ready"
    record["status"] = status
    record["metrics"] = {
        "mean_prediction_error": round(sum(row["prediction_error"] for row in mature) / len(mature), 8)
        if mature
        else None,
        "mean_absolute_error": round(sum(row["absolute_error"] for row in mature) / len(mature), 8)
        if mature
        else None,
    }
    record["promotion_eligible"] = False
    record["promotion_reason"] = "consumption_is_observational"
    record["consumption_hash"] = _hash_payload(_consumption_without_hash(record))
    return record


def validate_lesson_consumption(
    record: Mapping[str, Any],
    *,
    lesson_artifact: Mapping[str, Any],
    evaluation_as_of: Any,
) -> dict[str, Any]:
    """Validate a consumption hash and the exact lesson identity it records."""

    if not isinstance(record, Mapping):
        raise LessonEvidenceError("lesson_consumption_mapping_required")
    supplied_hash = record.get("consumption_hash")
    payload = {key: record[key] for key in record if key != "consumption_hash"}
    if payload.get("schema_version") != LESSON_CONSUMPTION_SCHEMA_VERSION:
        raise LessonEvidenceError("lesson_consumption_schema_version_mismatch")
    if supplied_hash != _hash_payload(payload):
        raise LessonEvidenceError("lesson_consumption_hash_mismatch")
    rebuilt = record_lesson_consumption(
        run_id=payload.get("run_id"),
        consumed_at=payload.get("consumed_at"),
        outcomes=payload.get("outcomes"),
        lesson_artifact=lesson_artifact,
        evaluation_as_of=evaluation_as_of,
    )
    if payload.get("lesson_id") != rebuilt["lesson_id"] or payload.get("lesson_version") != rebuilt["lesson_version"]:
        raise LessonEvidenceError("lesson_consumption_identity_mismatch")
    if payload.get("lesson_hash") != rebuilt["lesson_hash"]:
        raise LessonEvidenceError("lesson_consumption_lesson_hash_mismatch")
    for field in ("outcomes", "status", "metrics", "promotion_eligible", "promotion_reason"):
        if payload.get(field) != rebuilt.get(field):
            raise LessonEvidenceError(f"lesson_consumption_{field}_mismatch")
    payload_denominators = payload.get("denominators")
    rebuilt_denominators = rebuilt["denominators"]
    if not isinstance(payload_denominators, Mapping):
        raise LessonEvidenceError("lesson_consumption_denominators_invalid")
    for field in ("unique_rows", "matured_rows", "collecting_rows", "unavailable_rows"):
        if payload_denominators.get(field) != rebuilt_denominators[field]:
            raise LessonEvidenceError(f"lesson_consumption_denominator_{field}_mismatch")
    duplicates = _nonnegative_int(payload_denominators.get("idempotent_duplicates"), "idempotent_duplicates")
    if payload_denominators.get("input_rows") != payload_denominators.get("unique_rows") + duplicates:
        raise LessonEvidenceError("lesson_consumption_denominator_input_rows_mismatch")
    return {"valid": True, "record": copy.deepcopy(dict(record)), "promotion_eligible": False}
