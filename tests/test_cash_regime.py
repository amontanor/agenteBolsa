"""Tests de cash activo y estrategias por regimen (T5.7)."""

from types import SimpleNamespace

from agente_bolsa.config import Settings
from agente_bolsa.strategies.base import Strategy
from agente_bolsa.strategies.cash_allocation import enforce_cash_floor, target_cash_pct
from agente_bolsa.strategies.registry import strategy_matches_regime
from agente_bolsa.tools.hypothesis_factory import generate_variants


def _settings():
    return SimpleNamespace(cash_floor_risk_off=0.60, cash_floor_neutral=0.25)


def test_cash_target_by_regime():
    s = _settings()
    assert target_cash_pct(s, stance="risk_off") == 0.60
    assert target_cash_pct(s, regime="range") == 0.25
    assert target_cash_pct(s, stance="risk_on") == 0.0


def test_cash_target_escalates_with_drawdown():
    s = _settings()
    assert target_cash_pct(s, stance="risk_on", drawdown_pct=0.16) >= 0.50
    assert target_cash_pct(s, stance="risk_on", drawdown_pct=0.11) >= 0.35


def test_enforce_cash_floor_blocks_buys_below_floor():
    allowed, info = enforce_cash_floor(["b1", "b2"], cash_pct=0.20, target_cash_pct_value=0.25)
    assert allowed == []
    assert info["blocked_buys"] == 2
    allowed2, info2 = enforce_cash_floor(["b1"], cash_pct=0.40, target_cash_pct_value=0.25)
    assert allowed2 == ["b1"]
    assert info2["blocked_buys"] == 0


def test_generate_variants_reserves_regime_quota(tmp_path):
    settings = Settings(DATA_DIR=tmp_path, FACTORY_REGIME_QUOTA=0.30, FACTORY_MAX_VARIANTS_PER_NIGHT=100)
    variants = generate_variants(settings)
    non_trend = [v for v in variants if v.get("target_regime") in {"range", "bear"}]
    assert len(non_trend) >= int(len(variants) * 0.25)  # ~30% reservado


def test_strategy_matches_regime():
    class RangeStrat(Strategy):
        target_regime = "range"

        def generate_candidates(self, context):
            return []

    class AnyStrat(Strategy):
        def generate_candidates(self, context):
            return []

    assert strategy_matches_regime(RangeStrat(), "range")
    assert not strategy_matches_regime(RangeStrat(), "trend")
    assert strategy_matches_regime(AnyStrat(), "trend")
