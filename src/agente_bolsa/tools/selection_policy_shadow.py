"""Offline comparison of one selection/abstention change against controls.

The report keeps champion, one proposed change and a comparable control on the
same point-in-time snapshots.  It is deliberately a shadow artifact: sizing,
exits, risk, execution and active policy authority are outside this contract.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

SELECTION_SHADOW_SCHEMA_VERSION = "p-l117k.selection-policy-shadow.v1"
DEFAULT_VARIANTS = ("champion", "single_change", "comparable_control")
_UNCHANGED_BOUNDARIES = frozenset({"sizing", "exit", "risk", "execution"})
_EPSILON = 1e-12


class SelectionShadowError(ValueError):
    """Raised when a selection shadow comparison is not safe to compare."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _text(value: Any, field: str) -> str:
    if value is None or isinstance(value, bool) or not str(value).strip():
        raise SelectionShadowError(f"selection_{field}_required")
    text = str(value).strip()
    if len(text) > 500:
        raise SelectionShadowError(f"selection_{field}_too_long")
    return text


def _number(value: Any, field: str) -> float:
    if value is None or isinstance(value, bool):
        raise SelectionShadowError(f"selection_{field}_required")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise SelectionShadowError(f"selection_{field}_invalid") from exc
    if not math.isfinite(parsed):
        raise SelectionShadowError(f"selection_{field}_invalid")
    return parsed


def _utc(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise SelectionShadowError(f"selection_{field}_invalid") from exc
    else:
        raise SelectionShadowError(f"selection_{field}_required")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SelectionShadowError(f"selection_{field}_timezone_required")
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
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _variants(value: Iterable[str]) -> list[str]:
    result = [_text(item, "variant").lower() for item in value]
    if not result or len(result) != len(set(result)):
        raise SelectionShadowError("selection_variants_invalid")
    return result


def _normalise_change(value: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"change_id", "change_type", "description", "unchanged_boundaries"}
    unknown = sorted(set(value) - allowed, key=str)
    if unknown:
        raise SelectionShadowError("selection_change_unknown_fields:" + ",".join(str(item) for item in unknown))
    change_type = _text(value.get("change_type"), "change_type").lower()
    if change_type not in {"selection", "abstention"}:
        raise SelectionShadowError("selection_change_type_invalid")
    boundaries = value.get("unchanged_boundaries")
    if isinstance(boundaries, (str, bytes, Mapping)):
        raise SelectionShadowError("selection_unchanged_boundaries_invalid")
    try:
        normalised_boundaries = {_text(item, "unchanged_boundary").lower() for item in boundaries}
    except TypeError as exc:
        raise SelectionShadowError("selection_unchanged_boundaries_invalid") from exc
    if normalised_boundaries != _UNCHANGED_BOUNDARIES:
        raise SelectionShadowError("selection_unchanged_boundaries_incomplete")
    return {
        "change_id": _text(value.get("change_id"), "change_id"),
        "change_type": change_type,
        "description": _text(value.get("description"), "change_description"),
        "unchanged_boundaries": sorted(normalised_boundaries),
    }


def _normalise_row(row: Mapping[str, Any], *, evaluation_as_of: datetime) -> dict[str, Any]:
    allowed = {
        "snapshot_id",
        "signal_id",
        "variant",
        "captured_at",
        "outcome_matured_at",
        "selected",
        "gross_return",
        "benchmark_return",
        "selection_score",
        "abstention_reason",
        "policy_version",
    }
    unknown = sorted(set(row) - allowed, key=str)
    if unknown:
        raise SelectionShadowError("selection_row_unknown_fields:" + ",".join(str(item) for item in unknown))
    captured_at = _utc(row.get("captured_at"), "captured_at")
    matured_at = _utc(row.get("outcome_matured_at"), "outcome_matured_at")
    if matured_at <= captured_at:
        raise SelectionShadowError("selection_outcome_before_capture")
    if matured_at > evaluation_as_of:
        raise SelectionShadowError("selection_outcome_after_evaluation_as_of")
    selected = row.get("selected")
    if type(selected) is not bool:
        raise SelectionShadowError("selection_selected_invalid")
    reason = row.get("abstention_reason")
    if selected:
        if reason not in (None, ""):
            raise SelectionShadowError("selection_selected_has_abstention_reason")
        normalised_reason = None
    else:
        normalised_reason = _text(reason, "abstention_reason")
    benchmark = row.get("benchmark_return")
    score = row.get("selection_score")
    return {
        "snapshot_id": _text(row.get("snapshot_id"), "snapshot_id"),
        "signal_id": _text(row.get("signal_id"), "signal_id"),
        "variant": _text(row.get("variant"), "variant").lower(),
        "captured_at": _utc_text(captured_at),
        "outcome_matured_at": _utc_text(matured_at),
        "selected": selected,
        "gross_return": _number(row.get("gross_return"), "gross_return"),
        "benchmark_return": _number(benchmark, "benchmark_return") if benchmark is not None else None,
        "selection_score": _number(score, "selection_score") if score is not None else None,
        "abstention_reason": normalised_reason,
        "policy_version": _text(row.get("policy_version"), "policy_version") if row.get("policy_version") else None,
    }


def _normalise_rows(
    rows: Iterable[Mapping[str, Any]], *, evaluation_as_of: datetime
) -> tuple[list[dict[str, Any]], int]:
    result: list[dict[str, Any]] = []
    by_identity: dict[tuple[str, str], str] = {}
    duplicates = 0
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise SelectionShadowError("selection_row_mapping_required")
        normalised = _normalise_row(raw, evaluation_as_of=evaluation_as_of)
        identity = (normalised["snapshot_id"], normalised["variant"])
        fingerprint = _canonical_json(normalised)
        previous = by_identity.get(identity)
        if previous is not None:
            if previous != fingerprint:
                raise SelectionShadowError("selection_snapshot_variant_conflict")
            duplicates += 1
            continue
        by_identity[identity] = fingerprint
        result.append(normalised)
    return sorted(result, key=lambda item: (item["captured_at"], item["snapshot_id"], item["variant"])), duplicates


def _variant_metrics(rows: list[dict[str, Any]], *, friction: float) -> dict[str, Any]:
    selected = [row for row in rows if row["selected"]]
    net_returns = [float(row["gross_return"]) - friction for row in selected]
    benchmark = [float(row["benchmark_return"]) for row in selected if row["benchmark_return"] is not None]
    return {
        "sample_unit": "snapshot_signal",
        "rows": len(rows),
        "selected_rows": len(selected),
        "abstained_count": len(rows) - len(selected),
        "coverage": _round(len(selected) / len(rows)) if rows else None,
        "expectancy_net": _round(sum(net_returns) / len(net_returns)) if net_returns else None,
        "p10_net": _round(_p10(net_returns)),
        "positive_rate": _round(sum(value > 0.0 for value in net_returns) / len(net_returns)) if net_returns else None,
        "total_net_return": _round(sum(net_returns)) if net_returns else None,
        "benchmark_alpha": _round(sum(value - benchmark_value for value, benchmark_value in zip(net_returns, benchmark, strict=True)) / len(benchmark))
        if benchmark and len(benchmark) == len(net_returns)
        else None,
        "selection_score_mean": _round(
            sum(float(row["selection_score"]) for row in selected if row["selection_score"] is not None)
            / len([row for row in selected if row["selection_score"] is not None])
        )
        if any(row["selection_score"] is not None for row in selected)
        else None,
    }


def _pairwise(
    left: list[dict[str, Any]], right: list[dict[str, Any]], *, friction: float
) -> dict[str, Any]:
    left_by_snapshot = {row["snapshot_id"]: row for row in left}
    right_by_snapshot = {row["snapshot_id"]: row for row in right}
    common = sorted(set(left_by_snapshot) & set(right_by_snapshot))
    left_selected = [left_by_snapshot[snapshot] for snapshot in common if left_by_snapshot[snapshot]["selected"]]
    right_selected = [right_by_snapshot[snapshot] for snapshot in common if right_by_snapshot[snapshot]["selected"]]
    left_returns = [float(row["gross_return"]) - friction for row in left_selected]
    right_returns = [float(row["gross_return"]) - friction for row in right_selected]
    changed = [snapshot for snapshot in common if left_by_snapshot[snapshot]["selected"] != right_by_snapshot[snapshot]["selected"]]
    avoided_losers = [
        snapshot
        for snapshot in changed
        if left_by_snapshot[snapshot]["selected"]
        and not right_by_snapshot[snapshot]["selected"]
        and float(left_by_snapshot[snapshot]["gross_return"]) - friction < 0.0
    ]
    missed_winners = [
        snapshot
        for snapshot in changed
        if not left_by_snapshot[snapshot]["selected"]
        and right_by_snapshot[snapshot]["selected"]
        and float(right_by_snapshot[snapshot]["gross_return"]) - friction > 0.0
    ]
    return {
        "paired_rows": len(common),
        "paired_coverage_left": _round(len(left_selected) / len(common)) if common else None,
        "paired_coverage_right": _round(len(right_selected) / len(common)) if common else None,
        "coverage_delta_right_vs_left": _round(len(right_selected) / len(common) - len(left_selected) / len(common))
        if common
        else None,
        "expectancy_net_delta_right_vs_left": _round(
            (sum(right_returns) / len(right_returns) if right_returns else 0.0)
            - (sum(left_returns) / len(left_returns) if left_returns else 0.0)
        ),
        "p10_net_delta_right_vs_left": _round((_p10(right_returns) or 0.0) - (_p10(left_returns) or 0.0)),
        "total_net_return_delta_right_vs_left": _round(sum(right_returns) - sum(left_returns)),
        "selection_changes": len(changed),
        "avoided_losers": len(avoided_losers),
        "missed_winners": len(missed_winners),
    }


def _without_hash(report: Mapping[str, Any]) -> dict[str, Any]:
    return {key: report[key] for key in report if key != "report_hash"}


def build_selection_policy_shadow(
    rows: Iterable[Mapping[str, Any]],
    *,
    evaluation_as_of: Any,
    change: Mapping[str, Any],
    cost_bps: int | float,
    variants: Iterable[str] = DEFAULT_VARIANTS,
    min_rows_per_variant: int = 3,
) -> dict[str, Any]:
    """Build a same-snapshot comparison for exactly one shadow change."""

    if not isinstance(change, Mapping):
        raise SelectionShadowError("selection_change_mapping_required")
    evaluation = _utc(evaluation_as_of, "evaluation_as_of")
    friction_bps = _number(cost_bps, "cost_bps")
    if friction_bps < 0:
        raise SelectionShadowError("selection_cost_invalid")
    if type(min_rows_per_variant) is not int or min_rows_per_variant <= 0:
        raise SelectionShadowError("selection_min_rows_invalid")
    expected_variants = _variants(variants)
    required_variants = set(DEFAULT_VARIANTS)
    if set(expected_variants) != required_variants:
        raise SelectionShadowError("selection_variants_must_include_champion_change_control")
    normalised_rows, duplicates = _normalise_rows(rows, evaluation_as_of=evaluation)
    by_variant = {variant: [row for row in normalised_rows if row["variant"] == variant] for variant in expected_variants}
    present = sorted({row["variant"] for row in normalised_rows})
    unexpected = sorted(set(present) - set(expected_variants))
    if unexpected:
        raise SelectionShadowError("selection_unexpected_variant:" + ",".join(unexpected))
    identity_by_snapshot: dict[str, tuple[str, str, str, float, float | None]] = {}
    for row in normalised_rows:
        identity = (
            row["signal_id"],
            row["captured_at"],
            row["outcome_matured_at"],
            row["gross_return"],
            row["benchmark_return"],
        )
        previous = identity_by_snapshot.setdefault(row["snapshot_id"], identity)
        if previous != identity:
            raise SelectionShadowError("selection_snapshot_identity_conflict")
    reasons: list[str] = []
    for variant in expected_variants:
        if len(by_variant[variant]) < min_rows_per_variant:
            reasons.append(f"insufficient_rows:{variant}")
    snapshot_sets = {variant: {row["snapshot_id"] for row in by_variant[variant]} for variant in expected_variants}
    available_sets = [value for value in snapshot_sets.values() if value]
    if len(available_sets) < len(expected_variants):
        reasons.append("variant_unavailable")
    elif any(value != available_sets[0] for value in available_sets[1:]):
        reasons.append("snapshot_set_not_comparable")
    status = "unavailable" if not normalised_rows else ("collecting" if reasons else "ready")
    change_payload = _normalise_change(change)
    report: dict[str, Any] = {
        "schema_version": SELECTION_SHADOW_SCHEMA_VERSION,
        "evaluation_as_of": _utc_text(evaluation),
        "cost_bps": friction_bps,
        "variants": expected_variants,
        "change": change_payload,
        "status": status,
        "application_status": "shadow_only",
        "active_authority": "none",
        "promotion_eligible": False,
        "promotion_reason": "selection_shadow_requires_independent_review_and_mature_economic_evidence",
        "reasons": sorted(set(reasons)),
        "denominators": {
            "input_rows": len(normalised_rows) + duplicates,
            "unique_rows": len(normalised_rows),
            "idempotent_duplicates": duplicates,
            "variant_rows": {variant: len(by_variant[variant]) for variant in expected_variants},
            "comparable_snapshots": len(set.intersection(*available_sets)) if available_sets else 0,
        },
        "metrics_by_variant": {},
        "pairwise_vs_champion": {},
    }
    friction = friction_bps / 10000.0
    for variant in expected_variants:
        report["metrics_by_variant"][variant] = _variant_metrics(by_variant[variant], friction=friction)
    champion = by_variant["champion"]
    for variant in ("single_change", "comparable_control"):
        report["pairwise_vs_champion"][variant] = _pairwise(
            champion,
            by_variant[variant],
            friction=friction,
        )
    report["report_hash"] = _hash_payload(_without_hash(report))
    return report


def validate_selection_policy_shadow(report: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the shadow report hash and non-authoritative application state."""

    if not isinstance(report, Mapping):
        raise SelectionShadowError("selection_report_mapping_required")
    if report.get("schema_version") != SELECTION_SHADOW_SCHEMA_VERSION:
        raise SelectionShadowError("selection_schema_version_mismatch")
    if report.get("application_status") != "shadow_only" or report.get("active_authority") != "none":
        raise SelectionShadowError("selection_active_authority_forbidden")
    if report.get("promotion_eligible") is not False:
        raise SelectionShadowError("selection_promotion_forbidden")
    if report.get("report_hash") != _hash_payload(_without_hash(report)):
        raise SelectionShadowError("selection_report_hash_mismatch")
    return copy.deepcopy(dict(report))
