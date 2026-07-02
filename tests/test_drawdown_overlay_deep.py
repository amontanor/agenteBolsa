from __future__ import annotations

import pandas as pd

from scripts.study_drawdown_overlay_deep import (
    annual_expanding_blocks,
    fixed_policy_oos_report,
    preregistered_criteria_report,
    recovery_days_from_episode_trough,
    sanity_check_spy_vs_gspc,
)


def test_annual_expanding_blocks_start_2005_and_end_2026():
    blocks = annual_expanding_blocks(first_year=2000, train_end_year=2004, final_year=2026)

    assert len(blocks) == 22
    assert blocks[0] == {
        "label": "train_2000_2004_apply_2005",
        "train_end": "2004-12-31",
        "apply_start": "2005-01-01",
        "apply_end": "2005-12-31",
    }
    assert blocks[-1]["label"] == "train_2000_2025_apply_2026"
    assert blocks[-1]["apply_end"] == "2026-12-31"


def test_fixed_policy_oos_report_includes_only_preregistered_fixed_policies():
    index = pd.bdate_range("2004-01-01", "2006-12-31")
    close = pd.Series([100.0 + i * 0.1 for i in range(len(index))], index=index)
    blocks = annual_expanding_blocks(first_year=2004, train_end_year=2004, final_year=2006)

    report = fixed_policy_oos_report(
        close=close,
        since="2004-01-01",
        end="2006-12-31",
        cost_bps_values=(20.0,),
        blocks=blocks,
    )

    policies = report["by_cost_bps"]["20.0"]["policies"]
    assert set(policies) == {"buy_hold", "vol_target_10pct", "vol_target_12pct"}
    assert policies["buy_hold"]["metrics"]["periods"] > 0
    assert len(policies["vol_target_12pct"]["yearly"]) == 2


def test_recovery_days_from_episode_trough_uses_full_future_path():
    returns = pd.Series(
        [0.0, -0.2, 0.1, 0.05, 0.1],
        index=pd.bdate_range("2026-01-01", periods=5),
    )

    assert recovery_days_from_episode_trough(
        returns,
        episode_start="2026-01-01",
        episode_end="2026-01-02",
    ) == 3


def test_sanity_check_spy_vs_gspc_flags_large_return_deviations():
    index = pd.bdate_range("2026-01-01", periods=4)
    spy = pd.Series([100.0, 101.0, 99.0, 100.0], index=index)
    gspc = pd.Series([100.0, 101.0, 101.0, 101.0], index=index)

    report = sanity_check_spy_vs_gspc(spy, gspc)

    assert report["overlap_days"] == 3
    assert report["deviation_gt_1pct_count"] == 2
    assert report["anomalies"][0]["abs_deviation"] >= 0.01


def test_preregistered_criteria_returns_binary_verdict():
    index = pd.bdate_range("2000-01-01", "2001-12-31")
    values = []
    price = 100.0
    for day in index:
        if day.year == 2000 and len(values) < 80:
            price *= 0.997
        elif day.year == 2001 and len(values) < 360:
            price *= 0.997
        else:
            price *= 1.001
        values.append(price)
    close = pd.Series(values, index=index)

    report = preregistered_criteria_report(close=close, since="2000-01-01", end="2001-12-31", cost_bps=20.0)

    assert report["verdict"] in {"CUMPLE", "NO CUMPLE"}
    assert report["total_years"] >= 1
    assert "full_period_sortino_buy_hold" in report
