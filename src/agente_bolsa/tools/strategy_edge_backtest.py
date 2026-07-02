"""Historical strategy edge study for pullback vs breakout (read-only)."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
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
DEFAULT_OOS_SUBPERIODS = {
    "2022": ("2022-01-01", "2022-12-31"),
    "2023": ("2023-01-01", "2023-12-31"),
    "2024": ("2024-01-01", "2024-12-31"),
    "2025-26": ("2025-01-01", "2026-12-31"),
}
DEFAULT_WALK_FORWARD_BLOCKS = (
    {
        "label": "train_2022_apply_2023",
        "train_end": "2022-12-31",
        "apply_start": "2023-01-01",
        "apply_end": "2023-12-31",
    },
    {
        "label": "train_2022_2023_apply_2024",
        "train_end": "2023-12-31",
        "apply_start": "2024-01-01",
        "apply_end": "2024-12-31",
    },
    {
        "label": "train_2022_2024_apply_2025_26",
        "train_end": "2024-12-31",
        "apply_start": "2025-01-01",
        "apply_end": "2026-12-31",
    },
)
DEFAULT_OVERLAY_VOL_TARGETS = (0.10, 0.12, 0.15)
DEFAULT_OVERLAY_SMA_WINDOWS = (150, 200, 250)
DEFAULT_OVERLAY_DD_THRESHOLDS = (0.10, 0.15, 0.20)
DEFAULT_OVERLAY_COST_BPS = (10.0, 20.0, 30.0)
DEFAULT_OVERLAY_VOL_LOOKBACK = 20


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


def build_regime_map(
    spy_features: pd.DataFrame,
    *,
    mode: str = DEFAULT_REGIME,
    sma_window: int = 200,
) -> dict[str, str]:
    if mode != DEFAULT_REGIME:
        raise ValueError(f"Regime mode no soportado: {mode}")
    window = int(sma_window)
    if window <= 0:
        raise ValueError("La ventana SMA del regimen debe ser positiva.")
    sma_column = f"sma_{window}"
    sma_values = (
        spy_features[sma_column]
        if sma_column in spy_features.columns
        else spy_features["Close"].astype(float).rolling(window).mean()
    )
    result: dict[str, str] = {}
    for idx, row in spy_features.iterrows():
        close = _safe_float(row.get("Close"))
        sma_value = _safe_float(sma_values.loc[idx])
        label = "unknown"
        if close is not None and sma_value is not None:
            label = f"bull_above_sma{window}" if close > sma_value else f"bear_below_sma{window}"
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
    regime_sma_window: int = 200,
    provider: str | None = None,
    fmp_api_key: str | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    sample_every: int = DEFAULT_SAMPLE_EVERY,
    progress_every: int = DEFAULT_PROGRESS_EVERY,
    include_top_records: bool = False,
    include_candidate_records: bool = False,
    include_universe_records: bool = False,
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
    regime_by_date = build_regime_map(spy_features, mode=regime_mode, sma_window=regime_sma_window)

    records: list[dict[str, Any]] = []
    universe_records: list[dict[str, Any]] = []
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
        raw_returns = build_forward_return_map(features["Close"], horizons)
        beta_by_date = build_beta_map(features["Close"], spy_close, lookback=beta_lookback)
        if include_universe_records:
            universe_rows = features[
                features["_signal_date"].isin(eligible_dates)
                & (features["_position"] >= 419)
            ]
            for _index, row in universe_rows.iterrows():
                session_date = str(row.get("_signal_date") or "")[:10]
                raw_by_horizon = {h: raw_returns[h].get(session_date) for h in horizons}
                if all(value is None for value in raw_by_horizon.values()):
                    continue
                universe_records.append(
                    {
                        "signal_date": session_date,
                        "symbol": symbol,
                        "regime": regime_by_date.get(session_date, "unknown"),
                        "raw_returns": raw_by_horizon,
                        "benchmark_returns": {h: benchmark_returns[h].get(session_date) for h in horizons},
                        "beta_asof": beta_by_date.get(session_date),
                    }
                )
        eligible = features[
            features["_signal_date"].isin(eligible_dates)
            & (features["_position"] >= 419)
            & features["vector_selector_eligible"].fillna(False)
        ]
        if eligible.empty:
            continue
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
    weekly_benchmark_records = [
        {
            "signal_date": session_date,
            "regime": regime_by_date.get(session_date, "unknown"),
            "benchmark_returns": {h: benchmark_returns[h].get(session_date) for h in horizons},
        }
        for session_date in sampled_dates
    ]
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
            "regime_sma_window": regime_sma_window,
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
            "universe_member_records": len(universe_records),
            "elapsed_seconds": round(time.perf_counter() - started_at, 2),
        },
        "summary": summary,
        "top_pick_records": top_records if include_top_records else [],
        "candidate_records": records if include_candidate_records else [],
        "universe_member_records": universe_records if include_universe_records else [],
        "weekly_benchmark_records": weekly_benchmark_records,
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


def summarize_weekly_portfolio_returns(weekly_returns: list[tuple[str, str, float]]) -> dict[str, Any]:
    values = [value for _date, _regime, value in weekly_returns]
    if not values:
        return {
            "weeks": 0,
            "mean": None,
            "median": None,
            "sharpe_simple": None,
            "max_drawdown": None,
            "worst_week": None,
            "negative_week_rate": None,
            "tail_week_rate_lt_5pct": None,
        }
    mean = sum(values) / len(values)
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    equity = 1.0
    for value in values:
        equity *= 1.0 + value
    return {
        "weeks": len(values),
        "mean": round(mean, 6),
        "median": round(statistics.median(values), 6),
        "cumulative_return": round(equity - 1.0, 6),
        "sharpe_simple": round(mean / std, 6) if std > 0 else None,
        "sharpe_annualized": round((mean / std) * (52**0.5), 6) if std > 0 else None,
        "max_drawdown": _max_drawdown(values),
        "worst_week": round(min(values), 6),
        "negative_week_rate": round(sum(1 for value in values if value < 0) / len(values), 4),
        "tail_week_rate_lt_5pct": round(sum(1 for value in values if value < -0.05) / len(values), 4),
    }


def drawdown_series_from_returns(period_returns: pd.Series) -> pd.Series:
    returns = pd.to_numeric(period_returns, errors="coerce").fillna(0.0)
    equity = (1.0 + returns).cumprod()
    peak = equity.cummax()
    return (equity / peak) - 1.0


def max_recovery_time(period_returns: pd.Series) -> int:
    returns = pd.to_numeric(period_returns, errors="coerce").fillna(0.0)
    equity = (1.0 + returns).cumprod()
    peak = equity.cummax()
    underwater = equity < peak
    longest = 0
    current = 0
    for value in underwater:
        if bool(value):
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return int(longest)


def risk_overlay_metrics(period_returns: pd.Series, *, periods_per_year: int = 252) -> dict[str, Any]:
    returns = pd.to_numeric(period_returns, errors="coerce").dropna()
    if returns.empty:
        return {
            "periods": 0,
            "cagr": None,
            "sharpe": None,
            "sortino": None,
            "max_drawdown": None,
            "ulcer_index": None,
            "worst_week": None,
            "worst_month": None,
            "pct_time_in_drawdown": None,
            "max_recovery_periods": None,
            "cumulative_return": None,
        }
    equity = (1.0 + returns).cumprod()
    drawdowns = drawdown_series_from_returns(returns)
    years = max(len(returns) / float(periods_per_year), 1.0 / periods_per_year)
    cumulative = float(equity.iloc[-1] - 1.0)
    cagr = (float(equity.iloc[-1]) ** (1.0 / years)) - 1.0
    mean = float(returns.mean())
    std = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    downside = returns[returns < 0]
    downside_std = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
    weekly = (1.0 + returns).resample("W-FRI").prod() - 1.0
    monthly = (1.0 + returns).resample("ME").prod() - 1.0
    ulcer = float(((drawdowns * 100.0) ** 2).mean() ** 0.5) / 100.0
    return {
        "periods": int(len(returns)),
        "cagr": round(cagr, 6),
        "sharpe": round((mean / std) * (periods_per_year**0.5), 6) if std > 0 else None,
        "sortino": round((mean / downside_std) * (periods_per_year**0.5), 6) if downside_std > 0 else None,
        "max_drawdown": round(float(drawdowns.min()), 6),
        "ulcer_index": round(ulcer, 6),
        "worst_week": round(float(weekly.min()), 6) if not weekly.empty else None,
        "worst_month": round(float(monthly.min()), 6) if not monthly.empty else None,
        "pct_time_in_drawdown": round(float((drawdowns < 0).mean()), 6),
        "max_recovery_periods": max_recovery_time(returns),
        "cumulative_return": round(cumulative, 6),
    }


def exposure_regime_on_off(regime_close: pd.Series, *, sma_window: int) -> pd.Series:
    close = pd.to_numeric(regime_close, errors="coerce").dropna()
    features = pd.DataFrame({"Close": close})
    regime = build_regime_map(features, sma_window=int(sma_window))
    values = {pd.Timestamp(day): (1.0 if _is_bull_regime(label) else 0.0) for day, label in regime.items()}
    return pd.Series(values, dtype=float).reindex(close.index).ffill().fillna(0.0)


def exposure_vol_target(market_close: pd.Series, *, target_vol: float, lookback: int = DEFAULT_OVERLAY_VOL_LOOKBACK) -> pd.Series:
    close = pd.to_numeric(market_close, errors="coerce").dropna()
    realized = close.pct_change().rolling(int(lookback)).std() * (252**0.5)
    exposure = float(target_vol) / realized
    return exposure.clip(lower=0.0, upper=1.0).fillna(1.0)


def exposure_drawdown_guard(
    market_close: pd.Series,
    *,
    threshold: float,
    reduced_exposure: float = 0.5,
) -> pd.Series:
    close = pd.to_numeric(market_close, errors="coerce").dropna()
    trailing_peak = close.cummax()
    drawdown = (close / trailing_peak) - 1.0
    exposure = pd.Series(1.0, index=close.index)
    exposure = exposure.mask(drawdown <= -abs(float(threshold)), float(reduced_exposure))
    return exposure.clip(lower=0.0, upper=1.0)


def simulate_exposure_overlay(
    market_returns: pd.Series,
    target_exposure: pd.Series,
    *,
    cost_bps: float,
    start: str,
    end: str,
) -> dict[str, Any]:
    returns = pd.to_numeric(market_returns, errors="coerce").dropna().sort_index()
    target = pd.to_numeric(target_exposure, errors="coerce").reindex(returns.index).ffill().fillna(0.0).clip(0.0, 1.0)
    actual = target.shift(1).ffill().fillna(0.0)
    turnover = actual.diff().abs().fillna(actual.abs())
    cost = float(cost_bps) / 10000.0
    net_returns = (actual * returns) - (turnover * cost)
    period = net_returns.loc[str(start) : str(end)]
    period_exposure = actual.loc[period.index]
    period_turnover = turnover.loc[period.index]
    metrics = risk_overlay_metrics(period)
    metrics["avg_exposure"] = round(float(period_exposure.mean()), 6) if not period_exposure.empty else None
    metrics["turnover_sum"] = round(float(period_turnover.sum()), 6) if not period_turnover.empty else None
    metrics["turnover_mean"] = round(float(period_turnover.mean()), 6) if not period_turnover.empty else None
    return {
        "returns": period,
        "target_exposure": target.loc[period.index],
        "actual_exposure": period_exposure,
        "turnover": period_turnover,
        "metrics": metrics,
    }


def _overlay_policy_specs(
    *,
    sma_windows: tuple[int, ...],
    vol_targets: tuple[float, ...],
    dd_thresholds: tuple[float, ...],
) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = [{"id": "buy_hold", "kind": "buy_hold"}]
    specs.extend({"id": f"regime_sma{int(window)}", "kind": "regime", "sma_window": int(window)} for window in sma_windows)
    specs.extend({"id": f"vol_target_{int(target * 100)}pct", "kind": "vol_target", "target_vol": float(target)} for target in vol_targets)
    specs.extend({"id": f"drawdown_guard_{int(threshold * 100)}pct", "kind": "drawdown_guard", "threshold": float(threshold)} for threshold in dd_thresholds)
    for window in sma_windows:
        for target in vol_targets:
            specs.append(
                {
                    "id": f"combo_sma{int(window)}_vol{int(target * 100)}pct",
                    "kind": "combo_regime_vol",
                    "sma_window": int(window),
                    "target_vol": float(target),
                }
            )
    return specs


def _overlay_target_exposure(
    spec: dict[str, Any],
    *,
    market_close: pd.Series,
    regime_close: pd.Series,
) -> pd.Series:
    kind = str(spec["kind"])
    if kind == "buy_hold":
        return pd.Series(1.0, index=market_close.dropna().index)
    if kind == "regime":
        return exposure_regime_on_off(regime_close, sma_window=int(spec["sma_window"]))
    if kind == "vol_target":
        return exposure_vol_target(market_close, target_vol=float(spec["target_vol"]))
    if kind == "drawdown_guard":
        return exposure_drawdown_guard(market_close, threshold=float(spec["threshold"]))
    if kind == "combo_regime_vol":
        regime_exposure = exposure_regime_on_off(regime_close, sma_window=int(spec["sma_window"]))
        vol_exposure = exposure_vol_target(market_close, target_vol=float(spec["target_vol"]))
        return (regime_exposure.reindex(vol_exposure.index).ffill().fillna(0.0) * vol_exposure).clip(0.0, 1.0)
    raise ValueError(f"overlay policy kind no soportado: {kind}")


def _drawdown_return_tradeoff(policy_metrics: dict[str, Any], baseline_metrics: dict[str, Any]) -> dict[str, Any]:
    policy_dd = abs(float(policy_metrics.get("max_drawdown") or 0.0))
    baseline_dd = abs(float(baseline_metrics.get("max_drawdown") or 0.0))
    policy_cagr = _safe_float(policy_metrics.get("cagr"))
    baseline_cagr = _safe_float(baseline_metrics.get("cagr"))
    dd_reduction = baseline_dd - policy_dd
    cagr_sacrifice = (baseline_cagr - policy_cagr) if baseline_cagr is not None and policy_cagr is not None else None
    ratio = None
    if cagr_sacrifice is not None and cagr_sacrifice > 0:
        ratio = dd_reduction / cagr_sacrifice
    return {
        "drawdown_reduction": round(dd_reduction, 6),
        "cagr_sacrifice": round(cagr_sacrifice, 6) if cagr_sacrifice is not None else None,
        "dd_reduction_per_cagr_sacrificed": round(ratio, 6) if ratio is not None else None,
        "return_not_sacrificed": bool(cagr_sacrifice is not None and cagr_sacrifice <= 0),
    }


def build_overlay_policy_report(
    *,
    market_name: str,
    market_close: pd.Series,
    regime_close: pd.Series,
    since: str,
    end: str,
    cost_bps_values: tuple[float, ...] = DEFAULT_OVERLAY_COST_BPS,
    sma_windows: tuple[int, ...] = DEFAULT_OVERLAY_SMA_WINDOWS,
    vol_targets: tuple[float, ...] = DEFAULT_OVERLAY_VOL_TARGETS,
    dd_thresholds: tuple[float, ...] = DEFAULT_OVERLAY_DD_THRESHOLDS,
) -> dict[str, Any]:
    close = pd.to_numeric(market_close, errors="coerce").dropna().sort_index()
    returns = close.pct_change().dropna()
    specs = _overlay_policy_specs(sma_windows=sma_windows, vol_targets=vol_targets, dd_thresholds=dd_thresholds)
    by_cost: dict[str, Any] = {}
    for cost_bps in cost_bps_values:
        policies: dict[str, Any] = {}
        for spec in specs:
            target = _overlay_target_exposure(spec, market_close=close, regime_close=regime_close)
            simulation = simulate_exposure_overlay(returns, target, cost_bps=float(cost_bps), start=since, end=end)
            policies[str(spec["id"])] = {
                "spec": spec,
                "metrics": simulation["metrics"],
            }
        baseline = policies["buy_hold"]["metrics"]
        for payload in policies.values():
            payload["tradeoff_vs_buy_hold"] = _drawdown_return_tradeoff(payload["metrics"], baseline)
        by_cost[str(cost_bps)] = {"policies": policies}
    return {
        "market": market_name,
        "since": since,
        "end": end,
        "cost_bps_values": list(cost_bps_values),
        "sma_windows": list(sma_windows),
        "vol_targets": list(vol_targets),
        "dd_thresholds": list(dd_thresholds),
        "policies_by_cost": by_cost,
        "causality": "Cada exposicion objetivo usa indicadores calculados con datos <= t y se aplica a retornos desde t+1 mediante shift(1).",
    }


def _overlay_training_score(metrics: dict[str, Any]) -> tuple[float, float, float, float]:
    sortino = _safe_float(metrics.get("sortino"))
    max_dd = abs(float(metrics.get("max_drawdown") or 0.0))
    ulcer = abs(float(metrics.get("ulcer_index") or 0.0))
    cagr = _safe_float(metrics.get("cagr"))
    return (
        float(sortino) if sortino is not None else -999.0,
        -max_dd,
        -ulcer,
        float(cagr) if cagr is not None else -999.0,
    )


def build_overlay_walk_forward_report(
    *,
    market_name: str,
    market_close: pd.Series,
    regime_close: pd.Series,
    since: str,
    end: str,
    cost_bps_values: tuple[float, ...] = DEFAULT_OVERLAY_COST_BPS,
    sma_windows: tuple[int, ...] = DEFAULT_OVERLAY_SMA_WINDOWS,
    vol_targets: tuple[float, ...] = DEFAULT_OVERLAY_VOL_TARGETS,
    dd_thresholds: tuple[float, ...] = DEFAULT_OVERLAY_DD_THRESHOLDS,
    walk_forward_blocks: tuple[dict[str, str], ...] = DEFAULT_WALK_FORWARD_BLOCKS,
) -> dict[str, Any]:
    close = pd.to_numeric(market_close, errors="coerce").dropna().sort_index()
    returns = close.pct_change().dropna()
    specs = _overlay_policy_specs(sma_windows=sma_windows, vol_targets=vol_targets, dd_thresholds=dd_thresholds)
    target_by_id = {
        str(spec["id"]): _overlay_target_exposure(spec, market_close=close, regime_close=regime_close)
        for spec in specs
    }
    by_cost: dict[str, Any] = {}
    for cost_bps in cost_bps_values:
        stitched_returns: list[pd.Series] = []
        stitched_exposure: list[pd.Series] = []
        selected_steps: list[dict[str, Any]] = []
        for block in walk_forward_blocks:
            train_start = since
            train_end = min(block["train_end"], end)
            apply_start = max(block["apply_start"], since)
            apply_end = min(block["apply_end"], end)
            if train_start > train_end or apply_start > apply_end:
                continue
            evaluated: list[tuple[tuple[float, float, float, float], str, dict[str, Any], dict[str, Any]]] = []
            for spec in specs:
                policy_id = str(spec["id"])
                train_sim = simulate_exposure_overlay(
                    returns,
                    target_by_id[policy_id],
                    cost_bps=float(cost_bps),
                    start=train_start,
                    end=train_end,
                )
                evaluated.append((_overlay_training_score(train_sim["metrics"]), policy_id, spec, train_sim))
            evaluated.sort(key=lambda item: (item[0], item[1]), reverse=True)
            _score, chosen_id, chosen_spec, train_sim = evaluated[0]
            apply_sim = simulate_exposure_overlay(
                returns,
                target_by_id[chosen_id],
                cost_bps=float(cost_bps),
                start=apply_start,
                end=apply_end,
            )
            stitched_returns.append(apply_sim["returns"])
            stitched_exposure.append(apply_sim["actual_exposure"])
            selected_steps.append(
                {
                    "block": block["label"],
                    "train_start": train_start,
                    "train_end": train_end,
                    "apply_start": apply_start,
                    "apply_end": apply_end,
                    "selected": chosen_spec,
                    "training_metrics": train_sim["metrics"],
                    "oos_metrics": apply_sim["metrics"],
                }
            )
        oos_returns = pd.concat(stitched_returns).sort_index() if stitched_returns else pd.Series(dtype=float)
        oos_exposure = pd.concat(stitched_exposure).sort_index() if stitched_exposure else pd.Series(dtype=float)
        selected_ids = [str(step["selected"]["id"]) for step in selected_steps]
        changes = sum(1 for previous, current in zip(selected_ids, selected_ids[1:], strict=False) if previous != current)
        metrics = risk_overlay_metrics(oos_returns)
        metrics["avg_exposure"] = round(float(oos_exposure.mean()), 6) if not oos_exposure.empty else None
        by_cost[str(cost_bps)] = {
            "oos_metrics": metrics,
            "selected_steps": selected_steps,
            "selection_stability": {
                "steps": len(selected_steps),
                "changes": changes,
                "change_rate": round(changes / (len(selected_steps) - 1), 6) if len(selected_steps) > 1 else None,
                "selection_counts": {policy_id: selected_ids.count(policy_id) for policy_id in sorted(set(selected_ids))},
                "selected_sequence": selected_ids,
            },
        }
    return {
        "market": market_name,
        "since": since,
        "end": end,
        "cost_bps_values": list(cost_bps_values),
        "walk_forward_blocks": list(walk_forward_blocks),
        "selection_objective": "max training Sortino, tie lower max drawdown, tie lower Ulcer index, tie higher CAGR.",
        "by_cost_bps": by_cost,
    }


def _close_frame_from_prices(prices: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    columns: dict[str, pd.Series] = {}
    for symbol in symbols:
        frame = _normalize_download_frame(prices, symbol)
        if not frame.empty and "Close" in frame.columns:
            columns[symbol] = pd.to_numeric(frame["Close"], errors="coerce")
    return pd.DataFrame(columns).sort_index()


def _equal_weight_close(close_frame: pd.DataFrame) -> pd.Series:
    returns = close_frame.pct_change(fill_method=None)
    ew_returns = returns.mean(axis=1, skipna=True).dropna()
    return (100.0 * (1.0 + ew_returns).cumprod()).rename("equal_weight_universe")


def run_drawdown_overlay_study(
    *,
    since: str,
    end: str,
    universe_name: str = DEFAULT_UNIVERSE,
    max_symbols: int = 0,
    cost_bps_values: tuple[float, ...] = DEFAULT_OVERLAY_COST_BPS,
    sma_windows: tuple[int, ...] = DEFAULT_OVERLAY_SMA_WINDOWS,
    vol_targets: tuple[float, ...] = DEFAULT_OVERLAY_VOL_TARGETS,
    dd_thresholds: tuple[float, ...] = DEFAULT_OVERLAY_DD_THRESHOLDS,
    provider: str | None = None,
    fmp_api_key: str | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    study_start = (datetime.fromisoformat(since) - timedelta(days=DEFAULT_BUFFER_CALENDAR_DAYS)).date().isoformat()
    symbols = resolve_study_universe(universe_name, settings.universe, max_symbols, settings.data_dir / "cache")
    all_symbols = sorted({"SPY", *symbols})
    prices, meta = download_prices_read_only(
        all_symbols,
        start=study_start,
        end=end,
        provider=provider or settings.market_data_provider,
        fmp_api_key=fmp_api_key if fmp_api_key is not None else settings.fmp_api_key,
        batch_size=batch_size,
    )
    close_frame = _close_frame_from_prices(prices, all_symbols)
    if "SPY" not in close_frame:
        raise ValueError("SPY no disponible para el estudio de overlay.")
    spy_close = close_frame["SPY"].dropna()
    ew_symbols = [symbol for symbol in symbols if symbol in close_frame.columns and symbol != "SPY"]
    ew_close = _equal_weight_close(close_frame[ew_symbols]) if ew_symbols else pd.Series(dtype=float)
    markets = {
        "SPY": spy_close,
        "equal_weight_universe": ew_close,
    }
    market_reports = {
        name: build_overlay_policy_report(
            market_name=name,
            market_close=series,
            regime_close=spy_close,
            since=since,
            end=end,
            cost_bps_values=cost_bps_values,
            sma_windows=sma_windows,
            vol_targets=vol_targets,
            dd_thresholds=dd_thresholds,
        )
        for name, series in markets.items()
        if not series.empty
    }
    oos_reports = {
        name: build_overlay_walk_forward_report(
            market_name=name,
            market_close=series,
            regime_close=spy_close,
            since=since,
            end=end,
            cost_bps_values=cost_bps_values,
            sma_windows=sma_windows,
            vol_targets=vol_targets,
            dd_thresholds=dd_thresholds,
        )
        for name, series in markets.items()
        if not series.empty
    }
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "study": {
            "name": "drawdown_overlay_read_only",
            "since": since,
            "end": end,
            "universe_name": universe_name,
            "max_symbols": max_symbols,
            "cost_bps_values": list(cost_bps_values),
            "sma_windows": list(sma_windows),
            "vol_targets": list(vol_targets),
            "dd_thresholds": list(dd_thresholds),
            "causality": "Senales calculadas con datos <= t; exposicion aplicada con shift(1) a retornos posteriores.",
        },
        "data": {
            "download": meta,
            "equal_weight_symbols": ew_symbols,
            "equal_weight_symbol_count": len(ew_symbols),
        },
        "markets": market_reports,
        "walk_forward_oos": oos_reports,
    }


def _weekly_equal_weight_returns_from_records(
    records: list[dict[str, Any]],
    *,
    horizon: int,
    cost: float,
    extension_threshold: float | None = None,
) -> list[tuple[str, str, float]]:
    by_date: dict[str, dict[str, Any]] = {}
    for record in records:
        if extension_threshold is not None:
            distance = _safe_float(record.get("distance_sma20"))
            if distance is None or distance > extension_threshold:
                continue
        raw_returns = record.get("raw_returns") or {}
        value = raw_returns.get(horizon)
        if value is None:
            value = raw_returns.get(str(horizon))
        value = _safe_float(value)
        if value is None:
            continue
        signal_date = str(record.get("signal_date") or "")[:10]
        if not signal_date:
            continue
        bucket = by_date.setdefault(
            signal_date,
            {"regime": str(record.get("regime") or "unknown"), "values": []},
        )
        bucket["values"].append(value - cost)
    return [
        (signal_date, str(item["regime"]), round(sum(item["values"]) / len(item["values"]), 6))
        for signal_date, item in sorted(by_date.items())
        if item["values"]
    ]


def _weekly_benchmark_returns(
    records: list[dict[str, Any]],
    *,
    horizon: int,
    cost: float,
) -> list[tuple[str, str, float]]:
    weekly: list[tuple[str, str, float]] = []
    for record in records:
        returns = record.get("benchmark_returns") or {}
        value = returns.get(horizon)
        if value is None:
            value = returns.get(str(horizon))
        value = _safe_float(value)
        if value is None:
            continue
        weekly.append((str(record.get("signal_date") or "")[:10], str(record.get("regime") or "unknown"), value - cost))
    return weekly


def _weekly_cash_returns(records: list[dict[str, Any]]) -> list[tuple[str, str, float]]:
    return [
        (str(record.get("signal_date") or "")[:10], str(record.get("regime") or "unknown"), 0.0)
        for record in records
        if record.get("benchmark_returns", {}).get(5) is not None
        or record.get("benchmark_returns", {}).get("5") is not None
    ]


def summarize_policy_weekly_returns(
    policy_returns: dict[str, list[tuple[str, str, float]]],
) -> dict[str, Any]:
    regimes = sorted({regime for rows in policy_returns.values() for _date, regime, _value in rows})
    summary: dict[str, Any] = {"overall": {}, "by_regime": {}, "regimes": regimes}
    for policy, rows in policy_returns.items():
        summary["overall"][policy] = summarize_weekly_portfolio_returns(rows)
        for regime in regimes:
            regime_rows = [row for row in rows if row[1] == regime]
            summary["by_regime"].setdefault(regime, {})[policy] = summarize_weekly_portfolio_returns(regime_rows)
    return summary


def _is_bull_regime(regime: str) -> bool:
    return str(regime or "").startswith("bull_above_sma")


def _raw_return_for_horizon(record: dict[str, Any], horizon: int) -> float | None:
    raw_returns = record.get("raw_returns") or {}
    value = raw_returns.get(horizon)
    if value is None:
        value = raw_returns.get(str(horizon))
    return _safe_float(value)


def _benchmark_return_for_horizon(record: dict[str, Any], horizon: int) -> float | None:
    returns = record.get("benchmark_returns") or {}
    value = returns.get(horizon)
    if value is None:
        value = returns.get(str(horizon))
    return _safe_float(value)


def _records_by_date(records: list[dict[str, Any]], *, horizon: int, cost: float) -> dict[str, list[dict[str, Any]]]:
    by_date: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        signal_date = str(record.get("signal_date") or "")[:10]
        value = _raw_return_for_horizon(record, horizon)
        if not signal_date or value is None:
            continue
        enriched = dict(record)
        enriched["_net_return"] = value - cost
        enriched["_gross_return"] = value
        by_date.setdefault(signal_date, []).append(enriched)
    return by_date


def _stable_random_sample(records: list[dict[str, Any]], *, signal_date: str, random_seed: int, sample_size: int) -> list[dict[str, Any]]:
    if len(records) <= sample_size:
        return list(records)
    digest = hashlib.sha256(f"{random_seed}:{signal_date}".encode()).hexdigest()
    seeded = random.Random(int(digest[:16], 16))
    return seeded.sample(sorted(records, key=lambda item: str(item.get("symbol") or "")), sample_size)


def summarize_weekly_turnover(weekly_holdings: list[tuple[str, str, set[str]]]) -> dict[str, Any]:
    ordered = sorted(weekly_holdings, key=lambda item: item[0])
    values: list[float] = []
    previous: set[str] | None = None
    for _date, _regime, holdings in ordered:
        current = set(holdings)
        if previous is None:
            previous = current
            continue
        if not previous and not current:
            turnover = 0.0
        elif not previous or not current:
            turnover = 1.0
        else:
            turnover = 1.0 - (len(previous & current) / max(len(previous), len(current)))
        values.append(round(turnover, 6))
        previous = current
    return {
        "transitions": len(values),
        "mean": round(sum(values) / len(values), 6) if values else None,
        "median": round(statistics.median(values), 6) if values else None,
        "max": round(max(values), 6) if values else None,
    }


def _holding_turnover(previous: set[str], current: set[str]) -> float:
    if not previous and not current:
        return 0.0
    if not previous or not current:
        return 1.0
    return 1.0 - (len(previous & current) / max(len(previous), len(current)))


def _record_score(record: dict[str, Any]) -> float:
    value = _safe_float(record.get("selector_score"))
    return value if value is not None else 0.0


def _top_records_by_date(records: list[dict[str, Any]], *, horizon: int) -> dict[str, list[dict[str, Any]]]:
    by_date: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        signal_date = str(record.get("signal_date") or "")[:10]
        if not signal_date or _raw_return_for_horizon(record, horizon) is None:
            continue
        by_date.setdefault(signal_date, []).append(record)
    for rows in by_date.values():
        rows.sort(key=lambda item: (_record_score(item), _safe_float(item.get("technical_score")) or 0.0), reverse=True)
    return by_date


def _universe_records_by_date_symbol(
    records: list[dict[str, Any]],
    *,
    horizon: int,
) -> dict[str, dict[str, dict[str, Any]]]:
    by_date: dict[str, dict[str, dict[str, Any]]] = {}
    for record in records:
        signal_date = str(record.get("signal_date") or "")[:10]
        symbol = str(record.get("symbol") or "").upper()
        if not signal_date or not symbol or _raw_return_for_horizon(record, horizon) is None:
            continue
        by_date.setdefault(signal_date, {})[symbol] = record
    return by_date


def _select_hysteresis_holdings(
    previous_holdings: dict[str, dict[str, Any]],
    target_rows: list[dict[str, Any]],
    *,
    top_n: int,
    min_hold_weeks: int,
    score_delta: float,
) -> dict[str, dict[str, Any]]:
    target_by_symbol = {str(row.get("symbol") or "").upper(): row for row in target_rows}
    target_symbols = list(target_by_symbol)
    retained: dict[str, dict[str, Any]] = {}
    candidate_index = 0
    for symbol, state in previous_holdings.items():
        if len(retained) >= top_n:
            break
        target_row = target_by_symbol.get(symbol)
        if target_row is not None:
            retained[symbol] = {
                **state,
                "score": _record_score(target_row),
                "last_beta": _safe_float(target_row.get("beta_asof")) or state.get("last_beta"),
            }
            continue
        while candidate_index < len(target_symbols) and target_symbols[candidate_index] in retained:
            candidate_index += 1
        replacement_score = (
            _record_score(target_by_symbol[target_symbols[candidate_index]])
            if candidate_index < len(target_symbols)
            else None
        )
        held_weeks = int(state.get("held_weeks", 0))
        previous_score = float(state.get("score", 0.0))
        should_keep = held_weeks < min_hold_weeks or replacement_score is None or replacement_score < previous_score + score_delta
        if should_keep:
            retained[symbol] = state

    selected = dict(retained)
    for row in target_rows:
        if len(selected) >= top_n:
            break
        symbol = str(row.get("symbol") or "").upper()
        if not symbol or symbol in selected:
            continue
        selected[symbol] = {
            "score": _record_score(row),
            "held_weeks": 0,
            "last_beta": _safe_float(row.get("beta_asof")),
        }
    return selected


def _summarize_policy_subperiods(
    weekly_returns: list[tuple[str, str, float]],
    *,
    periods: dict[str, tuple[str, str]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for label, (start, end) in periods.items():
        rows = [row for row in weekly_returns if start <= row[0] <= end]
        result[label] = summarize_weekly_portfolio_returns(rows)
    return result


def summarize_policy_subperiods(
    policy_returns: dict[str, list[tuple[str, str, float]]],
    *,
    periods: dict[str, tuple[str, str]],
) -> dict[str, Any]:
    return {
        policy: _summarize_policy_subperiods(rows, periods=periods)
        for policy, rows in policy_returns.items()
    }


def simulate_top_pick_turnover_policy(
    benchmark_records: list[dict[str, Any]],
    top_records: list[dict[str, Any]],
    universe_records: list[dict[str, Any]],
    *,
    horizon: int,
    cost: float,
    top_n: int,
    cadence_weeks: int,
    min_hold_weeks: int,
    hysteresis_score_delta: float,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    top_by_date = _top_records_by_date(top_records, horizon=horizon)
    universe_by_date_symbol = _universe_records_by_date_symbol(universe_records, horizon=horizon)
    ordered_benchmark = sorted(benchmark_records, key=lambda item: str(item.get("signal_date") or "")[:10])
    holdings: dict[str, dict[str, Any]] = {}
    weeks_since_rebalance: int | None = None
    returns: list[tuple[str, str, float]] = []
    beta_adjusted_returns: list[tuple[str, str, float]] = []
    turnover_rows: list[tuple[str, str, set[str]]] = []
    use_hysteresis = min_hold_weeks > 0 or hysteresis_score_delta > 0.0

    for record in ordered_benchmark:
        signal_date = str(record.get("signal_date") or "")[:10]
        if start is not None and signal_date < start:
            continue
        if end is not None and signal_date > end:
            continue
        regime = str(record.get("regime") or "unknown")
        spy_value = _benchmark_return_for_horizon(record, horizon)
        if not signal_date or spy_value is None:
            continue
        previous_symbols = set(holdings)
        is_bull = _is_bull_regime(regime)
        if not is_bull:
            holdings = {}
            weeks_since_rebalance = None
        else:
            rebalance_due = weeks_since_rebalance is None or weeks_since_rebalance >= int(cadence_weeks)
            if rebalance_due:
                target_rows = top_by_date.get(signal_date, [])[:top_n]
                if use_hysteresis:
                    holdings = _select_hysteresis_holdings(
                        holdings,
                        target_rows,
                        top_n=top_n,
                        min_hold_weeks=min_hold_weeks,
                        score_delta=hysteresis_score_delta,
                    )
                else:
                    holdings = {
                        str(row.get("symbol") or "").upper(): {
                            "score": _record_score(row),
                            "held_weeks": 0,
                            "last_beta": _safe_float(row.get("beta_asof")),
                        }
                        for row in target_rows
                        if str(row.get("symbol") or "").strip()
                    }
                weeks_since_rebalance = 0

        current_symbols = set(holdings)
        turnover = _holding_turnover(previous_symbols, current_symbols)
        date_records = universe_by_date_symbol.get(signal_date, {})
        position_returns: list[float] = []
        position_betas: list[float] = []
        for symbol, state in holdings.items():
            symbol_record = date_records.get(symbol)
            symbol_return = _raw_return_for_horizon(symbol_record or {}, horizon)
            if symbol_return is None:
                continue
            position_returns.append(symbol_return)
            beta = _safe_float((symbol_record or {}).get("beta_asof"))
            if beta is None:
                beta = _safe_float(state.get("last_beta"))
            if beta is not None:
                position_betas.append(beta)
        if position_returns:
            gross_return = sum(position_returns) / len(position_returns)
            portfolio_beta = sum(position_betas) / len(position_betas) if position_betas else 1.0
        else:
            gross_return = 0.0
            portfolio_beta = 0.0
        net_return = round(gross_return - (cost * turnover), 6)
        beta_adjusted = round(net_return - (portfolio_beta * spy_value), 6)
        returns.append((signal_date, regime, net_return))
        beta_adjusted_returns.append((signal_date, regime, beta_adjusted))
        turnover_rows.append((signal_date, regime, current_symbols))
        if is_bull and weeks_since_rebalance is not None:
            weeks_since_rebalance += 1
        for state in holdings.values():
            state["held_weeks"] = int(state.get("held_weeks", 0)) + 1

    return {
        "returns": returns,
        "beta_adjusted_returns": beta_adjusted_returns,
        "turnover_rows": turnover_rows,
        "return_summary": summarize_weekly_portfolio_returns(returns),
        "beta_adjusted_summary": summarize_weekly_portfolio_returns(beta_adjusted_returns),
        "turnover": summarize_weekly_turnover(turnover_rows),
    }


def top_pick_turnover_sensitivity(
    benchmark_records: list[dict[str, Any]],
    top_records: list[dict[str, Any]],
    universe_records: list[dict[str, Any]],
    *,
    horizon: int,
    cost: float,
    top_n: int,
    cadence_weeks: tuple[int, ...] = (1, 2, 4),
    min_hold_weeks: int = 2,
    hysteresis_score_delta: float = 0.02,
    periods: dict[str, tuple[str, str]] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for cadence in cadence_weeks:
        for use_hysteresis in (False, True):
            variant = f"top_rebalance_{cadence}w"
            if use_hysteresis:
                variant = f"{variant}_hysteresis_min{min_hold_weeks}_delta{hysteresis_score_delta:g}"
            simulation = simulate_top_pick_turnover_policy(
                benchmark_records,
                top_records,
                universe_records,
                horizon=horizon,
                cost=cost,
                top_n=top_n,
                cadence_weeks=cadence,
                min_hold_weeks=min_hold_weeks if use_hysteresis else 0,
                hysteresis_score_delta=hysteresis_score_delta if use_hysteresis else 0.0,
            )

            variant_summary: dict[str, Any] = {
                "cadence_weeks": cadence,
                "hysteresis": use_hysteresis,
                "min_hold_weeks": min_hold_weeks if use_hysteresis else 0,
                "hysteresis_score_delta": hysteresis_score_delta if use_hysteresis else 0.0,
                "cost_model": "cost_bps * weekly_turnover",
                "return_summary": simulation["return_summary"],
                "beta_adjusted_summary": simulation["beta_adjusted_summary"],
                "turnover": simulation["turnover"],
            }
            if periods is not None:
                variant_summary["subperiods"] = {
                    "return": _summarize_policy_subperiods(simulation["returns"], periods=periods),
                    "beta_adjusted": _summarize_policy_subperiods(simulation["beta_adjusted_returns"], periods=periods),
                }
            result[variant] = variant_summary
    return result


def _walk_forward_param_id(params: dict[str, Any]) -> str:
    return (
        f"sma{params['sma_window']}_cadence{params['cadence_weeks']}w_"
        f"hold{params['min_hold_weeks']}_delta{params['hysteresis_score_delta']:g}"
    )


def _build_walk_forward_grid(
    *,
    sma_windows: tuple[int, ...],
    cadence_weeks: tuple[int, ...],
    min_hold_values: tuple[int, ...],
    hysteresis_deltas: tuple[float, ...],
) -> list[dict[str, Any]]:
    grid: list[dict[str, Any]] = []
    for sma_window in sma_windows:
        for cadence in cadence_weeks:
            for min_hold in min_hold_values:
                for delta in hysteresis_deltas:
                    params = {
                        "sma_window": int(sma_window),
                        "cadence_weeks": int(cadence),
                        "min_hold_weeks": int(min_hold),
                        "hysteresis_score_delta": float(delta),
                    }
                    params["id"] = _walk_forward_param_id(params)
                    grid.append(params)
    return grid


def _walk_forward_score(simulation: dict[str, Any]) -> tuple[float, float, float]:
    alpha = simulation["beta_adjusted_summary"]
    turnover = simulation["turnover"]
    sharpe = alpha.get("sharpe_annualized")
    cumulative = alpha.get("cumulative_return")
    turnover_mean = turnover.get("mean")
    return (
        float(sharpe) if sharpe is not None else -999.0,
        float(cumulative) if cumulative is not None else -999.0,
        -(float(turnover_mean) if turnover_mean is not None else 999.0),
    )


def build_regime_policy_walk_forward_report(
    selector_reports_by_sma: dict[str, dict[str, Any]],
    *,
    since: str,
    end: str,
    cost_bps_values: tuple[float, ...],
    sma_windows: tuple[int, ...],
    cadence_weeks: tuple[int, ...] = (1, 2, 4),
    min_hold_values: tuple[int, ...] = (0, 2),
    hysteresis_deltas: tuple[float, ...] = (0.0, 0.02),
    walk_forward_blocks: tuple[dict[str, str], ...] = DEFAULT_WALK_FORWARD_BLOCKS,
    horizon: int = 5,
) -> dict[str, Any]:
    grid = _build_walk_forward_grid(
        sma_windows=sma_windows,
        cadence_weeks=cadence_weeks,
        min_hold_values=min_hold_values,
        hysteresis_deltas=hysteresis_deltas,
    )
    by_cost: dict[str, Any] = {}
    for cost_bps in cost_bps_values:
        cost = cost_bps / 10000.0
        stitched_alpha: list[tuple[str, str, float]] = []
        stitched_turnover_rows: list[tuple[str, str, set[str]]] = []
        selected_steps: list[dict[str, Any]] = []
        for block in walk_forward_blocks:
            train_start = since
            train_end = min(block["train_end"], end)
            apply_start = max(block["apply_start"], since)
            apply_end = min(block["apply_end"], end)
            if train_start > train_end or apply_start > apply_end:
                continue
            evaluated: list[tuple[tuple[float, float, float], str, dict[str, Any], dict[str, Any]]] = []
            for params in grid:
                selector_report = selector_reports_by_sma[str(params["sma_window"])]
                train_simulation = simulate_top_pick_turnover_policy(
                    selector_report["weekly_benchmark_records"],
                    selector_report["top_pick_records"],
                    selector_report["universe_member_records"],
                    horizon=horizon,
                    cost=cost,
                    top_n=int(selector_report["study"]["top_n"]),
                    cadence_weeks=int(params["cadence_weeks"]),
                    min_hold_weeks=int(params["min_hold_weeks"]),
                    hysteresis_score_delta=float(params["hysteresis_score_delta"]),
                    start=train_start,
                    end=train_end,
                )
                evaluated.append((_walk_forward_score(train_simulation), str(params["id"]), params, train_simulation))
            evaluated.sort(key=lambda item: (item[0], item[1]), reverse=True)
            _score, _param_id, chosen_params, train_simulation = evaluated[0]
            apply_selector_report = selector_reports_by_sma[str(chosen_params["sma_window"])]
            apply_simulation = simulate_top_pick_turnover_policy(
                apply_selector_report["weekly_benchmark_records"],
                apply_selector_report["top_pick_records"],
                apply_selector_report["universe_member_records"],
                horizon=horizon,
                cost=cost,
                top_n=int(apply_selector_report["study"]["top_n"]),
                cadence_weeks=int(chosen_params["cadence_weeks"]),
                min_hold_weeks=int(chosen_params["min_hold_weeks"]),
                hysteresis_score_delta=float(chosen_params["hysteresis_score_delta"]),
                start=apply_start,
                end=apply_end,
            )
            stitched_alpha.extend(apply_simulation["beta_adjusted_returns"])
            stitched_turnover_rows.extend(apply_simulation["turnover_rows"])
            selected_steps.append(
                {
                    "block": block["label"],
                    "train_start": train_start,
                    "train_end": train_end,
                    "apply_start": apply_start,
                    "apply_end": apply_end,
                    "selected": dict(chosen_params),
                    "training_beta_adjusted": train_simulation["beta_adjusted_summary"],
                    "training_turnover": train_simulation["turnover"],
                    "oos_beta_adjusted": apply_simulation["beta_adjusted_summary"],
                    "oos_turnover": apply_simulation["turnover"],
                }
            )

        selected_ids = [str(step["selected"]["id"]) for step in selected_steps]
        changes = sum(1 for previous, current in zip(selected_ids, selected_ids[1:], strict=False) if previous != current)
        selection_counts = {param_id: selected_ids.count(param_id) for param_id in sorted(set(selected_ids))}
        by_cost[str(cost_bps)] = {
            "beta_adjusted_oos": summarize_weekly_portfolio_returns(stitched_alpha),
            "turnover": summarize_weekly_turnover(stitched_turnover_rows),
            "selected_steps": selected_steps,
            "selection_stability": {
                "steps": len(selected_steps),
                "changes": changes,
                "change_rate": round(changes / (len(selected_steps) - 1), 6) if len(selected_steps) > 1 else None,
                "selection_counts": selection_counts,
                "selected_sequence": selected_ids,
            },
        }

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "study": {
            "name": "regime_policy_walk_forward_oos",
            "since": since,
            "end": end,
            "horizon_days": horizon,
            "cost_bps_values": list(cost_bps_values),
            "sma_windows": list(sma_windows),
            "cadence_weeks": list(cadence_weeks),
            "min_hold_values": list(min_hold_values),
            "hysteresis_deltas": list(hysteresis_deltas),
            "walk_forward_blocks": list(walk_forward_blocks),
            "selection_objective": "max training beta-adjusted Sharpe, tie cumulative alpha, tie lower turnover, deterministic id",
            "cost_model": "cost_bps * weekly_turnover",
            "interpretation": "Walk-forward expansivo read-only: selecciona parametros solo con datos de entrenamiento y aplica al siguiente bloque.",
        },
        "grid": grid,
        "by_cost_bps": by_cost,
        "scan_by_sma_window": {
            sma_window: selector_reports_by_sma[sma_window]["scan"]
            for sma_window in sorted(selector_reports_by_sma)
        },
    }


def regime_policy_weekly_details(
    benchmark_records: list[dict[str, Any]],
    top_records: list[dict[str, Any]],
    *,
    horizon: int,
    cost: float,
    universe_records: list[dict[str, Any]] | None = None,
    random_seed: int = 17,
    random_n: int = 15,
) -> dict[str, Any]:
    top_by_date = _records_by_date(top_records, horizon=horizon, cost=cost)
    universe_by_date = _records_by_date(universe_records or [], horizon=horizon, cost=cost)

    policy_names = [
        "cash",
        "spy_buy_hold",
        "spy_bull_cash_bear",
        "top_bull_cash_bear",
        "top_bull_cash_bear_beta_adjusted",
        "universe_equal_weight_bull_cash_bear",
        "random15_bull_cash_bear",
    ]
    policy_returns: dict[str, list[tuple[str, str, float]]] = {name: [] for name in policy_names}
    weekly_holdings: dict[str, list[tuple[str, str, set[str]]]] = {
        "cash": [],
        "spy_buy_hold": [],
        "spy_bull_cash_bear": [],
        "top_bull_cash_bear": [],
        "universe_equal_weight_bull_cash_bear": [],
        "random15_bull_cash_bear": [],
    }
    weekly_details: dict[str, list[dict[str, Any]]] = {
        "top_bull_cash_bear": [],
        "universe_equal_weight_bull_cash_bear": [],
        "random15_bull_cash_bear": [],
    }

    for record in benchmark_records:
        signal_date = str(record.get("signal_date") or "")[:10]
        regime = str(record.get("regime") or "unknown")
        spy_value = _benchmark_return_for_horizon(record, horizon)
        if not signal_date or spy_value is None:
            continue
        is_bull = _is_bull_regime(regime)

        policy_returns["cash"].append((signal_date, regime, 0.0))
        policy_returns["spy_buy_hold"].append((signal_date, regime, round(spy_value - cost, 6)))
        policy_returns["spy_bull_cash_bear"].append((signal_date, regime, round(spy_value - cost, 6) if is_bull else 0.0))
        weekly_holdings["cash"].append((signal_date, regime, set()))
        weekly_holdings["spy_buy_hold"].append((signal_date, regime, {"SPY"}))
        weekly_holdings["spy_bull_cash_bear"].append((signal_date, regime, {"SPY"} if is_bull else set()))

        top_rows = top_by_date.get(signal_date, [])
        top_symbols = {str(item.get("symbol") or "") for item in top_rows if str(item.get("symbol") or "")}
        if is_bull and top_rows:
            top_return = round(sum(float(item["_net_return"]) for item in top_rows) / len(top_rows), 6)
            betas = [_safe_float(item.get("beta_asof")) for item in top_rows]
            clean_betas = [beta for beta in betas if beta is not None]
            portfolio_beta = sum(clean_betas) / len(clean_betas) if clean_betas else 1.0
            beta_adjusted = round(top_return - (portfolio_beta * spy_value), 6)
        else:
            top_return = 0.0
            portfolio_beta = None
            beta_adjusted = 0.0
        policy_returns["top_bull_cash_bear"].append((signal_date, regime, top_return))
        policy_returns["top_bull_cash_bear_beta_adjusted"].append((signal_date, regime, beta_adjusted))
        weekly_holdings["top_bull_cash_bear"].append((signal_date, regime, top_symbols if is_bull else set()))
        weekly_details["top_bull_cash_bear"].append(
            {
                "signal_date": signal_date,
                "regime": regime,
                "positions": len(top_rows) if is_bull else 0,
                "portfolio_beta": round(portfolio_beta, 6) if portfolio_beta is not None else None,
                "spy_return": round(spy_value, 6),
                "return": top_return,
                "beta_adjusted_return": beta_adjusted,
            }
        )

        universe_rows = universe_by_date.get(signal_date, [])
        if is_bull and universe_rows:
            universe_return = round(sum(float(item["_net_return"]) for item in universe_rows) / len(universe_rows), 6)
            universe_symbols = {str(item.get("symbol") or "") for item in universe_rows if str(item.get("symbol") or "")}
        else:
            universe_return = 0.0
            universe_symbols = set()
        policy_returns["universe_equal_weight_bull_cash_bear"].append((signal_date, regime, universe_return))
        weekly_holdings["universe_equal_weight_bull_cash_bear"].append((signal_date, regime, universe_symbols))
        weekly_details["universe_equal_weight_bull_cash_bear"].append(
            {
                "signal_date": signal_date,
                "regime": regime,
                "positions": len(universe_symbols),
                "return": universe_return,
            }
        )

        random_rows = _stable_random_sample(
            universe_rows,
            signal_date=signal_date,
            random_seed=random_seed,
            sample_size=max(1, int(random_n)),
        )
        if is_bull and random_rows:
            random_return = round(sum(float(item["_net_return"]) for item in random_rows) / len(random_rows), 6)
            random_symbols = {str(item.get("symbol") or "") for item in random_rows if str(item.get("symbol") or "")}
        else:
            random_return = 0.0
            random_symbols = set()
        policy_returns["random15_bull_cash_bear"].append((signal_date, regime, random_return))
        weekly_holdings["random15_bull_cash_bear"].append((signal_date, regime, random_symbols))
        weekly_details["random15_bull_cash_bear"].append(
            {
                "signal_date": signal_date,
                "regime": regime,
                "positions": len(random_symbols),
                "return": random_return,
            }
        )

    return {
        "policy_returns": policy_returns,
        "turnover": {policy: summarize_weekly_turnover(rows) for policy, rows in weekly_holdings.items()},
        "weekly_details": weekly_details,
    }


def regime_policy_weekly_returns(
    benchmark_records: list[dict[str, Any]],
    top_records: list[dict[str, Any]],
    *,
    horizon: int,
    cost: float,
    universe_records: list[dict[str, Any]] | None = None,
    random_seed: int = 17,
    random_n: int = 15,
) -> dict[str, list[tuple[str, str, float]]]:
    details = regime_policy_weekly_details(
        benchmark_records,
        top_records,
        horizon=horizon,
        cost=cost,
        universe_records=universe_records,
        random_seed=random_seed,
        random_n=random_n,
    )
    return details["policy_returns"]


def run_weekly_policy_decision_study(
    *,
    since: str,
    end: str,
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
    cost = cost_bps / 10000.0
    horizon = 5
    extension_threshold = float(settings.entry_quality_max_sma20_distance)
    selector_report = run_selector_edge_backtest(
        since=since,
        end=end,
        horizons=(horizon,),
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
        include_candidate_records=True,
        settings=settings,
    )
    benchmark_records = selector_report["weekly_benchmark_records"]
    top_records = selector_report["top_pick_records"]
    candidate_records = selector_report["candidate_records"]
    policy_returns = {
        "P0_cash": _weekly_cash_returns(benchmark_records),
        "P1_spy": _weekly_benchmark_returns(benchmark_records, horizon=horizon, cost=cost),
        "P2_top_pass_extension_gate": _weekly_equal_weight_returns_from_records(
            top_records,
            horizon=horizon,
            cost=cost,
            extension_threshold=extension_threshold,
        ),
        "P3_top_no_extension_gate": _weekly_equal_weight_returns_from_records(
            top_records,
            horizon=horizon,
            cost=cost,
        ),
        "P4_all_eligible_equal_weight": _weekly_equal_weight_returns_from_records(
            candidate_records,
            horizon=horizon,
            cost=cost,
        ),
    }
    summary = summarize_policy_weekly_returns(policy_returns)
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "study": {
            "name": "weekly_policy_decision_distribution",
            "since": since,
            "end": end,
            "horizon_days": horizon,
            "cost_bps": cost_bps,
            "top_n": top_n,
            "regime_mode": regime_mode,
            "current_regime_assumption": "bull_above_sma200",
            "extension_gate_threshold": extension_threshold,
            "sample_every_sessions": sample_every,
            "signal_sampling": "weekly" if int(sample_every) == 5 else f"every_{sample_every}_sessions",
            "interpretation": "Distribucion historica condicional, no prediccion.",
        },
        "universe": selector_report["universe"],
        "scan": {
            **selector_report["scan"],
            "policy_weeks": {policy: len(rows) for policy, rows in policy_returns.items()},
        },
        "summary": summary,
    }


def run_regime_policy_study(
    *,
    since: str,
    end: str,
    cost_bps: float,
    top_n: int = 15,
    universe_name: str = DEFAULT_UNIVERSE,
    max_symbols: int = 0,
    beta_lookback: int = DEFAULT_BETA_LOOKBACK,
    regime_mode: str = DEFAULT_REGIME,
    regime_sma_window: int = 200,
    random_seed: int = 17,
    random_n: int = 15,
    cadence_weeks: tuple[int, ...] = (1, 2, 4),
    min_hold_weeks: int = 2,
    hysteresis_score_delta: float = 0.02,
    provider: str | None = None,
    fmp_api_key: str | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    sample_every: int = DEFAULT_SAMPLE_EVERY,
    progress_every: int = DEFAULT_PROGRESS_EVERY,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    horizon = 5
    selector_report = run_selector_edge_backtest(
        since=since,
        end=end,
        horizons=(horizon,),
        cost_bps=cost_bps,
        top_n=top_n,
        universe_name=universe_name,
        max_symbols=max_symbols,
        beta_lookback=beta_lookback,
        regime_mode=regime_mode,
        regime_sma_window=regime_sma_window,
        provider=provider,
        fmp_api_key=fmp_api_key,
        batch_size=batch_size,
        sample_every=sample_every,
        progress_every=progress_every,
        include_top_records=True,
        include_universe_records=True,
        settings=settings,
    )
    return build_regime_policy_report_from_selector(
        selector_report,
        cost_bps=cost_bps,
        horizon=horizon,
        random_seed=random_seed,
        random_n=random_n,
        cadence_weeks=cadence_weeks,
        min_hold_weeks=min_hold_weeks,
        hysteresis_score_delta=hysteresis_score_delta,
    )


def build_regime_policy_report_from_selector(
    selector_report: dict[str, Any],
    *,
    cost_bps: float,
    horizon: int = 5,
    random_seed: int = 17,
    random_n: int = 15,
    cadence_weeks: tuple[int, ...] = (1, 2, 4),
    min_hold_weeks: int = 2,
    hysteresis_score_delta: float = 0.02,
    subperiods: dict[str, tuple[str, str]] | None = None,
) -> dict[str, Any]:
    cost = cost_bps / 10000.0
    periods = subperiods or DEFAULT_OOS_SUBPERIODS
    benchmark_records = selector_report["weekly_benchmark_records"]
    top_records = selector_report["top_pick_records"]
    universe_records = selector_report.get("universe_member_records", [])
    details = regime_policy_weekly_details(
        benchmark_records,
        top_records,
        horizon=horizon,
        cost=cost,
        universe_records=universe_records,
        random_seed=random_seed,
        random_n=random_n,
    )
    policy_returns = details["policy_returns"]
    summary = summarize_policy_weekly_returns(policy_returns)
    subperiod_summary = summarize_policy_subperiods(policy_returns, periods=periods)
    turnover_sensitivity = top_pick_turnover_sensitivity(
        benchmark_records,
        top_records,
        universe_records,
        horizon=horizon,
        cost=cost,
        top_n=int(selector_report["study"]["top_n"]),
        cadence_weeks=cadence_weeks,
        min_hold_weeks=min_hold_weeks,
        hysteresis_score_delta=hysteresis_score_delta,
        periods=periods,
    )
    regime_sma_window = int(selector_report["study"].get("regime_sma_window", 200))
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "study": {
            "name": "regime_governed_policy_historical",
            "since": selector_report["study"]["since"],
            "end": selector_report["study"]["end"],
            "horizon_days": horizon,
            "cost_bps": cost_bps,
            "top_n": selector_report["study"]["top_n"],
            "regime_rule": (
                f"SPY close > SMA{regime_sma_window} => bull/participar; "
                f"SPY close <= SMA{regime_sma_window} => bear/caja"
            ),
            "regime_mode": selector_report["study"]["regime_mode"],
            "regime_sma_window": regime_sma_window,
            "regime_label_causality": "SMA calculada con rolling historico hasta t incluido; no usa datos posteriores a la fecha de senal.",
            "random_seed": random_seed,
            "random_n": random_n,
            "cadence_weeks": list(cadence_weeks),
            "min_hold_weeks": min_hold_weeks,
            "hysteresis_score_delta": hysteresis_score_delta,
            "subperiods": periods,
            "sample_every_sessions": selector_report["study"]["sample_every_sessions"],
            "signal_sampling": selector_report["study"]["signal_sampling"],
            "interpretation": (
                "Politicas semanales read-only con coste aplicado solo cuando hay posicion. "
                "La serie beta-ajustada de top picks es retorno neto de cartera menos beta media por SPY. "
                "La sensibilidad de turnover aplica coste_bps por turnover semanal estimado."
            ),
        },
        "universe": selector_report["universe"],
        "scan": {
            **selector_report["scan"],
            "policy_weeks": {policy: len(rows) for policy, rows in policy_returns.items()},
        },
        "summary": summary,
        "subperiod_summary": subperiod_summary,
        "turnover": details["turnover"],
        "turnover_sensitivity": turnover_sensitivity,
        "weekly_details": details["weekly_details"],
        "policy_returns": policy_returns,
    }


def run_regime_policy_robustness_study(
    *,
    since: str,
    end: str,
    cost_bps_values: tuple[float, ...],
    sma_windows: tuple[int, ...],
    top_n: int = 15,
    universe_name: str = DEFAULT_UNIVERSE,
    max_symbols: int = 0,
    beta_lookback: int = DEFAULT_BETA_LOOKBACK,
    regime_mode: str = DEFAULT_REGIME,
    random_seed: int = 17,
    random_n: int = 15,
    cadence_weeks: tuple[int, ...] = (1, 2, 4),
    min_hold_weeks: int = 2,
    hysteresis_score_delta: float = 0.02,
    provider: str | None = None,
    fmp_api_key: str | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    sample_every: int = DEFAULT_SAMPLE_EVERY,
    progress_every: int = DEFAULT_PROGRESS_EVERY,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    horizon = 5
    reports_by_window: dict[str, Any] = {}
    scan_by_window: dict[str, Any] = {}
    for sma_window in sma_windows:
        selector_report = run_selector_edge_backtest(
            since=since,
            end=end,
            horizons=(horizon,),
            cost_bps=cost_bps_values[0] if cost_bps_values else 10.0,
            top_n=top_n,
            universe_name=universe_name,
            max_symbols=max_symbols,
            beta_lookback=beta_lookback,
            regime_mode=regime_mode,
            regime_sma_window=int(sma_window),
            provider=provider,
            fmp_api_key=fmp_api_key,
            batch_size=batch_size,
            sample_every=sample_every,
            progress_every=progress_every,
            include_top_records=True,
            include_universe_records=True,
            settings=settings,
        )
        scan_by_window[str(sma_window)] = selector_report["scan"]
        reports_by_window[str(sma_window)] = {
            str(cost_bps): build_regime_policy_report_from_selector(
                selector_report,
                cost_bps=cost_bps,
                horizon=horizon,
                random_seed=random_seed,
                random_n=random_n,
                cadence_weeks=cadence_weeks,
                min_hold_weeks=min_hold_weeks,
                hysteresis_score_delta=hysteresis_score_delta,
            )
            for cost_bps in cost_bps_values
        }
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "study": {
            "name": "regime_governed_policy_robustness_historical",
            "since": since,
            "end": end,
            "horizon_days": horizon,
            "top_n": top_n,
            "sma_windows": list(sma_windows),
            "cost_bps_values": list(cost_bps_values),
            "regime_mode": regime_mode,
            "random_seed": random_seed,
            "random_n": random_n,
            "cadence_weeks": list(cadence_weeks),
            "min_hold_weeks": min_hold_weeks,
            "hysteresis_score_delta": hysteresis_score_delta,
            "subperiods": DEFAULT_OOS_SUBPERIODS,
            "sample_every_sessions": sample_every,
            "signal_sampling": "weekly" if int(sample_every) == 5 else f"every_{sample_every}_sessions",
            "regime_label_causality": "Cada etiqueta usa Close[t] y SMA[t] calculada con datos <= t.",
            "interpretation": "Estudio historico read-only; no promueve cambios ni modifica estado.",
        },
        "scan_by_sma_window": scan_by_window,
        "reports_by_sma_window": reports_by_window,
    }


def run_regime_policy_walk_forward_study(
    *,
    since: str,
    end: str,
    cost_bps_values: tuple[float, ...],
    sma_windows: tuple[int, ...],
    top_n: int = 15,
    universe_name: str = DEFAULT_UNIVERSE,
    max_symbols: int = 0,
    beta_lookback: int = DEFAULT_BETA_LOOKBACK,
    regime_mode: str = DEFAULT_REGIME,
    cadence_weeks: tuple[int, ...] = (1, 2, 4),
    min_hold_values: tuple[int, ...] = (0, 2),
    hysteresis_deltas: tuple[float, ...] = (0.0, 0.02),
    provider: str | None = None,
    fmp_api_key: str | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    sample_every: int = DEFAULT_SAMPLE_EVERY,
    progress_every: int = DEFAULT_PROGRESS_EVERY,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    horizon = 5
    selector_reports_by_sma: dict[str, dict[str, Any]] = {}
    for sma_window in sma_windows:
        selector_reports_by_sma[str(sma_window)] = run_selector_edge_backtest(
            since=since,
            end=end,
            horizons=(horizon,),
            cost_bps=cost_bps_values[0] if cost_bps_values else 10.0,
            top_n=top_n,
            universe_name=universe_name,
            max_symbols=max_symbols,
            beta_lookback=beta_lookback,
            regime_mode=regime_mode,
            regime_sma_window=int(sma_window),
            provider=provider,
            fmp_api_key=fmp_api_key,
            batch_size=batch_size,
            sample_every=sample_every,
            progress_every=progress_every,
            include_top_records=True,
            include_universe_records=True,
            settings=settings,
        )
    return build_regime_policy_walk_forward_report(
        selector_reports_by_sma,
        since=since,
        end=end,
        cost_bps_values=cost_bps_values,
        sma_windows=sma_windows,
        cadence_weeks=cadence_weeks,
        min_hold_values=min_hold_values,
        hysteresis_deltas=hysteresis_deltas,
        horizon=horizon,
    )


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


def build_weekly_policy_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Estudio read-only de opciones de politica a 5 sesiones.")
    parser.add_argument("--since", default="2022-01-01", help="Fecha inicial de estudio YYYY-MM-DD.")
    parser.add_argument("--to", dest="end", default=date.today().isoformat(), help="Fecha final YYYY-MM-DD.")
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
        help="Evalua carteras cada N sesiones. Default: 5.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=DEFAULT_PROGRESS_EVERY,
        help="Imprime progreso cada N simbolos en stderr. 0 desactiva.",
    )
    parser.add_argument("--json", action="store_true", help="Imprime JSON completo.")
    return parser


def print_weekly_policy_summary(report: dict[str, Any]) -> None:
    def _pct(value: float | None) -> str:
        return "n/d" if value is None else f"{value * 100:.2f}%"

    print("\n=== Estudio de decision semanal por politica (read-only) ===")
    print(
        f"ventana={report['study']['since']}->{report['study']['end']} | "
        f"horizon={report['study']['horizon_days']}d | top_n={report['study']['top_n']} | "
        f"cost_bps={report['study']['cost_bps']}"
    )
    for regime in ("bull_above_sma200", "bear_below_sma200"):
        if regime not in report["summary"]["by_regime"]:
            continue
        print(f"\nRegimen: {regime}")
        print(f"{'policy':<34}{'weeks':>8}{'mean':>12}{'median':>12}{'sharpe':>10}{'max_dd':>12}{'worst':>12}{'neg':>10}{'tail<-5':>10}")
        for policy, stats in report["summary"]["by_regime"][regime].items():
            sharpe = "n/d" if stats["sharpe_simple"] is None else f"{stats['sharpe_simple']:.3f}"
            print(
                f"{policy:<34}{stats['weeks']:>8}"
                f"{_pct(stats['mean']):>12}{_pct(stats['median']):>12}{sharpe:>10}"
                f"{_pct(stats['max_drawdown']):>12}{_pct(stats['worst_week']):>12}"
                f"{_pct(stats['negative_week_rate']):>10}{_pct(stats['tail_week_rate_lt_5pct']):>10}"
            )


def weekly_policy_main(argv: list[str] | None = None) -> int:
    parser = build_weekly_policy_parser()
    args = parser.parse_args(argv)
    report = run_weekly_policy_decision_study(
        since=args.since,
        end=args.end,
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
        print_weekly_policy_summary(report)
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
    "build_weekly_policy_parser",
    "add_vector_signal_columns",
    "extension_gate_main",
    "main",
    "selector_main",
    "run_extension_gate_edge_backtest",
    "run_pullback_breakout_backtest",
    "run_regime_policy_robustness_study",
    "run_regime_policy_study",
    "run_regime_policy_walk_forward_study",
    "run_selector_edge_backtest",
    "run_weekly_policy_decision_study",
    "sampled_session_dates",
    "regime_policy_weekly_details",
    "regime_policy_weekly_returns",
    "summarize_policy_subperiods",
    "summarize_observations",
    "summarize_policy_weekly_returns",
    "summarize_selector_observations",
    "summarize_weekly_portfolio_returns",
    "build_regime_policy_walk_forward_report",
    "build_overlay_policy_report",
    "build_overlay_walk_forward_report",
    "drawdown_series_from_returns",
    "exposure_drawdown_guard",
    "exposure_regime_on_off",
    "exposure_vol_target",
    "max_recovery_time",
    "risk_overlay_metrics",
    "run_drawdown_overlay_study",
    "simulate_top_pick_turnover_policy",
    "simulate_exposure_overlay",
    "top_pick_turnover_sensitivity",
    "weekly_policy_main",
]
