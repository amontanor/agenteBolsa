#!/usr/bin/env python3
"""Informe semanal de mejora del sistema (markdown).

Motivacion (16-jun-2026): faltaba un reporting claro de que cambio, que mejoro,
que empeoro y que se revirtio. Este script lee la BD de estado (solo lectura) y
genera un markdown con la actividad del laboratorio de mejora continua, la
evolucion de equity/alpha y el estado del embudo de propuestas, para los ultimos
N dias.

Es seguro con el sistema levantado (abre la BD en modo solo-lectura).

Uso:
    python scripts/weekly_improvement_report.py
    python scripts/weekly_improvement_report.py --days 7 --out data/reports/weekly_improvement.md
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa._utils import sqlite_connect_ro, table_exists
from agente_bolsa.tools.c2_shadow_reporting import build_c2_shadow_report
from agente_bolsa.tools.profitability_scoreboard import build_profitability_scoreboard

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "state" / "agente_bolsa.sqlite3"
C2_SHADOW_SINCE_DATE = "2026-04-01"


def count_since(con, table, date_col, cutoff, where_extra="") -> int:
    if not table_exists(con, table):
        return 0
    try:
        sql = f"SELECT COUNT(*) FROM '{table}' WHERE {date_col} >= ?{where_extra}"
        return con.execute(sql, (cutoff,)).fetchone()[0]
    except sqlite3.OperationalError:
        return 0


def group_since(con, table, col, date_col, cutoff):
    if not table_exists(con, table):
        return []
    try:
        sql = f"SELECT {col} AS k, COUNT(*) AS n FROM '{table}' WHERE {date_col} >= ? GROUP BY {col} ORDER BY n DESC"
        return [(r["k"], r["n"]) for r in con.execute(sql, (cutoff,)).fetchall()]
    except sqlite3.OperationalError:
        return []


def build_markdown(db_path: Path, days: int) -> str:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    today = datetime.now(timezone.utc).date().isoformat()
    con = sqlite_connect_ro(db_path)
    out: list[str] = []
    out.append(f"# Informe semanal de mejora del sistema")
    out.append("")

    out.append(f"- Fecha de generacion: {today}")
    out.append(f"- Ventana: ultimos {days} dias (desde {cutoff[:10]})")
    out.append("")

    # --- Rendimiento ---
    out.append("## 1. Rendimiento (paper)")
    out.append("")
    if table_exists(con, "performance_daily"):
        rows = con.execute(
            "SELECT session_date, equity, pnl_pct, alpha, max_dd, sharpe_60, hit_rate_20 "
            "FROM performance_daily WHERE session_date >= ? ORDER BY session_date",
            (cutoff[:10],),
        ).fetchall()
        if rows:
            out.append("| Fecha | Equity | PnL% | Alpha | MaxDD | Sharpe60 | HitRate20 |")
            out.append("|---|---|---|---|---|---|---|")
            for r in rows:
                def f(x, p=4):
                    return "-" if x is None else f"{x:.{p}f}"
                out.append(
                    f"| {r['session_date']} | {f(r['equity'],2)} | {f(r['pnl_pct'])} | "
                    f"{f(r['alpha'])} | {f(r['max_dd'])} | {f(r['sharpe_60'])} | {f(r['hit_rate_20'])} |"
                )
            first, last = rows[0], rows[-1]
            if first["equity"] and last["equity"]:
                delta = last["equity"] - first["equity"]
                out.append("")
                out.append(f"Variacion de equity en la ventana: {delta:+.2f} "
                           f"({first['equity']:.2f} -> {last['equity']:.2f}).")
        else:
            out.append("_Sin filas de performance_daily en la ventana._")
    else:
        out.append("_Tabla performance_daily no disponible._")
    out.append("")

    # --- Embudo de mejora continua ---
    out.append("## 2. Embudo de mejora continua")
    out.append("")
    out.append(f"- Propuestas creadas: {count_since(con, 'continuous_improvement_proposals', 'created_at', cutoff)}")
    out.append(f"- Validaciones registradas: {count_since(con, 'continuous_improvement_validations', 'created_at', cutoff)}")
    out.append(f"- Cambios de codigo aplicados: {count_since(con, 'continuous_improvement_applied_changes', 'created_at', cutoff)}")
    out.append("")
    prop_status = group_since(con, "continuous_improvement_proposals", "status", "created_at", cutoff)
    if prop_status:
        out.append("Propuestas por estado (en ventana):")
        out.append("")
        for k, n in prop_status:
            out.append(f"- {k}: {n}")
        out.append("")
    val_status = group_since(con, "continuous_improvement_validations", "status", "created_at", cutoff)
    if val_status:
        out.append("Validaciones por estado (en ventana):")
        out.append("")
        for k, n in val_status:
            out.append(f"- {k}: {n}")
        out.append("")

    # --- Reglas / estrategias ---
    out.append("## 3. Reglas y estrategias")
    out.append("")
    if table_exists(con, "strategy_rules"):
        for k, n in [(r["status"], r["n"]) for r in con.execute(
                "SELECT status, COUNT(*) n FROM strategy_rules GROUP BY status")]:
            out.append(f"- strategy_rules [{k}]: {n}")
    out.append(f"- Versiones de estrategia totales: "
               f"{con.execute('SELECT COUNT(*) FROM strategy_versions').fetchone()[0] if table_exists(con,'strategy_versions') else 'n/d'}")
    out.append(f"- Reglas promovidas/retiradas en ventana (rule_evaluations): "
               f"{count_since(con, 'rule_evaluations', 'created_at', cutoff)}")
    out.append("")

    # --- Cambios aplicados y revertidos ---
    out.append("## 4. Cambios aplicados y revertidos")
    out.append("")
    if table_exists(con, "continuous_improvement_applied_changes"):
        applied = con.execute(
            "SELECT * FROM continuous_improvement_applied_changes WHERE created_at >= ? ORDER BY created_at DESC",
            (cutoff,),
        ).fetchall()
        if applied:
            for r in applied:
                d = dict(r)
                out.append(f"- {d.get('created_at','')[:19]} | {d.get('status','?')} | "
                           f"{str(d.get('summary') or d.get('proposal_id') or '')[:100]}")
        else:
            out.append("_Ningun cambio de codigo aplicado en la ventana._")
    else:
        out.append("_Tabla continuous_improvement_applied_changes no disponible._")
    out.append("")

    # --- Lecciones ---
    out.append("## 5. Aprendizaje destilado")
    out.append("")
    out.append(f"- Lecciones destiladas (total): "
               f"{con.execute('SELECT COUNT(*) FROM distilled_lessons').fetchone()[0] if table_exists(con,'distilled_lessons') else 'n/d'}")
    out.append(f"- Resumenes diarios de aprendizaje en ventana: "
               f"{count_since(con, 'learning_daily_summaries', 'created_at', cutoff)}")
    out.append("")

    # --- Capa 2 shadow ---
    out.append("## 6. Capa 2: medicion shadow")
    out.append("")
    try:
        data_dir = db_path.parent.parent
        settings = Settings(DATA_DIR=data_dir)
        store = Store(db_path, settings.agent_logs_dir)
        scoreboard = build_profitability_scoreboard(settings, store, since_date=C2_SHADOW_SINCE_DATE)
        horizon = scoreboard.get("exit_horizon_shadow") or {}
        perf = scoreboard.get("performance") or {}
        shadow = build_c2_shadow_report(settings, store, since_date=C2_SHADOW_SINCE_DATE)
        out.append(f"- Ventana Capa 2: desde {C2_SHADOW_SINCE_DATE} (necesaria para madurar 5-10 sesiones).")
        out.append(
            f"- Alpha acumulado vs SPY: {perf.get('cumulative_alpha')} "
            f"(cobertura {((perf.get('benchmark_coverage') or {}).get('available', 0))}/"
            f"{((perf.get('benchmark_coverage') or {}).get('total', 0))})."
        )
        out.append(
            f"- Horizonte actual 1-3d: {horizon.get('current_1_3d')}; "
            f"shadow 5-10d: {horizon.get('shadow_5_10d')}; "
            f"pareado: {horizon.get('paired_comparison')}."
        )
        stale = shadow.get("stale_guard") or {}
        out.append(
            f"- stale_guard SHADOW: flag conducta={((shadow.get('flags') or {}).get('stale_guard_behavior_enabled'))}, "
            f"elegibles={stale.get('eligible')}, disparos={stale.get('triggered')}, "
            f"actual={stale.get('current')}, shadow={stale.get('shadow')}."
        )
        confirmed = shadow.get("confirmed_pattern") or {}
        out.append(
            f"- confirmed_pattern SHADOW: aplicada={confirmed.get('applied')}, "
            f"senales={confirmed.get('signals')}, penalizacion={confirmed.get('shadow_penalty')}, "
            f"metricas={confirmed.get('metrics')}."
        )
    except Exception as exc:  # noqa: BLE001 - el informe base debe seguir disponible.
        out.append(f"_Medicion Capa 2 no disponible: {exc!r}._")
    out.append("")

    out.append("---")
    out.append("")
    out.append("_Generado por scripts/weekly_improvement_report.py. "
               "Anadir nuevas metricas aqui segun evolucione el sistema._")

    con.close()
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera el informe semanal de mejora.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--out", default=None, help="Ruta de salida .md (por defecto, stdout).")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: no existe la BD {db_path}", file=sys.stderr)
        return 2

    md = build_markdown(db_path, args.days)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        print(f"Informe escrito en {out_path}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
