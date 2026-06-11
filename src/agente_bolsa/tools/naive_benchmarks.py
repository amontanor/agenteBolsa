"""Benchmarks ingenuos y validacion de edge base (T5.1).

Para afirmar con un numero si la estrategia semilla tiene edge ANTES de dejar
que la autonomia la optimice, comparamos su PnL diario contra dos benchmarks
baratos: comprar y mantener SPY, y un momentum trivial (top-5 por return_20d con
rebalanceo semanal). El edge_report calcula el t-stat de los retornos
diferenciales y emite un veredicto.

La descarga de precios es inyectable/best-effort; el calculo del t-stat es
stdlib puro y testeable.
"""

from __future__ import annotations

import math
import statistics
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:  # pragma: no cover - solo anotaciones.
    from ..config import Settings


def compute_daily_benchmarks(
    settings: "Settings",
    session_date: str,
    *,
    spy_pct: float | None = None,
    momentum_pct: float | None = None,
    price_fetcher: Callable[[list[str], str], dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Retornos diarios de los benchmarks. Best-effort: degrada a None.

    Si se pasan `spy_pct`/`momentum_pct` (tests o pipeline) se usan tal cual; si
    no, se intenta calcular con `price_fetcher`; ante cualquier fallo, None.
    """

    result: dict[str, Any] = {"spy_buy_hold_pct": spy_pct, "naive_momentum_pct": momentum_pct, "quality": "provided"}
    if spy_pct is not None or momentum_pct is not None:
        return result
    if price_fetcher is None:
        return {"spy_buy_hold_pct": None, "naive_momentum_pct": None, "quality": "no_fetcher"}
    try:
        # El fetcher devuelve {symbol: daily_return}; el momentum ingenuo es la
        # media de los 5 mayores retornos disponibles (proxy del top-5 rebalanceado).
        returns = price_fetcher(["SPY"], session_date)
        spy = returns.get("SPY")
        universe_returns = price_fetcher([], session_date)  # universo del dia
        ranked = sorted((v for v in universe_returns.values() if isinstance(v, (int, float))), reverse=True)
        momentum = statistics.fmean(ranked[:5]) if len(ranked) >= 5 else None
        return {"spy_buy_hold_pct": spy, "naive_momentum_pct": momentum, "quality": "computed"}
    except Exception as exc:  # noqa: BLE001 - degradacion controlada.
        return {"spy_buy_hold_pct": None, "naive_momentum_pct": None, "quality": f"error:{type(exc).__name__}"}


def _t_stat(diffs: list[float]) -> float | None:
    clean = [d for d in diffs if isinstance(d, (int, float))]
    if len(clean) < 2:
        return None
    stdev = statistics.stdev(clean)
    if stdev == 0:
        return None
    mean = statistics.fmean(clean)
    return round((mean / (stdev / math.sqrt(len(clean)))), 4)


def _verdict(t_stat: float | None) -> str:
    if t_stat is None:
        return "NO_EDGE"
    if t_stat > 2.0:
        return "EDGE_CONFIRMED"
    if t_stat >= 1.0:
        return "EDGE_WEAK"
    return "NO_EDGE"


def edge_report(store: Any, sessions: int = 60) -> dict[str, Any]:
    """Veredicto de edge base vs SPY y vs momentum ingenuo (T5.1)."""

    rows = store.performance_daily(limit=0)[-sessions:]
    pnl = [r.get("pnl_pct") for r in rows]
    spy = [r.get("spy_pct") for r in rows]
    naive = [((r.get("payload") or {}).get("benchmarks") or {}).get("naive_momentum_pct") for r in rows]

    diff_spy = [
        p - s
        for p, s in zip(pnl, spy)
        if isinstance(p, (int, float)) and isinstance(s, (int, float))
    ]
    diff_naive = [
        p - n
        for p, n in zip(pnl, naive)
        if isinstance(p, (int, float)) and isinstance(n, (int, float))
    ]

    t_spy = _t_stat(diff_spy)
    t_naive = _t_stat(diff_naive)
    # El veredicto se rige por el benchmark mas exigente disponible (momentum).
    governing_t = t_naive if t_naive is not None else t_spy
    return {
        "sessions": len(rows),
        "alpha_vs_spy": round(sum(diff_spy), 6) if diff_spy else None,
        "alpha_vs_naive_momentum": round(sum(diff_naive), 6) if diff_naive else None,
        "t_stat_vs_spy": t_spy,
        "t_stat_vs_naive_momentum": t_naive,
        "verdict": _verdict(governing_t),
    }
