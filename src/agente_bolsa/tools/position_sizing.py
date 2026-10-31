"""Deterministic position sizing for LLM trade recommendations."""

from __future__ import annotations

import math
from decimal import ROUND_DOWN, Decimal

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


def _short_position_market_value(portfolio: PortfolioSnapshot, symbol: str) -> float:
    symbol = symbol.upper()
    total = 0.0
    for position in portfolio.positions:
        if position.symbol.upper() != symbol:
            continue
        side = str(position.side or "long").lower()
        if side == "short" or float(position.qty or 0.0) < 0:
            total += abs(float(position.market_value or 0.0))
    return total


def recommended_short_notional(
    settings: Settings,
    portfolio: PortfolioSnapshot,
    recommendation: TradeRecommendation,
    *,
    sizing_adjustment: dict[str, float] | None = None,
) -> tuple[float, dict[str, float]]:
    """Calculate a capped notional for a short entry.

    Shorts are integer-share only and never add to an existing short. The
    broker's buying power remains the authoritative margin authority; the
    kernel and ``risk.py`` keep the absolute caps.
    """

    entry = recommendation.entry_price or 0
    stop = recommendation.stop_loss or 0
    if entry <= 0 or stop <= entry:
        return 0.0, {"reason_code": 0.0, "reason": "invalid_short_geometry"}

    risk_per_dollar = (stop - entry) / entry
    if risk_per_dollar <= 0:
        return 0.0, {"reason_code": 0.0}

    equity = float(portfolio.portfolio_value or 0.0)
    if equity <= 0:
        return 0.0, {"reason": "invalid_equity"}

    if _short_position_market_value(portfolio, recommendation.symbol) > 0:
        return 0.0, {"reason": "short_adds_disabled"}

    max_risk_notional = (equity * float(settings.max_short_risk_per_trade)) / risk_per_dollar
    max_position_notional = equity * float(settings.max_short_position_exposure)
    target_exposure = recommendation.target_exposure_pct or float(settings.max_short_position_exposure)
    target_notional = equity * min(float(target_exposure), float(settings.max_short_position_exposure))

    adjustment = sizing_adjustment or {}
    try:
        multiplier = 1.0 if adjustment.get("size_multiplier") is None else float(adjustment["size_multiplier"])
    except (TypeError, ValueError, OverflowError):
        return 0.0, {"reason": "invalid_size_multiplier"}
    if not math.isfinite(multiplier):
        return 0.0, {"reason": "invalid_size_multiplier"}
    multiplier = min(1.0, max(0.0, multiplier))

    available_buying_power = max(0.0, float(portfolio.buying_power or 0.0))
    notional = min(
        max_risk_notional,
        target_notional * multiplier,
        max_position_notional,
        available_buying_power,
    )
    notional = _floor_currency(max(0.0, notional))
    qty = math.floor(notional / entry) if entry > 0 else 0
    if qty <= 0:
        return 0.0, {"reason": "quantity_below_one_share", "requested_notional": notional}
    integer_notional = _floor_currency(qty * entry)
    if integer_notional < float(settings.min_order_notional):
        return 0.0, {
            "reason": "below_min_order_notional",
            "integer_notional": integer_notional,
            "min_order_notional": float(settings.min_order_notional),
        }
    return integer_notional, {
        "reason_code": 1.0,
        "max_risk_notional": round(max_risk_notional, 2),
        "max_position_notional": round(max_position_notional, 2),
        "target_notional": round(target_notional, 2),
        "buying_power_cap": round(available_buying_power, 2),
        "size_multiplier": multiplier,
        "qty": qty,
        "risk_per_dollar": round(risk_per_dollar, 6),
    }


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
    raw_multiplier = adjustment.get("size_multiplier")
    try:
        multiplier = 1.0 if raw_multiplier is None else float(raw_multiplier)
    except (TypeError, ValueError, OverflowError):
        multiplier = 0.0
    if not math.isfinite(multiplier):
        multiplier = 0.0
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
