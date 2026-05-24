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
                "score": 17,
                "technical_state": {"return_20d": 0.05, "volume_zscore_20": 0.2, "chart_patterns": []},
            },
            {
                "symbol": "EDGE",
                "score": 15,
                "technical_state": {"event_momentum_long": True, "return_20d": 0.25, "volume_zscore_20": 3.0},
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
