#!/usr/bin/env python3
"""Mantenimiento de la base de datos de estado (retencion por tabla + VACUUM).

Contexto (jun-2026): agente_bolsa.sqlite3 llego a ~8 GB y disparo el estado
DOWN del panel (umbral OK < 3 GB, WARN 3-8 GB, DOWN >= 8 GB).

Diagnostico real (medido sobre produccion):
  - El crecimiento NO es espacio libre: el freelist era 0 el 20-jun-2026.
  - La causa principal eran snapshots duplicados en continuous_improvement_cycles:
    ~10,8 MB por ciclo y 8,5 GB para 783 ciclos. Las entidades canonicas ya
    existen en tablas normalizadas, por lo que el mantenimiento compacta esos
    snapshots sin perder propuestas, validaciones, eventos ni aprendizaje.
  - signal_outcomes es el segundo consumidor (~1,25 GB para 326k filas).
  - Hay ademas ~35-40% de paginas medio vacias en signal_outcomes por los
    UPDATE repetidos (upsert) a medida que maduran los outcomes. Eso solo lo
    recupera un VACUUM completo (no el incremental).
  - Nada borraba filas de la BD: retention.py solo limpia ficheros de disco.

Combina CUATRO palancas:
  1. COMPACTACION de snapshots historicos del laboratorio.
  2. RETENCION por tabla (borra filas antiguas tipo log; respeta operativa).
  3. VACUUM completo (defragmenta y devuelve espacio al SO).
  4. auto_vacuum=INCREMENTAL + incremental_vacuum para liberar sin VACUUM caro.

Por defecto DRY-RUN (solo informa) y abre en solo-lectura: seguro con el sistema
levantado. Para modos que escriben (--apply, --vacuum-only,
--set-incremental-autovacuum) el scheduler debe estar PARADO (VACUUM = lock
exclusivo). Aborta si hay -wal activo (>1 MB) salvo --force. Usa
scripts/run_db_maintenance.ps1 para parar/arrancar el scheduler.

Uso:
    python scripts/db_maintenance.py                         # dry-run
    python scripts/db_maintenance.py --days 45               # dry-run, corte global
    python scripts/db_maintenance.py --json                  # salida JSON
    python scripts/db_maintenance.py --vacuum-only           # solo compactar
    python scripts/db_maintenance.py --apply --days 45       # borrar + VACUUM
    python scripts/db_maintenance.py --apply --incremental   # borrar + incremental_vacuum
    python scripts/db_maintenance.py --set-incremental-autovacuum  # one-time
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agente_bolsa._utils import human_bytes, sqlite_connect_ro, table_exists

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "state" / "agente_bolsa.sqlite3"

# Retencion por tabla (dias a CONSERVAR). Solo tablas voluminosas tipo log.
# NO se incluye operativa/estado: esas se conservan integras.
DEFAULT_RETENTION = {
    "signal_outcomes": ("created_at", 45),
    "agent_events": ("created_at", 45),
    "learning_observations": ("created_at", 60),
    "continuous_improvement_llm_responses": ("created_at", 21),
    "continuous_improvement_decisions": ("created_at", 45),
    "continuous_improvement_cycles": ("created_at", 45),
    "continuous_improvement_events": ("created_at", 45),
    "continuous_improvement_initiative_messages": ("created_at", 45),
}


def connect(db_path: Path, read_only: bool) -> sqlite3.Connection:
    if read_only:
        return sqlite_connect_ro(db_path, timeout=30)
    con = sqlite3.connect(str(db_path), timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    return con


def _retention_plan(global_days):
    if global_days is None:
        return dict(DEFAULT_RETENTION)
    return {t: (col, global_days) for t, (col, _d) in DEFAULT_RETENTION.items()}


def analyze(db_path: Path, global_days) -> dict:
    plan = _retention_plan(global_days)
    now = datetime.now(timezone.utc)
    con = connect(db_path, read_only=True)
    cur = con.cursor()
    page_size = cur.execute("PRAGMA page_size").fetchone()[0]
    page_count = cur.execute("PRAGMA page_count").fetchone()[0]
    freelist = cur.execute("PRAGMA freelist_count").fetchone()[0]
    auto_vac = cur.execute("PRAGMA auto_vacuum").fetchone()[0]
    total_bytes = page_size * page_count
    free_bytes = page_size * freelist
    tables = []
    total_prunable = 0
    for table, (date_col, days) in plan.items():
        if not table_exists(cur, table):
            continue
        cutoff = (now - timedelta(days=days)).isoformat()
        total = cur.execute(f"SELECT COUNT(*) FROM '{table}'").fetchone()[0]
        try:
            old = cur.execute(
                f"SELECT COUNT(*) FROM '{table}' WHERE {date_col} < ?", (cutoff,)
            ).fetchone()[0]
        except sqlite3.OperationalError:
            old = 0
        total_prunable += old
        tables.append({"table": table, "date_col": date_col, "keep_days": days,
                       "cutoff": cutoff, "rows": total, "prunable_rows": old,
                       "keep_rows": total - old})
    con.close()
    return {"db_path": str(db_path),
            "auto_vacuum": {0: "NONE", 1: "FULL", 2: "INCREMENTAL"}.get(auto_vac, auto_vac),
            "file_bytes": total_bytes, "file_human": human_bytes(total_bytes),
            "free_bytes": free_bytes, "free_human": human_bytes(free_bytes),
            "free_ratio": round(free_bytes / total_bytes, 4) if total_bytes else 0.0,
            "tables": tables, "total_prunable_rows": total_prunable}


def _wal_blocks(db_path: Path, force: bool):
    wal = db_path.with_suffix(db_path.suffix + "-wal")
    if wal.exists() and wal.stat().st_size > 1_000_000 and not force:
        return ("Hay un -wal activo (>1MB): el scheduler probablemente esta escribiendo. "
                "Para el scheduler (scripts/run_db_maintenance.ps1) y reintenta, o usa --force.")
    return None


def _checkpoint(cur: sqlite3.Cursor) -> None:
    try:
        cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.OperationalError:
        pass


def vacuum(db_path: Path) -> None:
    con = connect(db_path, read_only=False)
    con.isolation_level = None
    _checkpoint(con.cursor())
    con.execute("VACUUM")
    con.close()


def set_incremental_autovacuum(db_path: Path) -> None:
    con = connect(db_path, read_only=False)
    con.isolation_level = None
    cur = con.cursor()
    _checkpoint(cur)
    cur.execute("PRAGMA auto_vacuum=INCREMENTAL")
    cur.execute("VACUUM")
    con.close()


def compact_ci_cycles(cur: sqlite3.Cursor) -> dict[str, int]:
    """Replace duplicated cycle payloads with bounded audit snapshots."""

    if not table_exists(cur, "continuous_improvement_cycles"):
        return {"scanned": 0, "compacted": 0, "bytes_before": 0, "bytes_after": 0}
    from agente_bolsa.continuous_improvement.persistence_compaction import (
        compact_cycle_context,
        compact_cycle_report,
    )

    rows = cur.execute(
        "SELECT cycle_id, context_json, report_json FROM continuous_improvement_cycles"
    ).fetchall()
    compacted = 0
    bytes_before = 0
    bytes_after = 0
    for cycle_id, context_text, report_text in rows:
        context_text = context_text or "{}"
        report_text = report_text or "{}"
        bytes_before += len(context_text.encode("utf-8")) + len(report_text.encode("utf-8"))
        try:
            context = json.loads(context_text)
        except (TypeError, ValueError):
            context = {}
        try:
            report = json.loads(report_text)
        except (TypeError, ValueError):
            report = {}
        compact_context = compact_cycle_context(context)
        compact_report = compact_cycle_report(report)
        new_context = json.dumps(compact_context, ensure_ascii=False, separators=(",", ":"), default=str)
        new_report = json.dumps(compact_report, ensure_ascii=False, separators=(",", ":"), default=str)
        bytes_after += len(new_context.encode("utf-8")) + len(new_report.encode("utf-8"))
        if new_context == context_text and new_report == report_text:
            continue
        cur.execute(
            """
            UPDATE continuous_improvement_cycles
            SET context_json = ?, report_json = ?, updated_at = ?
            WHERE cycle_id = ?
            """,
            (new_context, new_report, datetime.now(timezone.utc).isoformat(), cycle_id),
        )
        compacted += 1
    return {
        "scanned": len(rows),
        "compacted": compacted,
        "bytes_before": bytes_before,
        "bytes_after": bytes_after,
    }


def apply_maintenance(db_path: Path, global_days, force: bool, incremental: bool) -> dict:
    blocked = _wal_blocks(db_path, force)
    if blocked:
        return {"applied": False, "error": blocked}
    plan = _retention_plan(global_days)
    now = datetime.now(timezone.utc)
    con = connect(db_path, read_only=False)
    con.isolation_level = None
    cur = con.cursor()
    _checkpoint(cur)
    deleted = {}
    cur.execute("BEGIN")
    cycle_compaction = compact_ci_cycles(cur)
    for table, (date_col, days) in plan.items():
        if not table_exists(cur, table):
            continue
        cutoff = (now - timedelta(days=days)).isoformat()
        cur.execute(f"DELETE FROM '{table}' WHERE {date_col} < ?", (cutoff,))
        deleted[table] = cur.rowcount
    cur.execute("COMMIT")
    if incremental:
        cur.execute("PRAGMA incremental_vacuum")
        mode = "incremental_vacuum"
    else:
        cur.execute("VACUUM")
        mode = "VACUUM"
    con.close()
    return {
        "applied": True,
        "vacuum_mode": mode,
        "cycle_compaction": cycle_compaction,
        "deleted": deleted,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Mantenimiento de la BD de estado.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Ruta a la BD sqlite.")
    parser.add_argument("--days", type=int, default=None,
                        help="Corte global de retencion (sobreescribe valores por tabla).")
    parser.add_argument("--apply", action="store_true", help="Borrado + VACUUM (scheduler parado).")
    parser.add_argument("--incremental", action="store_true",
                        help="Con --apply: incremental_vacuum en vez de VACUUM completo.")
    parser.add_argument("--vacuum-only", action="store_true",
                        help="Solo VACUUM completo (no borra). Scheduler parado.")
    parser.add_argument("--set-incremental-autovacuum", action="store_true",
                        help="One-time: activa auto_vacuum=INCREMENTAL (+VACUUM).")
    parser.add_argument("--force", action="store_true", help="Forzar aun con -wal activo.")
    parser.add_argument("--json", action="store_true", help="Salida JSON.")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: no existe la BD {db_path}", file=sys.stderr)
        return 2

    report = analyze(db_path, args.days)

    if args.set_incremental_autovacuum:
        blocked = _wal_blocks(db_path, args.force)
        if blocked:
            print(f"NO APLICADO: {blocked}")
            return 1
        set_incremental_autovacuum(db_path)
        after = analyze(db_path, args.days)
        print(f"auto_vacuum -> {after['auto_vacuum']}. Tamano: {after['file_human']} (antes {report['file_human']})")
        return 0

    if args.vacuum_only and not args.apply:
        blocked = _wal_blocks(db_path, args.force)
        if blocked:
            print(f"NO APLICADO: {blocked}")
            return 1
        vacuum(db_path)
        after = analyze(db_path, args.days)
        print("VACUUM aplicado (sin borrado de filas).")
        print(f"Tamano: {after['file_human']} (antes {report['file_human']})")
        return 0

    if args.apply:
        result = apply_maintenance(db_path, args.days, args.force, args.incremental)
        report["apply_result"] = result
        if result.get("applied"):
            report["after"] = analyze(db_path, args.days)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== Mantenimiento de BD (modo: {mode}) ===")
    print(f"BD            : {report['db_path']}")
    print(f"Tamano fichero: {report['file_human']}   auto_vacuum={report['auto_vacuum']}")
    print(f"Espacio libre : {report['free_human']} ({report['free_ratio'] * 100:.1f}% del fichero)")
    print()
    print(f"{'tabla':<44}{'mant.d':>7}{'filas':>10}{'a borrar':>11}{'conservar':>11}")
    for t in report["tables"]:
        print(f"{t['table']:<44}{t['keep_days']:>7}{t['rows']:>10}{t['prunable_rows']:>11}{t['keep_rows']:>11}")
    print(f"\nTotal filas borrables: {report['total_prunable_rows']}")

    if args.apply:
        res = report.get("apply_result", {})
        if res.get("applied"):
            compaction = res.get("cycle_compaction", {})
            before = int(compaction.get("bytes_before") or 0)
            after_bytes = int(compaction.get("bytes_after") or 0)
            print(
                f"\nSnapshots CI compactados: {compaction.get('compacted', 0)}/"
                f"{compaction.get('scanned', 0)} ({human_bytes(before)} -> {human_bytes(after_bytes)})"
            )
            print(f"\nAPLICADO ({res.get('vacuum_mode')}). Filas borradas:")
            for tbl, n in res.get("deleted", {}).items():
                print(f"  {tbl}: {n}")
            after = report.get("after", {})
            print(f"\nTamano final: {after.get('file_human')} (antes {report['file_human']})")
        else:
            print(f"\nNO APLICADO: {res.get('error')}")
            return 1
    else:
        print("\n(DRY-RUN: no se modifico nada.)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
