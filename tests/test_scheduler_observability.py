from __future__ import annotations

import json

from agente_bolsa.config import Settings
from agente_bolsa.scheduler import _job_state_key, _selected_candidates, scheduler_status
from agente_bolsa.storage import Store


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
