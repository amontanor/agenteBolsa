"""Offline readiness contract for human-gated promotion follow-up.

The artifact can queue a review for ``shadow -> guarded_active -> active`` but
never applies a stage, changes capital, or grants authority.  Readiness is
computed from explicit economic evidence and deterministic gates; an LLM,
calendar, task completion or a passing test cannot authorize promotion.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

PROMOTION_FOLLOWUP_SCHEMA_VERSION = "p-l117m.promotion-followup.v1"
_STAGES = ("shadow", "guarded_active", "active")
_EPSILON = 1e-12


class PromotionFollowupError(ValueError):
    """Raised when a promotion readiness artifact is unsafe or incomplete."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _text(value: Any, field: str, *, required: bool = True) -> str | None:
    if value is None or isinstance(value, bool):
        if required:
            raise PromotionFollowupError(f"promotion_{field}_required")
        return None
    text = str(value).strip()
    if not text:
        if required:
            raise PromotionFollowupError(f"promotion_{field}_required")
        return None
    if len(text) > 500:
        raise PromotionFollowupError(f"promotion_{field}_too_long")
    return text


def _number(value: Any, field: str) -> float:
    if value is None or isinstance(value, bool):
        raise PromotionFollowupError(f"promotion_{field}_required")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise PromotionFollowupError(f"promotion_{field}_invalid") from exc
    if not math.isfinite(parsed):
        raise PromotionFollowupError(f"promotion_{field}_invalid")
    return parsed


def _positive_int(value: Any, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise PromotionFollowupError(f"promotion_{field}_invalid")
    return value


def _bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise PromotionFollowupError(f"promotion_{field}_invalid")
    return value


def _nonnegative_int(value: Any, field: str) -> int:
    if type(value) is not int or value < 0:
        raise PromotionFollowupError(f"promotion_{field}_invalid")
    return value


def _refs(value: Any, field: str) -> list[str]:
    if isinstance(value, (str, bytes, Mapping)):
        raise PromotionFollowupError(f"promotion_{field}_invalid")
    try:
        items = list(value)
    except TypeError as exc:
        raise PromotionFollowupError(f"promotion_{field}_invalid") from exc
    result = sorted({_text(item, field) for item in items})
    if not result:
        raise PromotionFollowupError(f"promotion_{field}_required")
    return result


def _metrics(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PromotionFollowupError(f"promotion_{field}_mapping_required")
    required = {"net_expectancy", "max_drawdown", "p10_net", "benchmark_alpha", "matured_rows", "sessions"}
    if set(value) != required:
        raise PromotionFollowupError(f"promotion_{field}_metrics_fields_invalid")
    drawdown = _number(value.get("max_drawdown"), f"{field}_max_drawdown")
    if drawdown < 0:
        raise PromotionFollowupError(f"promotion_{field}_max_drawdown_invalid")
    return {
        "net_expectancy": _number(value.get("net_expectancy"), f"{field}_net_expectancy"),
        "max_drawdown": drawdown,
        "p10_net": _number(value.get("p10_net"), f"{field}_p10_net"),
        "benchmark_alpha": _number(value.get("benchmark_alpha"), f"{field}_benchmark_alpha"),
        "matured_rows": _positive_int(value.get("matured_rows"), f"{field}_matured_rows"),
        "sessions": _positive_int(value.get("sessions"), f"{field}_sessions"),
    }


def _criteria(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PromotionFollowupError("promotion_criteria_mapping_required")
    allowed = {
        "min_matured_rows",
        "min_sessions",
        "max_drawdown_ratio",
        "min_benchmark_alpha",
        "require_oos",
        "require_paper",
    }
    if set(value) != allowed:
        raise PromotionFollowupError("promotion_criteria_fields_invalid")
    ratio = _number(value.get("max_drawdown_ratio"), "max_drawdown_ratio")
    if ratio < 0:
        raise PromotionFollowupError("promotion_max_drawdown_ratio_invalid")
    return {
        "min_matured_rows": _positive_int(value.get("min_matured_rows"), "min_matured_rows"),
        "min_sessions": _positive_int(value.get("min_sessions"), "min_sessions"),
        "max_drawdown_ratio": ratio,
        "min_benchmark_alpha": _number(value.get("min_benchmark_alpha"), "min_benchmark_alpha"),
        "require_oos": _bool(value.get("require_oos"), "require_oos"),
        "require_paper": _bool(value.get("require_paper"), "require_paper"),
    }


def _evidence(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PromotionFollowupError("promotion_evidence_mapping_required")
    allowed = {
        "evidence_id",
        "evidence_version",
        "source_hashes",
        "oos",
        "paper",
        "outcomes_matured",
        "champion_metrics",
        "candidate_metrics",
        "control_metrics",
    }
    if set(value) != allowed:
        raise PromotionFollowupError("promotion_evidence_fields_invalid")
    return {
        "evidence_id": _text(value.get("evidence_id"), "evidence_id"),
        "evidence_version": _text(value.get("evidence_version"), "evidence_version"),
        "source_hashes": _refs(value.get("source_hashes"), "source_hashes"),
        "oos": _bool(value.get("oos"), "oos"),
        "paper": _bool(value.get("paper"), "paper"),
        "outcomes_matured": _bool(value.get("outcomes_matured"), "outcomes_matured"),
        "champion_metrics": _metrics(value.get("champion_metrics"), "champion"),
        "candidate_metrics": _metrics(value.get("candidate_metrics"), "candidate"),
        "control_metrics": _metrics(value.get("control_metrics"), "control"),
    }


def _review(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PromotionFollowupError("promotion_review_mapping_required")
    allowed = {"review_id", "independent_validation", "validator_id", "human_approval", "human_reviewer_id"}
    if set(value) != allowed:
        raise PromotionFollowupError("promotion_review_fields_invalid")
    return {
        "review_id": _text(value.get("review_id"), "review_id"),
        "independent_validation": _bool(value.get("independent_validation"), "independent_validation"),
        "validator_id": _text(value.get("validator_id"), "validator_id"),
        "human_approval": _bool(value.get("human_approval"), "human_approval"),
        "human_reviewer_id": _text(value.get("human_reviewer_id"), "human_reviewer_id"),
    }


def _guarded_observation(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PromotionFollowupError("promotion_guarded_observation_mapping_required")
    allowed = {"completed", "sessions", "rollback_tested", "no_regression", "human_approval"}
    if set(value) != allowed:
        raise PromotionFollowupError("promotion_guarded_observation_fields_invalid")
    return {
        "completed": _bool(value.get("completed"), "guarded_completed"),
        "sessions": _nonnegative_int(value.get("sessions"), "guarded_sessions"),
        "rollback_tested": _bool(value.get("rollback_tested"), "rollback_tested"),
        "no_regression": _bool(value.get("no_regression"), "no_regression"),
        "human_approval": _bool(value.get("human_approval"), "guarded_human_approval"),
    }


def _without_hash(report: Mapping[str, Any]) -> dict[str, Any]:
    return {key: report[key] for key in report if key != "report_hash"}


def _metric_blockers(evidence: Mapping[str, Any], criteria: Mapping[str, Any]) -> list[str]:
    candidate = evidence["candidate_metrics"]
    champion = evidence["champion_metrics"]
    control = evidence["control_metrics"]
    blockers: list[str] = []
    if not evidence["outcomes_matured"]:
        blockers.append("outcomes_not_matured")
    if criteria["require_oos"] and not evidence["oos"]:
        blockers.append("oos_evidence_required")
    if criteria["require_paper"] and not evidence["paper"]:
        blockers.append("paper_evidence_required")
    if candidate["matured_rows"] < criteria["min_matured_rows"]:
        blockers.append("candidate_matured_rows_insufficient")
    if candidate["sessions"] < criteria["min_sessions"]:
        blockers.append("candidate_sessions_insufficient")
    if candidate["net_expectancy"] <= champion["net_expectancy"] + _EPSILON:
        blockers.append("candidate_not_better_than_champion_expectancy")
    if candidate["net_expectancy"] <= control["net_expectancy"] + _EPSILON:
        blockers.append("candidate_not_better_than_control_expectancy")
    if candidate["p10_net"] + _EPSILON < champion["p10_net"]:
        blockers.append("candidate_p10_below_champion")
    if candidate["p10_net"] + _EPSILON < control["p10_net"]:
        blockers.append("candidate_p10_below_control")
    if candidate["max_drawdown"] > champion["max_drawdown"] * criteria["max_drawdown_ratio"] + _EPSILON:
        blockers.append("candidate_drawdown_above_champion_limit")
    if candidate["max_drawdown"] > control["max_drawdown"] * criteria["max_drawdown_ratio"] + _EPSILON:
        blockers.append("candidate_drawdown_above_control_limit")
    if candidate["benchmark_alpha"] + _EPSILON < criteria["min_benchmark_alpha"]:
        blockers.append("candidate_benchmark_alpha_insufficient")
    return blockers


def _review_blockers(review: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not review["independent_validation"]:
        blockers.append("independent_validation_required")
    if not review["human_approval"]:
        blockers.append("human_approval_required")
    return blockers


def build_promotion_followup(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate a human-gated promotion plan without applying it."""

    if not isinstance(plan, Mapping):
        raise PromotionFollowupError("promotion_plan_mapping_required")
    allowed = {
        "candidate_id",
        "candidate_version",
        "current_stage",
        "requested_stage",
        "evidence",
        "criteria",
        "review",
        "guarded_observation",
        "calendar_trigger",
        "task_completion_trigger",
        "capital_change_authorized",
    }
    unknown = sorted(set(plan) - allowed, key=str)
    if unknown:
        raise PromotionFollowupError("promotion_plan_unknown_fields:" + ",".join(str(item) for item in unknown))
    candidate_id = _text(plan.get("candidate_id"), "candidate_id")
    candidate_version = _text(plan.get("candidate_version"), "candidate_version")
    current_stage = _text(plan.get("current_stage"), "current_stage").lower()
    requested_stage = _text(plan.get("requested_stage"), "requested_stage").lower()
    if current_stage not in _STAGES or requested_stage not in _STAGES:
        raise PromotionFollowupError("promotion_stage_invalid")
    evidence = _evidence(plan.get("evidence"))
    criteria = _criteria(plan.get("criteria"))
    review = _review(plan.get("review"))
    guarded = _guarded_observation(plan.get("guarded_observation"))
    calendar_trigger = _bool(plan.get("calendar_trigger"), "calendar_trigger")
    task_completion_trigger = _bool(plan.get("task_completion_trigger"), "task_completion_trigger")
    capital_change_authorized = _bool(plan.get("capital_change_authorized"), "capital_change_authorized")
    blockers = _metric_blockers(evidence, criteria)
    blockers.extend(_review_blockers(review))
    if calendar_trigger:
        blockers.append("calendar_trigger_forbidden")
    if task_completion_trigger:
        blockers.append("task_completion_trigger_forbidden")
    if capital_change_authorized:
        blockers.append("capital_change_forbidden")
    if current_stage == "shadow" and requested_stage == "active":
        blockers.append("direct_shadow_to_active_forbidden")
    if current_stage == "guarded_active" and requested_stage == "shadow":
        blockers.append("stage_transition_not_allowed")
    if current_stage == "active" and requested_stage != "active":
        blockers.append("active_rollback_requires_separate_review")
    if requested_stage == "active":
        if not guarded["completed"]:
            blockers.append("guarded_observation_required")
        if guarded["sessions"] <= 0:
            blockers.append("guarded_observation_sessions_required")
        if not guarded["rollback_tested"]:
            blockers.append("guarded_rollback_test_required")
        if not guarded["no_regression"]:
            blockers.append("guarded_no_regression_required")
        if not guarded["human_approval"]:
            blockers.append("guarded_human_approval_required")
    if blockers:
        readiness = "precondition_not_met"
        action = (
            "reject_transition"
            if "stage_transition_not_allowed" in blockers
            else "keep_shadow"
        )
    elif current_stage == requested_stage == "shadow":
        readiness = "ready_for_shadow"
        action = "keep_shadow"
    elif requested_stage == "guarded_active":
        readiness = "ready_for_guarded_active"
        action = "queue_guarded_active_for_human_review"
    else:
        readiness = "ready_for_active"
        action = "queue_active_for_human_review"
    report: dict[str, Any] = {
        "schema_version": PROMOTION_FOLLOWUP_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "candidate_version": candidate_version,
        "current_stage": current_stage,
        "requested_stage": requested_stage,
        "readiness": readiness,
        "action": action,
        "blockers": sorted(set(blockers)),
        "evidence": evidence,
        "criteria": criteria,
        "review": review,
        "guarded_observation": guarded,
        "calendar_trigger": calendar_trigger,
        "task_completion_trigger": task_completion_trigger,
        "capital_change_authorized": capital_change_authorized,
        "application_status": "shadow_only",
        "active_authority": "none",
        "applied": False,
        "llm_authority": False,
        "promotion_eligible": readiness in {"ready_for_guarded_active", "ready_for_active"},
    }
    report["report_hash"] = _hash_payload(_without_hash(report))
    return report


def validate_promotion_followup(report: Mapping[str, Any]) -> dict[str, Any]:
    """Validate hash and ensure the artifact has not become an activation."""

    if not isinstance(report, Mapping):
        raise PromotionFollowupError("promotion_report_mapping_required")
    if report.get("schema_version") != PROMOTION_FOLLOWUP_SCHEMA_VERSION:
        raise PromotionFollowupError("promotion_schema_version_mismatch")
    if report.get("application_status") != "shadow_only" or report.get("active_authority") != "none":
        raise PromotionFollowupError("promotion_active_authority_forbidden")
    if report.get("applied") is not False or report.get("llm_authority") is not False:
        raise PromotionFollowupError("promotion_application_forbidden")
    if report.get("report_hash") != _hash_payload(_without_hash(report)):
        raise PromotionFollowupError("promotion_report_hash_mismatch")
    return copy.deepcopy(dict(report))
