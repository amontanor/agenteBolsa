#!/usr/bin/env python3
"""Salud del grupo de agentes + mejores oportunidades (determinista).

Combina dos piezas para responder a "¿esta el grupo operando bien y que deberia
estar comprando?":

  1. Watchdog de LLM degradado (agente_bolsa.tools.llm_degraded_watchdog).
  2. Ranking determinista de oportunidades (agente_bolsa.tools.opportunity_ranker)
     sobre el universo amplio (estudio tecnico) o, si no, breakout scan / snapshot.

Escribe dos reportes en data/reports y resume en consola. Solo lectura sobre la
BD; no ejecuta ordenes. Pensado para ejecutarse a mano o como job programado.

Codigo de salida: 1 si el grupo esta en modo degradado (LLM caido), 0 si no.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DB = ROOT / "data" / "state" / "agente_bolsa.sqlite3"
REPORTS = ROOT / "data" / "reports"


def _latest(pattern: str) -> Path | None:
    files = sorted(glob.glob(str(REPORTS / pattern)))
    return Path(files[-1]) if files else None


def _build_opportunities(top_n: int, explicit_snapshot: str | None) -> dict:
    """Construye el ranking desde la mejor fuente: estudio tecnico amplio
    (~500 simbolos) > breakout scan > snapshot de megacaps."""
    from agente_bolsa.tools.opportunity_ranker import (
        rank_opportunities,
        snapshot_from_breakout_scan,
        snapshot_from_technical_study,
    )

    if explicit_snapshot:
        snap = json.loads(Path(explicit_snapshot).read_text(encoding="utf-8"))
        res = rank_opportunities(snap, top_n=top_n)
        res["source"] = explicit_snapshot
        return res

    study = REPORTS / "latest_closed_market_technical_study.json"
    if study.exists():
        data = json.loads(study.read_text(encoding="utf-8"))
        res = rank_opportunities(snapshot_from_technical_study(data), top_n=top_n)
        res["source"] = f"technical_study ({study.name})"
        return res

    scan = REPORTS / "latest_breakout_scan.json"
    if scan.exists():
        data = json.loads(scan.read_text(encoding="utf-8"))
        res = rank_opportunities(snapshot_from_breakout_scan(data), top_n=top_n)
        res["source"] = f"breakout_scan ({scan.name})"
        return res

    snap_path = _latest("market_snapshot_*.json")
    if snap_path:
        snap = json.loads(snap_path.read_text(encoding="utf-8"))
        res = rank_opportunities(snap, top_n=top_n)
        res["source"] = f"market_snapshot ({snap_path.name})"
        return res

    return {"error": "sin fuente de oportunidades"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Salud del grupo de agentes + oportunidades.")
    parser.add_argument("--top", type=int, default=10, help="Numero de oportunidades a mostrar.")
    parser.add_argument("--db", default=str(DB))
    parser.add_argument("--snapshot", default=None, help="Ruta a un snapshot JSON explicito.")
    parser.add_argument("--json", action="store_true", help="Salida JSON.")
    parser.add_argument("--no-write", action="store_true", help="No escribir reportes a disco.")
    args = parser.parse_args()

    try:
        from agente_bolsa.tools.llm_degraded_watchdog import evaluate as watchdog_evaluate
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR importando modulos del proyecto: {exc}", file=sys.stderr)
        return 2

    watchdog = {"degraded": None, "error": None}
    if Path(args.db).exists():
        try:
            watchdog = watchdog_evaluate(args.db)
        except Exception as exc:  # noqa: BLE001
            watchdog = {"degraded": None, "error": str(exc)}
    else:
        watchdog = {"degraded": None, "error": f"BD no encontrada: {args.db}"}

    try:
        opportunities = _build_opportunities(args.top, args.snapshot)
    except Exception as exc:  # noqa: BLE001
        opportunities = {"error": str(exc)}

    result = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "watchdog": watchdog,
        "opportunities": opportunities,
    }

    if not args.no_write:
        REPORTS.mkdir(parents=True, exist_ok=True)
        (REPORTS / "latest_agents_healthcheck.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        (REPORTS / "latest_opportunities.json").write_text(
            json.dumps(opportunities, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1 if watchdog.get("degraded") else 0

    print("=== Salud del grupo de agentes ===")
    sev = watchdog.get("severity", "?")
    if watchdog.get("degraded"):
        print(f"[DEGRADADO/{sev.upper()}] El grupo opera SIN LLM de decision fiable.")
        for r in watchdog.get("reasons", []):
            print(f"  - {r}")
        print(f"  Accion: {watchdog.get('recommended_action')}")
    elif watchdog.get("degraded") is None:
        print(f"[?] No se pudo evaluar el watchdog: {watchdog.get('error')}")
    else:
        print("[OK] LLM de decision disponible; el grupo opera normal.")

    print("\n=== Mejores oportunidades (determinista, sin LLM) ===")
    if "error" in opportunities:
        print(f"  No disponible: {opportunities['error']}")
    else:
        print(f"  Fuente: {opportunities.get('source')} | benchmark "
              f"{opportunities.get('benchmark')} ret20d={opportunities.get('benchmark_return_20d')}")
        print(f"  Evaluados {opportunities.get('evaluated')}, elegibles {opportunities.get('eligible')}")
        print(f"  {'#':>2} {'sym':<6} {'score':>7} {'ret20d':>8} {'RS':>7} {'stop%':>7}  motivo")
        for i, opp in enumerate(opportunities.get("opportunities", []), 1):
            m = opp["metrics"]
            ret = m.get("return_20d")
            rs = m.get("relative_return_20d")
            stop = opp.get("suggested_stop_pct")
            print(f"  {i:>2} {opp['symbol']:<6} {opp['score']:>7.1f} "
                  f"{(ret * 100 if ret is not None else 0):>7.1f}% "
                  f"{(rs * 100 if rs is not None else 0):>6.1f}% "
                  f"{(stop * 100 if stop is not None else 0):>6.1f}%  {opp['reason'][:66]}")

    return 1 if watchdog.get("degraded") else 0


if __name__ == "__main__":
    sys.exit(main())
