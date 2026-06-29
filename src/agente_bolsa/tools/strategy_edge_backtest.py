"""Historical strategy edge study for pullback vs breakout (read-only)."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from agente_bolsa.config import Settings, get_settings
from agente_bolsa.tools.market_data import download_daily_prices_with_metadata
from agente_bolsa.tools.technical_analysis import add_basic_technical_features
from agente_bolsa.tools.universe import resolve_study_universe, universe_as_of

DEFAULT_HORIZONS = (5, 10, 20)
DEFAULT_REGIME = "spy_sma200"
DEFAULT_UNIVERSE = "sp500"
DEFAULT_BETA_LOOKBACK = 120
DEFAULT_BUFFER_CALENDAR_DAYS = 750
DEFAULT_BATCH_SIZE = 80
DEFAULT_SAMPLE_EVERY = 5
DEFAULT_PROGRESS_EVERY = 25
MIN_CURRENT_SP500_SIZE = 450


@dataclass(frozen=True)
class StrategyObservation:
    strategy_name: str
    signal_date: str
    symbol: str
    regime: str
    raw_returns: dict[int, float | None]
    benchmark_returns: dict[int, float | None]
    beta_asof: float | None


def _date_text(value: Any) -> str:
    if hasattr(value, "date"):
        return str(value.date())
    return str(value)[:10]


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_horizons(value: str | None) -> tuple[int, ...]:
    if not value:
        return DEFAULT_HORIZONS
    horizons: list[int] = []
    for item in str(value).split(","):
        token = item.strip().lower().replace("d", "")
        if not token:
            continue
        horizon = int(token)
        if horizon <= 0:
            raise ValueError("Los horizontes deben ser positivos.")
        horizons.append(horizon)
    return tuple(horizons) or DEFAULT_HORIZONS


def _normalize_download_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    if isinstance(frame.columns, pd.MultiIndex):
        if symbol not in frame.columns.get_level_values(0):
            return pd.DataFrame()
        result = frame[symbol].copy()
    else:
        result = frame.copy()
    return result.dropna(how="all")


def _merge_batches(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    non_empty = {symbol: frame for symbol, frame in frames.items() if frame is not None and not frame.empty}
    if not non_empty:
        return pd.DataFrame()
    if len(non_empty) == 1:
        return pd.concat(non_empty, axis=1)
    return pd.concat(non_empty, axis=1).sort_index()


def _batched(items: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(items), max(1, size)):
        yield items[index : index + max(1, size)]


def _temp_market_cache_dir() -> Path:
    return Path(tempfile.gettempdir()) / "agente_bolsa_strategy_edge_backtest_cache"


def download_prices_read_only(
    symbols: list[str],
    *,
    start: str,
    end: str,
    provider: str | None,
    fmp_api_key: str | None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Downloads prices using the existing market-data stack but writes cache only to temp."""

    frames: dict[str, pd.DataFrame] = {}
    batch_meta: list[dict[str, Any]] = []
    for batch in _batched(sorted(set(symbols)), batch_size):
        data, meta = download_daily_prices_with_metadata(
            batch,
            start=start,
            end=end,
            provider=provider,
            fmp_api_key=fmp_api_key,
            cache_dir=_temp_market_cache_dir(),
        )
        batch_meta.append(meta)
        for symbol in batch:
            frame = _normalize_download_frame(data, symbol)
            if not frame.empty:
                frames[symbol] = frame
    merged = _merge_batches(frames)
    requested = sorted(set(symbols))
    delivered = sorted(frames)
    return merged, {
        "requested_symbols": requested,
        "requested_count": len(requested),
        "symbols_with_data": delivered,
        "symbols_with_data_count": len(delivered),
        "missing_symbols": sorted(set(requested) - set(delivered)),
        "missing_symbols_count": len(set(requested) - set(delivered)),
        "batches": len(batch_meta),
        "batch_meta": batch_meta,
        "source": batch_meta[0].get("source") if batch_meta else None,
        "temp_cache_dir": str(_temp_market_cache_dir()),
    }


def build_point_in_time_universe_map(
    session_dates: list[str],
    *,
    universe_name: str,
    settings: Settings,
    max_symbols: int = 0,
) -> tuple[dict[str, set[str]], dict[str, Any]]:
    if universe_name.strip().lower() != "sp500":
        static = resolve_study_universe(
            universe_name,
            settings.universe,
            max_symbols,
            settings.data_dir / "cache",
        )
        static_set = set(static)
        return (
            {session_date: static_set for session_date in session_dates},
            {
                "mode": "static",
                "universe_name": universe_name,
                "survivorship_biased": True,
                "current_universe_size": len(static_set),
            },
        )

    current = resolve_study_universe("sp500", settings.universe, 0, settings.data_dir / "cache")
    likely_fallback = len(current) < MIN_CURRENT_SP500_SIZE
    universe_map: dict[str, set[str]] = {}
    survivorship_biased = likely_fallback
    counts: list[int] = []
    for session_date in session_dates:
        state = universe_as_of(session_date, current_universe=current)
        symbols = state.get("symbols") or []
        if max_symbols > 0:
            symbols = symbols[:max_symbols]
        symbol_set = {str(symbol).upper() for symbol in symbols if str(symbol).strip()}
        universe_map[session_date] = symbol_set
        counts.append(len(symbol_set))
        survivorship_biased = survivorship_biased or bool(state.get("survivorship_biased"))
    return universe_map, {
        "mode": "point_in_time" if not survivorship_biased else "point_in_time_fallback",
        "universe_name": universe_name,
        "survivorship_biased": survivorship_biased,
        "current_universe_size": len(current),
        "likely_fallback_current_universe": likely_fallback,
        "daily_universe_min": min(counts) if counts else 0,
        "daily_universe_max": max(counts) if counts else 0,
    }


def build_forward_return_map(close: pd.Series, horizons: tuple[int, ...]) -> dict[int, dict[str, float | None]]:
    result: dict[int, dict[str, float | None]] = {}
    base = close.astype(float)
    for horizon in horizons:
        shifted = base.shift(-int(horizon))
        values = ((shifted / base) - 1.0).round(6)
        result[int(horizon)] = {_date_text(idx): _safe_float(val) for idx, val in values.items()}
    return result


def build_beta_map(close: pd.Series, spy_close: pd.Series, *, lookback: int) -> dict[str, float | None]:
    symbol_returns = close.astype(float).pct_change()
    spy_returns = spy_close.astype(float).pct_change()
    joined = pd.concat({"symbol": symbol_returns, "spy": spy_returns}, axis=1).dropna()
    if joined.empty:
        return {}
    covariance = joined["symbol"].rolling(int(lookback)).cov(joined["spy"])
    variance = joined["spy"].rolling(int(lookback)).var()
    beta = (covariance / variance).round(6)
    return {_date_text(idx): _safe_float(val) for idx, val in beta.items()}


def build_regime_map(spy_features: pd.DataFrame, *, mode: str = DEFAULT_REGIME) -> dict[str, str]:
    if mode != DEFAULT_REGIME:
        raise ValueError(f"Regime mode no soportado: {mode}")
    result: dict[str, str] = {}
    for idx, row in spy_features.iterrows():
        close = _safe_float(row.get("Close"))
        sma200 = _safe_float(row.get("sma_200"))
        label = "unknown"
        if close is not None and sma200 is not None:
            label = "bull_above_sma200" if close > sma200 else "bear_below_sma200"
        result[_date_text(idx)] = label
    return result


def _bool_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index)
    return frame[column].fillna(False).astype(bool)


def add_vector_signal_columns(features: pd.DataFrame) -> pd.DataFrame:
    """Adds causal vectorized approximations of the live technical predicates."""

    result = features.copy()
    close = result["Close"].astype(float)
    high = result["High"].astype(float)
    ret_5 = result["return_5d"].astype(float)
    ret_20 = result["return_20d"].astype(float)
    ret_60 = result["return_60d"].astype(float)
    rsi = result["rsi_14"].astype(float)
    volume_z = result["volume_zscore_20"].astype(float)
    gap_pct = result["gap_pct"].astype(float)
    close_position = result["close_position_in_range"].astype(float)
    prev_high_55 = result["prev_high_55"].astype(float)
    pct_b = result["bollinger_pct_b_20"].astype(float)
    macd = result["macd"].astype(float)
    macd_signal = result["macd_signal"].astype(float)
    above_long = _bool_series(result, "above_long_trend")
    trend_positive = _bool_series(result, "trend_positive")

    result["vector_breakout_continuation_long"] = (
        (volume_z >= 1.0)
        & (close_position >= 0.60)
        & (ret_20 > 0)
        & (prev_high_55.isna() | (prev_high_55 == 0) | (close >= prev_high_55 * 1.003))
    )
    result["vector_range_expansion_breakout_long"] = (
        (gap_pct >= 0.03)
        & (volume_z >= 1.0)
        & (close_position >= 0.75)
        & (rsi >= 50)
        & (rsi <= 78)
        & (ret_20 > 0)
        & prev_high_55.notna()
        & (prev_high_55 != 0)
        & (close >= prev_high_55 * 1.015)
    )
    result["vector_orderly_breakout_long"] = (
        (close_position >= 0.80)
        & (volume_z >= 0.25)
        & (rsi >= 52)
        & (rsi <= 74)
        & (ret_20 > 0)
        & prev_high_55.notna()
        & (prev_high_55 != 0)
        & (close >= prev_high_55 * 1.015)
    )
    result["vector_breakout_failure_risk"] = (
        prev_high_55.notna()
        & (prev_high_55 != 0)
        & (high >= prev_high_55 * 1.003)
        & (close < prev_high_55)
        & (volume_z >= 1.0)
    )
    result["vector_event_momentum_long"] = (
        (gap_pct >= 0.07)
        & (volume_z >= 2.0)
        & (close_position >= 0.65)
        & (prev_high_55.isna() | (prev_high_55 == 0) | (close >= prev_high_55 * 1.02))
    )
    result["vector_momentum_shakeout_hold_long"] = (
        (gap_pct <= -0.02)
        & (ret_5 >= 0.08)
        & (volume_z >= 1.5)
        & (close_position >= 0.70)
        & above_long
    )

    long_score = pd.Series(0, index=result.index, dtype="int64")
    short_score = pd.Series(0, index=result.index, dtype="int64")
    long_score += above_long.astype("int64") * 2
    short_score += (~above_long).astype("int64") * 2
    long_score += trend_positive.astype("int64") * 2
    short_score += (~trend_positive).astype("int64") * 2
    long_score += (ret_20 > 0.05).fillna(False).astype("int64") * 2
    short_score += (ret_20 < -0.05).fillna(False).astype("int64") * 2
    long_score += (ret_60 > 0.08).fillna(False).astype("int64")
    short_score += (ret_60 < -0.08).fillna(False).astype("int64")
    long_score += (macd > macd_signal).fillna(False).astype("int64")
    short_score += (macd <= macd_signal).fillna(False).astype("int64")
    long_score += (rsi <= 25).fillna(False).astype("int64")
    short_score += (rsi >= 75).fillna(False).astype("int64")
    long_score += ((rsi >= 45) & (rsi <= 68)).fillna(False).astype("int64")
    volume_event = (volume_z >= 1.5).fillna(False)
    long_score += (volume_event & (ret_5 >= 0)).fillna(False).astype("int64")
    short_score += (volume_event & (ret_5 < 0)).fillna(False).astype("int64")
    long_score += (pct_b >= 0.9).fillna(False).astype("int64")
    short_score += (pct_b <= 0.1).fillna(False).astype("int64")

    event = result["vector_event_momentum_long"].astype(bool)
    range_breakout = result["vector_range_expansion_breakout_long"].astype(bool)
    orderly = result["vector_orderly_breakout_long"].astype(bool)
    continuation = result["vector_breakout_continuation_long"].astype(bool)
    long_score += event.astype("int64") * 3
    long_score += (~event & range_breakout).astype("int64") * 3
    long_score += (~event & ~range_breakout & orderly).astype("int64") * 3
    long_score += (~event & ~range_breakout & ~orderly & continuation).astype("int64") * 2
    long_score += result["vector_momentum_shakeout_hold_long"].astype("int64") * 2
    short_score += result["vector_breakout_failure_risk"].astype("int64") * 2
    long_score -= result["vector_breakout_failure_risk"].astype("int64")

    long_score += _bool_series(result, "candle_bullish_signal").astype("int64")
    short_score += _bool_series(result, "candle_bearish_signal").astype("int64")
    doji = _bool_series(result, "candle_doji").astype("int64")
    long_score -= doji
    short_score -= doji

    result["vector_long_score"] = long_score
    result["vector_short_score"] = short_score
    result["vector_direction_long"] = long_score >= short_score
    distance_sma20 = (close - result["sma_20"].astype(float)) / result["sma_20"].astype(float)
    result["vector_distance_sma20"] = distance_sma20
    result["vector_pullback_signal"] = (
        result["vector_direction_long"]
        & (close > result["sma_200"].astype(float))
        & (close > result["sma_50"].astype(float))
        & (distance_sma20 >= -0.05)
        & (distance_sma20 <= 0.08)
        & (rsi >= 40)
        & (rsi <= 60)
        & (ret_5 <= 0.02)
        & (ret_20 >= -0.08)
        & (ret_60 > 0)
        & ~event
        & ~range_breakout
        & ~orderly
        & ~continuation
    )
    result["vector_breakout_signal"] = result["vector_direction_long"]
    return result


def sampled_session_dates(session_dates: list[str], *, every: int) -> list[str]:
    step = max(1, int(every))
    return session_dates[::step]


def summarize_observations(
    observations: list[StrategyObservation],
    *,
    horizons: tuple[int, ...],
    cost_bps: float,
) -> dict[str, Any]:
    cost = cost_bps / 10000.0
    strategies = sorted({item.strategy_name for item in observations})
    regimes = sorted({item.regime for item in observations})

    def _stats(values: list[float]) -> dict[str, Any]:
        if not values:
            return {"n": 0, "mean": None, "median": None, "hit_rate": None, "std": None, "mean_net": None}
        mean = sum(values) / len(values)
        return {
            "n": len(values),
            "mean": round(mean, 6),
            "median": round(statistics.median(values), 6),
            "hit_rate": round(sum(1 for value in values if value > 0) / len(values), 4),
            "std": round(statistics.stdev(values), 6) if len(values) > 1 else 0.0,
            "mean_net": round(mean - cost, 6),
        }

    def _delta(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
        return {
            "left_n": left.get("n", 0),
            "right_n": right.get("n", 0),
            "mean_delta": (
                round(float(left["mean"]) - float(right["mean"]), 6)
                if left.get("mean") is not None and right.get("mean") is not None
                else None
            ),
            "mean_net_delta": (
                round(float(left["mean_net"]) - float(right["mean_net"]), 6)
                if left.get("mean_net") is not None and right.get("mean_net") is not None
                else None
            ),
        }

    summary: dict[str, Any] = {
        "sample": {
            "observations": len(observations),
            "strategies": strategies,
            "regimes": regimes,
            "cost_bps": cost_bps,
        },
        "overall": {},
        "by_regime": {},
        "delta_pullback_minus_breakout": {},
        "delta_by_regime_pullback_minus_breakout": {},
    }
    for strategy in strategies:
        strategy_rows = [item for item in observations if item.strategy_name == strategy]
        summary["overall"][strategy] = {}
        for regime in regimes:
            regime_rows = [item for item in strategy_rows if item.regime == regime]
            summary["by_regime"].setdefault(regime, {})[strategy] = {}
            for horizon in horizons:
                raw_values = [item.raw_returns.get(horizon) for item in regime_rows if item.raw_returns.get(horizon) is not None]
                excess_values = [
                    item.raw_returns[horizon] - item.benchmark_returns[horizon]
                    for item in regime_rows
                    if item.raw_returns.get(horizon) is not None and item.benchmark_returns.get(horizon) is not None
                ]
                beta_values = [
                    item.raw_returns[horizon] - float(item.beta_asof) * item.benchmark_returns[horizon]
                    for item in regime_rows
                    if item.raw_returns.get(horizon) is not None
                    and item.benchmark_returns.get(horizon) is not None
                    and item.beta_asof is not None
                ]
                summary["by_regime"][regime][strategy][f"return_{horizon}d"] = {
                    "raw": _stats(raw_values),
                    "excess_vs_spy": _stats(excess_values),
                    "beta_adjusted_vs_spy": _stats(beta_values),
                }
        for horizon in horizons:
            raw_values = [
                item.raw_returns.get(horizon)
                for item in strategy_rows
                if item.raw_returns.get(horizon) is not None
            ]
            excess_values = [
                item.raw_returns[horizon] - item.benchmark_returns[horizon]
                for item in strategy_rows
                if item.raw_returns.get(horizon) is not None and item.benchmark_returns.get(horizon) is not None
            ]
            beta_values = [
                item.raw_returns[horizon] - float(item.beta_asof) * item.benchmark_returns[horizon]
                for item in strategy_rows
                if item.raw_returns.get(horizon) is not None
                and item.benchmark_returns.get(horizon) is not None
                and item.beta_asof is not None
            ]
            summary["overall"][strategy][f"return_{horizon}d"] = {
                "raw": _stats(raw_values),
                "excess_vs_spy": _stats(excess_values),
                "beta_adjusted_vs_spy": _stats(beta_values),
            }

    if "builtin_pullback" in summary["overall"] and "builtin_breakout" in summary["overall"]:
        for horizon in horizons:
            key = f"return_{horizon}d"
            summary["delta_pullback_minus_breakout"][key] = {
                metric: _delta(
                    summary["overall"]["builtin_pullback"][key][metric],
                    summary["overall"]["builtin_breakout"][key][metric],
                )
                for metric in ("raw", "excess_vs_spy", "beta_adjusted_vs_spy")
            }
        for regime in regimes:
            pullback_regime = summary["by_regime"].get(regime, {}).get("builtin_pullback")
            breakout_regime = summary["by_regime"].get(regime, {}).get("builtin_breakout")
            if not pullback_regime or not breakout_regime:
                continue
            summary["delta_by_regime_pullback_minus_breakout"][regime] = {}
            for horizon in horizons:
                key = f"return_{horizon}d"
                summary["delta_by_regime_pullback_minus_breakout"][regime][key] = {
                    metric: _delta(pullback_regime[key][metric], breakout_regime[key][metric])
                    for metric in ("raw", "excess_vs_spy", "beta_adjusted_vs_spy")
                }
    return summary


def run_pullback_breakout_backtest(
    *,
    since: str,
    end: str,
    horizons: tuple[int, ...],
    cost_bps: float,
    universe_name: str = DEFAULT_UNIVERSE,
    max_symbols: int = 0,
    beta_lookback: int = DEFAULT_BETA_LOOKBACK,
    regime_mode: str = DEFAULT_REGIME,
    provider: str | None = None,
    fmp_api_key: str | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    sample_every: int = DEFAULT_SAMPLE_EVERY,
    progress_every: int = DEFAULT_PROGRESS_EVERY,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    fetch_start = (
        date.fromisoformat(since) - timedelta(days=DEFAULT_BUFFER_CALENDAR_DAYS)
    ).isoformat()
    spy_data, spy_meta = download_prices_read_only(
        [settings.benchmark_symbol],
        start=fetch_start,
        end=end,
        provider=provider or settings.market_data_provider,
        fmp_api_key=fmp_api_key or settings.fmp_api_key,
        batch_size=1,
    )
    spy_symbol = str(settings.benchmark_symbol or "SPY").upper()
    spy_frame = _normalize_download_frame(spy_data, spy_symbol)
    spy_features = add_basic_technical_features(spy_frame).dropna(subset=["Close"]).copy()
    session_dates = [_date_text(index) for index in spy_features.index if since <= _date_text(index) <= end]
    sampled_dates = sampled_session_dates(session_dates, every=sample_every)
    universe_map, universe_meta = build_point_in_time_universe_map(
        sampled_dates,
        universe_name=universe_name,
        settings=settings,
        max_symbols=max_symbols,
    )
    union_symbols = sorted({symbol for symbols in universe_map.values() for symbol in symbols})
    prices, market_data_meta = download_prices_read_only(
        union_symbols,
        start=fetch_start,
        end=end,
        provider=provider or settings.market_data_provider,
        fmp_api_key=fmp_api_key or settings.fmp_api_key,
        batch_size=batch_size,
    )

    spy_close = spy_features["Close"].copy()
    benchmark_returns = build_forward_return_map(spy_close, horizons)
    regime_by_date = build_regime_map(spy_features, mode=regime_mode)

    observations: list[StrategyObservation] = []
    signal_counts = {"builtin_pullback": 0, "builtin_breakout": 0}
    symbols_scanned = 0
    symbols_with_features = 0
    started_at = time.perf_counter()
    total_symbols = len(union_symbols)
    for ordinal, symbol in enumerate(union_symbols, start=1):
        if progress_every > 0 and (ordinal == 1 or ordinal % progress_every == 0 or ordinal == total_symbols):
            elapsed = max(time.perf_counter() - started_at, 0.001)
            rate = ordinal / elapsed
            remaining = max(total_symbols - ordinal, 0)
            eta = remaining / rate if rate > 0 else 0.0
            print(
                (
                    f"[strategy-edge-backtest] {ordinal}/{total_symbols} symbols | "
                    f"elapsed={elapsed:.1f}s | eta={eta:.1f}s | "
                    f"signals={signal_counts}"
                ),
                file=sys.stderr,
                flush=True,
            )
        frame = _normalize_download_frame(prices, symbol)
        if frame.empty or "Close" not in frame.columns:
            continue
        symbols_scanned += 1
        try:
            features = add_vector_signal_columns(add_basic_technical_features(frame).dropna(subset=["Close"]).copy())
        except Exception:
            continue
        if features.empty:
            continue
        symbols_with_features += 1
        features["_signal_date"] = [_date_text(index) for index in features.index]
        features["_position"] = range(len(features))
        eligible_dates = {
            session_date
            for session_date in sampled_dates
            if symbol in universe_map.get(session_date, set())
        }
        if not eligible_dates:
            continue
        eligible = features[
            features["_signal_date"].isin(eligible_dates)
            & (features["_position"] >= 419)
        ]
        if eligible.empty:
            continue
        raw_returns = build_forward_return_map(features["Close"], horizons)
        beta_by_date = build_beta_map(features["Close"], spy_close, lookback=beta_lookback)
        signal_rows = eligible[
            eligible["vector_pullback_signal"].fillna(False)
            | eligible["vector_breakout_signal"].fillna(False)
        ]
        for _index, row in signal_rows.iterrows():
            session_date = str(row.get("_signal_date") or "")[:10]
            if bool(row.get("vector_pullback_signal", False)):
                signal_counts["builtin_pullback"] += 1
                observations.append(
                    StrategyObservation(
                        strategy_name="builtin_pullback",
                        signal_date=session_date,
                        symbol=symbol,
                        regime=regime_by_date.get(session_date, "unknown"),
                        raw_returns={h: raw_returns[h].get(session_date) for h in horizons},
                        benchmark_returns={h: benchmark_returns[h].get(session_date) for h in horizons},
                        beta_asof=beta_by_date.get(session_date),
                    )
                )

            if bool(row.get("vector_breakout_signal", False)):
                signal_counts["builtin_breakout"] += 1
                observations.append(
                    StrategyObservation(
                        strategy_name="builtin_breakout",
                        signal_date=session_date,
                        symbol=symbol,
                        regime=regime_by_date.get(session_date, "unknown"),
                        raw_returns={h: raw_returns[h].get(session_date) for h in horizons},
                        benchmark_returns={h: benchmark_returns[h].get(session_date) for h in horizons},
                        beta_asof=beta_by_date.get(session_date),
                    )
                )

    summary = summarize_observations(observations, horizons=horizons, cost_bps=cost_bps)
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "study": {
            "name": "pullback_vs_breakout_historical_edge",
            "since": since,
            "end": end,
            "horizons": list(horizons),
            "cost_bps": cost_bps,
            "beta_lookback": beta_lookback,
            "regime_mode": regime_mode,
            "benchmark_symbol": spy_symbol,
            "universe_name": universe_name,
            "max_symbols": max_symbols,
            "fetch_start": fetch_start,
            "sample_every_sessions": sample_every,
            "signal_sampling": "weekly" if int(sample_every) == 5 else f"every_{sample_every}_sessions",
            "vectorized_predicates": True,
            "limitations": [
                "builtin_breakout is approximated with the vectorized technical validator score/flags; chart_patterns are omitted.",
                "pullback filter uses vectorized equivalents of the live pullback thresholds and excludes vectorized momentum/breakout flags.",
                "forward returns use close[t+N]/close[t]-1, matching signal_learning outcome convention.",
            ],
        },
        "universe": universe_meta,
        "market_data": {
            "benchmark": spy_meta,
            "universe_prices": market_data_meta,
        },
        "scan": {
            "session_dates": len(session_dates),
            "sampled_signal_dates": len(sampled_dates),
            "symbols_scanned": symbols_scanned,
            "symbols_with_features": symbols_with_features,
            "signal_counts": signal_counts,
            "elapsed_seconds": round(time.perf_counter() - started_at, 2),
        },
        "summary": summary,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backtest historico read-only de edge pullback vs breakout.")
    parser.add_argument("--since", default="2024-01-01", help="Fecha inicial de estudio YYYY-MM-DD.")
    parser.add_argument("--to", dest="end", default=date.today().isoformat(), help="Fecha final YYYY-MM-DD.")
    parser.add_argument("--horizons", default="5,10,20", help="Horizontes forward separados por coma.")
    parser.add_argument("--cost-bps", type=float, default=10.0, help="Coste round-trip en bps.")
    parser.add_argument("--universe", default=DEFAULT_UNIVERSE, help="Universo. Default: sp500.")
    parser.add_argument("--max-symbols", type=int, default=0, help="Limite opcional de simbolos.")
    parser.add_argument("--beta-lookback", type=int, default=DEFAULT_BETA_LOOKBACK, help="Lookback de beta.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Tamano de batch de descarga.")
    parser.add_argument(
        "--sample-every",
        type=int,
        default=DEFAULT_SAMPLE_EVERY,
        help="Evalua senales cada N sesiones para reducir solape forward. Default: 5.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=DEFAULT_PROGRESS_EVERY,
        help="Imprime progreso cada N simbolos en stderr. 0 desactiva.",
    )
    parser.add_argument("--json", action="store_true", help="Imprime JSON completo.")
    return parser


def print_summary(report: dict[str, Any]) -> None:
    summary = report["summary"]

    def _pct(value: float | None) -> str:
        return "n/d" if value is None else f"{value * 100:.2f}%"

    print("\n=== Backtest historico pullback vs breakout (read-only) ===")
    print(
        f"ventana={report['study']['since']}->{report['study']['end']} | "
        f"horizons={report['study']['horizons']} | "
        f"cost_bps={report['study']['cost_bps']} | universo={report['study']['universe_name']}"
    )
    print(
        f"survivorship_biased={report['universe']['survivorship_biased']} | "
        f"sesiones={report['scan']['session_dates']} | sampled={report['scan']['sampled_signal_dates']} | "
        f"senales pullback={report['scan']['signal_counts']['builtin_pullback']} | "
        f"senales breakout={report['scan']['signal_counts']['builtin_breakout']}"
    )
    print("\nOverall:")
    print(f"{'strategy':<18}{'horizon':<12}{'metric':<22}{'n':>8}{'mean':>12}{'median':>12}{'hit':>10}{'std':>12}{'mean_net':>12}")
    for strategy, per_horizon in summary["overall"].items():
        for horizon_key, blocks in per_horizon.items():
            for metric_name, stats in blocks.items():
                print(
                    f"{strategy:<18}{horizon_key:<12}{metric_name:<22}{stats['n']:>8}"
                    f"{_pct(stats['mean']):>12}"
                    f"{_pct(stats['median']):>12}"
                    f"{_pct(stats['hit_rate']):>10}"
                    f"{_pct(stats['std']):>12}"
                    f"{_pct(stats['mean_net']):>12}"
                )
    print("\nDelta pullback - breakout:")
    print(f"{'horizon':<12}{'metric':<22}{'pull_n':>8}{'brk_n':>8}{'mean_delta':>14}{'net_delta':>14}")
    for horizon_key, blocks in summary["delta_pullback_minus_breakout"].items():
        for metric_name, delta in blocks.items():
            print(
                f"{horizon_key:<12}{metric_name:<22}{delta['left_n']:>8}{delta['right_n']:>8}"
                f"{_pct(delta['mean_delta']):>14}"
                f"{_pct(delta['mean_net_delta']):>14}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    report = run_pullback_breakout_backtest(
        since=args.since,
        end=args.end,
        horizons=_parse_horizons(args.horizons),
        cost_bps=args.cost_bps,
        universe_name=args.universe,
        max_symbols=args.max_symbols,
        beta_lookback=args.beta_lookback,
        batch_size=args.batch_size,
        sample_every=args.sample_every,
        progress_every=args.progress_every,
    )
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        print_summary(report)
    return 0


__all__ = [
    "StrategyObservation",
    "build_beta_map",
    "build_forward_return_map",
    "build_point_in_time_universe_map",
    "build_regime_map",
    "build_parser",
    "add_vector_signal_columns",
    "main",
    "run_pullback_breakout_backtest",
    "sampled_session_dates",
    "summarize_observations",
]
