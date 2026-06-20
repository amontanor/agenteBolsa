"""Estado del sistema agenteBolsa (importable por CLI y por el dashboard).

`build_status()` devuelve, en solo lectura, el estado de cada componente que
deberia estar levantado (scheduler, ciclo de mercado, watchdog, laboratorio,
LLM, panel web, frescura de datos, BD) con OK / WARN / DOWN y un veredicto
global. No toca nada y no lanza excepciones hacia el caller.
"""
from __future__ import annotations

import json
import logging
import socket
import sqlite3
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from agente_bolsa._utils import log_swallow, parse_iso, sqlite_connect_ro

LOGGER = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "data" / "state" / "agente_bolsa.sqlite3"
REPORTS = ROOT / "data" / "reports"

OK, WARN, DOWN, NA = "OK", "WARN", "DOWN", "--"


def _llm_expected_detail() -> str:
    try:
        from agente_bolsa.config import Settings
        from agente_bolsa.llm_router import primary_llm_endpoint

        settings = Settings()
        endpoint = primary_llm_endpoint(settings)
        selector = str(getattr(settings, "llm_model_selector", "custom") or "custom")
        return f"{selector}/{endpoint.model}/fallback respondiendo"
    except Exception:
        return "LLM primario/fallback respondiendo"


def _llm_component_status(*, degraded: bool | None, severity: str | None, decision_age_min: float | None) -> tuple[str, str]:
    if degraded and str(severity or "").lower() == "critical":
        return DOWN, "DEGRADADO (fallback dominante y sin actividad LLM)"
    if degraded:
        return WARN, "sin actividad LLM de decision reciente"
    if decision_age_min is None:
        return WARN, "sin llamadas de decision"
    if decision_age_min <= 1440:
        return OK, f"ultima decision hace {decision_age_min / 60:.1f} h"
    return WARN, f"ultima decision hace {decision_age_min / 60:.0f} h"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _age_min(ts):
    d = parse_iso(ts)
    return None if not d else (_now() - d).total_seconds() / 60.0


def _waiting_after_scheduler_restart(
    *,
    job_age_min: float | None,
    scheduler_age_min: float | None,
    cadence_min: float,
    grace_min: float = 2.0,
) -> bool:
    if scheduler_age_min is None or scheduler_age_min > cadence_min + grace_min:
        return False
    return job_age_min is None or job_age_min > cadence_min + grace_min


def _global_verdict(components: list[dict[str, Any]]) -> str:
    critical = [c["state"] for c in components if c["name"] in ("Scheduler", "Ciclo de mercado (15m)", "LLM de decision")]
    if DOWN in critical:
        return DOWN
    if any(c["state"] in {WARN, DOWN} for c in components):
        return WARN
    return OK


def _market_open(now) -> bool:
    if now.weekday() >= 5:
        return False
    mins = now.hour * 60 + now.minute
    return 13 * 60 + 30 <= mins <= 20 * 60


def _job_status(con):
    out = {}
    try:
        for k, v in con.execute("SELECT key,value_json FROM runtime_state WHERE key LIKE 'scheduler_job_status:%'"):
            try:
                out[k.split(":", 1)[1]] = json.loads(v)
            except Exception as exc:
                log_swallow(LOGGER, "decodificar estado de job del scheduler", exc)
    except sqlite3.OperationalError:
        pass
    return out


def _last_llm(con, sources):
    ph = ",".join("?" for _ in sources)
    try:
        r = con.execute(f"SELECT MAX(created_at) FROM llm_usage WHERE source IN ({ph})", sources).fetchone()
        return r[0] if r else None
    except sqlite3.OperationalError:
        return None


def _port_open(host, port, timeout=1.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def build_status(db_path: Path | None = None, reports_dir: Path | None = None) -> dict[str, Any]:
    db = Path(db_path) if db_path else DB
    reports = Path(reports_dir) if reports_dir else REPORTS
    now = _now()
    market_open = _market_open(now)
    comps: list[dict[str, Any]] = []

    if not db.exists():
        return {"as_of": now.isoformat(), "market_open": market_open,
                "components": [{"name": "Base de datos", "state": DOWN, "detail": f"no existe {db}", "expected": ""}],
                "verdict": DOWN}
    try:
        con = sqlite_connect_ro(db, timeout=5)
        jobs = _job_status(con)
    except sqlite3.Error as exc:
        return {"as_of": now.isoformat(), "market_open": market_open,
                "components": [{"name": "Base de datos", "state": WARN, "detail": f"lectura ocupada: {exc}", "expected": "reintentar"}],
                "verdict": WARN}

    hb = _age_min((jobs.get("portfolio_watch") or {}).get("finished_at"))
    sched = ((DOWN, "sin registro") if hb is None else
             (OK, f"vivo (latido hace {hb:.1f} min)") if hb <= 3 else
             (WARN, f"sin latido hace {hb:.1f} min") if hb <= 10 else
             (DOWN, f"parado hace {hb:.0f} min"))
    comps.append({"name": "Scheduler", "state": sched[0], "detail": sched[1], "expected": "tarea AgenteBolsaScheduler viva"})

    mc = jobs.get("market_cycle") or {}
    mc_age = _age_min(mc.get("finished_at"))
    st = ((NA, "mercado cerrado") if not market_open else
          (WARN, f"scheduler reiniciado hace {hb:.1f} min; esperando primer ciclo")
          if _waiting_after_scheduler_restart(job_age_min=mc_age, scheduler_age_min=hb, cadence_min=15.0) else
          (DOWN, "sin ciclos") if mc_age is None else
          (OK, f"hace {mc_age:.1f} min ({mc.get('status')})") if mc_age <= 20 else
          (WARN, f"hace {mc_age:.0f} min") if mc_age <= 35 else
          (DOWN, f"sin ciclos hace {mc_age:.0f} min con mercado abierto"))
    comps.append({"name": "Ciclo de mercado (15m)", "state": st[0], "detail": st[1], "expected": "cada 15 min con NYSE abierto"})

    a = _age_min((jobs.get("agents_healthcheck") or {}).get("finished_at"))
    st = ((WARN, f"scheduler reiniciado hace {hb:.1f} min; esperando healthcheck")
          if _waiting_after_scheduler_restart(job_age_min=a, scheduler_age_min=hb, cadence_min=30.0) else
          (WARN, "sin ejecuciones") if a is None else (OK, f"hace {a:.0f} min") if a <= 40 else
          (WARN, f"hace {a:.0f} min") if a <= 90 else (DOWN, f"hace {a:.0f} min"))
    comps.append({"name": "Watchdog agentes (30m)", "state": st[0], "detail": st[1], "expected": "cada 30 min"})

    ci = _age_min((jobs.get("continuous_improvement") or {}).get("finished_at"))
    st = ((WARN, "sin ejecuciones") if ci is None else (OK, f"hace {ci:.1f} min") if ci <= 15 else
          (WARN, f"hace {ci:.0f} min") if ci <= 60 else (DOWN, f"hace {ci:.0f} min"))
    comps.append({"name": "Laboratorio mejora continua", "state": st[0], "detail": st[1], "expected": "runtime residente"})

    dec = _age_min(_last_llm(con, ("trade_decision",)))
    degraded = None
    degraded_severity = None
    ahc = reports / "latest_agents_healthcheck.json"
    if ahc.exists():
        try:
            watchdog = json.loads(ahc.read_text(encoding="utf-8")).get("watchdog") or {}
            degraded = watchdog.get("degraded")
            degraded_severity = watchdog.get("severity")
        except Exception as exc:
            log_swallow(LOGGER, "leer estado del watchdog LLM", exc)
    st = _llm_component_status(degraded=degraded, severity=degraded_severity, decision_age_min=dec)
    comps.append({"name": "LLM de decision", "state": st[0], "detail": st[1], "expected": _llm_expected_detail()})

    web = _port_open("127.0.0.1", 8501)
    comps.append({"name": "Panel web (8501)", "state": OK if web else WARN,
                  "detail": "responde" if web else "no responde", "expected": "tarea AgenteBolsaWeb"})

    reps = sorted(reports.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True) if reports.exists() else []
    if reps:
        fr = (_now().timestamp() - reps[0].stat().st_mtime) / 60.0
        st = OK if fr <= 60 else (WARN if fr <= 1440 else DOWN)
        det = f"ultimo reporte hace {fr:.0f} min ({reps[0].name})"
    else:
        st, det = WARN, "sin reportes"
    comps.append({"name": "Frescura de datos", "state": st, "detail": det, "expected": "reportes recientes"})

    gb = db.stat().st_size / 1e9
    st = OK if gb < 3 else (WARN if gb < 8 else DOWN)
    comps.append({"name": "Base de datos", "state": st,
                  "detail": f"{gb:.1f} GB" + ("  (considerar VACUUM)" if gb >= 3 else ""), "expected": "< 3 GB"})
    con.close()

    return {"as_of": now.isoformat(), "market_open": market_open, "components": comps, "verdict": _global_verdict(comps)}


def color(state: str) -> str:
    return {OK: "#1a7f37", WARN: "#9a6700", DOWN: "#cf222e", NA: "#57606a"}.get(state, "#57606a")


def _to_html_legacy(status: dict) -> str:
    rows = "".join(
        "<tr><td>" + escape(c["name"]) + "</td><td style='color:" + color(c["state"]) +
        ";font-weight:700'>" + c["state"] + "</td><td>" + escape(c.get("detail", "")) +
        "</td><td style='color:#57606a'>" + escape(c.get("expected", "")) + "</td></tr>"
        for c in status["components"]
    )
    v = status["verdict"]
    mkt = "ABIERTO" if status.get("market_open") else "cerrado"
    return (
        "<div style=\"font-family:system-ui,Segoe UI,Arial,sans-serif\">"
        "<div style='margin-bottom:8px'>Veredicto global: "
        "<span style='padding:4px 12px;border-radius:8px;color:#fff;font-weight:700;background:" + color(v) + "'>" + v + "</span>"
        " <span style='color:#57606a;font-size:12px'>· " + escape(status['as_of'][:19]) + " UTC · Mercado " + mkt + "</span></div>"
        "<table style='border-collapse:collapse;width:100%;font-size:14px'>"
        "<thead><tr><th style='text-align:left;color:#57606a'>Componente</th><th style='text-align:left;color:#57606a'>Estado</th>"
        "<th style='text-align:left;color:#57606a'>Detalle</th><th style='text-align:left;color:#57606a'>Qué se espera</th></tr></thead>"
        "<tbody>" + rows + "</tbody></table></div>"
    )


def to_html(status: dict) -> str:
    rows = "".join(
        "<tr><td>" + escape(c["name"]) + "</td><td style='color:" + color(c["state"])
        + ";font-weight:700'>" + c["state"] + "</td><td>" + escape(c.get("detail", ""))
        + "</td><td style='color:#57606a'>" + escape(c.get("expected", "")) + "</td></tr>"
        for c in status["components"]
    )
    verdict = status["verdict"]
    market = "ABIERTO" if status.get("market_open") else "cerrado"
    return (
        "<div style=\"font-family:system-ui,Segoe UI,Arial,sans-serif\">"
        "<div style='margin-bottom:8px'>Veredicto global: "
        "<span style='padding:4px 12px;border-radius:8px;color:#fff;font-weight:700;background:"
        + color(verdict) + "'>" + verdict + "</span>"
        " <span style='color:#57606a;font-size:12px'>- " + escape(status["as_of"][:19])
        + " UTC - Mercado " + market + "</span></div>"
        "<table style='border-collapse:collapse;width:100%;font-size:14px'>"
        "<thead><tr><th style='text-align:left;color:#57606a'>Componente</th>"
        "<th style='text-align:left;color:#57606a'>Estado</th>"
        "<th style='text-align:left;color:#57606a'>Detalle</th>"
        "<th style='text-align:left;color:#57606a'>Que se espera</th></tr></thead>"
        "<tbody>" + rows + "</tbody></table></div>"
    )
