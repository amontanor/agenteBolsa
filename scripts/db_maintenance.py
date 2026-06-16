#!/usr/bin/env python3
"""Mantenimiento de la base de datos de estado (retencion + VACUUM).

Motivacion (16-jun-2026): agente_bolsa.sqlite3 crecio a ~6,9 GB con solo
~400k filas reales (~750 MB de contenido real). La causa NO es espacio libre
(freelist ~0) sino fragmentacion de paginas por UPDATEs repetidos (los outcomes
de senal maduran y se reescriben muchas veces) y ausencia de VACUUM. VACUUM
compacta el fichero aunque la retencion no borre filas.

Este script:
  1. Mide el tamano del fichero y el espacio libre real.
  2. Identifica filas mas antiguas que el corte de retencion en tablas
     voluminosas tipo log (NO toca tablas sensibles de operativa).
  3. En modo --apply: borra esas filas y ejecuta VACUUM.
  4. En modo --vacuum-only: solo defragmenta (sin borrar nada).

Por defecto corre en DRY-RUN (solo informa, no modifica nada) y abre la base
en modo solo-lectura, asi que es seguro con el sistema levantado.

IMPORTANTE: para --apply o --vacuum-only, el scheduler debe estar PARADO
(VACUUM toma lock exclusivo). El script aborta si detecta un -wal grande
activo salvo que se pase --force.

Uso:
    python scripts/db_maintenance.py                      # dry-run, retencion 120d
    python scripts/db_maintenance.py --days 90            # dry-run con otro corte
    python scripts/db_maintenance.py --vacuum-only        # solo compactar (scheduler parado)
    python scripts/db_maintenance.py --apply --days 120   # borrar + VACUUM (scheduler parado)
    python scripts/db_maintenance.py --json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "state" / "agente_bolsa.sqlite3"

RETENTION_TABLES = {
    "signal_outcomes": "created_at",
    "agent_events": "created_at",
    "learning_observations": "created_at",
    "continuous_improvement_llm_responses": "created_at",
    "continuous_improvement_decisions": "created_at",
    "continuous_improvement_initiative_messages": "created_at",
}


def human(n_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n_bytes) < 1024.0:
            return f"{n_bytes:.1f}{unit}"
        n_bytes /= 1024.0
    return f"{n_bytes:.1f}PB"


def connect(db_path: Path, read_only: bool) -> sqlite3.Connection:
    if read_only:
        uri = f"file:{db_path}?mode=ro&immutable=1"
        return sqlite3.connect(uri, uri=True)
    return sqlite3.connect(str(db_path))


def table_exists(cur: sqlite3.Cursor, name: str) -> bool:
    row = cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def analyze(db_path: Path, days: int) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    con = connect(db_path, read_only=True)
    cur = con.cursor()
    page_size = cur.execute("PRAGMA page_size").fetchone()[0]
    page_count = cur.execute("PRAGMA page_count").fetchone()[0]
    freelist = cur.execute("PRAGMA freelist_count").fetchone()[0]
    total_bytes = page_size * page_count
    free_bytes = page_size * freelist
    tables = []
    total_prunable = 0
    for table, date_col in RETENTION_TABLES.items():
        if not table_exists(cur, table):
            continue
        total = cur.execute(f"SELECT COUNT(*) FROM '{table}'").fetchone()[0]
        try:
            old = cur.execute(
                f"SELECT COUNT(*) FROM '{table}' WHERE {date_col} < ?", (cutoff,)
            ).fetchone()[0]
        except sqlite3.OperationalError:
            old = 0
        total_prunable += old
        tables.append({"table": table, "date_col": date_col, "rows": total,
                       "prunable_rows": old, "keep_rows": total - old})
    con.close()
    return {"db_path": str(db_path), "cutoff": cutoff, "retention_days": days,
            "file_bytes": total_bytes, "file_human": human(total_bytes),
            "free_bytes": free_bytes, "free_human": human(free_bytes),
            "free_ratio": round(free_bytes / total_bytes, 4) if total_bytes else 0.0,
            "tables": tables, "total_prunable_rows": total_prunable}


def _wal_blocks(db_path: Path, force: bool):
    wal = db_path.with_suffix(db_path.suffix + "-wal")
    if wal.exists() and wal.stat().st_size > 1_000_000 and not force:
        return ("Hay un -wal activo (>1MB): probablemente el scheduler esta escribiendo. "
                "Para el scheduler y reintenta, o usa --force bajo tu responsabilidad.")
    return None


def vacuum(db_path: Path) -> None:
    con = connect(db_path, read_only=False)
    con.isolation_level = None
    con.execute("VACUUM")
    con.close()


def apply_maintenance(db_path: Path, days: int, force: bool) -> dict:
    blocked = _wal_blocks(db_path, force)
    if blocked:
        return {"applied": False, "error": blocked}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    con = connect(db_path, read_only=False)
    cur = con.cursor()
    deleted = {}
    for table, date_col in RETENTION_TABLES.items():
        if not table_exists(cur, table):
            continue
        cur.execute(f"DELETE FROM '{table}' WHERE {date_col} < ?", (cutoff,))
        deleted[table] = cur.rowcount
    con.commit()
    con.isolation_level = None
    cur.execute("VACUUM")
    con.close()
    return {"applied": True, "cutoff": cutoff, "deleted": deleted}


def main() -> int:
    parser = argparse.ArgumentParser(description="Mantenimiento de la BD de estado.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Ruta a la BD sqlite.")
    parser.add_argument("--days", type=int, default=120, help="Dias de retencion a conservar.")
    parser.add_argument("--apply", action="store_true", help="Aplicar borrado + VACUUM (scheduler parado).")
    parser.add_argument("--vacuum-only", action="store_true",
                        help="Solo VACUUM (defragmenta, no borra filas). Requiere scheduler parado.")
    parser.add_argument("--force", action="store_true", help="Forzar aun con -wal activo.")
    parser.add_argument("--json", action="store_true", help="Salida JSON.")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: no existe la BD {db_path}", file=sys.stderr)
        return 2

    report = analyze(db_path, args.days)

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
        result = apply_maintenance(db_path, args.days, args.force)
        report["apply_result"] = result
        if result.get("applied"):
            report["after"] = analyze(db_path, args.days)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== Mantenimiento de BD (modo: {mode}) ===")
    print(f"BD: {report['db_path']}")
    print(f"Tamano fichero : {report['file_human']}")
    print(f"Espacio libre  : {report['free_human']} ({report['free_ratio'] * 100:.1f}% del fichero)")
    print(f"Corte retencion: {report['retention_days']}d  (< {report['cutoff']})")
    print()
    print(f"{'tabla':<42}{'filas':>10}{'a borrar':>12}{'conservar':>12}")
    for t in report["tables"]:
        print(f"{t['table']:<42}{t['rows']:>10}{t['prunable_rows']:>12}{t['keep_rows']:>12}")
    print(f"\nTotal filas borrables: {report['total_prunable_rows']}")

    if args.apply:
        res = report.get("apply_result", {})
        if res.get("applied"):
            print("\nAPLICADO. Filas borradas:")
            for tbl, n in res.get("deleted", {}).items():
                print(f"  {tbl}: {n}")
            after = report.get("after", {})
            print(f"\nTamano tras VACUUM: {after.get('file_human')} (antes {report['file_human']})")
        else:
            print(f"\nNO APLICADO: {res.get('error')}")
            return 1
    else:
        print("\n(DRY-RUN: no se modifico nada.)")
        print("Para compactar el fichero (causa principal del tamano), con el scheduler")
        print("parado ejecuta:  python scripts/db_maintenance.py --vacuum-only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
