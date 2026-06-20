from agente_bolsa.config import Settings
from agente_bolsa.tools import exit_horizon_shadow


def test_exit_horizon_shadow_compares_latest_matured_window(monkeypatch, tmp_path):
    rows = [
        {
            "signal_id": "s1",
            "symbol": "AAPL",
            "signal_date": "2026-06-01",
            "outcome": {"return_1d": 0.01, "return_3d": -0.02, "return_5d": 0.03, "return_10d": 0.08},
        },
        {
            "signal_id": "s2",
            "symbol": "MSFT",
            "signal_date": "2026-06-02",
            "outcome": {"return_1d": -0.01, "return_3d": 0.01, "return_5d": 0.02, "return_10d": None},
        },
    ]
    monkeypatch.setattr(
        exit_horizon_shadow,
        "linked_executed_buy_signals",
        lambda settings, store, since_date: {"linked_rows": rows},
    )
    benchmark = {
        ("2026-06-01", 3): 0.01,
        ("2026-06-01", 10): 0.02,
        ("2026-06-02", 3): 0.0,
        ("2026-06-02", 5): 0.01,
    }
    monkeypatch.setattr(exit_horizon_shadow, "_build_spy_forward_returns", lambda *args, **kwargs: benchmark)

    report = exit_horizon_shadow.build_exit_horizon_shadow(Settings(DATA_DIR=tmp_path), object())

    assert report["mode"] == "SHADOW"
    assert report["changes_trading_behavior"] is False
    assert report["current_1_3d"]["expectancy"] == -0.005
    assert report["shadow_5_10d"]["expectancy"] == 0.05
    assert report["paired_comparison"]["avg_return_delta"] == 0.055
    assert report["promotion_eligible"] is False
