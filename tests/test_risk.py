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


def test_portfolio_exposure_limit_blocks_when_total_would_exceed_cap():
    settings = Settings(TRADING_MODE="paper", MAX_POSITION_EXPOSURE=0.10, MAX_PORTFOLIO_EXPOSURE=0.50)
    manager = RiskManager(settings)
    proposal = OrderProposal(
        symbol="AAPL",
        side="buy",
        notional=1000,
        portfolio_equity=10000,
        strategy_name="test",
        entry_price=100,
        stop_loss=95,
        take_profit=110,
        current_portfolio_exposure=0.45,
        pending_portfolio_exposure=0.0,
    )

    decision = manager.validate_order(proposal)

    assert not decision.approved
    assert "exposicion agregada" in decision.reason


def test_total_open_risk_limit_blocks_when_risk_stack_is_too_high():
    settings = Settings(TRADING_MODE="paper", MAX_POSITION_EXPOSURE=0.20, MAX_TOTAL_OPEN_RISK=0.03)
    manager = RiskManager(settings)
    proposal = OrderProposal(
        symbol="AAPL",
        side="buy",
        notional=1000,
        portfolio_equity=10000,
        strategy_name="test",
        entry_price=100,
        stop_loss=95,
        take_profit=110,
        existing_open_risk_amount=220,
        pending_open_risk_amount=40,
    )

    decision = manager.validate_order(proposal)

    assert not decision.approved
    assert "riesgo agregado abierto" in decision.reason


def test_position_limit_allows_order_at_cap_after_conservative_rounding():
    settings = Settings(TRADING_MODE="paper", MAX_POSITION_EXPOSURE=0.05)
    manager = RiskManager(settings)
    proposal = OrderProposal(
        symbol="HPE",
        side="buy",
        notional=3531.98,
        portfolio_equity=70639.75,
        strategy_name="test",
        entry_price=32.17,
        stop_loss=29.9614,
        take_profit=35.4829,
    )

    decision = manager.validate_order(proposal)

    assert decision.approved
