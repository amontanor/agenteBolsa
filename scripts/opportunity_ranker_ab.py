#!/usr/bin/env python3
"""Shadow A/B for opportunity_ranker versus scanner order."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from agente_bolsa.config import get_settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.edge_analysis import _build_spy_forward_context
from agente_bolsa.tools.market_data import download_daily_prices
from agente_bolsa.tools.opportunity_ranker import score_symbol
from agente_bolsa.tools.signal_learning import HORIZONS


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _date_text(value: Any) -> str:
    return str(value or "")[:10]


def _benchmark_return_20d(settings, *, start: str, end: str) -> dict[str, float]:
    try:
        download_start = (date.fromisoformat(start[:10]) - timedelta(days=80)).isoformat()
    except ValueError:
        download_start = start
    try:
        frame = download_daily_prices(
            [settings.benchmark_symbol],
            start=download_start,
            end=end,
            provider=settings.market_data_provider,
            fmp_api_key=settings.fmp_api_key,
        )
    except Exception:
        return {}
    if frame.empty:
        return {}
    benchmark = str(settings.benchmark_symbol or "SPY").upper()
    if hasattr(frame.columns, "levels"):
        if benchmark not in frame.columns.get_level_values(0):
            return {}
        frame = frame[benchmark].copy()
    if "Close" not in frame.columns:
        return {}
    close = frame["Close"].dropna()
    out: dict[str, float] = {}
    for idx in range(20, len(close)):
        prev = _num(close.iloc[idx - 20])
        cur = _num(close.iloc[idx])
        if prev and cur:
            out[str(close.index[idx])[:10]] = round((cur / prev) - 1.0, 6)
    return out


def _candidate_metrics(row: dict[str, Any]) -> dict[str, Any]:
    features = row.get("features") or {}
    close = _num(features.get("close") or features.get("entry_price"))
    distance_sma20 = _num(features.get("distance_sma20"))
    distance_sma200 = _num(features.get("distance_sma200"))
    sma20 = (close / (1.0 + distance_sma20)) if close is not None and distance_sma20 is not None and (1.0 + distance_sma20) else None
    sma200 = (close / (1.0 + distance_sma200)) if close is not None and distance_sma200 is not None and (1.0 + distance_sma200) else None
    return {
        "close": close,
        "return_20d": _num(features.get("return_20d")),
        "sma_20": sma20,
        "sma_50": None,
        "sma_200": sma200,
        "volume_zscore_20": _num(features.get("volume_zscore_20")),
        "atr_14": _num(features.get("atr_14")),
        "trend_positive": close is not None and sma20 is not None and close > sma20,
        "above_long_trend": close is not None and sma200 is not None and close > sma200,
    }


def _opportunity_score(row: dict[str, Any], benchmark_20d: dict[str, float]) -> float:
    signal_date = _date_text(row.get("signal_date"))
    score = score_symbol(
        str(row.get("symbol") or ""),
        _candidate_metrics(row),
        benchmark_20d.get(signal_date, 0.0),
    )
    return float(score.score)


def _metrics(rows: list[dict[str, Any]], benchmark_forward: dict[tuple[str, int], float | None]) -> dict[str, Any]:
    out: dict[str, Any] = {"n": len(rows), "symbols": sorted({str(row.get("symbol")) for row in rows})[:20]}
    for horizon in HORIZONS:
        values: list[float] = []
        alpha_values: list[float] = []
        wins = 0
        for row in rows:
            value = _num((row.get("outcome") or {}).get(f"return_{horizon}d"))
            if value is None:
                continue
            values.append(value)
            if value > 0:
                wins += 1
            spy = benchmark_forward.get((_date_text(row.get("signal_date")), horizon))
            if spy is not None:
                alpha_values.append(value - spy)
        gains = sum(value for value in values if value > 0)
        losses = -sum(value for value in values if value < 0)
        out[f"matured_{horizon}d"] = len(values)
        out[f"expectancy_{horizon}d"] = round(sum(values) / len(values), 4) if values else None
        out[f"hit_rate_{horizon}d"] = round(wins / len(values), 4) if values else None
        out[f"profit_factor_{horizon}d"] = round(gains / losses, 4) if gains > 0 and losses > 0 else None
        out[f"alpha_{horizon}d"] = round(sum(alpha_values) / len(alpha_values), 4) if alpha_values else None
    return out


def build_report(*, since_date: str, top_n: int) -> dict[str, Any]:
    settings = get_settings()
    store = Store(settings.database_path, settings.agent_logs_dir)
    rows = [
        row
        for row in store.signal_outcomes(limit=200000, since_date=since_date)
        if (row.get("features") or {}).get("source_rank") is not None
        and str((row.get("features") or {}).get("direction") or "long").lower() == "long"
    ]
    if rows:
        start = min(_date_text(row.get("signal_date")) for row in rows)
        end = max(_date_text(row.get("signal_date")) for row in rows)
    else:
        start = end = since_date
    try:
        benchmark_end = (date.fromisoformat(end[:10]) + timedelta(days=max(HORIZONS) * 3)).isoformat()
    except ValueError:
        benchmark_end = datetime.now().date().isoformat()
    benchmark_forward = _build_spy_forward_context(settings, start=start, end=end)["returns"]
    benchmark_20d = _benchmark_return_20d(settings, start=start, end=benchmark_end)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("source_run_id") or "")].append(row)

    scanner_rows: list[dict[str, Any]] = []
    ranker_rows: list[dict[str, Any]] = []
    scanner_only: list[dict[str, Any]] = []
    ranker_only: list[dict[str, Any]] = []
    runs = 0
    for run_rows in grouped.values():
        if not run_rows:
            continue
        runs += 1
        scanner_top = sorted(run_rows, key=lambda row: int((row.get("features") or {}).get("source_rank") or 999999))[:top_n]
        ranker_top = sorted(run_rows, key=lambda row: _opportunity_score(row, benchmark_20d), reverse=True)[:top_n]
        scanner_keys = {str(row.get("signal_id")) for row in scanner_top}
        ranker_keys = {str(row.get("signal_id")) for row in ranker_top}
        scanner_rows.extend(scanner_top)
        ranker_rows.extend(ranker_top)
        scanner_only.extend([row for row in scanner_top if str(row.get("signal_id")) not in ranker_keys])
        ranker_only.extend([row for row in ranker_top if str(row.get("signal_id")) not in scanner_keys])

    return {
        "since_date": since_date,
        "top_n": top_n,
        "runs": runs,
        "benchmark_points": len(benchmark_forward),
        "benchmark_20d_points": len(benchmark_20d),
        "scanner_top": _metrics(scanner_rows, benchmark_forward),
        "ranker_top": _metrics(ranker_rows, benchmark_forward),
        "scanner_only": _metrics(scanner_only, benchmark_forward),
        "ranker_only": _metrics(ranker_only, benchmark_forward),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since-date", default="2026-04-01")
    parser.add_argument("--top-n", type=int, default=5)
    args = parser.parse_args()
    print(json.dumps(build_report(since_date=args.since_date, top_n=args.top_n), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
