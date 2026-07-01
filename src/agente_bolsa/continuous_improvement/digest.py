"""Read-only daily digest for the continuous improvement lab."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from agente_bolsa.storage import Store

REJECTION_BUCKETS = {
    "self_safety_modification_forbidden": "self_safety",
    "self_governance_modification_forbidden": "self_governance",
    "recently_rejected_duplicate": "recently_rejected",
}


def build_lab_digest(store: Store, *, days: int = 1) -> dict[str, Any]:
    days = max(1, int(days))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    proposals = store.continuous_improvement_proposals(limit=20000)
    experiments = store.continuous_improvement_experiments(limit=20000)
    applied_changes = store.continuous_improvement_applied_changes(limit=20000)

    recent_proposals_created = [item for item in proposals if _is_recent(item.get("created_at"), cutoff)]
    recent_rejected = [
        item for item in proposals if str(item.get("status") or "").upper() == "REJECTED" and _is_recent(item.get("updated_at"), cutoff)
    ]
    ready_to_apply = [
        _ready_item(store, item)
        for item in proposals
        if str(item.get("status") or "").upper() == "READY_TO_APPLY" and _is_recent(item.get("updated_at"), cutoff)
    ]
    recent_applied = [item for item in applied_changes if _is_recent(item.get("updated_at"), cutoff)]
    recent_experiments = [item for item in experiments if _is_recent(item.get("updated_at"), cutoff)]

    rejection_counts = {"self_safety": 0, "self_governance": 0, "recently_rejected": 0, "otros": 0}
    for proposal in recent_rejected:
        rejection_counts[_rejection_bucket(store, proposal)] += 1

    experiment_counts = {
        "run": len(recent_experiments),
        "passed": sum(1 for item in recent_experiments if str(item.get("status") or "").upper() in {"PASSED", "APPLIED"}),
        "failed": sum(
            1
            for item in recent_experiments
            if str(item.get("status") or "").upper() in {"FAILED", "REJECTED_BY_TESTS", "BLOCKED", "ROLLBACK_FAILED"}
        ),
    }
    applied_counts: dict[str, int] = {}
    for item in recent_applied:
        status = str(item.get("status") or "UNKNOWN").upper()
        applied_counts[status] = applied_counts.get(status, 0) + 1

    attention = [item for item in ready_to_apply if item["has_diff"]]
    return {
        "days": days,
        "window_start": cutoff.isoformat(),
        "proposals": {
            "created": len(recent_proposals_created),
            "rejected_by_reason": rejection_counts,
            "ready_to_apply": ready_to_apply,
            "ready_to_apply_count": len(ready_to_apply),
        },
        "applied_changes": {
            "total": len(recent_applied),
            "by_status": applied_counts,
        },
        "experiments": experiment_counts,
        "requires_attention": attention,
    }


def format_lab_digest_text(digest: dict[str, Any]) -> str:
    rejected = (digest.get("proposals") or {}).get("rejected_by_reason") or {}
    ready = (digest.get("proposals") or {}).get("ready_to_apply") or []
    applied = digest.get("applied_changes") or {}
    experiments = digest.get("experiments") or {}
    attention = digest.get("requires_attention") or []

    lines = [
        f"Digest diario del lab - ultimos {digest.get('days')} dia(s)",
        "",
        "Propuestas",
        f"- creadas: {(digest.get('proposals') or {}).get('created', 0)}",
        (
            "- rechazadas: "
            f"self_safety={rejected.get('self_safety', 0)}, "
            f"self_governance={rejected.get('self_governance', 0)}, "
            f"recently_rejected={rejected.get('recently_rejected', 0)}, "
            f"otros={rejected.get('otros', 0)}"
        ),
        f"- READY_TO_APPLY: {len(ready)}",
    ]
    for item in ready:
        marker = "diff adjunto" if item.get("has_diff") else "sin diff"
        lines.append(f"  - {item.get('proposal_id')} | {item.get('target')} | {marker}")

    lines.extend(
        [
            "",
            "Applied changes",
            f"- total: {applied.get('total', 0)}",
            f"- por estado: {_format_counts(applied.get('by_status') or {})}",
            "",
            "Experimentos",
            f"- corridos: {experiments.get('run', 0)}",
            f"- PASSED: {experiments.get('passed', 0)}",
            f"- FAILED: {experiments.get('failed', 0)}",
            "",
            "Requiere tu atencion",
        ]
    )
    if attention:
        for item in attention:
            lines.append(f"- {item.get('proposal_id')} | {item.get('target')} | diff listo")
    else:
        lines.append("- Nada con diff listo en la ventana.")
    return "\n".join(lines)


def _ready_item(store: Store, proposal: dict[str, Any]) -> dict[str, Any]:
    artifact = store.continuous_improvement_proposal_artifact(str(proposal.get("proposal_id") or ""))
    return {
        "proposal_id": proposal.get("proposal_id"),
        "target": f"{proposal.get('target_component')}/{proposal.get('target_identifier')}".rstrip("/"),
        "has_diff": _artifact_has_diff(artifact),
        "artifact_id": (artifact or {}).get("artifact_id"),
    }


def _artifact_has_diff(artifact: dict[str, Any] | None) -> bool:
    if not artifact:
        return False
    artifact_type = str(artifact.get("artifact_type") or "").lower()
    payload = artifact.get("payload") or {}
    content = str(artifact.get("content_text") or "")
    return (
        artifact_type in {"diff", "patch"}
        or "diff --git " in content
        or "--- " in content
        and "+++ " in content
        or str(payload.get("status") or "") == "READY_FOR_HUMAN_REVIEW"
        or bool(payload.get("diff") or payload.get("patch"))
    )


def _rejection_bucket(store: Store, proposal: dict[str, Any]) -> str:
    reasons: list[str] = []
    guard = proposal.get("guard") or {}
    reasons.extend(str(item or "") for item in guard.get("reasons") or [])
    for key in ("self_safety_violation", "self_governance_violation", "recently_rejected_duplicate"):
        if guard.get(key):
            reasons.append(str((guard.get(key) or {}).get("reason") or key))
    for decision in store.continuous_improvement_decisions(proposal_id=str(proposal.get("proposal_id") or ""), limit=20):
        reasons.append(str(decision.get("reason") or ""))
        payload = decision.get("payload") or {}
        for key in ("self_safety_violation", "self_governance_violation", "recently_rejected_duplicate"):
            if payload.get(key):
                reasons.append(str((payload.get(key) or {}).get("reason") or key))
    joined = " ".join(reasons).lower()
    for reason, bucket in REJECTION_BUCKETS.items():
        if reason in joined:
            return bucket
    return "otros"


def _is_recent(value: Any, cutoff: datetime) -> bool:
    parsed = _parse_iso_datetime(str(value or ""))
    return parsed is not None and parsed >= cutoff


def _parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "sin cambios"
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
