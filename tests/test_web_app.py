from datetime import datetime
from types import SimpleNamespace

from agente_bolsa.config import Settings
from agente_bolsa.llm_usage import usage_tokens
from agente_bolsa.models import OrderSnapshot, PortfolioSnapshot, PositionSnapshot
from agente_bolsa.storage import Store
from agente_bolsa.eventing import _format_time
from agente_bolsa.web_app import (
    _ci_task_activity,
    _create_manual_opportunity_plan,
    _estimated_portfolio_value_series,
    _latest_llm_context_by_symbol,
    _latest_daily_equity_change,
    _local_datetime,
    _llm_status_reason,
    _manual_opportunity_recommendation,
    _next_opportunity_snapshot_run_text,
    _opportunity_candidates,
    _opportunity_risk_plan,
    _opportunity_status,
    _portfolio_chart_visible_summary,
    _portfolio_value_series_from_alpaca,
    _sidebar_version_label,
    _trim_portfolio_chart_range,
)


def test_usage_tokens_reads_compatible_llm_usage_object():
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=8, total_tokens=20),
    )

    assert usage_tokens(response) == {
        "prompt_tokens": 12,
        "completion_tokens": 8,
        "total_tokens": 20,
    }


def test_usage_tokens_estimates_missing_local_backend_usage():
    response = SimpleNamespace(
        usage=None,
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content='{"recommendations":[]}')
            )
        ],
    )

    tokens = usage_tokens(response, prompt=[{"role": "user", "content": "x" * 40}])

    assert tokens["prompt_tokens"] > 0
    assert tokens["completion_tokens"] > 0
    assert tokens["total_tokens"] == tokens["prompt_tokens"] + tokens["completion_tokens"]


def test_store_daily_llm_usage_counts_requests_and_tokens(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()

    store.record_llm_usage(
        usage_id="usage_1",
        source="test",
        model="gpt-test",
        request_count=1,
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        payload={},
    )
    store.record_llm_usage(
        usage_id="usage_2",
        source="test",
        model="gpt-test",
        request_count=1,
        prompt_tokens=7,
        completion_tokens=3,
        total_tokens=10,
        payload={},
    )

    rows = store.daily_llm_usage()

    assert rows[0]["requests"] == 2
    assert rows[0]["prompt_tokens"] == 17
    assert rows[0]["completion_tokens"] == 8
    assert rows[0]["total_tokens"] == 25


def test_portfolio_value_series_from_alpaca_builds_daily_changes():
    payload = {
        "timestamp": [
            "2026-05-08T00:00:00Z",
            "2026-05-09T00:00:00Z",
            "2026-05-10T00:00:00Z",
        ],
        "equity": [1000.0, 1015.0, 1005.0],
    }

    df = _portfolio_value_series_from_alpaca(payload, current_equity=None, start_date="2026-05-01")

    assert list(df["fecha"]) == ["2026-05-08", "2026-05-09", "2026-05-10"]
    assert list(df["valor_cartera"]) == [1000.0, 1015.0, 1005.0]
    assert list(df["P/L dia"]) == [0.0, 15.0, -10.0]
    assert list(df["fuente"]) == ["Alpaca", "Alpaca", "Alpaca"]


def test_trim_portfolio_chart_range_keeps_latest_window():
    df = _portfolio_value_series_from_alpaca(
        {
            "timestamp": [
                "2026-05-06T00:00:00Z",
                "2026-05-07T00:00:00Z",
                "2026-05-08T00:00:00Z",
                "2026-05-09T00:00:00Z",
            ],
            "equity": [1000.0, 1001.0, 1002.0, 1003.0],
        },
        current_equity=None,
        start_date="2026-05-01",
    )

    trimmed = _trim_portfolio_chart_range(df, days=2)

    assert list(trimmed["fecha"]) == ["2026-05-08", "2026-05-09"]
    assert list(trimmed["valor_cartera"]) == [1002.0, 1003.0]


def test_estimated_portfolio_value_series_still_available_as_fallback():
    history = {
        "days": [
            {"date": "2026-05-11", "realized_pl": 10.0, "open_unrealized_pl": 0.0, "buy_notional": 1000.0},
            {"date": "2026-05-12", "realized_pl": -5.0, "open_unrealized_pl": 0.0, "sell_notional": 500.0},
        ]
    }

    df = _estimated_portfolio_value_series(history, current_equity=1005.0, days=2)

    assert list(df["valor_cartera"]) == [1010.0, 1005.0]
    assert list(df["P/L dia"]) == [10.0, -5.0]
    assert list(df["fuente"]) == ["estimado", "estimado"]


def test_portfolio_chart_visible_summary_uses_visible_window_change():
    df = _portfolio_value_series_from_alpaca(
        {
            "timestamp": [
                "2026-05-06T00:00:00Z",
                "2026-05-07T00:00:00Z",
                "2026-05-08T00:00:00Z",
                "2026-05-09T00:00:00Z",
            ],
            "equity": [1000.0, 1020.0, 1010.0, 1035.0],
        },
        current_equity=None,
        start_date="2026-05-01",
    )

    trimmed = _trim_portfolio_chart_range(df, days=3)
    summary = _portfolio_chart_visible_summary(trimmed)

    assert summary["days"] == 3
    assert summary["pl"] == 15.0
    assert summary["pl_pct"] == 0.014706


def test_latest_daily_equity_change_prefers_alpaca_daily_delta():
    payload = {
        "timestamp": [
            "2026-05-22T00:00:00Z",
            "2026-05-23T00:00:00Z",
            "2026-05-26T00:00:00Z",
        ],
        "equity": [70719.88, 71081.25, 71072.78],
    }

    change = _latest_daily_equity_change(history={}, current_equity=None, portfolio_history=payload)

    assert change["equity"] == 71072.78
    assert change["pl"] == -8.47
    assert change["pl_pct"] == -0.000119
    assert change["source"] == "Alpaca"


def test_latest_daily_equity_change_falls_back_to_estimated_series():
    history = {
        "days": [
            {"date": "2026-05-25", "realized_pl": 10.0, "open_unrealized_pl": 0.0, "buy_notional": 1000.0},
            {"date": "2026-05-26", "realized_pl": -5.0, "open_unrealized_pl": 0.0, "sell_notional": 500.0},
        ]
    }

    change = _latest_daily_equity_change(history=history, current_equity=1005.0, portfolio_history={})

    assert change["equity"] == 1005.0
    assert change["pl"] == -5.0
    assert change["pl_pct"] == -0.00495
    assert change["source"] == "estimado"


def test_sidebar_version_label_uses_semantic_version():
    assert _sidebar_version_label() == "v0.1.6"


def test_local_datetime_renders_spain_dst_from_utc():
    assert _local_datetime("2026-05-29T18:00:00+00:00", "Europe/Madrid") == "2026-05-29 20:00:00"


def test_eventing_format_time_treats_naive_timestamps_as_utc():
    assert _format_time("2026-05-29T18:00:00", "Europe/Madrid") == "20:00:00"


def test_next_opportunity_snapshot_run_text_same_day():
    settings = Settings(OPPORTUNITY_SNAPSHOT_TIMES_LOCAL="16:00,19:00,21:00", LOCAL_TIMEZONE="Europe/Madrid")

    result = _next_opportunity_snapshot_run_text(
        settings,
        now_local=datetime.fromisoformat("2026-05-28T18:15:00+02:00"),
    )

    assert result == "2026-05-28 19:00"


def test_next_opportunity_snapshot_run_text_next_day_after_last_slot():
    settings = Settings(OPPORTUNITY_SNAPSHOT_TIMES_LOCAL="16:00,19:00,21:00", LOCAL_TIMEZONE="Europe/Madrid")

    result = _next_opportunity_snapshot_run_text(
        settings,
        now_local=datetime.fromisoformat("2026-05-28T21:15:00+02:00"),
    )

    assert result == "2026-05-29 16:00"


def test_ci_task_activity_groups_messages_by_initiative_event():
    tasks = [
        {
            "task_id": "task_market",
            "event_id": "evt_1",
            "agent_name": "MarketEstimatorAgent",
            "status": "COMPLETED",
            "payload": {"focus": "market_regime"},
        },
        {
            "task_id": "task_strategy",
            "event_id": "evt_1",
            "agent_name": "StrategyEvaluatorAgent",
            "status": "RUNNING",
            "payload": {"focus": "strategy_validation"},
        },
    ]
    events = [
        {
            "event_id": "raw_1",
            "cycle_id": "ci_cycle_test",
            "agent": "MarketEstimatorAgent",
            "event_type": "lab_task_completed",
            "payload_json": '{"task_id":"task_market","event_id":"evt_1","summary":"mercado listo"}',
            "created_at": "2026-05-29T18:00:00+00:00",
        },
        {
            "event_id": "raw_2",
            "cycle_id": "ci_cycle_test",
            "agent": "StrategyEvaluatorAgent",
            "event_type": "lab_task_started",
            "payload_json": '{"task_id":"task_strategy","event_id":"evt_1","focus":"strategy_validation"}',
            "created_at": "2026-05-29T18:01:00+00:00",
        },
    ]

    grouped = _ci_task_activity(events, tasks, cycle_id="ci_cycle_test")

    assert len(grouped) == 1
    assert grouped[0]["initiative_id"] == "evt_1"
    assert set(grouped[0]["agent_names"]) == {"MarketEstimatorAgent", "StrategyEvaluatorAgent"}
    assert len(grouped[0]["messages"]) == 2


def _opportunity_candidate(symbol: str, **overrides):
    candidate = {
        "symbol": symbol,
        "direction": "long",
        "score": 15.0,
        "selection_score": 0.05,
        "rank_priority_score": 0.03,
        "selection_rank": 1,
        "setup_name": "orderly_breakout",
        "setup_quality": "strong",
        "reasons": ["momentum 20d positivo", "volumen confirma subida"],
        "technical_state": {
            "close": 105.0,
            "return_5d": 0.04,
            "return_20d": 0.12,
            "return_60d": 0.18,
            "sma_20": 100.0,
            "sma_50": 95.0,
            "sma_200": 80.0,
            "rsi_14": 64.0,
            "atr_14": 3.5,
            "volume_zscore_20": 1.6,
            "breakout_failure_risk": False,
            "candle_patterns": ["bullish_engulfing"],
            "chart_patterns": [{"label": "Bull flag", "pattern": "flag"}],
        },
        "risk_plan": {
            "entry_price": 105.0,
            "stop_loss": 99.0,
            "take_profit": 117.0,
            "reward_risk": 2.0,
            "invalidation": "Pierde soporte dinamico.",
            "time_stop": "5-10 sesiones",
        },
    }
    candidate.update(overrides)
    return candidate


def _portfolio_snapshot(*, positions=None, open_orders=None, buying_power=10000.0, portfolio_value=20000.0):
    return PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=buying_power,
        portfolio_value=portfolio_value,
        buying_power=buying_power,
        positions=positions or [],
        open_orders=open_orders or [],
    )


def test_opportunity_candidates_deduplicates_filters_long_and_limits():
    repeated = _opportunity_candidate("AAPL", selection_score=0.07)
    context = {
        "selected_candidates": [repeated],
        "top_longs": [_opportunity_candidate("AAPL", selection_score=0.04)],
        "all_candidates": [
            _opportunity_candidate(f"SYM{i:02d}", selection_score=0.06 - (i * 0.001))
            for i in range(25)
        ] + [
            _opportunity_candidate("TSLA", direction="short", selection_score=0.99),
        ],
    }

    result = _opportunity_candidates(context, limit=20)

    assert len(result) == 20
    assert result[0]["symbol"] == "AAPL"
    assert len([item for item in result if item["symbol"] == "AAPL"]) == 1
    assert all(item["direction"] == "long" for item in result)


def test_opportunity_candidates_sort_uses_fallbacks():
    strongest_selection = _opportunity_candidate("AAA", selection_score=0.08, rank_priority_score=0.01, score=10)
    strongest_priority = _opportunity_candidate("BBB", selection_score=None, rank_priority_score=0.07, score=18)
    strongest_score = _opportunity_candidate("CCC", selection_score=None, rank_priority_score=None, score=22)

    result = _opportunity_candidates(
        {"selected_candidates": [strongest_score, strongest_priority, strongest_selection]},
        limit=20,
    )

    assert [item["symbol"] for item in result] == ["AAA", "BBB", "CCC"]


def test_opportunity_risk_plan_extracts_values_and_fallbacks():
    candidate = _opportunity_candidate("NVDA")

    risk = _opportunity_risk_plan(candidate)

    assert risk["current_price"] == 105.0
    assert risk["entry_price"] == 105.0
    assert risk["stop_loss"] == 99.0
    assert risk["take_profit"] == 117.0
    assert risk["reward_risk"] == 2.0


def test_opportunity_status_reports_pending_plan():
    candidate = _opportunity_candidate("AAPL")
    status = _opportunity_status(
        candidate,
        portfolio=_portfolio_snapshot(),
        pending_plans_by_symbol={"AAPL": {"plan_id": "plan_1"}},
        settings=Settings(),
        llm_context=None,
    )

    assert status["label"] == "Plan pendiente"


def test_opportunity_status_reports_open_order():
    candidate = _opportunity_candidate("AAPL")
    portfolio = _portfolio_snapshot(open_orders=[OrderSnapshot("ord_1", "AAPL", "buy", 1.0, None, "market", "new")])

    status = _opportunity_status(
        candidate,
        portfolio=portfolio,
        pending_plans_by_symbol={},
        settings=Settings(),
        llm_context=None,
    )

    assert status["label"] == "Orden abierta"


def test_opportunity_status_reports_existing_position():
    candidate = _opportunity_candidate("AAPL")
    portfolio = _portfolio_snapshot(
        positions=[PositionSnapshot("AAPL", 2.0, 210.0, 100.0, 105.0, 10.0, 0.05)],
    )

    status = _opportunity_status(
        candidate,
        portfolio=portfolio,
        pending_plans_by_symbol={},
        settings=Settings(),
        llm_context=None,
    )

    assert status["label"] == "Posicion abierta"


def test_opportunity_status_reports_blocked_auto_buy():
    candidate = _opportunity_candidate("AAPL", blocked_auto_buy=True, blocked_auto_buy_reason="shadow_only")

    status = _opportunity_status(
        candidate,
        portfolio=_portfolio_snapshot(),
        pending_plans_by_symbol={},
        settings=Settings(AUTO_PAPER_TRADING=True, REQUIRE_HUMAN_APPROVAL=False),
        llm_context=None,
    )

    assert status["label"] == "Bloqueada auto-compra"
    assert "shadow_only" in status["reason"]


def test_opportunity_status_uses_llm_context_when_available():
    candidate = _opportunity_candidate("AAPL")
    llm_context = {
        "decision": "hold",
        "explanation": "El LLM ve setup correcto pero aun no confirma entrada.",
        "approved_buy": False,
    }

    status = _opportunity_status(
        candidate,
        portfolio=_portfolio_snapshot(),
        pending_plans_by_symbol={},
        settings=Settings(AUTO_PAPER_TRADING=True, REQUIRE_HUMAN_APPROVAL=False),
        llm_context=llm_context,
    )

    assert status["label"] == "LLM hold"
    assert "aun no confirma entrada" in status["reason"]


def test_llm_status_reason_marks_approved_buy():
    tone, label, reason = _llm_status_reason(
        {"decision": "buy", "approved_buy": True, "explanation": "Aprobada por momentum y riesgo controlado."}
    )

    assert tone == "good"
    assert label == "LLM aprobo compra"
    assert "momentum" in reason


def test_latest_llm_context_by_symbol_prefers_learning_observations(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.upsert_learning_observation(
        {
            "observation_id": "obs_1",
            "signal_date": "2026-05-27",
            "symbol": "AAPL",
            "source_family": "closed_market_study",
            "best_signal_id": "sig_1",
            "best_score": 17.0,
            "decision": "hold",
            "explanation": "El LLM espera confirmacion adicional antes de comprar.",
            "llm_considered": True,
            "approved_buy": False,
            "blocked_entry_quality": True,
            "blocked_backtest": False,
            "executed_buy": False,
            "gate": {"llm": {"reason": "setup valido pero entrada aun floja"}},
            "features": {},
            "outcome": {},
            "execution": {},
            "rank_path": [],
        }
    )

    context = _latest_llm_context_by_symbol(store, ["AAPL"])

    assert context["AAPL"]["source"] == "learning_observations"
    assert context["AAPL"]["decision"] == "hold"
    assert context["AAPL"]["blocked_entry_quality"] is True
    assert "confirmacion adicional" in context["AAPL"]["explanation"]


def test_manual_opportunity_recommendation_keeps_valid_stop_take():
    candidate = _opportunity_candidate("MSFT")
    recommendation = _manual_opportunity_recommendation(candidate, Settings())

    assert recommendation.symbol == "MSFT"
    assert recommendation.action == "buy"
    assert recommendation.entry_price == 105.0
    assert recommendation.stop_loss == 99.0
    assert recommendation.take_profit == 117.0
    assert recommendation.source == "manual_opportunity_screen"


def test_create_manual_opportunity_plan_saves_pending_plan(tmp_path):
    settings = Settings(
        DATA_DIR=tmp_path,
        AUTO_PAPER_TRADING=False,
        REQUIRE_HUMAN_APPROVAL=True,
        MAX_POSITION_EXPOSURE=0.10,
        MAX_PORTFOLIO_EXPOSURE=0.80,
        MIN_ORDER_NOTIONAL=100.0,
    )
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    candidate = _opportunity_candidate("AAPL")
    portfolio = _portfolio_snapshot(buying_power=5000.0, portfolio_value=20000.0)

    result = _create_manual_opportunity_plan(
        candidate=candidate,
        settings=settings,
        store=store,
        portfolio=portfolio,
    )

    assert result["ok"] is True
    pending = store.pending_order_plans(limit=20)
    assert len(pending) == 1
    assert pending[0]["symbol"] == "AAPL"
    assert pending[0]["plan_id"] == result["plan_id"]
