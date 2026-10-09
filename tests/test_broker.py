import socket
import sys
import types

import pytest
from alpaca.trading.enums import OrderSide, OrderStatus, OrderType, PositionSide

from agente_bolsa.config import Settings
from agente_bolsa.models import PortfolioSnapshot
from agente_bolsa.tools.broker import BrokerClientFactory, _str_attr
import agente_bolsa.tools.trade_decision as trade_decision
from agente_bolsa.tools.trade_decision import _portfolio_risk_context


def test_str_attr_normalizes_sdk_enum_and_defaults():
    assert _str_attr(types.SimpleNamespace(side=OrderSide.SELL), "side") == "sell"
    assert _str_attr(types.SimpleNamespace(type=OrderType.MARKET), "type") == "market"
    assert _str_attr(types.SimpleNamespace(status=OrderStatus.NEW), "status") == "new"
    assert _str_attr(types.SimpleNamespace(status=None), "status", "fallback") == "fallback"
    assert _str_attr(types.SimpleNamespace(raw="plain"), "raw") == "plain"


def test_sdk_position_side_flows_to_risk_context_without_losing_values(monkeypatch, tmp_path):
    def blocked(*_args, **_kwargs):
        raise RuntimeError("external_network_forbidden")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)

    settings = Settings(
        _env_file=None,
        DATA_DIR=tmp_path,
        TRADING_MODE="paper",
        ALLOW_LIVE_TRADING=False,
        ALPACA_PAPER=True,
        ALPACA_API_KEY="",
        ALPACA_SECRET_KEY="",
    )
    fixture = types.SimpleNamespace(
        symbol="TEST",
        qty="1",
        market_value="100",
        avg_entry_price="100",
        current_price="100",
        unrealized_pl="0",
        unrealized_plpc="0",
        side=PositionSide.LONG,
    )
    factory = BrokerClientFactory(settings)
    monkeypatch.setattr(
        factory,
        "alpaca_trading_client",
        lambda: types.SimpleNamespace(get_all_positions=lambda: [fixture]),
    )

    stores = []
    original_store = trade_decision.Store

    class TrackedStore(original_store):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            stores.append(self)

    monkeypatch.setattr(trade_decision, "Store", TrackedStore)
    try:
        position = factory.alpaca_positions()[0]
        portfolio = PortfolioSnapshot(
            "fixture",
            "ACTIVE",
            "USD",
            900.0,
            1000.0,
            900.0,
            [position],
            [],
        )
        risk_context = _portfolio_risk_context(settings, portfolio)
    finally:
        for store in stores:
            store.close_read_connection()

    assert position.side == PositionSide.LONG.value == "long"
    assert position.symbol == "TEST"
    assert position.qty == 1.0
    assert position.market_value == 100.0
    assert position.avg_entry_price == 100.0
    assert position.current_price == 100.0
    assert position.unrealized_pl == 0.0
    assert position.unrealized_plpc == 0.0
    assert risk_context["current_portfolio_exposure"] == pytest.approx(0.1)


def test_alpaca_client_uses_paper_endpoint(monkeypatch):
    captured = {}

    class FakeTradingClient:
        def __init__(self, api_key, secret_key, paper, url_override):
            captured.update(
                {
                    "api_key": api_key,
                    "secret_key": secret_key,
                    "paper": paper,
                    "url_override": url_override,
                }
            )

    alpaca_module = types.ModuleType("alpaca")
    trading_module = types.ModuleType("alpaca.trading")
    client_module = types.ModuleType("alpaca.trading.client")
    client_module.TradingClient = FakeTradingClient
    monkeypatch.setitem(sys.modules, "alpaca", alpaca_module)
    monkeypatch.setitem(sys.modules, "alpaca.trading", trading_module)
    monkeypatch.setitem(sys.modules, "alpaca.trading.client", client_module)

    settings = Settings(
        TRADING_MODE="paper",
        ALPACA_API_KEY="key",
        ALPACA_SECRET_KEY="secret",
        ALPACA_PAPER_ENDPOINT="https://paper.example.test/v2",
        ALPACA_PAPER=True,
    )

    BrokerClientFactory(settings).alpaca_trading_client()

    assert captured == {
        "api_key": "key",
        "secret_key": "secret",
        "paper": True,
        "url_override": "https://paper.example.test",
    }


def test_paper_mode_rejects_non_paper_alpaca_config():
    settings = Settings(
        TRADING_MODE="paper",
        ALPACA_API_KEY="key",
        ALPACA_SECRET_KEY="secret",
        ALPACA_PAPER=False,
    )

    with pytest.raises(RuntimeError, match="paper trading"):
        BrokerClientFactory(settings).alpaca_trading_client()


def test_alpaca_requires_credentials():
    settings = Settings(TRADING_MODE="paper", ALPACA_API_KEY="", ALPACA_SECRET_KEY="")

    with pytest.raises(RuntimeError, match="ALPACA_API_KEY"):
        BrokerClientFactory(settings).alpaca_trading_client()


def test_accepts_alpaca_key_alias():
    settings = Settings(
        TRADING_MODE="paper",
        ALPACA_KEY="key",
        ALPACA_SECRET_KEY="secret",
    )

    assert settings.alpaca_api_key == "key"
