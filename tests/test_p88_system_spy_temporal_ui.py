from datetime import datetime, timezone
import json

import pandas as pd

import pytest

from agente_bolsa import web_app
from agente_bolsa.config import Settings
from agente_bolsa.tools.opening_performance import (
    build_open_to_open_rows,
    load_cached_spy_open_observations,
)

UTC = timezone.utc


def _current_fixture(*, spy_at: str, system_at: str) -> tuple[list[dict], dict]:
    account_at = "2026-08-10T13:30:00+00:00"
    account = [{"session_date": "2026-08-10", "equity": 100.0, "observed_at": account_at}]
    spy = {
        "opens": [
            {
                "session_date": "2026-08-10",
                "price": 100.0,
                "price_basis": "adjusted_ohlc",
                "observed_at": account_at,
            }
        ],
        "current": {
            "price": 101.0,
            "price_basis": "adjusted_ohlc",
            "observed_at": spy_at,
            "source": "fixture",
        },
    }
    return account, spy


def test_current_spy_observation_with_small_lag_is_comparable():
    account, spy = _current_fixture(
        spy_at="2026-08-10T19:49:00+00:00",
        system_at="2026-08-10T19:51:00+00:00",
    )

    rows = build_open_to_open_rows(
        account,
        spy,
        current_equity=102.0,
        current_equity_at=datetime(2026, 8, 10, 19, 51, tzinfo=UTC),
    )

    current = rows[-1]
    assert current["comparison_status"] == "comparable"
    assert current["comparison_reason"] is None
    assert current["comparison_lag_seconds"] == pytest.approx(120.0)


def test_recent_cache_capture_without_provider_timestamp_is_not_comparable(tmp_path):
    cache = tmp_path / "cache" / "market_data"
    cache.mkdir(parents=True)
    pd.DataFrame(
        {"Open": [100.0], "Close": [101.0]},
        index=pd.to_datetime(["2026-08-10"]),
    ).to_pickle(cache / "market_data_recent.pkl")
    (cache / "market_data_recent.json").write_text(
        json.dumps(
            {
                "requested_symbols": ["SPY"],
                "interval": "1d",
                "price_basis": "adjusted_ohlc",
                "source": "yfinance",
                "created_at": "2026-08-10T13:59:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    now = datetime(2026, 8, 10, 14, 0, tzinfo=UTC)
    spy = load_cached_spy_open_observations(
        Settings(_env_file=None, DATA_DIR=tmp_path),
        now=now,
    )
    rows = build_open_to_open_rows(
        [{"session_date": "2026-08-10", "equity": 100.0, "observed_at": "2026-08-10T13:30:00+00:00"}],
        spy,
        current_equity=102.0,
        current_equity_at=now,
    )

    current = rows[-1]
    assert current["comparison_status"] == "unavailable"
    assert current["comparison_reason"] == "current_observation_timestamp_unverified"
    assert current["spy_pct"] is None


def test_current_spy_observation_beyond_tolerance_is_unavailable():
    account, spy = _current_fixture(
        spy_at="2026-08-10T19:45:59+00:00",
        system_at="2026-08-10T19:51:00+00:00",
    )

    rows = build_open_to_open_rows(
        account,
        spy,
        current_equity=102.0,
        current_equity_at=datetime(2026, 8, 10, 19, 51, tzinfo=UTC),
    )

    current = rows[-1]
    assert current["comparison_status"] == "unavailable"
    assert current["comparison_reason"] == "current_observation_not_aligned"
    assert current["comparison_lag_seconds"] == pytest.approx(301.0)


def test_current_spy_observation_at_tolerance_boundary_is_comparable():
    account, spy = _current_fixture(
        spy_at="2026-08-10T19:46:00+00:00",
        system_at="2026-08-10T19:51:00+00:00",
    )

    rows = build_open_to_open_rows(
        account,
        spy,
        current_equity=102.0,
        current_equity_at=datetime(2026, 8, 10, 19, 51, tzinfo=UTC),
    )

    current = rows[-1]
    assert current["comparison_status"] == "comparable"
    assert current["comparison_alignment_tolerance_seconds"] == 300


def test_future_spy_observation_remains_unavailable():
    account, spy = _current_fixture(
        spy_at="2026-08-10T19:52:00+00:00",
        system_at="2026-08-10T19:51:00+00:00",
    )

    rows = build_open_to_open_rows(
        account,
        spy,
        current_equity=102.0,
        current_equity_at=datetime(2026, 8, 10, 19, 51, tzinfo=UTC),
    )

    assert rows[-1]["comparison_reason"] == "current_observation_future"


def test_system_window_is_open_to_now_even_when_spy_is_stale():
    account, spy = _current_fixture(
        spy_at="2026-08-10T16:02:32+00:00",
        system_at="2026-08-10T17:51:00+00:00",
    )

    rows = build_open_to_open_rows(
        account,
        spy,
        current_equity=100.07,
        current_equity_at=datetime(2026, 8, 10, 17, 51, tzinfo=UTC),
    )

    current = rows[-1]
    assert current["system_delta"] == pytest.approx(0.07)
    assert current["system_pct"] == pytest.approx(0.0007)
    assert current["spy_pct"] == pytest.approx(0.01)
    assert current["comparison_status"] == "unavailable"
    assert current["comparison_reason"] == "current_observation_not_aligned"


def test_portfolio_series_keeps_source_rows_immutable():
    payload = {
        "timestamp": ["2026-08-05T00:00:00Z", "2026-08-06T00:00:00Z"],
        "equity": [100.0, 101.0],
    }
    original = {key: list(value) for key, value in payload.items()}

    web_app._portfolio_value_series_from_alpaca(payload, current_equity=None, start_date="2026-08-01")

    assert payload == original


def test_opening_summary_contract_exposes_system_and_benchmark_separately():
    context = {
        "account_current": {
            "system_delta": 48.55,
            "system_pct": 0.0007,
            "system_start_at": "2026-08-10T13:30:00+00:00",
            "system_end_at": "2026-08-10T17:51:00+00:00",
        },
        "current": {
            "status": "in_progress",
            "comparison_status": "unavailable",
            "comparison_reason": "current_observation_not_aligned",
            "spy_pct": 0.0022,
            "spy_end_at": "2026-08-10T16:02:32+00:00",
            "price_basis": "adjusted_ohlc",
        },
    }

    metric = web_app._opening_comparable_metric(context)

    assert metric["system_amount"] == pytest.approx(48.55)
    assert metric["system_pct"] == pytest.approx(0.0007)
    assert metric["spy_pct"] is None
    assert metric["spy_status"] == "unavailable"
    assert metric["spy_reason"] == "current_observation_not_aligned"


def test_opening_summary_does_not_treat_spx_label_as_spy():
    context = {
        "account_current": {"system_delta": 1.0, "system_pct": 0.01},
        "current": {
            "comparison_status": "comparable",
            "spy_pct": 0.02,
            "instrument_label": "SPX (index)",
        },
    }

    metric = web_app._opening_comparable_metric(context)

    assert metric["spy_status"] == "unavailable"
    assert metric["spy_reason"] == "benchmark_instrument_not_spy"
