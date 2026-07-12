from __future__ import annotations

from types import SimpleNamespace

from agente_bolsa.config import Settings
from agente_bolsa.cycle_runner import _auto_paper_trade
from agente_bolsa.models import OrderPlan, RiskDecision, TradeRecommendation
from agente_bolsa.tools.market_cycle_timing import MarketCycleTiming


class _StoreSpy:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.plans: list[dict] = []

    def save_trade_recommendation(self, **_kwargs) -> None:
        self.calls.append("save_trade_recommendation")

    def save_order_plan(self, **kwargs) -> None:
        self.calls.append("save_order_plan")
        self.plans.append({**kwargs, "status": "PENDING"})

    def pending_order_plans(self, **_kwargs):
        return self.plans

    def save_broker_order(self, **_kwargs) -> None:
        self.calls.append("save_broker_order")

    def count_broker_orders(self, **_kwargs) -> int:
        return 0


class _Reporter:
    def emit(self, *_args, **_kwargs) -> None:
        pass


def _patch_trading_flow(monkeypatch, *, shadow: bool = False, fail_backtest: bool = False):
    import agente_bolsa.cycle_runner as runner

    calls: list[str] = []
    recommendation = TradeRecommendation("AAPL", "buy", 0.9, "prueba", entry_price=100, stop_loss=95, take_profit=110)
    plan = OrderPlan("AAPL", "buy", 100.0, 1.0, 100.0, 95.0, 110.0, recommendation, RiskDecision(True, "ok", {}))

    monkeypatch.setattr(runner, "active_learning_mode", lambda _settings: {"shadow_first": True, "shadow_strategies": []} if shadow else None)
    monkeypatch.setattr(runner, "load_daily_learning_context", lambda _path: {})
    monkeypatch.setattr(runner, "load_operational_response_context", lambda _path: {})
    monkeypatch.setattr(runner, "load_operational_block_context", lambda _path: {})
    monkeypatch.setattr(runner, "record_setup_edge_cycle_shadow", lambda *_args: {})
    monkeypatch.setattr(runner, "MarketCalendar", lambda *_args: SimpleNamespace(status=lambda: SimpleNamespace(is_open=True)))
    monkeypatch.setattr(runner, "BrokerClientFactory", lambda _settings: SimpleNamespace(alpaca_portfolio_snapshot=lambda: {}))
    monkeypatch.setattr(runner, "build_portfolio_rebalance_context", lambda *_args: {})
    monkeypatch.setattr(runner, "load_latest_sentiment", lambda _path: {})
    monkeypatch.setattr(runner, "augment_recommendations_with_deterministic_fallback", lambda _settings, _portfolio, _context, items, **_kwargs: (items, {"added": []}))
    monkeypatch.setattr(runner, "request_trade_recommendations", lambda *_args: calls.append("request_trade_recommendations") or {"recommendations": [recommendation]})
    monkeypatch.setattr(runner, "review_recommendations", lambda *_args: (calls.append("review_recommendations") or [recommendation], [{"symbol": "AAPL", "action": "buy", "approved": True}]))
    monkeypatch.setattr(runner, "review_recommendations_adversarial", lambda *_args, **_kwargs: calls.append("review_recommendations_adversarial") or [{"symbol": "AAPL", "action": "buy", "approved": True}])
    monkeypatch.setattr(runner, "_annotate_recommendations_with_strategy", lambda items, *_args: items)
    monkeypatch.setattr(runner, "_annotate_recommendations_with_lineage", lambda items, *_args, **_kwargs: items)
    monkeypatch.setattr(runner, "recommendation_input_fingerprint", lambda *_args, **_kwargs: "fingerprint")
    monkeypatch.setattr(runner, "_apply_entry_quality_gate", lambda *_args, **_kwargs: (calls.append("_apply_entry_quality_gate") or [recommendation], []))

    def backtest(*_args):
        calls.append("_apply_backtest_gate")
        if fail_backtest:
            raise RuntimeError("backtest failed")
        return [recommendation], []

    monkeypatch.setattr(runner, "_apply_backtest_gate", backtest)
    monkeypatch.setattr(runner, "update_signal_decisions", lambda *_args, **_kwargs: calls.append("update_signal_decisions") or 0)
    monkeypatch.setattr(runner, "build_order_plans", lambda *_args, **_kwargs: calls.append("build_order_plans") or [plan])
    monkeypatch.setattr(runner, "_apply_daily_buy_limit", lambda *_args, **_kwargs: calls.append("_apply_daily_buy_limit") or _args[4])
    monkeypatch.setattr(runner, "_apply_low_sample_daily_quota", lambda *_args, **_kwargs: calls.append("_apply_low_sample_daily_quota") or _args[4])
    monkeypatch.setattr(runner, "_separate_strategy_paused_plans", lambda _mode, plans: (calls.append("_separate_strategy_paused_plans") or plans, []))
    monkeypatch.setattr(runner, "_effective_buy_plan_limit", lambda *_args: 1)
    monkeypatch.setattr(runner, "_effective_daily_buy_limit", lambda *_args: 1)
    monkeypatch.setattr(runner, "_low_sample_usage_payload", lambda *_args: {})
    monkeypatch.setattr(runner, "update_signal_execution_status", lambda *_args, **_kwargs: calls.append("update_signal_execution_status") or 1)
    monkeypatch.setattr(runner, "submit_paper_order_plan", lambda *_args, **_kwargs: calls.append("submit_paper_order_plan") or {"id": "broker-1", "status": "accepted"})
    monkeypatch.setattr(runner, "_write_learning_mode_shadow_report", lambda *_args, **_kwargs: calls.append("_write_learning_mode_shadow_report") or "shadow.json")
    return calls


def _run(monkeypatch, tmp_path, *, timing, shadow: bool = False, fail_backtest: bool = False):
    calls = _patch_trading_flow(monkeypatch, shadow=shadow, fail_backtest=fail_backtest)
    store = _StoreSpy()
    settings = Settings(DATA_DIR=tmp_path, AUTO_PAPER_TRADING=True, REQUIRE_HUMAN_APPROVAL=False)
    result = _auto_paper_trade(settings, store, _Reporter(), "cycle", {"run_id": "source"}, {}, {}, timing=timing)
    return result, calls, store


def _segments(report):
    return {stage: {segment["name"] for segment in item.get("segments", [])} for stage, item in report["stages"].items()}


def test_auto_paper_trade_assigns_real_calls_to_the_required_segments(monkeypatch, tmp_path):
    timing = MarketCycleTiming(tmp_path, "integration")
    _result, calls, store = _run(monkeypatch, tmp_path, timing=timing)
    report = timing.finalize("completed")
    segments = _segments(report)

    assert "request_trade_recommendations" in calls
    assert {"structured_recommendations"} <= segments["llm_decision"]
    assert "structured_recommendations" not in segments["deterministic_gates"]
    assert {"deterministic_review", "adversarial_review", "entry_quality_gate", "backtest_gate", "order_plan_build"} <= segments["deterministic_gates"]
    assert {"recommendation_records", "signal_decision_updates", "order_plan_records", "execution_status_updates"} <= segments["persistence"]
    assert {"save_trade_recommendation", "save_order_plan", "save_broker_order"} <= set(store.calls)
    assert "submit_paper_order_plan" in calls
    assert all("submit_paper_order_plan" not in names for names in segments.values())
    assert report["segment_overlap_count"] == 0


def test_shadow_report_and_failed_segment_keep_prior_timing(monkeypatch, tmp_path):
    timing = MarketCycleTiming(tmp_path, "failed")
    try:
        _run(monkeypatch, tmp_path, timing=timing, fail_backtest=True)
    except RuntimeError as exc:
        assert str(exc) == "backtest failed"
    report = timing.finalize("failed")
    assert report["stages"]["llm_decision"]["status"] == "completed"
    assert report["stages"]["deterministic_gates"]["status"] == "failed"
    assert next(item for item in report["stages"]["deterministic_gates"]["segments"] if item["name"] == "backtest_gate")["status"] == "failed"

    shadow_timing = MarketCycleTiming(tmp_path, "shadow")
    _run(monkeypatch, tmp_path, timing=shadow_timing, shadow=True)
    shadow_segments = _segments(shadow_timing.finalize("completed"))
    assert "learning_shadow_report" in shadow_segments["report_generation"]
    assert "execution_status_updates" in shadow_segments["persistence"]


def test_timing_none_preserves_the_observable_flow(monkeypatch, tmp_path):
    without_timing = _run(monkeypatch, tmp_path / "without", timing=None)
    with_timing = _run(monkeypatch, tmp_path / "with", timing=MarketCycleTiming(tmp_path / "with", "with"))

    assert without_timing[0] == with_timing[0]
    assert without_timing[1] == with_timing[1]
    assert without_timing[2].calls == with_timing[2].calls


def test_comparable_capture_uses_final_plans_after_real_filters(monkeypatch, tmp_path):
    import agente_bolsa.cycle_runner as runner

    calls = _patch_trading_flow(monkeypatch)
    captured: dict[str, object] = {}

    def capture(**kwargs):
        calls.append("comparable_control_capture")
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(runner, "build_comparable_control_sets", capture)
    store = _StoreSpy()
    settings = Settings(DATA_DIR=tmp_path, AUTO_PAPER_TRADING=True, REQUIRE_HUMAN_APPROVAL=False)
    runner._auto_paper_trade(settings, store, _Reporter(), "cycle", {"run_id": "source"}, {}, {})
    assert calls.index("build_order_plans") < calls.index("_apply_daily_buy_limit")
    assert calls.index("_apply_low_sample_daily_quota") < calls.index("_separate_strategy_paused_plans")
    assert calls.index("_separate_strategy_paused_plans") < calls.index("comparable_control_capture")
    assert len(captured["plans"]) == 1
    assert captured["rejected_order_plans"] == []
