"""Offline ablation of deterministic, individual and grouped predictions.

The report compares the same point-in-time snapshots across variants.  It is a
measurement boundary only: it does not vote, promote memory, call an agent or
alter selection, sizing, risk or execution.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

ABLATION_SCHEMA_VERSION = "p-l117j.agent-group-ablation.v1"
DEFAULT_VARIANTS = ("deterministic", "individual", "group", "no_specialist")

_ALLOWED_FIELDS = {
    "snapshot_id",
    "signal_id",
    "variant",
    "captured_at",
    "outcome_matured_at",
    "predicted_probability",
    "predicted_return",
    "gross_return",
    "abstained",
    "agent_probabilities",
    "latency_ms",
    "cost_usd",
    "model_version",
    "prompt_version",
    "memory_version",
}
_EPSILON = 1e-12


class AblationContractError(ValueError):
    """Raised when a same-snapshot ablation cannot be compared safely."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AblationContractError(f"ablation_{field}_required")
    return value.strip()


def _number(value: Any, field: str) -> float:
    if value is None or value == "" or isinstance(value, bool):
        raise AblationContractError(f"ablation_{field}_required")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise AblationContractError(f"ablation_{field}_invalid") from exc
    if not math.isfinite(parsed):
        raise AblationContractError(f"ablation_{field}_invalid")
    return parsed


def _probability(value: Any, field: str) -> float:
    parsed = _number(value, field)
    if not 0.0 <= parsed <= 1.0:
        raise AblationContractError(f"ablation_{field}_invalid")
    return parsed


def _utc(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise AblationContractError(f"ablation_{field}_invalid") from exc
    else:
        raise AblationContractError(f"ablation_{field}_required")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AblationContractError(f"ablation_{field}_timezone_required")
    return parsed.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _round(value: float | None) -> float | None:
    return round(value, 8) if value is not None else None


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


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _normalise_row(row: Mapping[str, Any], *, evaluation_as_of: datetime) -> dict[str, Any]:
    unknown = sorted(set(row) - _ALLOWED_FIELDS, key=str)
    if unknown:
        raise AblationContractError(f"ablation_unknown_fields:{','.join(str(item) for item in unknown)}")
    captured_at = _utc(row.get("captured_at"), "captured_at")
    matured_at = _utc(row.get("outcome_matured_at"), "outcome_matured_at")
    if matured_at <= captured_at:
        raise AblationContractError("ablation_outcome_before_capture")
    if matured_at > evaluation_as_of:
        raise AblationContractError("ablation_outcome_after_evaluation_as_of")
    abstained = row.get("abstained")
    if type(abstained) is not bool:
        raise AblationContractError("ablation_abstained_invalid")
    latency = _number(row.get("latency_ms"), "latency_ms")
    cost = _number(row.get("cost_usd"), "cost_usd")
    if latency < 0 or cost < 0:
        raise AblationContractError("ablation_operational_metric_invalid")
    probabilities = row.get("agent_probabilities")
    if not isinstance(probabilities, Mapping):
        raise AblationContractError("ablation_agent_probabilities_mapping_required")
    normalised_probabilities: dict[str, float] = {}
    for agent_id, probability in sorted(probabilities.items(), key=lambda item: str(item[0])):
        normalised_probabilities[_text(agent_id, "agent_id")] = _probability(probability, "agent_probability")
    return {
        "snapshot_id": _text(row.get("snapshot_id"), "snapshot_id"),
        "signal_id": _text(row.get("signal_id"), "signal_id"),
        "variant": _text(row.get("variant"), "variant").lower(),
        "captured_at": _utc_text(captured_at),
        "outcome_matured_at": _utc_text(matured_at),
        "predicted_probability": _probability(row.get("predicted_probability"), "predicted_probability"),
        "predicted_return": _number(row.get("predicted_return"), "predicted_return"),
        "gross_return": _number(row.get("gross_return"), "gross_return"),
        "abstained": abstained,
        "agent_probabilities": normalised_probabilities,
        "latency_ms": latency,
        "cost_usd": cost,
        "model_version": _text(row.get("model_version"), "model_version") if row.get("model_version") else None,
        "prompt_version": _text(row.get("prompt_version"), "prompt_version") if row.get("prompt_version") else None,
        "memory_version": _text(row.get("memory_version"), "memory_version") if row.get("memory_version") else None,
    }


def _normalise_variants(variants: Iterable[str]) -> list[str]:
    result = [_text(value, "variant").lower() for value in variants]
    if len(set(result)) != len(result) or not result:
        raise AblationContractError("ablation_variants_invalid")
    return result


def _normalise_collection(
    rows: Iterable[Mapping[str, Any]], *, evaluation_as_of: datetime
) -> tuple[list[dict[str, Any]], int]:
    result: list[dict[str, Any]] = []
    by_identity: dict[tuple[str, str], str] = {}
    fingerprints: set[str] = set()
    duplicates = 0
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise AblationContractError("ablation_row_mapping_required")
        normalised = _normalise_row(raw, evaluation_as_of=evaluation_as_of)
        identity = (normalised["snapshot_id"], normalised["variant"])
        fingerprint = _canonical_json(normalised)
        if identity in by_identity and by_identity[identity] != fingerprint:
            raise AblationContractError("ablation_snapshot_variant_conflict")
        if fingerprint in fingerprints:
            duplicates += 1
            continue
        by_identity[identity] = fingerprint
        fingerprints.add(fingerprint)
        result.append(normalised)
    result.sort(key=lambda row: (row["captured_at"], row["snapshot_id"], row["variant"]))
    return result, duplicates


def _target(row: Mapping[str, Any], *, friction: float) -> int:
    return int(float(row["gross_return"]) - friction > 0.0)


def _variant_metrics(rows: list[dict[str, Any]], *, friction: float) -> dict[str, Any]:
    covered = [row for row in rows if not row["abstained"]]
    outcomes = [_target(row, friction=friction) for row in covered]
    probabilities = [float(row["predicted_probability"]) for row in covered]
    net_returns = [float(row["gross_return"]) - friction for row in covered]
    predicted_returns = [float(row["predicted_return"]) for row in covered]
    disagreement = []
    for row in rows:
        opinions = list(row["agent_probabilities"].values())
        if len(opinions) >= 2:
            mean = sum(opinions) / len(opinions)
            disagreement.append(sum(abs(value - mean) for value in opinions) / len(opinions))
    return {
        "sample_unit": "snapshot_signal",
        "rows": len(rows),
        "covered_rows": len(covered),
        "abstained_count": len(rows) - len(covered),
        "coverage": _round(len(covered) / len(rows)) if rows else None,
        "brier": _round(sum((probability - outcome) ** 2 for probability, outcome in zip(probabilities, outcomes, strict=True)) / len(probabilities))
        if probabilities
        else None,
        "expectancy_net": _round(sum(net_returns) / len(net_returns)) if net_returns else None,
        "p10_net": _round(_p10(net_returns)),
        "positive_rate": _round(sum(outcomes) / len(outcomes)) if outcomes else None,
        "predicted_return_mae": _round(
            sum(abs(predicted - actual) for predicted, actual in zip(predicted_returns, net_returns, strict=True))
            / len(predicted_returns)
        )
        if predicted_returns
        else None,
        "disagreement_mean": _round(sum(disagreement) / len(disagreement)) if disagreement else None,
        "disagreement_rows": len(disagreement),
        "latency_p50_ms": _round(_percentile([float(row["latency_ms"]) for row in rows], 0.50)),
        "latency_p95_ms": _round(_percentile([float(row["latency_ms"]) for row in rows], 0.95)),
        "cost_total_usd": _round(sum(float(row["cost_usd"]) for row in rows)),
        "cost_mean_usd": _round(sum(float(row["cost_usd"]) for row in rows) / len(rows)) if rows else None,
    }


def _pair_metrics(
    left: list[dict[str, Any]], right: list[dict[str, Any]], *, friction: float
) -> dict[str, Any]:
    left_by_snapshot = {row["snapshot_id"]: row for row in left}
    right_by_snapshot = {row["snapshot_id"]: row for row in right}
    common = sorted(set(left_by_snapshot) & set(right_by_snapshot))
    covered = [
        snapshot
        for snapshot in common
        if not left_by_snapshot[snapshot]["abstained"] and not right_by_snapshot[snapshot]["abstained"]
    ]
    if not covered:
        return {"paired_rows": 0, "paired_coverage": _round(len(common) / max(len(left), len(right))) if common else 0.0}
    left_prob = [float(left_by_snapshot[snapshot]["predicted_probability"]) for snapshot in covered]
    right_prob = [float(right_by_snapshot[snapshot]["predicted_probability"]) for snapshot in covered]
    outcomes = [_target(left_by_snapshot[snapshot], friction=friction) for snapshot in covered]
    left_brier = sum((value - outcome) ** 2 for value, outcome in zip(left_prob, outcomes, strict=True)) / len(outcomes)
    right_brier = sum((value - outcome) ** 2 for value, outcome in zip(right_prob, outcomes, strict=True)) / len(outcomes)
    left_returns = [float(left_by_snapshot[snapshot]["gross_return"]) - friction for snapshot in covered]
    right_returns = [float(right_by_snapshot[snapshot]["gross_return"]) - friction for snapshot in covered]
    return {
        "paired_rows": len(covered),
        "paired_coverage": _round(len(covered) / max(len(left), len(right))),
        "brier_delta_vs_deterministic": _round(right_brier - left_brier),
        "expectancy_net_delta": _round(sum(right_returns) / len(right_returns) - sum(left_returns) / len(left_returns)),
        "p10_net_delta": _round((_p10(right_returns) or 0.0) - (_p10(left_returns) or 0.0)),
    }


def _report_hash_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    return {key: report[key] for key in report if key != "report_hash"}


def build_agent_group_ablation(
    rows: Iterable[Mapping[str, Any]],
    *,
    evaluation_as_of: Any,
    cost_bps: int | float,
    slippage_bps: int | float = 0,
    variants: Iterable[str] = DEFAULT_VARIANTS,
    min_rows_per_variant: int = 3,
) -> dict[str, Any]:
    """Compare variants on identical snapshots with no active authority."""

    evaluation = _utc(evaluation_as_of, "evaluation_as_of")
    friction_bps = _number(cost_bps, "cost_bps") + _number(slippage_bps, "slippage_bps")
    if friction_bps < 0:
        raise AblationContractError("ablation_cost_invalid")
    if type(min_rows_per_variant) is not int or min_rows_per_variant <= 0:
        raise AblationContractError("ablation_min_rows_invalid")
    expected_variants = _normalise_variants(variants)
    normalised_rows, duplicates = _normalise_collection(rows, evaluation_as_of=evaluation)
    by_variant = {variant: [row for row in normalised_rows if row["variant"] == variant] for variant in expected_variants}
    present_variants = sorted({row["variant"] for row in normalised_rows})
    unexpected = sorted(set(present_variants) - set(expected_variants))
    if unexpected:
        raise AblationContractError("ablation_unexpected_variant:" + ",".join(unexpected))
    reasons: list[str] = []
    for variant in expected_variants:
        if len(by_variant[variant]) < min_rows_per_variant:
            reasons.append(f"insufficient_rows:{variant}")
    snapshot_sets = {variant: {row["snapshot_id"] for row in by_variant[variant]} for variant in expected_variants}
    snapshot_identity: dict[str, tuple[str, str, str]] = {}
    for row in normalised_rows:
        identity = (row["signal_id"], row["captured_at"], row["outcome_matured_at"])
        previous = snapshot_identity.setdefault(row["snapshot_id"], identity)
        if previous != identity:
            raise AblationContractError("ablation_snapshot_identity_conflict")
    available_sets = [value for value in snapshot_sets.values() if value]
    if len(available_sets) < len(expected_variants):
        reasons.append("variant_unavailable")
    elif any(value != available_sets[0] for value in available_sets[1:]):
        reasons.append("snapshot_set_not_comparable")
    status = "unavailable" if not normalised_rows else ("collecting" if reasons else "ready")
    report: dict[str, Any] = {
        "schema_version": ABLATION_SCHEMA_VERSION,
        "evaluation_as_of": _utc_text(evaluation),
        "evaluation_contract_version": ABLATION_SCHEMA_VERSION,
        "cost_bps": float(cost_bps),
        "slippage_bps": float(slippage_bps),
        "variants": expected_variants,
        "status": status,
        "reasons": sorted(set(reasons)),
        "denominators": {
            "input_rows": len(normalised_rows) + duplicates,
            "unique_rows": len(normalised_rows),
            "idempotent_duplicates": duplicates,
            "variant_rows": {variant: len(by_variant[variant]) for variant in expected_variants},
            "comparable_snapshots": len(set.intersection(*available_sets)) if available_sets else 0,
        },
        "metrics_by_variant": {},
        "pairwise_vs_deterministic": {},
    }
    friction = friction_bps / 10000.0
    for variant in expected_variants:
        report["metrics_by_variant"][variant] = _variant_metrics(by_variant[variant], friction=friction)
    deterministic = by_variant.get("deterministic", [])
    for variant in expected_variants:
        if variant != "deterministic":
            report["pairwise_vs_deterministic"][variant] = _pair_metrics(
                deterministic, by_variant[variant], friction=friction
            )
    report["report_hash"] = _hash_payload(_report_hash_payload(report))
    return report


def validate_agent_group_ablation(report: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the ablation report's schema and tamper-evident hash."""

    if not isinstance(report, Mapping):
        raise AblationContractError("ablation_report_mapping_required")
    if report.get("schema_version") != ABLATION_SCHEMA_VERSION:
        raise AblationContractError("ablation_schema_version_mismatch")
    if report.get("evaluation_contract_version") != ABLATION_SCHEMA_VERSION:
        raise AblationContractError("ablation_contract_version_mismatch")
    if report.get("report_hash") != _hash_payload(_report_hash_payload(report)):
        raise AblationContractError("ablation_report_hash_mismatch")
    return copy.deepcopy(dict(report))
