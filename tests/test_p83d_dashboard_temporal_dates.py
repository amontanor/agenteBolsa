from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pandas as pd

from agente_bolsa.config import Settings
import agente_bolsa.web_app as web_app


def _patch_dashboard_settings(monkeypatch):
    monkeypatch.setattr(
        web_app,
        "_settings",
        lambda: Settings(_env_file=None, LOCAL_TIMEZONE="Europe/Madrid"),
    )


def _epoch_seconds(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def test_parse_utc_timestamp_uses_epoch_seconds_and_milliseconds(monkeypatch):
    _patch_dashboard_settings(monkeypatch)

    assert web_app._parse_utc_timestamp(1785801600) == datetime(2026, 8, 4, tzinfo=timezone.utc)
    assert web_app._parse_utc_timestamp(1785801600000) == datetime(2026, 8, 4, tzinfo=timezone.utc)
    assert web_app._parse_utc_timestamp("2026-08-04T00:00:00") == datetime(2026, 8, 4, tzinfo=timezone.utc)
    assert web_app._parse_utc_timestamp("not-a-timestamp") is None


def test_alpaca_daily_bucket_maps_to_completed_xnys_session_not_civil_date(monkeypatch):
    _patch_dashboard_settings(monkeypatch)

    assert web_app._portfolio_session_date_for_timestamp(1785542400) == "2026-07-31"
    assert web_app._portfolio_session_date_for_timestamp(1785801600) == "2026-08-03"


def test_daily_bucket_handles_holiday_and_early_close_with_xnys_calendar(monkeypatch):
    _patch_dashboard_settings(monkeypatch)

    # 2026-07-04 00:00Z is Friday evening in New York; July 3 is the
    # observed Independence Day holiday, so the last close was July 2.
    assert web_app._portfolio_session_date_for_timestamp("2026-07-04T00:00:00Z") == "2026-07-02"
    # The 2026-11-27 early close is already complete at 18:00Z.
    assert web_app._portfolio_session_date_for_timestamp("2026-11-27T18:00:00Z") == "2026-11-27"


def test_portfolio_series_separates_session_closes_from_current_provisional(monkeypatch):
    _patch_dashboard_settings(monkeypatch)
    payload = {
        "timestamp": [1785542400, 1785801600],
        "equity": [70547.06, 70633.59],
    }

    result = web_app._portfolio_value_series_from_alpaca(
        payload,
        70635.28,
        start_date="2026-07-20",
        as_of=datetime(2026, 8, 4, 9, 19, tzinfo=timezone.utc),
    )

    assert list(result["fecha"]) == ["2026-07-31", "2026-08-03", "2026-08-04"]
    assert list(result["valor_cartera"]) == [70547.06, 70633.59, 70635.28]
    assert list(result["es_provisional"]) == [False, False, True]
    assert list(result["P/L dia"].iloc[1:]) == [86.53, 1.69]


def test_seven_day_window_uses_normalized_session_dates_and_keeps_current(monkeypatch):
    _patch_dashboard_settings(monkeypatch)
    payload = {
        "timestamp": [
            _epoch_seconds("2026-07-30T00:00:00Z"),  # close 2026-07-29
            _epoch_seconds("2026-08-01T00:00:00Z"),  # close 2026-07-31
            _epoch_seconds("2026-08-04T00:00:00Z"),  # close 2026-08-03
        ],
        "equity": [70644.33, 70547.06, 70633.59],
    }

    series = web_app._portfolio_value_series_from_alpaca(
        payload,
        70635.28,
        start_date="2026-07-20",
        as_of=datetime(2026, 8, 4, 9, 19, tzinfo=timezone.utc),
    )
    visible = web_app._trim_portfolio_chart_range(series, days=7)
    summary = web_app._portfolio_chart_visible_summary(visible)

    assert summary["start_date"] == "2026-07-29"
    assert summary["end_date"] == "2026-08-04"
    assert summary["start_value"] == 70644.33
    assert summary["end_value"] == 70635.28
    assert summary["pl"] == -9.05


def test_current_snapshot_does_not_overwrite_same_session_close(monkeypatch):
    _patch_dashboard_settings(monkeypatch)
    payload = {
        "timestamp": [_epoch_seconds("2026-08-05T00:00:00Z")],
        "equity": [100.0],
    }

    result = web_app._portfolio_value_series_from_alpaca(
        payload,
        101.0,
        start_date="2026-08-01",
        as_of=datetime(2026, 8, 4, 22, 30, tzinfo=timezone.utc),
    )

    assert list(result["fecha"]) == ["2026-08-04", "2026-08-04"]
    assert list(result["es_provisional"]) == [False, True]
    assert list(result["valor_cartera"]) == [100.0, 101.0]


def test_future_and_invalid_buckets_are_unavailable_without_mutating_payload(monkeypatch):
    _patch_dashboard_settings(monkeypatch)
    payload = {
        "timestamp": ["2026-08-04T00:00:00Z", "2027-01-01T00:00:00Z", "invalid"],
        "equity": [100.0, 200.0, 300.0],
    }
    original = deepcopy(payload)

    result = web_app._portfolio_value_series_from_alpaca(
        payload,
        None,
        start_date="2026-08-01",
        as_of=datetime(2026, 8, 4, 9, 19, tzinfo=timezone.utc),
    )

    assert payload == original
    assert list(result["valor_cartera"]) == [100.0]


def test_daily_equity_detail_uses_session_date_for_bucket_and_local_date_for_current(monkeypatch):
    _patch_dashboard_settings(monkeypatch)
    detail = web_app._daily_equity_detail(
        {
            "status": "available",
            "window_start": 1785801600,
            "window_end": "2026-08-04T09:19:00Z",
        }
    )

    assert "03/08/2026" in detail
    assert "04/08/2026" in detail
    assert "1970" not in detail
