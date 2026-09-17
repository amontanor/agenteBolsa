"""P-L127 caracterizacion: barras futuras no invalidan el par (rojo)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

from agente_bolsa.tools.performance_benchmark import (
    load_cached_spy_observation,
    previous_xnys_session,
)


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


def test_backfill_builds_from_existing_caches_without_download(tmp_path):
    from agente_bolsa.tools.spy_eod_authority import backfill_spy_eod_receipts, load_spy_eod_receipt

    settings = _settings(tmp_path)
    _write_cache(
        settings,
        dates=["2026-09-10", "2026-09-11", "2026-09-14"],
        closes=[700.0, 702.0, 704.0],
        created_at="2026-09-15T01:00:00+00:00",
    )
    now = datetime(2026, 9, 16, 21, 0, tzinfo=timezone.utc)
    report = backfill_spy_eod_receipts(settings, "2026-09-11", "2026-09-14", now=now)
    assert report["built"] == ["2026-09-11", "2026-09-14"]
    assert report["unavailable"] == {}
    assert load_spy_eod_receipt(settings, "2026-09-14")["close"] == 704.0
    rerun = backfill_spy_eod_receipts(settings, "2026-09-11", "2026-09-14", now=now)
    assert rerun["skipped"] == ["2026-09-11", "2026-09-14"]
    assert rerun["built"] == []


def test_refresh_open_session_never_downloads(tmp_path, monkeypatch):
    from agente_bolsa.tools import spy_eod_authority

    settings = _settings(tmp_path)
    monkeypatch.setattr(
        spy_eod_authority,
        "download_daily_prices_with_metadata",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debe descargar")),
        raising=False,
    )
    now = datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)
    result = spy_eod_authority.refresh_and_capture_spy_eod(settings, "2026-09-17", now=now)
    assert result["persisted"] is False
    assert result["receipt"] is None
