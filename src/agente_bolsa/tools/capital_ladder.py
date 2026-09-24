"""Human-gated paper capital ladder with an immutable 25% hard ceiling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "capital_ladder.v1"
STAGE_LIMITS = {0: 0.25, 1: 0.10, 2: 0.15, 3: 0.20, 4: 0.25}
HARD_MAX_EXPOSURE = 0.25
STAGE_REQUIREMENTS = {
    0: (0, 0),
    1: (0, 0),
    2: (20, 15),
    3: (35, 25),
    4: (50, 35),
}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _paper_safe(raw: dict[str, Any]) -> bool:
    return (
        raw.get("trading_mode") == "paper"
        and raw.get("alpaca_paper") is True
        and raw.get("allow_live_trading") is False
        and raw.get("allow_auto_apply_improvements") is False
    )


def load_capital_ladder(data_dir: Path) -> dict[str, Any]:
    """Read optional operator approval; absence is safe stage 0."""

    path = Path(data_dir) / "config" / "capital_ladder.json"
    base = {
        "schema_version": SCHEMA_VERSION,
        "config_path": str(path),
        "requested_stage": 0,
        "approved_stage": 0,
        "active_stage": 0,
        "human_approved": False,
        "max_exposure": STAGE_LIMITS[0],
        "paper_only": True,
        "status": "shadow",
        "reasons": ["approval_file_absent"],
    }
    if not path.exists():
        return base
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {**base, "status": "blocked", "reasons": ["approval_file_invalid"]}
    if not isinstance(raw, dict) or raw.get("schema_version") not in {None, SCHEMA_VERSION}:
        return {**base, "status": "blocked", "reasons": ["schema_version_invalid"]}
    requested = _safe_int(raw.get("requested_stage"), 0)
    approved = _safe_int(raw.get("approved_stage"), 0)
    human = raw.get("human_approved") is True
    reasons: list[str] = []
    if requested not in STAGE_LIMITS or approved not in STAGE_LIMITS:
        return {**base, "status": "blocked", "reasons": ["stage_out_of_range"]}
    if not _paper_safe(raw):
        reasons.append("paper_safety_flags_invalid")
        human = False
        requested = approved = 0
    if approved < requested:
        reasons.append("requested_stage_exceeds_approval")
        requested = approved = 0
    active = requested if human else 0
    if not human and requested:
        reasons.append("human_approval_required")
    if not reasons:
        reasons.append("human_approved" if human else "stage_0_shadow")
    return {
        **base,
        "requested_stage": requested,
        "approved_stage": approved,
        "active_stage": active,
        "human_approved": human,
        "max_exposure": STAGE_LIMITS[active],
        "paper_only": True,
        "status": "active" if active else "shadow",
        "reasons": reasons,
        "approval_id": str(raw.get("approval_id") or "") or None,
    }


def cap_notional_for_ladder(
    *,
    equity: float,
    desired_notional: float,
    current_exposure: float = 0.0,
    pending_exposure: float = 0.0,
    planned_exposure: float = 0.0,
    ladder: dict[str, Any] | None = None,
) -> tuple[float, dict[str, Any]]:
    state = ladder or {"active_stage": 0, "max_exposure": HARD_MAX_EXPOSURE, "status": "shadow"}
    equity_value = max(0.0, _safe_float(equity))
    desired = max(0.0, _safe_float(desired_notional))
    stage = _safe_int(state.get("active_stage"), 0)
    max_exposure = min(HARD_MAX_EXPOSURE, STAGE_LIMITS.get(stage, HARD_MAX_EXPOSURE))
    base_exposure = max(0.0, _safe_float(current_exposure)) + max(0.0, _safe_float(pending_exposure)) + max(0.0, _safe_float(planned_exposure))
    available = max(0.0, (max_exposure - base_exposure) * equity_value)
    capped = min(desired, available)
    return round(capped, 2), {
        "schema_version": SCHEMA_VERSION,
        "stage": stage,
        "status": state.get("status", "shadow"),
        "max_exposure": round(max_exposure, 4),
        "base_exposure": round(base_exposure, 6),
        "available_notional": round(available, 2),
        "desired_notional": round(desired, 2),
        "capped": capped < desired,
        "hard_max_exposure": HARD_MAX_EXPOSURE,
        "paper_only": True,
        "no_forced_buy": True,
    }


def evaluate_stage_promotion(
    metrics: dict[str, Any],
    *,
    target_stage: int,
    human_approved: bool,
) -> dict[str, Any]:
    """Evaluate evidence; never changes runtime state or self-approves."""

    reasons: list[str] = []
    if target_stage not in STAGE_LIMITS or target_stage < 1:
        reasons.append("target_stage_invalid")
    if not human_approved:
        reasons.append("human_approval_required")
    if not _paper_safe(metrics):
        reasons.append("paper_safety_flags_invalid")
    minimum_buys, minimum_controls = STAGE_REQUIREMENTS.get(target_stage, (10**9, 10**9))
    mature_buys = _safe_int(metrics.get("mature_buys"))
    controls = _safe_int(metrics.get("controls"))
    if mature_buys < minimum_buys:
        reasons.append("mature_buys_below_minimum")
    if controls < minimum_controls:
        reasons.append("controls_below_minimum")
    if _safe_float(metrics.get("lineage_coverage")) < 0.95:
        reasons.append("lineage_coverage_below_95pct")
    if _safe_int(metrics.get("critical_alerts")) != 0:
        reasons.append("critical_alerts_present")
    if _safe_int(metrics.get("missing_critical_data")) != 0:
        reasons.append("critical_data_missing")
    if _safe_int(metrics.get("positive_windows")) < 2:
        reasons.append("fewer_than_two_positive_windows")
    if _safe_int(metrics.get("material_loss_windows")) != 0:
        reasons.append("material_loss_window_present")
    return {
        "schema_version": SCHEMA_VERSION,
        "target_stage": target_stage,
        "eligible": not reasons,
        "decision": "eligible_for_human_review" if not reasons else "blocked",
        "active": False,
        "max_exposure": STAGE_LIMITS.get(target_stage),
        "requirements": {"mature_buys": minimum_buys, "controls": minimum_controls},
        "reasons": reasons,
        "paper_only": True,
        "allow_live_trading": False,
        "allow_auto_apply_improvements": False,
    }


def rollback_stage(state: dict[str, Any], target_stage: int) -> dict[str, Any]:
    """Return a lower stage without touching files or deleting evidence."""

    current = _safe_int(state.get("active_stage"), 0)
    if target_stage not in STAGE_LIMITS or target_stage > current:
        raise ValueError("capital_ladder_rollback_must_be_downward")
    result = dict(state)
    result.update(
        {
            "active_stage": target_stage,
            "requested_stage": min(_safe_int(state.get("requested_stage"), target_stage), target_stage),
            "max_exposure": STAGE_LIMITS[target_stage],
            "status": "rollback",
            "reasons": ["operator_rollback"],
        }
    )
    return result
