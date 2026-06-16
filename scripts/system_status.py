#!/usr/bin/env python3
"""Pantalla de estado del sistema agenteBolsa.

Responde de un vistazo a "¿esta todo lo que deberia estar levantado y sano?".
Lee el estado REAL (sin tocar nada): heartbeat del scheduler, estado de cada job,
frescura de datos, disponibilidad del LLM, panel web y tamano de la BD. Marca cada
componente OK / WARN / DOWN y da un veredicto global.

Solo lectura. Seguro con el sistema levantado.

Uso:
    python scripts/system_status.py
    python scripts/system_status.py --html
    python scripts/system_status.py --json
"""
from __future__ import annotations

import argparse
import json
import socket
import sqlite3
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "state" / "agente_bolsa.sqlite3"
REPORTS = ROOT / "data" / "reports"

OK, WARN, DOWN, NA = "OK", "WARN", "DOWN", "--"


def _now():
    return datetime.now(timezone.utc)


def _parse(ts):
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _age_min(ts):
    d = _parse(ts)
    return None if not d else (_now() - d).total_seconds() / 60.0


def _market_open(now):
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
            except Exception:
                pass
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


def build_status():
    now = _now()
    market_open = _market_open(now)
    comps = []

    if not DB.exists():
        return {"as_of": now.isoformat(), "market_open": market_open,
                "components": [{"name": "Base de datos", "state": DOWN, "detail": f"no existe {DB}", "expected": ""}],
                "verdict": DOWN}

    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
        con.execute("PRAGMA query_only=ON")
        jobs = _job_status(con)
    except sqlite3.Error as exc:
        return {"as_of": now.isoformat(), "market_open": market_open,
                "components": [{"name": "Base de datos", "state": DOWN, "detail": f"no accesible: {exc}", "expected": "lectura ro"}],
                "verdict": DOWN}

    hb = _age_min((jobs.get("portfolio_watch") or {}).get("finished_at"))
    if hb is None:
        sched = (DOWN, "sin registro de actividad")
    elif hb <= 3:
        sched = (OK, f"vivo (heartbeat hace {hb:.1f} min)")
    elif hb <= 10:
        sched = (WARN, f"sin latido hace {hb:.1f} min")
    else:
        sched = (DOWN, f"parado: ultimo latido hace {hb:.0f} min")
    comps.append({"name": "Scheduler", "state": sched[0], "detail": sched[1], "expected": "proceso vivo (tarea AgenteBolsaScheduler)"})

    mc = jobs.get("market_cycle") or {}
    mc_age = _age_min(mc.get("finished_at"))
    if not market_open:
        st = (NA, "mercado cerrado: no aplica")
    elif mc_age is None:
        st = (DOWN, "sin ciclos registrados")
    elif mc_age <= 20:
        st = (OK, f"ultimo ciclo hace {mc_age:.1f} min ({mc.get('status')})")
    elif mc_age <= 35:
        st = (WARN, f"ultimo ciclo hace {mc_age:.0f} min")
    else:
        st = (DOWN, f"sin ciclos hace {mc_age:.0f} min con mercado abierto")
    comps.append({"name": "Ciclo de mercado (15m)", "state": st[0], "detail": st[1], "expected": "cada 15 min con NYSE abierto"})

    ahc_age = _age_min((jobs.get("agents_healthcheck") or {}).get("finished_at"))
    if ahc_age is None:
        st = (WARN, "sin ejecuciones")
    elif ahc_age <= 40:
        st = (OK, f"hace {ahc_age:.0f} min")
    elif ahc_age <= 90:
        st = (WARN, f"hace {ahc_age:.0f} min")
    else:
        st = (DOWN, f"hace {ahc_age:.0f} min")
    comps.append({"name": "Watchdog agentes (30m)", "state": st[0], "detail": st[1], "expected": "cada 30 min"})

    ci_age = _age_min((jobs.get("continuous_improvement") or {}).get("finished_at"))
    if ci_age is None:
        st = (WARN, "sin ejecuciones")
    elif ci_age <= 15:
        st = (OK, f"hace {ci_age:.1f} min")
    elif ci_age <= 60:
        st = (WARN, f"hace {ci_age:.0f} min")
    else:
        st = (DOWN, f"hace {ci_age:.0f} min")
    comps.append({"name": "Laboratorio mejora continua", "state": st[0], "detail": st[1], "expected": "runtime residente (~1 min)"})

    dec_age = _age_min(_last_llm(con, ("trade_decision",)))
    degraded = None
    ahc_path = REPORTS / "latest_agents_healthcheck.json"
    if ahc_path.exists():
        try:
            degraded = (json.loads(ahc_path.read_text(encoding="utf-8")).get("watchdog") or {}).get("degraded")
        except Exception:
            pass
    if degraded:
        st = (DOWN, "watchdog marca DEGRADADO (sin LLM de decision)")
    elif dec_age is None:
        st = (WARN, "sin llamadas de decision registradas")
    elif dec_age <= 24 * 60:
        st = (OK, f"ultima decision LLM hace {dec_age/60:.1f} h")
    else:
        st = (WARN, f"ultima decision LLM hace {dec_age/60:.0f} h")
    comps.append({"name": "LLM de decision", "state": st[0], "detail": st[1], "expected": "MiMo (o fallback) respondiendo"})

    web_up = _port_open("127.0.0.1", 8501)
    comps.append({"name": "Panel web (8501)", "state": OK if web_up else WARN,
                  "detail": "responde" if web_up else "no responde en 127.0.0.1:8501", "expected": "tarea AgenteBolsaWeb"})

    reps = sorted(REPORTS.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if reps:
        fresh = (_now().timestamp() - reps[0].stat().st_mtime) / 60.0
        det = f"ultimo reporte hace {fresh:.0f} min ({reps[0].name})"
        st = OK if fresh <= 60 else (WARN if fresh <= 24 * 60 else DOWN)
    else:
        st, det = WARN, "sin reportes"
    comps.append({"name": "Frescura de datos", "state": st, "detail": det, "expected": "reportes recientes"})

    size_gb = DB.stat().st_size / 1e9
    st = OK if size_gb < 3 else (WARN if size_gb < 8 else DOWN)
    comps.append({"name": "Base de datos", "state": st,
                  "detail": f"{size_gb:.1f} GB" + ("  (considerar VACUUM)" if size_gb >= 3 else ""), "expected": "< 3 GB"})

    con.close()

    crit = [c["state"] for c in comps if c["name"] in ("Scheduler", "Ciclo de mercado (15m)", "LLM de decision")]
    if DOWN in crit:
        verdict = DOWN
    elif any(c["state"] == WARN for c in comps):
        verdict = WARN
    else:
        verdict = OK
    return {"as_of": now.isoformat(), "market_open": market_open, "components": comps, "verdict": verdict}


def _color(s):
    return {OK: "#1a7f37", WARN: "#9a6700", DOWN: "#cf222e", NA: "#57606a"}.get(s, "#57606a")


def to_html(status):
    rows = []
    for c in status["components"]:
        rows.append(
            "<tr><td>" + escape(c["name"]) + "</td>"
            + "<td style='color:" + _color(c["state"]) + ";font-weight:700'>" + c["state"] + "</td>"
            + "<td>" + escape(c.get("detail", "")) + "</td>"
            + "<td style='color:#57606a'>" + escape(c.get("expected", "")) + "</td></tr>"
        )
    v = status["verdict"]
    mkt = "ABIERTO" if status["market_open"] else "cerrado"
    return (
        "<!doctype html><html lang='es'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta http-equiv='refresh' content='60'><title>Estado agenteBolsa</title><style>"
        "body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:24px;color:#1f2328;background:#fff}"
        "h1{font-size:20px;margin:0 0 4px}.sub{color:#57606a;font-size:13px;margin-bottom:16px}"
        ".badge{display:inline-block;padding:6px 14px;border-radius:8px;color:#fff;font-weight:700;font-size:18px;background:"
        + _color(v) + "}table{border-collapse:collapse;width:100%;margin-top:16px;font-size:14px}"
        "th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #eaecef}"
        "th{color:#57606a;font-weight:600;font-size:12px;text-transform:uppercase}</style></head><body>"
        "<h1>Estado del sistema — agenteBolsa</h1>"
        "<div class='sub'>Generado " + escape(status["as_of"][:19]) + " UTC · Mercado: " + mkt + " · auto-refresco 60s</div>"
        "<div>Veredicto global: <span class='badge'>" + v + "</span></div>"
        "<table><thead><tr><th>Componente</th><th>Estado</th><th>Detalle</th><th>Qué se espera</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>"
        "<p class='sub'>OK=sano · WARN=revisar · DOWN=caido · --=no aplica. scripts/system_status.py</p></body></html>"
    )


def main():
    ap = argparse.ArgumentParser(description="Pantalla de estado del sistema.")
    ap.add_argument("--html", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    status = build_status()
    if args.json:
        print(json.dumps(status, indent=2, ensure_ascii=False))
    else:
        print("=" * 64)
        print(f" ESTADO agenteBolsa - {status['as_of'][:19]} UTC - Mercado {'ABIERTO' if status['market_open'] else 'cerrado'}")
        print(f" VEREDICTO GLOBAL: {status['verdict']}")
        print("=" * 64)
        for c in status["components"]:
            print(f" [{c['state']:^4}] {c['name']:<28} {c['detail']}")
        print("=" * 64)
        print(" OK=sano  WARN=revisar  DOWN=caido  --=no aplica")
    if args.html:
        REPORTS.mkdir(parents=True, exist_ok=True)
        out = REPORTS / "system_status.html"
        out.write_text(to_html(status), encoding="utf-8")
        print(f"\nHTML escrito en {out}")
    return 1 if status["verdict"] == DOWN else 0


if __name__ == "__main__":
    sys.exit(main())
