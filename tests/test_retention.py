from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from agente_bolsa.config import Settings
from agente_bolsa.tools.reporting import write_json_report
from agente_bolsa.tools.retention import cleanup_runtime_data
from agente_bolsa.tools.trade_decision import (
    load_latest_sentiment,
    load_latest_technical_candidates,
)


def _settings(tmp_path):
    return Settings(
        DATA_DIR=tmp_path,
        RETENTION_ENABLED=True,
        REPORT_RETENTION_DAYS=30,
        LOG_RETENTION_DAYS=30,
        CACHE_RETENTION_DAYS=7,
        DISABLED_REPORT_PREFIXES=(
            "postmortem_signals,missed_opportunities,decision_compare,"
            "walk_forward_validation,session_retrospective"
        ),
    )


def _age_file(path, *, days: int) -> None:
    old_time = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
    os.utime(path, (old_time, old_time))


def test_write_json_report_skips_disabled_prefix(monkeypatch, tmp_path):
    settings = _settings(tmp_path)
    monkeypatch.setattr("agente_bolsa.tools.reporting.get_settings", lambda: settings)

    report = write_json_report(
        {"run_id": "pm_test", "as_of": datetime.now(timezone.utc).isoformat()},
        tmp_path / "reports",
        "postmortem_signals",
        "pm_test",
    )

    assert report["persisted"] is False
    assert report["path"] is None
    assert not list((tmp_path / "reports").glob("postmortem_signals_*"))


def test_write_json_report_persists_latest_for_operational_reports(monkeypatch, tmp_path):
    settings = _settings(tmp_path)
    monkeypatch.setattr("agente_bolsa.tools.reporting.get_settings", lambda: settings)

    report = write_json_report(
        {"run_id": "scan_test", "as_of": datetime.now(timezone.utc).isoformat(), "top_longs": []},
        tmp_path / "reports",
        "closed_market_technical_study",
        "scan_test",
        latest_filename="latest_closed_market_technical_study.json",
    )

    assert report["persisted"] is True
    assert (tmp_path / "reports" / "closed_market_technical_study_scan_test.json").exists()
    assert (tmp_path / "reports" / "latest_closed_market_technical_study.json").exists()


def test_cleanup_runtime_data_keeps_latest_and_deletes_old_artifacts(tmp_path):
    settings = _settings(tmp_path)
    reports_dir = tmp_path / "reports"
    logs_dir = tmp_path / "logs"
    cache_dir = tmp_path / "cache"
    reports_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    old_report = reports_dir / "closed_market_technical_study_old.json"
    old_manifest = reports_dir / "closed_market_technical_study_old.manifest.json"
    latest_report = reports_dir / "latest_closed_market_technical_study.json"
    old_log = logs_dir / "system.jsonl"
    old_cache = cache_dir / "market.pkl"
    for path in (old_report, old_manifest, latest_report, old_log, old_cache):
        path.write_text("{}", encoding="utf-8")

    _age_file(old_report, days=31)
    _age_file(old_manifest, days=31)
    _age_file(latest_report, days=31)
    _age_file(old_log, days=31)
    _age_file(old_cache, days=8)

    summary = cleanup_runtime_data(settings)

    assert summary.reports_deleted >= 2
    assert summary.logs_deleted == 1
    assert summary.cache_deleted == 1
    assert not old_report.exists()
    assert not old_manifest.exists()
    assert latest_report.exists()


def test_trade_decision_loaders_prefer_latest_files(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latest_closed_market_technical_study.json").write_text(
        json.dumps(
            {
                "run_id": "latest_run",
                "as_of": "2026-05-24T00:00:00+00:00",
                "top_longs": [{"symbol": "AAPL"}],
                "top_shorts": [{"symbol": "TSLA"}],
                "all_candidates": [{"symbol": "AAPL"}],
                "analysis_plan_counts": {"technical": 1},
            }
        ),
        encoding="utf-8",
    )
    (reports_dir / "latest_news_sentiment.json").write_text(
        json.dumps(
            {
                "run_id": "news_latest",
                "as_of": "2026-05-24T00:00:00+00:00",
                "results": [{"symbol": "AAPL", "sentiment": {"summary": "ok"}}],
            }
        ),
        encoding="utf-8",
    )

    technical = load_latest_technical_candidates(tmp_path, per_side=5)
    sentiment = load_latest_sentiment(tmp_path)

    assert technical["run_id"] == "latest_run"
    assert technical["top_longs"][0]["symbol"] == "AAPL"
    assert sentiment["run_id"] == "news_latest"
    assert sentiment["results"][0]["symbol"] == "AAPL"
