"""Estudio (solo lectura): edge actual por setup / regimen.

Objetivo: confirmar que confirmed_pattern tiene edge negativo y localizar que
setups tienen edge positivo HOY, para reorientar la generacion de candidatos.

Como el campo features.setup_name suele venir null, agrupamos por proxies
robustos: presencia de patron alcista confirmado, calidad de setup y regimen.
Imprime tambien cobertura de campos para poder afinar el agrupador con datos.

Uso:
    python scripts/study_setup_edge.py [ruta_db] [dias_ventana]

Por defecto: data/state/agente_bolsa.sqlite3, ventana 120 dias. No escribe nada.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from statistics import mean

DEFAULT_DB = Path("data/state/agente_bolsa.sqlite3")
HORIZONS = ("return_1d", "return_3d", "return_5d", "return_10d")


def _loads(raw):
    try:
        v = json.loads(raw or "{}")
        return v if isinstance(v, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _summary(returns):
    if not returns:
        return {"n": 0}
    from agente_bolsa.tools.trade_costs import net_return

    wins = [r for r in returns if r > 0]
    losses = [-r for r in returns if r < 0]
    pf = (sum(wins) / sum(losses)) if losses else float("inf")
    nets = [net_return(r) for r in returns]
    return {
        "n": len(returns),
        "mean": round(mean(returns), 4),
        "hit": round(len(wins) / len(returns), 3),
        "pf": round(pf, 3) if pf != float("inf") else "inf",
        "net_mean": round(mean(nets), 4),
    }


def _setup_key(feats: dict) -> str:
    name = str(feats.get("setup_name") or "").strip()
    if name and name.lower() != "null":
        return name
    patterns = feats.get("chart_patterns") or {}
    confirmed = _f(patterns.get("bullish_confirmed_count")) or 0.0
    quality = str(feats.get("setup_quality") or "n/d")
    return f"{'confirmed_pattern' if confirmed >= 1 else 'sin_patron'}|{quality}"


def main() -> int:
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
    window_days = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    if not db.exists():
        print(f"DB no encontrada: {db}")
        return 2
    since = (date.today() - timedelta(days=window_days)).isoformat()
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)
    con.execute("PRAGMA query_only=ON")
    con.row_factory = sqlite3.Row

    rows = con.execute(
        """
        SELECT signal_date, features_json, outcome_json
        FROM signal_outcomes
        WHERE signal_date >= ? AND outcome_json IS NOT NULL
        """,
        (since,),
    ).fetchall()

    by_setup: dict[str, list[float]] = {}
    by_regime: dict[str, list[float]] = {}
    field_cov: Counter = Counter()
    matured = 0
    for r in rows:
        outcome = _loads(r["outcome_json"])
        feats = _loads(r["features_json"])
        r5 = _f(outcome.get("return_5d"))
        if r5 is None:
            continue
        matured += 1
        for k in ("setup_name", "setup_quality", "market_regime"):
            if feats.get(k) not in (None, "", "null"):
                field_cov[k] += 1
        if (feats.get("chart_patterns") or {}).get("bullish_confirmed_count") is not None:
            field_cov["chart_patterns.bullish_confirmed_count"] += 1
        by_setup.setdefault(_setup_key(feats), []).append(r5)
        by_regime.setdefault(str(feats.get("market_regime") or "unknown"), []).append(r5)

    print(f"DB: {db}  ventana desde {since}")
    print(f"senales con return_5d maduro: {matured}\n")
    print(f"cobertura de campos (sobre {matured}): {dict(field_cov)}\n")
    print("Edge por setup (return_5d), de mejor a peor:")
    for key, vals in sorted(by_setup.items(), key=lambda kv: -(mean(kv[1]) if kv[1] else 0)):
        if len(vals) >= 5:
            print(f"  {key:34} {_summary(vals)}")
    print("\nEdge por regimen (return_5d):")
    for key, vals in sorted(by_regime.items(), key=lambda kv: -len(kv[1])):
        print(f"  {key:16} {_summary(vals)}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
