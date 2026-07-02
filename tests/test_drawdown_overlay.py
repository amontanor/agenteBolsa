from __future__ import annotations

import pandas as pd

from agente_bolsa.tools.strategy_edge_backtest import (
    exposure_drawdown_guard,
    exposure_vol_target,
    risk_overlay_metrics,
)


def test_risk_overlay_metrics_known_drawdown_ulcer_and_recovery():
    returns = pd.Series(
        [0.10, -0.10, -0.10, 0.25, 0.0],
        index=pd.bdate_range("2026-01-01", periods=5),
    )

    metrics = risk_overlay_metrics(returns)

    assert metrics["max_drawdown"] == -0.19
    assert round(metrics["ulcer_index"], 6) == 0.096021
    assert metrics["max_recovery_periods"] == 2
    assert metrics["pct_time_in_drawdown"] == 0.4


def test_vol_target_caps_to_one_and_scales_high_vol():
    calm = pd.Series([100.0 + i * 0.1 for i in range(30)], index=pd.bdate_range("2026-01-01", periods=30))
    volatile = pd.Series(
        [100.0, 110.0, 90.0, 115.0, 85.0] * 6,
        index=pd.bdate_range("2026-01-01", periods=30),
    )

    calm_exposure = exposure_vol_target(calm, target_vol=0.10, lookback=5)
    volatile_exposure = exposure_vol_target(volatile, target_vol=0.10, lookback=5)

    assert calm_exposure.max() <= 1.0
    assert calm_exposure.iloc[-1] == 1.0
    assert volatile_exposure.iloc[-1] < 1.0


def test_drawdown_guard_reduces_after_threshold_and_restores_on_new_high():
    close = pd.Series(
        [100.0, 110.0, 100.0, 90.0, 112.0],
        index=pd.bdate_range("2026-01-01", periods=5),
    )

    exposure = exposure_drawdown_guard(close, threshold=0.10, reduced_exposure=0.5)

    assert exposure.iloc[0] == 1.0
    assert exposure.iloc[2] == 1.0
    assert exposure.iloc[3] == 0.5
    assert exposure.iloc[4] == 1.0


def test_vol_target_is_causal_for_today_when_future_bar_changes():
    index = pd.bdate_range("2026-01-01", periods=40)
    close = pd.Series([100.0 + i for i in range(40)], index=index)
    changed_future = close.copy()
    changed_future.iloc[-1] = 10_000.0

    exposure = exposure_vol_target(close, target_vol=0.12, lookback=10)
    exposure_changed = exposure_vol_target(changed_future, target_vol=0.12, lookback=10)

    today = index[-2]
    assert exposure.loc[today] == exposure_changed.loc[today]
