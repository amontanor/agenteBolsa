from agente_bolsa.config import Settings
from agente_bolsa.models import PortfolioSnapshot, PositionSnapshot, TradeRecommendation
from agente_bolsa.tools.position_sizing import recommended_notional


def _portfolio(*, buying_power: float = 100_000, positions=None) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=50_000,
        portfolio_value=100_000,
        buying_power=buying_power,
        positions=positions or [],
        open_orders=[],
    )


def test_position_sizing_caps_by_max_position_exposure():
    settings = Settings(MAX_POSITION_EXPOSURE=0.05, MAX_RISK_PER_TRADE=0.01)
    recommendation = TradeRecommendation(
        symbol="AAPL",
        action="buy",
        confidence=0.9,
        reason="test",
        entry_price=100,
        stop_loss=95,
        take_profit=110,
        target_exposure_pct=0.10,
    )

    notional, checks = recommended_notional(settings, _portfolio(), recommendation)

    assert notional == 5000
    assert checks["max_position_notional"] == 5000


def test_position_sizing_caps_by_risk_per_trade():
    settings = Settings(MAX_POSITION_EXPOSURE=0.50, MAX_RISK_PER_TRADE=0.01)
    recommendation = TradeRecommendation(
        symbol="AAPL",
        action="buy",
        confidence=0.9,
        reason="test",
        entry_price=100,
        stop_loss=80,
        take_profit=140,
        target_exposure_pct=0.50,
    )

    notional, checks = recommended_notional(settings, _portfolio(), recommendation)

    assert notional == 5000
    assert checks["max_risk_notional"] == 5000


def test_position_sizing_blocks_position_adds_by_default():
    settings = Settings(MAX_POSITION_EXPOSURE=0.05, MAX_RISK_PER_TRADE=0.01)
    recommendation = TradeRecommendation(
        symbol="AAPL",
        action="buy",
        confidence=0.9,
        reason="test",
        entry_price=100,
        stop_loss=95,
        take_profit=110,
        target_exposure_pct=0.05,
    )
    portfolio = _portfolio(
        positions=[
            PositionSnapshot(
                symbol="AAPL",
                qty=49,
                market_value=4900,
                avg_entry_price=100,
                current_price=100,
                unrealized_pl=0,
                unrealized_plpc=0,
            )
        ]
    )

    notional, checks = recommended_notional(settings, portfolio, recommendation)

    assert notional == 0
    assert checks["reason"] == "position_adds_disabled"


def test_position_sizing_blocks_tiny_orders():
    settings = Settings(
        MAX_POSITION_EXPOSURE=0.05,
        MAX_RISK_PER_TRADE=0.01,
        ALLOW_POSITION_ADDS=True,
        MIN_ORDER_NOTIONAL=100,
    )
    recommendation = TradeRecommendation(
        symbol="AAPL",
        action="buy",
        confidence=0.9,
        reason="test",
        entry_price=100,
        stop_loss=95,
        take_profit=110,
        target_exposure_pct=0.05,
    )
    portfolio = _portfolio(
        positions=[
            PositionSnapshot(
                symbol="AAPL",
                qty=49.99,
                market_value=4999,
                avg_entry_price=100,
                current_price=100,
                unrealized_pl=0,
                unrealized_plpc=0,
            )
        ]
    )

    notional, checks = recommended_notional(settings, portfolio, recommendation)

    assert notional == 0
    assert checks["reason"] == "below_min_order_notional"
