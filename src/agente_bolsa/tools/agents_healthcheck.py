"""Vigilancia de salud del grupo de agentes (resiliencia ante LLM caido).

Aborda T1b/T11: combina el watchdog de LLM degradado con el ranking determinista
de oportunidades del universo amplio. Pensado para llamarse desde un job del
scheduler. Esta deliberadamente en su propio modulo para mantener `scheduler.py`
con el minimo de cambios. Nunca lanza excepciones hacia el caller.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from agente_bolsa._utils import log_swallow

LOGGER = logging.getLogger(__name__)


def run_agents_healthcheck(
    settings: Any,
    store: Any,
    reporter: Any = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Evalua el estado del grupo de agentes y publica las mejores oportunidades.

    - Detecta modo degradado (sin LLM de decision) y, si lo hay, emite un evento
      `llm_degraded_alert` por el reporter (si se pasa uno).
    - Deja en data/reports `latest_agents_healthcheck.json` y
      `latest_opportunities.json` con el ranking del universo amplio.

    Devuelve un resumen. No propaga excepciones: la vigilancia nunca debe romper
    el ciclo del scheduler.
    """
    from .llm_degraded_watchdog import evaluate as _watchdog_evaluate
    from .opportunity_ranker import rank_opportunities, snapshot_from_technical_study

    now = datetime.now(timezone.utc)

    # --- Watchdog de LLM ---
    try:
        watchdog = _watchdog_evaluate(settings.database_path)
    except Exception as exc:  # noqa: BLE001 - degradar sin romper
        watchdog = {"degraded": None, "error": str(exc)}

    # --- Oportunidades (universo amplio si esta disponible) ---
    reports_dir = settings.data_dir / "reports"
    opportunities: dict[str, Any] = {"error": "sin fuente de oportunidades"}
    try:
        study_path = reports_dir / "latest_closed_market_technical_study.json"
        if study_path.exists():
            data = json.loads(study_path.read_text(encoding="utf-8"))
            opportunities = rank_opportunities(
                snapshot_from_technical_study(data), top_n=15
            )
            opportunities["source"] = study_path.name
    except Exception as exc:  # noqa: BLE001
        opportunities = {"error": str(exc)}

    # --- Persistir reportes ---
    try:
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / "latest_agents_healthcheck.json").write_text(
            json.dumps(
                {"as_of": now.isoformat(), "watchdog": watchdog, "opportunities": opportunities},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (reports_dir / "latest_opportunities.json").write_text(
            json.dumps(opportunities, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001 - persistir nunca debe romper la vigilancia
        log_swallow(LOGGER, "persistir informe agents_healthcheck", exc)

    # --- Alerta visible si el grupo opera sin LLM ---
    if reporter is not None and isinstance(watchdog, dict) and watchdog.get("degraded"):
        try:
            critical = str(watchdog.get("severity") or "").lower() == "critical"
            reporter.emit(
                "orchestrator",
                "llm_degraded_alert",
                run_id or "ahc",
                (
                    "Grupo de agentes degradado: fallback dominante y sin actividad LLM."
                    if critical
                    else "Sin actividad LLM de decision reciente; revisar si persiste con mercado abierto."
                ),
                watchdog,
            )
        except Exception as exc:  # noqa: BLE001
            log_swallow(LOGGER, "emitir alerta visible de degradacion LLM", exc)

    opp_count = len(opportunities.get("opportunities", [])) if isinstance(opportunities, dict) else 0
    return {
        "degraded": watchdog.get("degraded") if isinstance(watchdog, dict) else None,
        "watchdog": watchdog,
        "opportunities_count": opp_count,
    }
