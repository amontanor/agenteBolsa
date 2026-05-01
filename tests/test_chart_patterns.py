import pandas as pd

from agente_bolsa.tools.chart_patterns import analyze_chart_patterns
from agente_bolsa.tools.technical_analysis import add_basic_technical_features
from agente_bolsa.tools.technical_state_validator import validate_symbol_technical_state


def _ohlcv(values: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=len(values), freq="B")
    close = pd.Series(values, index=dates, dtype=float)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 0.5,
            "Low": close - 0.5,
            "Close": close,
            "Volume": 1_000_000,
        },
        index=dates,
    )


def test_detects_confirmed_head_and_shoulders():
    values = [100.0] * 100
    values += [116, 119, 125, 120, 116, 119, 132, 122, 114, 117, 124, 119, 112, 110, 108]

    patterns = analyze_chart_patterns(_ohlcv(values), lookback=40)

    head_shoulders = next(item for item in patterns if item["pattern"] == "head_and_shoulders")
    assert head_shoulders["bias"] == "bearish"
    assert head_shoulders["status"] == "confirmed"
    assert head_shoulders["label"] == "hombro-cabeza-hombro"


def test_detects_confirmed_inverse_head_and_shoulders():
    values = [100.0] * 100
    values += [102, 98, 95, 100, 106, 99, 88, 97, 107, 101, 96, 103, 109, 110]

    patterns = analyze_chart_patterns(_ohlcv(values), lookback=40)

    inverse = next(item for item in patterns if item["pattern"] == "inverse_head_and_shoulders")
    assert inverse["bias"] == "bullish"
    assert inverse["status"] == "confirmed"
    assert inverse["label"] == "hombro-cabeza-hombro invertido"


def test_chart_patterns_are_added_to_symbol_validation():
    values = [100.0] * 215
    values += [116, 119, 125, 120, 116, 119, 132, 122, 114, 117, 124, 119, 112, 110, 108]

    features = add_basic_technical_features(_ohlcv(values))
    candidate = validate_symbol_technical_state("TEST", features)

    chart_patterns = candidate["technical_state"]["chart_patterns"]
    assert any(item["pattern"] == "head_and_shoulders" for item in chart_patterns)
    assert "chart_patterns" in candidate["analysis_plan"]
    assert "head_and_shoulders_check" in candidate["analysis_plan"]
    assert candidate["short_score"] >= 3
