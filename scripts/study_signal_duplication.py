"""Cuantifica la duplicación de señales (T6, 25-jun-2026).

`record_signal_candidates` graba TODOS los candidatos en CADA ciclo (cada 15 min), con
`signal_id = {run_id}:{symbol}`. Por eso el mismo símbolo se repite ~26 veces/día con
features casi idénticas: el `duplicate_ratio` ~0.90. Esto infla `signal_outcomes` y, sobre
todo, hace que los "N samples" de los estudios de edge sean **altamente correlacionados**:
la muestra INDEPENDIENTE real es (símbolo × día), no (símbolo × ciclo).

Este script (SOLO lectura) mide el panorama real:
  - filas totales vs combinaciones únicas (símbolo, día) = muestra independiente efectiva,
  - duplicate_ratio real,
  - filas por símbolo-día (media/máx),
  - rango de fechas y nº de símbolos.

Uso:
    .\.venv\Scripts\python.exe scripts\study_signal_duplication.py
"""
from __future__ import annotations

import argparse
from collections import Counter

from agente_bolsa._utils import sqlite_connect_ro, table_exists
from agente_bolsa.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Duplicación de señales en signal_outcomes.")
    parser.add_argument("--db", default=None, help="Ruta a la BD (por defecto, settings).")
    args = parser.parse_args()

    settings = get_settings()
    db_path = args.db or str(settings.database_path)
    conn = sqlite_connect_ro(db_path, timeout=30.0)
    try:
        if not table_exists(conn, "signal_outcomes"):
            print("No existe la tabla signal_outcomes.")
            return
        rows = conn.execute(
            "SELECT signal_date, signal_id FROM signal_outcomes WHERE coalesce(source, '') != 'lab_book'"
        ).fetchall()
    finally:
        conn.close()

    total = 0
    by_symbol_day: Counter = Counter()
    symbols: set[str] = set()
    dates: set[str] = set()
    for row in rows:
        sdate = (row["signal_date"] if hasattr(row, "keys") else row[0]) or ""
        sid = (row["signal_id"] if hasattr(row, "keys") else row[1]) or ""
        day = str(sdate)[:10]
        symbol = str(sid).split(":")[-1].upper() if sid else "?"
        if not day or symbol == "?":
            continue
        total += 1
        by_symbol_day[(symbol, day)] += 1
        symbols.add(symbol)
        dates.add(day)

    unique = len(by_symbol_day)
    dup_ratio = round(1 - unique / total, 4) if total else 0.0
    counts = list(by_symbol_day.values())
    avg_per = round(total / unique, 2) if unique else 0.0
    mx = max(counts) if counts else 0

    print("\n=== Duplicación de señales (signal_outcomes) ===")
    print(f"filas totales                 : {total}")
    print(f"combinaciones (símbolo, día)  : {unique}   <- muestra INDEPENDIENTE efectiva")
    print(f"duplicate_ratio real          : {dup_ratio*100:.1f}%")
    print(f"filas por símbolo-día (media) : {avg_per}   (máx: {mx})")
    print(f"símbolos distintos            : {len(symbols)}")
    print(f"días distintos                : {len(dates)}")
    if dates:
        print(f"rango de fechas               : {min(dates)} -> {max(dates)}")
    print(
        "\nLectura: si los estudios de edge usaron las filas totales como 'N', la N real\n"
        f"independiente es ~{unique} (símbolo-día), no {total}. Eso reduce drásticamente la\n"
        "potencia estadística (intervalos de confianza mucho más anchos de lo que el conteo\n"
        "sugería). Refuerza la conclusión: no promover edges sin más DÍAS/regímenes."
    )


if __name__ == "__main__":
    main()
