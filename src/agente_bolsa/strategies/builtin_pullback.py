"""Estrategia builtin: pullbacks de calidad en tendencia (SHADOW).

Genera candidatos long cerca de la SMA20, evitando nombres extendidos o en
ruptura parabolica. Reutiliza `validate_symbol_technical_state` para construir
el mismo payload que consume el resto del pipeline, pero filtra para dejar solo
retrocesos moderados en tendencia mayor intacta.
"""

from __future__ import annotations

from typing import Any

from ..tools.technical_analysis import add_basic_technical_features
from ..tools.technical_state_validator import validate_symbol_technical_state
from .base import CandidateSignal, MarketContext, Strategy

_PULLBACK_MIN_SMA20_DISTANCE = -0.05
_PULLBACK_MAX_SMA20_DISTANCE = 0.08
_PULLBACK_MIN_RSI = 40.0
_PULLBACK_MAX_RSI = 60.0
_PULLBACK_MAX_RETURN_5D = 0.02
_PULLBACK_MIN_RETURN_20D = -0.08
_PULLBACK_MIN_RETURN_60D = 0.0


def _symbol_frame(data: Any, symbol: str, multi_symbol: bool):
    if multi_symbol:
        return data[symbol].copy().dropna(how="all")
    return data.copy().dropna(how="all")


def _float(value: Any, precision: int = 4) -> float | None:
    import pandas as pd

    if pd.isna(value):
        return None
    return round(float(value), precision)


def _distance_to_sma20(technical_state: dict[str, Any]) -> float | None:
    close = _float(technical_state.get("close"))
    sma20 = _float(technical_state.get("sma_20"))
    if close is None or sma20 in {None, 0.0}:
        return None
    return round((close - sma20) / sma20, 4)


def is_pullback_candidate(candidate: CandidateSignal) -> bool:
    technical = (candidate.get("technical_state") or {}) if isinstance(candidate, dict) else {}
    close = _float(technical.get("close"))
    sma50 = _float(technical.get("sma_50"))
    sma200 = _float(technical.get("sma_200"))
    rsi = _float(technical.get("rsi_14"), precision=2)
    return_5d = _float(technical.get("return_5d"))
    return_20d = _float(technical.get("return_20d"))
    return_60d = _float(technical.get("return_60d"))
    distance_sma20 = _distance_to_sma20(technical)

    if candidate.get("direction") != "long":
        return False
    if close is None or sma50 is None or sma200 is None:
        return False
    if close <= sma200 or close <= sma50:
        return False
    if distance_sma20 is None or not (_PULLBACK_MIN_SMA20_DISTANCE <= distance_sma20 <= _PULLBACK_MAX_SMA20_DISTANCE):
        return False
    if rsi is None or not (_PULLBACK_MIN_RSI <= rsi <= _PULLBACK_MAX_RSI):
        return False
    if return_5d is None or return_5d > _PULLBACK_MAX_RETURN_5D:
        return False
    if return_20d is None or return_20d < _PULLBACK_MIN_RETURN_20D:
        return False
    if return_60d is None or return_60d <= _PULLBACK_MIN_RETURN_60D:
        return False
    if any(
        bool(technical.get(flag))
        for flag in (
            "event_momentum_long",
            "range_expansion_breakout_long",
            "orderly_breakout_long",
            "breakout_continuation_long",
        )
    ):
        return False
    return True


def build_pullback_candidate(symbol: str, features: Any) -> CandidateSignal | None:
    candidate = validate_symbol_technical_state(symbol, features)
    if not is_pullback_candidate(candidate):
        return None
    technical = candidate.get("technical_state", {}) or {}
    distance_sma20 = _distance_to_sma20(technical)
    candidate["setup_quality"] = "strong"
    candidate["analysis_plan"] = [
        "trend_stack",
        "pullback_quality",
        "mean_reversion_check",
        "volume_confirmation",
        "risk_plan",
    ]
    candidate["reasons"] = [
        "pullback sano en tendencia alcista",
        "precio cerca de SMA20 sin extension toxica",
        "RSI moderado sin sobrecompra",
        "retroceso reciente con tendencia mayor intacta",
    ]
    candidate["technical_state"] = {
        **technical,
        "distance_sma20": distance_sma20,
        "pullback_candidate_long": True,
    }
    candidate["strategy_notes"] = {
        "profile": "pullback",
        "shadow_only": True,
    }
    return candidate


class PullbackShadowStrategy(Strategy):
    name = "builtin_pullback"
    version = "1"
    status = "SHADOW"
    target_regime = "any"
    required_history_days = 420

    def __init__(self) -> None:
        self.last_warnings: list[str] = []

    def generate_candidates(self, context: MarketContext) -> list[CandidateSignal]:
        self.last_warnings = []
        candidates: list[CandidateSignal] = []
        if context.data is None:
            return candidates
        for symbol in context.symbols:
            try:
                frame = _symbol_frame(context.data, symbol, context.multi_symbol)
                if frame.empty:
                    self.last_warnings.append(f"{symbol}: sin datos")
                    continue
                features = add_basic_technical_features(frame)
                candidate = build_pullback_candidate(symbol, features)
                if candidate is not None:
                    candidates.append(candidate)
            except Exception as exc:  # noqa: BLE001 - un simbolo malo no bloquea el scan.
                self.last_warnings.append(f"{symbol}: {exc}")
        return candidates


def get_strategy() -> Strategy:
    return PullbackShadowStrategy()
