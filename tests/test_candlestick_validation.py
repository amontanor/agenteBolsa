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
