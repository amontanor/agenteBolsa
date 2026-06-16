#!/usr/bin/env python3
"""Refresca la capa de evidencia externa de investigacion.

Motivacion (16-jun-2026): la tabla `research_evidence` estaba vacia y el fichero
`data/reports/latest_research_evidence.json` no existia, porque
`build_research_evidence_report` no se invocaba en el ciclo programado. Como
consecuencia, el "research_guard" (fail-closed por falta de evidencia) era un
no-op y la enriquecimiento de la decision con evidencia no aportaba nada.

Este script ejecuta el constructor de evidencia de forma explicita para:
  - poblar la tabla `research_evidence`,
  - escribir `latest_research_evidence.json` (que lee el guard),
  - dejar trazabilidad de fiabilidad/frescura por simbolo.

Pensado para ejecutarse a mano o como job programado (p.ej. junto al daily_study
o al inicio de sesion). Requiere el entorno del proyecto (.venv) porque usa los
modulos de la aplicacion.

Uso:
    python scripts/refresh_research_evidence.py
    python scripts/refresh_research_evidence.py --symbols AAPL MSFT NVDA
    python scripts/refresh_research_evidence.py --max-symbols 12 --json
"""
from __future__ import annotations

import argparse
import json
import sys
from uuid import uuid4


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresca la evidencia externa de investigacion.")
    parser.add_argument("--symbols", nargs="*", default=None,
                        help="Simbolos a evaluar. Por defecto, el universo configurado.")
    parser.add_argument("--max-symbols", type=int, default=12,
                        help="Maximo de simbolos a procesar (coste de fetch).")
    parser.add_argument("--json", action="store_true", help="Salida JSON del resumen.")
    args = parser.parse_args()

    # Imports diferidos: solo disponibles dentro del entorno del proyecto.
    try:
        from agente_bolsa.config import get_settings
        from agente_bolsa.storage import Store
        from agente_bolsa.tools.research_evidence import build_research_evidence_report
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR importando el proyecto (¿venv activo?): {exc}", file=sys.stderr)
        return 2

    settings = get_settings()
    if not getattr(settings, "research_evidence_enabled", True):
        print("RESEARCH_EVIDENCE_ENABLED=false: la capa esta desactivada por configuracion.")
        return 0

    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()

    symbols = args.symbols if args.symbols else list(getattr(settings, "universe", []))
    symbols = [str(s).upper() for s in symbols if str(s).strip()][: args.max_symbols]
    if not symbols:
        print("No hay simbolos que evaluar (universo vacio y sin --symbols).", file=sys.stderr)
        return 1

    reports_dir = settings.data_dir / "reports"
    run_id = f"research_{uuid4().hex[:12]}"
    report = build_research_evidence_report(
        store,
        settings,
        reports_dir,
        run_id,
        symbols=symbols,
        market_state=None,
        sentiment_context=None,
    )

    summary = report.get("summary", {}) if isinstance(report, dict) else {}
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print("=== Refresco de evidencia externa ===")
        print(f"Run: {run_id}")
        print(f"Simbolos solicitados : {summary.get('symbols_requested')}")
        print(f"Con evidencia fresca : {summary.get('symbols_with_fresh_evidence')}")
        print(f"Sin evidencia fresca : {summary.get('symbols_missing_fresh_evidence')}")
        print(f"Filas persistidas    : {summary.get('rows_persisted')}")
        print(f"Fail-closed activo   : {summary.get('required')}")
        print(f"Decision lista       : {summary.get('decision_ready')}")
        print(f"\nReporte: {reports_dir / 'latest_research_evidence.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
