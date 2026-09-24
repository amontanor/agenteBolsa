"""Shadow-only challenger ranking and promotion gates."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from agente_bolsa.tools.offline_challenger_backtest import (
    WINDOW_CONTRACT_VERSION,
    validate_window_descriptors,
)

THRESHOLDS = {
    "cost_bps": 20,
    "min_expectancy_net": 0.0,
    "min_hit_rate": 0.55,
    "min_profit_factor": 1.15,
    "max_drawdown": 0.08,
    "min_p10": -0.06,
    "min_windows": 3,
}
HYPOTHESIS_TAGS = ("rsi_high", "neutral_regime", "range_position", "orderly_breakout")
CHALLENGER_VALIDATION_SCHEMA_VERSION = "p-l118.challenger-validation.v1"
_VALIDATION_SOURCES = frozenset({"offline_challenger_backtest", "p-l117d1.windows.v1"})
CanonicalValidationResolver = Callable[[Mapping[str, Any]], Mapping[str, Any] | None]


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _metadata_text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _canonical_json(value: Mapping[str, Any]) -> str | None:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return None


def _mapping_hash(value: Mapping[str, Any]) -> str | None:
    payload = _canonical_json(value)
    if payload is None:
        return None
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _stats_provenance_compatible(
    stats: Mapping[str, Any],
    *,
    profile_key: str,
) -> bool:
    provenance = stats.get("provenance") if isinstance(stats.get("provenance"), Mapping) else stats
    source_profile = _metadata_text(provenance.get("profile_key") or provenance.get("source_profile_key"))
    source = (_metadata_text(provenance.get("source")) or "").lower()
    dataset_hash = _metadata_text(provenance.get("dataset_hash"))
    contract = _metadata_text(provenance.get("evaluation_contract_version"))
    return bool(
        source_profile == profile_key
        and source in _VALIDATION_SOURCES
        and dataset_hash
        and contract
    )


def _cost_compatible(stats: Mapping[str, Any], *, cost_bps: int) -> bool:
    declared = _number(stats.get("cost_bps"))
    return declared is not None and math.isclose(declared, float(cost_bps), rel_tol=0.0, abs_tol=1e-9)


def _numbers_match(left: Any, right: Any) -> bool:
    left_number = _number(left)
    right_number = _number(right)
    return (
        left_number is not None
        and right_number is not None
        and math.isclose(left_number, right_number, rel_tol=0.0, abs_tol=1e-9)
    )


def _window_is_valid(window: Any) -> bool:
    if not isinstance(window, Mapping):
        return False
    values = []
    for field in ("start", "end", "as_of"):
        value = _metadata_text(window.get(field))
        if not value:
            return False
        try:
            parsed = value.replace("Z", "+00:00")
            values.append(datetime.fromisoformat(parsed))
        except ValueError:
            return False
    start, end, as_of = values
    if start.tzinfo is None or end.tzinfo is None or as_of.tzinfo is None:
        return False
    return start < end <= as_of


def _canonical_statistical_resolution(
    resolved: Any,
    *,
    artifact: Mapping[str, Any],
    stats: Mapping[str, Any],
    candidate: Mapping[str, Any],
    profile_key: str,
    cost_bps: int,
) -> tuple[bool, str]:
    """Check the response from the trusted canonical evidence reader."""

    if not isinstance(resolved, Mapping) or resolved.get("status") != "verified":
        return False, "validation_artifact_provenance_unresolved"
    identity = artifact.get("identity")
    lineage = artifact.get("lineage")
    if (
        resolved.get("artifact_id") != artifact.get("artifact_id")
        or resolved.get("artifact_hash") != artifact.get("artifact_hash")
        or resolved.get("profile_key") != profile_key
        or resolved.get("identity") != identity
        or resolved.get("lineage") != lineage
        or resolved.get("dataset_hash") != artifact.get("dataset_hash")
        or resolved.get("evaluation_contract_version") != artifact.get("evaluation_contract_version")
        or not _cost_compatible(resolved, cost_bps=cost_bps)
        or resolved.get("window") != artifact.get("window")
        or resolved.get("maturity") != artifact.get("maturity")
        or resolved.get("control") != artifact.get("control")
        or resolved.get("validation_run_id") != artifact.get("validation_run_id")
        or resolved.get("validator_id") != artifact.get("validator_id")
        or resolved.get("independent") is not True
        or resolved.get("source") not in _VALIDATION_SOURCES
    ):
        return False, "validation_artifact_canonical_mismatch"
    source_refs = resolved.get("source_refs")
    if (
        not isinstance(source_refs, list)
        or not source_refs
        or any(not _metadata_text(value) for value in source_refs)
        or source_refs != artifact.get("evidence_refs")
        or resolved.get("source_adapters") != artifact.get("source_adapters")
    ):
        return False, "validation_artifact_canonical_evidence_missing"
    metrics = resolved.get("metrics")
    if not isinstance(metrics, Mapping):
        return False, "validation_artifact_canonical_metrics_missing"
    for field in ("dataset_hash", "evaluation_contract_version"):
        if metrics.get(field) != artifact.get(field):
            return False, "validation_artifact_canonical_metrics_mismatch"
    if not _cost_compatible(metrics, cost_bps=cost_bps):
        return False, "validation_artifact_canonical_metrics_mismatch"
    for field in ("expectancy_net", "expectancy_gross", "expectancy", "hit_rate", "profit_factor", "max_drawdown", "p10_net"):
        supplied = _number(stats.get(field))
        if supplied is not None and not _numbers_match(supplied, metrics.get(field)):
            return False, "validation_artifact_stats_mismatch"
    candidate_id = _metadata_text(candidate.get("candidate_id"))
    resolved_candidate_id = _metadata_text((identity or {}).get("candidate_id")) if isinstance(identity, Mapping) else None
    if candidate_id and resolved_candidate_id != candidate_id:
        return False, "validation_artifact_candidate_mismatch"
    return True, "independent_artifact_verified"


def _validate_statistical_artifact(
    artifact: Any,
    *,
    candidate: Mapping[str, Any],
    stats: Mapping[str, Any],
    profile_key: str,
    cost_bps: int,
    canonical_validation_resolver: CanonicalValidationResolver | None = None,
) -> dict[str, Any]:
    """Validate integrity first, then require canonical evidence resolution."""

    failure = {
        "validated": False,
        "status": "unavailable",
        "reason": "validation_artifact_required",
        "integrity_status": "missing",
    }
    if not isinstance(artifact, Mapping):
        return failure
    allowed = {
        "schema_version",
        "artifact_id",
        "artifact_hash",
        "status",
        "independent",
        "validation_run_id",
        "validator_id",
        "identity",
        "lineage",
        "dataset_hash",
        "evaluation_contract_version",
        "cost_bps",
        "window",
        "maturity",
        "control",
        "evidence_refs",
        "source_adapters",
    }
    if set(artifact) - allowed:
        return {**failure, "reason": "validation_artifact_unknown_fields", "integrity_status": "invalid"}
    supplied_hash = _metadata_text(artifact.get("artifact_hash"))
    payload = {key: artifact[key] for key in artifact if key != "artifact_hash"}
    expected_hash = _mapping_hash(payload)
    if not supplied_hash or supplied_hash != expected_hash:
        return {**failure, "reason": "validation_artifact_hash_invalid", "integrity_status": "invalid"}
    if artifact.get("schema_version") != CHALLENGER_VALIDATION_SCHEMA_VERSION:
        return {**failure, "reason": "validation_artifact_schema_invalid", "integrity_status": "invalid"}
    if _metadata_text(artifact.get("artifact_id")) is None:
        return {**failure, "reason": "validation_artifact_identity_missing", "integrity_status": "invalid"}
    if str(artifact.get("status") or "").strip().lower() != "validated":
        return {**failure, "reason": "validation_artifact_not_validated", "integrity_status": "invalid"}
    if artifact.get("independent") is not True:
        return {**failure, "reason": "validation_artifact_not_independent", "integrity_status": "invalid"}
    validation_run_id = _metadata_text(artifact.get("validation_run_id"))
    validator_id = _metadata_text(artifact.get("validator_id"))
    if not validation_run_id or not validator_id:
        return {**failure, "reason": "validation_artifact_validator_missing", "integrity_status": "invalid"}
    identity = artifact.get("identity")
    if not isinstance(identity, Mapping):
        return {**failure, "reason": "validation_artifact_identity_missing", "integrity_status": "invalid"}
    if _metadata_text(identity.get("profile_key")) != profile_key:
        return {**failure, "reason": "validation_artifact_profile_mismatch", "integrity_status": "invalid"}
    candidate_id = _metadata_text(candidate.get("candidate_id"))
    if candidate_id and _metadata_text(identity.get("candidate_id")) != candidate_id:
        return {**failure, "reason": "validation_artifact_candidate_mismatch", "integrity_status": "invalid"}
    for field in ("signal_id", "signal_capture_id", "signal_source_run_id"):
        expected = _metadata_text(candidate.get(field))
        supplied = _metadata_text(identity.get(field))
        if expected and supplied != expected:
            return {**failure, "reason": f"validation_artifact_{field}_mismatch", "integrity_status": "invalid"}
        if not supplied:
            return {**failure, "reason": f"validation_artifact_{field}_missing", "integrity_status": "invalid"}
    lineage = artifact.get("lineage")
    if not isinstance(lineage, Mapping):
        return {**failure, "reason": "validation_artifact_lineage_missing", "integrity_status": "invalid"}
    lineage_run_ids = lineage.get("agent_run_ids")
    if not isinstance(lineage_run_ids, list) or not lineage_run_ids or any(
        not _metadata_text(value) for value in lineage_run_ids
    ):
        return {**failure, "reason": "validation_artifact_lineage_incomplete", "integrity_status": "invalid"}
    if validation_run_id in {str(value).strip() for value in lineage_run_ids}:
        return {**failure, "reason": "validation_artifact_self_referential", "integrity_status": "invalid"}
    if not _metadata_text(lineage.get("source_run_id")) or not _metadata_text(lineage.get("cycle_id")):
        return {**failure, "reason": "validation_artifact_lineage_incomplete", "integrity_status": "invalid"}
    dataset_hash = _metadata_text(artifact.get("dataset_hash"))
    contract = _metadata_text(artifact.get("evaluation_contract_version"))
    if not dataset_hash or not contract:
        return {**failure, "reason": "validation_artifact_dataset_metadata_missing", "integrity_status": "invalid"}
    provenance = stats.get("provenance") if isinstance(stats.get("provenance"), Mapping) else stats
    if (
        not isinstance(provenance, Mapping)
        or _metadata_text(provenance.get("dataset_hash")) != dataset_hash
        or _metadata_text(provenance.get("evaluation_contract_version")) != contract
    ):
        return {**failure, "reason": "validation_artifact_stats_provenance_mismatch", "integrity_status": "valid"}
    if not _cost_compatible(artifact, cost_bps=cost_bps):
        return {**failure, "reason": "validation_artifact_cost_mismatch", "integrity_status": "invalid"}
    if not _cost_compatible(stats, cost_bps=cost_bps):
        return {**failure, "reason": "validation_artifact_stats_cost_mismatch", "integrity_status": "valid"}
    window = artifact.get("window")
    if not _window_is_valid(window):
        return {**failure, "reason": "validation_artifact_window_invalid", "integrity_status": "invalid"}
    maturity = artifact.get("maturity")
    if not isinstance(maturity, Mapping):
        return {**failure, "reason": "validation_artifact_maturity_missing", "integrity_status": "invalid"}
    if (
        str(maturity.get("status") or "").strip().lower() != "matured"
        or type(maturity.get("matured_rows")) is not int
        or maturity.get("matured_rows") <= 0
        or maturity.get("evaluated_rows") != maturity.get("matured_rows")
    ):
        return {**failure, "reason": "validation_artifact_maturity_incomplete", "integrity_status": "invalid"}
    control = artifact.get("control")
    if not isinstance(control, Mapping):
        return {**failure, "reason": "validation_artifact_control_missing", "integrity_status": "invalid"}
    if (
        control.get("status") != "verified"
        or control.get("same_cycle") is not True
        or control.get("dataset_hash") != dataset_hash
        or control.get("evaluation_contract_version") != contract
        or control.get("matured_rows") != maturity.get("matured_rows")
        or control.get("verified_rows") != maturity.get("matured_rows")
        or control.get("coverage") != 1.0
    ):
        return {**failure, "reason": "validation_artifact_control_incomplete", "integrity_status": "invalid"}
    refs = artifact.get("evidence_refs")
    adapters = artifact.get("source_adapters")
    if (
        not isinstance(refs, list)
        or not refs
        or any(not _metadata_text(value) for value in refs)
        or not isinstance(adapters, Mapping)
        or not all(_metadata_text(adapters.get(name)) for name in ("agent_events", "point_in_time_replay"))
    ):
        return {**failure, "reason": "validation_artifact_evidence_incomplete", "integrity_status": "invalid"}
    if canonical_validation_resolver is None:
        return {
            **failure,
            "reason": "validation_artifact_provenance_unresolved",
            "integrity_status": "valid_unverified",
        }
    try:
        resolved = canonical_validation_resolver(artifact)
    except Exception:  # noqa: BLE001 - an unavailable verifier must fail closed.
        return {
            **failure,
            "reason": "validation_artifact_canonical_resolution_failed",
            "integrity_status": "valid_unverified",
        }
    verified, reason = _canonical_statistical_resolution(
        resolved,
        artifact=artifact,
        stats=stats,
        candidate=candidate,
        profile_key=profile_key,
        cost_bps=cost_bps,
    )
    if not verified:
        return {**failure, "reason": reason, "integrity_status": "valid_unverified"}
    return {
        "validated": True,
        "status": "validated",
        "reason": "independent_artifact_verified",
        "integrity_status": "verified",
        "artifact_id": str(artifact["artifact_id"]),
        "artifact_hash": supplied_hash,
        "validation_run_id": validation_run_id,
        "validator_id": validator_id,
    }


def candidate_profile_key(candidate: dict[str, Any]) -> str:
    setup = str(candidate.get("setup_name") or candidate.get("strategy_name") or "unknown").strip().lower()
    regime = str(candidate.get("market_regime") or (candidate.get("market_state") or {}).get("market_regime") or "unknown").strip().lower()
    confidence = _number(candidate.get("confidence"))
    if confidence is None:
        confidence_bucket = "unknown"
    elif confidence < 0.60:
        confidence_bucket = "lt0_60"
    elif confidence < 0.75:
        confidence_bucket = "0_60_0_74"
    elif confidence < 0.90:
        confidence_bucket = "0_75_0_89"
    else:
        confidence_bucket = "gte0_90"
    return f"{setup}|{regime}|{confidence_bucket}"


def _stats_map(digest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    source = digest.get("challenger_stats", {}) if isinstance(digest, dict) else {}
    if isinstance(source, dict):
        return {str(key): value for key, value in source.items() if isinstance(value, dict)}
    return {
        str(row.get("profile_key")): row
        for row in source or []
        if isinstance(row, dict) and row.get("profile_key")
    }


def hypothesis_tags(candidate: dict[str, Any]) -> list[str]:
    technical = candidate.get("technical_state") if isinstance(candidate.get("technical_state"), dict) else {}
    rsi = _number(candidate.get("rsi_14", technical.get("rsi_14")))
    close_position = _number(candidate.get("close_position_in_range", technical.get("close_position_in_range")))
    tags: list[str] = []
    if rsi is not None and rsi >= 70.0:
        tags.append("rsi_high")
    regime = str(candidate.get("market_regime") or technical.get("market_regime") or "").lower()
    if regime == "neutral":
        tags.append("neutral_regime")
    if close_position is not None:
        tags.append("range_position")
    if bool(candidate.get("orderly_breakout_long", technical.get("orderly_breakout_long"))):
        tags.append("orderly_breakout")
    return [tag for tag in HYPOTHESIS_TAGS if tag in tags]


def score_challenger_candidate(
    candidate: dict[str, Any],
    digest: dict[str, Any] | None = None,
    *,
    cost_bps: int = 20,
    canonical_validation_resolver: CanonicalValidationResolver | None = None,
) -> dict[str, Any]:
    """Score an idea for observation; this function cannot approve a trade."""

    key = candidate_profile_key(candidate)
    digest_stats = _stats_map(digest or {}).get(key, {})
    candidate_stats = candidate.get("stats") if isinstance(candidate.get("stats"), dict) else {}
    candidate_stats_ok = _stats_provenance_compatible(candidate_stats, profile_key=key)
    stats = digest_stats or (candidate_stats if candidate_stats_ok else {})
    gross = _number(stats.get("expectancy_gross"))
    if gross is None:
        gross = _number(stats.get("expectancy"))
    net = _number(stats.get("expectancy_net"))
    if net is not None and not _cost_compatible(stats, cost_bps=cost_bps):
        net = None
    if net is None and _cost_compatible(stats, cost_bps=cost_bps):
        net = _number(stats.get("expectancy_net_20bps"))
    if net is None and gross is not None:
        net = gross - (float(cost_bps) / 10000.0)
    expectation_available = net is not None
    validation_artifact = stats.get("validation_artifact")
    validation = _validate_statistical_artifact(
        validation_artifact,
        candidate=candidate,
        stats=stats,
        profile_key=key,
        cost_bps=cost_bps,
        canonical_validation_resolver=canonical_validation_resolver,
    )
    return {
        "status": "shadow_only",
        "policy_authority": "none",
        "active_policy_changed": False,
        "profile_key": key,
        "expectation_available": expectation_available,
        "validated_statistically": bool(validation["validated"]),
        "calibrated": expectation_available and bool(validation["validated"]),
        "validation_status": validation["status"],
        "validation_reason": validation["reason"],
        "validation_integrity_status": validation["integrity_status"],
        "calibration_source": (
            "challenger_stats_exact_profile"
            if digest_stats
            else "candidate_stats_provenance_verified"
            if candidate_stats_ok
            else "unavailable"
        ),
        "expectancy_net": round(net, 6) if net is not None else None,
        "cost_bps": cost_bps,
        "hypothesis_tags": hypothesis_tags(candidate),
        "control": "champion_current_policy",
    }


def build_challenger_shadow_rank(
    candidates: list[dict[str, Any]],
    digest: dict[str, Any] | None = None,
    *,
    canonical_validation_resolver: CanonicalValidationResolver | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        shadow = score_challenger_candidate(
            candidate,
            digest,
            canonical_validation_resolver=canonical_validation_resolver,
        )
        rows.append({**candidate, "challenger_shadow": shadow})

    def ranking_identity(row: dict[str, Any]) -> tuple[str, str]:
        explicit_status = str(row.get("signal_identity_status") or "").strip().lower()
        if explicit_status in {"ambiguous", "conflict"}:
            return "ambiguous", "ambiguous"
        values = {
            "candidate_id": _metadata_text(row.get("candidate_id")),
            "signal_id": _metadata_text(row.get("signal_id")),
            "signal_capture_id": _metadata_text(row.get("signal_capture_id")),
            "signal_source_run_id": _metadata_text(row.get("signal_source_run_id")),
        }
        if all(values[field] for field in ("signal_id", "signal_capture_id", "signal_source_run_id")):
            return "verified", json.dumps(values, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        candidate_id = values["candidate_id"]
        if candidate_id and candidate_id.lower() not in {"unknown", "none", "null", "unavailable", "na"}:
            return "partial", json.dumps(
                {"candidate_id": candidate_id, "profile_key": candidate_profile_key(row)},
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
        stable_fallback = {
            "symbol": str(row.get("symbol") or "").strip().upper() or None,
            "profile_key": candidate_profile_key(row),
        }
        return "missing", json.dumps(stable_fallback, ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    def ranking_key(row: dict[str, Any]) -> tuple[int, float, int, str]:
        expectancy = _number((row.get("challenger_shadow") or {}).get("expectancy_net"))
        if expectancy is None:
            tier = 0
            numeric = 0.0
        elif expectancy > 0:
            tier = 3
            numeric = expectancy
        elif expectancy == 0:
            tier = 2
            numeric = 0.0
        else:
            tier = 1
            numeric = expectancy
        identity_status, identity_key = ranking_identity(row)
        identity_tier = {"verified": 0, "partial": 1, "missing": 2, "ambiguous": 3}[identity_status]
        row["challenger_shadow"]["ranking_identity_status"] = identity_status
        row["challenger_shadow"]["ranking_identity"] = identity_key
        return (-tier, -numeric, identity_tier, identity_key)

    return sorted(
        rows,
        key=ranking_key,
    )


def evaluate_challenger_metrics(
    metrics: dict[str, Any],
    *,
    control: dict[str, Any] | None = None,
    windows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Apply strict review thresholds while keeping activation human-gated."""

    reasons: list[str] = []
    expectancy = _number(metrics.get("expectancy_net", metrics.get("expectancy_net_20bps")))
    hit_rate = _number(metrics.get("hit_rate"))
    profit_factor = _number(metrics.get("profit_factor"))
    drawdown = _number(metrics.get("max_drawdown"))
    p10 = _number(metrics.get("p10_net", metrics.get("p10")))
    if expectancy is None or expectancy < THRESHOLDS["min_expectancy_net"]:
        reasons.append("expectancy_net_below_zero")
    if hit_rate is None or hit_rate < THRESHOLDS["min_hit_rate"]:
        reasons.append("hit_rate_below_55pct")
    if profit_factor is None or profit_factor < THRESHOLDS["min_profit_factor"]:
        reasons.append("profit_factor_below_1_15")
    if drawdown is None or drawdown > THRESHOLDS["max_drawdown"]:
        reasons.append("drawdown_above_8pct")
    if p10 is None or p10 < THRESHOLDS["min_p10"]:
        reasons.append("p10_below_minus_6pct")
    raw_rows = list(windows or [])
    rows = [row for row in raw_rows if isinstance(row, dict)]
    window_contract = None
    if len(rows) != len(raw_rows):
        reasons.append("window_contract_invalid:backtest_row_mapping_required")
    elif rows:
        try:
            window_contract = validate_window_descriptors(rows, require_summary=True)
            rows = window_contract["rows"]
        except ValueError as exc:
            reasons.append(f"window_contract_invalid:{exc}")
    window_ids = list((window_contract or {}).get("intervals", {}))
    if len(window_ids) < THRESHOLDS["min_windows"]:
        reasons.append("three_non_overlapping_windows_required")
    metrics_dataset = _metadata_text(metrics.get("dataset_hash"))
    metrics_contract = _metadata_text(metrics.get("evaluation_contract_version"))
    if not metrics_dataset or metrics_contract != WINDOW_CONTRACT_VERSION:
        reasons.append("metrics_metadata_unavailable")
    if window_contract and (
        window_contract["dataset_hash"] != metrics_dataset
        or window_contract["evaluation_contract_version"] != metrics_contract
    ):
        reasons.append("window_metadata_mismatch")
    if control is None:
        reasons.append("comparable_control_required")
    elif not isinstance(control, dict):
        reasons.append("control_incomplete")
    else:
        control_dataset = _metadata_text(control.get("dataset_hash"))
        control_contract = _metadata_text(control.get("evaluation_contract_version"))
        if not control_dataset or not control_contract:
            reasons.append("control_metadata_unavailable")
        elif (control_dataset, control_contract) != (metrics_dataset, metrics_contract):
            reasons.append("control_metadata_mismatch")
        if control.get("status") != "verified":
            reasons.append("control_not_verified")
        control_expectancy = _number(control.get("expectancy_net", control.get("expectancy_net_20bps")))
        control_drawdown = _number(control.get("max_drawdown"))
        control_p10 = _number(control.get("p10_net", control.get("p10")))
        if control_expectancy is None or control_drawdown is None or control_p10 is None:
            reasons.append("control_incomplete")
        elif metrics_contract == WINDOW_CONTRACT_VERSION and metrics_dataset == control_dataset:
            if expectancy is None or expectancy < control_expectancy:
                reasons.append("below_comparable_control")
            if drawdown is None or drawdown > control_drawdown:
                reasons.append("worse_than_comparable_control_drawdown")
            if p10 is None or p10 < control_p10:
                reasons.append("worse_than_comparable_control_p10")
    return {
        "status": "review_only",
        "decision": "eligible_for_human_review" if not reasons else "blocked",
        "active": False,
        "policy_authority": "none",
        "thresholds": THRESHOLDS.copy(),
        "reasons": reasons,
        "metrics": dict(metrics),
        "control": dict(control or {}) if isinstance(control, dict) else {},
        "windows": rows,
    }
