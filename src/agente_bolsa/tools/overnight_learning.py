"""Overnight learning heartbeat with optional LLM reflection."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .reporting import write_json_report

if TYPE_CHECKING:  # pragma: no cover - typing only.
    from agente_bolsa.config import Settings
    from agente_bolsa.storage import Store


def _latest_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"available": False, "path": str(path)}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"available": False, "path": str(path), "error": str(exc)}
    return {
        "available": True,
        "path": str(path),
        "as_of": payload.get("as_of"),
        "summary": payload.get("summary") or {},
        "health": payload.get("health") or {},
    }


def _latest_llm_age_hours(store: Store) -> float | None:
    rows = store.latest_llm_usage(limit=1)
    if not rows:
        return None
    raw = str(rows[0].get("created_at") or "")
    try:
        created = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - created.astimezone(timezone.utc)).total_seconds() / 3600.0, 3)


def _build_snapshot(store: Store, settings: Settings) -> dict[str, Any]:
    reports_dir = settings.data_dir / "reports"
    latest_age = _latest_llm_age_hours(store)
    stale_threshold = float(getattr(settings, "overnight_learning_stale_llm_alert_hours", 24.0))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "overnight_learning_heartbeat",
        "market_safety": {
            "trading_allowed": False,
            "reason": "overnight heartbeat is research-only and never creates orders",
        },
        "llm": {
            "enabled": bool(getattr(settings, "overnight_learning_use_llm", True))
            and bool(getattr(settings, "improvement_llm_enabled", False)),
            "provider": settings.improvement_llm_provider,
            "model": settings.improvement_llm_orchestrator_model,
            "latest_usage_age_hours": latest_age,
            "stale_threshold_hours": stale_threshold,
            "stale": latest_age is None or latest_age > stale_threshold,
        },
        "reports": {
            "post_market_learning": _latest_report(reports_dir / "latest_post_market_learning.json"),
            "daily_learning": _latest_report(reports_dir / "latest_daily_learning_digest.json"),
            "operational_learning": _latest_report(reports_dir / "latest_operational_learning.json"),
            "research_evidence": _latest_report(reports_dir / "latest_research_evidence.json"),
            "continuous_improvement": _latest_report(reports_dir / "latest_continuous_improvement_report.json"),
        },
        "backlog": {
            "open_initiatives": len(
                [
                    item
                    for item in store.continuous_improvement_initiatives(limit=1000)
                    if item.get("status") not in {"CLOSED", "REJECTED", "COMPLETED"}
                ]
            ),
            "pending_tasks": len(
                [
                    item
                    for item in store.continuous_improvement_tasks(limit=1000)
                    if item.get("status") not in {"COMPLETED", "CANCELLED", "FAILED"}
                ]
            ),
            "ready_to_apply": len(store.continuous_improvement_proposals(status="READY_TO_APPLY", limit=1000)),
        },
        "learning": {
            "active_lessons": len(store.distilled_lessons(status="ACTIVE", limit=1000)),
            "hypothesis_lessons": len(store.distilled_lessons(status="HYPOTHESIS", limit=1000)),
            "shadow_rules": len(store.strategy_rules(status="shadow", limit=1000)),
            "open_promotion_windows": len(store.promotion_windows(status="OPEN", limit=1000)),
        },
    }


def _llm_messages(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    system = (
        "Eres el supervisor nocturno de aprendizaje de un sistema de trading paper. "
        "No puedes proponer ordenes ni cambios de riesgo. Devuelve SOLO un JSON valido "
        "con esta forma exacta: "
        '{"diagnosis":{"summary":"texto","confidence":"LOW|MEDIUM|HIGH","data_quality":"INSUFFICIENT|PARTIAL|GOOD"},'
        '"detected_issues":[],"proposals":[],"recommended_next_actions":["texto"]}. '
        "No uses scores numericos en confidence. No uses objetos en data_quality. "
        "Para este heartbeat deja detected_issues y proposals como arrays vacios si no puedes "
        "cumplir exactamente el schema. Incluye las observaciones accionables en recommended_next_actions."
    )
    user = {
        "task": "heartbeat nocturno de aprendizaje",
        "goal": "confirmar si el sistema esta aprendiendo y que falta revisar antes de la proxima sesion",
        "snapshot": snapshot,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=True, default=str)},
    ]


def build_overnight_learning_heartbeat(
    store: Store,
    settings: Settings,
    reports_dir: Path,
    run_id: str,
) -> dict[str, Any]:
    snapshot = _build_snapshot(store, settings)
    llm_result_payload: dict[str, Any] | None = None
    usage: dict[str, Any] = {"recorded": False}
    warnings: list[str] = []

    if snapshot["llm"]["enabled"]:
        try:
            from agente_bolsa.continuous_improvement.llm_client import ImprovementLLMClient
            from agente_bolsa.continuous_improvement.llm_usage_bridge import (
                record_improvement_llm_usage,
            )
            from agente_bolsa.continuous_improvement.schemas import llm_response_json_schema

            client = ImprovementLLMClient(settings)
            result = client.generate_json(
                _llm_messages(snapshot),
                llm_response_json_schema(),
                model=settings.improvement_llm_orchestrator_model,
                max_tokens=min(int(settings.improvement_llm_max_tokens), 1200),
            )
            usage = record_improvement_llm_usage(
                store,
                settings,
                source="overnight_learning_heartbeat",
                result=result,
                role="overnight_learning",
            )
            if usage.get("recorded"):
                snapshot["llm"]["latest_usage_age_hours"] = _latest_llm_age_hours(store)
                snapshot["llm"]["stale"] = False
            if not result.ok:
                warnings.append("overnight_llm_response_invalid")
            llm_result_payload = {
                "ok": result.ok,
                "llm_call_id": result.llm_call_id,
                "provider": result.provider,
                "model": result.model,
                "fallback_used": result.fallback_used,
                "error": result.error,
                "diagnosis": result.payload.diagnosis.model_dump() if result.payload else None,
                "recommended_next_actions": result.payload.recommended_next_actions if result.payload else [],
                "usage": usage,
            }
        except Exception as exc:  # noqa: BLE001 - heartbeat must never kill schedule.
            warnings.append(f"overnight_llm_failed:{type(exc).__name__}:{exc}")
    else:
        reason = "OVERNIGHT_LEARNING_USE_LLM=false" if not getattr(settings, "overnight_learning_use_llm", True) else "IMPROVEMENT_LLM_ENABLED=false"
        warnings.append(reason)

    health_status = "ok"
    if warnings:
        health_status = "degraded"
    if snapshot["llm"]["stale"]:
        health_status = "degraded"
        warnings.append("llm_usage_stale_or_missing")

    report = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "status": health_status,
        "snapshot": snapshot,
        "llm_result": llm_result_payload,
        "warnings": sorted(set(warnings)),
        "summary": {
            "llm_enabled": snapshot["llm"]["enabled"],
            "llm_usage_recorded": bool(usage.get("recorded")),
            "llm_latest_usage_age_hours": snapshot["llm"]["latest_usage_age_hours"],
            "open_initiatives": snapshot["backlog"]["open_initiatives"],
            "pending_tasks": snapshot["backlog"]["pending_tasks"],
            "active_lessons": snapshot["learning"]["active_lessons"],
            "shadow_rules": snapshot["learning"]["shadow_rules"],
        },
    }
    return write_json_report(
        report,
        reports_dir,
        "overnight_learning_heartbeat",
        run_id,
        latest_filename="latest_overnight_learning_heartbeat.json",
        manifest={"research_only": True},
    )


def should_run_overnight_for_session(store: Store, session_key: str, *, force: bool = False) -> bool:
    if force:
        return True
    return store.get_runtime_value("overnight_learning_heartbeat_last_session") != session_key


def mark_overnight_session_done(store: Store, session_key: str) -> None:
    store.set_runtime_value("overnight_learning_heartbeat_last_session", session_key)
