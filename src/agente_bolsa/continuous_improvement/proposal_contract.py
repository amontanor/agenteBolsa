"""Evidence contract and deterministic admission checks for improvement proposals."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .codegen import _candidate_paths_from_proposal, _is_low_risk_codegen_path

CHANGE_CLASSES = frozenset({"trading", "reliability", "observability", "docs"})
MIN_EVIDENCE_SAMPLE = 30
VAGUE_METRICS = frozenset({"", "improve", "improvement", "mejora", "quality", "score", "metric"})
CLASS_METRIC_MARKERS = {
    "trading": ("expectancy", "alpha", "excess_return", "drawdown", "control", "forward_return"),
    "reliability": ("failure", "error", "recurrence", "availability", "recovery", "mttr"),
    "observability": ("coverage", "diagnostic_latency", "false_positive", "visibility", "eligible"),
    "docs": ("delivery", "consistency", "verified"),
}
TERMINAL_PROPOSAL_STATUSES = frozenset(
    {"APPLIED", "ARCHIVED", "BLOCKED", "DUPLICATE", "REJECTED", "REJECTED_BY_TESTS", "ROLLED_BACK"}
)
_SAFETY_RELAXATION_MARKERS = (
    "allow_auto_apply_improvements=true",
    "disable risk",
    "disable gate",
    "relax safety",
    "enable live trading",
    "increase max orders",
    "increase exposure",
)


@dataclass(frozen=True)
class EvidenceCard:
    """Immutable measured evidence carried unchanged into a proposal contract."""

    change_class: str
    hypothesis_id: str
    evidence_refs: tuple[str, ...]
    metric_name: str
    baseline: float
    target: float
    evaluation_window: str
    min_sample: int
    target_paths: tuple[str, ...]
    rollback: str
    finding_source: str
    improvement_direction: str = "increase"

    def as_contract(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_refs"] = list(self.evidence_refs)
        payload["target_paths"] = list(self.target_paths)
        return payload


def experiment_contract(proposal: dict[str, Any]) -> dict[str, Any]:
    """Return the canonical contract without guessing absent historical fields."""

    payload = proposal.get("payload") or proposal
    raw = payload.get("experiment_contract") or proposal.get("experiment_contract") or {}
    contract = dict(raw) if isinstance(raw, dict) else {}
    aliases = {
        "change_class": ("change_class",),
        "hypothesis_id": ("hypothesis_id",),
        "evidence_refs": ("evidence_refs", "evidence"),
        "metric_name": ("metric_name",),
        "baseline": ("baseline",),
        "target": ("target", "target_value"),
        "evaluation_window": ("evaluation_window",),
        "min_sample": ("min_sample",),
        "target_paths": ("target_paths", "target_files"),
        "rollback": ("rollback", "rollback_plan"),
    }
    for canonical, keys in aliases.items():
        if canonical in contract:
            continue
        for key in keys:
            if key in payload:
                contract[canonical] = payload[key]
                break
    return contract


def validate_experiment_contract(
    proposal: dict[str, Any],
    *,
    workspace: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate evidence, measurement, scope and freshness before code generation."""

    contract = experiment_contract(proposal)
    payload = proposal.get("payload") or proposal
    failures: list[str] = []
    change_class = str(contract.get("change_class") or "").strip().lower()
    if change_class not in CHANGE_CLASSES:
        failures.append("change_class_invalid")
    for field in ("hypothesis_id", "metric_name", "evaluation_window", "rollback"):
        if not str(contract.get(field) or "").strip():
            failures.append(f"missing_{field}")
    refs = contract.get("evidence_refs")
    if not isinstance(refs, list) or not any(str(item).strip() for item in refs):
        failures.append("missing_evidence_refs")
    elif workspace is not None:
        for ref in refs:
            text = str(ref).strip()
            if _looks_like_path(text) and not (workspace / Path(text)).exists():
                failures.append(f"evidence_ref_missing:{text}")
    for field in ("baseline", "target"):
        value = contract.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            failures.append(f"invalid_{field}")
    metric_name = str(contract.get("metric_name") or "").strip().lower()
    if metric_name in VAGUE_METRICS:
        failures.append("metric_name_vague")
    elif change_class in CLASS_METRIC_MARKERS and not any(
        marker in metric_name for marker in CLASS_METRIC_MARKERS[change_class]
    ):
        failures.append(f"metric_incompatible_with_class:{change_class}")

    baseline, target = contract.get("baseline"), contract.get("target")
    inferred_direction = "decrease" if isinstance(baseline, (int, float)) and isinstance(target, (int, float)) and target < baseline else "increase"
    direction = str(contract.get("improvement_direction") or inferred_direction).strip().lower()
    if isinstance(baseline, (int, float)) and isinstance(target, (int, float)):
        if direction == "increase" and target <= baseline:
            failures.append("target_not_above_baseline")
        elif direction == "decrease" and target >= baseline:
            failures.append("target_not_below_baseline")
        elif direction not in {"increase", "decrease"}:
            failures.append("improvement_direction_invalid")

    min_sample = contract.get("min_sample")
    if not isinstance(min_sample, int) or isinstance(min_sample, bool) or min_sample < MIN_EVIDENCE_SAMPLE:
        failures.append("invalid_min_sample")

    targets = contract.get("target_paths")
    normalized_targets = _normalize_paths(targets)
    candidate_proposal = proposal if proposal.get("payload") else {**proposal, "payload": proposal}
    payload_targets = _candidate_paths_from_proposal(candidate_proposal)
    if not normalized_targets:
        failures.append("missing_target_paths")
    if payload_targets and set(normalized_targets) != set(payload_targets):
        failures.append("target_paths_mismatch")
    for target in normalized_targets:
        path = PurePosixPath(target)
        if path.is_absolute() or ".." in path.parts or not _is_low_risk_codegen_path(target):
            failures.append(f"target_path_forbidden:{target}")
            continue
        if workspace is not None and not (workspace / Path(target)).exists():
            failures.append(f"target_path_missing:{target}")

    evidence_as_of = _parse_datetime(contract.get("evidence_as_of"))
    if contract.get("evidence_as_of") and evidence_as_of is None:
        failures.append("evidence_as_of_invalid")
    if evidence_as_of is not None:
        reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if evidence_as_of < reference - timedelta(days=30):
            failures.append("evidence_stale")

    text = " ".join(
        str(value or "").lower()
        for value in (
            proposal.get("target_identifier"),
            proposal.get("rationale"),
            payload.get("proposed_value"),
            payload.get("expected_impact"),
        )
    )
    if any(marker in text for marker in _SAFETY_RELAXATION_MARKERS):
        failures.append("safety_relaxation_requested")
    vague = str(payload.get("expected_impact") or "").strip().lower()
    if vague in {"", "improve", "mejorar", "better", "optimization", "optimizar"}:
        failures.append("expected_impact_vague")

    return {
        "valid": not failures,
        "failures": list(dict.fromkeys(failures)),
        "contract": {**contract, "change_class": change_class, "target_paths": normalized_targets},
    }


def historical_contract_class(proposal: dict[str, Any]) -> str:
    """Classify legacy rows at read time without filling absent evidence."""
    validation = validate_experiment_contract(proposal)
    if validation["valid"]:
        return "evidence_experiment"
    payload = proposal.get("payload") or proposal
    if str(payload.get("finding_kind") or "").lower() == "operational_check":
        return "operational_check"
    return "unverifiable_legacy"


def classify_experiment(experiment: dict[str, Any], proposal: dict[str, Any] | None = None) -> str:
    """Read-only classification; historical rows are never rewritten."""

    status = str(experiment.get("status") or "").upper()
    if status in {"FAILED", "REJECTED_BY_TESTS", "BLOCKED", "ROLLBACK_FAILED"}:
        return "failed_runs"
    metrics = experiment.get("metrics") or (experiment.get("payload") or {}).get("metrics") or {}
    if metrics and proposal is not None and validate_experiment_contract(proposal)["valid"]:
        return "evidence_experiments"
    if metrics and str(experiment.get("experiment_type") or "").lower() in {
        "strategy_edge_compare",
        "shadow_strategy",
        "controlled_experiment",
    }:
        return "evidence_experiments"
    return "operational_checks"


def _normalize_paths(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(
        dict.fromkeys(
            str(item).replace("\\", "/").removeprefix("./").strip()
            for item in value
            if str(item).strip()
        )
    )


def _looks_like_path(value: str) -> bool:
    return "/" in value or "\\" in value or Path(value).suffix != ""


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
