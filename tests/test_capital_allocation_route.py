from dataclasses import asdict

from agente_bolsa.config import Settings
from agente_bolsa.models import (
    OrderSnapshot,
    PortfolioSnapshot,
    PositionSnapshot,
    TradeRecommendation,
)
from agente_bolsa.tools import trade_decision as td


def _setup(monkeypatch, tmp_path, *, active=True):
    s = Settings(_env_file=None, DATA_DIR=str(tmp_path), MAX_TOTAL_OPEN_RISK=0.03,
                 MAX_POSITION_EXPOSURE=0.05, MAX_RISK_PER_TRADE=0.01,
                 USE_BRACKET_ORDERS=True, MIN_ORDER_NOTIONAL=50, MACRO_THESIS_ENABLED=False)
    p = {"stage": 2, "active": active, "status": "guarded_active" if active else "shadow", "policy_hash": "test"}
    monkeypatch.setattr(td, "load_capital_allocation_policy", lambda *a, **kw: p)
    monkeypatch.setattr(td, "active_learning_mode", lambda *a: {"daily_order_budget": 3,
                        "per_trade_notional_usd": 1000, "max_portfolio_exposure_pct": 15})
    monkeypatch.setattr(td, "_sizing_adjustment_for_recommendation", lambda *a: {"size_multiplier": 0.5})
    return s


def _portfolio(cash=3000, orders=None):
    return PortfolioSnapshot(account_id="paper", status="ACTIVE", currency="USD", cash=cash,
        portfolio_value=100_000, buying_power=200_000, positions=[], open_orders=orders or [])


def _buy(symbol, **extra):
    return TradeRecommendation(symbol=symbol, action="buy", confidence=0.9, reason="eligible",
        entry_price=100, stop_loss=95, take_profit=110, target_exposure_pct=0.05, **extra)


def test_active_size_replaces_fixed_cap_without_double_multiplier(monkeypatch, tmp_path):
    s = _setup(monkeypatch, tmp_path)
    plans = td.build_buy_order_plans(s, _portfolio(50_000), [_buy("AAPL")])
    assert len(plans) == 1 and plans[0].notional == 2500 and plans[0].qty == 25
    assert plans[0].risk_decision.checks["position_sizing"]["size_multiplier"] == 0.5


def test_cash_is_reserved_across_plans_and_margin_is_not_used(monkeypatch, tmp_path):
    s = _setup(monkeypatch, tmp_path)
    plans = td.build_buy_order_plans(s, _portfolio(3000), [_buy("AAPL"), _buy("MSFT")])
    assert [p.notional for p in plans] == [2500, 500]
    assert sum(p.notional for p in plans) <= 3000
    assert td.build_buy_order_plans(s, _portfolio(0), [_buy("AAPL")]) == []


def test_pending_buy_reserves_cash_and_unknown_price_blocks(monkeypatch, tmp_path):
    s = _setup(monkeypatch, tmp_path)
    order = OrderSnapshot(order_id="pending", symbol="OTHER", side="buy", qty=None,
                          notional=2000, order_type="market", status="new")
    plans = td.build_buy_order_plans(s, _portfolio(3000, [order]), [_buy("AAPL")])
    assert len(plans) == 1 and plans[0].notional == 1000
    unknown = OrderSnapshot(order_id="unknown", symbol="OTHER", side="buy", qty=10,
                            notional=None, order_type="limit", status="new")
    rejected = []
    assert td.build_buy_order_plans(s, _portfolio(3000, [unknown]), [_buy("AAPL")], rejected=rejected) == []
    assert rejected[0]["reason"] == "allocation_inputs_unavailable"


def test_shadow_keeps_fixed_cap_orders_and_checks_identical(monkeypatch, tmp_path):
    s = _setup(monkeypatch, tmp_path, active=False)
    a = td.build_buy_order_plans(s, _portfolio(50_000), [_buy("AAPL")])
    monkeypatch.setattr(td, "load_capital_allocation_policy", lambda *a, **kw: {"status": "shadow", "active": False})
    b = td.build_buy_order_plans(s, _portfolio(50_000), [_buy("AAPL")])
    assert asdict(a[0]) == asdict(b[0])
    assert a[0].notional == 1000
    assert "capital_allocation" not in a[0].risk_decision.checks["position_sizing"]


def test_zero_micro_multiplier_cannot_turn_into_nonzero_buy(monkeypatch, tmp_path):
    s = _setup(monkeypatch, tmp_path)
    assert td.build_buy_order_plans(s, _portfolio(50_000), [_buy("AAPL", micro_experiment=True, size_multiplier=0)]) == []


def test_blocked_policy_prevents_new_buys_without_lowering_existing_risk(monkeypatch, tmp_path):
    s = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(td, "load_capital_allocation_policy", lambda *a, **kw: {"status": "blocked", "active": False})
    assert td._effective_daily_buy_limit(s, []) == 0
    assert td.build_buy_order_plans(s, _portfolio(50_000), [_buy("AAPL")]) == []


def test_stage_three_uses_four_buy_budget_not_old_learning_three(monkeypatch, tmp_path):
    s = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(td, "load_capital_allocation_policy", lambda *a, **kw: {"stage": 3, "active": True, "status": "guarded_active"})
    assert td._effective_buy_plan_limit(s, [_buy("AAPL")]) == 4
    assert td._effective_daily_buy_limit(s, []) == 4


def test_unknown_existing_stop_risk_blocks_new_buy(monkeypatch, tmp_path):
    s = _setup(monkeypatch, tmp_path)
    portfolio = _portfolio(50_000)
    portfolio.positions.append(PositionSnapshot("OTHER", 10, 1000, 95, 100, 50, 0.05))
    rejected = []
    assert td.build_buy_order_plans(s, portfolio, [_buy("AAPL")], rejected=rejected) == []
    assert rejected[0]["reason"] == "allocation_inputs_unavailable"


def test_allocation_adds_cannot_bypass_missing_added_quantity_protection(monkeypatch, tmp_path):
    s = _setup(monkeypatch, tmp_path).model_copy(update={"allow_position_adds": True})
    monkeypatch.setattr(td, "load_capital_allocation_policy", lambda *a, **kw: {
        "stage": 2, "active": True, "status": "guarded_active", "enable_adds": True})
    portfolio = _portfolio(50_000)
    portfolio.positions.append(PositionSnapshot("AAPL", 10, 1000, 95, 100, 50, 0.05))
    rejected = []
    assert td.build_buy_order_plans(s, portfolio, [_buy("AAPL")], rejected=rejected) == []
    assert rejected[0]["reason"] == "controlled_add_protection_unavailable"


def test_local_pending_is_observed_without_a_second_risk_read(monkeypatch, tmp_path):
    s = _setup(monkeypatch, tmp_path)
    original = td._portfolio_risk_context
    calls = []
    def context(*args):
        calls.append(True)
        return {**original(*args), "pending_buy_notional": 2000,
                "pending_portfolio_exposure": 0.02, "pending_open_risk_amount": 100}
    monkeypatch.setattr(td, "_portfolio_risk_context", context)
    observations = []
    plans = td.build_buy_order_plans(s, _portfolio(3000), [_buy("AAPL")], allocation_observations=observations)
    assert len(calls) == 1
    assert plans[0].notional == 1000
    assert observations[0]["pending_buy_notional"] == 2000
