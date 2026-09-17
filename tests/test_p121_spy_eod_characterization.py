"""P-L121 caracterizacion: par de cierres SPY con autoridad EOD (rojo)."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from agente_bolsa.tools.performance_benchmark import previous_xnys_session
from agente_bolsa.tools.spy_eod_authority import (
    SPY_EOD_RECEIPT_SCHEMA,
    build_spy_eod_receipt,
    capture_spy_eod_receipt,
    load_spy_eod_receipt,
    spy_eod_coverage,
)


def _settings(tmp_path):
    from agente_bolsa.config import Settings

    return Settings(
        _env_file=None,
        DATA_DIR=tmp_path,
        ALLOW_LIVE_TRADING=False,
        TRADING_MODE="paper",
    )


def _write_daily_cache(settings, *, previous, session, prev_close, close, created_at):
    cache_root = settings.data_dir / "cache" / "market_data"
    cache_root.mkdir(parents=True, exist_ok=True)
    index = pd.DatetimeIndex([pd.Timestamp(previous), pd.Timestamp(session)])
    frame = pd.DataFrame({"Adj Close": [prev_close, close]}, index=index)
    frame.to_pickle(cache_root / "market_data_fixture.pkl")
    meta = {
        "requested_symbols": ["SPY"],
        "source": "yfinance",
        "interval": "1d",
        "start": previous,
        "end": session,
        "created_at": created_at,
        "price_basis": "adjusted_ohlc",
    }
    (cache_root / "market_data_fixture.json").write_text(
        __import__("json").dumps(meta), encoding="utf-8"
    )


def test_previous_session_is_xnys_consecutive_not_calendar():
    assert previous_xnys_session("2026-08-10") == "2026-08-07"


def test_missing_cache_yields_unavailable_without_zero():
    settings = _settings(__import__("pathlib").Path("unused"))
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        from pathlib import Path

        settings = _settings(Path(tmp))
        now = datetime(2026, 8, 12, 21, 0, tzinfo=timezone.utc)
        receipt = build_spy_eod_receipt(settings, "2026-08-11", now=now)
    assert receipt["schema_version"] == SPY_EOD_RECEIPT_SCHEMA
    assert receipt["comparison_status"] == "unavailable"
    assert receipt["previous_close"] is None
    assert receipt["close"] is None
    assert receipt["daily_return"] is None
    assert receipt["reason_codes"]


def test_close_pair_receipt_is_comparable_with_exact_return():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        settings = _settings(Path(tmp))
        _write_daily_cache(
            settings,
            previous="2026-08-10",
            session="2026-08-11",
            prev_close=774.53,
            close=776.10,
            created_at="2026-08-12T01:00:00+00:00",
        )
        now = datetime(2026, 8, 12, 21, 0, tzinfo=timezone.utc)
        captured = capture_spy_eod_receipt(settings, "2026-08-11", now=now)
        assert captured["persisted"] is True
        receipt = captured["receipt"]
        assert receipt["comparison_status"] == "comparable"
        assert receipt["previous_close"] == 774.53
        assert receipt["close"] == 776.10
        assert abs(receipt["daily_return"] - (776.10 / 774.53 - 1.0)) < 1e-12
        assert receipt["eod_authority"] in {"post_session_cache", "next_session_confirmed"}
        loaded = load_spy_eod_receipt(settings, "2026-08-11")
        assert loaded is not None
        assert loaded["content_hash"] == receipt["content_hash"]
        coverage = spy_eod_coverage(settings, "2026-08-10", "2026-08-11", now=now)
        assert coverage["sessions_total"] == 2
        assert coverage["sessions_comparable"] == 1
        assert coverage["sessions_unavailable"] == 1
        assert coverage["denominator"] == "xnys_sessions"
        assert coverage["provisional"] is True
