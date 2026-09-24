"""Dictamen operativo del grupo de agentes.

Este modulo resume exclusivamente la telemetria de ejecucion ya capturada.
No interpreta P/L, no promociona agentes y no convierte volumen de runs en
evidencia de edge. La calidad predictiva permanece ``not_evaluable`` hasta que
existan outcomes maduros y controles comparables.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..agent_registry import canonical_agent_id

SCHEMA_VERSION = "p-l97.agent-group-review.v1"
_TERMINAL_STATES = ("succeeded", "failed", "timeout", "skipped", "blocked")


def build_agent_group_conclusions(
    productivity: Mapping[str, Any] | None,
    *,
    expected_roles: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Build an auditable operational conclusion for each configured role.

    ``healthy`` means only that the observed runs terminated without execution
    failures or empty outputs from successful runs. Blocked/skipped runs may
    intentionally have no output. Legacy payloads that cannot attribute an
    empty output to a state are ``ambiguous`` rather than being imputed to
    ``succeeded``. It is deliberately not a claim about trading skill. Roles
    with no runs are surfaced as ``no_data`` instead of being omitted.
    """

    report = productivity if isinstance(productivity, Mapping) else {}
    observed = report.get("runs_by_role")
    observed_roles = _canonicalize_role_reports(observed if isinstance(observed, Mapping) else {})
    expected = {
        _canonical_role_name(role)
        for role in (expected_roles or [])
        if _canonical_role_name(role)
    }
    role_names = sorted({str(role).strip() for role in observed_roles if str(role).strip()} | expected)
    roles: list[dict[str, Any]] = []
    for role in role_names:
        role_report = observed_roles.get(role) or {}
        roles.append(_role_conclusion(role, role_report))

    degraded_roles = [item["role"] for item in roles if item["status"] == "degraded"]
    ambiguous_roles = [item["role"] for item in roles if item["status"] == "ambiguous"]
    no_data_roles = [item["role"] for item in roles if item["status"] == "no_data"]
    controlled_roles = [
        item["role"] for item in roles if item["status"] == "controlled_blocked"
    ]
    observed_run_count = _nonnegative_int(report.get("total_runs"))
    if not roles or observed_run_count == 0:
        execution_status = "unavailable"
        conclusion = "No hay runs observados del grupo; la actividad del agente es unavailable."
    elif ambiguous_roles:
        execution_status = "unavailable"
        conclusion = (
            f"No se puede atribuir la salida vacía por estado en {len(ambiguous_roles)} rol(es); "
            "la evidencia operativa es ambiguous."
        )
    elif degraded_roles:
        execution_status = "degraded"
        conclusion = f"Hay fallos operativos en {len(degraded_roles)} rol(es); requieren revisión."
    elif no_data_roles:
        execution_status = "collecting"
        conclusion = f"Ejecución estable, pero faltan datos de {len(no_data_roles)} rol(es)."
    elif controlled_roles and len(controlled_roles) == len(roles):
        execution_status = "controlled_blocked"
        conclusion = "Los runs observados quedaron bloqueados o omitidos por una condición controlada."
    else:
        execution_status = "healthy"
        conclusion = "Ejecución observada estable; esto no demuestra valor predictivo."

    actions: list[str] = []
    if degraded_roles:
        actions.append("Revisar primero los roles degradados y sus error_code antes de volver a ejecutar.")
    if ambiguous_roles:
        actions.append(
            "Regenerar telemetría con atribución por estado; no inferir salidas vacías de runs succeeded."
        )
    if no_data_roles:
        actions.append("Verificar wiring, cadencia y ventana de cada rol sin runs.")
    if not actions and controlled_roles:
        actions.append("Confirmar que los bloqueos controlados corresponden a precondiciones esperadas.")
    actions.append("Mantener calidad predictiva en not_evaluable hasta outcomes maduros y control same-cycle.")

    return {
        "schema_version": SCHEMA_VERSION,
        "execution_status": execution_status,
        "quality_status": "not_evaluable",
        "quality_reason": "mature_outcomes_and_same_cycle_control_unavailable",
        "conclusion": conclusion,
        "recommended_actions": actions,
        "summary": {
            "roles_observed": sum(item["runs"] > 0 for item in roles),
            "roles_expected": len(expected),
            "roles_degraded": len(degraded_roles),
            "roles_ambiguous": len(ambiguous_roles),
            "roles_no_data": len(no_data_roles),
            "roles_controlled_blocked": len(controlled_roles),
            "total_runs": observed_run_count,
            "terminal_runs": _nonnegative_int(report.get("terminal_runs")),
            "failed_runs": _nonnegative_int(report.get("failed")),
            "timeout_runs": _nonnegative_int(report.get("timeout")),
            "open_runs": _nonnegative_int(report.get("open_runs")),
            "empty_output_runs": _nonnegative_int(report.get("empty_output_count")),
            "empty_success_output_runs": _empty_success_output_count(report, roles),
        },
        "roles": roles,
    }


def _role_conclusion(role: str, report: Mapping[str, Any]) -> dict[str, Any]:
    runs = _nonnegative_int(report.get("runs"))
    states = report.get("states") if isinstance(report.get("states"), Mapping) else {}
    succeeded = _nonnegative_int(states.get("succeeded"))
    failed = _nonnegative_int(states.get("failed"))
    timeout = _nonnegative_int(states.get("timeout"))
    skipped = _nonnegative_int(states.get("skipped"))
    blocked = _nonnegative_int(states.get("blocked"))
    open_runs = _nonnegative_int(states.get("started"))
    terminal = sum(_nonnegative_int(states.get(state)) for state in _TERMINAL_STATES)
    empty_outputs = _nonnegative_int(report.get("empty_outputs"))
    raw_empty_success_outputs = report.get("empty_success_outputs")
    attribution_ambiguous = (
        raw_empty_success_outputs is None and succeeded > 0 and empty_outputs > 0
    )
    empty_success_outputs = None if attribution_ambiguous else _nonnegative_int(raw_empty_success_outputs)
    failure_count = failed + timeout
    if runs == 0:
        status = "no_data"
        conclusion = "No hay ejecuciones observadas para este rol."
        action = "Comprobar wiring y cadencia; no inferir inactividad ni calidad."
    elif attribution_ambiguous:
        status = "ambiguous"
        conclusion = (
            "No se puede atribuir la salida vacía a un estado concreto en este payload legacy/partial."
        )
        action = "Regenerar el informe con empty_success_outputs; no imputar el vacío a succeeded."
    elif failure_count or empty_success_outputs or open_runs:
        status = "degraded"
        reasons: list[str] = []
        if failure_count:
            reasons.append(f"{failure_count} fallo(s)/timeout")
        if open_runs:
            reasons.append(f"{open_runs} run(s) abierto(s)")
        if empty_success_outputs:
            reasons.append(f"{empty_success_outputs} salida(s) vacía(s) en éxito")
        conclusion = "Ejecución degradada: " + ", ".join(reasons) + "."
        action = "Revisar error_code, terminalidad y contrato de salida antes de valorar el rol."
    elif succeeded == 0 and (skipped or blocked):
        status = "controlled_blocked"
        conclusion = "Sin éxito ejecutado; solo hubo skips/bloqueos controlados."
        action = "Confirmar que la precondición de bloqueo era la esperada."
    else:
        status = "healthy"
        conclusion = "Runs terminales sin fallo operativo ni salida vacía."
        action = "Seguir recogiendo outcomes; salud operativa no equivale a edge."
    return {
        "role": role,
        "status": status,
        "runs": runs,
        "terminal_runs": terminal,
        "successes": succeeded,
        "failures": failed,
        "timeouts": timeout,
        "skipped": skipped,
        "blocked": blocked,
        "open_runs": open_runs,
        "empty_outputs": empty_outputs,
        "empty_success_outputs": empty_success_outputs,
        "raw_roles": dict(report.get("raw_roles") or {})
        if isinstance(report.get("raw_roles"), Mapping)
        else {},
        "terminal_rate": round(terminal / runs, 4) if runs else None,
        "failure_rate": round(failure_count / terminal, 4) if terminal else None,
        "output_coverage": (
            round((succeeded - empty_success_outputs) / succeeded, 4)
            if succeeded and empty_success_outputs is not None
            else None
        ),
        "conclusion": conclusion,
        "recommended_action": action,
    }


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _canonical_role_name(value: object) -> str:
    raw = str(value or "").strip()
    return canonical_agent_id(raw) or raw


def _canonicalize_role_reports(
    observed_roles: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Join direct legacy aggregates without rewriting their raw identity.

    The normal producer already emits canonical roles. This boundary also
    accepts older persisted aggregates so a direct consumer cannot silently
    report a mapped legacy role as a separate healthy/no-data pair.
    """

    normalized: dict[str, dict[str, Any]] = {}
    numeric_fields = (
        "runs",
        "outputs",
        "findings",
        "proposals",
        "fallbacks",
        "input_tokens",
        "output_tokens",
        "tokens_available_runs",
        "empty_outputs",
    )
    for raw_role, raw_report in observed_roles.items():
        raw_name = str(raw_role or "").strip()
        if not raw_name:
            continue
        role = _canonical_role_name(raw_name)
        source = raw_report if isinstance(raw_report, Mapping) else {}
        target = normalized.setdefault(role, {"raw_roles": {}})
        for field in numeric_fields:
            target[field] = _nonnegative_int(target.get(field)) + _nonnegative_int(source.get(field))
        for field in ("states", "execution_kinds"):
            source_counts = source.get(field)
            if not isinstance(source_counts, Mapping):
                continue
            target_counts = target.setdefault(field, {})
            for state, value in source_counts.items():
                state_name = str(state).strip()
                if state_name:
                    target_counts[state_name] = _nonnegative_int(target_counts.get(state_name)) + _nonnegative_int(value)
        source_raw_roles = source.get("raw_roles")
        target_raw_roles = target.setdefault("raw_roles", {})
        if isinstance(source_raw_roles, Mapping):
            for source_raw_role, value in source_raw_roles.items():
                source_raw_name = str(source_raw_role).strip()
                if source_raw_name:
                    target_raw_roles[source_raw_name] = _nonnegative_int(
                        target_raw_roles.get(source_raw_name)
                    ) + _nonnegative_int(value)
        else:
            target_raw_roles[raw_name] = _nonnegative_int(target_raw_roles.get(raw_name)) + _nonnegative_int(
                source.get("runs")
            )
        if "empty_success_outputs" not in source or source.get("empty_success_outputs") is None:
            target["_empty_success_outputs_unknown"] = True
        else:
            target["empty_success_outputs"] = _nonnegative_int(
                target.get("empty_success_outputs")
            ) + _nonnegative_int(source.get("empty_success_outputs"))
    for target in normalized.values():
        if target.pop("_empty_success_outputs_unknown", False):
            target["empty_success_outputs"] = None
        else:
            target.setdefault("empty_success_outputs", 0)
    return normalized


def _empty_success_output_count(
    report: Mapping[str, Any], roles: list[Mapping[str, Any]]
) -> int | None:
    if any(role.get("empty_success_outputs") is None for role in roles if role.get("runs")):
        return None
    value = report.get("empty_success_output_count")
    if value is not None:
        return _nonnegative_int(value)
    return sum(_nonnegative_int(role.get("empty_success_outputs")) for role in roles)
