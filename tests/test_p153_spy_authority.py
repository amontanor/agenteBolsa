"""P-L153: session-aware SPY authority + honest closed-market cards."""

import json
from datetime import datetime, timezone

import pandas as pd

from agente_bolsa.config import Settings
from agente_bolsa.tools.opening_performance import (
    _candidate_settled,
    _session_settled_at,
    load_cached_spy_open_observations,
    quarantined_open_sessions,
)
from agente_bolsa.web_app import _position_rows

SESSION_DATE = "2026-09-17"
SETTLED_AFTER = "2026-09-17T20:30:00+00:00"


def _candidate(price, created_at, authority=None):
    provenance = {"cache_created_at": created_at, "cache_id": "test"}
    if authority:
        provenance["authority"] = authority
    return {"price": price, "price_basis": "adjusted_ohlc", "provenance": provenance}


def test_settled_boundary_is_session_close_plus_grace():
    settled_at = _session_settled_at(SESSION_DATE)

    assert settled_at.isoformat() == "2026-09-17T20:15:00+00:00"


def test_intraday_download_is_not_settled():
    assert _candidate_settled(SESSION_DATE, _candidate(759.5, "2026-09-17T13:37:34+00:00")) is False


def test_post_close_download_is_settled():
    assert _candidate_settled(SESSION_DATE, _candidate(763.15, SETTLED_AFTER)) is True


def test_authority_is_always_settled():
    assert (
        _candidate_settled(
            SESSION_DATE,
            _candidate(760.0, "2026-09-17T10:00:00+00:00", authority="explicit_benchmark_open"),
        )
        is True
    )


def test_missing_or_invalid_created_at_is_kept():
    assert _candidate_settled(SESSION_DATE, {"price": 1.0, "provenance": {}}) is True
    assert _candidate_settled(SESSION_DATE, _candidate(1.0, "not-a-date")) is True


def test_quarantine_reports_only_partially_covered_sessions():
    by_session = {
        "2026-09-17": [
            _candidate(759.5, "2026-09-17T13:37:34+00:00"),
            _candidate(763.15, SETTLED_AFTER),
        ],
        "2026-09-16": [_candidate(750.0, "2026-09-16T10:00:00+00:00")],
    }

    assert quarantined_open_sessions(by_session) == ["2026-09-17"]


def _write_cache(tmp_path, name, *, created_at, open_price, requested_symbols, purpose=None):
    cache_root = tmp_path / "cache" / "market_data"
    cache_root.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {"Open": [open_price], "Close": [open_price]},
        index=pd.to_datetime([SESSION_DATE]),
    )
    frame.to_pickle(cache_root / f"market_data_{name}.pkl")
    metadata = {
        "source": "fixture",
        "created_at": created_at,
        "provider_observed_at": created_at,
        "requested_symbols": requested_symbols,
        "start": SESSION_DATE,
        "end": SESSION_DATE,
        "interval": "1d",
        "price_basis": "adjusted_ohlc",
    }
    if purpose:
        metadata["purpose"] = purpose
    (cache_root / f"market_data_{name}.json").write_text(json.dumps(metadata), encoding="utf-8")


def _settings(tmp_path):
    return Settings(_env_file=None, DATA_DIR=tmp_path)


def test_partial_bar_quarantined_when_settled_exists(tmp_path):
    _write_cache(
        tmp_path, "intraday", created_at="2026-09-17T13:37:34+00:00",
        open_price=759.5, requested_symbols=["SPY"],
    )
    _write_cache(
        tmp_path, "settled", created_at=SETTLED_AFTER,
        open_price=763.15, requested_symbols=["SPY"],
    )

    observed = load_cached_spy_open_observations(
        _settings(tmp_path), now=datetime(2026, 9, 18, 10, 0, tzinfo=timezone.utc)
    )

    assert observed["opens"][0]["price"] == 763.15
    assert SESSION_DATE not in observed["conflicts"]
    assert "partial_session_bars_quarantined" in observed["warnings"]


def test_genuine_settled_disagreement_still_conflicts(tmp_path):
    _write_cache(
        tmp_path, "settled-a", created_at="2026-09-17T21:00:00+00:00",
        open_price=759.5, requested_symbols=["SPY"],
    )
    _write_cache(
        tmp_path, "settled-b", created_at=SETTLED_AFTER,
        open_price=763.15, requested_symbols=["SPY"],
    )

    observed = load_cached_spy_open_observations(
        _settings(tmp_path), now=datetime(2026, 9, 18, 10, 0, tzinfo=timezone.utc)
    )

    assert SESSION_DATE in observed["conflicts"]


def test_position_day_blanked_when_requested():
    history = {
        "open_positions": [
            {"symbol": "AAPL", "qty": 1, "market_value": 100.0,
             "avg_entry_price": 90.0, "current_price": 100.0,
             "unrealized_pl": 10.0, "unrealized_plpc": 0.1,
             "unrealized_intraday_pl": 0.0, "unrealized_intraday_plpc": 0.0},
        ],
        "risk_levels": {},
    }

    [row] = _position_rows(history, blank_intraday=True)

    assert row["P/L día $"] is None
    assert row["P/L día %"] is None
    assert row["P/L $"] == 10.0


def test_position_day_kept_by_default():
    history = {
        "open_positions": [
            {"symbol": "AAPL", "qty": 1, "market_value": 100.0,
             "avg_entry_price": 90.0, "current_price": 100.0,
             "unrealized_pl": 10.0, "unrealized_plpc": 0.1,
             "unrealized_intraday_pl": 0.0, "unrealized_intraday_plpc": 0.0},
        ],
        "risk_levels": {},
    }

    [row] = _position_rows(history)

    assert row["P/L día $"] == 0.0
