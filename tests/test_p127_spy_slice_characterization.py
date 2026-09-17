"""P-L127 caracterizacion: barras futuras no invalidan el par (rojo)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from agente_bolsa.tools.performance_benchmark import load_cached_spy_observation, previous_xnys_session


def _settings(tmp_path):
    from agente_bolsa.config import Settings

    return Settings(
        _env_file=None,
        DATA_DIR=tmp_path,
        ALLOW_LIVE_TRADING=False,
        TRADING_MODE="paper",
    )


def _write_cache(settings, *, dates, closes, created_at):
    cache_root = settings.data_dir / "cache" / "market_data"
    cache_root.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {"Adj Close": closes},
        index=pd.DatetimeIndex([pd.Timestamp(d) for d in dates]),
    )
    frame.to_pickle(cache_root / "market_data_fixture.pkl")
    meta = {
        "requested_symbols": ["SPY"],
        "source": "yfinance",
        "interval": "1d",
        "start": dates[0],
        "end": dates[-1],
        "created_at": created_at,
        "price_basis": "adjusted_ohlc",
    }
    (cache_root / "market_data_fixture.json").write_text(json.dumps(meta), encoding="utf-8")


def test_pair_with_future_bars_is_available(tmp_path):
    settings = _settings(tmp_path)
    _write_cache(
        settings,
        dates=["2026-09-10", "2026-09-11", "2026-09-14", "2026-09-15"],
        closes=[700.0, 702.0, 705.0, 710.0],
        created_at="2026-09-15T01:00:00+00:00",
    )
    assert previous_xnys_session("2026-09-14") == "2026-09-11"
    now = datetime(2026, 9, 15, 21, 0, tzinfo=timezone.utc)
    obs = load_cached_spy_observation(settings, "2026-09-14", now=now)
    assert obs["status"] == "available", obs.get("warnings")
    assert obs["previous_close"] == 702.0
    assert obs["close"] == 705.0
    assert abs(obs["daily_return"] - (705.0 / 702.0 - 1.0)) < 1e-12


def test_same_day_cache_stays_unavailable(tmp_path):
    settings = _settings(tmp_path)
    _write_cache(
        settings,
        dates=["2026-09-11", "2026-09-14"],
        closes=[702.0, 705.0],
        created_at="2026-09-14T21:00:00+00:00",
    )
    now = datetime(2026, 9, 14, 22, 0, tzinfo=timezone.utc)
    obs = load_cached_spy_observation(settings, "2026-09-14", now=now)
    assert obs["status"] == "unavailable"
    assert "same_day_cache_not_eod" in (obs.get("warnings") or [])


def test_missing_pair_stays_unavailable_without_zero(tmp_path):
    settings = _settings(tmp_path)
    _write_cache(
        settings,
        dates=["2026-09-11"],
        closes=[702.0],
        created_at="2026-09-15T01:00:00+00:00",
    )
    now = datetime(2026, 9, 15, 21, 0, tzinfo=timezone.utc)
    obs = load_cached_spy_observation(settings, "2026-09-14", now=now)
    assert obs["status"] == "unavailable"
    assert obs["previous_close"] is None
    assert obs["close"] is None
    assert obs["daily_return"] is None
