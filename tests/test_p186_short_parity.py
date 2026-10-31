"""P-L186: contrato y limites de la linea corta (aislado, sin red)."""

from __future__ import annotations

import sys
import types
from dataclasses import replace
from pathlib import Path

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.kernel import kernel_check_order
from agente_bolsa.models import (
    PortfolioSnapshot,
    PositionSnapshot,
    TradeRecommendation,
)
from agente_bolsa.storage import Store
from agente_bolsa.tools.execution import (
    _is_full_position_exit,
    _plan_effect,
    build_market_order_request,
)
from agente_bolsa.tools.position_sizing import recommended_short_notional
from agente_bolsa.tools.risk import OrderProposal, RiskManager
from agente_bolsa.tools.trade_decision import (
    VALID_ACTIONS,
    _recommendation_from_dict,
    _short_reward_risk,
    _short_selection_eligible,
)


def _settings(tmp_path: Path, **overrides) -> Settings:
    base = dict(
        DATA_DIR=tmp_path,
        _env_file=None,
        TRADING_MODE="paper",
        ALPACA_PAPER=True,
        ALLOW_LIVE_TRADING=False,
        ALLOW_SHORT_SELLING=True,
        MAX_SHORT_EXPOSURE=0.10,
        MAX_SHORT_POSITION_EXPOSURE=0.03,
        MAX_GROSS_EXPOSURE=0.80,
        MAX_OPEN_SHORT_POSITIONS=2,
        MAX_SHORT_RISK_PER_TRADE=0.005,
        MAX_TOTAL_SHORT_OPEN_RISK=0.010,
        MIN_ORDER_NOTIONAL=100,
    )
    base.update(overrides)
    return Settings(**base)


def _portfolio(**kwargs) -> PortfolioSnapshot:
    defaults = dict(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=70_000.0,
        portfolio_value=70_000.0,
        buying_power=140_000.0,
        positions=[],
        open_orders=[],
    )
    defaults.update(kwargs)
    return PortfolioSnapshot(**defaults)


def _short_recommendation(**overrides) -> TradeRecommendation:
    data = dict(
        symbol="AAPL",
        action="short",
        confidence=0.8,
        reason="tesis bajista",
        entry_price=100.0,
        stop_loss=110.0,
        take_profit=80.0,
        direction="short",
    )
    data.update(overrides)
    return TradeRecommendation(**data)


def _kernel_plan(effect: str, **overrides) -> dict:
    payload = {
        "qty": 10,
        "entry_price": 100.0,
        "stop_loss": 110.0,
        "take_profit": 80.0,
        "portfolio_equity": 70_000.0,
        "position_effect": effect,
        "direction": "short" if effect.endswith("_short") else "long",
        "risk_decision": {
            "approved": True,
            "checks": {
                "portfolio_equity": 70_000.0,
                "reward_risk": 2.0,
                "projected_short_exposure": 0.014,
                "projected_gross_exposure": 0.20,
                "borrow": {"status": "verified", "shortable": True, "easy_to_borrow": True},
            },
        },
    }
    payload.update(overrides)
    return {
        "symbol": "AAPL",
        "side": "buy" if effect in {"close_short", "open_long"} else "sell",
        "notional": 1_000.0,
        "position_effect": effect,
        "direction": payload["direction"],
        "payload": payload,
    }


def test_config_defaults_are_guarded(tmp_path: Path) -> None:
    settings = Settings(DATA_DIR=tmp_path, _env_file=None)
    assert settings.allow_short_selling is False
    assert settings.max_short_exposure == pytest.approx(0.10)
    assert settings.max_short_position_exposure == pytest.approx(0.03)
    assert settings.max_open_short_positions == 2
    assert settings.max_daily_short_orders == 1
    assert settings.max_short_risk_per_trade == pytest.approx(0.005)
    assert settings.max_gross_exposure == pytest.approx(0.80)


def test_action_contract_accepts_short_and_cover() -> None:
    assert {"short", "cover"} <= VALID_ACTIONS
    short = _recommendation_from_dict(
        {
            "symbol": "MSFT",
            "action": "short",
            "confidence": 0.7,
            "reason": "bajista",
            "entry_price": 100,
            "stop_loss": 110,
            "take_profit": 80,
        }
    )
    assert short is not None and short.action == "short"
    cover = _recommendation_from_dict(
        {"symbol": "MSFT", "action": "cover", "confidence": 0.7, "reason": "cerrar"}
    )
    assert cover is not None and cover.action == "cover"


def test_short_selection_requires_negative_trend_and_inverted_geometry() -> None:
    candidate = {
        "symbol": "AAPL",
        "direction": "short",
        "setup_quality": "strong",
        "risk_plan": {"entry_price": 100.0, "stop_loss": 110.0, "take_profit": 80.0},
        "technical_state": {"return_20d": -0.12},
    }
    assert _short_selection_eligible(candidate) == (True, "eligible")
    wrong_geometry = dict(candidate)
    wrong_geometry["risk_plan"] = {"entry_price": 100.0, "stop_loss": 90.0, "take_profit": 120.0}
    assert _short_selection_eligible(wrong_geometry)[1] == "invalid_short_risk_plan"
    bull = dict(candidate)
    bull["technical_state"] = {"return_20d": 0.05}
    assert _short_selection_eligible(bull)[1] == "return_20d_not_negative"


def test_short_reward_risk_inverted() -> None:
    recommendation = _short_recommendation()
    assert _short_reward_risk(recommendation) == pytest.approx(2.0)
    assert _short_reward_risk(replace(recommendation, stop_loss=90.0, take_profit=110.0)) is None


def test_risk_manager_approves_bounded_short(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    proposal = OrderProposal(
        symbol="AAPL",
        side="sell",
        notional=1_000.0,
        portfolio_equity=70_000.0,
        strategy_name="short",
        entry_price=100.0,
        stop_loss=110.0,
        take_profit=80.0,
        direction="short",
        position_effect="open_short",
    )
    decision = RiskManager(settings).validate_order(proposal)
    assert decision.approved is True
    assert decision.checks["projected_short_exposure"] == pytest.approx(1000 / 70_000)


def test_risk_manager_rejects_short_over_position_cap(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    proposal = OrderProposal(
        symbol="AAPL",
        side="sell",
        notional=3_000.0,
        portfolio_equity=70_000.0,
        strategy_name="short",
        entry_price=100.0,
        stop_loss=110.0,
        take_profit=80.0,
        direction="short",
        position_effect="open_short",
    )
    decision = RiskManager(settings).validate_order(proposal)
    assert decision.approved is False
    assert "limite por activo" in decision.reason


def test_risk_manager_always_allows_cover(tmp_path: Path) -> None:
    settings = _settings(tmp_path, MAX_SHORT_EXPOSURE=0.0)
    decision = RiskManager(settings).validate_order(
        OrderProposal(
            symbol="AAPL",
            side="buy",
            notional=10_000.0,
            portfolio_equity=70_000.0,
            strategy_name="cover",
            direction="short",
            position_effect="close_short",
        )
    )
    assert decision.approved is True


def test_kernel_blocks_short_without_borrow(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    plan = _kernel_plan("open_short")
    plan["payload"]["risk_decision"]["checks"].pop("borrow")
    ok, reason = kernel_check_order(plan, _portfolio(), settings)
    assert ok is False and "borrow" in reason


def test_kernel_allows_verified_short_and_cover(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    ok, reason = kernel_check_order(_kernel_plan("open_short"), _portfolio(), settings)
    assert ok is True, reason
    cover = _kernel_plan("close_short")
    cover["payload"]["qty"] = 10
    ok, reason = kernel_check_order(cover, _portfolio(), settings)
    assert ok is True, reason


def test_kernel_blocks_short_over_absolute_cap(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    plan = _kernel_plan("open_short", notional=70_000.0 * 0.20)
    plan["notional"] = 70_000.0 * 0.20
    ok, reason = kernel_check_order(plan, _portfolio(), settings)
    assert ok is False and "posicion" in reason


def test_kernel_legacy_sell_still_passes_as_close(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    plan = {
        "symbol": "AAPL",
        "side": "sell",
        "notional": 1_000.0,
        "payload": {"qty": 10, "recommendation": {"action": "sell"}},
    }
    assert _plan_effect(plan) == "close_long"
    ok, reason = kernel_check_order(plan, _portfolio(), settings)
    assert ok is True, reason


class _FakeOrderSide:
    BUY = "buy"
    SELL = "sell"


class _FakeOrderClass:
    BRACKET = "bracket"


class _FakeTIF:
    DAY = "day"


class _FakeRequest:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


@pytest.fixture()
def fake_alpaca(monkeypatch: pytest.MonkeyPatch) -> None:
    enums = types.ModuleType("alpaca.trading.enums")
    enums.OrderClass = _FakeOrderClass
    enums.OrderSide = _FakeOrderSide
    enums.TimeInForce = _FakeTIF
    requests = types.ModuleType("alpaca.trading.requests")
    requests.LimitOrderRequest = _FakeRequest
    requests.MarketOrderRequest = _FakeRequest
    requests.StopLossRequest = _FakeRequest
    requests.TakeProfitRequest = _FakeRequest
    trading = types.ModuleType("alpaca.trading")
    alpaca = types.ModuleType("alpaca")
    monkeypatch.setitem(sys.modules, "alpaca", alpaca)
    monkeypatch.setitem(sys.modules, "alpaca.trading", trading)
    monkeypatch.setitem(sys.modules, "alpaca.trading.enums", enums)
    monkeypatch.setitem(sys.modules, "alpaca.trading.requests", requests)


def test_execution_maps_short_to_sell_and_cover_to_buy(fake_alpaca) -> None:
    short_plan = {
        "symbol": "AAPL",
        "side": "sell",
        "notional": 1_000.0,
        "payload": {
            "qty": 10,
            "entry_price": 100.0,
            "stop_loss": 110.0,
            "take_profit": 80.0,
            "position_effect": "open_short",
            "direction": "short",
        },
    }
    request = build_market_order_request(
        short_plan,
        client_order_id="c1",
        use_bracket_orders=True,
    )
    assert request.kwargs["side"] == _FakeOrderSide.SELL
    assert request.kwargs["qty"] == 10.0
    assert "order_class" not in request.kwargs

    cover_plan = {
        "symbol": "AAPL",
        "side": "buy",
        "notional": 1_000.0,
        "payload": {
            "qty": 10,
            "position_effect": "close_short",
            "direction": "short",
        },
    }
    request = build_market_order_request(cover_plan, client_order_id="c2", use_bracket_orders=True)
    assert request.kwargs["side"] == _FakeOrderSide.BUY

    assert _is_full_position_exit({**cover_plan, "payload": {**cover_plan["payload"], "recommendation": {"action": "cover"}}}) is True


def test_execution_rejects_fractional_short(fake_alpaca) -> None:
    plan = {
        "symbol": "AAPL",
        "side": "sell",
        "payload": {
            "qty": 1.5,
            "position_effect": "open_short",
            "direction": "short",
        },
    }
    with pytest.raises(RuntimeError, match="entera"):
        build_market_order_request(plan, client_order_id="c3", use_bracket_orders=False)


def test_short_sizing_is_integer_and_capped(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    notional, checks = recommended_short_notional(
        settings,
        _portfolio(),
        _short_recommendation(entry_price=333.0, stop_loss=366.0, take_profit=266.0),
    )
    assert notional >= 100
    assert checks["qty"] == int(checks["qty"])
    assert notional <= 70_000.0 * settings.max_short_position_exposure + 0.01


def test_storage_distinguishes_short_entries(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    plan = {
        "plan_id": "plan_short_1",
        "symbol": "AAPL",
        "side": "sell",
        "notional": 1_000.0,
        "payload": {
            "qty": 10,
            "position_effect": "open_short",
            "direction": "short",
        },
    }
    store.save_order_plan(
        plan_id="plan_short_1",
        cycle_id="cycle_1",
        symbol="AAPL",
        side="sell",
        notional=1_000.0,
        approved=True,
        dry_run=True,
        payload=plan,
    )
    store.save_broker_order(
        broker_order_id="broker_short_1",
        plan_id="plan_short_1",
        cycle_id="cycle_1",
        symbol="AAPL",
        side="sell",
        status="accepted",
        payload={"plan": plan, "broker_order": {"id": "broker_short_1"}},
    )
    entries = store.latest_entry_plans_by_symbol()
    assert entries["AAPL"]["position_effect"] == "open_short"
    assert entries["AAPL"]["direction"] == "short"
    assert store.count_short_entries_since("2000-01-01T00:00:00+00:00") == 1


def test_trade_history_short_round_trip_realizes_profit() -> None:
    from agente_bolsa.tools.trade_history import realized_pl_from_fills

    rows, summary = realized_pl_from_fills(
        [
            {
                "transaction_time": "2026-10-01T14:00:00Z",
                "symbol": "AMD",
                "side": "sell",
                "qty": "10",
                "price": "100",
                "order_id": "short-entry",
            },
            {
                "transaction_time": "2026-10-02T14:00:00Z",
                "symbol": "AMD",
                "side": "buy",
                "qty": "10",
                "price": "90",
                "order_id": "short-cover",
            },
        ]
    )
    assert rows[0]["position_effect"] == "open_short"
    assert rows[1]["position_effect"] == "close_short"
    assert rows[1]["realized_pl"] == pytest.approx(100.0)
    assert summary["realized_pl"] == pytest.approx(100.0)
    assert summary["realized_trades"] == 1


def test_short_position_is_recognised_by_portfolio_helpers() -> None:
    short_position = PositionSnapshot(
        symbol="AAPL",
        qty=-10,
        market_value=-1_000.0,
        avg_entry_price=100.0,
        current_price=100.0,
        unrealized_pl=0.0,
        unrealized_plpc=0.0,
        side="short",
    )
    portfolio = _portfolio(positions=[short_position])
    assert short_position.side == "short" and short_position.qty < 0
    assert portfolio.portfolio_value == 70_000.0


def test_build_order_plans_creates_short_and_cover(tmp_path: Path, monkeypatch) -> None:
    from agente_bolsa.tools import trade_decision as td

    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()

    candidate = {
        "symbol": "AAPL",
        "direction": "short",
        "setup_quality": "strong",
        "score": 12,
        "risk_plan": {"entry_price": 100.0, "stop_loss": 110.0, "take_profit": 80.0},
        "technical_state": {"return_20d": -0.12, "close": 100.0},
    }
    monkeypatch.setattr(td, "load_latest_technical_candidates", lambda *a, **k: {"top_shorts": [candidate], "all_candidates": [candidate]})
    monkeypatch.setattr(td, "load_daily_learning_context", lambda *a, **k: {})
    monkeypatch.setattr(td, "load_operational_response_context", lambda *a, **k: {})
    monkeypatch.setattr(td, "load_operational_block_context", lambda *a, **k: {})
    monkeypatch.setattr(td, "load_research_evidence_context", lambda *a, **k: {})
    monkeypatch.setattr(td, "load_capital_allocation_policy", lambda *a, **k: {})
    monkeypatch.setattr(td, "load_capital_ladder", lambda *a, **k: {})
    monkeypatch.setattr(td, "active_learning_mode", lambda *a, **k: None)
    monkeypatch.setattr(td, "load_post_market_learning_context", lambda *a, **k: {})
    monkeypatch.setattr(td, "load_operational_learning_context", lambda *a, **k: {})
    monkeypatch.setattr(td, "_annotate_technical_context_with_learning", lambda ctx, *a, **k: ctx)
    monkeypatch.setattr(td, "_short_entry_cutoff_reached", lambda s: (False, {"status": "test"}))
    monkeypatch.setattr(td, "earnings_days_by_symbol", lambda *a, **k: {})

    recommendation = _short_recommendation(
        recommendation_id="rec_short_1",
        decision_lineage={"cycle_id": "cycle_1", "signal_id": "sig_1"},
    )
    plans = td.build_order_plans(settings, _portfolio(), [recommendation], dry_run=True)
    shorts = [plan for plan in plans if plan.position_effect == "open_short"]
    assert len(shorts) == 1
    short_plan = shorts[0]
    assert short_plan.side == "sell" and short_plan.direction == "short"
    assert short_plan.qty and float(short_plan.qty).is_integer()
    assert short_plan.risk_decision.checks["borrow"]["status"] == "pending_broker_verification"

    short_position = PositionSnapshot(
        symbol="AAPL",
        qty=-10,
        market_value=-1_000.0,
        avg_entry_price=100.0,
        current_price=115.0,
        unrealized_pl=-150.0,
        unrealized_plpc=-0.15,
        side="short",
    )
    cover = _short_recommendation(
        action="cover",
        confidence=0.9,
        entry_price=100.0,
        stop_loss=110.0,
        take_profit=80.0,
    )
    plans = td.build_order_plans(
        settings,
        _portfolio(positions=[short_position]),
        [cover],
        dry_run=True,
    )
    covers = [plan for plan in plans if plan.position_effect == "close_short"]
    assert len(covers) == 1
    assert covers[0].side == "buy" and covers[0].qty == 10

