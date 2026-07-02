from __future__ import annotations

import json

import pandas as pd

from agente_bolsa.research.overlay_shadow import (
    build_overlay_shadow_observation,
    persist_overlay_shadow_observation,
)
from agente_bolsa.tools.strategy_edge_backtest import (
    DEFAULT_OVERLAY_VOL_LOOKBACK,
    exposure_regime_on_off,
    exposure_vol_target,
)


def _spy_close() -> pd.Series:
    index = pd.bdate_range("2024-01-02", periods=260)
    values = [400 + idx * 0.55 + ((idx % 7) - 3) * 0.4 for idx in range(len(index))]
    return pd.Series(values, index=index, name="Close")


def test_overlay_shadow_reproduces_deep_study_exposures():
    close = _spy_close()
    observation = build_overlay_shadow_observation(close)
    latest = close.index.max()
    realized = close.pct_change().rolling(DEFAULT_OVERLAY_VOL_LOOKBACK).std() * (252**0.5)

    assert observation["data_date"] == str(latest.date())
    assert observation["realized_vol_lookback_days"] == DEFAULT_OVERLAY_VOL_LOOKBACK
    assert observation["realized_vol_annualized"] == round(float(realized.loc[latest]), 6)
    assert observation["target_exposures"]["vol_target_12pct"] == round(
        float(exposure_vol_target(close, target_vol=0.12).loc[latest]), 6
    )
    assert observation["target_exposures"]["vol_target_10pct"] == round(
        float(exposure_vol_target(close, target_vol=0.10).loc[latest]), 6
    )
    assert observation["target_exposures"]["regime_sma200"] == round(
        float(exposure_regime_on_off(close, sma_window=200).loc[latest]), 6
    )


def test_overlay_shadow_persistence_is_daily_json_and_append_only_jsonl(tmp_path):
    observation = build_overlay_shadow_observation(_spy_close())

    first = persist_overlay_shadow_observation(observation, tmp_path)
    second = persist_overlay_shadow_observation(observation, tmp_path)

    daily_path = tmp_path / f"overlay_shadow_{observation['data_date']}.json"
    log_path = tmp_path / "overlay_shadow_log.jsonl"
    assert first["path"] == str(daily_path)
    assert second["log_path"] == str(log_path)
    assert json.loads(daily_path.read_text(encoding="utf-8"))["target_exposures"]["vol_target_12pct"] is not None
    assert len(log_path.read_text(encoding="utf-8").splitlines()) == 2
