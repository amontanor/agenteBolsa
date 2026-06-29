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


@dataclass(frozen=True)
class SelectorObservation:
    cohort: str
    signal_date: str
    symbol: str
    regime: str
    selector_score: float
    technical_score: float
    score_decile: int | None
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


def add_vector_selector_columns(
    features: pd.DataFrame,
    *,
    benchmark_return_20d_by_date: dict[str, float | None],
    settings: Settings,
) -> pd.DataFrame:
    """Adds a causal vectorized approximation of the deterministic selector score."""

    result = features.copy()
    if "vector_long_score" not in result.columns or "vector_short_score" not in result.columns:
        result = add_vector_signal_columns(result)
    if "_signal_date" not in result.columns:
        result["_signal_date"] = [_date_text(index) for index in result.index]

    score = result[["vector_long_score", "vector_short_score"]].max(axis=1).astype(float)
    long_score = result["vector_long_score"].astype(float)
    short_score = result["vector_short_score"].astype(float)
    ret_20 = result["return_20d"].astype(float)
    ret_60 = result["return_60d"].astype(float)
    rsi = result["rsi_14"].astype(float)
    volume_z = result["volume_zscore_20"].astype(float)
    close_position = result["close_position_in_range"].astype(float)
    distance = result["vector_distance_sma20"].astype(float)
    pct_b = result["bollinger_pct_b_20"].astype(float)
    close = result["Close"].astype(float)
    atr = result["atr_14"].astype(float) if "atr_14" in result.columns else pd.Series(1.0, index=result.index)
    benchmark_20 = result["_signal_date"].map(benchmark_return_20d_by_date).astype(float)
    relative_return_20d = ret_20 - benchmark_20.fillna(0.0)

    setup_quality_strong = (long_score.sub(short_score).abs() > 1) & (score >= 7)
    result["vector_selector_eligible"] = (
        result["vector_direction_long"].fillna(False).astype(bool)
        & setup_quality_strong
        & (ret_20 > 0)
        & (atr > 0)
        & (close > 0)
    )
    result["vector_technical_score"] = score
    result["vector_relative_return_20d"] = relative_return_20d

    score_component = (score / 1200.0).clip(lower=0.0, upper=0.025)
    relative_component = (relative_return_20d * 0.20).clip(lower=-0.010, upper=0.020)
    leader_like = (
        (score >= getattr(settings, "selection_leader_momentum_min_score", 11))
        & (relative_return_20d >= getattr(settings, "selection_leader_momentum_min_relative_return_20d", 0.16))
        & (distance <= getattr(settings, "selection_leader_momentum_max_sma20_distance", 0.33))
        & (rsi <= getattr(settings, "selection_leader_momentum_max_rsi", 86.0))
        & (close_position >= getattr(settings, "selection_leader_momentum_min_close_position_in_range", 0.35))
    )
    emerging_like = (
        (score >= getattr(settings, "selection_emerging_leader_min_score", 10))
        & (score <= getattr(settings, "selection_emerging_leader_max_score", 11))
        & (ret_20 >= getattr(settings, "selection_emerging_leader_min_return_20d", 0.08))
        & (rsi >= getattr(settings, "selection_emerging_leader_min_rsi", 75.0))
        & (rsi <= getattr(settings, "selection_emerging_leader_max_rsi", 86.0))
        & (distance >= getattr(settings, "selection_emerging_leader_min_sma20_distance", 0.04))
        & (distance <= getattr(settings, "selection_emerging_leader_max_sma20_distance", 0.15))
        & (close_position >= getattr(settings, "selection_emerging_leader_min_close_position_in_range", 0.75))
    )
    parabolic_like = (
        (score >= getattr(settings, "selection_parabolic_leader_min_score", 14))
        & (ret_20 >= getattr(settings, "selection_parabolic_leader_min_return_20d", 0.60))
        & (rsi >= getattr(settings, "selection_parabolic_leader_min_rsi", 85.0))
        & (rsi <= getattr(settings, "selection_parabolic_leader_max_rsi", 94.0))
        & (distance >= getattr(settings, "selection_parabolic_leader_min_sma20_distance", 0.25))
        & (distance <= getattr(settings, "selection_parabolic_leader_max_sma20_distance", 0.45))
    )
    volume_component = pd.Series(0.0, index=result.index)
    volume_component = volume_component.mask(volume_z >= 1.0, 0.006)
    volume_component = volume_component.mask((volume_z < 0) & ~(leader_like | emerging_like | parabolic_like), -0.006)

    continuation_component = pd.Series(0.0, index=result.index)
    continuation_component = continuation_component.mask(
        result["vector_orderly_breakout_long"].fillna(False).astype(bool),
        0.012,
    )
    continuation_component = continuation_component.mask(
        ~result["vector_orderly_breakout_long"].fillna(False).astype(bool)
        & result["vector_breakout_continuation_long"].fillna(False).astype(bool),
        0.008,
    )
    leader_bonus = pd.Series(0.0, index=result.index)
    leader_bonus = leader_bonus.mask(
        leader_like,
        float(getattr(settings, "selection_leader_momentum_selection_bonus", 0.016)),
    )
    leader_bonus = leader_bonus.mask(
        emerging_like,
        float(getattr(settings, "selection_emerging_leader_selection_bonus", 0.018)),
    )
    leader_bonus = leader_bonus.mask(
        parabolic_like,
        float(getattr(settings, "selection_parabolic_leader_selection_bonus", 0.020)),
    )
    constructive_like = (
        (score >= getattr(settings, "selection_constructive_early_min_score", 14))
        & (score <= getattr(settings, "selection_constructive_early_max_score", 16))
        & (ret_20 >= getattr(settings, "selection_constructive_early_min_return_20d", 0.065))
        & (ret_20 <= getattr(settings, "selection_constructive_early_max_return_20d", 0.09))
        & (ret_60 >= getattr(settings, "selection_constructive_early_min_return_60d", 0.03))
        & (ret_60 <= getattr(settings, "selection_constructive_early_max_return_60d", 0.14))
        & (rsi >= getattr(settings, "selection_constructive_early_min_rsi", 65.0))
        & (rsi <= getattr(settings, "selection_constructive_early_max_rsi", 72.0))
        & (distance >= getattr(settings, "selection_constructive_early_min_sma20_distance", 0.055))
        & (distance <= getattr(settings, "selection_constructive_early_max_sma20_distance", 0.08))
        & (pct_b >= getattr(settings, "selection_constructive_early_min_bollinger_pct_b", 0.85))
    )
    constructive_bonus = pd.Series(0.0, index=result.index).mask(
        constructive_like,
        float(getattr(settings, "selection_constructive_early_selection_bonus", 0.014)),
    )
    failure_penalty = pd.Series(0.0, index=result.index).mask(
        result["vector_breakout_failure_risk"].fillna(False).astype(bool),
        0.020,
    )
    setup_risk_penalty = pd.Series(0.0, index=result.index).mask(
        result["vector_range_expansion_breakout_long"].fillna(False).astype(bool),
        0.080,
    )
    negative_pocket = pd.Series(0.0, index=result.index)
    if bool(getattr(settings, "selection_negative_pocket_penalty_enabled", False)):
        negative_pocket += ((volume_z < 0).fillna(False)).astype(float) * float(
            getattr(settings, "selection_negative_pocket_weak_volume_penalty", 0.025)
        )
        negative_pocket += (((distance >= 0) & (distance < 0.06)).fillna(False)).astype(float) * float(
            getattr(settings, "selection_negative_pocket_tight_sma20_penalty", 0.03)
        )
        negative_pocket += (((rsi >= 60) & (rsi < 75)).fillna(False)).astype(float) * float(
            getattr(settings, "selection_negative_pocket_mid_rsi_penalty", 0.02)
        )

    result["vector_selector_score"] = (
        -0.018
        + score_component
        + relative_component
        + volume_component
        + continuation_component
        + leader_bonus
        + constructive_bonus
        - failure_penalty
        - setup_risk_penalty
        - negative_pocket
    ).round(6)
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


def _max_drawdown(period_returns: list[float]) -> float | None:
    if not period_returns:
        return None
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for value in period_returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = min(max_drawdown, (equity / peak) - 1.0)
    return round(max_drawdown, 6)


def _stats(values: list[float], *, cost: float, dated_values: list[tuple[str, float]] | None = None) -> dict[str, Any]:
    if not values:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "hit_rate": None,
            "std": None,
            "mean_net": None,
            "sharpe_simple": None,
            "downside_deviation": None,
            "tail_loss_rate_lt_10pct": None,
            "max_drawdown": None,
        }
    mean = sum(values) / len(values)
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    net_values = [value - cost for value in values]
    downside_values = [min(0.0, value) for value in net_values]
    downside_deviation = (sum(value * value for value in downside_values) / len(downside_values)) ** 0.5
    by_date: dict[str, list[float]] = {}
    for signal_date, value in dated_values or []:
        by_date.setdefault(str(signal_date), []).append(value - cost)
    period_returns = [sum(items) / len(items) for _date, items in sorted(by_date.items()) if items]
    return {
        "n": len(values),
        "mean": round(mean, 6),
        "median": round(statistics.median(values), 6),
        "hit_rate": round(sum(1 for value in values if value > 0) / len(values), 4),
        "std": round(std, 6),
        "mean_net": round(mean - cost, 6),
        "sharpe_simple": round((mean - cost) / std, 6) if std > 0 else None,
        "downside_deviation": round(downside_deviation, 6),
        "tail_loss_rate_lt_10pct": round(sum(1 for value in net_values if value < -0.10) / len(net_values), 4),
        "max_drawdown": _max_drawdown(period_returns),
    }


def _metric_values(
    rows: list[SelectorObservation],
    *,
    horizon: int,
    metric: str,
) -> list[float]:
    if metric == "raw":
        return [item.raw_returns[horizon] for item in rows if item.raw_returns.get(horizon) is not None]
    if metric == "excess_vs_spy":
        return [
            item.raw_returns[horizon] - item.benchmark_returns[horizon]
            for item in rows
            if item.raw_returns.get(horizon) is not None and item.benchmark_returns.get(horizon) is not None
        ]
    if metric == "beta_adjusted_vs_spy":
        return [
            item.raw_returns[horizon] - float(item.beta_asof) * item.benchmark_returns[horizon]
            for item in rows
            if item.raw_returns.get(horizon) is not None
            and item.benchmark_returns.get(horizon) is not None
            and item.beta_asof is not None
        ]
    raise ValueError(f"Metric no soportada: {metric}")


def _metric_dated_values(
    rows: list[SelectorObservation],
    *,
    horizon: int,
    metric: str,
) -> list[tuple[str, float]]:
    if metric == "raw":
        return [
            (item.signal_date, item.raw_returns[horizon])
            for item in rows
            if item.raw_returns.get(horizon) is not None
        ]
    if metric == "excess_vs_spy":
        return [
            (item.signal_date, item.raw_returns[horizon] - item.benchmark_returns[horizon])
            for item in rows
            if item.raw_returns.get(horizon) is not None and item.benchmark_returns.get(horizon) is not None
        ]
    if metric == "beta_adjusted_vs_spy":
        return [
            (item.signal_date, item.raw_returns[horizon] - float(item.beta_asof) * item.benchmark_returns[horizon])
            for item in rows
            if item.raw_returns.get(horizon) is not None
            and item.benchmark_returns.get(horizon) is not None
            and item.beta_asof is not None
        ]
    raise ValueError(f"Metric no soportada: {metric}")


def summarize_selector_observations(
    observations: list[SelectorObservation],
    *,
    horizons: tuple[int, ...],
    cost_bps: float,
) -> dict[str, Any]:
    cost = cost_bps / 10000.0
    cohorts = sorted({item.cohort for item in observations})
    regimes = sorted({item.regime for item in observations})
    metrics = ("raw", "excess_vs_spy", "beta_adjusted_vs_spy")
    summary: dict[str, Any] = {
        "sample": {
            "observations": len(observations),
            "cohorts": cohorts,
            "regimes": regimes,
            "cost_bps": cost_bps,
        },
        "overall": {},
        "by_regime": {},
        "delta_top_n_minus_population": {},
        "score_deciles": {},
        "score_monotonicity": {},
    }

    for cohort in cohorts:
        cohort_rows = [item for item in observations if item.cohort == cohort]
        summary["overall"][cohort] = {}
        for horizon in horizons:
            key = f"return_{horizon}d"
            summary["overall"][cohort][key] = {
                metric: _stats(
                    _metric_values(cohort_rows, horizon=horizon, metric=metric),
                    cost=cost,
                    dated_values=_metric_dated_values(cohort_rows, horizon=horizon, metric=metric),
                )
                for metric in metrics
            }
        for regime in regimes:
            regime_rows = [item for item in cohort_rows if item.regime == regime]
            summary["by_regime"].setdefault(regime, {})[cohort] = {}
            for horizon in horizons:
                key = f"return_{horizon}d"
                summary["by_regime"][regime][cohort][key] = {
                    metric: _stats(
                        _metric_values(regime_rows, horizon=horizon, metric=metric),
                        cost=cost,
                        dated_values=_metric_dated_values(regime_rows, horizon=horizon, metric=metric),
                    )
                    for metric in metrics
                }

    population = summary["overall"].get("population", {})
    top_n = summary["overall"].get("top_n", {})
    for horizon in horizons:
        key = f"return_{horizon}d"
        summary["delta_top_n_minus_population"][key] = {}
        for metric in metrics:
            left = top_n.get(key, {}).get(metric, {})
            right = population.get(key, {}).get(metric, {})
            summary["delta_top_n_minus_population"][key][metric] = {
                "top_n": left.get("n", 0),
                "population_n": right.get("n", 0),
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

    population_rows = [item for item in observations if item.cohort == "population" and item.score_decile is not None]
    for decile in range(1, 11):
        decile_rows = [item for item in population_rows if item.score_decile == decile]
        summary["score_deciles"][str(decile)] = {}
        for horizon in horizons:
            key = f"return_{horizon}d"
            summary["score_deciles"][str(decile)][key] = {
                metric: _stats(
                    _metric_values(decile_rows, horizon=horizon, metric=metric),
                    cost=cost,
                    dated_values=_metric_dated_values(decile_rows, horizon=horizon, metric=metric),
                )
                for metric in metrics
            }
    for horizon in horizons:
        key = f"return_{horizon}d"
        summary["score_monotonicity"][key] = {}
        for metric in metrics:
            means = [
                summary["score_deciles"][str(decile)][key][metric]["mean_net"]
                for decile in range(1, 11)
                if summary["score_deciles"][str(decile)][key][metric]["mean_net"] is not None
            ]
            increasing_steps = sum(1 for left, right in zip(means, means[1:], strict=False) if right >= left)
            summary["score_monotonicity"][key][metric] = {
                "deciles_with_data": len(means),
                "increasing_steps": increasing_steps,
                "possible_steps": max(len(means) - 1, 0),
                "d10_minus_d1": (
                    round(float(means[-1]) - float(means[0]), 6)
                    if len(means) >= 2
                    else None
                ),
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


def _rank_score_deciles(records: list[dict[str, Any]]) -> None:
    if not records:
        return
    ordered = sorted(enumerate(records), key=lambda item: (float(item[1]["selector_score"]), item[0]))
    total = len(ordered)
    for rank, (_index, record) in enumerate(ordered, start=1):
        record["score_decile"] = min(10, max(1, int(((rank - 1) * 10) / total) + 1))


def _selector_observation(record: dict[str, Any], *, cohort: str) -> SelectorObservation:
    return SelectorObservation(
        cohort=cohort,
        signal_date=str(record["signal_date"]),
        symbol=str(record["symbol"]),
        regime=str(record["regime"]),
        selector_score=float(record["selector_score"]),
        technical_score=float(record["technical_score"]),
        score_decile=record.get("score_decile"),
        raw_returns=record["raw_returns"],
        benchmark_returns=record["benchmark_returns"],
        beta_asof=record.get("beta_asof"),
    )


def run_selector_edge_backtest(
    *,
    since: str,
    end: str,
    horizons: tuple[int, ...],
    cost_bps: float,
    top_n: int = 15,
    universe_name: str = DEFAULT_UNIVERSE,
    max_symbols: int = 0,
    beta_lookback: int = DEFAULT_BETA_LOOKBACK,
    regime_mode: str = DEFAULT_REGIME,
    provider: str | None = None,
    fmp_api_key: str | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    sample_every: int = DEFAULT_SAMPLE_EVERY,
    progress_every: int = DEFAULT_PROGRESS_EVERY,
    include_top_records: bool = False,
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
    benchmark_return_20d_by_date = {
        _date_text(index): _safe_float(value) for index, value in spy_features["return_20d"].items()
    }
    regime_by_date = build_regime_map(spy_features, mode=regime_mode)

    records: list[dict[str, Any]] = []
    candidates_by_date: dict[str, list[dict[str, Any]]] = {}
    symbols_scanned = 0
    symbols_with_features = 0
    started_at = time.perf_counter()
    total_symbols = len(union_symbols)
    for ordinal, symbol in enumerate(union_symbols, start=1):
        if progress_every > 0 and (ordinal == 1 or ordinal % progress_every == 0 or ordinal == total_symbols):
            elapsed = max(time.perf_counter() - started_at, 0.001)
            rate = ordinal / elapsed
            eta = max(total_symbols - ordinal, 0) / rate if rate > 0 else 0.0
            print(
                (
                    f"[selector-edge-backtest] {ordinal}/{total_symbols} symbols | "
                    f"elapsed={elapsed:.1f}s | eta={eta:.1f}s | candidates={len(records)}"
                ),
                file=sys.stderr,
                flush=True,
            )
        frame = _normalize_download_frame(prices, symbol)
        if frame.empty or "Close" not in frame.columns:
            continue
        symbols_scanned += 1
        try:
            features = add_basic_technical_features(frame).dropna(subset=["Close"]).copy()
            features = add_vector_signal_columns(features)
            features["_signal_date"] = [_date_text(index) for index in features.index]
            features["_position"] = range(len(features))
            features = add_vector_selector_columns(
                features,
                benchmark_return_20d_by_date=benchmark_return_20d_by_date,
                settings=settings,
            )
        except Exception:
            continue
        if features.empty:
            continue
        symbols_with_features += 1
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
            & features["vector_selector_eligible"].fillna(False)
        ]
        if eligible.empty:
            continue
        raw_returns = build_forward_return_map(features["Close"], horizons)
        beta_by_date = build_beta_map(features["Close"], spy_close, lookback=beta_lookback)
        for _index, row in eligible.iterrows():
            session_date = str(row.get("_signal_date") or "")[:10]
            record = {
                "signal_date": session_date,
                "symbol": symbol,
                "regime": regime_by_date.get(session_date, "unknown"),
                "selector_score": float(row.get("vector_selector_score", 0.0)),
                "technical_score": float(row.get("vector_technical_score", 0.0)),
                "distance_sma20": _safe_float(row.get("vector_distance_sma20")),
                "raw_returns": {h: raw_returns[h].get(session_date) for h in horizons},
                "benchmark_returns": {h: benchmark_returns[h].get(session_date) for h in horizons},
                "beta_asof": beta_by_date.get(session_date),
                "score_decile": None,
            }
            records.append(record)
            candidates_by_date.setdefault(session_date, []).append(record)

    _rank_score_deciles(records)
    observations = [_selector_observation(record, cohort="population") for record in records]
    top_records: list[dict[str, Any]] = []
    for session_date in sorted(candidates_by_date):
        ranked = sorted(
            candidates_by_date[session_date],
            key=lambda item: (float(item["selector_score"]), float(item["technical_score"])),
            reverse=True,
        )
        top_records.extend(ranked[: max(1, int(top_n))])
    observations.extend(_selector_observation(record, cohort="top_n") for record in top_records)

    summary = summarize_selector_observations(observations, horizons=horizons, cost_bps=cost_bps)
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "study": {
            "name": "selector_deterministic_edge_historical",
            "since": since,
            "end": end,
            "horizons": list(horizons),
            "cost_bps": cost_bps,
            "top_n": top_n,
            "beta_lookback": beta_lookback,
            "regime_mode": regime_mode,
            "benchmark_symbol": spy_symbol,
            "universe_name": universe_name,
            "max_symbols": max_symbols,
            "fetch_start": fetch_start,
            "sample_every_sessions": sample_every,
            "signal_sampling": "weekly" if int(sample_every) == 5 else f"every_{sample_every}_sessions",
            "vectorized_selector": True,
            "limitations": [
                "Replays the deterministic selector score approximately from causal vector features.",
                "Learning-prior edge, chart-pattern counts, same-session bonuses and LLM recommendations are omitted.",
                "Forward returns use close[t+N]/close[t]-1, matching signal_learning outcome convention.",
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
            "population_candidates": len(records),
            "top_n_candidates": len(top_records),
            "elapsed_seconds": round(time.perf_counter() - started_at, 2),
        },
        "summary": summary,
        "top_pick_records": top_records if include_top_records else [],
    }


def _delta_between_cohorts(summary: dict[str, Any], *, left: str, right: str, horizons: tuple[int, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for horizon in horizons:
        key = f"return_{horizon}d"
        result[key] = {}
        for metric in ("raw", "excess_vs_spy", "beta_adjusted_vs_spy"):
            left_stats = summary.get("overall", {}).get(left, {}).get(key, {}).get(metric, {})
            right_stats = summary.get("overall", {}).get(right, {}).get(key, {}).get(metric, {})
            result[key][metric] = {
                "left_n": left_stats.get("n", 0),
                "right_n": right_stats.get("n", 0),
                "mean_delta": (
                    round(float(left_stats["mean"]) - float(right_stats["mean"]), 6)
                    if left_stats.get("mean") is not None and right_stats.get("mean") is not None
                    else None
                ),
                "mean_net_delta": (
                    round(float(left_stats["mean_net"]) - float(right_stats["mean_net"]), 6)
                    if left_stats.get("mean_net") is not None and right_stats.get("mean_net") is not None
                    else None
                ),
                "sharpe_simple_delta": (
                    round(float(left_stats["sharpe_simple"]) - float(right_stats["sharpe_simple"]), 6)
                    if left_stats.get("sharpe_simple") is not None and right_stats.get("sharpe_simple") is not None
                    else None
                ),
                "max_drawdown_delta": (
                    round(float(left_stats["max_drawdown"]) - float(right_stats["max_drawdown"]), 6)
                    if left_stats.get("max_drawdown") is not None and right_stats.get("max_drawdown") is not None
                    else None
                ),
                "downside_deviation_delta": (
                    round(float(left_stats["downside_deviation"]) - float(right_stats["downside_deviation"]), 6)
                    if left_stats.get("downside_deviation") is not None
                    and right_stats.get("downside_deviation") is not None
                    else None
                ),
                "tail_loss_rate_lt_10pct_delta": (
                    round(float(left_stats["tail_loss_rate_lt_10pct"]) - float(right_stats["tail_loss_rate_lt_10pct"]), 6)
                    if left_stats.get("tail_loss_rate_lt_10pct") is not None
                    and right_stats.get("tail_loss_rate_lt_10pct") is not None
                    else None
                ),
            }
    return result


def _delta_between_cohorts_by_regime(
    summary: dict[str, Any],
    *,
    left: str,
    right: str,
    horizons: tuple[int, ...],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for regime, cohorts in summary.get("by_regime", {}).items():
        if left not in cohorts or right not in cohorts:
            continue
        result[regime] = {}
        for horizon in horizons:
            key = f"return_{horizon}d"
            result[regime][key] = {}
            for metric in ("raw", "excess_vs_spy", "beta_adjusted_vs_spy"):
                left_stats = cohorts[left][key][metric]
                right_stats = cohorts[right][key][metric]
                result[regime][key][metric] = {
                    "left_n": left_stats.get("n", 0),
                    "right_n": right_stats.get("n", 0),
                    "mean_delta": (
                        round(float(left_stats["mean"]) - float(right_stats["mean"]), 6)
                        if left_stats.get("mean") is not None and right_stats.get("mean") is not None
                        else None
                    ),
                    "mean_net_delta": (
                        round(float(left_stats["mean_net"]) - float(right_stats["mean_net"]), 6)
                        if left_stats.get("mean_net") is not None and right_stats.get("mean_net") is not None
                        else None
                    ),
                    "sharpe_simple_delta": (
                        round(float(left_stats["sharpe_simple"]) - float(right_stats["sharpe_simple"]), 6)
                        if left_stats.get("sharpe_simple") is not None and right_stats.get("sharpe_simple") is not None
                        else None
                    ),
                    "max_drawdown_delta": (
                        round(float(left_stats["max_drawdown"]) - float(right_stats["max_drawdown"]), 6)
                        if left_stats.get("max_drawdown") is not None and right_stats.get("max_drawdown") is not None
                        else None
                    ),
                    "downside_deviation_delta": (
                        round(float(left_stats["downside_deviation"]) - float(right_stats["downside_deviation"]), 6)
                        if left_stats.get("downside_deviation") is not None
                        and right_stats.get("downside_deviation") is not None
                        else None
                    ),
                    "tail_loss_rate_lt_10pct_delta": (
                        round(
                            float(left_stats["tail_loss_rate_lt_10pct"])
                            - float(right_stats["tail_loss_rate_lt_10pct"]),
                            6,
                        )
                        if left_stats.get("tail_loss_rate_lt_10pct") is not None
                        and right_stats.get("tail_loss_rate_lt_10pct") is not None
                        else None
                    ),
                }
    return result


def run_extension_gate_edge_backtest(
    *,
    since: str,
    end: str,
    horizons: tuple[int, ...],
    cost_bps: float,
    top_n: int = 15,
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
    threshold = float(settings.entry_quality_max_sma20_distance)
    selector_report = run_selector_edge_backtest(
        since=since,
        end=end,
        horizons=horizons,
        cost_bps=cost_bps,
        top_n=top_n,
        universe_name=universe_name,
        max_symbols=max_symbols,
        beta_lookback=beta_lookback,
        regime_mode=regime_mode,
        provider=provider,
        fmp_api_key=fmp_api_key,
        batch_size=batch_size,
        sample_every=sample_every,
        progress_every=progress_every,
        include_top_records=True,
        settings=settings,
    )
    top_records = selector_report["top_pick_records"]
    observations: list[SelectorObservation] = []
    cohort_counts = {"extension_pass": 0, "extension_rejected": 0, "missing_distance": 0}
    distance_summary_values: dict[str, list[float]] = {"extension_pass": [], "extension_rejected": []}
    for record in top_records:
        distance = _safe_float(record.get("distance_sma20"))
        if distance is None:
            cohort_counts["missing_distance"] += 1
            continue
        cohort = "extension_rejected" if distance > threshold else "extension_pass"
        cohort_counts[cohort] += 1
        distance_summary_values[cohort].append(distance)
        observations.append(_selector_observation(record, cohort=cohort))

    summary = summarize_selector_observations(observations, horizons=horizons, cost_bps=cost_bps)
    summary["delta_rejected_minus_pass"] = _delta_between_cohorts(
        summary,
        left="extension_rejected",
        right="extension_pass",
        horizons=horizons,
    )
    summary["delta_by_regime_rejected_minus_pass"] = _delta_between_cohorts_by_regime(
        summary,
        left="extension_rejected",
        right="extension_pass",
        horizons=horizons,
    )
    summary["distance_sma20"] = {
        cohort: {
            "n": len(values),
            "min": round(min(values), 6) if values else None,
            "median": round(statistics.median(values), 6) if values else None,
            "max": round(max(values), 6) if values else None,
        }
        for cohort, values in distance_summary_values.items()
    }
    result = dict(selector_report)
    result["study"] = {
        **selector_report["study"],
        "name": "selector_top_extension_gate_edge_historical",
        "extension_gate_threshold": threshold,
        "extension_gate_source": "settings.entry_quality_max_sma20_distance",
    }
    result["scan"] = {
        **selector_report["scan"],
        "extension_gate_cohort_counts": cohort_counts,
    }
    result["summary"] = summary
    result.pop("top_pick_records", None)
    return result


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


def build_selector_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backtest historico read-only de edge del selector determinista.")
    parser.add_argument("--since", default="2024-01-01", help="Fecha inicial de estudio YYYY-MM-DD.")
    parser.add_argument("--to", dest="end", default=date.today().isoformat(), help="Fecha final YYYY-MM-DD.")
    parser.add_argument("--horizons", default="5,10,20", help="Horizontes forward separados por coma.")
    parser.add_argument("--cost-bps", type=float, default=10.0, help="Coste round-trip en bps.")
    parser.add_argument("--top-n", type=int, default=15, help="Top N seleccionado por fecha.")
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


def print_selector_summary(report: dict[str, Any]) -> None:
    summary = report["summary"]

    def _pct(value: float | None) -> str:
        return "n/d" if value is None else f"{value * 100:.2f}%"

    print("\n=== Backtest historico selector determinista (read-only) ===")
    print(
        f"ventana={report['study']['since']}->{report['study']['end']} | "
        f"horizons={report['study']['horizons']} | top_n={report['study']['top_n']} | "
        f"cost_bps={report['study']['cost_bps']} | universo={report['study']['universe_name']}"
    )
    print(
        f"survivorship_biased={report['universe']['survivorship_biased']} | "
        f"sesiones={report['scan']['session_dates']} | sampled={report['scan']['sampled_signal_dates']} | "
        f"poblacion={report['scan']['population_candidates']} | top_n={report['scan']['top_n_candidates']}"
    )
    print("\nOverall:")
    print(f"{'cohort':<12}{'horizon':<12}{'metric':<22}{'n':>8}{'mean':>12}{'median':>12}{'hit':>10}{'mean_net':>12}")
    for cohort, per_horizon in summary["overall"].items():
        for horizon_key, blocks in per_horizon.items():
            for metric_name, stats in blocks.items():
                print(
                    f"{cohort:<12}{horizon_key:<12}{metric_name:<22}{stats['n']:>8}"
                    f"{_pct(stats['mean']):>12}"
                    f"{_pct(stats['median']):>12}"
                    f"{_pct(stats['hit_rate']):>10}"
                    f"{_pct(stats['mean_net']):>12}"
                )
    print("\nDelta top_n - population:")
    print(f"{'horizon':<12}{'metric':<22}{'top_n':>8}{'pop_n':>8}{'mean_delta':>14}{'net_delta':>14}")
    for horizon_key, blocks in summary["delta_top_n_minus_population"].items():
        for metric_name, delta in blocks.items():
            print(
                f"{horizon_key:<12}{metric_name:<22}{delta['top_n']:>8}{delta['population_n']:>8}"
                f"{_pct(delta['mean_delta']):>14}"
                f"{_pct(delta['mean_net_delta']):>14}"
            )
    print("\nMonotonia por decil de score:")
    print(f"{'horizon':<12}{'metric':<22}{'steps':>10}{'d10-d1 net':>14}")
    for horizon_key, blocks in summary["score_monotonicity"].items():
        for metric_name, stats in blocks.items():
            steps = f"{stats['increasing_steps']}/{stats['possible_steps']}"
            print(f"{horizon_key:<12}{metric_name:<22}{steps:>10}{_pct(stats['d10_minus_d1']):>14}")


def selector_main(argv: list[str] | None = None) -> int:
    parser = build_selector_parser()
    args = parser.parse_args(argv)
    report = run_selector_edge_backtest(
        since=args.since,
        end=args.end,
        horizons=_parse_horizons(args.horizons),
        cost_bps=args.cost_bps,
        top_n=args.top_n,
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
        print_selector_summary(report)
    return 0


def build_extension_gate_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backtest read-only del gate de extension sobre top picks del selector.")
    parser.add_argument("--since", default="2022-01-01", help="Fecha inicial de estudio YYYY-MM-DD.")
    parser.add_argument("--to", dest="end", default=date.today().isoformat(), help="Fecha final YYYY-MM-DD.")
    parser.add_argument("--horizons", default="5,10,20", help="Horizontes forward separados por coma.")
    parser.add_argument("--cost-bps", type=float, default=10.0, help="Coste round-trip en bps.")
    parser.add_argument("--top-n", type=int, default=15, help="Top N seleccionado por fecha.")
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


def print_extension_gate_summary(report: dict[str, Any]) -> None:
    summary = report["summary"]

    def _pct(value: float | None) -> str:
        return "n/d" if value is None else f"{value * 100:.2f}%"

    print("\n=== Backtest historico gate de extension sobre top picks (read-only) ===")
    print(
        f"ventana={report['study']['since']}->{report['study']['end']} | "
        f"horizons={report['study']['horizons']} | top_n={report['study']['top_n']} | "
        f"threshold={report['study']['extension_gate_threshold']:.2%} | "
        f"cost_bps={report['study']['cost_bps']}"
    )
    counts = report["scan"]["extension_gate_cohort_counts"]
    print(
        f"top_picks={report['scan']['top_n_candidates']} | "
        f"pasa={counts['extension_pass']} | rechazado={counts['extension_rejected']} | "
        f"missing_distance={counts['missing_distance']}"
    )
    print("\nOverall:")
    print(f"{'cohort':<20}{'horizon':<12}{'metric':<22}{'n':>8}{'mean':>12}{'median':>12}{'hit':>10}{'mean_net':>12}")
    for cohort, per_horizon in summary["overall"].items():
        for horizon_key, blocks in per_horizon.items():
            for metric_name, stats in blocks.items():
                print(
                    f"{cohort:<20}{horizon_key:<12}{metric_name:<22}{stats['n']:>8}"
                    f"{_pct(stats['mean']):>12}"
                    f"{_pct(stats['median']):>12}"
                    f"{_pct(stats['hit_rate']):>10}"
                    f"{_pct(stats['mean_net']):>12}"
                )
    print("\nDelta rechazado - pasa:")
    print(f"{'horizon':<12}{'metric':<22}{'rej_n':>8}{'pass_n':>8}{'mean_delta':>14}{'net_delta':>14}")
    for horizon_key, blocks in summary["delta_rejected_minus_pass"].items():
        for metric_name, delta in blocks.items():
            print(
                f"{horizon_key:<12}{metric_name:<22}{delta['left_n']:>8}{delta['right_n']:>8}"
                f"{_pct(delta['mean_delta']):>14}"
                f"{_pct(delta['mean_net_delta']):>14}"
            )


def extension_gate_main(argv: list[str] | None = None) -> int:
    parser = build_extension_gate_parser()
    args = parser.parse_args(argv)
    report = run_extension_gate_edge_backtest(
        since=args.since,
        end=args.end,
        horizons=_parse_horizons(args.horizons),
        cost_bps=args.cost_bps,
        top_n=args.top_n,
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
        print_extension_gate_summary(report)
    return 0


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
    "SelectorObservation",
    "StrategyObservation",
    "add_vector_selector_columns",
    "build_beta_map",
    "build_forward_return_map",
    "build_point_in_time_universe_map",
    "build_regime_map",
    "build_parser",
    "build_extension_gate_parser",
    "build_selector_parser",
    "add_vector_signal_columns",
    "extension_gate_main",
    "main",
    "selector_main",
    "run_extension_gate_edge_backtest",
    "run_pullback_breakout_backtest",
    "run_selector_edge_backtest",
    "sampled_session_dates",
    "summarize_observations",
    "summarize_selector_observations",
]
