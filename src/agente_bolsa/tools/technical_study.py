"""Closed-market technical scanner for long/short preparation."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .market_data import download_daily_prices_with_metadata
from .reporting import write_json_report
from .technical_analysis import add_basic_technical_features
from .technical_state_validator import validate_symbol_technical_state


def _symbol_frame(data: pd.DataFrame, symbol: str, multi_symbol: bool) -> pd.DataFrame:
    if multi_symbol:
        return data[symbol].copy().dropna(how="all")
    return data.copy().dropna(how="all")


def _float(value: Any, precision: int = 4) -> float | None:
    if pd.isna(value):
        return None
    return round(float(value), precision)


def build_closed_market_technical_study(
    symbols: list[str],
    output_dir: Path,
    run_id: str,
    lookback_days: int = 420,
    top_n: int = 15,
    progress_callback: Any | None = None,
    benchmark_symbol: str = "SPY",
) -> dict[str, Any]:
    end = datetime.now(timezone.utc).date() + timedelta(days=1)
    start = end - timedelta(days=lookback_days)
    requested_symbols = list(symbols)
    download_symbols = list(symbols)
    if benchmark_symbol and benchmark_symbol not in download_symbols:
        download_symbols.append(benchmark_symbol)
    data, market_data_meta = download_daily_prices_with_metadata(
        download_symbols,
        start=start.isoformat(),
        end=end.isoformat(),
    )
    multi_symbol = isinstance(data.columns, pd.MultiIndex)
    benchmark_return_20d: float | None = None
    if benchmark_symbol:
        try:
            benchmark_frame = _symbol_frame(data, benchmark_symbol, multi_symbol)
            if not benchmark_frame.empty:
                benchmark_features = add_basic_technical_features(benchmark_frame)
                benchmark_latest = benchmark_features.dropna(subset=["Close"]).iloc[-1]
                benchmark_return_20d = _float(benchmark_latest.get("return_20d"))
        except Exception as exc:  # noqa: BLE001 - benchmark enrichment must stay best-effort.
            warnings = [f"{benchmark_symbol}: benchmark enrichment failed: {exc}"]
        else:
            warnings = []
    else:
        warnings = []

    candidates: list[dict[str, Any]] = []
    tool_requests: list[dict[str, Any]] = []
    for index, symbol in enumerate(requested_symbols, start=1):
        try:
            frame = _symbol_frame(data, symbol, multi_symbol)
            if frame.empty:
                warnings.append(f"{symbol}: sin datos")
                continue
            features = add_basic_technical_features(frame)
            candidate = validate_symbol_technical_state(symbol, features)
            symbol_return_20d = _float((candidate.get("technical_state", {}) or {}).get("return_20d"))
            candidate["relative_return_20d"] = (
                round(symbol_return_20d - benchmark_return_20d, 4)
                if symbol_return_20d is not None and benchmark_return_20d is not None
                else None
            )
            candidates.append(candidate)
            tool_requests.extend(candidate.get("tool_requests", []))
        except Exception as exc:  # noqa: BLE001 - a bad symbol must not block the whole scan.
            warnings.append(f"{symbol}: {exc}")
        if progress_callback and (index % 25 == 0 or index == len(requested_symbols)):
            progress_callback(index, len(requested_symbols), len(candidates))

    long_candidates = sorted(
        [item for item in candidates if item["direction"] == "long"],
        key=lambda item: item["score"],
        reverse=True,
    )[:top_n]
    short_candidates = sorted(
        [item for item in candidates if item["direction"] == "short"],
        key=lambda item: item["score"],
        reverse=True,
    )[:top_n]
    plan_counts = Counter(
        analysis
        for candidate in candidates
        for analysis in candidate.get("analysis_plan", [])
    )
    setup_counts = Counter(
        "event_momentum"
        if (candidate.get("technical_state", {}) or {}).get("event_momentum_long")
        else "momentum_shakeout"
        if (candidate.get("technical_state", {}) or {}).get("momentum_shakeout_hold_long")
        else "chart_pattern"
        if ((candidate.get("technical_state", {}) or {}).get("chart_patterns") or [])
        else "trend_continuation"
        for candidate in candidates
    )

    report = {
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "symbols_scanned": len(requested_symbols),
        "symbols_with_data": len(candidates),
        "benchmark_symbol": benchmark_symbol,
        "benchmark_return_20d": benchmark_return_20d,
        "market_data": market_data_meta,
        "top_longs": long_candidates,
        "top_shorts": short_candidates,
        "analysis_plan_counts": dict(plan_counts.most_common()),
        "setup_counts": dict(setup_counts.most_common()),
        "all_candidates": candidates,
        "tool_requests": tool_requests[:100],
        "warnings": warnings[:100],
    }
    return write_json_report(
        report,
        output_dir,
        "closed_market_technical_study",
        run_id,
        latest_filename="latest_closed_market_technical_study.json",
        manifest={"market_data": market_data_meta},
    )
