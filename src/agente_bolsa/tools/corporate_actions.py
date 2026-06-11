"""Huecos operativos: earnings en holds, splits, dividendos y halts (T5.10).

Cierra fuentes de perdidas raras-pero-grandes que el hit rate no detecta:
- posiciones ABIERTAS que atraviesan earnings sin decision explicita,
- outcomes distorsionados por splits/dividendos,
- simbolos con datos congelados (posible halt).

Funciones puras y testables; el scheduler/signal_learning las invocan.
"""

from __future__ import annotations

from typing import Any


def earnings_hold_decision(
    *,
    unrealized_pnl: float | None,
    days_to_earnings: int | None,
    policy: str = "reduce",
    max_days: int = 2,
) -> dict[str, Any]:
    """Decision determinista para una posicion abierta ante earnings cercanos.

    Por defecto (`reduce`): reducir 50% o cerrar si el PnL no realizado es < 0.
    """

    if days_to_earnings is None or days_to_earnings > max_days:
        return {"action": "hold", "qty_factor": 1.0, "reason": "earnings lejos o desconocidos"}
    policy = str(policy or "reduce").lower()
    if policy == "hold":
        return {"action": "hold", "qty_factor": 1.0, "reason": "politica hold"}
    if policy == "exit":
        return {"action": "exit", "qty_factor": 0.0, "reason": "politica exit ante earnings"}
    # reduce (default)
    if isinstance(unrealized_pnl, (int, float)) and unrealized_pnl < 0:
        return {"action": "exit", "qty_factor": 0.0, "reason": "earnings con PnL negativo: cerrar"}
    return {"action": "reduce", "qty_factor": 0.5, "reason": "earnings cercanos: reducir 50%"}


def detect_split_factor(prev_close: float, new_price: float, *, jump_threshold: float = 0.40) -> float | None:
    """Detecta el factor de split si el salto de precio supera el umbral.

    Devuelve el factor (p. ej. 2.0 para 2:1, 0.5 para reverse 1:2) o None.
    """

    if prev_close <= 0 or new_price <= 0:
        return None
    change = abs(new_price - prev_close) / prev_close
    if change < jump_threshold:
        return None
    ratio = prev_close / new_price
    for factor in (2.0, 3.0, 4.0, 5.0, 10.0, 0.5, 1 / 3, 0.25, 0.1):
        if abs(ratio - factor) / factor <= 0.10:
            return round(factor, 4)
    return None


def adjust_outcome_for_split(
    outcome: dict[str, Any],
    *,
    prev_close: float,
    new_price: float,
) -> dict[str, Any]:
    """Corrige un outcome por split: ajusta el return y marca la accion corporativa."""

    factor = detect_split_factor(prev_close, new_price)
    if factor is None:
        return outcome
    adjusted = dict(outcome)
    ret = outcome.get("return_pct")
    if isinstance(ret, (int, float)):
        # Un 2:1 produce un -50% espurio; al multiplicar el precio por el factor
        # el retorno real se recupera: (new*factor - prev)/prev.
        adjusted["return_pct"] = round((new_price * factor - prev_close) / prev_close, 6)
    adjusted["corporate_action_adjusted"] = 1
    adjusted["split_factor"] = factor
    return adjusted


def apply_dividend(outcome: dict[str, Any], *, dividend_per_share: float, entry_price: float) -> dict[str, Any]:
    """Suma el dividendo recibido en la ventana al return del outcome."""

    if dividend_per_share <= 0 or entry_price <= 0:
        return outcome
    adjusted = dict(outcome)
    ret = float(outcome.get("return_pct") or 0.0)
    adjusted["return_pct"] = round(ret + dividend_per_share / entry_price, 6)
    adjusted["dividend_adjusted"] = 1
    return adjusted


def detect_halt(sessions_without_bar: int, *, threshold: int = 2) -> bool:
    """True si el simbolo no imprime barra nueva en `threshold` sesiones (T5.10)."""

    return int(sessions_without_bar) >= int(threshold)
