from __future__ import annotations

import json

from agente_bolsa.config import Settings
from agente_bolsa.main import build_parser
from agente_bolsa.storage import Store
from agente_bolsa.tools.operational_health import (
    build_operational_health_report,
    build_production_health_report,
    load_operational_block_context,
)


def test_operational_health_command_is_parseable():
    parser = build_parser()
    args = parser.parse_args(["operational-health"])
    assert args.command == "operational-health"
    args = parser.parse_args(["operational-responses"])
    assert args.command == "operational-responses"
    args = parser.parse_args(["production-health"])
    assert args.command == "production-health"


def test_operational_health_flags_failed_job_and_degrading_setup(tmp_path):
    settings = Settings(DATA_DIR=tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.set_runtime_value(
        "scheduler_job_status:market_cycle",
        {
            "job": "market_cycle",
            "status": "failed",
            "run_id": "mkt_fail",
            "started_at": "2026-05-09T10:00:00+00:00",
            "finished_at": "2026-05-09T10:10:00+00:00",
            "duration_seconds": 600.0,
            "detail": "broker sync timeout",
            "extra": {"error_type": "TimeoutError"},
        },
    )
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latest_closed_market_technical_study.json").write_text(
        json.dumps(
            {
                "symbols_scanned": 100,
                "symbols_with_data": 80,
                "market_data": {"requested_count": 100, "missing_symbols_count": 20},
                "warnings": ["AAPL: sin datos"],
            }
        ),
        encoding="utf-8",
    )
    (reports_dir / "latest_daily_learning_digest.json").write_text(
        json.dumps(
            {
                "setup_stats_3d": [
                    {"setup": "baseline_trend", "matured": 8, "avg_return": -0.02, "win_rate": 0.25}
                ]
            }
        ),
        encoding="utf-8",
    )
    (reports_dir / "latest_post_market_learning.json").write_text(
        json.dumps({"pipeline_steps": {"learning_pipeline_seconds": 30.0}}),
        encoding="utf-8",
    )

    report = build_operational_health_report(settings, store, reports_dir, "ops_test")

    assert report["summary"]["overall_status"] == "critical"
    kinds = {item["kind"] for item in report["alerts"]}
    assert "job_failed" in kinds
    assert "market_data_coverage_drop" in kinds
    assert "setup_edge_deterioration" in kinds
    actions = {item["action"] for item in report["responses"]}
    assert "deprioritize_setup_before_llm" in actions
    assert "pause_recent_universe_overlays" in actions


def test_operational_block_context_activates_kill_switch_on_critical_alerts(tmp_path):
    settings = Settings(DATA_DIR=tmp_path)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latest_operational_health.json").write_text(
        json.dumps(
            {
                "as_of": "2026-05-13T10:00:00+00:00",
                "alerts": [
                    {
                        "severity": "critical",
                        "kind": "job_failed",
                        "job": "market_cycle",
                        "detail": "broker sync timeout",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    block = load_operational_block_context(settings.data_dir)

    assert block["kill_switch_active"] is True
    assert block["block_new_buys"] is True
    assert block["block_buy_execution"] is True
    assert block["blocking_alerts"][0]["kind"] == "job_failed"


def test_production_health_report_combines_operational_and_ci_runtime(tmp_path):
    settings = Settings(DATA_DIR=tmp_path, CONTINUOUS_IMPROVEMENT_RUNTIME_INTERVAL_SECONDS=60)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.upsert_continuous_improvement_runtime_state(
        runtime_name="lab",
        status="IDLE",
        heartbeat_at="2026-05-01T00:00:00+00:00",
        payload={"mode": "scheduled"},
    )
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latest_closed_market_technical_study.json").write_text(
        json.dumps(
            {
                "symbols_scanned": 100,
                "symbols_with_data": 100,
                "market_data": {"requested_count": 100, "missing_symbols_count": 0},
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    (reports_dir / "latest_daily_learning_digest.json").write_text(
        json.dumps({"setup_stats_3d": []}),
        encoding="utf-8",
    )
    (reports_dir / "latest_post_market_learning.json").write_text(
        json.dumps({"pipeline_steps": {"learning_pipeline_seconds": 12.0}}),
        encoding="utf-8",
    )

    report = build_production_health_report(settings, store, reports_dir, "prod_test")

    assert report["summary"]["overall_status"] in {"warning", "critical"}
    assert report["continuous_improvement"]["heartbeat"]["status"] == "stale"
    assert report["continuous_improvement"]["status"] == "IDLE"
    kinds = {item["kind"] for item in report["alerts"]}
    assert "continuous_improvement_runtime_stale" in kinds
