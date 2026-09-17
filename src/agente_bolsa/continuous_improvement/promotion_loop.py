"""Cierre determinista del bucle de promocion (P-L122).

Tres piezas que existian por separado pero nunca se ejecutaban juntas:

- `close_stale_validations`: las validaciones PENDING mas viejas que el TTL
  (14 dias) se cierran como EXPIRED_PENDING con fila de decision durable.
- `resolve_applied_impacts`: un cambio APPLIED con impacto PENDING recibe
  veredicto medido (PASSED si sobrevive sin rollback del watchdog,
  FAILED si hay rollback). Sin veredicto medido no cuenta para autonomia.
- `sync_promotion_policies`: los veredictos PROMOTE_CANDIDATE de
  `promotion_readiness` crean politicas en shadow (jamas activas); los
  RETIRE_CANDIDATE degradan a shadow politicas coincidentes; la subida a
  guarded_active/active queda siempre en manos humanas (`human_review`).

Nada aqui toca trading, riesgo, sizing, broker, ejecucion ni configuracion.
Todo es stdlib y determinista: testeable sin red, broker ni LLM.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

VALIDATION_TTL_DAYS = 14
POLICY_ID_PREFIX = "auto_"
HUMAN_HELD_STATUSES = frozenset({"guarded_active", "active"})
POLICY_TYPE_BY_KIND = {
    "setup": "setup_shadow",
    "tag": "feature_shadow",
    "regime": "regime_shadow",
}


def _now(now: datetime | None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _parse(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def close_stale_validations(store: Any, *, now: datetime | None = None, ttl_days: int = VALIDATION_TTL_DAYS) -> dict[str, Any]:
    """Cierra PENDING mas viejas que el TTL con decision durable."""
    reference = _now(now)
    cutoff = reference - timedelta(days=int(ttl_days))
    expired: list[str] = []
    for validation in store.continuous_improvement_validations(limit=100000):
        if str(validation.get("status") or "") != "PENDING":
            continue
        created = _parse(validation.get("created_at"))
        if created is None or created >= cutoff:
            continue
        age_days = (reference - created).days
        store.update_continuous_improvement_validation_status(
            str(validation["validation_id"]),
            status="EXPIRED_PENDING",
            actor="PromotionLoop",
            reason="pending_validation_expired",
            payload={"age_days": age_days, "ttl_days": int(ttl_days)},
        )
        expired.append(str(validation["validation_id"]))
    return {"expired": len(expired), "expired_ids": sorted(expired), "ttl_days": int(ttl_days)}


def resolve_applied_impacts(store: Any, *, now: datetime | None = None, clean_days: int = 15) -> dict[str, Any]:
    """Veredicto medido post-aplicacion: PASSED por supervivencia, FAILED por rollback."""
    reference = _now(now)
    changes = store.continuous_improvement_applied_changes(limit=10000)
    rollbacks = store.continuous_improvement_applied_changes(statuses=["ROLLED_BACK"], limit=10000)
    rolled_proposals = {str(item.get("proposal_id")) for item in rollbacks}
    passed: list[str] = []
    failed: list[str] = []
    skipped: list[str] = []
    for change in changes:
        if str(change.get("status") or "") != "APPLIED":
            continue
        decision = dict(change.get("decision") or {})
        impact = decision.get("impact_validation") or {}
        if str(impact.get("status") or "").upper() in {"PASSED", "FAILED"}:
            continue
        updated = _parse(change.get("created_at")) or _parse(change.get("updated_at"))
        age_days = (reference - updated).days if updated is not None else 0
        if age_days < int(clean_days):
            skipped.append(str(change["applied_change_id"]))
            continue
        change_id = str(change["applied_change_id"])
        rollback_hit = next(
            (item for item in rollbacks if str(item.get("proposal_id")) == str(change.get("proposal_id"))),
            None,
        )
        if str(change.get("proposal_id")) in rolled_proposals and rollback_hit is not None:
            verdict: dict[str, Any] = {
                "status": "FAILED",
                "measured_at": reference.isoformat(),
                "evaluator": "PromotionLoop",
                "evidence": {"watchdog_rollback": True, "survival_days": age_days},
            }
            failed.append(change_id)
        else:
            verdict = {
                "status": "PASSED",
                "measured_at": reference.isoformat(),
                "evaluator": "PromotionLoop",
                "evidence": {"watchdog_rollbacks": 0, "survival_days": age_days},
            }
            passed.append(change_id)
        decision["impact_validation"] = verdict
        store.save_continuous_improvement_applied_change(
            {
                "applied_change_id": change_id,
                "initiative_id": change.get("initiative_id"),
                "proposal_id": change.get("proposal_id"),
                "cycle_id": change.get("cycle_id"),
                "status": "APPLIED",
                "change_type": change.get("change_type"),
                "target_key": change.get("target_key"),
                "before": change.get("before") or {},
                "after": change.get("after") or {},
                "rollback": change.get("rollback") or {},
                "decision": decision,
                "validation_ids": change.get("validation_ids") or [],
                "error": change.get("error"),
                "created_at": change.get("created_at"),
                "updated_at": change.get("updated_at"),
            }
        )
    return {"passed": sorted(passed), "failed": sorted(failed), "skipped": sorted(skipped), "clean_days": int(clean_days)}


def _policy_id(kind: str, key: str) -> str:
    return f"{POLICY_ID_PREFIX}{_slug(kind)}_{_slug(key)}"


def sync_promotion_policies(
    store: Any,
    settings: Any = None,
    *,
    since_date: str = "2026-04-01",
    evaluations: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Sincroniza veredictos de readiness con politicas shadow (nunca activa)."""
    from .promotion_readiness import evaluate_promotion_readiness

    reference = _now(now)
    if evaluations is None and settings is None:
        return {"shadowed": [], "kept": [], "demoted": [], "human_review": [], "reason": "settings_required"}
        evaluations = evaluate_promotion_readiness(settings, store, since_date=since_date).get("evaluations", [])
    existing = {str(item.get("policy_id")): item for item in store.learning_policy_candidates(limit=1000)}
    shadowed: list[str] = []
    kept: list[str] = []
    demoted: list[str] = []
    human_review: list[str] = []
    for evaluation in evaluations or []:
        verdict = str(evaluation.get("verdict") or "")
        kind = str(evaluation.get("kind") or "")
        key = str(evaluation.get("key") or "")
        metrics = evaluation.get("metrics") or {}
        if verdict == "PROMOTE_CANDIDATE":
            policy_id = _policy_id(kind, key)
            current = existing.get(policy_id)
            if current is not None and str(current.get("status") or "") in HUMAN_HELD_STATUSES:
                kept.append(policy_id)
                human_review.append(policy_id)
                continue
            store.upsert_learning_policy_candidate(
                {
                    "policy_id": policy_id,
                    "name": f"Auto shadow {kind}:{key}",
                    "policy_type": POLICY_TYPE_BY_KIND.get(kind, "feature_shadow"),
                    "status": "shadow",
                    "scope": "global",
                    "auto_activatable": False,
                    "evidence": {
                        "verdict": verdict,
                        "kind": kind,
                        "key": key,
                        "sessions": evaluation.get("sessions"),
                        "since_date": since_date,
                    },
                    "metrics": metrics,
                    "notes": "PROMOTE_CANDIDATE con evidencia dura; requiere walk-forward y revision humana para guarded_active.",
                    "promoted_at": None,
                    "last_evaluated_at": reference.isoformat(),
                    "created_at": (current or {}).get("created_at"),
                    "updated_at": reference.isoformat(),
                }
            )
            shadowed.append(policy_id)
        elif verdict == "RETIRE_CANDIDATE":
            for policy_id, current in existing.items():
                evidence = current.get("evidence") or {}
                if str(evidence.get("tag") or "") != key and not policy_id.endswith(_slug(key)):
                    continue
                if str(current.get("status") or "") not in HUMAN_HELD_STATUSES:
                    continue
                store.upsert_learning_policy_candidate(
                    {
                        "policy_id": policy_id,
                        "name": str(current.get("name") or policy_id),
                        "policy_type": str(current.get("policy_type") or "feature_shadow"),
                        "status": "shadow",
                        "scope": str(current.get("scope") or "global"),
                        "auto_activatable": False,
                        "evidence": {**(evidence if isinstance(evidence, dict) else {}), "retired_at": reference.isoformat(), "retire_key": key},
                        "metrics": current.get("metrics") or {},
                        "notes": f"RETIRE_CANDIDATE ({key}): degradada a shadow con trazabilidad; reactivacion solo humana.",
                        "promoted_at": current.get("promoted_at"),
                        "last_evaluated_at": reference.isoformat(),
                        "created_at": current.get("created_at"),
                        "updated_at": reference.isoformat(),
                    }
                )
                demoted.append(policy_id)
    for policy_id in sorted(set(shadowed) | set(demoted)):
        store.save_learning_policy_evaluation(
            {
                "evaluation_id": f"promo_sync_{policy_id}_{reference.date().isoformat()}",
                "policy_id": policy_id,
                "session_date": reference.date().isoformat(),
                "phase": "promotion_sync",
                "payload": {"sync": "promotion_loop", "measured_at": reference.isoformat()},
            }
        )
    return {
        "shadowed": sorted(shadowed),
        "kept": sorted(kept),
        "demoted": sorted(demoted),
        "human_review": sorted(human_review),
    }
