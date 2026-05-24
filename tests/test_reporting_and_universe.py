from __future__ import annotations

import json

import pandas as pd

from agente_bolsa.tools.technical_study import build_closed_market_technical_study
from agente_bolsa.tools.universe import resolve_study_universe


def _study_frame() -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=230, freq="B")
    close = pd.Series([100 + (idx * 0.1) for idx in range(230)], index=dates, dtype=float)
    return pd.DataFrame(
        {
            "Open": close - 0.2,
            "High": close + 0.8,
            "Low": close - 0.8,
            "Close": close,
            "Volume": 1_000_000,
        },
        index=dates,
    )


def test_technical_study_writes_manifest(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "agente_bolsa.tools.technical_study.download_daily_prices_with_metadata",
        lambda *args, **kwargs: (
            _study_frame(),
            {"source": "test", "symbols_with_data": ["AAPL"], "cache_hit": False},
        ),
    )

    report = build_closed_market_technical_study(["AAPL"], tmp_path / "reports", "scan_test")

    manifest_path = tmp_path / "reports" / "closed_market_technical_study_scan_test.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert report["manifest_path"] == str(manifest_path)
    assert report["market_data"]["source"] == "test"
    assert "setup_counts" in report
    assert manifest["inputs"]["market_data"]["source"] == "test"


def test_technical_study_enriches_relative_return_vs_benchmark(monkeypatch, tmp_path):
    frame = _study_frame()
    benchmark = frame.copy()
    benchmark["Close"] = benchmark["Close"] * 0.98
    benchmark["Open"] = benchmark["Open"] * 0.98
    benchmark["High"] = benchmark["High"] * 0.98
    benchmark["Low"] = benchmark["Low"] * 0.98
    combined = pd.concat({"AAPL": frame, "SPY": benchmark}, axis=1)

    monkeypatch.setattr(
        "agente_bolsa.tools.technical_study.download_daily_prices_with_metadata",
        lambda *args, **kwargs: (
            combined,
            {"source": "test", "symbols_with_data": ["AAPL", "SPY"], "cache_hit": False},
        ),
    )

    report = build_closed_market_technical_study(
        ["AAPL"],
        tmp_path / "reports",
        "scan_rel",
        benchmark_symbol="SPY",
    )

    candidate = report["all_candidates"][0]
    assert report["benchmark_symbol"] == "SPY"
    assert report["benchmark_return_20d"] is not None
    assert candidate["relative_return_20d"] is not None


def test_resolve_universe_can_overlay_recent_breakouts(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latest_breakout_scan.json").write_text(
        json.dumps({"confirmed": [{"symbol": "AKAM"}], "watch": [{"symbol": "DDOG"}]}),
        encoding="utf-8",
    )

    symbols = resolve_study_universe(
        "sp500_plus_recent_breakouts",
        ["SPY"],
        max_symbols=0,
        cache_dir=tmp_path / "cache",
    )

    assert "AKAM" in symbols
    assert "DDOG" in symbols


def test_resolve_universe_intraday_focus_prioritizes_recent_overlays(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latest_breakout_scan.json").write_text(
        json.dumps({"confirmed": [{"symbol": "AKAM"}], "watch": [{"symbol": "DDOG"}]}),
        encoding="utf-8",
    )
    (reports_dir / "latest_closed_market_technical_study.json").write_text(
        json.dumps({"top_longs": [{"symbol": "FTNT"}, {"symbol": "PANW"}]}),
        encoding="utf-8",
    )

    symbols = resolve_study_universe(
        "sp500_plus_intraday_focus",
        ["SPY"],
        max_symbols=4,
        cache_dir=tmp_path / "cache",
    )

    assert symbols[:4] == ["AKAM", "DDOG", "FTNT", "PANW"]
