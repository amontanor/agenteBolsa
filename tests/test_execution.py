import sys
import types
import pytest

from agente_bolsa.config import Settings
from agente_bolsa.tools.broker import BrokerClientFactory
from agente_bolsa.tools.execution import (
    _alpaca_price,
    _is_fractional_qty,
    _is_full_position_exit,
    build_market_order_request,
    submit_paper_order_plan,
)


def test_alpaca_price_rounds_equity_prices_to_penny():
    assert _alpaca_price(1256.3146) == 1256.31
    assert _alpaca_price(1256.315) == 1256.32
    assert _alpaca_price(0.123456) == 0.1235


def test_detects_fractional_quantities():
    assert _is_fractional_qty(2.5)
    assert not _is_fractional_qty(2)
    assert not _is_fractional_qty("2.000000")


def test_detects_full_position_exit_plan():
    assert _is_full_position_exit(
        {
            "symbol": "AMZN",
            "side": "sell",
            "payload": {
                "recommendation": {"action": "exit"},
                "risk_decision": {"checks": {"held_qty": 13.600098938}},
            },
        }
    )
    assert not _is_full_position_exit(
        {
            "symbol": "AMZN",
            "side": "sell",
            "payload": {
                "recommendation": {"action": "reduce"},
                "risk_decision": {"checks": {"held_qty": 13.600098938}},
            },
        }
    )


def _install_fake_alpaca(monkeypatch):
    class _EnumValue:
        def __init__(self, value):
            self.value = value

    class OrderSide:
        BUY = _EnumValue("buy")
        SELL = _EnumValue("sell")

    class TimeInForce:
        DAY = _EnumValue("day")

    class OrderClass:
        BRACKET = _EnumValue("bracket")

    class MarketOrderRequest:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class LimitOrderRequest:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class StopLossRequest:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class TakeProfitRequest:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    alpaca_module = types.ModuleType("alpaca")
    trading_module = types.ModuleType("alpaca.trading")
    enums_module = types.ModuleType("alpaca.trading.enums")
    requests_module = types.ModuleType("alpaca.trading.requests")
    enums_module.OrderSide = OrderSide
    enums_module.TimeInForce = TimeInForce
    enums_module.OrderClass = OrderClass
    requests_module.MarketOrderRequest = MarketOrderRequest
    requests_module.LimitOrderRequest = LimitOrderRequest
    requests_module.StopLossRequest = StopLossRequest
    requests_module.TakeProfitRequest = TakeProfitRequest
    monkeypatch.setitem(sys.modules, "alpaca", alpaca_module)
    monkeypatch.setitem(sys.modules, "alpaca.trading", trading_module)
    monkeypatch.setitem(sys.modules, "alpaca.trading.enums", enums_module)
    monkeypatch.setitem(sys.modules, "alpaca.trading.requests", requests_module)


def test_builds_bracket_market_order(monkeypatch):
    _install_fake_alpaca(monkeypatch)
    plan = {
        "plan_id": "plan_123",
        "symbol": "AAPL",
        "side": "buy",
        "notional": 200.0,
        "payload": {
            "qty": 2,
            "stop_loss": 95.0,
            "take_profit": 110.0,
        },
    }

    request = build_market_order_request(
        plan,
        client_order_id="agente-plan_123",
        use_bracket_orders=True,
    )

    assert request.kwargs["symbol"] == "AAPL"
    assert request.kwargs["qty"] == 2.0
    assert request.kwargs["client_order_id"] == "agente-plan_123"
    assert request.kwargs["take_profit"].kwargs["limit_price"] == 110.0
    assert request.kwargs["stop_loss"].kwargs["stop_price"] == 95.0


def test_limit_entry_applies_gap_cap(monkeypatch):
    _install_fake_alpaca(monkeypatch)
    plan = {
        "plan_id": "plan_lim",
        "symbol": "AAPL",
        "side": "buy",
        "notional": 200.0,
        "payload": {"qty": 2, "entry_price": 100.0, "stop_loss": 95.0, "take_profit": 110.0},
    }
    request = build_market_order_request(
        plan,
        client_order_id="agente-lim",
        use_bracket_orders=False,
        use_limit_entries=True,
        max_entry_gap_pct=0.015,
    )
    # Limit price = 100 * 1.015 = 101.50
    assert request.kwargs["limit_price"] == 101.5
    assert request.kwargs["qty"] == 2.0
    assert "notional" not in request.kwargs


def test_fractional_buy_uses_simple_notional_order(monkeypatch):
    _install_fake_alpaca(monkeypatch)
    plan = {
        "plan_id": "plan_123",
        "symbol": "STX",
        "side": "buy",
        "notional": 3573.97,
        "payload": {
            "qty": 2.846321,
            "stop_loss": 1180.0,
            "take_profit": 1300.0,
        },
    }

    request = build_market_order_request(
        plan,
        client_order_id="agente-plan_123",
        use_bracket_orders=True,
    )

    assert request.kwargs["symbol"] == "STX"
    assert request.kwargs["notional"] == 3573.97
    assert "qty" not in request.kwargs
    assert "order_class" not in request.kwargs
    assert "take_profit" not in request.kwargs
    assert "stop_loss" not in request.kwargs


def test_full_exit_uses_alpaca_close_position(monkeypatch):
    captured = {}

    class FakeClient:
        def close_position(self, symbol):
            captured["closed"] = symbol
            return {
                "id": "order-1",
                "symbol": symbol,
                "side": "sell",
                "type": "market",
                "status": "accepted",
                "qty": None,
            }

        def submit_order(self, order_data):  # pragma: no cover - must not be called.
            raise AssertionError("submit_order should not be called for full exits")

    monkeypatch.setattr(
        BrokerClientFactory,
        "alpaca_trading_client",
        lambda self: FakeClient(),
    )
    plan = {
        "symbol": "AMZN",
        "side": "sell",
        "notional": 3570.0,
        "payload": {
            "qty": 13.600098938,
            "recommendation": {"action": "exit"},
            "risk_decision": {"checks": {"action": "exit", "held_qty": 13.600098938}},
        },
    }

    result = submit_paper_order_plan(
        Settings(TRADING_MODE="paper", ALPACA_PAPER=True),
        plan,
        client_order_id="agente-plan",
    )

    assert captured["closed"] == "AMZN"
    assert result["id"] == "order-1"
    assert result["side"] == "sell"


def test_buy_execution_is_blocked_by_operational_kill_switch(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latest_operational_health.json").write_text(
        '{"alerts":[{"severity":"critical","kind":"job_failed","job":"market_cycle","detail":"broker sync timeout"}]}',
        encoding="utf-8",
    )
    plan = {
        "symbol": "AAPL",
        "side": "buy",
        "notional": 200.0,
        "payload": {
            "qty": 2,
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "take_profit": 110.0,
        },
    }

    with pytest.raises(RuntimeError, match="operational kill switch"):
        submit_paper_order_plan(
            Settings(TRADING_MODE="paper", ALPACA_PAPER=True, DATA_DIR=tmp_path),
            plan,
            client_order_id="agente-plan",
        )
