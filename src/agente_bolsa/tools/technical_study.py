"""Closed-market technical scanner for long/short preparation."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .learning_mode import LEARNING_EXPERIMENT_SOURCE
from .market_data import download_daily_prices_with_metadata
from .reporting import write_json_report
from .technical_analysis import add_basic_technical_features


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
    store: Any | None = None,
    learning_mode_config: dict[str, Any] | None = None,
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

    # Generacion de candidatos via registro de estrategias (T1.2). Por defecto
    # solo `builtin_breakout` esta ACTIVE, lo que reproduce el comportamiento
    # previo (mismos candidatos), ahora etiquetados con strategy_name/version.
    from ..strategies.base import MarketContext
    from ..strategies.registry import discover

    context = MarketContext(
        symbols=requested_symbols,
        data=data,
        multi_symbol=multi_symbol,
        benchmark_return_20d=benchmark_return_20d,
    )
    learning_mode = learning_mode_config if learning_mode_config else None
    allowed_learning_strategies = {
        str(item)
        for item in list((learning_mode or {}).get("allowed_strategies") or [])
        if str(item).strip()
    }
    candidates: list[dict[str, Any]] = []
    shadow_candidates: list[dict[str, Any]] = []
    tool_requests: list[dict[str, Any]] = []
    for strategy in discover(store):
        if learning_mode and allowed_learning_strategies and strategy.name not in allowed_learning_strategies:
            continue
        produced = strategy.generate_candidates(context)
        for candidate in produced:
            candidate["strategy_name"] = strategy.name
            candidate["strategy_version"] = strategy.version
            candidate["cohort"] = LEARNING_EXPERIMENT_SOURCE if learning_mode else None
            candidate["learning_mode"] = bool(learning_mode)
        warnings.extend(getattr(strategy, "last_warnings", []) or [])
        strategy_status = str(getattr(strategy, "status", "ACTIVE")).upper()
        if learning_mode and strategy.name in allowed_learning_strategies:
            strategy_status = "ACTIVE"
            for candidate in produced:
                candidate["strategy_status"] = "LEARNING_ACTIVE"
        if strategy_status == "SHADOW":
            # Las SHADOW acumulan outcomes pero NUNCA llegan a decision/ejecucion.
            shadow_candidates.extend(produced)
            continue
        candidates.extend(produced)
        for candidate in produced:
            tool_requests.extend(candidate.get("tool_requests", []))
    if progress_callback:
        progress_callback(len(requested_symbols), len(requested_symbols), len(candidates))

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
        "shadow_candidates": shadow_candidates,
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
