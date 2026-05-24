"""Deep technical-state validation for a single symbol."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .chart_patterns import analyze_chart_patterns


def _num(row: pd.Series, key: str, default: float = 0.0) -> float:
    value = row.get(key, default)
    if pd.isna(value):
        return default
    return float(value)


def _round(value: float | None, precision: int = 4) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), precision)


def _flag(row: pd.Series, key: str) -> bool:
    value = row.get(key, False)
    if pd.isna(value):
        return False
    return bool(value)


def _candle_patterns(latest: pd.Series) -> list[str]:
    patterns = []
    if _flag(latest, "candle_doji"):
        patterns.append("doji")
    if _flag(latest, "candle_hammer"):
        patterns.append("hammer")
    if _flag(latest, "candle_shooting_star"):
        patterns.append("shooting_star")
    if _flag(latest, "candle_bullish_engulfing"):
        patterns.append("bullish_engulfing")
    if _flag(latest, "candle_bearish_engulfing"):
        patterns.append("bearish_engulfing")
    return patterns


def choose_analysis_plan(
    latest: pd.Series,
    chart_patterns: list[dict[str, Any]] | None = None,
) -> list[str]:
    plan = [
        "trend_stack",
        "momentum_profile",
        "volatility_atr",
        "volume_confirmation",
        "candlestick_patterns",
        "chart_patterns",
        "risk_plan",
    ]
    close = _num(latest, "Close")
    high_55 = _num(latest, "high_55")
    low_55 = _num(latest, "low_55")
    rsi = _num(latest, "rsi_14", 50)
    ret_5 = _num(latest, "return_5d")
    pct_b = _num(latest, "bollinger_pct_b_20", 0.5)
    atr = _num(latest, "atr_14")
    volume_z = _num(latest, "volume_zscore_20")
    gap_pct = _num(latest, "gap_pct")
    close_position = _num(latest, "close_position_in_range", 0.5)
    prev_high_55 = _num(latest, "prev_high_55")
    breakout_continuation = (
        volume_z >= 1.0
        and close_position >= 0.60
        and (not prev_high_55 or close >= prev_high_55 * 1.003)
    )
    range_expansion_breakout = (
        gap_pct >= 0.03
        and volume_z >= 1.0
        and close_position >= 0.75
        and 50 <= rsi <= 78
        and bool(prev_high_55)
        and close >= prev_high_55 * 1.015
    )
    orderly_breakout = (
        close_position >= 0.80
        and volume_z >= 0.25
        and 52 <= rsi <= 74
        and bool(prev_high_55)
        and close >= prev_high_55 * 1.015
    )
    breakout_failure_risk = (
        bool(prev_high_55)
        and _num(latest, "High") >= prev_high_55 * 1.003
        and close < prev_high_55
        and volume_z >= 1.0
    )
    momentum_shakeout_hold = (
        gap_pct <= -0.02
        and ret_5 >= 0.08
        and volume_z >= 1.5
        and close_position >= 0.70
        and bool(latest.get("above_long_trend"))
    )

    if high_55 and close >= high_55 * 0.98:
        plan.append("breakout_continuation")
    if (
        gap_pct >= 0.07
        and volume_z >= 2.0
        and close_position >= 0.65
        and (not prev_high_55 or close >= prev_high_55 * 1.02)
    ):
        plan.append("event_momentum_continuation")
    elif breakout_continuation:
        plan.append("breakout_follow_through")
    if range_expansion_breakout:
        plan.append("range_expansion_breakout")
    if orderly_breakout and not range_expansion_breakout:
        plan.append("orderly_breakout")
    if momentum_shakeout_hold:
        plan.append("momentum_shakeout_hold")
    if breakout_failure_risk:
        plan.append("breakout_failure_risk")
    if low_55 and close <= low_55 * 1.02:
        plan.append("breakdown_or_reversal")
    if rsi >= 70 or pct_b >= 0.9:
        plan.append("overextension_check")
    if rsi <= 30 or pct_b <= 0.1:
        plan.append("mean_reversion_check")
    if close and atr / close >= 0.04:
        plan.append("high_volatility_risk")
    if abs(volume_z) >= 1.5:
        plan.append("volume_event")
    if _flag(latest, "candle_bullish_signal") or _flag(latest, "candle_bearish_signal"):
        plan.append("candle_confirmation")
    if _flag(latest, "candle_doji"):
        plan.append("candle_indecision")
    for pattern in chart_patterns or []:
        pattern_name = str(pattern.get("pattern", "chart_pattern"))
        plan.append(f"{pattern_name}_check")
        if pattern.get("status") == "confirmed":
            plan.append("chart_pattern_breakout_confirmation")
    return plan


def validate_symbol_technical_state(symbol: str, features: pd.DataFrame) -> dict[str, Any]:
    latest = features.dropna(subset=["Close", "sma_20", "sma_50", "sma_200"]).iloc[-1]
    close = _num(latest, "Close")
    atr = _num(latest, "atr_14", close * 0.02)
    rsi = _num(latest, "rsi_14", 50)
    ret_5 = _num(latest, "return_5d")
    ret_20 = _num(latest, "return_20d")
    ret_60 = _num(latest, "return_60d")
    volume_z = _num(latest, "volume_zscore_20")
    macd = _num(latest, "macd")
    macd_signal = _num(latest, "macd_signal")
    pct_b = _num(latest, "bollinger_pct_b_20", 0.5)
    gap_pct = _num(latest, "gap_pct")
    close_position = _num(latest, "close_position_in_range", 0.5)
    prev_high_55 = _num(latest, "prev_high_55")
    breakout_continuation_long = (
        volume_z >= 1.0
        and close_position >= 0.60
        and ret_20 > 0
        and (not prev_high_55 or close >= prev_high_55 * 1.003)
    )
    range_expansion_breakout_long = (
        gap_pct >= 0.03
        and volume_z >= 1.0
        and close_position >= 0.75
        and 50 <= rsi <= 78
        and ret_20 > 0
        and bool(prev_high_55)
        and close >= prev_high_55 * 1.015
    )
    orderly_breakout_long = (
        close_position >= 0.80
        and volume_z >= 0.25
        and 52 <= rsi <= 74
        and ret_20 > 0
        and bool(prev_high_55)
        and close >= prev_high_55 * 1.015
    )
    breakout_failure_risk = (
        bool(prev_high_55)
        and _num(latest, "High") >= prev_high_55 * 1.003
        and close < prev_high_55
        and volume_z >= 1.0
    )
    event_momentum_long = (
        gap_pct >= 0.07
        and volume_z >= 2.0
        and close_position >= 0.65
        and (not prev_high_55 or close >= prev_high_55 * 1.02)
    )
    momentum_shakeout_hold_long = (
        gap_pct <= -0.02
        and ret_5 >= 0.08
        and volume_z >= 1.5
        and close_position >= 0.70
        and bool(latest.get("above_long_trend"))
    )
    candle_patterns = _candle_patterns(latest)
    chart_patterns = analyze_chart_patterns(features)

    long_score = 0
    short_score = 0
    long_reasons: list[str] = []
    short_reasons: list[str] = []

    if bool(latest.get("above_long_trend")):
        long_score += 2
        long_reasons.append("precio sobre SMA200")
    else:
        short_score += 2
        short_reasons.append("precio bajo SMA200")

    if bool(latest.get("trend_positive")):
        long_score += 2
        long_reasons.append("SMA20 > SMA50")
    else:
        short_score += 2
        short_reasons.append("SMA20 < SMA50")

    if ret_20 > 0.05:
        long_score += 2
        long_reasons.append("momentum 20d positivo")
    elif ret_20 < -0.05:
        short_score += 2
        short_reasons.append("momentum 20d negativo")

    if ret_60 > 0.08:
        long_score += 1
        long_reasons.append("momentum 60d favorable")
    elif ret_60 < -0.08:
        short_score += 1
        short_reasons.append("momentum 60d desfavorable")

    if macd > macd_signal:
        long_score += 1
        long_reasons.append("MACD sobre senal")
    else:
        short_score += 1
        short_reasons.append("MACD bajo senal")

    if rsi >= 75:
        short_score += 1
        short_reasons.append("RSI sobreextendido")
    elif rsi <= 25:
        long_score += 1
        long_reasons.append("RSI en sobreventa")
    elif 45 <= rsi <= 68:
        long_score += 1
        long_reasons.append("RSI constructivo")

    if volume_z >= 1.5:
        if ret_5 >= 0:
            long_score += 1
            long_reasons.append("volumen confirma subida")
        else:
            short_score += 1
            short_reasons.append("volumen confirma venta")

    if pct_b >= 0.9:
        long_score += 1
        long_reasons.append("cierre cerca de banda superior")
    elif pct_b <= 0.1:
        short_score += 1
        short_reasons.append("cierre cerca de banda inferior")

    if event_momentum_long:
        long_score += 3
        long_reasons.append("repricing alcista: gap fuerte, volumen anormal y cierre firme sobre rango previo")
    elif range_expansion_breakout_long:
        long_score += 3
        long_reasons.append("range expansion breakout: gap moderado, ruptura 55d, volumen y cierre fuerte")
    elif orderly_breakout_long:
        long_score += 3
        long_reasons.append("orderly breakout: ruptura 55d con cierre muy fuerte, volumen positivo y extension controlada")
    elif breakout_continuation_long:
        long_score += 2
        long_reasons.append("continuacion de ruptura: mantiene nivel roto con volumen y cierre util")
    if momentum_shakeout_hold_long:
        long_score += 2
        long_reasons.append("shakeout alcista: pullback con volumen que cierra fuerte y mantiene momentum")
    if breakout_failure_risk:
        short_score += 2
        short_reasons.append("fallo de ruptura: rompio resistencia intradia pero no la sostuvo al cierre")
        long_score -= 1
        long_reasons.append("riesgo de fallo de ruptura: mejor esperar nueva confirmacion")

    if _flag(latest, "candle_bullish_signal"):
        long_score += 1
        long_reasons.append(f"vela apoya sesgo alcista: {', '.join(candle_patterns)}")
    if _flag(latest, "candle_bearish_signal"):
        short_score += 1
        short_reasons.append(f"vela apoya sesgo bajista: {', '.join(candle_patterns)}")
    if _flag(latest, "candle_doji"):
        long_score -= 1
        short_score -= 1
        long_reasons.append("doji: indecision, requiere confirmacion")
        short_reasons.append("doji: indecision, requiere confirmacion")

    for pattern in chart_patterns:
        label = str(pattern.get("label", pattern.get("pattern", "figura chartista")))
        status = str(pattern.get("status", "forming"))
        confidence = float(pattern.get("confidence", 0))
        points = 3 if status == "confirmed" else 1
        if confidence < 0.55:
            points = max(1, points - 1)

        if pattern.get("bias") == "bullish":
            long_score += points
            long_reasons.append(f"figura chartista alcista ({status}): {label}")
        elif pattern.get("bias") == "bearish":
            short_score += points
            short_reasons.append(f"figura chartista bajista ({status}): {label}")
        else:
            long_reasons.append(f"figura chartista neutral: {label}, espera ruptura")
            short_reasons.append(f"figura chartista neutral: {label}, espera ruptura")

    direction = "long" if long_score >= short_score else "short"
    score = max(long_score, short_score)
    reasons = long_reasons if direction == "long" else short_reasons
    if abs(long_score - short_score) <= 1:
        setup_quality = "mixed"
    elif score >= 7:
        setup_quality = "strong"
    elif score >= 5:
        setup_quality = "watchlist"
    else:
        setup_quality = "weak"

    if direction == "long":
        stop_loss = close - (2 * atr)
        take_profit = close + (3 * atr)
        invalidation = "Pierde soporte dinamico o cierra bajo stop ATR."
    else:
        stop_loss = close + (2 * atr)
        take_profit = close - (3 * atr)
        invalidation = "Recupera tendencia o cierra sobre stop ATR."

    missing_tools = []
    if abs(volume_z) >= 1.5:
        missing_tools.append(
            {
                "requested_by": "technical_analyst",
                "assigned_to": "self_improvement_engineer",
                "tool": "premarket_volume_validator",
                "reason": "Validar si el volumen anormal continua antes de la apertura.",
            }
        )
    missing_tools.append(
        {
            "requested_by": "technical_analyst",
            "assigned_to": "self_improvement_engineer",
            "tool": "sector_relative_strength_validator",
            "reason": "Comparar el simbolo contra su sector ademas de SPY.",
        }
    )

    return {
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "long_score": long_score,
        "short_score": short_score,
        "setup_quality": setup_quality,
        "analysis_plan": choose_analysis_plan(latest, chart_patterns),
        "reasons": reasons,
        "last_date": str(latest.name.date()) if hasattr(latest.name, "date") else str(latest.name),
        "technical_state": {
            "close": _round(close),
            "return_5d": _round(ret_5),
            "return_20d": _round(ret_20),
            "return_60d": _round(ret_60),
            "sma_20": _round(_num(latest, "sma_20")),
            "sma_50": _round(_num(latest, "sma_50")),
            "sma_200": _round(_num(latest, "sma_200")),
            "rsi_14": _round(rsi, 2),
            "macd": _round(macd),
            "macd_signal": _round(macd_signal),
            "atr_14": _round(atr),
            "realized_vol_20": _round(_num(latest, "realized_vol_20")),
            "volume_zscore_20": _round(volume_z, 2),
            "bollinger_pct_b_20": _round(pct_b, 2),
            "gap_pct": _round(gap_pct),
            "close_position_in_range": _round(close_position, 3),
            "prev_high_55": _round(prev_high_55),
            "breakout_continuation_long": breakout_continuation_long,
            "range_expansion_breakout_long": range_expansion_breakout_long,
            "orderly_breakout_long": orderly_breakout_long,
            "breakout_failure_risk": breakout_failure_risk,
            "event_momentum_long": event_momentum_long,
            "momentum_shakeout_hold_long": momentum_shakeout_hold_long,
            "candle_patterns": candle_patterns,
            "candle_body_pct": _round(_num(latest, "candle_body_pct"), 3),
            "bullish_candle_signal": _flag(latest, "candle_bullish_signal"),
            "bearish_candle_signal": _flag(latest, "candle_bearish_signal"),
            "chart_patterns": chart_patterns,
        },
        "risk_plan": {
            "entry_price": _round(close),
            "stop_loss": _round(stop_loss),
            "take_profit": _round(take_profit),
            "reward_risk": 1.5,
            "invalidation": invalidation,
            "time_stop": "5-10 sesiones salvo invalidacion previa.",
        },
        "next_open_checks": [
            "gap de apertura contra cierre previo",
            "volumen relativo primeros 30 minutos",
            "confirmacion sobre/bajo nivel de entrada",
            "no operar si spread o slippage invalida el reward/risk",
        ],
        "tool_requests": missing_tools,
    }
