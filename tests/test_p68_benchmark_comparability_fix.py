"""P-L68: comparabilidad honesta y visualización provisional Sistema vs SP500."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

import agente_bolsa.web_app as web_app
from agente_bolsa.tools.market_data import download_daily_prices_with_metadata

READ_AT = datetime(2026, 7, 28, 22, 30, tzinfo=timezone.utc)


def _row(
    *,
    captured_at: str = "2026-07-28T20:10:00+00:00",
    as_of: str = "2026-07-28T00:00:00",
    price_basis: str = "adjusted_ohlc",
    quality: str = "available",
) -> dict:
    return {
        "session_date": "2026-07-28",
        "payload": {
            "performance_benchmark": {
                "schema_version": "p-l40b.performance-benchmark.v1",
                "captured_at": captured_at,
                "account": {
                    "equity": 70_700.0,
                    "previous_equity": 70_500.0,
                },
                "benchmark": {
                    "previous_close": 637.0,
                    "close": 640.0,
                    "price_basis": price_basis,
                    "source": "yfinance",
                    "as_of": as_of,
                    "eod_authority": "post_session_cache",
                    "comparison_status": "comparable",
                    "data_quality": "available",
                },
                "data_quality": {
                    "status": quality,
                    "warnings": [] if quality == "available" else ["position_side_invalid"],
                },
            }
        },
    }


def test_yfinance_metadata_declares_adjusted_price_basis(monkeypatch, tmp_path):
    calls: list[dict] = []

    class FakeYF:
        @staticmethod
        def download(**kwargs):
            calls.append(kwargs)
            return pd.DataFrame(
                {
                    "Open": [100.0, 101.0],
                    "High": [101.0, 102.0],
                    "Low": [99.0, 100.0],
                    "Close": [100.5, 101.5],
                    "Volume": [1_000_000, 1_100_000],
                },
                index=pd.date_range("2026-07-27", periods=2, freq="D"),
            )

    monkeypatch.setitem(__import__("sys").modules, "yfinance", FakeYF)

    _frame, meta = download_daily_prices_with_metadata(
        ["SPY"],
        "2026-07-27",
        "2026-07-29",
        cache_dir=tmp_path / "cache",
        provider="yfinance",
        max_retries=0,
    )

    assert calls[0]["auto_adjust"] is True
    assert meta["auto_adjust"] is True
    assert meta["price_basis"] == "adjusted_ohlc"


def test_date_precision_bar_is_not_rejected_for_preceding_postclose_capture():
    normalized = web_app._canonical_daily_vs_spy_row(_row(), consumer_read_at=READ_AT)

    assert normalized["comparison_status"] == "comparable"
    assert normalized["freshness_status"] == "fresh"
    assert normalized["freshness_age_seconds"] is None
    assert normalized["benchmark_as_of_precision"] == "date"
    assert "generated_at_after_benchmark_as_of" not in normalized["reason_codes"]


def test_exact_benchmark_timestamp_uses_capture_minus_observation_lag():
    normalized = web_app._canonical_daily_vs_spy_row(
        _row(as_of="2026-07-28T20:00:00+00:00"),
        consumer_read_at=READ_AT,
    )

    assert normalized["comparison_status"] == "comparable"
    assert normalized["freshness_age_seconds"] == 600.0
    assert normalized["benchmark_as_of_precision"] == "instant"


def test_exact_benchmark_timestamp_after_capture_is_unavailable():
    normalized = web_app._canonical_daily_vs_spy_row(
        _row(as_of="2026-07-28T20:20:00+00:00"),
        consumer_read_at=READ_AT,
    )

    assert normalized["comparison_status"] == "pending"
    assert normalized["freshness_status"] == "unavailable"
    assert "benchmark_as_of_after_generated_at" in normalized["reason_codes"]


def test_unrelated_global_warning_does_not_hide_complete_benchmark_pair():
    normalized = web_app._canonical_daily_vs_spy_row(
        _row(quality="partial"),
        consumer_read_at=READ_AT,
    )

    assert normalized["comparison_status"] == "comparable"
    assert normalized["contract_quality_status"] == "partial"
    assert normalized["benchmark_quality_status"] == "available"


def test_pending_numeric_history_is_drawn_as_provisional_without_counting_winner():
    normalized = web_app._canonical_daily_vs_spy_row(
        _row(price_basis="unknown"),
        consumer_read_at=READ_AT,
    )

    assert normalized["comparison_status"] == "pending"
    assert normalized["system_pct"] is not None
    assert normalized["spy_pct"] is not None
    assert web_app._daily_vs_spy_summary([normalized]) == {
        "visible_total": 1,
        "comparable": 0,
        "pending": 1,
        "system_wins": 0,
        "spy_wins": 0,
        "ties": 0,
        "start_date": "2026-07-28",
        "end_date": "2026-07-28",
    }

    chart = web_app._daily_vs_spy_chart([normalized])
    assert chart is not None
    spec = chart.to_dict()
    data_layers = [
        layer
        for layer in spec["layer"]
        if layer.get("mark", {}).get("type") in {"line", "point"}
    ]
    assert len(data_layers) == 2
    for layer in data_layers:
        assert any(item.get("field") == "estado" and item.get("title") == "Estado" for item in layer["encoding"]["tooltip"])
    assert all("strokeDash" not in layer["encoding"] for layer in data_layers)


def test_cumulative_baseline_compounds_daily_returns_instead_of_adding_them():
    first = _row()
    first["payload"]["performance_benchmark"]["account"] = {
        "equity": 110.0,
        "previous_equity": 100.0,
    }
    first["payload"]["performance_benchmark"]["benchmark"].update(
        previous_close=100.0,
        close=110.0,
    )
    second = _row()
    second["payload"]["performance_benchmark"]["account"] = {
        "equity": 99.0,
        "previous_equity": 110.0,
    }
    second["payload"]["performance_benchmark"]["benchmark"].update(
        previous_close=110.0,
        close=99.0,
    )

    rows, cumulative_system, cumulative_spy = web_app._performance_baseline_series(
        [first, second]
    )

    assert rows[-1]["Sistema"] == -0.01
    assert rows[-1]["SPY"] == -0.01
    assert round(cumulative_system, 12) == -0.01
    assert round(cumulative_spy, 12) == -0.01
