from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.runtime import ContinuousImprovementLabRuntime
from agente_bolsa.continuous_improvement.schemas import Diagnosis, LLMImprovementResponse, LLMJsonResult
from agente_bolsa.scheduler import (
    _exit_policy_v2_stale_guard_trigger,
    _exit_policy_v2_runtime_trigger,
    _exit_policy_v2_time_stop_trigger,
    _job_state_key,
    _selected_candidates,
    continuous_improvement_job,
    overnight_learning_heartbeat_job,
    scheduler_status,
)
from agente_bolsa.storage import Store
from agente_bolsa.tools.overnight_learning import build_overnight_learning_heartbeat


def test_selected_candidates_prioritizes_recent_positive_setup_edge(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latest_daily_learning_digest.json").write_text(
        json.dumps(
            {
                "setup_stats_3d": [
                    {"setup": "event_momentum", "avg_return": 0.08},
                    {"setup": "baseline_trend", "avg_return": 0.01},
                ]
            }
        ),
        encoding="utf-8",
    )
    (reports_dir / "latest_operational_health.json").write_text(
        json.dumps(
            {
                "responses": [
                    {
                        "status": "guarded_active",
                        "action": "deprioritize_setup_before_llm",
                        "scope": "baseline_trend",
                        "candidate_priority_penalty": 0.05,
                        "detail": "baseline_trend degradado",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(DATA_DIR=tmp_path)
    report = {
        "top_longs": [
            {
                "symbol": "BASE",
                "direction": "long",
                "score": 17,
                "setup_quality": "strong",
                "technical_state": {"return_20d": 0.05, "volume_zscore_20": 0.2, "chart_patterns": []},
                "risk_plan": {"entry_price": 100.0, "stop_loss": 95.0, "take_profit": 110.0},
            },
            {
                "symbol": "EDGE",
                "direction": "long",
                "score": 15,
                "setup_quality": "strong",
                "technical_state": {"event_momentum_long": True, "return_20d": 0.25, "volume_zscore_20": 3.0},
                "risk_plan": {"entry_price": 100.0, "stop_loss": 94.0, "take_profit": 112.0},
            },
        ],
        "all_candidates": [
            {
                "symbol": "BASE",
                "direction": "long",
                "score": 17,
                "setup_quality": "strong",
                "technical_state": {"return_20d": 0.05, "volume_zscore_20": 0.2, "chart_patterns": []},
                "risk_plan": {"entry_price": 100.0, "stop_loss": 95.0, "take_profit": 110.0},
            },
            {
                "symbol": "EDGE",
                "direction": "long",
                "score": 15,
                "setup_quality": "strong",
                "technical_state": {"event_momentum_long": True, "return_20d": 0.25, "volume_zscore_20": 3.0},
                "risk_plan": {"entry_price": 100.0, "stop_loss": 94.0, "take_profit": 112.0},
            },
        ],
        "top_shorts": [],
    }

    selected, symbols = _selected_candidates(report, settings)

    assert selected[0]["symbol"] == "EDGE"
    assert selected[0]["setup_name"] == "event_momentum"
    assert selected[0]["setup_edge_3d"] == 0.08
    assert selected[1]["operational_penalty"] == 0.05
    assert selected[1]["operational_notes"] == ["baseline_trend degradado"]
    assert symbols == ["BASE", "EDGE"]


def test_scheduler_status_includes_last_job_runtime(tmp_path):
    settings = Settings(DATA_DIR=tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.set_runtime_value(
        _job_state_key("market_cycle"),
        {
            "job": "market_cycle",
            "status": "completed",
            "run_id": "mkt_test",
            "started_at": "2026-05-09T10:00:00+00:00",
            "finished_at": "2026-05-09T10:00:05+00:00",
            "duration_seconds": 5.0,
            "detail": "ok",
            "extra": {"selected_symbols": ["AAPL"]},
        },
    )

    status = scheduler_status(settings)

    assert status["job_runtime"]["market_cycle"]["status"] == "completed"
    assert status["job_runtime"]["market_cycle"]["extra"]["selected_symbols"] == ["AAPL"]


def test_scheduler_status_includes_overnight_learning_heartbeat(tmp_path):
    settings = Settings(DATA_DIR=tmp_path, OVERNIGHT_LEARNING_TIME_LOCAL="00:10")
    status = scheduler_status(settings)

    job_ids = {job["id"] for job in status["jobs"]}
    assert "overnight_learning_heartbeat" in job_ids


def test_scheduler_status_includes_broker_reconciliation(tmp_path):
    settings = Settings(DATA_DIR=tmp_path)

    status = scheduler_status(settings)

    job_ids = {item["id"] for item in status["jobs"]}
    assert "broker_reconciliation" in job_ids
    assert "broker_reconciliation" in status["job_runtime"]
    assert "overnight_learning_heartbeat" in status["job_runtime"]


def test_overnight_learning_heartbeat_records_llm_usage(tmp_path, monkeypatch):
    settings = Settings(
        DATA_DIR=tmp_path,
        IMPROVEMENT_LLM_ENABLED=True,
        OVERNIGHT_LEARNING_USE_LLM=True,
    )
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()

    class FakeImprovementLLMClient:
        def __init__(self, settings):
            self.settings = settings

        def generate_json(self, messages, schema, *, model, max_tokens):
            return LLMJsonResult(
                ok=True,
                llm_call_id="ci_llm_overnight_test",
                payload=LLMImprovementResponse(
                    diagnosis=Diagnosis(summary="aprendizaje nocturno operativo", confidence="HIGH", data_quality="GOOD"),
                    recommended_next_actions=["mantener observabilidad LLM"],
                ),
                raw_response='{"diagnosis":{"summary":"aprendizaje nocturno operativo"}}',
                provider="fake",
                model=model,
                prompt_tokens_estimate=42,
            )

    monkeypatch.setattr(
        "agente_bolsa.continuous_improvement.llm_client.ImprovementLLMClient",
        FakeImprovementLLMClient,
    )

    report = build_overnight_learning_heartbeat(store, settings, settings.data_dir / "reports", "night_test")

    latest_usage = store.latest_llm_usage(limit=1)[0]
    assert report["status"] == "ok"
    assert report["summary"]["llm_usage_recorded"] is True
    assert latest_usage["source"] == "overnight_learning_heartbeat"
    assert latest_usage["role"] == "overnight_learning"
    assert latest_usage["total_tokens"] > 42


def test_overnight_learning_heartbeat_job_runs_once_per_session(tmp_path, monkeypatch):
    settings = Settings(DATA_DIR=tmp_path, OVERNIGHT_LEARNING_ENABLED=True)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()

    fake_status = SimpleNamespace(
        now_market="2026-06-15T18:30:00-04:00",
        as_dict=lambda: {"now_market": "2026-06-15T18:30:00-04:00"},
    )

    class FakeMarketCalendar:
        def __init__(self, *args, **kwargs):
            pass

        def should_run_daily_study(self):
            return True, fake_status

    calls = {"count": 0}

    def fake_build(store_arg, settings_arg, reports_dir, run_id):
        calls["count"] += 1
        return {
            "path": str(reports_dir / "latest_overnight_learning_heartbeat.json"),
            "status": "ok",
            "summary": {"llm_usage_recorded": True},
            "warnings": [],
        }

    monkeypatch.setattr("agente_bolsa.scheduler.MarketCalendar", FakeMarketCalendar)
    monkeypatch.setattr("agente_bolsa.scheduler.build_overnight_learning_heartbeat", fake_build)

    first = overnight_learning_heartbeat_job(settings, store, verbose=False)
    second = overnight_learning_heartbeat_job(settings, store, verbose=False)

    assert first["status"] == "ok"
    assert second is None
    assert calls["count"] == 1
    assert store.get_runtime_value("overnight_learning_heartbeat_last_session") == "2026-06-15"
    job_state = store.get_runtime_value(_job_state_key("overnight_learning_heartbeat"))
    assert job_state["status"] == "skipped"


def test_exit_policy_v2_time_stop_triggers_for_stale_flat_position(tmp_path):
    settings = Settings(
        DATA_DIR=tmp_path,
        EXIT_POLICY_V2_ENABLED=True,
        EXIT_POLICY_V2_TIME_STOP_DAYS=5,
        EXIT_POLICY_V2_TIME_STOP_MIN_RETURN=0.0,
    )
    position = SimpleNamespace(current_price=101.0, unrealized_plpc=-0.002)
    source_created_at = (datetime.now(timezone.utc) - timedelta(days=6)).isoformat()

    trigger, level = _exit_policy_v2_time_stop_trigger(
        settings,
        position=position,
        source_created_at=source_created_at,
    )

    assert trigger == "time_stop_v2"
    assert level == 101.0


def test_exit_policy_v2_runtime_triggers_partial_once(tmp_path):
    settings = Settings(DATA_DIR=tmp_path, EXIT_POLICY_V2_ENABLED=True)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    source = {"created_at": datetime.now(timezone.utc).isoformat(), "plan": {"plan_id": "plan-1"}}
    payload = {"entry_price": 100.0, "stop_loss": 95.0}
    position = SimpleNamespace(avg_entry_price=100.0, current_price=105.0, unrealized_plpc=0.05)

    trigger = _exit_policy_v2_runtime_trigger(
        settings,
        store,
        symbol="AAPL",
        position=position,
        source=source,
        payload=payload,
    )
    store.set_runtime_value(trigger["state_key"], trigger["state"])
    second = _exit_policy_v2_runtime_trigger(
        settings,
        store,
        symbol="AAPL",
        position=position,
        source=source,
        payload=payload,
    )

    assert trigger["trigger"] == "partial_take_profit_v2"
    assert trigger["qty_fraction"] == 0.5
    assert second is None


def test_exit_policy_v2_runtime_triggers_trailing_after_high_water(tmp_path):
    settings = Settings(DATA_DIR=tmp_path, EXIT_POLICY_V2_ENABLED=True)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    source = {"created_at": datetime.now(timezone.utc).isoformat(), "plan": {"plan_id": "plan-1"}}
    payload = {"entry_price": 100.0, "stop_loss": 95.0}

    first = _exit_policy_v2_runtime_trigger(
        settings,
        store,
        symbol="AAPL",
        position=SimpleNamespace(avg_entry_price=100.0, current_price=112.0, unrealized_plpc=0.12),
        source=source,
        payload=payload,
    )
    store.set_runtime_value(first["state_key"], first["state"])
    trigger = _exit_policy_v2_runtime_trigger(
        settings,
        store,
        symbol="AAPL",
        position=SimpleNamespace(avg_entry_price=100.0, current_price=107.0, unrealized_plpc=0.07),
        source=source,
        payload=payload,
    )

    assert trigger["trigger"] == "trailing_stop_v2"
    assert trigger["level"] == 107.0


def test_exit_policy_v2_stale_guard_triggers_for_nonperformer_position(tmp_path):
    settings = Settings(
        DATA_DIR=tmp_path,
        EXIT_POLICY_V2_ENABLED=True,
        EXIT_POLICY_V2_STALE_GUARD_ENABLED=True,
        EXIT_POLICY_V2_STALE_GUARD_DAYS=10,
        EXIT_POLICY_V2_STALE_GUARD_MAX_PEAK_RETURN=0.05,
        EXIT_POLICY_V2_STALE_GUARD_MIN_RETURN=0.01,
    )
    position = SimpleNamespace(current_price=100.5, unrealized_plpc=0.005)
    source_created_at = (datetime.now(timezone.utc) - timedelta(days=12)).isoformat()

    trigger, level = _exit_policy_v2_stale_guard_trigger(
        settings,
        position=position,
        source_created_at=source_created_at,
        state={"high_water": 104.0},
        entry_price=100.0,
    )

    assert trigger == "stale_guard_v2"
    assert level == 100.5


def test_continuous_improvement_job_persists_retry_metadata_after_failure(tmp_path, monkeypatch):
    settings = Settings(
        DATA_DIR=tmp_path,
        CONTINUOUS_IMPROVEMENT_ENABLED=True,
        CONTINUOUS_IMPROVEMENT_SCHEDULE_ENABLED=True,
        IMPROVEMENT_LLM_ENABLED=False,
        CONTINUOUS_IMPROVEMENT_RUNTIME_INTERVAL_SECONDS=60,
        CONTINUOUS_IMPROVEMENT_RETRY_BASE_SECONDS=180,
        CONTINUOUS_IMPROVEMENT_RETRY_MAX_SECONDS=900,
    )
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()

    def _boom(self):
        raise RuntimeError("scheduler ci timeout")

    monkeypatch.setattr(ContinuousImprovementLabRuntime, "tick", _boom)

    report = continuous_improvement_job(settings, store, verbose=False)

    assert report is None
    job_state = store.get_runtime_value(_job_state_key("continuous_improvement"))
    assert job_state["status"] == "failed"
    assert "Reintento automatico en 180 s" in job_state["detail"]
    assert job_state["extra"]["retry_attempt"] == 1
    runtime_state = store.continuous_improvement_runtime_state()
    assert runtime_state["status"] == "FAILED"
    assert runtime_state["payload"]["error"] == "scheduler ci timeout"
    assert runtime_state["payload"]["retry_delay_seconds"] == 180


def test_continuous_improvement_job_waits_until_retry_window(tmp_path, monkeypatch):
    settings = Settings(
        DATA_DIR=tmp_path,
        CONTINUOUS_IMPROVEMENT_ENABLED=True,
        CONTINUOUS_IMPROVEMENT_SCHEDULE_ENABLED=True,
        IMPROVEMENT_LLM_ENABLED=False,
        CONTINUOUS_IMPROVEMENT_RUNTIME_INTERVAL_SECONDS=60,
        CONTINUOUS_IMPROVEMENT_RETRY_BASE_SECONDS=180,
        CONTINUOUS_IMPROVEMENT_RETRY_MAX_SECONDS=900,
    )
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.set_runtime_value(
        _job_state_key("continuous_improvement"),
        {
            "job": "continuous_improvement",
            "status": "failed",
            "run_id": "ci_prev",
            "started_at": "2026-06-02T16:16:00+00:00",
            "finished_at": "2999-06-02T16:16:01+00:00",
            "duration_seconds": 1.0,
            "detail": "old failure",
            "extra": {
                "error_type": "RuntimeError",
                "retry_attempt": 1,
                "retry_delay_seconds": 180,
                "next_retry_at": "2999-06-02T16:20:00+00:00",
            },
        },
    )
    called = {"value": False}

    def _tick(self):
        called["value"] = True
        return {"status": "COMPLETED"}

    monkeypatch.setattr(ContinuousImprovementLabRuntime, "tick", _tick)

    report = continuous_improvement_job(settings, store, verbose=False)

    assert report is None
    assert called["value"] is False
    job_state = store.get_runtime_value(_job_state_key("continuous_improvement"))
    assert job_state["status"] == "retry_wait"
    assert job_state["extra"]["retry_attempt"] == 1


def test_selected_candidates_promotes_repeated_intraday_momentum_not_selected_by_llm(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latest_daily_learning_digest.json").write_text(json.dumps({}), encoding="utf-8")
    (reports_dir / "latest_operational_health.json").write_text(json.dumps({"responses": []}), encoding="utf-8")
    settings = Settings(DATA_DIR=tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    for idx, price in enumerate([100.0, 104.0, 108.0], start=1):
        store.save_signal_outcome(
            signal_id=f"scan{idx}:HOOD",
            source_run_id=f"scan{idx}",
            source="intraday_scan",
            symbol="HOOD",
            signal_date="2026-05-28",
            decision="candidate",
            features={
                "direction": "long",
                "score": 14,
                "entry_price": price,
                "selected_for_llm": False,
                "rsi_14": 62.0,
                "volume_zscore_20": 0.8,
                "distance_sma20": 0.08,
                "chart_patterns": {"bullish_confirmed_count": 2},
            },
            outcome={},
        )

    report = {
        "as_of": "2026-05-28T19:51:59+00:00",
        "top_longs": [
            {
                "symbol": "BASE",
                "direction": "long",
                "score": 15,
                "setup_quality": "strong",
                "technical_state": {"return_20d": 0.05, "volume_zscore_20": 0.2, "chart_patterns": []},
                "risk_plan": {"entry_price": 100.0, "stop_loss": 95.0, "take_profit": 110.0},
            },
            {
                "symbol": "HOOD",
                "direction": "long",
                "score": 14,
                "setup_quality": "strong",
                "technical_state": {
                    "return_20d": 0.06,
                    "volume_zscore_20": 0.8,
                    "rsi_14": 62.0,
                    "sma_20": 100.0,
                    "close": 108.0,
                    "chart_patterns": [
                        {"bias": "bullish", "status": "confirmed"},
                        {"bias": "bullish", "status": "confirmed"},
                    ],
                },
                "risk_plan": {"entry_price": 108.0, "stop_loss": 102.0, "take_profit": 120.0},
            },
        ],
        "all_candidates": [
            {
                "symbol": "BASE",
                "direction": "long",
                "score": 15,
                "setup_quality": "strong",
                "technical_state": {"return_20d": 0.05, "volume_zscore_20": 0.2, "chart_patterns": []},
                "risk_plan": {"entry_price": 100.0, "stop_loss": 95.0, "take_profit": 110.0},
            },
            {
                "symbol": "HOOD",
                "direction": "long",
                "score": 14,
                "setup_quality": "strong",
                "technical_state": {
                    "return_20d": 0.06,
                    "volume_zscore_20": 0.8,
                    "rsi_14": 62.0,
                    "sma_20": 100.0,
                    "close": 108.0,
                    "chart_patterns": [
                        {"bias": "bullish", "status": "confirmed"},
                        {"bias": "bullish", "status": "confirmed"},
                    ],
                },
                "risk_plan": {"entry_price": 108.0, "stop_loss": 102.0, "take_profit": 120.0},
            },
        ],
        "top_shorts": [],
    }

    selected, _symbols = _selected_candidates(report, settings)

    assert selected[0]["symbol"] == "HOOD"
    assert "same_session_intraday_momentum" in selected[0]["selection_reason"]


def test_selected_candidates_promotes_same_session_leader_even_with_lower_score_and_volume(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latest_daily_learning_digest.json").write_text(json.dumps({}), encoding="utf-8")
    (reports_dir / "latest_operational_health.json").write_text(json.dumps({"responses": []}), encoding="utf-8")
    settings = Settings(DATA_DIR=tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    prices = [100.0, 101.5, 103.0, 104.8, 106.0]
    for idx, price in enumerate(prices, start=1):
        store.save_signal_outcome(
            signal_id=f"scan{idx}:WDAY",
            source_run_id=f"scan{idx}",
            source="intraday_scan",
            symbol="WDAY",
            signal_date="2026-05-29",
            decision="candidate",
            features={
                "direction": "long",
                "score": 13,
                "entry_price": price,
                "selected_for_llm": False,
                "rsi_14": 63.5,
                "volume_zscore_20": -0.2,
                "distance_sma20": 0.15,
                "chart_patterns": {"bullish_confirmed_count": 2},
            },
            outcome={},
        )

    report = {
        "as_of": "2026-05-29T19:51:59+00:00",
        "top_longs": [
            {
                "symbol": "BASE",
                "direction": "long",
                "score": 15,
                "setup_quality": "strong",
                "technical_state": {"return_20d": 0.05, "volume_zscore_20": 0.2, "chart_patterns": []},
                "risk_plan": {"entry_price": 100.0, "stop_loss": 95.0, "take_profit": 110.0},
            },
            {
                "symbol": "WDAY",
                "direction": "long",
                "score": 13,
                "setup_quality": "strong",
                "technical_state": {
                    "return_20d": 0.06,
                    "volume_zscore_20": -0.2,
                    "rsi_14": 63.5,
                    "sma_20": 100.0,
                    "close": 115.0,
                    "chart_patterns": [
                        {"bias": "bullish", "status": "confirmed"},
                        {"bias": "bullish", "status": "confirmed"},
                    ],
                },
                "risk_plan": {"entry_price": 115.0, "stop_loss": 108.0, "take_profit": 127.0},
            },
        ],
        "all_candidates": [
            {
                "symbol": "BASE",
                "direction": "long",
                "score": 15,
                "setup_quality": "strong",
                "technical_state": {"return_20d": 0.05, "volume_zscore_20": 0.2, "chart_patterns": []},
                "risk_plan": {"entry_price": 100.0, "stop_loss": 95.0, "take_profit": 110.0},
            },
            {
                "symbol": "WDAY",
                "direction": "long",
                "score": 13,
                "setup_quality": "strong",
                "technical_state": {
                    "return_20d": 0.06,
                    "volume_zscore_20": -0.2,
                    "rsi_14": 63.5,
                    "sma_20": 100.0,
                    "close": 115.0,
                    "chart_patterns": [
                        {"bias": "bullish", "status": "confirmed"},
                        {"bias": "bullish", "status": "confirmed"},
                    ],
                },
                "risk_plan": {"entry_price": 115.0, "stop_loss": 108.0, "take_profit": 127.0},
            },
        ],
        "top_shorts": [],
    }

    selected, _symbols = _selected_candidates(report, settings)

    assert selected[0]["symbol"] == "WDAY"
    assert "same_session_intraday_leader" in selected[0]["selection_reason"]


def test_selected_candidates_reuses_short_budget_for_longs_when_short_selling_disabled(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latest_daily_learning_digest.json").write_text(json.dumps({}), encoding="utf-8")
    (reports_dir / "latest_operational_health.json").write_text(json.dumps({"responses": []}), encoding="utf-8")
    settings = Settings(DATA_DIR=tmp_path)
    selected_longs = []
    for idx in range(12):
        selected_longs.append(
            {
                "symbol": f"LONG{idx}",
                "direction": "long",
                "score": 20 - idx,
                "setup_quality": "strong",
                "selection_score": 0.05 - (idx * 0.001),
                "technical_state": {
                    "return_20d": 0.08,
                    "volume_zscore_20": 1.0,
                    "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
                },
                "risk_plan": {"entry_price": 100.0, "stop_loss": 95.0, "take_profit": 112.0},
            }
        )
    report = {
        "selected_candidates": selected_longs,
        "top_longs": selected_longs,
        "top_shorts": [
            {
                "symbol": "SHORT0",
                "direction": "short",
                "score": 18,
                "setup_quality": "strong",
                "technical_state": {"return_20d": -0.08, "volume_zscore_20": 1.0, "chart_patterns": []},
                "risk_plan": {"entry_price": 100.0, "stop_loss": 105.0, "take_profit": 90.0},
            }
        ],
    }

    selected, symbols = _selected_candidates(report, settings)

    assert len(selected) == 12
    assert all(item["symbol"].startswith("LONG") for item in selected)
    assert symbols == sorted(f"LONG{i}" for i in range(12))


def test_selected_candidates_uses_trade_selection_top_n_for_long_only(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latest_daily_learning_digest.json").write_text(json.dumps({}), encoding="utf-8")
    (reports_dir / "latest_operational_health.json").write_text(json.dumps({"responses": []}), encoding="utf-8")
    settings = Settings(DATA_DIR=tmp_path, NEWS_SENTIMENT_TOP_N=10, TRADE_SELECTION_TOP_N=16)
    selected_longs = []
    for idx in range(16):
        selected_longs.append(
            {
                "symbol": f"LONG{idx}",
                "direction": "long",
                "score": 20 - idx,
                "setup_quality": "strong",
                "selection_score": 0.05 - (idx * 0.001),
                "technical_state": {
                    "return_20d": 0.08,
                    "volume_zscore_20": 1.0,
                    "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
                },
                "risk_plan": {"entry_price": 100.0, "stop_loss": 95.0, "take_profit": 112.0},
            }
        )
    report = {
        "selected_candidates": selected_longs,
        "top_longs": selected_longs,
        "top_shorts": [],
    }

    selected, symbols = _selected_candidates(report, settings)

    assert len(selected) == 16
    assert symbols == sorted(f"LONG{i}" for i in range(16))
