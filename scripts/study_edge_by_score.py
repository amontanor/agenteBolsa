"""Estudio de edge forward por SCORE, calidad y extension (24-jun-2026).

Motivacion: el shadow A2 mostro que la taxonomia `setup_quality` es degenerada
(87% de los candidatos caen en `confirmed_pattern|strong`), asi que el sesgo por
setup tiene poco recorrido. Este script busca el edge en dimensiones que SI
discriminan, sobre el historico real de `signal_outcomes`:

  1. por bucket de `score` (el ranking actual ordena por score: ¿predice?),
  2. por `setup_quality` (para cuantificar la degeneracion),
  3. por extension `return_20d` (hipotesis: los lideres mas extendidos revierten).

Es SOLO lectura: abre la BD en modo read-only y no toca nada. Imprime tablas y
escribe `data/reports/edge_by_score_study.json`.

Uso:
    .\.venv\Scripts\python.exe scripts\study_edge_by_score.py
    .\.venv\Scripts\python.exe scripts\study_edge_by_score.py --horizon return_5d --train-days 0 --min-samples 30
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from agente_bolsa._utils import sqlite_connect_ro, table_exists, to_float
from agente_bolsa.config import get_settings


def _loads(raw) -> dict:
    try:
        v = json.loads(raw or "{}")
        return v if isinstance(v, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _bucket(value, edges: list[float], labels: list[str]) -> str:
    if value is None:
        return "n/d"
    for edge, label in zip(edges, labels):
        if value < edge:
            return label
    return labels[-1]


SCORE_EDGES = [8, 10, 12, 14, 16, 18, 1e9]
SCORE_LABELS = ["<8", "8-10", "10-12", "12-14", "14-16", "16-18", ">=18"]

EXT_EDGES = [0.0, 0.05, 0.10, 0.15, 0.20, 1e9]
EXT_LABELS = ["<0%", "0-5%", "5-10%", "10-15%", "15-20%", ">=20%"]


def _summarize(groups: dict[str, list[float]], cost: float, min_samples: int) -> list[dict]:
    rows = []
    for key, vals in groups.items():
        n = len(vals)
        if n == 0:
            continue
        mean = sum(vals) / n
        rows.append(
            {
                "group": key,
                "n": n,
                "mean_gross": round(mean, 6),
                "mean_net": round(mean - cost, 6),
                "median": round(statistics.median(vals), 6),
                "hit_rate": round(sum(1 for v in vals if v > 0) / n, 4),
                "enough_sample": n >= min_samples,
            }
        )
    return sorted(rows, key=lambda r: r["mean_net"], reverse=True)


def _print(title: str, rows: list[dict]) -> None:
    print(f"\n=== {title} ===")
    print(f"{'grupo':<16}{'n':>6}{'media_bruta':>13}{'media_neta':>12}{'mediana':>10}{'hit%':>8}{'muestra':>9}")
    for r in rows:
        print(
            f"{r['group']:<16}{r['n']:>6}{r['mean_gross']*100:>12.2f}%{r['mean_net']*100:>11.2f}%"
            f"{r['median']*100:>9.2f}%{r['hit_rate']*100:>7.1f}%{'ok' if r['enough_sample'] else 'baja':>9}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Edge forward por score/calidad/extension.")
    parser.add_argument("--db", default=None, help="Ruta a la BD (por defecto, la de settings).")
    parser.add_argument("--horizon", default="return_5d", help="Horizonte de outcome (return_3d/5d/10d).")
    parser.add_argument("--train-days", type=int, default=0, help="Ventana en dias (0 = todo el historico).")
    parser.add_argument("--min-samples", type=int, default=30, help="Muestra minima para fiarse de un grupo.")
    parser.add_argument("--cost-bps", type=float, default=15.0, help="Coste roundtrip en bps (neto).")
    args = parser.parse_args()

    settings = get_settings()
    db_path = args.db or str(settings.database_path)
    cost = args.cost_bps / 10000.0

    conn = sqlite_connect_ro(db_path, timeout=30.0)
    try:
        if not table_exists(conn, "signal_outcomes"):
            print("No existe la tabla signal_outcomes.")
            return
        where = ""
        params: tuple = ()
        if args.train_days and args.train_days > 0:
            from datetime import date, timedelta

            start = (date.today() - timedelta(days=args.train_days)).isoformat()
            where = "WHERE signal_date >= ?"
            params = (start,)
        rows = conn.execute(
            f"SELECT signal_date, features_json, outcome_json FROM signal_outcomes {where}", params
        ).fetchall()
    finally:
        conn.close()

    by_score: dict[str, list[float]] = {}
    by_quality: dict[str, list[float]] = {}
    by_ext: dict[str, list[float]] = {}
    by_year_ext: dict[str, dict[str, list[float]]] = {}
    total = 0
    for row in rows:
        if hasattr(row, "keys"):
            sdate, fjson, ojson = row["signal_date"], row["features_json"], row["outcome_json"]
        else:
            sdate, fjson, ojson = row[0], row[1], row[2]
        features = _loads(fjson)
        outcome = _loads(ojson)
        fwd = to_float(outcome.get(args.horizon))
        if fwd is None:
            continue
        total += 1
        score = to_float(features.get("score"))
        quality = str(features.get("setup_quality") or "n/d")
        ext = to_float(features.get("return_20d"))
        ext_bucket = _bucket(ext, EXT_EDGES, EXT_LABELS)
        by_score.setdefault(_bucket(score, SCORE_EDGES, SCORE_LABELS), []).append(fwd)
        by_quality.setdefault(quality, []).append(fwd)
        by_ext.setdefault(ext_bucket, []).append(fwd)
        year = str(sdate or "")[:4]
        if year.isdigit():
            by_year_ext.setdefault(year, {}).setdefault(ext_bucket, []).append(fwd)

    score_rows = _summarize(by_score, cost, args.min_samples)
    quality_rows = _summarize(by_quality, cost, args.min_samples)
    ext_rows = _summarize(by_ext, cost, args.min_samples)

    # Robustez temporal: spread pullback(<0%) - extendido(>=20%) por año.
    # Si el spread es positivo año tras año, el edge de reversion no es un artefacto
    # de un regimen concreto.
    by_year_spread: list[dict] = []
    for year in sorted(by_year_ext):
        pull = by_year_ext[year].get("<0%", [])
        ext_g = by_year_ext[year].get(">=20%", [])
        if len(pull) < args.min_samples or len(ext_g) < args.min_samples:
            continue
        net_pull = sum(pull) / len(pull) - cost
        net_ext = sum(ext_g) / len(ext_g) - cost
        by_year_spread.append(
            {
                "year": year,
                "n_pull": len(pull),
                "net_pull": round(net_pull, 6),
                "n_ext": len(ext_g),
                "net_ext": round(net_ext, 6),
                "spread": round(net_pull - net_ext, 6),
            }
        )

    print(f"\nMuestras con outcome {args.horizon}: {total}  |  coste neto: {args.cost_bps} bps")
    _print("Edge por bucket de SCORE", score_rows)
    _print("Edge por setup_quality (degeneracion)", quality_rows)
    _print("Edge por extension return_20d (reversion)", ext_rows)

    print(f"\n=== Robustez por año: spread pullback(<0%) menos extendido(>=20%) [{args.horizon}] ===")
    print(f"{'anio':<8}{'n_pull':>8}{'neto_pull':>11}{'n_ext':>8}{'neto_ext':>11}{'spread':>10}")
    for r in by_year_spread:
        print(
            f"{r['year']:<8}{r['n_pull']:>8}{r['net_pull']*100:>10.2f}%"
            f"{r['n_ext']:>8}{r['net_ext']*100:>10.2f}%{r['spread']*100:>9.2f}%"
        )

    out = {
        "horizon": args.horizon,
        "train_days": args.train_days,
        "cost_bps": args.cost_bps,
        "samples": total,
        "by_score": score_rows,
        "by_setup_quality": quality_rows,
        "by_extension_return_20d": ext_rows,
        "by_year_pullback_vs_extended_spread": by_year_spread,
    }
    reports_dir = settings.data_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "edge_by_score_study.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=True), encoding="utf-8"
    )
    print(f"\nReporte: {reports_dir / 'edge_by_score_study.json'}")


if __name__ == "__main__":
    main()
