"""Ciclo de vida del laboratorio de mejora continua (Etapa 7).

Problema que resuelve: las iniciativas se quedaban abiertas 7-8 dias sin
terminar y las tareas colgadas por dependencias muertas, asi que el laboratorio
acumulaba backlog en vez de mejorar. Reglas:

- TTL de tareas: una tarea no terminal mas vieja que `CI_TASK_TTL_HOURS` se
  cancela; sus dependientes tambien (el trabajo previo no ocurrio).
- Cierre con rendicion de cuentas: una iniciativa MONITORING sin tareas vivas
  y sin movimiento durante `CI_MONITORING_CLOSE_DAYS` se cierra con outcome
  (mejoro su target_metric o no).
- Avance de fase: una iniciativa OPEN sin tareas vivas y con propuestas activas
  pasa a VALIDATING para no planificar otra tanda de agentes sobre el mismo tema.
- Fragmentacion: una iniciativa cuyo tema es un id interno (`ci_prop_*`,
  `ci_init_*`, etc.) expira pronto; esos ids son metadatos, no objetivos.
- Sin salida: una iniciativa OPEN vieja, sin tareas vivas y sin propuestas
  activas, expira aunque su updated_at se haya refrescado por bookkeeping.
- Validacion estancada: una iniciativa VALIDATING sin tareas vivas ni
  propuestas listas para aplicar expira tras `CI_VALIDATION_BACKLOG_TTL_DAYS`.
- Expiracion: una iniciativa abierta mas de `CI_INITIATIVE_TTL_DAYS` dias y sin
  avance en `CI_INITIATIVE_STALL_DAYS` se marca REJECTED (expirada). Puede
  reabrirse despues, pero solo con evidencia nueva.
- El informe de flujo expone WIP, edades y throughput para el digest.

Todo es stdlib y deterministico: testeable sin LLM.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from .._utils import log_swallow
from ..logging_utils import log_system_event
from .agents import is_generated_ci_reference

if TYPE_CHECKING:  # pragma: no cover - solo anotaciones.
    from ..config import Settings
    from ..storage import Store


LOGGER = logging.getLogger(__name__)


NON_TERMINAL_TASK_STATUSES = [
    "DISCOVERED",
    "PLANNED",
    "ASSIGNED",
    "RUNNING",
    "WAITING_DEPENDENCY",
    "VALIDATING",
    "WAITING_HUMAN_REVIEW",
]
TERMINAL_TASK_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}
ACTIVE_INITIATIVE_STATUSES = {
    "OPEN",
    "ANALYZING",
    "EXPERIMENTING",
    "VALIDATING",
    "WAITING_REVIEW",
    "READY_TO_APPLY",
}
CHURN_DECISIONS = {
    "PENDING",
    "VALIDATING",
    "WAITING_HUMAN_REVIEW",
    "REQUIRES_HUMAN_REVIEW",
    "WAITING_REVIEW",
    "ESCALATE",
}
REJECTABLE_PROPOSAL_STATUSES = {
    "PENDING",
    "VALIDATING",
    "WAITING_HUMAN_REVIEW",
    "REQUIRES_HUMAN_REVIEW",
    "FAILED",
}
ACTIVE_PROPOSAL_STATUSES = {
    "PENDING",
    "VALIDATING",
    "WAITING_HUMAN_REVIEW",
    "REQUIRES_HUMAN_REVIEW",
    "READY_TO_APPLY",
}
READY_PROPOSAL_STATUSES = {"READY_TO_APPLY", "PASSED"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _age_hours(value: Any) -> float | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - moment).total_seconds() / 3600.0


def sweep_stale_tasks(store: Store, settings: Settings) -> dict[str, Any]:
    """Cancela tareas no terminales vencidas y sus dependientes huerfanos."""

    ttl_hours = float(getattr(settings, "ci_task_ttl_hours", 48.0))
    tasks = store.continuous_improvement_tasks(statuses=NON_TERMINAL_TASK_STATUSES, limit=2000)
    expired: list[str] = []
    for task in tasks:
        age = _age_hours(task.get("created_at"))
        if age is not None and age > ttl_hours:
            store.update_continuous_improvement_task(
                task["task_id"],
                status="CANCELLED",
                error={"reason": "ttl_expired", "age_hours": round(age, 1)},
                finished_at=_now_iso(),
            )
            expired.append(task["task_id"])

    cancelled_dependents: list[str] = []
    expired_set = set(expired)
    for task in tasks:
        if task["task_id"] in expired_set or task.get("status") != "WAITING_DEPENDENCY":
            continue
        dead_dep = None
        for dep_id in task.get("dependency_ids") or []:
            if dep_id in expired_set:
                dead_dep = dep_id
                break
            dep = store.continuous_improvement_task(dep_id)
            if dep is None or dep.get("status") in {"FAILED", "CANCELLED"}:
                dead_dep = dep_id
                break
        if dead_dep:
            store.update_continuous_improvement_task(
                task["task_id"],
                status="CANCELLED",
                error={"reason": "dependency_dead", "dependency_id": dead_dep},
                finished_at=_now_iso(),
            )
            cancelled_dependents.append(task["task_id"])

    return {"expired": expired, "cancelled_dependents": cancelled_dependents}


def _open_tasks_by_initiative(store: Store) -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in store.continuous_improvement_tasks(statuses=NON_TERMINAL_TASK_STATUSES, limit=2000):
        initiative_id = str((task.get("payload") or {}).get("initiative_id") or "")
        if initiative_id:
            counts[initiative_id] = counts.get(initiative_id, 0) + 1
    return counts


def _outcome_for(initiative: dict[str, Any]) -> dict[str, Any]:
    baseline = initiative.get("baseline_value")
    current = initiative.get("current_value")
    improved: bool | None = None
    if isinstance(baseline, (int, float)) and isinstance(current, (int, float)):
        # Convencion: target_metric es algo a REDUCIR (errores, bloqueos,
        # duplicados) salvo que el nombre sugiera lo contrario.
        metric = str(initiative.get("target_metric") or "").lower()
        higher_is_better = any(token in metric for token in ("expectancy", "coverage", "stability", "maturity", "hit"))
        improved = (current > baseline) if higher_is_better else (current < baseline)
    return {
        "target_metric": initiative.get("target_metric"),
        "baseline_value": baseline,
        "current_value": current,
        "improved": improved,
    }


def _is_decision_churn(initiative: dict[str, Any]) -> bool:
    """True when recent updates are bookkeeping, not real progress."""

    latest = initiative.get("latest_decision") or {}
    decision = str(latest.get("decision") or "").upper()
    source = str(latest.get("source") or "")
    next_action = str(initiative.get("next_action") or "").lower()
    if source == "AutonomyNormalizer":
        return True
    if decision in CHURN_DECISIONS and source in {"DecisionCommitteeAgent", "validation", "proposal_persist", "runtime"}:
        return True
    return decision in CHURN_DECISIONS and any(
        token in next_action
        for token in (
            "esperar",
            "revalidar",
            "revision humana",
            "validacion objetiva",
        )
    )


def _is_generated_topic_initiative(initiative: dict[str, Any]) -> bool:
    key = str(initiative.get("initiative_key") or "")
    topic = key.split(":", 1)[-1]
    return is_generated_ci_reference(topic)


def _is_validation_backlog_churn(initiative: dict[str, Any]) -> bool:
    """True when VALIDATING is just a queue state, not objective progress."""

    latest = initiative.get("latest_decision") or {}
    source = str(latest.get("source") or "")
    reason = str(latest.get("reason") or "").lower()
    next_action = str(initiative.get("next_action") or "").lower()
    if _is_decision_churn(initiative):
        return True
    if source == "lifecycle" and reason == "all_tasks_terminal_with_active_proposals":
        return True
    return "validar propuestas vinculadas" in next_action


def _reject_linked_pending_proposals(
    store: Store,
    initiative: dict[str, Any],
    *,
    reason: str,
    proposal_status_by_id: dict[str, str] | None = None,
) -> list[str]:
    rejected: list[str] = []
    proposal_status_by_id = proposal_status_by_id or {}
    for proposal_id in list(initiative.get("linked_proposal_ids") or []):
        current_status = str(proposal_status_by_id.get(str(proposal_id)) or "").upper()
        if not current_status:
            proposal = store.continuous_improvement_proposal(str(proposal_id))
            if not proposal:
                continue
            current_status = str(proposal.get("status") or "").upper()
        if current_status not in REJECTABLE_PROPOSAL_STATUSES:
            continue
        try:
            store.update_continuous_improvement_proposal_status(
                str(proposal_id),
                status="REJECTED",
                actor="LifecycleAgent",
                reason=reason,
                payload={
                    "initiative_id": initiative.get("initiative_id"),
                    "initiative_key": initiative.get("initiative_key"),
                    "previous_status": current_status,
                },
            )
            rejected.append(str(proposal_id))
        except KeyError:
            continue
    return rejected


def _proposal_status_by_id(store: Store) -> dict[str, str]:
    return {
        str(proposal["proposal_id"]): str(proposal.get("status") or "").upper()
        for proposal in store.continuous_improvement_proposals(limit=10000)
    }


def _active_linked_proposal_ids(initiative: dict[str, Any], proposal_status_by_id: dict[str, str]) -> list[str]:
    active: list[str] = []
    for proposal_id in list(initiative.get("linked_proposal_ids") or []):
        if str(proposal_status_by_id.get(str(proposal_id)) or "").upper() in ACTIVE_PROPOSAL_STATUSES:
            active.append(str(proposal_id))
    return active


def _ready_linked_proposal_ids(initiative: dict[str, Any], proposal_status_by_id: dict[str, str]) -> list[str]:
    ready: list[str] = []
    for proposal_id in list(initiative.get("linked_proposal_ids") or []):
        if str(proposal_status_by_id.get(str(proposal_id)) or "").upper() in READY_PROPOSAL_STATUSES:
            ready.append(str(proposal_id))
    return ready


def resolve_initiatives(store: Store, settings: Settings) -> dict[str, Any]:
    """Cierra iniciativas monitorizadas sin movimiento y expira las estancadas."""

    ttl_days = float(getattr(settings, "ci_initiative_ttl_days", 5.0))
    validation_backlog_ttl_days = float(getattr(settings, "ci_validation_backlog_ttl_days", min(ttl_days, 2.0)))
    stall_days = float(getattr(settings, "ci_initiative_stall_days", 3.0))
    monitoring_close_days = float(getattr(settings, "ci_monitoring_close_days", 5.0))
    open_tasks = _open_tasks_by_initiative(store)
    proposal_statuses = _proposal_status_by_id(store)

    closed: list[dict[str, Any]] = []
    expired: list[dict[str, Any]] = []
    advanced: list[dict[str, Any]] = []
    for initiative in store.continuous_improvement_initiatives(limit=1000):
        status = str(initiative.get("status") or "")
        if status in {"CLOSED", "REJECTED"}:
            continue
        initiative_id = str(initiative["initiative_id"])
        has_open_tasks = open_tasks.get(initiative_id, 0) > 0
        age_days = ( _age_hours(initiative.get("created_at")) or 0.0) / 24.0
        idle_days = ( _age_hours(initiative.get("updated_at")) or 0.0) / 24.0

        if status == "MONITORING" and not has_open_tasks and idle_days > monitoring_close_days:
            outcome = _outcome_for(initiative)
            store.update_continuous_improvement_initiative(
                initiative_id,
                status="CLOSED",
                latest_decision={"decision": "CLOSED", "source": "lifecycle", "outcome": outcome},
                next_action="Cerrada por ciclo de vida: monitorizacion completada.",
            )
            closed.append({"initiative_id": initiative_id, "initiative_key": initiative.get("initiative_key"), "outcome": outcome})
            continue

        active_proposals = _active_linked_proposal_ids(initiative, proposal_statuses)
        ready_proposals = _ready_linked_proposal_ids(initiative, proposal_statuses)
        latest_source = str((initiative.get("latest_decision") or {}).get("source") or "")
        generated_topic_expired = age_days > min(ttl_days, 1.0) and not has_open_tasks and _is_generated_topic_initiative(initiative)
        validation_backlog_expired = (
            status == "VALIDATING"
            and age_days > validation_backlog_ttl_days
            and not has_open_tasks
            and not ready_proposals
            and latest_source != "AutonomyNormalizer"
            and _is_validation_backlog_churn(initiative)
        )
        no_output_expired = (
            status == "OPEN"
            and age_days > ttl_days
            and not has_open_tasks
            and not active_proposals
            and bool(initiative.get("linked_task_ids") or [])
        )
        human_review_no_output_expired = (
            status == "WAITING_REVIEW"
            and age_days > validation_backlog_ttl_days
            and not has_open_tasks
            and not active_proposals
            and bool(initiative.get("linked_task_ids") or [])
        )
        if generated_topic_expired:
            reason = f"clave de iniciativa generada sin objetivo semantico durante {age_days:.1f} dias"
            rejected_proposals = _reject_linked_pending_proposals(
                store,
                initiative,
                reason=reason,
                proposal_status_by_id=proposal_statuses,
            )
            store.update_continuous_improvement_initiative(
                initiative_id,
                status="REJECTED",
                latest_decision={
                    "decision": "EXPIRED",
                    "source": "lifecycle",
                    "reason": reason,
                    "rejected_proposal_ids": rejected_proposals,
                },
                next_action="Expirada por fragmentacion: reabrir solo como iniciativa semantica.",
            )
            expired.append(
                {
                    "initiative_id": initiative_id,
                    "initiative_key": initiative.get("initiative_key"),
                    "reason": reason,
                    "rejected_proposal_ids": rejected_proposals,
                }
            )
            continue

        if validation_backlog_expired:
            reason = f"validacion pendiente sin evidencia objetiva durante {age_days:.1f} dias"
            rejected_proposals = _reject_linked_pending_proposals(
                store,
                initiative,
                reason=reason,
                proposal_status_by_id=proposal_statuses,
            )
            store.update_continuous_improvement_initiative(
                initiative_id,
                status="REJECTED",
                latest_decision={
                    "decision": "EXPIRED",
                    "source": "lifecycle",
                    "reason": reason,
                    "rejected_proposal_ids": rejected_proposals,
                    "validation_backlog_ttl_days": validation_backlog_ttl_days,
                },
                next_action="Expirada por validacion estancada: reabrir solo con evidencia nueva.",
            )
            expired.append(
                {
                    "initiative_id": initiative_id,
                    "initiative_key": initiative.get("initiative_key"),
                    "reason": reason,
                    "rejected_proposal_ids": rejected_proposals,
                }
            )
            continue

        if no_output_expired:
            reason = f"grupo experto completado sin propuestas activas tras {age_days:.1f} dias"
            store.update_continuous_improvement_initiative(
                initiative_id,
                status="REJECTED",
                latest_decision={
                    "decision": "EXPIRED",
                    "source": "lifecycle",
                    "reason": reason,
                    "rejected_proposal_ids": [],
                },
                next_action="Expirada sin salida accionable: reabrir solo con evidencia nueva.",
            )
            expired.append(
                {
                    "initiative_id": initiative_id,
                    "initiative_key": initiative.get("initiative_key"),
                    "reason": reason,
                    "rejected_proposal_ids": [],
                }
            )
            continue

        if human_review_no_output_expired:
            reason = f"revision humana sin propuesta accionable tras {age_days:.1f} dias"
            store.update_continuous_improvement_initiative(
                initiative_id,
                status="REJECTED",
                latest_decision={
                    "decision": "EXPIRED",
                    "source": "lifecycle",
                    "reason": reason,
                    "rejected_proposal_ids": [],
                },
                next_action="Expirada: el laboratorio autonomo no espera revision humana sin propuesta accionable.",
            )
            expired.append(
                {
                    "initiative_id": initiative_id,
                    "initiative_key": initiative.get("initiative_key"),
                    "reason": reason,
                    "rejected_proposal_ids": [],
                }
            )
            continue

        if status == "OPEN" and not has_open_tasks and active_proposals:
            store.update_continuous_improvement_initiative(
                initiative_id,
                status="VALIDATING",
                latest_decision={
                    "decision": "VALIDATING",
                    "source": "lifecycle",
                    "reason": "all_tasks_terminal_with_active_proposals",
                    "active_proposal_ids": active_proposals[:25],
                    "active_proposal_count": len(active_proposals),
                },
                next_action="Validar propuestas vinculadas antes de planificar mas tareas.",
            )
            advanced.append(
                {
                    "initiative_id": initiative_id,
                    "initiative_key": initiative.get("initiative_key"),
                    "status": "VALIDATING",
                    "active_proposal_count": len(active_proposals),
                }
            )
            continue

        churn_expired = age_days > ttl_days and not has_open_tasks and _is_decision_churn(initiative)
        stalled_expired = age_days > ttl_days and idle_days > stall_days and not has_open_tasks
        if churn_expired or stalled_expired:
            reason = (
                f"churn de decisiones sin avance util durante {age_days:.1f} dias"
                if churn_expired
                else f"estancada {idle_days:.1f} dias sin avance (edad {age_days:.1f}d)"
            )
            rejected_proposals = _reject_linked_pending_proposals(
                store,
                initiative,
                reason=reason,
                proposal_status_by_id=proposal_statuses,
            )
            store.update_continuous_improvement_initiative(
                initiative_id,
                status="REJECTED",
                latest_decision={
                    "decision": "EXPIRED",
                    "source": "lifecycle",
                    "reason": reason,
                    "rejected_proposal_ids": rejected_proposals,
                },
                next_action="Expirada por inactividad: reabrir solo con evidencia nueva.",
            )
            expired.append(
                {
                    "initiative_id": initiative_id,
                    "initiative_key": initiative.get("initiative_key"),
                    "reason": reason,
                    "rejected_proposal_ids": rejected_proposals,
                }
            )

    return {"closed": closed, "expired": expired, "advanced": advanced}


def flow_report(store: Store) -> dict[str, Any]:
    """WIP, edades y throughput del laboratorio: la salud del flujo en numeros."""

    initiatives = store.continuous_improvement_initiatives(limit=1000)
    by_status: dict[str, int] = {}
    ages_open: list[float] = []
    throughput_7d = 0
    for initiative in initiatives:
        status = str(initiative.get("status") or "")
        by_status[status] = by_status.get(status, 0) + 1
        if status in ACTIVE_INITIATIVE_STATUSES or status == "MONITORING":
            age = _age_hours(initiative.get("created_at"))
            if age is not None:
                ages_open.append(round(age / 24.0, 1))
        if status in {"CLOSED", "REJECTED"}:
            updated_age = _age_hours(initiative.get("updated_at"))
            if updated_age is not None and updated_age <= 7 * 24:
                throughput_7d += 1
    open_task_count = len(store.continuous_improvement_tasks(statuses=NON_TERMINAL_TASK_STATUSES, limit=2000))
    return {
        "initiatives_by_status": by_status,
        "wip": sum(by_status.get(s, 0) for s in ACTIVE_INITIATIVE_STATUSES),
        "open_task_count": open_task_count,
        "oldest_open_days": max(ages_open, default=0.0),
        "open_age_days": sorted(ages_open, reverse=True)[:10],
        "resolved_last_7d": throughput_7d,
    }


def run_lifecycle(store: Store, settings: Settings) -> dict[str, Any]:
    """Tick completo de ciclo de vida; idempotente y barato. Se llama por ciclo."""

    swept = sweep_stale_tasks(store, settings)
    resolved = resolve_initiatives(store, settings)
    report = flow_report(store)
    result = {"tasks": swept, "initiatives": resolved, "flow": report}
    try:
        log_system_event(settings.logs_dir, "ci_lifecycle_tick", result)
    except Exception as exc:  # noqa: BLE001 - el logging no debe romper el tick.
        log_swallow(LOGGER, "persistir evento del lifecycle CI", exc)
    return result
