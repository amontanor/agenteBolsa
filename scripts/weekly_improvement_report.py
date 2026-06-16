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

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "state" / "agente_bolsa.sqlite3"


def connect_ro(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    return con


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


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
    con = connect_ro(db_path)
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
