"""Deterministic position sizing for LLM trade recommendations."""

from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

from agente_bolsa.config import Settings
from agente_bolsa.models import PortfolioSnapshot, TradeRecommendation


def _position_market_value(portfolio: PortfolioSnapshot, symbol: str) -> float:
    symbol = symbol.upper()
    return sum(
        position.market_value
        for position in portfolio.positions
        if position.symbol.upper() == symbol
    )


def _floor_currency(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_DOWN))


def recommended_notional(
    settings: Settings,
    portfolio: PortfolioSnapshot,
    recommendation: TradeRecommendation,
    *,
    sizing_adjustment: dict[str, float] | None = None,
) -> tuple[float, dict[str, float]]:
    """Calculate a capped notional size for a recommendation."""

    entry = recommendation.entry_price or 0
    stop = recommendation.stop_loss or 0
    if entry <= 0 or stop <= 0:
        return 0.0, {"reason_code": 0.0}

    risk_per_dollar = abs(entry - stop) / entry
    if risk_per_dollar <= 0:
        return 0.0, {"reason_code": 0.0}

    max_risk_notional = (portfolio.portfolio_value * settings.max_risk_per_trade) / risk_per_dollar
    max_position_notional = portfolio.portfolio_value * settings.max_position_exposure
    target_exposure = recommendation.target_exposure_pct or settings.max_position_exposure
    target_notional = portfolio.portfolio_value * min(
        target_exposure,
        settings.max_position_exposure,
    )
    current_notional = _position_market_value(portfolio, recommendation.symbol)
    if current_notional > 0 and not settings.allow_position_adds:
        return 0.0, {
            "reason": "position_adds_disabled",
            "current_notional": round(current_notional, 2),
            "allow_position_adds": 0.0,
        }

    available_position_room = max(0.0, max_position_notional - current_notional)
    available_buying_power = max(0.0, portfolio.buying_power)

    adjustment = sizing_adjustment or {}
    multiplier = float(adjustment.get("size_multiplier") or 1.0)
    if multiplier < 0:
        multiplier = 0.0
    multiplier = min(1.15, multiplier)
    adjusted_target_notional = target_notional * multiplier
    notional = min(
        max_risk_notional,
        adjusted_target_notional,
        available_position_room,
        available_buying_power,
    )
    conservative_notional = _floor_currency(max(0.0, notional))
    if conservative_notional < settings.min_order_notional:
        return 0.0, {
            "reason": "below_min_order_notional",
            "calculated_notional": conservative_notional,
            "min_order_notional": round(settings.min_order_notional, 2),
            "current_notional": round(current_notional, 2),
            "available_position_room": round(available_position_room, 2),
            "size_multiplier": round(multiplier, 4),
            "target_notional": round(target_notional, 2),
            "adjusted_target_notional": round(adjusted_target_notional, 2),
        }

    return conservative_notional, {
        "risk_per_dollar": round(risk_per_dollar, 6),
        "max_risk_notional": round(max_risk_notional, 2),
        "max_position_notional": round(max_position_notional, 2),
        "target_notional": round(target_notional, 2),
        "adjusted_target_notional": round(adjusted_target_notional, 2),
        "current_notional": round(current_notional, 2),
        "available_position_room": round(available_position_room, 2),
        "available_buying_power": round(available_buying_power, 2),
        "min_order_notional": round(settings.min_order_notional, 2),
        "size_multiplier": round(multiplier, 4),
        "size_adjustment_reason": adjustment.get("reason"),
    }
