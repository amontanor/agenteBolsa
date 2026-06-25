"""Tests de la estrategia builtin_pullback."""

import pandas as pd

from agente_bolsa.strategies.base import MarketContext
from agente_bolsa.strategies.builtin_pullback import (
    PullbackShadowStrategy,
    build_pullback_candidate,
    is_pullback_candidate,
)


def _candidate(
    *,
    close: float = 106.0,
    sma20: float = 102.0,
    sma50: float = 100.0,
    sma200: float = 90.0,
    rsi_14: float = 52.0,
    return_5d: float = -0.01,
    return_20d: float = 0.04,
    return_60d: float = 0.12,
    direction: str = "long",
    event_momentum_long: bool = False,
    range_expansion_breakout_long: bool = False,
    orderly_breakout_long: bool = False,
    breakout_continuation_long: bool = False,
):
    return {
        "symbol": "AAA",
        "direction": direction,
        "score": 8,
        "setup_quality": "watchlist",
        "analysis_plan": ["trend_stack"],
        "reasons": ["base"],
        "technical_state": {
            "close": close,
            "sma_20": sma20,
            "sma_50": sma50,
            "sma_200": sma200,
            "rsi_14": rsi_14,
            "return_5d": return_5d,
            "return_20d": return_20d,
            "return_60d": return_60d,
            "event_momentum_long": event_momentum_long,
            "range_expansion_breakout_long": range_expansion_breakout_long,
            "orderly_breakout_long": orderly_breakout_long,
            "breakout_continuation_long": breakout_continuation_long,
        },
    }


def test_is_pullback_candidate_accepts_constructive_pullback():
    assert is_pullback_candidate(_candidate()) is True


def test_is_pullback_candidate_rejects_extended_or_breakout_profiles():
    assert is_pullback_candidate(_candidate(close=120.0, sma20=100.0)) is False
    assert is_pullback_candidate(_candidate(rsi_14=67.0)) is False
    assert is_pullback_candidate(_candidate(return_5d=0.06)) is False
    assert is_pullback_candidate(_candidate(event_momentum_long=True)) is False


def test_build_pullback_candidate_tags_shadow_profile(monkeypatch):
    monkeypatch.setattr(
        "agente_bolsa.strategies.builtin_pullback.validate_symbol_technical_state",
        lambda symbol, features: _candidate(),
    )

    candidate = build_pullback_candidate("AAA", pd.DataFrame())

    assert candidate is not None
    assert candidate["setup_quality"] == "strong"
    assert candidate["technical_state"]["pullback_candidate_long"] is True
    assert candidate["technical_state"]["distance_sma20"] == 0.0392
    assert candidate["strategy_notes"]["shadow_only"] is True


def test_pullback_strategy_generates_only_matching_candidates(monkeypatch):
    raw = pd.DataFrame({"Close": [1.0, 2.0]}, index=pd.date_range("2026-01-01", periods=2))
    context = MarketContext(symbols=["AAA", "BBB"], data=raw, multi_symbol=False)
    calls = iter(
        [
            _candidate(),
            _candidate(close=118.0, sma20=100.0),
        ]
    )

    monkeypatch.setattr(
        "agente_bolsa.strategies.builtin_pullback.add_basic_technical_features",
        lambda frame: frame,
    )
    monkeypatch.setattr(
        "agente_bolsa.strategies.builtin_pullback.validate_symbol_technical_state",
        lambda symbol, features: next(calls),
    )

    produced = PullbackShadowStrategy().generate_candidates(context)

    assert [item["symbol"] for item in produced] == ["AAA"]
