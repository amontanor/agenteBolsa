"""Technical analysis feature generation."""

from __future__ import annotations

import pandas as pd


def add_basic_technical_features(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"Close", "High", "Low", "Volume"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Faltan columnas requeridas: {sorted(missing)}")

    result = frame.copy()
    open_price = result["Open"] if "Open" in result else result["Close"]
    previous_close = result["Close"].shift(1)
    previous_open = open_price.shift(1)
    previous_body = result["Close"].shift(1) - previous_open
    result["sma_20"] = result["Close"].rolling(20).mean()
    result["sma_50"] = result["Close"].rolling(50).mean()
    result["sma_200"] = result["Close"].rolling(200).mean()
    result["ema_12"] = result["Close"].ewm(span=12, adjust=False).mean()
    result["ema_26"] = result["Close"].ewm(span=26, adjust=False).mean()
    result["macd"] = result["ema_12"] - result["ema_26"]
    result["macd_signal"] = result["macd"].ewm(span=9, adjust=False).mean()
    result["return_5d"] = result["Close"].pct_change(5)
    result["return_20d"] = result["Close"].pct_change(20)
    result["return_60d"] = result["Close"].pct_change(60)
    result["high_20"] = result["High"].rolling(20).max()
    result["low_20"] = result["Low"].rolling(20).min()
    result["high_55"] = result["High"].rolling(55).max()
    result["low_55"] = result["Low"].rolling(55).min()
    result["prev_high_55"] = result["high_55"].shift(1)
    result["prev_low_55"] = result["low_55"].shift(1)
    result["high_252"] = result["High"].rolling(252).max()
    result["low_252"] = result["Low"].rolling(252).min()
    result["volume_mean_20"] = result["Volume"].rolling(20).mean()
    result["volume_std_20"] = result["Volume"].rolling(20).std()
    result["volume_zscore_20"] = (
        (result["Volume"] - result["volume_mean_20"]) / result["volume_std_20"]
    )
    result["true_range"] = (
        pd.concat(
            [
                (result["High"] - result["Low"]).abs(),
                (result["High"] - previous_close).abs(),
                (result["Low"] - previous_close).abs(),
            ],
            axis=1,
        )
        .max(axis=1)
    )
    result["atr_14"] = result["true_range"].rolling(14).mean()
    result["realized_vol_20"] = result["Close"].pct_change().rolling(20).std() * (252 ** 0.5)
    delta = result["Close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    result["rsi_14"] = 100 - (100 / (1 + rs))
    result["bollinger_mid_20"] = result["Close"].rolling(20).mean()
    result["bollinger_std_20"] = result["Close"].rolling(20).std()
    result["bollinger_upper_20"] = result["bollinger_mid_20"] + (2 * result["bollinger_std_20"])
    result["bollinger_lower_20"] = result["bollinger_mid_20"] - (2 * result["bollinger_std_20"])
    result["bollinger_width_20"] = (
        (result["bollinger_upper_20"] - result["bollinger_lower_20"]) / result["bollinger_mid_20"]
    )
    result["bollinger_pct_b_20"] = (
        (result["Close"] - result["bollinger_lower_20"])
        / (result["bollinger_upper_20"] - result["bollinger_lower_20"])
    )
    result["gap_pct"] = (open_price - previous_close) / previous_close
    result["trend_positive"] = result["sma_20"] > result["sma_50"]
    result["above_long_trend"] = result["Close"] > result["sma_200"]

    result["candle_body"] = result["Close"] - open_price
    result["candle_body_abs"] = result["candle_body"].abs()
    result["candle_range"] = (result["High"] - result["Low"]).abs()
    result["upper_shadow"] = result["High"] - pd.concat(
        [open_price, result["Close"]], axis=1
    ).max(axis=1)
    result["lower_shadow"] = pd.concat([open_price, result["Close"]], axis=1).min(
        axis=1
    ) - result["Low"]
    safe_range = result["candle_range"].replace(0, float("nan"))
    safe_body = result["candle_body_abs"].replace(0, float("nan"))
    result["candle_body_pct"] = result["candle_body_abs"] / safe_range
    result["close_position_in_range"] = (result["Close"] - result["Low"]) / safe_range
    result["candle_doji"] = result["candle_body_pct"] <= 0.10
    result["candle_hammer"] = (
        (result["lower_shadow"] >= 2 * safe_body)
        & (result["upper_shadow"] <= safe_body)
        & ((result["Close"] - result["Low"]) / safe_range >= 0.60)
    )
    result["candle_shooting_star"] = (
        (result["upper_shadow"] >= 2 * safe_body)
        & (result["lower_shadow"] <= safe_body)
        & ((result["High"] - result["Close"]) / safe_range >= 0.60)
    )
    result["candle_bullish_engulfing"] = (
        (previous_body < 0)
        & (result["candle_body"] > 0)
        & (open_price <= result["Close"].shift(1))
        & (result["Close"] >= previous_open)
    )
    result["candle_bearish_engulfing"] = (
        (previous_body > 0)
        & (result["candle_body"] < 0)
        & (open_price >= result["Close"].shift(1))
        & (result["Close"] <= previous_open)
    )
    result["candle_bullish_signal"] = (
        result["candle_hammer"] | result["candle_bullish_engulfing"]
    )
    result["candle_bearish_signal"] = (
        result["candle_shooting_star"] | result["candle_bearish_engulfing"]
    )
    return result
