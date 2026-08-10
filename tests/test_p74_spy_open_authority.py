from __future__ import annotations

import json
from datetime import datetime, timezone
from inspect import getsource

import pandas as pd
import pytest

from agente_bolsa import scheduler, web_app
from agente_bolsa.config import Settings
from agente_bolsa.scheduler import _attempt_authoritative_spy_open_capture
from agente_bolsa.storage import Store
from agente_bolsa.tools import market_data
from agente_bolsa.tools.opening_performance import (
    build_open_to_open_rows,
    capture_authoritative_spy_open_cache,
    load_cached_spy_open_observations,
    opening_performance_context,
)
from agente_bolsa.tools.telegram_daily_summary import build_daily_summary, format_daily_summary


def _write_cache(
    tmp_path,
    name: str,
    *,
    created_at: str,
    open_price: float,
    current_price: float,
    requested_symbols: list[str],
    purpose: str | None = None,
    session_date: str = "2026-07-29",
) -> None:
    cache_root = tmp_path / "cache" / "market_data"
    cache_root.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {"Open": [open_price], "Close": [current_price]},
        index=pd.to_datetime([session_date]),
    )
    frame.to_pickle(cache_root / f"market_data_{name}.pkl")
    (cache_root / f"market_data_{name}.json").write_text(
        json.dumps(
            {
                "source": "yfinance",
                "created_at": created_at,
                "provider_observed_at": created_at,
                "requested_symbols": requested_symbols,
                "start": "2026-07-29",
                "end": "2026-07-29",
                "interval": "1d",
                "price_basis": "adjusted_ohlc",
                **({"purpose": purpose} if purpose else {}),
            }
        ),
        encoding="utf-8",
    )


def test_conflicting_same_session_caches_are_not_resolved_by_latest_timestamp(tmp_path):
    """La base selecciona la caché estrecha más reciente sin resolver el conflicto."""

    _write_cache(
        tmp_path,
        "0bc493d6d987c1b1",
        created_at="2026-07-29T13:42:39+00:00",
        open_price=739.1900024414062,
        current_price=739.5599975585938,
        requested_symbols=[f"S{index:02d}" for index in range(24)] + ["SPY"],
    )
    _write_cache(
        tmp_path,
        "fae973e5b2174803",
        created_at="2026-07-29T13:50:33+00:00",
        open_price=739.969970703125,
        current_price=738.6500244140625,
        requested_symbols=["PM", "SPY"],
    )

    observed = load_cached_spy_open_observations(
        Settings(_env_file=None, DATA_DIR=tmp_path),
        now=datetime(2026, 7, 29, 16, 0, tzinfo=timezone.utc),
    )

    assert observed["status"] == "conflict"
    assert observed["current"] is None
    assert observed["opens"] == []
    assert "conflicting_session_open_observations" in observed["warnings"]


def test_current_price_is_freshest_valid_observation_not_an_open_conflict(tmp_path):
    common = {
        "open_price": 739.1900024414062,
        "requested_symbols": ["SPY"],
    }
    _write_cache(
        tmp_path,
        "early",
        created_at="2026-07-29T13:42:39+00:00",
        current_price=739.5599975585938,
        **common,
    )
    _write_cache(
        tmp_path,
        "late",
        created_at="2026-07-29T13:50:33+00:00",
        current_price=738.6500244140625,
        **common,
    )

    observed = load_cached_spy_open_observations(
        Settings(_env_file=None, DATA_DIR=tmp_path),
        now=datetime(2026, 7, 29, 16, 0, tzinfo=timezone.utc),
    )

    assert observed["status"] == "available"
    assert observed["current"]["price"] == pytest.approx(738.6500244140625)
    assert observed["current"]["provenance"]["cache_id"] == "market_data_late"
    assert not any("current" in warning and "conflict" in warning for warning in observed["warnings"])


def test_explicit_spy_open_authority_resolves_different_non_authoritative_cache(tmp_path):
    _write_cache(
        tmp_path,
        "broad",
        created_at="2026-07-29T13:42:39+00:00",
        open_price=739.1900024414062,
        current_price=739.5599975585938,
        requested_symbols=["AAPL", "SPY"],
    )
    _write_cache(
        tmp_path,
        "dedicated",
        created_at="2026-07-29T13:50:33+00:00",
        open_price=739.969970703125,
        current_price=738.6500244140625,
        requested_symbols=["SPY"],
        purpose="benchmark_open",
    )

    observed = load_cached_spy_open_observations(
        Settings(_env_file=None, DATA_DIR=tmp_path),
        now=datetime(2026, 7, 29, 16, 0, tzinfo=timezone.utc),
    )

    assert observed["status"] == "available"
    assert observed["opens"][0]["price"] == pytest.approx(739.969970703125)
    assert observed["opens"][0]["provenance"]["authority"] == "explicit_benchmark_open"
    assert observed["current"]["price"] == pytest.approx(738.6500244140625)


def test_dedicated_producer_writes_reachable_explicit_authority_without_network(tmp_path, monkeypatch):
    frame = pd.DataFrame(
        {"Open": [739.969970703125], "Close": [738.6500244140625]},
        index=pd.to_datetime(["2026-07-29"]),
    )

    def fake_download(*_args, **_kwargs):
        return frame, {
            "source": "fixture",
            "provider": "fixture",
            "requested_symbols": ["SPY"],
            "interval": "1d",
            "price_basis": "adjusted_ohlc",
            "created_at": "2026-07-29T13:50:33+00:00",
        }

    monkeypatch.setattr(market_data, "download_daily_prices_with_metadata", fake_download)
    settings = Settings(_env_file=None, DATA_DIR=tmp_path)
    result = capture_authoritative_spy_open_cache(
        settings,
        "2026-07-29",
        now=datetime(2026, 7, 29, 16, 0, tzinfo=timezone.utc),
    )

    assert result["status"] == "inserted"
    metadata = json.loads(next((tmp_path / "cache" / "market_data").glob("market_data_*.json")).read_text(encoding="utf-8"))
    assert metadata["purpose"] == "benchmark_open"
    assert metadata["observation_kind"] == "spy_open"
    assert metadata["requested_symbols"] == ["SPY"]
    observed = load_cached_spy_open_observations(settings, now=datetime(2026, 7, 29, 16, 0, tzinfo=timezone.utc))
    assert observed["opens"][0]["provenance"]["authority"] == "explicit_benchmark_open"


def test_dedicated_producer_is_idempotent_and_recovers_missing_payload(tmp_path, monkeypatch):
    frame = pd.DataFrame(
        {"Open": [739.969970703125], "Close": [738.6500244140625]},
        index=pd.to_datetime(["2026-07-29"]),
    )
    monkeypatch.setattr(
        market_data,
        "download_daily_prices_with_metadata",
        lambda *_args, **_kwargs: (
            frame,
            {"source": "fixture", "requested_symbols": ["SPY"], "price_basis": "adjusted_ohlc"},
        ),
    )
    settings = Settings(_env_file=None, DATA_DIR=tmp_path)
    first = capture_authoritative_spy_open_cache(settings, "2026-07-29", now=datetime(2026, 7, 29, 16, 0, tzinfo=timezone.utc))
    second = capture_authoritative_spy_open_cache(settings, "2026-07-29", now=datetime(2026, 7, 29, 16, 5, tzinfo=timezone.utc))
    assert first["status"] == "inserted"
    assert second["status"] == "available"
    assert second["cache_id"] == first["cache_id"]

    cache_root = tmp_path / "cache" / "market_data"
    data_path = cache_root / f"market_data_{first['cache_id']}.pkl"
    data_path.unlink()
    recovered = capture_authoritative_spy_open_cache(settings, "2026-07-29", now=datetime(2026, 7, 29, 16, 10, tzinfo=timezone.utc))
    assert recovered["status"] == "recovered"
    assert data_path.exists()
    recovered_frame = pd.read_pickle(data_path)
    assert float(recovered_frame.loc[pd.Timestamp("2026-07-29"), "Open"]) == pytest.approx(739.969970703125)


def test_distinct_open_candidate_is_auditable_conflict_and_original_is_untouched(tmp_path, monkeypatch):
    frame = pd.DataFrame(
        {"Open": [740.50], "Close": [738.65]},
        index=pd.to_datetime(["2026-07-29"]),
    )
    monkeypatch.setattr(
        market_data,
        "download_daily_prices_with_metadata",
        lambda *_args, **_kwargs: (frame, {"source": "fixture", "requested_symbols": ["SPY"], "price_basis": "adjusted_ohlc"}),
    )
    settings = Settings(_env_file=None, DATA_DIR=tmp_path)
    cache_root = tmp_path / "cache" / "market_data"
    cache_root.mkdir(parents=True)
    identity_hash = __import__("hashlib").sha256(
        json.dumps({"symbol": "SPY", "session_date": "2026-07-29", "price_basis": "adjusted_ohlc"}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]
    cache_id = f"spy_open_20260729_{identity_hash}"
    original = {
        "schema_version": "p-l74.spy-open-authority.v1",
        "session_date": "2026-07-29",
        "symbol": "SPY",
        "open_price": 739.969970703125,
        "source": "fixture",
        "price_basis": "adjusted_ohlc",
        "purpose": "benchmark_open",
        "requested_symbols": ["SPY"],
        "content_hash": "original-semantic-hash",
    }
    (cache_root / f"market_data_{cache_id}.json").write_text(json.dumps(original), encoding="utf-8")
    result = capture_authoritative_spy_open_cache(settings, "2026-07-29", now=datetime(2026, 7, 29, 16, 0, tzinfo=timezone.utc))

    assert result["status"] == "conflict"
    assert json.loads((cache_root / f"market_data_{cache_id}.json").read_text(encoding="utf-8"))["open_price"] == 739.969970703125
    assert list(cache_root.glob("spy_open_conflict_*.json"))


def test_market_cycle_capture_retries_after_three_failures_until_success(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, DATA_DIR=tmp_path)
    calls = {"count": 0}
    outcomes = [
        {"status": "unavailable", "reason": "bar_missing"},
        {"status": "unavailable", "reason": "bar_missing"},
        {"status": "unavailable", "reason": "bar_missing"},
        {"status": "inserted", "cache_id": "spy_open_final"},
    ]

    def fake_capture(*_args, **_kwargs):
        result = outcomes[calls["count"]]
        calls["count"] += 1
        return result

    monkeypatch.setattr(scheduler, "capture_authoritative_spy_open_cache", fake_capture)

    class Runtime:
        def __init__(self):
            self.values = {}

        def get_runtime_value(self, key):
            return self.values.get(key)

        def set_runtime_value(self, key, value):
            self.values[key] = value

    store = Runtime()
    for _ in range(4):
        state = _attempt_authoritative_spy_open_capture(settings, store, session_date="2026-07-29")

    assert calls["count"] == 4
    assert state["status"] == "inserted"
    assert state["attempts"] == 4


def test_capture_before_open_is_unavailable_without_downloader(tmp_path, monkeypatch):
    monkeypatch.setattr(market_data, "download_daily_prices_with_metadata", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network")))
    result = capture_authoritative_spy_open_cache(
        Settings(_env_file=None, DATA_DIR=tmp_path),
        "2026-07-29",
        now=datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc),
    )
    assert result == {"status": "unavailable", "reason": "session_open_not_reached"}


@pytest.mark.parametrize("terminal_status", ["inserted", "available", "idempotent", "recovered"])
def test_market_cycle_guard_terminalizes_all_successful_capture_states(tmp_path, monkeypatch, terminal_status):
    settings = Settings(_env_file=None, DATA_DIR=tmp_path)
    calls = {"count": 0}

    def fake_capture(*_args, **_kwargs):
        calls["count"] += 1
        return {"status": terminal_status, "cache_id": "spy_open_final"}

    monkeypatch.setattr(scheduler, "capture_authoritative_spy_open_cache", fake_capture)

    class Runtime:
        def __init__(self):
            self.values = {}

        def get_runtime_value(self, key):
            return self.values.get(key)

        def set_runtime_value(self, key, value):
            self.values[key] = value

    store = Runtime()
    first = _attempt_authoritative_spy_open_capture(settings, store, session_date="2026-07-29")
    second = _attempt_authoritative_spy_open_capture(settings, store, session_date="2026-07-29")

    assert first["status"] == terminal_status
    assert first["retry_on_next_market_cycle"] is False
    assert second == first
    assert calls["count"] == 1


def test_market_cycle_owns_dedicated_capture_and_portfolio_watch_does_not():
    market_source = getsource(scheduler.market_cycle_job)
    helper_source = getsource(_attempt_authoritative_spy_open_capture)
    portfolio_source = getsource(scheduler.portfolio_watch_job)
    assert "_attempt_authoritative_spy_open_capture(" in market_source
    assert "market_cycle_spy_open_capture:" in helper_source
    assert "portfolio_watch_spy_open_capture:" not in portfolio_source
    assert "capture_authoritative_spy_open_cache(" not in portfolio_source
    assert "attempts >= 3" not in helper_source
    assert 'retry_on_next_market_cycle": result.get("status") not in {' in helper_source


def test_historical_open_conflict_does_not_make_authoritative_current_session_global_conflict(tmp_path):
    _write_cache(
        tmp_path,
        "historical_a",
        created_at="2026-07-28T13:40:00+00:00",
        open_price=740.0,
        current_price=741.0,
        requested_symbols=["SPY"],
        session_date="2026-07-28",
    )
    _write_cache(
        tmp_path,
        "historical_b",
        created_at="2026-07-28T13:41:00+00:00",
        open_price=741.0,
        current_price=742.0,
        requested_symbols=["SPY"],
        session_date="2026-07-28",
    )
    _write_cache(
        tmp_path,
        "current_authoritative",
        created_at="2026-07-29T13:50:00+00:00",
        open_price=739.969970703125,
        current_price=738.6500244140625,
        requested_symbols=["SPY"],
        purpose="benchmark_open",
    )

    observed = load_cached_spy_open_observations(
        Settings(_env_file=None, DATA_DIR=tmp_path),
        now=datetime(2026, 7, 29, 16, 0, tzinfo=timezone.utc),
    )

    assert observed["status"] == "available"
    assert "2026-07-28" in observed["conflicts"]
    assert observed["current"]["price"] == pytest.approx(738.6500244140625)


def test_conflicted_open_does_not_reach_open_to_now_return_or_telegram(tmp_path):
    _write_cache(
        tmp_path,
        "broad",
        created_at="2026-07-29T13:42:39+00:00",
        open_price=739.1900024414062,
        current_price=739.5599975585938,
        requested_symbols=["AAPL", "SPY"],
    )
    _write_cache(
        tmp_path,
        "narrow",
        created_at="2026-07-29T13:50:33+00:00",
        open_price=739.969970703125,
        current_price=738.6500244140625,
        requested_symbols=["PM", "SPY"],
    )
    history = {
        "timestamp": ["2026-07-29T13:30:00+00:00"],
        "equity": [70672.33],
    }
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    settings = Settings(_env_file=None, DATA_DIR=tmp_path)
    context = opening_performance_context(
        settings,
        store,
        intraday_history=history,
        current_equity=70640.16,
        now=datetime(2026, 7, 29, 16, 0, tzinfo=timezone.utc),
    )

    assert context["spy_status"] == "conflict"
    assert context["account_current"]["system_pct"] == pytest.approx(70640.16 / 70672.33 - 1)
    assert context["current"] is None
    payload = build_daily_summary(
        session_date="2026-07-29",
        performance={"spy_pct": 0.0005},
        portfolio=type("Portfolio", (), {"portfolio_value": 70640.16, "positions": []})(),
        opening_performance=context,
    )

    assert payload["spy_daily_return"] is None
    assert payload["comparison_status"] == "unavailable"
    assert "SPY (ETF S&P 500): +0.05%" not in format_daily_summary(payload)


def test_opening_row_keeps_negative_current_return_explicitly():
    rows = build_open_to_open_rows(
        [
            {"session_date": "2026-07-29", "equity": 70672.33, "observed_at": "2026-07-29T13:30:00+00:00", "source": "test"},
        ],
        {
            "opens": [
                {
                    "session_date": "2026-07-29",
                    "price": 739.969970703125,
                    "observed_at": "2026-07-29T13:30:00+00:00",
                    "source": "test",
                    "price_basis": "adjusted_ohlc",
                },
            ],
            "current": {
                "session_date": "2026-07-29",
                "price": 738.6500244140625,
                "observed_at": "2026-07-29T15:50:00+00:00",
                "source": "test",
                "price_basis": "adjusted_ohlc",
            },
        },
        current_equity=70640.16,
        current_equity_at=datetime(2026, 7, 29, 16, 0, tzinfo=timezone.utc),
    )

    assert rows[0]["status"] == "in_progress"
    assert rows[0]["spy_pct"] == pytest.approx(738.6500244140625 / 739.969970703125 - 1)
    assert rows[0]["spy_pct"] < 0


def test_ui_names_session_and_interval_without_collapsing_old_final_into_current():
    source = __import__("inspect").getsource(web_app._render_daily_vs_spy_table)
    chart_source = __import__("inspect").getsource(web_app._daily_vs_spy_chart)

    assert "Rendimiento desde apertura: Sistema vs SPY" in source
    assert "<th>Sesión iniciada</th>" in source
    assert "<th>Intervalo</th>" in source
    assert 'title="Sesión iniciada"' in chart_source
    assert 'title="Intervalo"' in chart_source
    assert "Final" in chart_source and "En curso" in chart_source
