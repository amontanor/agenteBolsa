"""Shadow walk-forward (solo lectura): ¿reorientar hacia setups con edge positivo
mejora la expectativa FUERA DE MUESTRA?

Antes de cablear ningun cambio de estrategia, esto responde con datos y sin riesgo:
1. Divide el historico por fecha en TRAIN (antiguo) y TEST (reciente).
2. Calcula el edge por setup SOLO con TRAIN (`edge_table`).
3. En TEST (out-of-sample) compara la expectativa forward (return_5d) de:
   - todas las senales,
   - el sesgo actual del sistema (confirmed_pattern),
   - una politica que selecciona setups con edge positivo en TRAIN,
   - lo que el sistema aprobo realmente.
Si la politica "setups buenos por TRAIN" bate a confirmed_pattern en TEST y el signo
del edge se mantiene, reorientar esta justificado (y no es sobreajuste). Si no, NO.

Uso:
    python scripts/shadow_setup_edge_reweight.py [ruta_db] [train_frac] [min_n_train]

Defaults: data/state/agente_bolsa.sqlite3, train_frac=0.7, min_n_train=200.
No escribe nada.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from statistics import mean

from agente_bolsa.tools.setup_edge import setup_quality_key

import json

DEFAULT_DB = Path("data/state/agente_bolsa.sqlite3")
APPROVED = {
    "approved_buy", "approved_buy_micro", "approved_buy_soft_backtest",
    "executed_buy", "executed_buy_micro",
}


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


def _summary(returns: list[float]) -> dict:
    if not returns:
        return {"n": 0}
    from agente_bolsa.tools.trade_costs import net_return

    wins = [r for r in returns if r > 0]
    losses = [-r for r in returns if r < 0]
    pf = (sum(wins) / sum(losses)) if losses else float("inf")
    nets = [net_return(r) for r in returns]
    nwins = [r for r in nets if r > 0]
    nlosses = [-r for r in nets if r < 0]
    npf = (sum(nwins) / sum(nlosses)) if nlosses else float("inf")
    return {
        "n": len(returns),
        "mean": round(mean(returns), 4),
        "hit": round(len(wins) / len(returns), 3),
        "pf": round(pf, 3) if pf != float("inf") else "inf",
        "net_mean": round(mean(nets), 4),
        "net_pf": round(npf, 3) if npf != float("inf") else "inf",
    }


def main() -> int:
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
    train_frac = float(sys.argv[2]) if len(sys.argv) > 2 else 0.7
    min_n_train = int(sys.argv[3]) if len(sys.argv) > 3 else 200
    if not db.exists():
        print(f"DB no encontrada: {db}")
        return 2
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)
    con.execute("PRAGMA query_only=ON")
    con.row_factory = sqlite3.Row

    rows = []
    for r in con.execute(
        "SELECT signal_date, decision, features_json, outcome_json "
        "FROM signal_outcomes WHERE outcome_json IS NOT NULL"
    ):
        ret5 = _f(_loads(r["outcome_json"]).get("return_5d"))
        if ret5 is None:
            continue
        rows.append((
            str(r["signal_date"]),
            str(r["decision"] or ""),
            setup_quality_key(_loads(r["features_json"])),
            ret5,
        ))
    con.close()

    if not rows:
        print("Sin filas maduras (return_5d).")
        return 1

    dates = sorted({d for d, _, _, _ in rows})
    split_at = dates[int(len(dates) * train_frac)] if len(dates) > 1 else dates[0]
    train = [x for x in rows if x[0] < split_at]
    test = [x for x in rows if x[0] >= split_at]

    # edge_table desde TRAIN
    by_key_train: dict[str, list[float]] = {}
    for _d, _dec, key, ret in train:
        by_key_train.setdefault(key, []).append(ret)
    edge_table = {k: mean(v) for k, v in by_key_train.items() if len(v) >= min_n_train}
    good = {k for k, v in edge_table.items() if v > 0}

    # politicas evaluadas en TEST (out-of-sample)
    all_test = [ret for _d, _dec, _k, ret in test]
    confirmed = [ret for _d, _dec, k, ret in test if k.startswith("confirmed_pattern")]
    good_policy = [ret for _d, _dec, k, ret in test if k in good]
    approved = [ret for _d, _dec, k, ret in test if _dec in APPROVED]

    by_key_test: dict[str, list[float]] = {}
    for _d, _dec, key, ret in test:
        by_key_test.setdefault(key, []).append(ret)

    print(f"DB: {db}")
    print(f"fechas: {dates[0]} .. {dates[-1]}  | split TRAIN<{split_at}<=TEST")
    print(f"filas TRAIN={len(train)}  TEST={len(test)}\n")
    print(f"edge_table (TRAIN, min_n={min_n_train}): "
          + ", ".join(f"{k}={v:+.4f}" for k, v in sorted(edge_table.items(), key=lambda kv: -kv[1])))
    print(f"setups 'buenos' por TRAIN (edge>0): {sorted(good)}\n")
    print("Expectativa OUT-OF-SAMPLE (TEST, return_5d):")
    print(f"  todas                       {_summary(all_test)}")
    print(f"  sesgo actual (confirmed)    {_summary(confirmed)}")
    print(f"  politica setups-buenos      {_summary(good_policy)}")
    print(f"  aprobado realmente          {_summary(approved)}")
    print("\nPersistencia del edge por setup (TEST):")
    for key, vals in sorted(by_key_test.items(), key=lambda kv: -(mean(kv[1]) if kv[1] else 0)):
        if len(vals) >= 30:
            train_edge = edge_table.get(key)
            tag = "" if train_edge is None else f"  (train {train_edge:+.4f})"
            print(f"  {key:30} {_summary(vals)}{tag}")
    print("\nVeredicto: reorientar esta justificado si 'politica setups-buenos' bate a")
    print("'sesgo actual (confirmed)' en TEST y el signo del edge se mantiene train->test.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
