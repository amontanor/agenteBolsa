from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from agente_bolsa.tools.errors import MarketDataValidationError
from agente_bolsa.tools.market_data import download_daily_prices_with_metadata


def _single_symbol_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0],
            "High": [101.0, 102.0, 103.0],
            "Low": [99.0, 100.0, 101.0],
            "Close": [100.5, 101.5, 102.5],
            "Volume": [1_000_000, 1_100_000, 1_200_000],
        },
        index=pd.date_range("2026-05-01", periods=3, freq="D"),
    )


def test_market_data_uses_cache_between_calls(monkeypatch, tmp_path):
    class FakeYF:
        calls = 0

        @staticmethod
        def download(**_kwargs):
            FakeYF.calls += 1
            return _single_symbol_frame()

    monkeypatch.setitem(__import__("sys").modules, "yfinance", FakeYF)

    first, first_meta = download_daily_prices_with_metadata(
        ["AAPL"],
        "2026-05-01",
        "2026-05-10",
        cache_dir=tmp_path / "cache",
    )
    second, second_meta = download_daily_prices_with_metadata(
        ["AAPL"],
        "2026-05-01",
        "2026-05-10",
        cache_dir=tmp_path / "cache",
    )

    assert FakeYF.calls == 1
    assert first.equals(second)
    assert first_meta["cache_hit"] is False
    assert second_meta["cache_hit"] is True
    assert second_meta["symbols_with_data"] == ["AAPL"]


def test_market_data_validation_raises_on_empty_frame(monkeypatch, tmp_path):
    class FakeYF:
        @staticmethod
        def download(**_kwargs):
            return pd.DataFrame()

    monkeypatch.setitem(__import__("sys").modules, "yfinance", FakeYF)

    with pytest.raises(MarketDataValidationError):
        download_daily_prices_with_metadata(
            ["AAPL"],
            "2026-05-01",
            "2026-05-10",
            cache_dir=tmp_path / "cache",
            max_retries=0,
        )


def test_market_data_can_use_fmp_provider(monkeypatch, tmp_path):
    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def read(self):
            return self.payload.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request, timeout=30):
        calls.append((request.full_url, timeout))
        return FakeResponse(
            """
            {
              "symbol": "AAPL",
              "historical": [
                {"date": "2026-05-01", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "adjClose": 100.5, "volume": 1000000},
                {"date": "2026-05-02", "open": 101.0, "high": 102.0, "low": 100.0, "close": 101.5, "adjClose": 101.5, "volume": 1100000}
              ]
            }
            """
        )

    monkeypatch.setattr("agente_bolsa.tools.market_data.urlopen", fake_urlopen)

    frame, meta = download_daily_prices_with_metadata(
        ["AAPL"],
        "2026-05-01",
        "2026-05-10",
        cache_dir=tmp_path / "cache",
        provider="fmp",
        fmp_api_key="demo",
    )

    assert calls
    assert meta["source"] == "fmp"
    assert meta["symbols_with_data"] == ["AAPL"]
    assert list(frame.columns)[:5] == ["Open", "High", "Low", "Close", "Adj Close"]
