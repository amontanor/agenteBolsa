from __future__ import annotations

import pandas as pd

from agente_bolsa.tools.backtest import backtest_technical_long_rule, build_symbol_backtest


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


def test_backtest_report_includes_costs_exit_reasons_and_regime_summary():
    report = backtest_technical_long_rule(
        "AAPL",
        _trend_frame(),
        min_score=5,
        setup_quality="",
        warmup_days=260,
        max_holding_days=10,
    )

    assert "total_cost" in report["metrics"]
    assert "avg_holding_days" in report["metrics"]
    assert "exit_reasons" in report["metrics"]
    assert "sortino" in report["metrics"]
    assert "calmar" in report["metrics"]
    assert "expectancy_per_trade" in report["metrics"]
    assert "turnover" in report["metrics"]
    assert "drawdown_windows" in report["metrics"]
    assert "regime_summary" in report
    assert "setup_summary" in report


def test_backtest_can_filter_specific_setup_names():
    report = backtest_technical_long_rule(
        "AAPL",
        _trend_frame(),
        min_score=5,
        setup_quality="",
        warmup_days=260,
        max_holding_days=10,
        allowed_setup_names={"trend_volume"},
    )

    assert report["strategy"]["allowed_setup_names"] == ["trend_volume"]
    assert all(trade["setup_name"] == "trend_volume" for trade in report["trades"])


def test_build_symbol_backtest_attaches_market_data_and_gate_validation(monkeypatch, tmp_path):
    import agente_bolsa.tools.backtest as backtest_module

    prices = pd.concat(
        {"AAPL": _trend_frame(), "SPY": _trend_frame()},
        axis=1,
    )

    def fake_download(symbols, start, end, **_kwargs):
        return prices, {
            "source": "fmp",
            "requested_count": len(symbols),
            "symbols_with_data": ["AAPL", "SPY"],
            "missing_symbols_count": 0,
        }

    monkeypatch.setattr(backtest_module, "download_daily_prices_with_metadata", fake_download)

    report = build_symbol_backtest(
        "AAPL",
        tmp_path,
        "bt_test",
        start="2024-01-01",
        end="2025-12-31",
        min_score=5,
        setup_quality="",
        benchmark_symbol="SPY",
        gate_config={
            "min_trades": 1,
            "min_hit_rate": 0.0,
            "min_profit_factor": 0.0,
            "max_drawdown": 1.0,
            "min_alpha_vs_benchmark": -10.0,
            "min_trade_window_alpha": -10.0,
            "min_regime_trades": 1,
            "max_negative_regimes": 99,
        },
    )

    assert report["backtest_context"]["data_source"] == "fmp"
    assert report["backtest_context"]["market_data"]["symbols_with_data"] == ["AAPL", "SPY"]
    assert report["backtest_context"]["benchmark_symbol"] == "SPY"
    assert report["benchmark"]["symbol"] == "SPY"
    assert report["benchmark"]["available"] is True
    assert report["validation"]["gate"]["approved"] is True
