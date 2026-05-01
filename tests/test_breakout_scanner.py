import pandas as pd

from agente_bolsa.tools.breakout_scanner import classify_breakout, merge_breakout_universe
from agente_bolsa.tools.technical_analysis import add_basic_technical_features


def _frame(latest_close: float, latest_high: float, latest_volume: float = 3000.0) -> pd.DataFrame:
    rows = []
    for index in range(70):
        close = 95.0 + (index % 5)
        rows.append(
            {
                "Open": close - 0.5,
                "High": 100.0,
                "Low": close - 1.0,
                "Close": close,
                "Volume": 1000.0,
            }
        )
    rows[-1] = {
        "Open": latest_close - 2.0,
        "High": latest_high,
        "Low": latest_close - 3.0,
        "Close": latest_close,
        "Volume": latest_volume,
    }
    return pd.DataFrame(rows, index=pd.date_range("2026-01-01", periods=70))


def test_confirmed_breakout_can_be_tradable_when_volume_and_risk_are_ok() -> None:
    features = add_basic_technical_features(_frame(101.0, 102.0))

    alert = classify_breakout("TEST", features)

    assert alert is not None
    assert alert["status"] == "confirmed_breakout"
    assert alert["tradable"] is True
    assert alert["risk_level"] == "moderate"
    assert alert["stop_loss"] < alert["close"]
    assert alert["take_profit"] > alert["close"]


def test_extended_breakout_is_detected_but_not_tradable() -> None:
    features = add_basic_technical_features(_frame(120.0, 121.0))

    alert = classify_breakout("TEST", features)

    assert alert is not None
    assert alert["status"] == "confirmed_breakout"
    assert alert["tradable"] is False
    assert alert["risk_level"] == "high"


def test_near_resistance_is_watch_only() -> None:
    features = add_basic_technical_features(_frame(99.0, 99.5))

    alert = classify_breakout("TEST", features)

    assert alert is not None
    assert alert["status"] == "watch_breakout"
    assert alert["tradable"] is False


def test_merge_breakout_universe_adds_extras_without_duplicates() -> None:
    assert merge_breakout_universe(["AAPL", "RDDT"], ["rddt", "NVDA"]) == ["AAPL", "RDDT", "NVDA"]
