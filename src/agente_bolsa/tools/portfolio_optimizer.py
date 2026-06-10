"""Portfolio-level rebalance context for LLM decisions."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.models import PortfolioSnapshot

from .costs import TransactionCostModel


def _round(value: float | int | None, precision: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), precision)


def _candidate_items(technical_context: dict[str, Any]) -> list[dict[str, Any]]:
    if technical_context.get("selected_candidates"):
        candidates = technical_context.get("selected_candidates", [])
    else:
        candidates = [
            *technical_context.get("top_longs", []),
            *technical_context.get("top_shorts", []),
        ]
    seen: set[str] = set()
    result = []
    for candidate in candidates:
        symbol = str(candidate.get("symbol", "")).upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        result.append(candidate)
    return result


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    state = candidate.get("technical_state", {}) or {}
    risk = candidate.get("risk_plan", {}) or {}
    raw_chart_patterns = state.get("chart_patterns") or candidate.get("chart_patterns") or []
    chart_patterns = [
        {
            "pattern": pattern.get("pattern"),
            "label": pattern.get("label"),
            "bias": pattern.get("bias"),
            "status": pattern.get("status"),
            "confidence": pattern.get("confidence"),
        }
        for pattern in raw_chart_patterns[:5]
        if isinstance(pattern, dict)
    ]
    return {
        "symbol": str(candidate.get("symbol", "")).upper(),
        "direction": candidate.get("direction"),
        "score": candidate.get("score", 0),
        "setup_quality": candidate.get("setup_quality"),
        "reasons": candidate.get("reasons", [])[:6],
        "close": state.get("close") or candidate.get("close"),
        "rsi_14": state.get("rsi_14") or candidate.get("rsi_14"),
        "atr_14": state.get("atr_14") or candidate.get("atr_14"),
        "relative_return_20d": state.get("relative_return_20d") or candidate.get("relative_return_20d"),
        "entry_price": risk.get("entry_price") or state.get("close") or candidate.get("close"),
        "stop_loss": risk.get("stop_loss"),
        "take_profit": risk.get("take_profit"),
        "reward_risk": risk.get("reward_risk", 1.5),
        "chart_patterns": chart_patterns,
        "candlestick_patterns": (state.get("candle_patterns") or candidate.get("candlestick_patterns") or [])[:5],
    }


def _sentiment_map(sentiment_context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in sentiment_context.get("results", []):
        symbol = str(item.get("symbol", "")).upper()
        if not symbol:
            continue
        sentiment = item.get("sentiment", {}) or {}
        result[symbol] = {
            "sentiment": sentiment.get("sentiment"),
            "sentiment_score": sentiment.get("sentiment_score"),
            "supports_technical_setup": sentiment.get("supports_technical_setup"),
            "confidence": sentiment.get("confidence"),
            "risk_flags": sentiment.get("risk_flags", []),
        }
    return result


def _position_summary(portfolio: PortfolioSnapshot, symbol_scores: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for position in portfolio.positions:
        exposure = position.market_value / portfolio.portfolio_value if portfolio.portfolio_value else 0
        technical = symbol_scores.get(position.symbol.upper(), {})
        result.append(
            {
                "symbol": position.symbol.upper(),
                "qty": position.qty,
                "market_value": _round(position.market_value, 2),
                "exposure_pct": _round(exposure, 4),
                "avg_entry_price": _round(position.avg_entry_price, 4),
                "current_price": _round(position.current_price, 4),
                "unrealized_pl": _round(position.unrealized_pl, 2),
                "unrealized_plpc": _round(position.unrealized_plpc, 4),
                "drawdown_from_entry": _round(min(0.0, position.unrealized_plpc), 4),
                "technical_score": technical.get("score"),
                "technical_direction": technical.get("direction"),
                "setup_quality": technical.get("setup_quality"),
            }
        )
    return result


def build_portfolio_rebalance_context(
    settings: Settings,
    portfolio: PortfolioSnapshot,
    technical_context: dict[str, Any],
    sentiment_context: dict[str, Any],
) -> dict[str, Any]:
    """Build a compact portfolio optimization context for the decision LLM."""

    costs = TransactionCostModel()
    candidates = [_candidate_summary(item) for item in _candidate_items(technical_context)]
    sentiment_by_symbol = _sentiment_map(sentiment_context)
    for candidate in candidates:
        candidate["sentiment"] = sentiment_by_symbol.get(candidate["symbol"], {})

    symbol_scores = {item["symbol"]: item for item in candidates}
    positions = _position_summary(portfolio, symbol_scores)
    long_candidates = [
        item for item in candidates if item.get("direction") == "long" and (item.get("score") or 0) > 0
    ]
    short_candidates = [
        item for item in candidates if item.get("direction") == "short" and (item.get("score") or 0) > 0
    ]
    best_longs = sorted(long_candidates, key=lambda item: item.get("score") or 0, reverse=True)[:5]

    cash_available_exposure = portfolio.cash / portfolio.portfolio_value if portfolio.portfolio_value else 0
    current_exposure = sum(position.market_value for position in portfolio.positions) / portfolio.portfolio_value if portfolio.portfolio_value else 0
    available_portfolio_room = max(0.0, settings.max_portfolio_exposure - current_exposure)

    rotation_candidates = []
    for position in positions:
        sell_cost = costs.one_way_cost(float(position["market_value"] or 0))
        for candidate in best_longs:
            if candidate["symbol"] == position["symbol"]:
                continue
            candidate_notional = min(
                portfolio.portfolio_value * settings.max_position_exposure,
                portfolio.buying_power,
                float(position["market_value"] or 0),
            )
            buy_cost = costs.one_way_cost(candidate_notional)
            position_score = position.get("technical_score") or 0
            candidate_score = candidate.get("score") or 0
            score_delta = candidate_score - position_score
            rotation_candidates.append(
                {
                    "from_symbol": position["symbol"],
                    "to_symbol": candidate["symbol"],
                    "from_score": position_score,
                    "to_score": candidate_score,
                    "score_delta": score_delta,
                    "position_unrealized_plpc": position.get("unrealized_plpc"),
                    "estimated_switch_cost": _round(sell_cost + buy_cost, 2),
                    "estimated_switch_cost_bps": costs.round_trip_bps,
                    "candidate_reasons": candidate.get("reasons", [])[:4],
                }
            )

    rotation_candidates = sorted(
        rotation_candidates,
        key=lambda item: (item["score_delta"], -(item["estimated_switch_cost"] or 0)),
        reverse=True,
    )[:8]

    deterministic_guidance = []
    if not positions:
        deterministic_guidance.append("No hay posiciones actuales: evaluar compras solo si hay candidatos con edge claro y riesgo definido.")
    if available_portfolio_room <= 0:
        deterministic_guidance.append("Cartera en limite de exposicion: comprar solo si se reduce o vende otra posicion.")
    if short_candidates and not settings.allow_short_selling:
        deterministic_guidance.append("Hay candidatos short, pero no se permiten cortos: solo sirven para evitar compras o salir de posiciones existentes.")

    return {
        "portfolio": {
            "cash": _round(portfolio.cash, 2),
            "portfolio_value": _round(portfolio.portfolio_value, 2),
            "buying_power": _round(portfolio.buying_power, 2),
            "current_exposure_pct": _round(current_exposure, 4),
            "available_portfolio_room_pct": _round(available_portfolio_room, 4),
            "cash_available_exposure_pct": _round(cash_available_exposure, 4),
            "open_orders": [asdict(order) for order in portfolio.open_orders],
        },
        "positions": positions,
        "candidate_buys": best_longs,
        "candidate_risk_avoids": short_candidates[:5],
        "rotation_candidates": rotation_candidates,
        "transaction_costs": {
            "commission_bps": costs.commission_bps,
            "slippage_bps": costs.slippage_bps,
            "round_trip_bps": costs.round_trip_bps,
        },
        "decision_policy": [
            "La salida por defecto de una posicion abierta es tocar stop_loss o take_profit; mantener mientras no se toque ningun nivel.",
            "Mantener si la posicion actual sigue dentro de stop/take, aunque aparezca otro candidato con score superior.",
            "Reducir si la exposicion supera objetivo, la tesis se debilita o el drawdown/riesgo sube.",
            "Vender/exit por criterio LLM solo en caso excepcional: deterioro bajista claro, noticia negativa material o riesgo extraordinario.",
            "No rotar solo porque exista un candidato nuevo con mayor score; la rotacion normal queda bloqueada salvo excepcion material.",
            "No ampliar posiciones existentes por defecto; una nueva compra debe abrir o completar una posicion con margen real y notional suficiente.",
            f"No abrir mas de {settings.max_daily_buy_orders} compras nuevas por sesion ni mas de {settings.max_orders_per_cycle} ordenes por ciclo.",
            "No comprar por tener cash: comprar solo con edge tecnico/sentimiento/riesgo y stop/take_profit validos.",
        ],
        "deterministic_guidance": deterministic_guidance,
    }
