"""Regresion del bug `material_risk` en la revision determinista.

El campo `material_risk` de la fila de sentimiento es un DICT
(`assess_material_news_risk`). Antes se evaluaba `bool(dict)` (siempre True), de
modo que la revision bloqueaba TODA compra con reason="material_risk". El fix lee
el booleano interno `.material`.
"""
from __future__ import annotations

from agente_bolsa.config import Settings
from agente_bolsa.models import TradeRecommendation
from agente_bolsa.tools.deterministic_reviewer import _material_flag, review_recommendations


def test_material_flag_reads_inner_boolean():
    assert _material_flag({"material_risk": {"material": True}}) is True
    # Antes daba True (bug); ahora False:
    assert _material_flag({"material_risk": {"material": False, "severity": "none"}}) is False
    assert _material_flag({"material_risk": {}}) is False
    assert _material_flag({}) is False
    assert _material_flag({"material_risk": True}) is True  # legado bool


def test_review_does_not_block_buy_without_material_news():
    settings = Settings()
    rec = TradeRecommendation(
        symbol="AAA",
        action="buy",
        confidence=0.7,
        reason="test",
        entry_price=100.0,
        stop_loss=99.0,
        take_profit=140.0,
    )
    technical = {"selected_candidates": [{"symbol": "AAA", "score": 99}]}
    sentiment = {
        "results": [
            {
                "symbol": "AAA",
                "sentiment": {"sentiment_score": 0.2, "confidence": 0.6},
                "material_risk": {"material": False, "severity": "none"},
            }
        ]
    }
    market_state = {
        "market_regime": "bullish",
        "data_quality": {"status": "GOOD"},
        "market_regime_policy": {"allow_new_buys": True},
    }
    _reviewed, decisions = review_recommendations(settings, [rec], technical, sentiment, market_state)
    assert decisions[0]["reason"] != "material_risk"
    assert decisions[0]["approved"] is True
