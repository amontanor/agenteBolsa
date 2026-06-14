"""Unified operational health report for jobs, data and setup degradation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.market_calendar import MarketCalendar
from agente_bolsa.storage import Store

from .reporting import write_json_report


JOB_NAMES = [
    "portfolio_watch",
    "market_cycle",
    "closed_market_technical_study",
    "daily_study",
    "post_market_review",
    "pre_earnings",
]

JOB_DURATION_WARNINGS = {
    "portfolio_watch": 30.0,
    "market_cycle": 600.0,
    "closed_market_technical_study": 1800.0,
    "daily_study": 900.0,
    "post_market_review": 900.0,
    "pre_earnings": 1200.0,
}

CRITICAL_KILL_SWITCH_KINDS = {
    "data_pipeline_down",
    "job_failed",
    "missing_report",
}
KILL_SWITCH_MAX_REPORT_AGE_SECONDS = 6 * 60 * 60
DATA_PIPELINE_MAX_STALE_SECONDS = 30 * 60
DATA_PIPELINE_REPORT_PATTERNS = (
    "market_snapshot_*.json",
    "market_state_*.json",
    "breakout_scan_*.json",
    "closed_market_technical_study_*.json",
)


def _job_state_key(job_name: str) -> str:
    return f"scheduler_job_status:{job_name}"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _latest_report_payload(data_dir: Path, filename: str) -> dict[str, Any] | None:
    return _load_json(data_dir / "reports" / filename)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _freshness_status(heartbeat_at: Any, *, max_age_seconds: int) -> dict[str, Any]:
    parsed = _parse_datetime(heartbeat_at)
    if parsed is None:
        return {
            "status": "missing",
            "heartbeat_at": heartbeat_at,
            "age_seconds": None,
            "max_age_seconds": max_age_seconds,
            "is_fresh": False,
        }
    age_seconds = max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())
    return {
        "status": "fresh" if age_seconds <= max_age_seconds else "stale",
        "heartbeat_at": parsed.isoformat(),
        "age_seconds": round(age_seconds, 3),
        "max_age_seconds": max_age_seconds,
        "is_fresh": age_seconds <= max_age_seconds,
    }


def _latest_report_file_time(reports_dir: Path, patterns: tuple[str, ...]) -> tuple[Path, datetime] | None:
    latest: tuple[Path, datetime] | None = None
    for pattern in patterns:
        for path in reports_dir.glob(pattern):
            if not path.is_file() or path.name.endswith(".manifest.json"):
                continue
            try:
                modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            if latest is None or modified_at > latest[1]:
                latest = (path, modified_at)
    return latest


def _data_pipeline_heartbeat(settings: Settings, data_dir: Path, now: datetime | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    calendar = MarketCalendar(settings.market_calendar, settings.local_timezone)
    market = calendar.status(now)
    now_utc = _parse_datetime(market.now_utc) or datetime.now(timezone.utc)
    market_open = _parse_datetime(market.market_open)
    reports_dir = data_dir / "reports"
    latest = _latest_report_file_time(reports_dir, DATA_PIPELINE_REPORT_PATTERNS)
    latest_path = str(latest[0]) if latest else None
    latest_at = latest[1] if latest else None
    latest_age_seconds = (now_utc - latest_at).total_seconds() if latest_at else None
    open_age_seconds = (now_utc - market_open).total_seconds() if market_open else None

    summary: dict[str, Any] = {
        "market_is_open": market.is_open,
        "session_date": market.session_date,
        "max_stale_seconds": DATA_PIPELINE_MAX_STALE_SECONDS,
        "latest_report_path": latest_path,
        "latest_report_at": latest_at.isoformat() if latest_at else None,
        "latest_report_age_seconds": round(max(0.0, latest_age_seconds), 3) if latest_age_seconds is not None else None,
        "market_open_age_seconds": round(max(0.0, open_age_seconds), 3) if open_age_seconds is not None else None,
    }

    if not market.is_open:
        summary["status"] = "not_required_market_closed"
        return summary, []
    if open_age_seconds is not None and open_age_seconds < DATA_PIPELINE_MAX_STALE_SECONDS:
        summary["status"] = "grace_period_after_open"
        return summary, []
    if latest_age_seconds is not None and latest_age_seconds <= DATA_PIPELINE_MAX_STALE_SECONDS:
        summary["status"] = "fresh"
        return summary, []

    summary["status"] = "stale_or_missing"
    detail = (
        "Mercado abierto sin snapshots/reportes de datos frescos en "
        f"{DATA_PIPELINE_MAX_STALE_SECONDS // 60} minutos."
    )
    if latest_path:
        detail += f" Ultimo reporte: {latest_path} hace {int(max(0.0, latest_age_seconds or 0))}s."
    else:
        detail += " No hay reportes de mercado producidos."
    return summary, [
        {
            "severity": "critical",
            "kind": "data_pipeline_down",
            "scope": "market_data",
            "detail": detail,
        }
    ]


def load_operational_response_context(data_dir: Path) -> dict[str, Any]:
    payload = _latest_report_payload(data_dir, "latest_operational_health.json") or {}
    responses = payload.get("responses", []) if isinstance(payload, dict) else []
    setup_penalties: dict[str, float] = {}
    response_notes: dict[str, list[str]] = {}
    for item in responses or []:
        if str(item.get("action") or "") != "deprioritize_setup_before_llm":
            continue
        if str(item.get("status") or "") not in {"guarded_active", "active"}:
            continue
        scope = str(item.get("scope") or "").strip()
        penalty = item.get("candidate_priority_penalty")
        if scope and isinstance(penalty, (int, float)):
            setup_penalties[scope] = float(penalty)
            response_notes.setdefault(scope, []).append(str(item.get("detail") or item.get("reason") or "").strip())
    return {
        "responses": responses,
        "setup_penalties": setup_penalties,
        "response_notes": response_notes,
    }


KILL_SWITCH_OVERRIDE_FILENAME = "operational_kill_switch.json"


def _kill_switch_override_path(data_dir: Path) -> Path:
    return data_dir / "state" / KILL_SWITCH_OVERRIDE_FILENAME


def activate_persistent_kill_switch(
    data_dir: Path,
    *,
    reason: str,
    kind: str = "manual",
) -> dict[str, Any]:
    """Activa un kill switch persistente que bloquea la ejecucion de compras.

    A diferencia de los alerts derivados del reporte (que se recalculan cada
    ciclo), este override vive en disco hasta que se desactiva explicitamente.
    Lo usa, por ejemplo, ``kernel_integrity`` ante una violacion de integridad.
    """

    path = _kill_switch_override_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "active": True,
        "kind": kind,
        "reason": reason,
        "activated_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return payload


def clear_persistent_kill_switch(data_dir: Path) -> bool:
    """Desactiva el kill switch persistente. Devuelve True si existia."""

    path = _kill_switch_override_path(data_dir)
    if path.exists():
        path.unlink()
        return True
    return False


def load_persistent_kill_switch(data_dir: Path) -> dict[str, Any]:
    payload = _load_json(_kill_switch_override_path(data_dir)) or {}
    return payload if bool(payload.get("active")) else {}


def load_operational_block_context(data_dir: Path) -> dict[str, Any]:
    override = load_persistent_kill_switch(data_dir)
    if override:
        reason = str(override.get("reason") or "kill_switch_persistente_activo")
        return {
            "available": True,
            "as_of": override.get("activated_at"),
            "kill_switch_active": True,
            "block_new_buys": True,
            "block_buy_execution": True,
            "blocking_alerts": [
                {
                    "kind": str(override.get("kind") or "manual"),
                    "scope": "global",
                    "detail": reason,
                }
            ],
            "reasons": [reason],
        }
    path = data_dir / "reports" / "latest_operational_health.json"
    if not path.exists():
        return {
            "available": False,
            "as_of": None,
            "kill_switch_active": False,
            "block_new_buys": False,
            "block_buy_execution": False,
            "blocking_alerts": [],
            "reasons": [],
        }
    age_seconds = (datetime.now(timezone.utc).timestamp() - path.stat().st_mtime)
    if age_seconds > KILL_SWITCH_MAX_REPORT_AGE_SECONDS:
        return {
            "available": True,
            "as_of": None,
            "kill_switch_active": False,
            "block_new_buys": False,
            "block_buy_execution": False,
            "blocking_alerts": [],
            "reasons": [f"stale_operational_health_report:{int(age_seconds)}s"],
        }
    payload = _load_json(path) or {}
    alerts = payload.get("alerts", []) if isinstance(payload, dict) else []
    blocking_alerts = []
    for item in alerts or []:
        if str(item.get("severity") or "").lower() != "critical":
            continue
        kind = str(item.get("kind") or "")
        if kind not in CRITICAL_KILL_SWITCH_KINDS:
            continue
        blocking_alerts.append(
            {
                "kind": kind,
                "scope": item.get("job") or item.get("scope") or "global",
                "detail": str(item.get("detail") or "").strip(),
            }
        )

    reasons = [
        f"{item['kind']}:{item['scope']}: {item['detail']}".strip()
        for item in blocking_alerts
    ]
    return {
        "available": bool(payload),
        "as_of": payload.get("as_of") if isinstance(payload, dict) else None,
        "kill_switch_active": bool(blocking_alerts),
        "block_new_buys": bool(blocking_alerts),
        "block_buy_execution": bool(blocking_alerts),
        "blocking_alerts": blocking_alerts,
        "reasons": reasons,
    }


def _job_runtime(store: Store) -> dict[str, Any]:
    return {job_name: store.get_runtime_value(_job_state_key(job_name)) for job_name in JOB_NAMES}


def _job_alerts(job_runtime: dict[str, Any]) -> list[dict[str, Any]]:
    alerts = []
    for job_name, state in job_runtime.items():
        if not state:
            alerts.append(
                {
                    "severity": "warning",
                    "kind": "job_never_recorded",
                    "job": job_name,
                    "detail": "El job todavia no ha dejado estado operativo en runtime_state.",
                }
            )
            continue
        status = str(state.get("status") or "")
        if status == "failed":
            alerts.append(
                {
                    "severity": "critical",
                    "kind": "job_failed",
                    "job": job_name,
                    "detail": str(state.get("detail") or "Fallo sin detalle."),
                }
            )
        duration = state.get("duration_seconds")
        warning_threshold = JOB_DURATION_WARNINGS.get(job_name)
        if isinstance(duration, (int, float)) and warning_threshold and duration > warning_threshold:
            alerts.append(
                {
                    "severity": "warning",
                    "kind": "job_slow",
                    "job": job_name,
                    "detail": f"Duracion {duration:.2f}s > umbral {warning_threshold:.2f}s.",
                }
            )
    return alerts


def _report_health(settings: Settings, data_dir: Path, now: datetime | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    reports = {
        "technical_study": _latest_report_payload(data_dir, "latest_closed_market_technical_study.json"),
        "breakout_scan": _latest_report_payload(data_dir, "latest_breakout_scan.json"),
        "daily_learning_digest": _latest_report_payload(data_dir, "latest_daily_learning_digest.json"),
        "post_market_learning": _latest_report_payload(data_dir, "latest_post_market_learning.json"),
        "signal_learning": _latest_report_payload(data_dir, "latest_signal_learning.json"),
    }
    alerts: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    data_pipeline, data_pipeline_alerts = _data_pipeline_heartbeat(settings, data_dir, now)
    summary["data_pipeline"] = data_pipeline
    alerts.extend(data_pipeline_alerts)

    technical = reports["technical_study"] or {}
    market_data = technical.get("market_data", {}) or {}
    missing_count = int(market_data.get("missing_symbols_count") or 0)
    requested_count = int(market_data.get("requested_count") or 0)
    missing_ratio = (missing_count / requested_count) if requested_count else 0.0
    summary["technical_study"] = {
        "available": bool(technical),
        "symbols_scanned": technical.get("symbols_scanned"),
        "symbols_with_data": technical.get("symbols_with_data"),
        "warnings_count": len(technical.get("warnings", []) or []),
        "missing_symbols_count": missing_count,
        "missing_ratio": round(missing_ratio, 4),
    }
    if not technical:
        alerts.append(
            {
                "severity": "critical",
                "kind": "missing_report",
                "scope": "technical_study",
                "detail": "No existe latest_closed_market_technical_study.json.",
            }
        )
    elif missing_ratio >= 0.10:
        alerts.append(
            {
                "severity": "warning",
                "kind": "market_data_coverage_drop",
                "scope": "technical_study",
                "detail": f"Faltan datos para {missing_count}/{requested_count} simbolos.",
            }
        )

    digest = reports["daily_learning_digest"] or {}
    setup_rows = digest.get("setup_stats_3d", []) or []
    degrading_setups = [
        item
        for item in setup_rows
        if int(item.get("matured") or 0) >= 5
        and (
            (isinstance(item.get("avg_return"), (int, float)) and float(item["avg_return"]) < 0)
            or (isinstance(item.get("win_rate"), (int, float)) and float(item["win_rate"]) < 0.40)
        )
    ]
    summary["daily_learning_digest"] = {
        "available": bool(digest),
        "setup_stats_count": len(setup_rows),
        "degrading_setups": degrading_setups[:5],
    }
    for item in degrading_setups[:5]:
        alerts.append(
            {
                "severity": "warning",
                "kind": "setup_edge_deterioration",
                "scope": str(item.get("setup")),
                "detail": (
                    f"Setup {item.get('setup')} con avg_return={item.get('avg_return')} "
                    f"y win_rate={item.get('win_rate')} en 3d."
                ),
            }
        )

    post_market = reports["post_market_learning"] or {}
    pipeline_steps = post_market.get("pipeline_steps", {}) or {}
    summary["post_market_learning"] = {
        "available": bool(post_market),
        "pipeline_steps": pipeline_steps,
    }
    if pipeline_steps:
        total = sum(float(value) for value in pipeline_steps.values() if isinstance(value, (int, float)))
        if total > 1200:
            alerts.append(
                {
                    "severity": "warning",
                    "kind": "post_market_pipeline_slow",
                    "scope": "post_market_review",
                    "detail": f"Pipeline post-market tarda {total:.2f}s acumulados.",
                }
            )

    return summary, alerts


def _response_id(kind: str, scope: str) -> str:
    clean_scope = scope.replace(" ", "_").replace("/", "_") or "global"
    return f"{kind}:{clean_scope}"


def _build_operational_responses(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    responses: list[dict[str, Any]] = []
    seen: set[str] = set()
    for alert in alerts:
        kind = str(alert.get("kind") or "")
        scope = str(alert.get("job") or alert.get("scope") or "global")
        detail = str(alert.get("detail") or "")
        if kind == "setup_edge_deterioration":
            response = {
                "response_id": _response_id(kind, scope),
                "status": "guarded_active",
                "action": "deprioritize_setup_before_llm",
                "scope": scope,
                "mode": "ranking_only",
                "candidate_priority_penalty": 0.05,
                "detail": f"Reducir prioridad del setup {scope} hasta que recupere edge reciente.",
                "reason": detail,
            }
        elif kind == "data_pipeline_down":
            response = {
                "response_id": _response_id(kind, scope),
                "status": "guarded_active",
                "action": "block_new_buys_until_data_pipeline_recovers",
                "scope": scope,
                "mode": "kill_switch",
                "detail": "Bloquear compras nuevas hasta que el pipeline genere un snapshot fresco.",
                "reason": detail,
            }
        elif kind in {"market_data_coverage_drop", "missing_report"}:
            response = {
                "response_id": _response_id(kind, scope),
                "status": "shadow",
                "action": "pause_recent_universe_overlays",
                "scope": scope,
                "mode": "shadow_only",
                "target_universes": [
                    "sp500_plus_recent_breakouts",
                    "sp500_plus_recent_leaders",
                ],
                "detail": "No ampliar universo con overlays recientes mientras la cobertura de datos siga degradada.",
                "reason": detail,
            }
        elif kind == "job_failed":
            response = {
                "response_id": _response_id(kind, scope),
                "status": "shadow",
                "action": "investigate_failed_job",
                "scope": scope,
                "mode": "shadow_only",
                "detail": "Registrar y priorizar investigacion operativa antes de promover cambios de politica.",
                "reason": detail,
            }
        elif kind == "post_market_pipeline_slow":
            response = {
                "response_id": _response_id(kind, scope),
                "status": "shadow",
                "action": "review_optional_pipeline_steps",
                "scope": scope,
                "mode": "shadow_only",
                "detail": "Revisar pasos opcionales y cuellos de botella antes de ampliar el pipeline.",
                "reason": detail,
            }
        else:
            continue
        response_id = str(response["response_id"])
        if response_id in seen:
            continue
        seen.add(response_id)
        responses.append(response)
    return responses


def build_production_health_report(
    settings: Settings,
    store: Store,
    reports_dir: Path,
    run_id: str,
) -> dict[str, Any]:
    operational_report = build_operational_health_report(settings, store, reports_dir, run_id)
    ci_runtime = store.continuous_improvement_runtime_state()
    latest_cycle = store.latest_continuous_improvement_cycle()
    applied_changes = store.continuous_improvement_applied_changes(limit=500)
    committee_decisions = store.continuous_improvement_decisions(actor="DecisionCommitteeAgent", limit=500)

    ci_max_age_seconds = max(300, int(settings.continuous_improvement_runtime_interval_seconds) * 3)
    ci_freshness = _freshness_status((ci_runtime or {}).get("heartbeat_at"), max_age_seconds=ci_max_age_seconds)
    scheduler_runtime = operational_report.get("job_runtime", {}) or {}
    scheduler_updates = [
        _parse_datetime((item or {}).get("finished_at"))
        for item in scheduler_runtime.values()
        if isinstance(item, dict)
    ]
    scheduler_updates = [item for item in scheduler_updates if item is not None]
    latest_scheduler_update = max(scheduler_updates) if scheduler_updates else None
    scheduler_max_age_seconds = max(900, int(settings.run_interval_seconds) * 2)
    scheduler_freshness = _freshness_status(
        latest_scheduler_update.isoformat() if latest_scheduler_update else None,
        max_age_seconds=scheduler_max_age_seconds,
    )

    continuous_improvement_summary = {
        "enabled": settings.continuous_improvement_enabled,
        "status": (ci_runtime or {}).get("status") or "missing",
        "heartbeat": ci_freshness,
        "latest_cycle": {
            "cycle_id": (latest_cycle or {}).get("cycle_id"),
            "status": (latest_cycle or {}).get("status"),
            "updated_at": (latest_cycle or {}).get("updated_at"),
        }
        if latest_cycle
        else None,
        "applied_changes": len([item for item in applied_changes if item.get("status") == "APPLIED"]),
        "rolled_back_changes": len([item for item in applied_changes if item.get("status") == "ROLLED_BACK"]),
        "committee_decisions": len(committee_decisions),
    }

    alerts = list(operational_report.get("alerts", []))
    responses = list(operational_report.get("responses", []))
    if not ci_freshness["is_fresh"]:
        alerts.append(
            {
                "severity": "warning" if ci_runtime else "critical",
                "kind": "continuous_improvement_runtime_stale" if ci_runtime else "continuous_improvement_runtime_missing",
                "scope": "continuous_improvement",
                "detail": (
                    f"Heartbeat de mejora continua {ci_freshness['status']} "
                    f"(max_age={ci_freshness['max_age_seconds']}s)."
                ),
            }
        )
    if not scheduler_freshness["is_fresh"]:
        alerts.append(
            {
                "severity": "warning" if scheduler_updates else "critical",
                "kind": "scheduler_runtime_stale" if scheduler_updates else "scheduler_runtime_missing",
                "scope": "scheduler",
                "detail": (
                    f"Ultima actualizacion del scheduler {scheduler_freshness['status']} "
                    f"(max_age={scheduler_freshness['max_age_seconds']}s)."
                ),
            }
        )

    severity_counts = {
        "critical": sum(1 for item in alerts if item["severity"] == "critical"),
        "warning": sum(1 for item in alerts if item["severity"] == "warning"),
        "info": sum(1 for item in alerts if item["severity"] == "info"),
    }
    overall_status = "critical" if severity_counts["critical"] > 0 else "warning" if severity_counts["warning"] > 0 else "ok"
    report = {
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "overall_status": overall_status,
            "healthy": overall_status == "ok",
            "alerts": len(alerts),
            "severity_counts": severity_counts,
            "responses": len(responses),
            "scheduler_heartbeat": scheduler_freshness,
            "continuous_improvement_heartbeat": ci_freshness,
        },
        "operational_health": operational_report,
        "alerts": alerts,
        "responses": responses,
        "scheduler_heartbeat": scheduler_freshness,
        "continuous_improvement": continuous_improvement_summary,
    }
    return write_json_report(report, reports_dir, "production_health", run_id, latest_filename="latest_production_health.json")


def build_operational_health_report(
    settings: Settings,
    store: Store,
    reports_dir: Path,
    run_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    job_runtime = _job_runtime(store)
    report_health, report_alerts = _report_health(settings, settings.data_dir, now)
    job_alerts = _job_alerts(job_runtime)
    alerts = [*job_alerts, *report_alerts]
    responses = _build_operational_responses(alerts)
    severity_counts = {
        "critical": sum(1 for item in alerts if item["severity"] == "critical"),
        "warning": sum(1 for item in alerts if item["severity"] == "warning"),
        "info": sum(1 for item in alerts if item["severity"] == "info"),
    }
    report = {
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "overall_status": "critical"
            if severity_counts["critical"] > 0
            else "warning"
            if severity_counts["warning"] > 0
            else "ok",
            "alerts": len(alerts),
            "severity_counts": severity_counts,
            "responses": len(responses),
        },
        "job_runtime": job_runtime,
        "report_health": report_health,
        "alerts": alerts,
        "responses": responses,
    }
    return write_json_report(report, reports_dir, "operational_health", run_id, latest_filename="latest_operational_health.json")
