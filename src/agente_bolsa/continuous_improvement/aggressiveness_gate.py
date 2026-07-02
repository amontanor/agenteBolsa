"""Deterministic evidence gate for more aggressive trading proposals."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agente_bolsa.storage import Store

AGGRESSIVENESS_REQUIRES_EDGE_EVIDENCE = "aggressiveness_requires_edge_evidence"
AGGRESSIVENESS_GATE_ACTOR = "AggressivenessEvidenceGate"
CONSTITUTIONAL_GATE_ACTOR = "ConstitutionalQueueAudit"

AGGRESSIVENESS_PARAMETER_CRITERIA: dict[str, str] = {
    "max_daily_buy_orders": "increase",
    "max_orders_per_cycle": "increase",
    "trade_selection_top_n": "increase",
    "trade_aggressiveness_profile": "more_aggressive_profile",
    "max_risk_per_trade": "increase",
    "risk_off_buy_factor": "increase",
    "min_order_notional": "decrease",
    "min_llm_confidence_to_trade": "decrease",
    "entry_quality_min_score": "decrease",
    "entry_quality_max_rsi": "increase",
    "entry_quality_max_sma20_distance": "increase",
    "sleeve_fraction": "increase",
    "core_sleeve_sleeve_fraction": "increase",
    "target_vol": "increase",
    "core_sleeve_target_vol": "increase",
    "lab_book_daily_cap": "increase",
    "lab_book_fixed_notional": "increase",
    "lab_book_notional": "increase",
    "lab_book_max_universe_symbols": "increase",
}

PROFILE_RANK = {
    "defensive": 0,
    "conservative": 1,
    "balanced": 2,
    "neutral": 2,
    "opportunistic": 3,
    "aggressive": 4,
}

AGGRESSIVE_LANGUAGE = (
    "aggressive",
    "agresiv",
    "aument",
    "increase",
    "more orders",
    "more trades",
    "mas ordenes",
    "mas operaciones",
    "relax",
    "loosen",
    "lower threshold",
    "subir",
    "bajar umbral",
)


@dataclass(frozen=True)
class AggressivenessAssessment:
    requires_evidence: bool
    has_edge_evidence: bool
    criterion: str | None = None
    target_identifier: str | None = None
    current_value: Any = None
    proposed_value: Any = None
    evidence: dict[str, Any] | None = None
    reason: str | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "requires_evidence": self.requires_evidence,
            "has_edge_evidence": self.has_edge_evidence,
            "criterion": self.criterion,
            "target_identifier": self.target_identifier,
            "current_value": self.current_value,
            "proposed_value": self.proposed_value,
            "evidence": self.evidence or {},
            "reason": self.reason,
        }


def aggressiveness_parameter_criteria(settings: Any | None = None) -> dict[str, str]:
    """Return direct settings and same-family analogs with their loosening direction."""
    criteria = dict(AGGRESSIVENESS_PARAMETER_CRITERIA)
    fields = getattr(type(settings), "model_fields", None) if settings is not None else None
    for name in fields or {}:
        field = str(name)
        if field.startswith("entry_quality_"):
            if _has_any(field, ("_min_score", "_min_rsi", "_min_return", "_min_relative_return", "_min_volume_z")):
                criteria.setdefault(field, "decrease")
            elif _has_any(field, ("_max_rsi", "_max_sma20_distance", "_max_selection_rank", "_max_volume_z")):
                criteria.setdefault(field, "increase")
        elif field.endswith("_trade_min_score"):
            criteria.setdefault(field, "decrease")
        elif field.endswith("_trade_target_exposure_pct"):
            criteria.setdefault(field, "increase")
    return criteria


def assess_aggressiveness_evidence(
    proposal: dict[str, Any],
    *,
    settings: Any,
    store: Store | None,
) -> AggressivenessAssessment:
    payload = proposal.get("payload") or {}
    target_identifier = str(proposal.get("target_identifier") or payload.get("target_identifier") or "").strip()
    target_component = str(proposal.get("target_component") or payload.get("target_component") or "").strip()
    if not target_identifier:
        return AggressivenessAssessment(False, False, reason="no_target_identifier")
    criteria = aggressiveness_parameter_criteria(settings)
    canonical_identifier = re.sub(r"[^a-z0-9_]+", "_", target_identifier.lower()).strip("_")
    component_identifier = re.sub(
        r"[^a-z0-9_]+",
        "_",
        f"{target_component}_{target_identifier}".lower(),
    ).strip("_")
    criterion = criteria.get(target_identifier) or criteria.get(canonical_identifier) or criteria.get(component_identifier)
    if criterion is None:
        return AggressivenessAssessment(False, False, target_identifier=target_identifier, reason="target_not_aggressiveness")

    current_value = _value_or_setting(payload.get("current_value"), settings, target_identifier)
    proposed_value = payload.get("proposed_value")
    requires_evidence = _is_aggressiveness_increase(
        criterion=criterion,
        current_value=current_value,
        proposed_value=proposed_value,
        proposal=proposal,
    )
    if not requires_evidence:
        return AggressivenessAssessment(
            False,
            False,
            criterion=criterion,
            target_identifier=target_identifier,
            current_value=current_value,
            proposed_value=proposed_value,
            reason="not_more_aggressive",
        )

    evidence = find_linked_edge_evidence(store, proposal_id=str(proposal.get("proposal_id") or ""))
    return AggressivenessAssessment(
        True,
        bool(evidence),
        criterion=criterion,
        target_identifier=target_identifier,
        current_value=current_value,
        proposed_value=proposed_value,
        evidence=evidence,
        reason=None if evidence else AGGRESSIVENESS_REQUIRES_EDGE_EVIDENCE,
    )


def find_linked_edge_evidence(store: Store | None, *, proposal_id: str) -> dict[str, Any] | None:
    if store is None or not proposal_id:
        return None
    for experiment in store.continuous_improvement_experiments(proposal_id=proposal_id, statuses=["PASSED"], limit=100):
        metric = _positive_net_edge_metric(experiment)
        if metric is not None:
            return {
                "experiment_id": experiment.get("experiment_id"),
                "status": experiment.get("status"),
                "metric_path": metric[0],
                "metric_value": metric[1],
            }
    return None


def reject_ready_aggressiveness_without_evidence(
    store: Store,
    *,
    settings: Any,
    limit: int = 50000,
) -> list[dict[str, Any]]:
    rejected: list[dict[str, Any]] = []
    for proposal in store.continuous_improvement_proposals(status="READY_TO_APPLY", limit=limit):
        assessment = assess_aggressiveness_evidence(proposal, settings=settings, store=store)
        if not assessment.requires_evidence or assessment.has_edge_evidence:
            continue
        store.update_continuous_improvement_proposal_status(
            str(proposal["proposal_id"]),
            status="REJECTED",
            actor=AGGRESSIVENESS_GATE_ACTOR,
            reason=AGGRESSIVENESS_REQUIRES_EDGE_EVIDENCE,
            payload=assessment.as_payload(),
        )
        rejected.append({"proposal_id": proposal["proposal_id"], **assessment.as_payload()})
    return rejected


def reject_ready_constitutional_holes(
    store: Store,
    *,
    limit: int = 50000,
) -> list[dict[str, Any]]:
    from .agents import (
        SELF_GOVERNANCE_REJECTION_REASON,
        SELF_SAFETY_REJECTION_REASON,
        self_governance_modification_violation,
        self_safety_modification_violation,
    )

    rejected: list[dict[str, Any]] = []
    for proposal in store.continuous_improvement_proposals(status="READY_TO_APPLY", limit=limit):
        payload = proposal.get("payload") or {}
        target_component = str(proposal.get("target_component") or payload.get("target_component") or "")
        target_identifier = str(proposal.get("target_identifier") or payload.get("target_identifier") or "")
        violation = self_safety_modification_violation(
            target_component=target_component,
            target_identifier=target_identifier,
            payload=payload,
        )
        reason = SELF_SAFETY_REJECTION_REASON
        if violation is None:
            violation = self_governance_modification_violation(
                target_component=target_component,
                target_identifier=target_identifier,
                payload=payload,
            )
            reason = SELF_GOVERNANCE_REJECTION_REASON
        if violation is None:
            continue
        store.update_continuous_improvement_proposal_status(
            str(proposal["proposal_id"]),
            status="REJECTED",
            actor=CONSTITUTIONAL_GATE_ACTOR,
            reason=reason,
            payload={"violation": violation},
        )
        rejected.append({"proposal_id": proposal["proposal_id"], "reason": reason, "violation": violation})
    return rejected


def _is_aggressiveness_increase(
    *,
    criterion: str,
    current_value: Any,
    proposed_value: Any,
    proposal: dict[str, Any],
) -> bool:
    text_is_aggressive = _has_any(_proposal_text(proposal), AGGRESSIVE_LANGUAGE)
    if criterion == "more_aggressive_profile":
        current_rank = PROFILE_RANK.get(str(current_value).strip().lower())
        proposed_rank = PROFILE_RANK.get(str(proposed_value).strip().lower())
        if current_rank is not None and proposed_rank is not None:
            return proposed_rank > current_rank
    current_number = _to_float(current_value)
    proposed_numbers = _to_floats(proposed_value)
    proposed_number = None
    if proposed_numbers:
        proposed_number = max(proposed_numbers) if criterion == "increase" else min(proposed_numbers)
    if current_number is not None and proposed_number is not None:
        if criterion == "increase":
            return proposed_number > current_number or text_is_aggressive
        if criterion == "decrease":
            return proposed_number < current_number or text_is_aggressive
    return text_is_aggressive


def _value_or_setting(value: Any, settings: Any, field: str) -> Any:
    if value not in (None, ""):
        return value
    return getattr(settings, field, value)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    values = _to_floats(value)
    if not values:
        return None
    return values[0]


def _to_floats(value: Any) -> list[float]:
    if value is None:
        return []
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    return [float(item.replace(",", ".")) for item in re.findall(r"[-+]?\d+(?:[.,]\d+)?", str(value))]


def _positive_net_edge_metric(experiment: dict[str, Any]) -> tuple[str, float] | None:
    for path, value in _walk_numbers({"metrics": experiment.get("metrics"), "result": experiment.get("result")}):
        path_lower = path.lower()
        if value <= 0:
            continue
        if not _has_any(path_lower, ("expectancy", "alpha", "edge", "excess")):
            continue
        if _has_any(path_lower, ("net", "after_cost", "after_costs", "cost", "forward", "oos")):
            return path, value
    return None


def _walk_numbers(value: Any, *, path: str = "") -> list[tuple[str, float]]:
    if isinstance(value, dict):
        rows: list[tuple[str, float]] = []
        for key, child in value.items():
            rows.extend(_walk_numbers(child, path=f"{path}.{key}" if path else str(key)))
        return rows
    if isinstance(value, list):
        rows = []
        for idx, child in enumerate(value):
            rows.extend(_walk_numbers(child, path=f"{path}[{idx}]"))
        return rows
    number = _to_float(value)
    return [(path, number)] if number is not None else []


def _proposal_text(proposal: dict[str, Any]) -> str:
    payload = proposal.get("payload") or {}
    chunks = [
        proposal.get("proposal_type"),
        proposal.get("target_component"),
        proposal.get("target_identifier"),
        payload.get("rationale"),
        payload.get("expected_impact"),
        payload.get("current_value"),
        payload.get("proposed_value"),
        payload.get("summary"),
    ]
    return " ".join(str(item or "").lower() for item in chunks)


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)
