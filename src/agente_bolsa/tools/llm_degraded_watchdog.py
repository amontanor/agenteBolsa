"""Watchdog de modo degradado del LLM (grupo de agentes "sin cabeza").

Motivacion (16-jun-2026): el sistema dejo de operar ~10 dias sin avisar porque el
LLM de decision y el de sentimiento estaban caidos y el sistema degrado en
silencio a fallback determinista. Este watchdog detecta esa situacion a partir de
la actividad real registrada en la BD (`llm_usage` y `trade_recommendations`) y
produce una alerta accionable.

Solo lectura, sin dependencias pesadas (stdlib). Pensado para llamarse desde un
job o un script y para que el dashboard muestre el estado del grupo de agentes.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agente_bolsa._utils import parse_iso, sqlite_connect_ro

# Fuentes de LLM consideradas criticas para operar bien.
DECISION_SOURCES = ("trade_decision",)
SENTIMENT_SOURCES = ("news_sentiment",)


def _last_usage_at(con: sqlite3.Connection, sources: tuple[str, ...]) -> str | None:
    placeholders = ",".join("?" for _ in sources)
    try:
        row = con.execute(
            f"SELECT MAX(created_at) FROM llm_usage WHERE source IN ({placeholders})",
            sources,
        ).fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None


def _recent_fallback_ratio(con: sqlite3.Connection, since_iso: str) -> dict[str, Any]:
    """Proporcion de recomendaciones recientes que vienen del fallback determinista."""
    try:
        rows = con.execute(
            "SELECT payload_json FROM trade_recommendations WHERE created_at >= ?",
            (since_iso,),
        ).fetchall()
    except sqlite3.OperationalError:
        return {"total": 0, "fallback": 0, "ratio": 0.0}
    total = 0
    fallback = 0
    for r in rows:
        total += 1
        payload = r[0] or ""
        if "deterministic_fallback" in payload or "Fallback determinista" in payload:
            fallback += 1
    ratio = round(fallback / total, 4) if total else 0.0
    return {"total": total, "fallback": fallback, "ratio": ratio}


def _role_snapshot(name: str, hours_since: float | None, limit_hours: float) -> dict[str, Any]:
    down = hours_since is None or hours_since > limit_hours
    return {
        "name": name,
        "ok": not down,
        "hours_since_real_response": round(hours_since, 1) if hours_since is not None else None,
        "max_hours_without_response": limit_hours,
    }


def format_status_line(report: dict[str, Any]) -> str:
    roles = report.get("roles") or {}
    decision = roles.get("decision") or {}
    sentiment = roles.get("sentiment") or {}

    def _status(role: dict[str, Any]) -> str:
        label = "OK" if role.get("ok") else "CAIDO"
        hours = role.get("hours_since_real_response")
        hours_text = "sin dato" if hours is None else f"{hours:.1f}h"
        return f"{label} ({hours_text} sin respuesta real)"

    return (
        "LLM: "
        f"decision={_status(decision)} "
        f"sentiment={_status(sentiment)}"
    )


def evaluate(
    db_path: str | Path,
    *,
    now: datetime | None = None,
    max_hours_decision: float = 24.0,
    max_hours_sentiment: float = 48.0,
    recent_window_hours: float = 24.0,
) -> dict[str, Any]:
    """Evalua el estado del grupo de agentes respecto a la disponibilidad de LLM.

    Devuelve un dict con `degraded` (bool), severidad y detalle accionable.
    """
    now = now or datetime.now(timezone.utc)
    con = sqlite_connect_ro(db_path)
    try:
        last_decision = _last_usage_at(con, DECISION_SOURCES)
        last_sentiment = _last_usage_at(con, SENTIMENT_SOURCES)
        since_iso = (now.timestamp() - recent_window_hours * 3600)
        since_dt = datetime.fromtimestamp(since_iso, tz=timezone.utc).isoformat()
        fallback = _recent_fallback_ratio(con, since_dt)
    finally:
        con.close()

    dt_decision = parse_iso(last_decision)
    dt_sentiment = parse_iso(last_sentiment)

    hours_decision = (now - dt_decision).total_seconds() / 3600 if dt_decision else None
    hours_sentiment = (now - dt_sentiment).total_seconds() / 3600 if dt_sentiment else None

    decision_down = hours_decision is None or hours_decision > max_hours_decision
    sentiment_down = hours_sentiment is None or hours_sentiment > max_hours_sentiment
    heavy_fallback = fallback["total"] >= 3 and fallback["ratio"] >= 0.8

    degraded = decision_down or (heavy_fallback and sentiment_down)
    if decision_down and heavy_fallback:
        severity = "critical"
    elif degraded:
        severity = "warning"
    else:
        severity = "ok"

    reasons: list[str] = []
    if decision_down:
        if hours_decision is None:
            reasons.append("Sin ninguna llamada LLM de decision registrada.")
        else:
            reasons.append(f"Ultima llamada LLM de decision hace {hours_decision:.1f}h (> {max_hours_decision}h).")
    if sentiment_down:
        if hours_sentiment is None:
            reasons.append("Sin ninguna llamada LLM de sentimiento registrada.")
        else:
            reasons.append(f"Ultima llamada LLM de sentimiento hace {hours_sentiment:.1f}h (> {max_hours_sentiment}h).")
    if heavy_fallback:
        reasons.append(
            f"{fallback['fallback']}/{fallback['total']} recomendaciones recientes "
            f"({fallback['ratio'] * 100:.0f}%) vienen del fallback determinista."
        )

    roles = {
        "decision": _role_snapshot("decision", hours_decision, max_hours_decision),
        "sentiment": _role_snapshot("sentiment", hours_sentiment, max_hours_sentiment),
    }

    report = {
        "as_of": now.isoformat(),
        "degraded": degraded,
        "severity": severity,
        "last_decision_llm_at": last_decision,
        "hours_since_decision_llm": round(hours_decision, 1) if hours_decision is not None else None,
        "last_sentiment_llm_at": last_sentiment,
        "hours_since_sentiment_llm": round(hours_sentiment, 1) if hours_sentiment is not None else None,
        "roles": roles,
        "recent_recommendations": fallback,
        "reasons": reasons,
        "recommended_action": (
            "El fallback domina y no hay actividad LLM: validar proveedores con "
            "scripts/llm_health_check.py antes del siguiente ciclo."
            if severity == "critical"
            else "No hay actividad LLM reciente; comprobar salud si persiste durante mercado abierto."
            if degraded
            else "Sin accion: hay actividad LLM reciente."
        ),
    }
    report["status_line"] = format_status_line(report)
    return report
