"""Estudio (solo lectura): ¿el backtest gate bloquea edge bueno o malo?

Mide la expectativa forward de los candidatos que fallaron el backtest gate
UNICAMENTE por estabilidad de regimen ("regimenes negativos N > maximo M"),
no por hit-rate/PF/drawdown/alpha. Si la expectativa es positiva, abrir la
micro-valvula (tamano 0.5x, medido) esta justificado; si es negativa, el gate
acierta y el problema es el universo de setups.

Uso:
    python scripts/study_near_miss_shadow.py [ruta_db]

Por defecto usa data/state/agente_bolsa.sqlite3 en modo solo-lectura.
No escribe nada.
"""
from __future__ import annotations

import json
import sqlite3
import sys
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


def _summarize(returns: list[float]) -> dict:
    if not returns:
        return {"n": 0}
    wins = [r for r in returns if r > 0]
    losses = [-r for r in returns if r < 0]
    pf = (sum(wins) / sum(losses)) if losses else float("inf")
    return {
        "n": len(returns),
        "mean": round(mean(returns), 4),
        "hit_rate": round(len(wins) / len(returns), 3),
        "profit_factor": round(pf, 3) if pf != float("inf") else "inf",
    }


def main() -> int:
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
    if not db.exists():
        print(f"DB no encontrada: {db}")
        return 2
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)
    con.execute("PRAGMA query_only=ON")
    con.row_factory = sqlite3.Row

    rows = con.execute(
        """
        SELECT signal_date, features_json, gate_json, outcome_json
        FROM signal_outcomes
        WHERE decision = 'blocked_backtest'
          AND coalesce(source, '') != 'lab_book'
        """
    ).fetchall()

    by_h: dict[str, list[float]] = {h: [] for h in HORIZONS}
    by_regime: dict[str, list[float]] = {}
    total = 0
    regime_only = 0
    for r in rows:
        total += 1
        gate = _loads(r["gate_json"])
        reason = str((gate.get("backtest_gate") or {}).get("reason") or "")
        if "regimenes negativos" not in reason:
            continue  # bloqueado por otra causa (hit-rate/PF/drawdown/alpha) -> excluir
        regime_only += 1
        outcome = _loads(r["outcome_json"])
        feats = _loads(r["features_json"])
        regime = str(feats.get("market_regime") or "unknown")
        r5 = _f(outcome.get("return_5d"))
        for h in HORIZONS:
            v = _f(outcome.get(h))
            if v is not None:
                by_h[h].append(v)
        if r5 is not None:
            by_regime.setdefault(regime, []).append(r5)

    print(f"DB: {db}")
    print(f"blocked_backtest total: {total}")
    print(f"bloqueados SOLO por estabilidad de regimen: {regime_only}\n")
    print("Expectativa forward de esos candidatos (si los hubieramos dejado entrar):")
    for h in HORIZONS:
        print(f"  {h:12} {_summarize(by_h[h])}")
    print("\nPor regimen (return_5d):")
    for regime, vals in sorted(by_regime.items(), key=lambda kv: -len(kv[1])):
        print(f"  {regime:16} {_summarize(vals)}")
    print("\nLectura: si mean/hit-rate/PF son claramente positivos (y n suficiente),")
    print("abrir la micro-valvula esta justificado. Si no, el gate acierta.")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
