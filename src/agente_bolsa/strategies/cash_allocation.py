"""Cash como posicion activa (T5.7).

Estar fuera del mercado pasa a ser una decision. Esta pseudo-estrategia emite a
diario un `target_cash_pct` segun el regimen de mercado, la tesis y el drawdown
rodante. `portfolio_optimizer` la respeta como restriccion dura: no comprar si la
caja objetivo no lo permite; vender lo mas debil si se excede.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - solo anotaciones.
    from ..config import Settings


def target_cash_pct(
    settings: "Settings",
    *,
    regime: str | None = None,
    stance: str | None = None,
    drawdown_pct: float | None = None,
) -> float:
    """Fraccion de caja objetivo [0,1] segun regimen/tesis/drawdown."""

    floor_risk_off = float(getattr(settings, "cash_floor_risk_off", 0.60))
    floor_neutral = float(getattr(settings, "cash_floor_neutral", 0.25))

    regime = str(regime or "").lower()
    stance = str(stance or "").lower()

    if stance == "risk_off" or regime in {"bearish", "bear", "down"}:
        target = floor_risk_off
    elif stance == "neutral" or regime in {"range", "neutral", "sideways", "lateral"}:
        target = floor_neutral
    else:  # risk_on / alcista
        target = 0.0

    # Escalado por drawdown rodante: cuanto peor, mas caja (reducir riesgo).
    if isinstance(drawdown_pct, (int, float)):
        dd = abs(float(drawdown_pct))
        if dd > 0.15:
            target = max(target, 0.50)
        elif dd > 0.10:
            target = max(target, 0.35)
    return round(max(0.0, min(1.0, target)), 4)


def enforce_cash_floor(
    buy_plans: list[Any],
    *,
    cash_pct: float,
    target_cash_pct_value: float,
) -> tuple[list[Any], dict[str, Any]]:
    """Filtra compras si violan la caja objetivo (restriccion dura, T5.7).

    Si la caja disponible ya esta por debajo del objetivo, no se permiten compras
    nuevas. Devuelve (compras_permitidas, info).
    """

    if cash_pct <= target_cash_pct_value:
        return [], {"blocked_buys": len(buy_plans), "reason": "cash_below_floor", "cash_pct": cash_pct, "target": target_cash_pct_value}
    return buy_plans, {"blocked_buys": 0, "cash_pct": cash_pct, "target": target_cash_pct_value}
