"""§1 (experimento paper): construir el take a un R:R mínimo cuando el del LLM es bajo.

Sube el take_profit hasta `entry_score_v2_min_reward_risk` (respetando el stop; nunca
empeora ni toca el stop). Los buenos R:R quedan intactos.
"""
from __future__ import annotations

from agente_bolsa.config import Settings
from agente_bolsa.models import TradeRecommendation
from agente_bolsa.tools.trade_decision import _construct_min_reward_risk


def _rec(entry, stop, take):
    return TradeRecommendation(
        symbol="AAA", action="buy", confidence=0.7, reason="t",
        entry_price=entry, stop_loss=stop, take_profit=take,
    )


def test_raises_take_when_reward_risk_low():
    s = Settings()  # entry_score_v2_min_reward_risk default 1.5
    rec = _rec(100.0, 95.0, 102.0)  # R:R = 2/5 = 0.4 (bajo)
    out = _construct_min_reward_risk(rec, s)
    rr = (out.take_profit - 100.0) / (100.0 - 95.0)
    assert rr >= 1.5
    assert out.take_profit > rec.take_profit  # solo sube el take


def test_leaves_good_reward_risk_untouched():
    s = Settings()
    rec = _rec(100.0, 95.0, 120.0)  # R:R = 20/5 = 4.0
    out = _construct_min_reward_risk(rec, s)
    assert out.take_profit == 120.0


def test_invalid_inputs_untouched():
    s = Settings()
    rec = _rec(None, None, None)
    assert _construct_min_reward_risk(rec, s) is rec
    # stop por encima de entry -> sin cambios
    bad = _rec(100.0, 105.0, 110.0)
    assert _construct_min_reward_risk(bad, s) is bad
