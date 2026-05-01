from agente_bolsa.config import Settings
from agente_bolsa.tools.risk import OrderProposal, RiskManager


def test_live_trading_requires_explicit_permission():
    settings = Settings(TRADING_MODE="live", ALLOW_LIVE_TRADING=False)
    manager = RiskManager(settings)
    proposal = OrderProposal(
        symbol="AAPL",
        side="buy",
        notional=1000,
        portfolio_equity=100000,
        strategy_name="test",
        entry_price=100,
        stop_loss=95,
        take_profit=110,
    )

    decision = manager.validate_order(proposal)

    assert not decision.approved
    assert "Live trading" in decision.reason


def test_position_limit_blocks_large_order():
    settings = Settings(TRADING_MODE="paper", MAX_POSITION_EXPOSURE=0.05)
    manager = RiskManager(settings)
    proposal = OrderProposal(
        symbol="AAPL",
        side="buy",
        notional=10000,
        portfolio_equity=100000,
        strategy_name="test",
        entry_price=100,
        stop_loss=95,
        take_profit=110,
    )

    decision = manager.validate_order(proposal)

    assert not decision.approved
    assert "limite" in decision.reason


def test_order_requires_defined_exit_risk():
    settings = Settings(TRADING_MODE="paper")
    manager = RiskManager(settings)
    proposal = OrderProposal(
        symbol="AAPL",
        side="buy",
        notional=1000,
        portfolio_equity=100000,
        strategy_name="test",
    )

    decision = manager.validate_order(proposal)

    assert not decision.approved
    assert "stop_loss" in decision.reason


def test_reward_risk_must_be_sufficient():
    settings = Settings(TRADING_MODE="paper")
    manager = RiskManager(settings)
    proposal = OrderProposal(
        symbol="AAPL",
        side="buy",
        notional=1000,
        portfolio_equity=100000,
        strategy_name="test",
        entry_price=100,
        stop_loss=95,
        take_profit=104,
    )

    decision = manager.validate_order(proposal)

    assert not decision.approved
    assert "beneficio/riesgo" in decision.reason
