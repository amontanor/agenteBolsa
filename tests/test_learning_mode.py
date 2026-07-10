from __future__ import annotations

import json
from types import SimpleNamespace

from agente_bolsa.config import Settings
from agente_bolsa.cycle_runner import (
    _apply_backtest_gate,
    _learning_mode_backtest_near_miss,
    _low_sample_runtime_key,
    _market_session_date,
    _separate_strategy_paused_plans,
    _write_learning_mode_shadow_report,
)
from agente_bolsa.models import PortfolioSnapshot, RiskDecision, TradeRecommendation
from agente_bolsa.storage import Store
from agente_bolsa.tools.learning_mode import (
    LEARNING_EXPERIMENT_SOURCE,
    LOW_SAMPLE_EXPLORATION_TAG,
    load_learning_mode_config,
)
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
    assert config["shadow_strategies"] == []
    assert config["shadow_first"] is True


def _plan(symbol: str, strategy_name: str):
    return SimpleNamespace(
        symbol=symbol,
        side="buy",
        notional=1000.0,
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        backtest_soft_override=False,
        micro_experiment=False,
        recommendation=SimpleNamespace(
            reason="test",
            source="deterministic_fallback",
            tags=[f"strategy:{strategy_name}"],
        ),
    )


def test_strategy_pause_keeps_gated_plan_out_of_execution_and_records_shadow(tmp_path):
    settings = _settings(tmp_path)
    pullback = _plan("PULL", "builtin_pullback")
    breakout = _plan("BRK", "builtin_breakout")

    executable, paused = _separate_strategy_paused_plans(
        {"shadow_strategies": ["builtin_pullback"]},
        [pullback, breakout],
    )

    assert executable == [breakout]
    assert paused == [(pullback, "builtin_pullback")]
    path = _write_learning_mode_shadow_report(
        settings,
        run_id="run-pause",
        recommendations=[],
        plans=[plan for plan, _ in paused],
        rejected=[],
        paused_strategies=["builtin_pullback"],
    )
    payload = json.loads(open(path, encoding="utf-8").read())
    assert payload["would_buy"] == [
        {
            "symbol": "PULL",
            "notional": 1000.0,
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "take_profit": 110.0,
            "reason": "test",
            "source": "deterministic_fallback",
            "strategy_name": "builtin_pullback",
            "shadow_reason": "strategy_paused",
            "backtest_soft_override": False,
            "micro_experiment": False,
        }
    ]


def test_strategy_pause_empty_or_unknown_list_preserves_current_behavior():
    plan = _plan("BRK", "builtin_breakout")

    executable, paused = _separate_strategy_paused_plans({"shadow_strategies": []}, [plan])
    assert executable == [plan]
    assert paused == []

    executable, paused = _separate_strategy_paused_plans({"shadow_strategies": ["unknown_strategy"]}, [plan])
    assert executable == [plan]
    assert paused == []


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


class _Reporter:
    def emit(self, *args, **kwargs):  # pragma: no cover - helper sin comportamiento.
        return None


def test_learning_mode_allows_low_sample_exception_when_only_failure_is_sample(tmp_path, monkeypatch):
    _write_learning_mode(tmp_path, enabled=True, shadow_first=False, low_sample_daily_quota=1)
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    recommendation = TradeRecommendation(symbol="AAPL", action="buy", confidence=0.8, reason="test")
    monkeypatch.setattr(
        "agente_bolsa.cycle_runner.build_symbol_backtest",
        lambda *args, **kwargs: {
            "metrics": {"trades": 6, "hit_rate": 0.43, "profit_factor": 0.97, "max_drawdown": -0.03},
            "benchmark": {"metrics": {"trade_window_alpha": -0.004}},
            "regime_summary": {},
            "path": "bt.json",
        },
    )

    kept, decisions = _apply_backtest_gate(settings, store, _Reporter(), "run-low-sample", [recommendation])

    assert len(kept) == 1
    assert kept[0].micro_experiment is True
    assert LOW_SAMPLE_EXPLORATION_TAG in kept[0].tags
    assert decisions[0]["approved"] is True
    assert "aprobada por excepcion low-sample" in decisions[0]["reason"]


def test_learning_mode_rejects_low_sample_when_hit_rate_is_bad(tmp_path, monkeypatch):
    _write_learning_mode(tmp_path, enabled=True, shadow_first=False, low_sample_daily_quota=1)
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    recommendation = TradeRecommendation(symbol="AAPL", action="buy", confidence=0.8, reason="test")
    monkeypatch.setattr(
        "agente_bolsa.cycle_runner.build_symbol_backtest",
        lambda *args, **kwargs: {
            "metrics": {"trades": 6, "hit_rate": 0.38, "profit_factor": 0.97, "max_drawdown": -0.03},
            "benchmark": {"metrics": {"trade_window_alpha": -0.004}},
            "regime_summary": {},
            "path": "bt.json",
        },
    )

    kept, decisions = _apply_backtest_gate(settings, store, _Reporter(), "run-low-sample-bad-hr", [recommendation])

    assert kept == []
    assert decisions[0]["approved"] is False
    assert "hit-rate" in decisions[0]["reason"]


def test_learning_mode_rejects_second_low_sample_of_day(tmp_path, monkeypatch):
    _write_learning_mode(tmp_path, enabled=True, shadow_first=False, low_sample_daily_quota=1)
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    session_date = _market_session_date(settings)
    store.set_runtime_value(
        _low_sample_runtime_key(session_date),
        {
            "session_date": session_date,
            "quota": 1,
            "orders": [{"run_id": "prev", "plan_id": "plan-prev", "symbol": "MSFT", "recorded_at": "2026-07-08T10:00:00+00:00"}],
        },
    )
    recommendation = TradeRecommendation(symbol="AAPL", action="buy", confidence=0.8, reason="test")
    monkeypatch.setattr(
        "agente_bolsa.cycle_runner.build_symbol_backtest",
        lambda *args, **kwargs: {
            "metrics": {"trades": 6, "hit_rate": 0.43, "profit_factor": 0.97, "max_drawdown": -0.03},
            "benchmark": {"metrics": {"trade_window_alpha": -0.004}},
            "regime_summary": {},
            "path": "bt.json",
        },
    )

    kept, decisions = _apply_backtest_gate(settings, store, _Reporter(), "run-low-sample-full", [recommendation])

    assert kept == []
    assert decisions[0]["approved"] is False
    assert decisions[0]["checks"]["clear_reject"] == "low_sample_daily_quota_exhausted"


def test_learning_mode_can_disable_low_sample_quota(tmp_path, monkeypatch):
    _write_learning_mode(tmp_path, enabled=True, shadow_first=False, low_sample_daily_quota=0)
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    recommendation = TradeRecommendation(symbol="AAPL", action="buy", confidence=0.8, reason="test")
    monkeypatch.setattr(
        "agente_bolsa.cycle_runner.build_symbol_backtest",
        lambda *args, **kwargs: {
            "metrics": {"trades": 6, "hit_rate": 0.43, "profit_factor": 0.97, "max_drawdown": -0.03},
            "benchmark": {"metrics": {"trade_window_alpha": -0.004}},
            "regime_summary": {},
            "path": "bt.json",
        },
    )

    kept, decisions = _apply_backtest_gate(settings, store, _Reporter(), "run-low-sample-off", [recommendation])

    assert kept == []
    assert decisions[0]["approved"] is False
    assert decisions[0]["checks"]["clear_reject"] == "low_sample_daily_quota_disabled"
