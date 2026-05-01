import sys
import types

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.tools.broker import BrokerClientFactory


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
