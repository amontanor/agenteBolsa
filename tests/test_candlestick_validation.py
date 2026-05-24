import pandas as pd

from agente_bolsa.tools.technical_analysis import add_basic_technical_features
from agente_bolsa.tools.technical_state_validator import validate_symbol_technical_state


def _price_frame() -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=230, freq="B")
    close = pd.Series(range(100, 330), index=dates, dtype=float)
    frame = pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "Volume": 1_000_000,
        },
        index=dates,
    )
    frame.iloc[-1, frame.columns.get_loc("Open")] = 320
    frame.iloc[-1, frame.columns.get_loc("High")] = 322
    frame.iloc[-1, frame.columns.get_loc("Low")] = 300
    frame.iloc[-1, frame.columns.get_loc("Close")] = 321
    return frame


def test_hammer_candle_supports_long_candidate():
    features = add_basic_technical_features(_price_frame())
    candidate = validate_symbol_technical_state("TEST", features)

    assert "hammer" in candidate["technical_state"]["candle_patterns"]
    assert candidate["technical_state"]["bullish_candle_signal"]
    assert "candlestick_patterns" in candidate["analysis_plan"]
    assert any("vela apoya sesgo alcista" in reason for reason in candidate["reasons"])


def _event_gap_frame(volume: float = 6_000_000, close_near_high: bool = True) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=230, freq="B")
    close = pd.Series([100 + (idx * 0.02) for idx in range(230)], index=dates, dtype=float)
    frame = pd.DataFrame(
        {
            "Open": close - 0.2,
            "High": close + 0.8,
            "Low": close - 0.8,
            "Close": close,
            "Volume": 1_000_000,
        },
        index=dates,
    )
    previous_close = float(frame.iloc[-2]["Close"])
    event_open = previous_close * 1.10
    event_close = previous_close * (1.18 if close_near_high else 1.17)
    event_high = previous_close * (1.19 if close_near_high else 1.24)
    event_low = previous_close * 1.08
    frame.iloc[-1, frame.columns.get_loc("Open")] = event_open
    frame.iloc[-1, frame.columns.get_loc("High")] = event_high
    frame.iloc[-1, frame.columns.get_loc("Low")] = event_low
    frame.iloc[-1, frame.columns.get_loc("Close")] = event_close
    frame.iloc[-1, frame.columns.get_loc("Volume")] = volume
    return frame


def test_event_momentum_gap_adds_long_signal_and_explanation():
    features = add_basic_technical_features(_event_gap_frame())
    candidate = validate_symbol_technical_state("TEST", features)

    assert candidate["direction"] == "long"
    assert candidate["technical_state"]["event_momentum_long"] is True
    assert "event_momentum_continuation" in candidate["analysis_plan"]
    assert any("repricing alcista" in reason for reason in candidate["reasons"])


def test_event_momentum_requires_volume_and_strong_close():
    low_volume = validate_symbol_technical_state(
        "TEST",
        add_basic_technical_features(_event_gap_frame(volume=1_000_000)),
    )
    weak_close = validate_symbol_technical_state(
        "TEST",
        add_basic_technical_features(_event_gap_frame(close_near_high=False)),
    )

    assert low_volume["technical_state"]["event_momentum_long"] is False
    assert weak_close["technical_state"]["event_momentum_long"] is False


def _momentum_shakeout_frame() -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=230, freq="B")
    close = pd.Series([90 + (idx * 0.10) for idx in range(230)], index=dates, dtype=float)
    frame = pd.DataFrame(
        {
            "Open": close - 0.2,
            "High": close + 0.8,
            "Low": close - 0.8,
            "Close": close,
            "Volume": 1_000_000,
        },
        index=dates,
    )
    for offset, multiplier in zip(range(6, 1, -1), [1.00, 1.03, 1.06, 1.10, 1.14], strict=True):
        idx = -offset
        base = float(frame.iloc[idx]["Close"]) * multiplier
        frame.iloc[idx, frame.columns.get_loc("Open")] = base - 0.4
        frame.iloc[idx, frame.columns.get_loc("High")] = base + 0.9
        frame.iloc[idx, frame.columns.get_loc("Low")] = base - 1.0
        frame.iloc[idx, frame.columns.get_loc("Close")] = base
        frame.iloc[idx, frame.columns.get_loc("Volume")] = 1_800_000
    previous_close = float(frame.iloc[-2]["Close"])
    frame.iloc[-1, frame.columns.get_loc("Open")] = previous_close * 0.96
    frame.iloc[-1, frame.columns.get_loc("High")] = previous_close * 0.995
    frame.iloc[-1, frame.columns.get_loc("Low")] = previous_close * 0.94
    frame.iloc[-1, frame.columns.get_loc("Close")] = previous_close * 0.99
    frame.iloc[-1, frame.columns.get_loc("Volume")] = 4_000_000
    return frame


def test_momentum_shakeout_hold_adds_long_signal():
    candidate = validate_symbol_technical_state(
        "TEST",
        add_basic_technical_features(_momentum_shakeout_frame()),
    )

    assert candidate["technical_state"]["momentum_shakeout_hold_long"] is True
    assert "momentum_shakeout_hold" in candidate["analysis_plan"]
    assert any("shakeout alcista" in reason for reason in candidate["reasons"])


def _breakout_follow_through_frame(fail_close: bool = False) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=230, freq="B")
    close = pd.Series([100 + (idx * 0.10) for idx in range(230)], index=dates, dtype=float)
    frame = pd.DataFrame(
        {
            "Open": close - 0.2,
            "High": close + 0.8,
            "Low": close - 0.8,
            "Close": close,
            "Volume": 1_000_000,
        },
        index=dates,
    )
    prev_high = float(frame.iloc[:-1]["High"].rolling(55).max().iloc[-1])
    frame.iloc[-1, frame.columns.get_loc("Open")] = prev_high * 0.998
    frame.iloc[-1, frame.columns.get_loc("High")] = prev_high * 1.02
    frame.iloc[-1, frame.columns.get_loc("Low")] = prev_high * 0.99
    frame.iloc[-1, frame.columns.get_loc("Close")] = prev_high * (0.997 if fail_close else 1.01)
    frame.iloc[-1, frame.columns.get_loc("Volume")] = 4_000_000
    return frame


def test_breakout_follow_through_adds_intraday_continuation_signal():
    candidate = validate_symbol_technical_state(
        "TEST",
        add_basic_technical_features(_breakout_follow_through_frame()),
    )

    assert candidate["technical_state"]["breakout_continuation_long"] is True
    assert "breakout_follow_through" in candidate["analysis_plan"]
    assert any("continuacion de ruptura" in reason for reason in candidate["reasons"])


def _range_expansion_breakout_frame() -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=230, freq="B")
    rows = []
    for index in range(230):
        close = 100 + ((index % 10) - 5)
        if index >= 170:
            close = 104 + (((index % 4) - 2) * 1.5)
        rows.append(
            {
                "Open": close - 0.5,
                "High": 110.0,
                "Low": close - 1.0,
                "Close": close,
                "Volume": 1_000_000,
            }
        )
    rows[-2] = {"Open": 111.0, "High": 112.0, "Low": 108.0, "Close": 111.0, "Volume": 1_000_000}
    rows[-1] = {"Open": 115.5, "High": 121.0, "Low": 113.0, "Close": 119.0, "Volume": 4_000_000}
    return pd.DataFrame(rows, index=dates)


def test_range_expansion_breakout_adds_distinct_long_signal():
    candidate = validate_symbol_technical_state(
        "TEST",
        add_basic_technical_features(_range_expansion_breakout_frame()),
    )

    assert candidate["technical_state"]["range_expansion_breakout_long"] is True
    assert "range_expansion_breakout" in candidate["analysis_plan"]
    assert any("range expansion breakout" in reason for reason in candidate["reasons"])


def _orderly_breakout_frame() -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=230, freq="B")
    close = pd.Series([100 + ((idx % 8) - 4) * 0.9 for idx in range(230)], index=dates, dtype=float)
    frame = pd.DataFrame(
        {
            "Open": close - 0.3,
            "High": close + 0.8,
            "Low": close - 0.8,
            "Close": close,
            "Volume": 1_000_000,
        },
        index=dates,
    )
    prev_high = float(frame.iloc[:-1]["High"].rolling(55).max().iloc[-1])
    frame.iloc[-2, frame.columns.get_loc("Open")] = prev_high * 1.005
    frame.iloc[-2, frame.columns.get_loc("High")] = prev_high * 1.01
    frame.iloc[-2, frame.columns.get_loc("Low")] = prev_high * 0.995
    frame.iloc[-2, frame.columns.get_loc("Close")] = prev_high * 1.008
    frame.iloc[-2, frame.columns.get_loc("Volume")] = 1_050_000
    frame.iloc[-1, frame.columns.get_loc("Open")] = prev_high * 1.015
    frame.iloc[-1, frame.columns.get_loc("High")] = prev_high * 1.05
    frame.iloc[-1, frame.columns.get_loc("Low")] = prev_high * 1.0
    frame.iloc[-1, frame.columns.get_loc("Close")] = prev_high * 1.042
    frame.iloc[-1, frame.columns.get_loc("Volume")] = 1_300_000
    return frame


def test_orderly_breakout_adds_distinct_long_signal():
    candidate = validate_symbol_technical_state(
        "TEST",
        add_basic_technical_features(_orderly_breakout_frame()),
    )

    assert candidate["technical_state"]["orderly_breakout_long"] is True
    assert "orderly_breakout" in candidate["analysis_plan"]
    assert any("orderly breakout" in reason for reason in candidate["reasons"])


def test_breakout_failure_risk_marks_failed_close():
    candidate = validate_symbol_technical_state(
        "TEST",
        add_basic_technical_features(_breakout_follow_through_frame(fail_close=True)),
    )

    assert candidate["technical_state"]["breakout_failure_risk"] is True
    assert "breakout_failure_risk" in candidate["analysis_plan"]
    assert any("fallo de ruptura" in reason for reason in candidate["reasons"])
