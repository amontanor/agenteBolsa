"""Cuadro de mando diario de mejora (P-L123): responde tres preguntas.

1. Quien va mejor (sistema vs SPY) con cobertura explicita.
2. Que aprendio hoy el sistema (actividad, no mejora).
3. Que mejora real hubo hoy (admisiones, aplicaciones, promociones, impactos).

RESULTADO y PROCESO van separados: el volumen de actividad jamas cuenta
como mejora. El veredicto es SI solo con mejora real medida en el dia.
Todo read-only, stdlib + lectores de `Store`, testeable sin red ni broker.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

SPY_WINDOW_SESSIONS = 10


def _today_iso(today: str | None) -> str:
    if today:
        return today[:10]
    return datetime.now(timezone.utc).date().isoformat()


def _is_today(value: Any, today: str) -> bool:
    return str(value or "")[:10] == today


def _status_counts(rows: list[dict[str, Any]], today: str) -> dict[str, Any]:
    total: dict[str, int] = {}
    today_counts: dict[str, int] = {}
    for row in rows or []:
        status = str(row.get("status") or "UNKNOWN")
        total[status] = total.get(status, 0) + 1
        if _is_today(row.get("created_at"), today):
            today_counts[status] = today_counts.get(status, 0) + 1
    return {"total": total, "today": today_counts, "today_total": sum(today_counts.values())}


def _system_vs_spy(store: Any, settings: Any, today: str) -> dict[str, Any]:
    perf = store.performance_daily(limit=0) or []
    latest = perf[-1] if perf else {}
    equity = latest.get("equity")
    latest_session = str(latest.get("session_date") or today)[:10]
    coverage: dict[str, Any] = {
        "sessions_total": 0,
        "sessions_comparable": 0,
        "sessions_unavailable": 0,
        "provisional": True,
    }
    try:
        from .performance_benchmark import xnys_sessions_between
        from .spy_eod_authority import spy_eod_coverage

        end = min(latest_session, today)
        start = (date.fromisoformat(end) - timedelta(days=45)).isoformat()
        sessions = xnys_sessions_between(start, end)[-SPY_WINDOW_SESSIONS:]
        if sessions:
            coverage = spy_eod_coverage(settings, sessions[0], sessions[-1])
    except Exception:  # noqa: BLE001 - sin cobertura el cuadro sigue disponible.
        pass
    comparable = int(coverage.get("sessions_comparable") or 0)
    return {
        "session_date": latest.get("session_date"),
        "equity": equity,
        "pnl_pct": latest.get("pnl_pct"),
        "iq_score": latest.get("iq_score"),
        "coverage": coverage,
        "provisional": comparable < int(coverage.get("sessions_total") or 0) or comparable == 0,
    }


def _daily_learning(store: Any, today: str) -> dict[str, Any]:
    observations = store.learning_observations(limit=5000) or []
    obs_today = sum(1 for row in observations if _is_today(row.get("created_at"), today))
    lessons = store.distilled_lessons(limit=2000) or []
    lessons_today: dict[str, int] = {}
    for row in lessons:
        if _is_today(row.get("created_at"), today):
            status = str(row.get("status") or "UNKNOWN")
            lessons_today[status] = lessons_today.get(status, 0) + 1
    experiments = store.continuous_improvement_experiments(limit=2000) or []
    exp_today: dict[str, int] = {}
    for row in experiments:
        if _is_today(row.get("created_at"), today):
            status = str(row.get("status") or "UNKNOWN")
            exp_today[status] = exp_today.get(status, 0) + 1
    return {
        "observations_today": obs_today,
        "lessons_today": lessons_today,
        "lessons_net": sum(lessons_today.values()),
        "experiments_today": exp_today,
        "experiments_net": sum(exp_today.values()),
    }


def _real_improvement(store: Any, today: str) -> dict[str, Any]:
    proposals = store.continuous_improvement_proposals(limit=5000) or []
    admitted_today = sum(
        1
        for row in proposals
        if _is_today(row.get("created_at"), today) and str(row.get("status") or "") not in {"REJECTED", "REJECTED_BY_TESTS"}
    )
    proposals_total = _status_counts(proposals, today)
    changes = store.continuous_improvement_applied_changes(limit=1000) or []
    applied_total = sum(1 for row in changes if str(row.get("status") or "") == "APPLIED")
    rolled_total = sum(1 for row in changes if str(row.get("status") or "") == "ROLLED_BACK")
    applied_today = sum(
        1 for row in changes if str(row.get("status") or "") == "APPLIED" and _is_today(row.get("created_at"), today)
    )
    impacts = {"passed_total": 0, "failed_total": 0, "passed_today": 0, "failed_today": 0}
    for row in changes:
        impact = (row.get("decision") or {}).get("impact_validation") or {}
        status = str(impact.get("status") or "").upper()
        measured_at = str(impact.get("measured_at") or "")
        if status == "PASSED":
            impacts["passed_total"] += 1
            impacts["passed_today"] += 1 if _is_today(measured_at, today) else 0
        elif status == "FAILED":
            impacts["failed_total"] += 1
            impacts["failed_today"] += 1 if _is_today(measured_at, today) else 0
    windows = store.promotion_windows(limit=500) or []
    windows_total = _status_counts(windows, today)
    policies = store.learning_policy_candidates(limit=1000) or []
    policies_total = _status_counts(policies, today)
    evaluations = store.learning_policy_evaluations(limit=2000) or []
    sync_today = sum(
        1
        for row in evaluations
        if str(row.get("phase") or "") == "promotion_sync" and _is_today(row.get("created_at"), today)
    )
    validations = store.continuous_improvement_validations(limit=20000) or []
    expired_total = sum(1 for row in validations if str(row.get("status") or "") == "EXPIRED_PENDING")
    expired_today_decisions = sum(
        1
        for row in (store.continuous_improvement_decisions(limit=20000) or [])
        if str(row.get("reason") or "") == "pending_validation_expired" and _is_today(row.get("created_at"), today)
    )
    return {
        "proposals_admitted_today": admitted_today,
        "proposals_total": proposals_total,
        "applied_today": applied_today,
        "applied_total": applied_total,
        "rolled_back_total": rolled_total,
        "impacts": impacts,
        "windows_total": windows_total,
        "policies_total": policies_total,
        "promotion_sync_today": sync_today,
        "validations_expired_total": expired_total,
        "validations_expired_today": expired_today_decisions,
    }


def build_improvement_dashboard(
    store: Any, settings: Any, *, today: str | None = None
) -> dict[str, Any]:
    """Construye el cuadro diario. `today` YYYY-MM-DD (UTC) para tests."""
    day = _today_iso(today)
    system_vs_spy = _system_vs_spy(store, settings, day)
    daily_learning = _daily_learning(store, day)
    real = _real_improvement(store, day)
    improved_today = bool(
        real["applied_today"] > 0
        or real["promotion_sync_today"] > 0
        or real["impacts"]["passed_today"] > 0
        or real["impacts"]["failed_today"] > 0
        or real["validations_expired_today"] > 0
    )
    verdict = "SI" if improved_today else "NO"
    markdown = "\n".join(
        [
            f"# Mejora diaria — {day} — veredicto: {verdict}",
            "",
            "## RESULTADO",
            f"- Sistema vs SPY: veredicto pendiente (comparables "
            f"{system_vs_spy['coverage'].get('sessions_comparable')}/"
            f"{system_vs_spy['coverage'].get('sessions_total')}, "
            f"provisional={system_vs_spy['provisional']}).",
            f"- Equity: {system_vs_spy.get('equity')} | pnl_dia: {system_vs_spy.get('pnl_pct')} | "
            f"iq: {system_vs_spy.get('iq_score')}.",
            f"- Mejora real hoy: {verdict} (aplicados={real['applied_today']}, "
            f"sync={real['promotion_sync_today']}, impactos={real['impacts']['passed_today']}/"
            f"{real['impacts']['failed_today']}, caducadas={real['validations_expired_today']}).",
            "",
            "## PROCESO (actividad, no es mejora)",
            f"- Observaciones: {daily_learning['observations_today']} | lecciones netas: "
            f"{daily_learning['lessons_net']} | experimentos netos: {daily_learning['experiments_net']}.",
            f"- Propuestas admitidas hoy: {real['proposals_admitted_today']}.",
        ]
    )
    return {
        "date": day,
        "verdict": verdict,
        "system_vs_spy": system_vs_spy,
        "daily_learning": daily_learning,
        "real_improvement": real,
        "markdown": markdown,
    }
