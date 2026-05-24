"""Unified operational health report for jobs, data and setup degradation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agente_bolsa.config import Settings
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
    "job_failed",
    "missing_report",
}
KILL_SWITCH_MAX_REPORT_AGE_SECONDS = 6 * 60 * 60


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


def load_operational_block_context(data_dir: Path) -> dict[str, Any]:
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


def _report_health(data_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    reports = {
        "technical_study": _latest_report_payload(data_dir, "latest_closed_market_technical_study.json"),
        "breakout_scan": _latest_report_payload(data_dir, "latest_breakout_scan.json"),
        "daily_learning_digest": _latest_report_payload(data_dir, "latest_daily_learning_digest.json"),
        "post_market_learning": _latest_report_payload(data_dir, "latest_post_market_learning.json"),
        "signal_learning": _latest_report_payload(data_dir, "latest_signal_learning.json"),
    }
    alerts: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}

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


def build_operational_health_report(
    settings: Settings,
    store: Store,
    reports_dir: Path,
    run_id: str,
) -> dict[str, Any]:
    job_runtime = _job_runtime(store)
    report_health, report_alerts = _report_health(settings.data_dir)
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
