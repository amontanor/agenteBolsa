"""QA aislada de P-L62: freshness visible, null-safe y no autoritativa."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from inspect import getsource

import agente_bolsa.web_app as web_app
from agente_bolsa.config import Settings


def test_report_age_handles_fresh_stale_missing_naive_and_future():
    now = datetime.now(timezone.utc)
    fresh = (now - timedelta(hours=2)).isoformat()
    stale = (now - timedelta(days=8)).isoformat()
    future = (now + timedelta(hours=1)).isoformat()

    assert web_app._report_age_days(fresh) is not None
    assert web_app._report_age_days(stale) > 7
    assert web_app._report_age_days(None) is None
    assert web_app._report_age_days("not-a-timestamp") is None
    assert web_app._report_age_days(future) is None
    assert web_app._report_age_text(fresh).startswith("hace")
    assert web_app._report_age_text(future) == "futuro"
    assert web_app._report_age_text("2026-07-28T12:00:00")


def test_latest_report_json_exposes_filesystem_generated_at_without_store(tmp_path, monkeypatch):
    settings = Settings(DATA_DIR=tmp_path)
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "latest_market_data_quality.json").write_text(
        '{"summary": {"coverage_ratio": 1.0}}', encoding="utf-8"
    )
    monkeypatch.setattr(web_app, "_settings", lambda: settings)

    result = web_app._latest_report_json("latest_market_data_quality.json")

    assert result["available"] is True
    assert result["generated_at"]
    assert result["payload"]["summary"]["coverage_ratio"] == 1.0


def test_p62_freshness_is_only_presentational_and_p61_panel_is_not_reintroduced():
    page_source = getsource(web_app.page_dashboard)
    panel_source = getsource(web_app._render_daily_vs_spy_table)

    assert "_report_age_days" in page_source
    assert "_render_daily_vs_spy_table(store, current_equity" not in panel_source
    assert "_fetch_spy_today_return" not in panel_source
