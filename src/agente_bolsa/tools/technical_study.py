"""Closed-market technical scanner for long/short preparation."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .market_data import download_daily_prices
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
) -> dict[str, Any]:
    end = datetime.now(timezone.utc).date() + timedelta(days=1)
    start = end - timedelta(days=lookback_days)
    data = download_daily_prices(symbols, start=start.isoformat(), end=end.isoformat())
    multi_symbol = isinstance(data.columns, pd.MultiIndex)

    candidates: list[dict[str, Any]] = []
    tool_requests: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, symbol in enumerate(symbols, start=1):
        try:
            frame = _symbol_frame(data, symbol, multi_symbol)
            if frame.empty:
                warnings.append(f"{symbol}: sin datos")
                continue
            features = add_basic_technical_features(frame)
            candidate = validate_symbol_technical_state(symbol, features)
            candidates.append(candidate)
            tool_requests.extend(candidate.get("tool_requests", []))
        except Exception as exc:  # noqa: BLE001 - a bad symbol must not block the whole scan.
            warnings.append(f"{symbol}: {exc}")
        if progress_callback and (index % 25 == 0 or index == len(symbols)):
            progress_callback(index, len(symbols), len(candidates))

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

    report = {
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "symbols_scanned": len(symbols),
        "symbols_with_data": len(candidates),
        "top_longs": long_candidates,
        "top_shorts": short_candidates,
        "analysis_plan_counts": dict(plan_counts.most_common()),
        "all_candidates": candidates,
        "tool_requests": tool_requests[:100],
        "warnings": warnings[:100],
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"closed_market_technical_study_{run_id}.json"
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    report["path"] = str(output_path)
    return report
