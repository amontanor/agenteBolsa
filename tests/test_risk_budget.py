"""Tests del presupuesto de riesgo (T4.1)."""

from agente_bolsa.config import Settings
from agente_bolsa.kernel import KernelLimits
from agente_bolsa.risk_budget import (
    RiskBudget,
    can_consume,
    check_order,
    consume,
    fresh_state,
    release,
)
from agente_bolsa.storage import Store


def _settings(tmp_path, **overrides):
    return Settings(DATA_DIR=tmp_path, **overrides)


def _store(settings):
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def test_budget_is_clamped_to_kernel(tmp_path):
    settings = _settings(
        tmp_path,
        RISK_BUDGET_DAILY_VAR_PCT=0.10,
        RISK_BUDGET_MAX_NEW_RISK_PER_DAY_PCT=0.2,
        RISK_BUDGET_MAX_CORRELATED_CLUSTER_PCT=0.2,
    )
    budget = RiskBudget.from_settings(settings)
    limits = KernelLimits()
    assert budget.daily_var_budget_pct == limits.absolute_max_daily_loss_pct
    assert budget.max_new_risk_per_day_pct <= budget.daily_var_budget_pct


def test_consume_and_daily_var_limit():
    budget = RiskBudget(daily_var_budget_pct=0.03, max_new_risk_per_day_pct=0.05, max_correlated_cluster_pct=0.05)
    state = {"date": "9999-01-01", "open_risk_pct": 0.028, "new_risk_today_pct": 0.0, "by_sector": {}}
    # _ensure_today resetea fecha pero conserva open_risk.
    ok, reason = can_consume(budget, state, 0.01, "tech")
    assert not ok
    assert "VaR" in reason


def test_new_risk_daily_limit():
    budget = RiskBudget(daily_var_budget_pct=0.03, max_new_risk_per_day_pct=0.015, max_correlated_cluster_pct=0.05)
    state = consume(fresh_state(), 0.01, "tech")
    ok, reason = can_consume(budget, state, 0.01, "health")
    assert not ok
    assert "riesgo nuevo" in reason


def test_correlated_cluster_limit():
    budget = RiskBudget(daily_var_budget_pct=0.03, max_new_risk_per_day_pct=0.015, max_correlated_cluster_pct=0.012)
    state = consume(fresh_state(), 0.007, "tech")
    blocked, _ = can_consume(budget, state, 0.006, "tech")
    allowed, _ = can_consume(budget, state, 0.006, "health")
    assert not blocked
    assert allowed


def test_release_frees_risk():
    state = consume(fresh_state(), 0.01, "tech")
    state = release(state, 0.01, "tech")
    assert state["open_risk_pct"] == 0.0
    assert state["by_sector"]["tech"] == 0.0


def test_check_order_blocks_when_over_budget(tmp_path):
    settings = _settings(tmp_path, RISK_BUDGET_ENABLED=True)
    store = _store(settings)
    plan = {
        "side": "buy",
        "payload": {
            "sector": "tech",
            "risk_decision": {"checks": {"portfolio_equity": 100000.0, "proposed_trade_risk_amount": 4000.0}},
        },
    }
    # 4000/100000 = 4% > VaR 3% -> bloqueado
    ok, reason = check_order(store, settings, plan)
    assert not ok
    assert "VaR" in reason


def test_check_order_disabled_passes(tmp_path):
    settings = _settings(tmp_path, RISK_BUDGET_ENABLED=False)
    store = _store(settings)
    ok, reason = check_order(store, settings, {"side": "buy", "payload": {}})
    assert ok
    assert reason == "risk_budget_disabled"
