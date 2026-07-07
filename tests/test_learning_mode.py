from __future__ import annotations

import json

from agente_bolsa.config import Settings
from agente_bolsa.cycle_runner import _learning_mode_backtest_near_miss
from agente_bolsa.models import PortfolioSnapshot, RiskDecision, TradeRecommendation
from agente_bolsa.storage import Store
from agente_bolsa.tools.learning_mode import LEARNING_EXPERIMENT_SOURCE, load_learning_mode_config
from agente_bolsa.tools.trade_decision import (
    build_buy_order_plans,
    deterministic_trade_fallback_recommendations,
)


def _settings(tmp_path) -> Settings:
    return Settings(
        DATA_DIR=tmp_path,
        DATABASE_PATH=tmp_path / "state" / "test.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "logs" / "agents",
        ALPACA_API_KEY="key",
        ALPACA_SECRET_KEY="secret",
        ALLOW_LIVE_TRADING=False,
        TRADING_MODE="paper",
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )


def _portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=20_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[],
        open_orders=[],
    )


def _write_learning_mode(tmp_path, **overrides) -> None:
    path = tmp_path / "config" / "learning_mode.json"
    config = load_learning_mode_config(path)
    config.update(overrides)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def test_learning_mode_config_defaults_are_created(tmp_path):
    path = tmp_path / "config" / "learning_mode.json"

    config = load_learning_mode_config(path)

    assert path.exists()
    assert config["enabled"] is False
    assert config["human_gated"] is True
    assert config["daily_order_budget"] == 3
    assert config["per_trade_notional_usd"] == 1000
    assert config["max_portfolio_exposure_pct"] == 15
    assert config["allowed_strategies"] == ["builtin_breakout", "builtin_pullback"]
    assert config["shadow_first"] is True


def test_signal_outcomes_exclude_learning_experiment_by_default(tmp_path):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="real",
        source_run_id="run-real",
        source="closed_market_study",
        symbol="AAPL",
        signal_date="2026-07-07",
        decision="candidate",
        features={},
    )
    store.save_signal_outcome(
        signal_id="learn",
        source_run_id="run-learn",
        source=LEARNING_EXPERIMENT_SOURCE,
        symbol="MSFT",
        signal_date="2026-07-07",
        decision="candidate",
        features={},
    )

    default_rows = store.signal_outcomes(limit=10, since_date="2026-07-01")
    cohort_rows = store.signal_outcomes(limit=10, since_date="2026-07-01", include_learning_experiment=True)

    assert [row["signal_id"] for row in default_rows] == ["real"]
    assert {row["signal_id"] for row in cohort_rows} == {"real", "learn"}


def test_learning_mode_relaxes_partial_market_state_only_when_enabled(tmp_path):
    candidate = {
        "symbol": "FRT",
        "direction": "long",
        "score": 18,
        "selection_score": 0.04,
        "selection_rank": 1,
        "setup_quality": "strong",
        "technical_state": {
            "close": 100.0,
            "sma_20": 95.0,
            "rsi_14": 67.0,
            "return_20d": 0.08,
            "volume_zscore_20": 1.2,
            "macd": 2.0,
            "macd_signal": 1.0,
        },
        "risk_plan": {"entry_price": 100.0, "stop_loss": 95.0, "take_profit": 112.0},
    }
    market_state = {
        "data_quality": {
            "status": "PARTIAL",
            "notes": ["macro_summary_missing"],
            "data_vendor_quality": "informal",
        }
    }
    blocked = deterministic_trade_fallback_recommendations(
        _settings(tmp_path),
        _portfolio(),
        {"selected_candidates": [candidate]},
        market_state=market_state,
    )
    _write_learning_mode(tmp_path, enabled=True, shadow_first=True)
    allowed = deterministic_trade_fallback_recommendations(
        _settings(tmp_path),
        _portfolio(),
        {"selected_candidates": [candidate]},
        market_state=market_state,
    )

    assert blocked == []
    assert len(allowed) == 1
    assert allowed[0].symbol == "FRT"


def test_learning_mode_caps_per_trade_notional(tmp_path, monkeypatch):
    _write_learning_mode(tmp_path, enabled=True, shadow_first=True, per_trade_notional_usd=1000)
    settings = _settings(tmp_path)
    recommendation = TradeRecommendation(
        symbol="AAPL",
        action="buy",
        confidence=0.9,
        reason="test",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=112.0,
        cohort=LEARNING_EXPERIMENT_SOURCE,
    )
    monkeypatch.setattr(
        "agente_bolsa.tools.trade_decision.load_latest_technical_candidates",
        lambda *args, **kwargs: {"top_longs": [], "top_shorts": []},
    )
    monkeypatch.setattr(
        "agente_bolsa.tools.trade_decision.recommended_notional",
        lambda *args, **kwargs: (2500.0, {"reason": "ok", "size_multiplier": 1.0}),
    )
    monkeypatch.setattr(
        "agente_bolsa.tools.trade_decision.RiskManager.validate_order",
        lambda self, proposal: RiskDecision(approved=True, reason="ok", checks={"proposed_trade_risk_amount": 10.0}),
    )

    plans = build_buy_order_plans(settings, _portfolio(), [recommendation])

    assert len(plans) == 1
    assert plans[0].notional == 1000.0
    assert plans[0].cohort == LEARNING_EXPERIMENT_SOURCE


def test_learning_mode_accepts_backtest_near_miss_but_rejects_clear_trash(tmp_path):
    _write_learning_mode(tmp_path, enabled=True, shadow_first=True)
    settings = _settings(tmp_path)
    near_miss_ok, near_miss_checks = _learning_mode_backtest_near_miss(
        settings,
        {
            "metrics": {"trades": 12, "hit_rate": 0.43, "profit_factor": 0.96, "max_drawdown": -0.03},
            "benchmark": {"metrics": {"trade_window_alpha": -0.004}},
            "regime_summary": {},
        },
    )
    hard_no, hard_no_checks = _learning_mode_backtest_near_miss(
        settings,
        {
            "metrics": {"trades": 7, "hit_rate": 0.50, "profit_factor": 1.10, "max_drawdown": -0.03},
            "benchmark": {"metrics": {"trade_window_alpha": 0.01}},
            "regime_summary": {},
        },
    )

    assert near_miss_ok is True
    assert near_miss_checks["mode"] == "learning_near_miss"
    assert hard_no is False
    assert hard_no_checks["clear_reject"] == "trades_lt_8"
