"""Ciclo de vida del laboratorio de mejora continua (Etapa 7).

Problema que resuelve: las iniciativas se quedaban abiertas 7-8 dias sin
terminar y las tareas colgadas por dependencias muertas, asi que el laboratorio
acumulaba backlog en vez de mejorar. Reglas:

- TTL de tareas: una tarea no terminal mas vieja que `CI_TASK_TTL_HOURS` se
  cancela; sus dependientes tambien (el trabajo previo no ocurrio).
- Cierre con rendicion de cuentas: una iniciativa MONITORING sin tareas vivas
  y sin movimiento durante `CI_MONITORING_CLOSE_DAYS` se cierra con outcome
  (mejoro su target_metric o no).
- Expiracion: una iniciativa abierta mas de `CI_INITIATIVE_TTL_DAYS` dias y sin
  avance en `CI_INITIATIVE_STALL_DAYS` se marca REJECTED (expirada). Puede
  reabrirse despues, pero solo con evidencia nueva.
- El informe de flujo expone WIP, edades y throughput para el digest.

Todo es stdlib y deterministico: testeable sin LLM.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from ..logging_utils import log_system_event

if TYPE_CHECKING:  # pragma: no cover - solo anotaciones.
    from ..config import Settings
    from ..storage import Store


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


def sweep_stale_tasks(store: "Store", settings: "Settings") -> dict[str, Any]:
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


def _open_tasks_by_initiative(store: "Store") -> dict[str, int]:
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


def resolve_initiatives(store: "Store", settings: "Settings") -> dict[str, Any]:
    """Cierra iniciativas monitorizadas sin movimiento y expira las estancadas."""

    ttl_days = float(getattr(settings, "ci_initiative_ttl_days", 5.0))
    stall_days = float(getattr(settings, "ci_initiative_stall_days", 3.0))
    monitoring_close_days = float(getattr(settings, "ci_monitoring_close_days", 5.0))
    open_tasks = _open_tasks_by_initiative(store)

    closed: list[dict[str, Any]] = []
    expired: list[dict[str, Any]] = []
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

        if age_days > ttl_days and idle_days > stall_days and not has_open_tasks:
            store.update_continuous_improvement_initiative(
                initiative_id,
                status="REJECTED",
                latest_decision={
                    "decision": "EXPIRED",
                    "source": "lifecycle",
                    "reason": f"estancada {idle_days:.1f} dias sin avance (edad {age_days:.1f}d)",
                },
                next_action="Expirada por inactividad: reabrir solo con evidencia nueva.",
            )
            expired.append({"initiative_id": initiative_id, "initiative_key": initiative.get("initiative_key")})

    return {"closed": closed, "expired": expired}


def flow_report(store: "Store") -> dict[str, Any]:
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


def run_lifecycle(store: "Store", settings: "Settings") -> dict[str, Any]:
    """Tick completo de ciclo de vida; idempotente y barato. Se llama por ciclo."""

    swept = sweep_stale_tasks(store, settings)
    resolved = resolve_initiatives(store, settings)
    report = flow_report(store)
    result = {"tasks": swept, "initiatives": resolved, "flow": report}
    try:
        log_system_event(settings.logs_dir, "ci_lifecycle_tick", result)
    except Exception:  # noqa: BLE001 - el logging no debe romper el tick.
        pass
    return result
