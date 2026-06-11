"""Realismo de ejecucion: slippage, limit orders y calibracion de costes (T5.5).

Que el paper deje de mentir: fills castigados, gaps controlados y costes
calibrados con fills reales. Funciones puras y testables; `execution.py`,
`trade_decision.py` y `signal_learning.py` las invocan.
"""

from __future__ import annotations

import statistics
from typing import Any


def apply_synthetic_slippage(
    gross_return: float,
    *,
    slippage_bps: float = 10.0,
    atr_pct: float | None = None,
) -> float:
    """Penaliza un retorno bruto con slippage adverso (round-trip) — T5.5.

    Resta el slippage en ambos lados (entrada y salida) mas media horquilla
    estimada por ATR si se conoce.
    """

    penalty = 2.0 * (float(slippage_bps) / 10_000.0)
    if isinstance(atr_pct, (int, float)):
        penalty += 0.5 * abs(float(atr_pct))
    return round(float(gross_return) - penalty, 6)


def limit_price_with_gap_cap(entry_price: float, *, max_gap_pct: float = 0.015) -> float:
    """Precio limite de compra con techo de gap (T5.5)."""

    return round(float(entry_price) * (1.0 + float(max_gap_pct)), 4)


def gap_exceeds_cap(open_price: float, entry_price: float, *, max_gap_pct: float = 0.015) -> bool:
    """True si el gap de apertura supera el techo (la orden limit no se llena)."""

    if entry_price <= 0:
        return False
    return (float(open_price) - float(entry_price)) / float(entry_price) > float(max_gap_pct)


def calibrate_cost_bps(fills: list[dict[str, Any]]) -> dict[str, Any]:
    """Calibra los bps de coste comparando fills reales vs precio teorico (T5.5).

    Cada fill: {signal_price, fill_price, side}. Devuelve la mediana del coste
    implicito en bps (adverso = fill peor que la senal).
    """

    bps_samples: list[float] = []
    for fill in fills:
        signal = fill.get("signal_price")
        actual = fill.get("fill_price")
        side = str(fill.get("side") or "buy").lower()
        if not isinstance(signal, (int, float)) or not isinstance(actual, (int, float)) or signal <= 0:
            continue
        slip = (actual - signal) / signal if side == "buy" else (signal - actual) / signal
        bps_samples.append(slip * 10_000.0)
    if not bps_samples:
        return {"samples": 0, "median_bps": None, "mean_bps": None}
    return {
        "samples": len(bps_samples),
        "median_bps": round(statistics.median(bps_samples), 2),
        "mean_bps": round(statistics.fmean(bps_samples), 2),
    }
