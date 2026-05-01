from __future__ import annotations

import pandas as pd

from agente_bolsa.tools.backtest import backtest_technical_long_rule


def _trend_frame(rows: int = 340) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=rows, freq="B")
    records = []
    price = 100.0
    for i, _ in enumerate(dates):
        price *= 1.002
        if i > 280:
            price *= 1.004
        records.append(
            {
                "Open": price * 0.998,
                "High": price * 1.018,
                "Low": price * 0.992,
                "Close": price,
                "Volume": 1_000_000 + (i * 1_000),
            }
        )
    return pd.DataFrame(records, index=dates)


def test_backtest_returns_metrics_and_trades_for_trending_symbol():
    report = backtest_technical_long_rule(
        "AAPL",
        _trend_frame(),
        min_score=5,
        setup_quality="",
        warmup_days=260,
        max_holding_days=10,
    )

    assert report["symbol"] == "AAPL"
    assert "metrics" in report
    assert report["metrics"]["trades"] >= 1
    assert report["metrics"]["wins"] + report["metrics"]["losses"] == report["metrics"]["trades"]
    assert report["trades"][0]["stop_loss"] < report["trades"][0]["entry_price"]
    assert report["trades"][0]["take_profit"] > report["trades"][0]["entry_price"]


def test_backtest_returns_empty_metrics_when_no_signal():
    frame = _trend_frame()
    frame["Close"] = 100.0
    frame["Open"] = 100.0
    frame["High"] = 101.0
    frame["Low"] = 99.0

    report = backtest_technical_long_rule(
        "FLAT",
        frame,
        min_score=99,
        setup_quality="strong",
        warmup_days=260,
    )

    assert report["metrics"]["trades"] == 0
    assert report["metrics"]["hit_rate"] == 0.0
    assert report["trades"] == []
