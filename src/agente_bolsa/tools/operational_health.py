"""Unified operational health report for jobs, data and setup degradation."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.logging_utils import log_system_event
from agente_bolsa.market_calendar import MarketCalendar
from agente_bolsa.storage import Store

from .adaptive_tuning import adaptive_governance_status
from .llm_decision_quality import build_llm_decision_quality, write_llm_decision_quality_report
from .market_cycle_timing import summarize_market_cycle_timings
from .reporting import write_json_report
from .time_stop_policy import shadow_time_stop_digest_summary

JOB_NAMES = [
    "portfolio_watch",
    "market_cycle",
    "closed_market_technical_study",
    "daily_study",
    "post_market_review",
    "broker_reconciliation",
    "operational_health_refresh",
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
    "stale_required_report",
}
KILL_SWITCH_MAX_REPORT_AGE_SECONDS = 6 * 60 * 60
DATA_PIPELINE_MAX_STALE_SECONDS = 30 * 60
DATA_PIPELINE_REPORT_PATTERNS = (
    "market_snapshot_*.json",
    "market_state_*.json",
    "breakout_scan_*.json",
    "closed_market_technical_study_*.json",
)
MARKET_DATA_QUALITY_TTL_SECONDS = 26 * 60 * 60


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


def _kernel_integrity_settings(data_dir: Path) -> Any:
    class _KernelIntegritySettings:
        def __init__(self, root: Path) -> None:
            self.state_dir = root / "state"

    return _KernelIntegritySettings(Path(data_dir))


def _is_kernel_integrity_override(override: dict[str, Any]) -> bool:
    kind = str(override.get("kind") or "").strip().lower()
    reason = str(override.get("reason") or "").strip().lower()
    return kind == "kernel_integrity_violation" or reason.startswith("kernel_integrity_violation")


def clear_kernel_integrity_override_if_recovered(
    data_dir: Path,
    *,
    settings: Settings | Any | None = None,
    source: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    override = load_persistent_kill_switch(data_dir)
    if not override or not _is_kernel_integrity_override(override):
        return {"cleared": False, "reason": "override_not_kernel_integrity"}

    from agente_bolsa.kernel import kernel_integrity

    integrity_settings = settings if settings is not None else _kernel_integrity_settings(data_dir)
    integrity = kernel_integrity(integrity_settings)
    if not integrity.get("ok"):
        return {
            "cleared": False,
            "reason": "kernel_still_failing",
            "integrity": integrity,
            "override": override,
        }

    cleared = clear_persistent_kill_switch(data_dir)
    event_payload = {
        "source": source,
        "activated_at": override.get("activated_at"),
        "kind": override.get("kind"),
        "reason": override.get("reason"),
        "verified_at": (now or datetime.now(timezone.utc)).isoformat(),
    }
    log_system_event((Path(data_dir) / "logs"), "kernel_integrity_override_cleared", event_payload)
    return {
        "cleared": cleared,
        "reason": "kernel_recovered",
        "integrity": integrity,
        "override": override,
        "event_payload": event_payload,
    }


def load_operational_block_context(
    data_dir: Path,
    *,
    settings: Settings | Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    override = load_persistent_kill_switch(data_dir)
    if override:
        if _is_kernel_integrity_override(override):
            recovery = clear_kernel_integrity_override_if_recovered(
                data_dir,
                settings=settings,
                source="load_operational_block_context",
                now=now,
            )
            if recovery.get("cleared"):
                return {
                    "available": True,
                    "as_of": recovery["event_payload"].get("verified_at"),
                    "kill_switch_active": False,
                    "block_new_buys": False,
                    "block_buy_execution": False,
                    "blocking_alerts": [],
                    "reasons": ["kernel_integrity_override_expired"],
                }
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


def _report_health(settings: Settings, data_dir: Path, store: Store, now: datetime | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from .performance_benchmark import benchmark_summary

    reports = {
        "technical_study": _latest_report_payload(data_dir, "latest_closed_market_technical_study.json"),
        "breakout_scan": _latest_report_payload(data_dir, "latest_breakout_scan.json"),
        "daily_learning_digest": _latest_report_payload(data_dir, "latest_daily_learning_digest.json"),
        "post_market_learning": _latest_report_payload(data_dir, "latest_post_market_learning.json"),
        "signal_learning": _latest_report_payload(data_dir, "latest_signal_learning.json"),
        "gate_effectiveness_quality": _latest_report_payload(data_dir, "latest_gate_effectiveness_quality.json"),
    }
    alerts: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    data_pipeline, data_pipeline_alerts = _data_pipeline_heartbeat(settings, data_dir, now)
    summary["data_pipeline"] = data_pipeline
    alerts.extend(data_pipeline_alerts)
    gate_runtime = store.get_runtime_value("gate_effectiveness_quality_runtime") or {}
    gate_report = reports["gate_effectiveness_quality"] or {}
    gate_status = str(gate_runtime.get("status") or gate_report.get("status") or "collecting")
    summary["gate_effectiveness_quality"] = {
        "status": gate_status, "runtime": gate_runtime, "report_session": gate_report.get("report_session"),
        "freshness": gate_report.get("freshness") or {"status": "unavailable"},
        "degraded_observability": gate_status == "failed",
    }
    if gate_status == "failed":
        alerts.append({"severity": "warning", "kind": "degraded_observability", "scope": "gate_effectiveness_quality",
                       "detail": "El informe derivado de gates fallo; no afecta trading ni gates."})

    try:
        benchmark_conflicts = store.get_runtime_value("performance_benchmark_conflicts") or {}
        summary["performance_benchmark"] = benchmark_summary(
            store.performance_daily(limit=0),
            conflict_count=benchmark_conflicts.get("count"),
            now=now,
        )
    except Exception as exc:  # noqa: BLE001 - observabilidad fail-open.
        summary["performance_benchmark"] = {
            "status": "unavailable",
            "reason": type(exc).__name__,
            "legacy_rows": None,
        }

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
    execution_attribution = post_market.get("execution_attribution") or {}
    candidate_attribution = post_market.get("candidate_attribution") or {}
    attribution_status = post_market.get("post_market_attribution_status") or (
        "healthy"
        if execution_attribution and not execution_attribution.get("llm_attribution_conflicts")
        else "degraded_attribution"
        if execution_attribution
        else "collecting"
    )
    summary["post_market_learning"] = {
        "available": bool(post_market),
        "session_date": post_market.get("session_date"),
        "pipeline_steps": pipeline_steps,
        "attribution": {
            "status": attribution_status,
            "canonical_trade_evaluations": execution_attribution.get("canonical_trade_evaluations"),
            "activity_fragments": execution_attribution.get("activity_fragments"),
            "duplicate_fragment_count": execution_attribution.get("duplicate_fragment_count"),
            "exit_origin_coverage": execution_attribution.get("exit_origin_coverage"),
            "automatic_exit_count": execution_attribution.get("automatic_exit_count"),
            "manual_exit_count": execution_attribution.get("manual_exit_count"),
            "unknown_exit_origin_count": execution_attribution.get("unknown_exit_origin_count"),
            "llm_attribution_conflicts": execution_attribution.get("llm_attribution_conflicts"),
            "recommendation_coverage": {
                "raw": candidate_attribution.get("recommendations_raw"),
                "unique": candidate_attribution.get("recommendations_unique"),
                "non_executed": candidate_attribution.get("non_executed_candidates"),
            },
            "legacy_unverified_count": candidate_attribution.get("legacy_unverified_count"),
            "immature_outcome_count": post_market.get("immature_outcome_count"),
        },
    }
    if attribution_status == "degraded_attribution":
        alerts.append(
            {
                "severity": "warning",
                "kind": "post_market_attribution_degraded",
                "scope": "post_market_attribution",
                "detail": "La atribucion post-market contiene conflictos o identidad incompleta; no afecta trading.",
            }
        )
    calendar = MarketCalendar(settings.market_calendar, settings.local_timezone)
    market = calendar.status(now)
    now_utc = _parse_datetime(market.now_utc) or datetime.now(timezone.utc)
    market_close = _parse_datetime(market.market_close)
    now_market = _parse_datetime(market.now_market)
    derived_session_date = (
        str(market.session_date or "")
        or (now_market.date().isoformat() if now_market and now_market.weekday() < 5 else None)
    )
    after_regular_close = bool(
        now_market and now_market.weekday() < 5 and (now_market.hour, now_market.minute) >= (16, 0)
    )
    post_market_required = bool(
        not market.is_open and ((market_close and now_utc > market_close) or after_regular_close)
    )
    summary["post_market_learning"]["required"] = post_market_required
    summary["post_market_learning"]["required_session_date"] = derived_session_date
    if post_market_required and not post_market:
        alerts.append(
            {
                "severity": "critical",
                "kind": "missing_report",
                "scope": "post_market_review",
                "detail": f"Falta latest_post_market_learning.json para la sesion {derived_session_date}.",
            }
        )
    elif post_market_required and derived_session_date and str(post_market.get("session_date") or "") != str(derived_session_date):
        alerts.append(
            {
                "severity": "critical",
                "kind": "stale_required_report",
                "scope": "post_market_review",
                "detail": (
                    f"Post-market stale: session_date={post_market.get('session_date')} "
                    f"pero se requiere {derived_session_date}."
                ),
            }
        )
    post_market_session_date = str(post_market.get("session_date") or "")
    timing_applies_to_current_session = bool(
        not derived_session_date
        or not post_market_session_date
        or post_market_session_date == str(derived_session_date)
        or post_market_required
    )
    if pipeline_steps and timing_applies_to_current_session:
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


def _ci_backlog_alerts(settings: Settings, store: Store) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    active_statuses = ("OPEN", "ANALYZING", "EXPERIMENTING", "VALIDATING", "WAITING_REVIEW", "READY_TO_APPLY")
    task_statuses = (
        "DISCOVERED",
        "PLANNED",
        "ASSIGNED",
        "RUNNING",
        "WAITING_DEPENDENCY",
        "VALIDATING",
        "WAITING_HUMAN_REVIEW",
    )
    with store.connect() as conn:
        active_rows = conn.execute(
            f"""
            SELECT status, initiative_key
            FROM continuous_improvement_initiatives
            WHERE status IN ({",".join("?" for _ in active_statuses)})
            """,
            active_statuses,
        ).fetchall()
        open_task_count = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM continuous_improvement_agent_tasks
            WHERE status IN ({",".join("?" for _ in task_statuses)})
            """,
            task_statuses,
        ).fetchone()["count"]
    generated_topic_count = sum(1 for row in active_rows if ":ci_prop_" in str(row["initiative_key"]))
    validating_count = sum(1 for row in active_rows if str(row["status"]) == "VALIDATING")
    max_open = max(1, int(getattr(settings, "ci_max_open_initiatives", 4)))
    summary = {
        "active_initiatives": len(active_rows),
        "validating_initiatives": validating_count,
        "generated_topic_initiatives": generated_topic_count,
        "open_task_count": int(open_task_count or 0),
        "max_open_initiatives": max_open,
    }
    alerts: list[dict[str, Any]] = []
    if generated_topic_count:
        alerts.append(
            {
                "severity": "warning",
                "kind": "ci_generated_topic_loop",
                "scope": "continuous_improvement",
                "detail": f"{generated_topic_count} iniciativa(s) activas usan claves generadas tipo ci_prop_*.",
            }
        )
    if len(active_rows) > max_open * 2:
        alerts.append(
            {
                "severity": "warning",
                "kind": "ci_backlog_over_wip_limit",
                "scope": "continuous_improvement",
                "detail": f"WIP CI={len(active_rows)} supera el limite operativo {max_open}.",
            }
        )
    if validating_count > max_open:
        alerts.append(
            {
                "severity": "warning",
                "kind": "ci_validation_backlog",
                "scope": "continuous_improvement",
                "detail": f"{validating_count} iniciativa(s) en VALIDATING; el laboratorio debe cerrar o aplicar.",
            }
        )
    return summary, alerts


def _market_data_quality_freshness(
    data_dir: Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    path = data_dir / "reports" / "latest_market_data_quality.json"
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload = _load_json(path) or {}
    report_at = _parse_datetime(payload.get("as_of")) if payload else None
    if report_at is None and path.exists():
        report_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    age_seconds = max(0.0, (reference - report_at).total_seconds()) if report_at else None
    return {
        "status": "fresh" if age_seconds is not None and age_seconds <= MARKET_DATA_QUALITY_TTL_SECONDS else "stale_or_missing",
        "path": str(path),
        "report_at": report_at.isoformat() if report_at else None,
        "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
        "max_age_seconds": MARKET_DATA_QUALITY_TTL_SECONDS,
        "is_fresh": age_seconds is not None and age_seconds <= MARKET_DATA_QUALITY_TTL_SECONDS,
    }


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:  # noqa: BLE001 - health must remain read-only and resilient.
            return False
    try:
        os.kill(pid, 0)
    except (OSError, SystemError):
        return False
    return True


def _scheduler_coherence(settings: Settings, heartbeat: dict[str, Any]) -> dict[str, Any]:
    path = settings.state_dir / "scheduler.lock"
    payload = _load_json(path) or {}
    if not payload and path.exists():
        try:
            payload = {"pid": int(path.read_text(encoding="utf-8").strip()), "kind": "legacy"}
        except (OSError, ValueError):
            payload = {}
    try:
        pid = int(payload.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    pid_alive = _pid_running(pid)
    lock_valid = bool(payload) and str(payload.get("kind") or "scheduler") in {"scheduler", "legacy"}
    raw_expected_token = payload.get("owner_process_token") or payload.get("token")
    expected_token = str(raw_expected_token).strip() if raw_expected_token is not None else None
    expected_token = expected_token or None
    actual_token = None
    if pid_alive:
        try:
            from agente_bolsa.scheduler import _process_start_token

            actual_token = _process_start_token(pid)
        except Exception:  # noqa: BLE001 - health must remain read-only.
            actual_token = None
    token_match = bool(expected_token and actual_token and expected_token == actual_token)
    if not path.exists():
        status = "missing_lock"
    elif not payload:
        status = "malformed_lock"
    elif not pid_alive:
        status = "stale_dead_owner"
    elif expected_token and actual_token and expected_token != actual_token:
        status = "pid_reused"
    elif expected_token and actual_token and expected_token == actual_token:
        status = "owner_alive"
    else:
        status = "owner_alive"
    heartbeat_fresh = bool(heartbeat.get("is_fresh"))
    coherent = lock_valid and pid_alive and heartbeat_fresh and status == "owner_alive"
    return {
        "status": "healthy_owned" if coherent else status,
        "lock_path": str(path),
        "lock_exists": path.exists(),
        "lock_kind": payload.get("kind"),
        "pid": pid or None,
        "pid_alive": pid_alive,
        "expected_token": expected_token,
        "actual_token": actual_token,
        "token_match": token_match,
        "heartbeat_fresh": heartbeat_fresh,
        "coherent": coherent,
    }


def _llm_fallback_ratio(store: Store, *, now: datetime | None = None) -> dict[str, Any]:
    decision_quality = build_llm_decision_quality(store, now=now)
    summary = decision_quality["summary"]
    if summary["known_decisions"]:
        return {
            "window_days": decision_quality["window"]["days"],
            "basis": decision_quality["basis"],
            "decisions": summary["known_decisions"],
            "unknown_decisions": summary["unknown_decisions"],
            "real_decisions": summary["real_decisions"],
            "fallback_decisions": summary["fallback_decisions"],
            "llm_failure_fallback_decisions": summary["llm_failure_fallback_decisions"],
            "deterministic_after_llm_ok_decisions": summary["deterministic_after_llm_ok_decisions"],
            "real_ratio": summary["real_ratio"],
            "fallback_ratio": summary["fallback_ratio"],
            "llm_failure_fallback_ratio": summary["llm_failure_fallback_ratio"],
            "fallback_reasons": decision_quality["by_fallback_reason"],
            "status": summary["status"],
        }
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = (reference - timedelta(days=7)).isoformat()
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT source, request_count, payload_json FROM llm_usage WHERE created_at >= ?",
            (cutoff,),
        ).fetchall()
    total = 0
    fallback = 0
    for row in rows:
        count = max(1, int(row["request_count"] or 0))
        total += count
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        marker = " ".join(
            str(value or "").lower()
            for value in (row["source"], payload.get("decision_origin"), payload.get("provider"))
        )
        if payload.get("fallback_used") is True or "fallback" in marker or "deterministic" in marker:
            fallback += count
    real = max(0, total - fallback)
    return {
        "window_days": 7,
        "basis": "llm_usage_fallback",
        "requests": total,
        "real_requests": real,
        "fallback_requests": fallback,
        "real_ratio": round(real / total, 4) if total else None,
        "fallback_ratio": round(fallback / total, 4) if total else None,
        "status": "available" if total else "unavailable",
    }


def _post_market_runtime_health(job_runtime: dict[str, Any], data_dir: Path) -> dict[str, Any]:
    post = job_runtime.get("post_market_review") or {}
    post_status = str(post.get("status") or "")
    post_start = _parse_datetime(post.get("started_at"))
    post_end = _parse_datetime(post.get("finished_at"))
    overlaps = []
    if post_status == "completed" and post_start and post_end:
        for name, state in job_runtime.items():
            if name == "post_market_review" or not isinstance(state, dict):
                continue
            start = _parse_datetime(state.get("started_at"))
            end = _parse_datetime(state.get("finished_at"))
            if start and end and max(post_start, start) < min(post_end, end):
                overlaps.append(name)
    measurement = _latest_report_payload(data_dir, "latest_post_market_measurement_pipeline.json") or {}
    post_market_report = _latest_report_payload(data_dir, "latest_post_market_learning.json") or {}
    reported_steps = post_market_report.get("pipeline_steps") or {}
    reported_duration = sum(
        float(value) for value in reported_steps.values() if isinstance(value, (int, float))
    )
    return {
        "status": "available" if post_status == "completed" and post_start and post_end else "unavailable",
        "latest_scheduler_status": post_status or "missing",
        "duration_seconds": post.get("duration_seconds") if post_status == "completed" else None,
        "reported_pipeline_duration_seconds": round(reported_duration, 3) if reported_steps else None,
        "started_at": post.get("started_at"),
        "finished_at": post.get("finished_at"),
        "overlap_count": len(overlaps),
        "overlap_status": "measured" if post_status == "completed" and post_start and post_end else "unavailable",
        "overlapping_jobs": sorted(overlaps),
        "measurement_timings": measurement.get("timings") or {},
        "measurement_session_date": measurement.get("session_date"),
    }


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
        elif kind in {"ci_generated_topic_loop", "ci_backlog_over_wip_limit", "ci_validation_backlog"}:
            response = {
                "response_id": _response_id(kind, scope),
                "status": "guarded_active",
                "action": "run_ci_lifecycle_and_reduce_wip",
                "scope": scope,
                "mode": "governance",
                "detail": "Ejecutar lifecycle y no planificar nuevas iniciativas hasta reducir WIP.",
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
    market_data_quality = _market_data_quality_freshness(settings.data_dir)
    scheduler_coherence = _scheduler_coherence(settings, scheduler_freshness)
    llm_decision_quality = write_llm_decision_quality_report(store, reports_dir, run_id)
    llm_quality = _llm_fallback_ratio(store)
    post_market_runtime = _post_market_runtime_health(scheduler_runtime, settings.data_dir)
    market_cycle_timing = summarize_market_cycle_timings(reports_dir, limit=20)

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
    if not market_data_quality["is_fresh"]:
        alerts.append(
            {
                "severity": "warning",
                "kind": "market_data_quality_stale",
                "scope": "market_data_quality",
                "detail": (
                    "latest_market_data_quality.json ausente o con mas de 26 horas "
                    f"(age={market_data_quality.get('age_seconds')})."
                ),
            }
        )
    if not scheduler_coherence["coherent"]:
        alerts.append(
            {
                "severity": "critical" if scheduler_coherence["lock_exists"] else "warning",
                "kind": "scheduler_pid_lock_heartbeat_incoherent",
                "scope": "scheduler",
                "detail": (
                    f"lock={scheduler_coherence['lock_exists']} pid_alive={scheduler_coherence['pid_alive']} "
                    f"heartbeat_fresh={scheduler_coherence['heartbeat_fresh']}."
                ),
            }
        )
    if isinstance(llm_quality.get("fallback_ratio"), (int, float)) and llm_quality["fallback_ratio"] > 0.50:
        alerts.append(
            {
                "severity": "warning",
                "kind": "llm_fallback_ratio_high",
                "scope": "llm",
                "detail": f"Fallback LLM 7d={llm_quality['fallback_ratio']:.1%} (>50%).",
            }
        )
    if post_market_runtime["overlap_count"]:
        alerts.append(
            {
                "severity": "warning",
                "kind": "post_market_pipeline_overlap",
                "scope": "post_market_review",
                "detail": "Solapamiento con: " + ", ".join(post_market_runtime["overlapping_jobs"]),
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
            "market_data_quality": market_data_quality,
            "scheduler_coherence": scheduler_coherence,
            "llm_quality": llm_quality,
            "llm_decision_quality": {
                "path": llm_decision_quality.get("path"),
                "latest_path": llm_decision_quality.get("latest_path"),
                "summary": llm_decision_quality.get("summary"),
            },
            "post_market_runtime": post_market_runtime,
            "market_cycle_timing": market_cycle_timing,
        },
        "operational_health": operational_report,
        "alerts": alerts,
        "responses": responses,
        "scheduler_heartbeat": scheduler_freshness,
        "scheduler_coherence": scheduler_coherence,
        "market_data_quality": market_data_quality,
        "llm_quality": llm_quality,
        "llm_decision_quality": {
            "path": llm_decision_quality.get("path"),
            "latest_path": llm_decision_quality.get("latest_path"),
            "summary": llm_decision_quality.get("summary"),
        },
        "post_market_runtime": post_market_runtime,
        "market_cycle_timing": market_cycle_timing,
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
    report_health, report_alerts = _report_health(settings, settings.data_dir, store, now)
    adaptive_governance = adaptive_governance_status(settings)
    report_health["adaptive_config_governance"] = adaptive_governance
    try:
        report_health["time_stop_shadow"] = shadow_time_stop_digest_summary(store)
    except Exception:  # noqa: BLE001 - shadow health is observability only.
        report_health["time_stop_shadow"] = {
            "status": "unavailable",
            "shadow_only": True,
            "evaluations": None,
        }
    try:
        from .learning_penalty_cycle_shadow import learning_penalty_shadow_digest

        report_health["learning_penalty_shadow"] = learning_penalty_shadow_digest(store)
    except Exception:  # noqa: BLE001 - shadow health is observability only.
        report_health["learning_penalty_shadow"] = {
            "status": "degraded_observability",
            "shadow_only": True,
            "observations": None,
        }
    try:
        from .canonical_operation_telemetry import canonical_operation_telemetry_digest

        report_health["canonical_operation_telemetry"] = canonical_operation_telemetry_digest(store)
    except Exception:  # noqa: BLE001 - canonical telemetry is observability only.
        report_health["canonical_operation_telemetry"] = {
            "status": "degraded_observability",
            "denominators": None,
            "execution": None,
            "exits": None,
            "freshness": None,
        }
    try:
        from .data_quality_decision_shadow import data_quality_decision_shadow_digest

        # Read-only consumer: it never evaluates a gate and never derives
        # missing denominators from symbols or reports generated later.
        report_health["data_quality_decision_shadow"] = data_quality_decision_shadow_digest(store)
    except Exception:  # noqa: BLE001 - a telemetry failure is fail-open.
        report_health["data_quality_decision_shadow"] = {
            "status": "unavailable",
            "shadow_only": True,
            "denominators": None,
            "warnings": ["read_failed"],
        }
    if adaptive_governance["status"] == "critical":
        report_alerts.append(
            {
                "severity": "critical",
                "kind": "adaptive_config_unauthorized_override",
                "scope": "adaptive_config",
                "detail": "Existe al menos un override adaptativo no autorizado que relaja una protección.",
            }
        )
    elif adaptive_governance["status"] == "degraded_governance":
        report_alerts.append(
            {
                "severity": "warning",
                "kind": "adaptive_config_governance_degraded",
                "scope": "adaptive_config",
                "detail": "Overrides adaptativos preexistentes sin autorización vigente; no se han modificado.",
            }
        )
    ci_backlog, ci_alerts = _ci_backlog_alerts(settings, store)
    report_health["continuous_improvement_backlog"] = ci_backlog
    job_alerts = _job_alerts(job_runtime)
    alerts = [*job_alerts, *report_alerts, *ci_alerts]
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
