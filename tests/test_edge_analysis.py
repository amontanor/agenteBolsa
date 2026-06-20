import pandas as pd

from agente_bolsa.config import Settings
from agente_bolsa.tools import edge_analysis
from agente_bolsa.tools.edge_analysis import summarize_by_group


def test_summarize_by_group_computes_expectancy_hit_rate_and_profit_factor():
    rows = [
        {"group": "confirmed_pattern", "signal_date": "2026-06-10", "outcome": {"return_1d": 0.02, "return_3d": 0.03, "return_5d": 0.05, "return_10d": 0.04}},
        {"group": "confirmed_pattern", "signal_date": "2026-06-11", "outcome": {"return_1d": -0.01, "return_3d": 0.00, "return_5d": -0.02, "return_10d": -0.01}},
    ]

    summary = summarize_by_group(rows, {}, key_fn=lambda row: row.get("group"))

    assert len(summary) == 1
    item = summary[0]
    assert item["key"] == "confirmed_pattern"
    assert item["n"] == 2
    assert item["expectancy_5d"] == 0.015
    assert item["hit_rate_5d"] == 0.5
    assert item["profit_factor_5d"] == 2.5


def test_build_spy_forward_returns_extends_end_date_and_reads_multiindex(monkeypatch):
    captured = {}
    dates = pd.bdate_range("2026-06-01", periods=12)
    frame = pd.concat(
        {"SPY": pd.DataFrame({"Close": [100 + index for index in range(len(dates))]}, index=dates)},
        axis=1,
    )

    def _download(symbols, *, start, end, cache_dir, provider, fmp_api_key):
        captured["symbols"] = symbols
        captured["start"] = start
        captured["end"] = end
        return frame

    monkeypatch.setattr(edge_analysis, "download_daily_prices", _download)

    returns = edge_analysis._build_spy_forward_returns(
        Settings(BENCHMARK_SYMBOL="SPY"),
        start="2026-06-01",
        end="2026-06-03",
    )

    assert captured["symbols"] == ["SPY"]
    assert captured["start"] < "2026-06-01"
    assert captured["end"] > "2026-06-03"
    assert returns[("2026-06-01", 1)] == 0.01
    assert returns[("2026-06-01", 10)] == 0.1


def test_build_spy_daily_returns_maps_session_returns(monkeypatch, tmp_path):
    dates = pd.bdate_range("2026-06-01", periods=4)
    frame = pd.DataFrame({"Close": [100.0, 102.0, 101.0, 103.0]}, index=dates)

    monkeypatch.setattr(edge_analysis, "download_daily_prices", lambda *args, **kwargs: frame)

    result = edge_analysis.build_spy_daily_returns(
        Settings(DATA_DIR=tmp_path, BENCHMARK_SYMBOL="SPY"),
        start="2026-06-02",
        end="2026-06-04",
    )

    assert result["2026-06-02"] == 0.02
    assert result["2026-06-03"] == -0.009804
