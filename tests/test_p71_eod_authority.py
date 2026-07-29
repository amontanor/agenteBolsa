"""Caracterización P-L71 de autoridad EOD y coherencia temporal."""

from __future__ import annotations

import json
import inspect
from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

import agente_bolsa.tools.performance_benchmark as performance_benchmark
from agente_bolsa import web_app
from agente_bolsa import scheduler
from agente_bolsa.tools import telegram_daily_summary as telegram


def _settings(tmp_path):
    return SimpleNamespace(
        data_dir=tmp_path,
        market_data_provider="auto",
        fmp_api_key=None,
        benchmark_symbol="SPY",
    )


def _write_cache(
    cache_root,
    name: str,
    current_close: float,
    created_at: str,
    *,
    price_basis: str = "unknown",
    interval: str | None = "1d",
    frame: pd.DataFrame | None = None,
) -> None:
    cache_root.mkdir(parents=True, exist_ok=True)
    frame = frame if frame is not None else pd.DataFrame(
        {"Close": [739.0900268554688, current_close]},
        index=pd.to_datetime(["2026-07-27", "2026-07-28"]),
    )
    frame.to_pickle(cache_root / f"market_data_{name}.pkl")
    (cache_root / f"market_data_{name}.json").write_text(
        json.dumps(
            {
                "source": "yfinance",
                "created_at": created_at,
                "requested_symbols": ["SPY"],
                "start": "2026-07-25",
                "end": "2026-07-29",
                "price_basis": price_basis,
                "interval": interval,
            }
        ),
        encoding="utf-8",
    )


def test_base_reproduces_alphabetical_cache_selection_false_eod_return(tmp_path, monkeypatch):
    """La base elegía el primer hash y publicaba el -0,3044 % intradía antiguo."""

    cache_root = tmp_path / "cache" / "market_data"
    _write_cache(cache_root, "000_old", 736.8400268554688, "2026-07-28T13:44:00+00:00")
    _write_cache(cache_root, "999_newer", 740.9400024414062, "2026-07-29T04:37:00+00:00")
    _write_cache(cache_root, "888_mid", 740.760009765625, "2026-07-28T20:14:00+00:00")
    monkeypatch.setattr(
        performance_benchmark,
        "previous_xnys_session",
        lambda _session_date: "2026-07-27",
    )
    monkeypatch.setattr(
        performance_benchmark,
        "session_status",
        lambda _session_date, now=None: ("closed", []),
    )

    observed = performance_benchmark.load_cached_spy_observation(
        _settings(tmp_path),
        "2026-07-28",
        now=datetime(2026, 7, 29, 5, 0, tzinfo=timezone.utc),
    )

    legacy_return = 736.8400268554688 / 739.0900268554688 - 1.0
    assert legacy_return == pytest.approx(-0.003044284077, rel=1e-9)
    assert observed["status"] == "unavailable"
    assert "same_day_cache_not_eod" in observed["warnings"]


def test_post_session_cache_is_selected_by_created_at_not_filename(tmp_path, monkeypatch):
    cache_root = tmp_path / "cache" / "market_data"
    _write_cache(cache_root, "000_old", 736.8400268554688, "2026-07-28T13:44:00+00:00")
    _write_cache(
        cache_root,
        "999_final",
        740.9400024414062,
        "2026-07-29T04:37:00+00:00",
        price_basis="adjusted_ohlc",
    )
    monkeypatch.setattr(performance_benchmark, "previous_xnys_session", lambda _value: "2026-07-27")
    monkeypatch.setattr(performance_benchmark, "session_status", lambda _value, now=None: ("closed", []))

    observed = performance_benchmark.load_cached_spy_observation(
        _settings(tmp_path),
        "2026-07-28",
        now=datetime(2026, 7, 29, 5, 0, tzinfo=timezone.utc),
    )

    assert observed["status"] == "available"
    assert observed["close"] == pytest.approx(740.9400024414062)
    assert observed["eod_authority"] == "post_session_cache"
    assert observed["price_basis"] == "adjusted_ohlc"


def test_same_day_cache_is_unavailable_even_after_market_close_without_finality(tmp_path, monkeypatch):
    cache_root = tmp_path / "cache" / "market_data"
    _write_cache(
        cache_root,
        "same_day",
        740.760009765625,
        "2026-07-28T20:14:00+00:00",
        price_basis="adjusted_ohlc",
    )
    monkeypatch.setattr(performance_benchmark, "previous_xnys_session", lambda _value: "2026-07-27")
    monkeypatch.setattr(performance_benchmark, "session_status", lambda _value, now=None: ("closed", []))

    observed = performance_benchmark.load_cached_spy_observation(
        _settings(tmp_path),
        "2026-07-28",
        now=datetime(2026, 7, 29, 5, 0, tzinfo=timezone.utc),
    )

    assert observed["status"] == "unavailable"
    assert observed["close"] is None
    assert "same_day_cache_not_eod" in observed["warnings"]


def test_missing_interval_or_basis_never_becomes_canonical(tmp_path, monkeypatch):
    cache_root = tmp_path / "cache" / "market_data"
    _write_cache(
        cache_root,
        "missing_metadata",
        740.94,
        "2026-07-29T04:37:00+00:00",
        price_basis="unknown",
        interval=None,
    )
    monkeypatch.setattr(performance_benchmark, "previous_xnys_session", lambda _value: "2026-07-27")
    monkeypatch.setattr(performance_benchmark, "session_status", lambda _value, now=None: ("closed", []))

    observed = performance_benchmark.load_cached_spy_observation(
        _settings(tmp_path),
        "2026-07-28",
        now=datetime(2026, 7, 29, 5, 0, tzinfo=timezone.utc),
    )

    assert observed["status"] == "unavailable"
    assert {"daily_interval_unavailable", "price_basis_unknown"}.issubset(observed["warnings"])


def test_future_cache_and_mixed_price_basis_are_rejected(tmp_path, monkeypatch):
    cache_root = tmp_path / "cache" / "market_data"
    frame = pd.DataFrame(
        {"Adj Close": [739.09, 740.94]},
        index=pd.to_datetime(["2026-07-27", "2026-07-28"]),
    )
    _write_cache(
        cache_root,
        "future_adjusted_as_close",
        740.94,
        "2026-07-30T04:37:00+00:00",
        price_basis="close_unadjusted",
        frame=frame,
    )
    monkeypatch.setattr(performance_benchmark, "previous_xnys_session", lambda _value: "2026-07-27")
    monkeypatch.setattr(performance_benchmark, "session_status", lambda _value, now=None: ("closed", []))

    observed = performance_benchmark.load_cached_spy_observation(
        _settings(tmp_path),
        "2026-07-28",
        now=datetime(2026, 7, 29, 5, 0, tzinfo=timezone.utc),
    )

    assert observed["status"] == "unavailable"
    assert {"cache_created_at_future", "price_basis_field_mismatch"}.issubset(observed["warnings"])


def test_future_bar_in_an_otherwise_valid_cache_is_rejected(tmp_path, monkeypatch):
    cache_root = tmp_path / "cache" / "market_data"
    frame = pd.DataFrame(
        {"Close": [739.09, 740.94, 741.20]},
        index=pd.to_datetime(["2026-07-27", "2026-07-28", "2026-07-29"]),
    )
    _write_cache(
        cache_root,
        "future_bar",
        740.94,
        "2026-07-29T04:37:00+00:00",
        price_basis="adjusted_ohlc",
        frame=frame,
    )
    monkeypatch.setattr(performance_benchmark, "previous_xnys_session", lambda _value: "2026-07-27")
    monkeypatch.setattr(performance_benchmark, "session_status", lambda _value, now=None: ("closed", []))

    observed = performance_benchmark.load_cached_spy_observation(
        _settings(tmp_path),
        "2026-07-28",
        now=datetime(2026, 7, 29, 5, 0, tzinfo=timezone.utc),
    )

    assert observed["status"] == "unavailable"
    assert "future_spy_bar" in observed["warnings"]


def _stored_performance_row() -> dict:
    return {
        "session_date": "2026-07-28",
        "payload": {
            "performance_benchmark": {
                "schema_version": "p-l40b.performance-benchmark.v1",
                "captured_at": "2026-07-28T20:27:17+00:00",
                "account": {
                    "equity": 70634.91,
                    "previous_equity": 70534.69,
                    "daily_return": 0.00142086,
                },
                "benchmark": {
                    "symbol": "SPY",
                    "instrument_label": "SPY (ETF S&P 500)",
                    "previous_close": 739.0900268554688,
                    "close": 736.8400268554688,
                    "daily_return": -0.003044284077,
                    "price_basis": "unknown",
                    "source": "yfinance",
                    "as_of": "2026-07-28T00:00:00",
                    "data_quality": "partial",
                },
                "comparison": {"excess_return_total": 0.00446514},
                "data_quality": {"status": "partial", "warnings": ["price_basis_unknown"]},
                "content_hash": "stored-original-hash",
            }
        },
    }


def test_eod_overlay_preserves_false_storage_and_projects_later_authority(tmp_path, monkeypatch):
    cache_root = tmp_path / "cache" / "market_data"
    _write_cache(
        cache_root,
        "000_old",
        736.8400268554688,
        "2026-07-28T13:44:00+00:00",
    )
    _write_cache(
        cache_root,
        "999_final",
        740.9400024414062,
        "2026-07-29T04:37:00+00:00",
        price_basis="adjusted_ohlc",
    )
    monkeypatch.setattr(performance_benchmark, "previous_xnys_session", lambda _value: "2026-07-27")
    monkeypatch.setattr(performance_benchmark, "session_status", lambda _value, now=None: ("closed", []))
    row = _stored_performance_row()

    projected = performance_benchmark.overlay_eod_benchmark(
        row,
        _settings(tmp_path),
        now=datetime(2026, 7, 29, 5, 0, tzinfo=timezone.utc),
    )
    projected_benchmark = projected["payload"]["performance_benchmark"]["benchmark"]

    assert projected_benchmark["close"] == pytest.approx(740.9400024414062)
    assert projected_benchmark["daily_return"] == pytest.approx(740.9400024414062 / 739.0900268554688 - 1)
    assert projected_benchmark["price_basis"] == "adjusted_ohlc"
    assert projected_benchmark["eod_authority"] == "post_session_cache"
    assert projected["payload"]["performance_benchmark"]["content_hash"] == "stored-original-hash"
    assert row["payload"]["performance_benchmark"]["benchmark"]["close"] == pytest.approx(736.8400268554688)
    assert projected["payload"]["performance_benchmark"]["eod_overlay"]["stored_benchmark"]["close"] == pytest.approx(736.8400268554688)


def test_eod_overlay_drops_false_value_when_no_authoritative_cache(tmp_path, monkeypatch):
    cache_root = tmp_path / "cache" / "market_data"
    _write_cache(cache_root, "same_day", 736.8400268554688, "2026-07-28T20:14:00+00:00")
    monkeypatch.setattr(performance_benchmark, "previous_xnys_session", lambda _value: "2026-07-27")
    monkeypatch.setattr(performance_benchmark, "session_status", lambda _value, now=None: ("closed", []))

    projected = performance_benchmark.overlay_eod_benchmark(
        _stored_performance_row(),
        _settings(tmp_path),
        now=datetime(2026, 7, 29, 5, 0, tzinfo=timezone.utc),
    )
    benchmark = projected["payload"]["performance_benchmark"]["benchmark"]

    assert projected["eod_overlay_status"] == "unavailable"
    assert benchmark["daily_return"] is None
    assert benchmark["close"] is None
    assert benchmark["data_quality"] == "unavailable"


def test_ui_and_telegram_use_same_eod_overlay_contract(tmp_path, monkeypatch):
    cache_root = tmp_path / "cache" / "market_data"
    _write_cache(
        cache_root,
        "999_final",
        740.9400024414062,
        "2026-07-29T04:37:00+00:00",
        price_basis="adjusted_ohlc",
    )
    monkeypatch.setattr(performance_benchmark, "previous_xnys_session", lambda _value: "2026-07-27")
    monkeypatch.setattr(performance_benchmark, "session_status", lambda _value, now=None: ("closed", []))
    projected = performance_benchmark.overlay_eod_benchmark(
        _stored_performance_row(),
        _settings(tmp_path),
        now=datetime(2026, 7, 29, 5, 0, tzinfo=timezone.utc),
    )
    ui_row = web_app._canonical_daily_vs_spy_row(
        projected,
        consumer_read_at=datetime(2026, 7, 29, 5, 0, tzinfo=timezone.utc),
    )
    projected_for_telegram = dict(projected)
    projected_for_telegram.update({"pnl_pct": 0.00142086, "equity": 70634.91})
    payload = telegram.build_daily_summary(
        session_date="2026-07-28",
        performance=projected_for_telegram,
        portfolio=SimpleNamespace(positions=[], portfolio_value=70634.91),
    )

    assert ui_row["comparison_status"] == "comparable"
    assert ui_row["instrument_label"] == "SPY (ETF S&P 500)"
    assert payload["benchmark"]["status"] == "comparable"
    assert payload["benchmark"]["daily_return"] == pytest.approx(ui_row["spy_pct"])
    assert "SPY (ETF S&P 500)" in telegram.format_daily_summary(payload)


def test_telegram_publish_projects_eod_overlay_in_real_consumer_boundary(tmp_path, monkeypatch):
    """La ruta real de publicación no puede confiar en ``row['spy_pct']`` stale."""

    cache_root = tmp_path / "cache" / "market_data"
    _write_cache(
        cache_root,
        "999_final",
        740.9400024414062,
        "2026-07-29T04:37:00+00:00",
        price_basis="adjusted_ohlc",
    )
    monkeypatch.setattr(performance_benchmark, "previous_xnys_session", lambda _value: "2026-07-27")
    monkeypatch.setattr(performance_benchmark, "session_status", lambda _value, now=None: ("closed", []))
    sent: list[dict] = []
    monkeypatch.setattr(
        telegram,
        "send_telegram_message",
        lambda **kwargs: sent.append(kwargs) or {"ok": True, "message_id": 7},
    )
    recorded: list[dict] = []
    store = SimpleNamespace(
        agent_events=lambda **_kwargs: [],
        record_append_only_event=lambda **kwargs: recorded.append(kwargs) or {"status": "inserted"},
    )
    settings = SimpleNamespace(
        data_dir=tmp_path,
        benchmark_symbol="SPY",
        telegram_daily_summary_enabled=True,
        telegram_bot_token="test-token",
        telegram_daily_summary_chat_id="-100123",
        telegram_timeout_seconds=15,
    )
    performance = _stored_performance_row()
    performance.update(
        {
            "pnl_pct": 0.00142086,
            "spy_pct": -0.003044284077,
            "equity": 70634.91,
        }
    )
    performance["payload"]["performance_benchmark"]["benchmark"].update(
        {
            "daily_return": 0.00250308,
            "comparison_status": "comparable",
            "eod_authority": "post_session_cache",
        }
    )

    result = telegram.publish_daily_summary(
        settings,
        store,
        session_date="2026-07-28",
        performance=performance,
        portfolio=SimpleNamespace(positions=[], portfolio_value=70634.91),
    )

    assert result["status"] == "sent"
    assert len(sent) == 1
    assert "+0.25%" in sent[0]["text"]
    assert "-0.30%" not in sent[0]["text"]
    assert recorded[0]["payload"]["content_hash"]


def test_telegram_publish_without_authoritative_cache_never_falls_back_to_stale_scalar(tmp_path, monkeypatch):
    monkeypatch.setattr(performance_benchmark, "previous_xnys_session", lambda _value: "2026-07-27")
    monkeypatch.setattr(performance_benchmark, "session_status", lambda _value, now=None: ("closed", []))
    sent: list[dict] = []
    monkeypatch.setattr(
        telegram,
        "send_telegram_message",
        lambda **kwargs: sent.append(kwargs) or {"ok": True, "message_id": 8},
    )
    events: list[dict] = []
    store = SimpleNamespace(
        agent_events=lambda **_kwargs: list(events),
        record_append_only_event=lambda **kwargs: events.append(
            {"event_id": kwargs["event_id"], "event_type": kwargs["event_type"]}
        )
        or {"status": "inserted"},
    )
    settings = SimpleNamespace(
        data_dir=tmp_path,
        benchmark_symbol="SPY",
        telegram_daily_summary_enabled=True,
        telegram_bot_token="test-token",
        telegram_daily_summary_chat_id="-100123",
        telegram_timeout_seconds=15,
    )
    performance = _stored_performance_row()
    performance.update({"pnl_pct": 0.00142086, "spy_pct": -0.003044284077, "equity": 70634.91})

    first = telegram.publish_daily_summary(
        settings,
        store,
        session_date="2026-07-28",
        performance=performance,
        portfolio=SimpleNamespace(positions=[], portfolio_value=70634.91),
    )
    second = telegram.publish_daily_summary(
        settings,
        store,
        session_date="2026-07-28",
        performance=performance,
        portfolio=SimpleNamespace(positions=[], portfolio_value=70634.91),
    )

    assert first["status"] == "sent"
    assert second["status"] == "idempotent"
    assert len(sent) == 1
    assert "SPY (ETF S&P 500): n/d" in sent[0]["text"]
    assert "-0.30%" not in sent[0]["text"]


def test_telegram_job_and_pmr_fallback_share_the_same_publish_boundary():
    job_source = inspect.getsource(scheduler.telegram_daily_summary_job)
    pmr_source = inspect.getsource(scheduler.post_market_review_job)

    assert scheduler.publish_daily_summary is telegram.publish_daily_summary
    assert job_source.count("publish_daily_summary(") == 1
    assert pmr_source.count("publish_daily_summary(") == 1


def test_exact_direction_fixture_keeps_live_and_eod_measurements_separate():
    persisted_equity = 70634.91
    previous_equity = 70534.69
    live_equity = 70640.16
    assert round(persisted_equity - previous_equity, 2) == 100.22
    assert round(live_equity - previous_equity, 2) == 105.47
    assert round((persisted_equity - previous_equity) / previous_equity, 8) == pytest.approx(0.00142086)
    assert round(740.94 / 739.09 - 1.0, 8) == pytest.approx(0.00250308)
    assert round(7428.78 / 7413.18 - 1.0, 8) == pytest.approx(0.0021044, rel=1e-4)


def test_account_header_exposes_live_as_of_without_reusing_benchmark(tmp_path, monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(web_app.st, "markdown", lambda value, **_kwargs: captured.append(value))

    web_app._account_group(
        initial_equity=70534.69,
        current_equity=70640.16,
        cash=62000.0,
        exposure=8600.0,
        exposure_pct=0.121,
        total_pl=105.47,
        total_pct=0.0015,
        today_pl=105.47,
        today_pct=0.0015,
        positions_count=8,
        orders_count=0,
        equity_summary={"start_date": "2026-04-01", "end_date": "2026-07-29"},
        equity_source="cartera actual (estimación del panel)",
        equity_as_of="2026-07-29T05:00:00+00:00",
    )

    assert captured
    assert "cartera actual" in captured[0]
    assert "as_of 2026-07-29T05:00:00+00:00" in captured[0]
