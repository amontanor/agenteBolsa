"""Modelo de costes de trading (puro) para evaluar edge NETO.

El edge medido sobre retornos forward es BRUTO. Antes de promocionar cualquier
política hay que restar el coste round-trip realista (comisión + slippage + cruce
de spread, en bps). Este módulo es puro y sin dependencias: lo usan los estudios
offline y, más adelante, el modelado de decisiones.

Defaults conservadores para US equities en Alpaca paper:
- comisión: 0 bps (Alpaca es commission-free en equities).
- slippage: 5 bps por lado (entrada y salida).
- spread: 5 bps (se cruza media horquilla al entrar y media al salir ~= 1 spread).

Round-trip por defecto = 2*0 + 2*5 + 5 = 15 bps = 0.0015 (0,15%).
"""
from __future__ import annotations

DEFAULT_COMMISSION_BPS = 0.0
DEFAULT_SLIPPAGE_BPS = 5.0
DEFAULT_SPREAD_BPS = 5.0


def round_trip_cost_fraction(
    *,
    commission_bps: float = DEFAULT_COMMISSION_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    spread_bps: float = DEFAULT_SPREAD_BPS,
) -> float:
    """Coste round-trip (entrada+salida) como fracción del precio.

    Comisión y slippage se pagan en ambos lados (x2); el spread se cruza una vez
    en total (media horquilla al entrar + media al salir).
    """
    total_bps = 2.0 * float(commission_bps) + 2.0 * float(slippage_bps) + float(spread_bps)
    return max(0.0, total_bps) / 10000.0


def net_return(
    gross_return: float,
    *,
    commission_bps: float = DEFAULT_COMMISSION_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    spread_bps: float = DEFAULT_SPREAD_BPS,
) -> float:
    """Retorno neto de costes: bruto menos el coste round-trip."""
    return float(gross_return) - round_trip_cost_fraction(
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
        spread_bps=spread_bps,
    )
