"""Market data helpers."""

from __future__ import annotations

from datetime import datetime

import pandas as pd


def download_daily_prices(symbols: list[str], start: str | datetime, end: str | datetime | None = None) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("Instala yfinance con `pip install -r requirements.txt`.") from exc

    data = yf.download(
        tickers=" ".join(symbols),
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
    )
    return data
