import pandas as pd

import agente_bolsa.tools.strategy_edge_backtest as strategy_edge_backtest
from agente_bolsa.tools.strategy_edge_backtest import (
    SelectorObservation,
    StrategyObservation,
    add_vector_signal_columns,
    sampled_session_dates,
    summarize_observations,
    summarize_selector_observations,
)


def test_summarize_observations_aggregates_overall_and_by_regime():
    observations = [
        StrategyObservation(
            strategy_name="builtin_pullback",
            signal_date="2026-01-02",
            symbol="AAA",
            regime="bull_above_sma200",
            raw_returns={5: 0.04},
            benchmark_returns={5: 0.01},
            beta_asof=1.2,
        ),
        StrategyObservation(
            strategy_name="builtin_pullback",
            signal_date="2026-01-03",
            symbol="BBB",
            regime="bear_below_sma200",
            raw_returns={5: -0.01},
            benchmark_returns={5: -0.02},
            beta_asof=0.8,
        ),
        StrategyObservation(
            strategy_name="builtin_breakout",
            signal_date="2026-01-02",
            symbol="CCC",
            regime="bull_above_sma200",
            raw_returns={5: 0.02},
            benchmark_returns={5: 0.01},
            beta_asof=1.0,
        ),
        StrategyObservation(
            strategy_name="builtin_breakout",
            signal_date="2026-01-03",
            symbol="DDD",
            regime="bear_below_sma200",
            raw_returns={5: -0.03},
            benchmark_returns={5: -0.02},
            beta_asof=1.5,
        ),
    ]

    summary = summarize_observations(observations, horizons=(5,), cost_bps=10.0)

    pull_raw = summary["overall"]["builtin_pullback"]["return_5d"]["raw"]
    assert pull_raw["n"] == 2
    assert pull_raw["mean"] == 0.015
    assert pull_raw["median"] == 0.015
    assert pull_raw["hit_rate"] == 0.5
    assert pull_raw["mean_net"] == 0.014

    pull_excess = summary["overall"]["builtin_pullback"]["return_5d"]["excess_vs_spy"]
    assert pull_excess["mean"] == 0.02

    breakout_beta = summary["overall"]["builtin_breakout"]["return_5d"]["beta_adjusted_vs_spy"]
    assert breakout_beta["mean"] == 0.005

    bull_pull = summary["by_regime"]["bull_above_sma200"]["builtin_pullback"]["return_5d"]["raw"]
    assert bull_pull["n"] == 1
    assert bull_pull["mean"] == 0.04

    delta_raw = summary["delta_pullback_minus_breakout"]["return_5d"]["raw"]
    assert delta_raw["mean_delta"] == 0.02
    assert delta_raw["mean_net_delta"] == 0.02


def test_vector_signal_columns_detect_pullback_and_exclude_breakout_flags():
    frame = pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [102.0, 102.0],
            "Low": [99.0, 100.0],
            "Close": [101.0, 104.0],
            "Volume": [1_000_000, 1_100_000],
            "sma_20": [100.0, 100.0],
            "sma_50": [95.0, 95.0],
            "sma_200": [90.0, 90.0],
            "return_5d": [0.0, 0.0],
            "return_20d": [0.01, 0.01],
            "return_60d": [0.08, 0.08],
            "rsi_14": [50.0, 55.0],
            "volume_zscore_20": [0.0, 1.5],
            "gap_pct": [0.0, 0.04],
            "close_position_in_range": [0.6, 0.9],
            "prev_high_55": [120.0, 100.0],
            "bollinger_pct_b_20": [0.5, 0.5],
            "macd": [1.0, 1.0],
            "macd_signal": [0.5, 0.5],
            "above_long_trend": [True, True],
            "trend_positive": [True, True],
            "candle_bullish_signal": [False, False],
            "candle_bearish_signal": [False, False],
            "candle_doji": [False, False],
        },
        index=pd.bdate_range("2026-01-01", periods=2),
    )

    result = add_vector_signal_columns(frame)

    assert bool(result.iloc[0]["vector_pullback_signal"]) is True
    assert bool(result.iloc[1]["vector_range_expansion_breakout_long"]) is True
    assert bool(result.iloc[1]["vector_pullback_signal"]) is False


def test_sampled_session_dates_keeps_one_of_every_n_sessions():
    assert sampled_session_dates(["d1", "d2", "d3", "d4", "d5", "d6"], every=5) == ["d1", "d6"]


def test_summarize_selector_observations_compares_top_n_and_deciles():
    observations = [
        SelectorObservation(
            cohort="population",
            signal_date="2026-01-02",
            symbol="AAA",
            regime="bull_above_sma200",
            selector_score=0.01,
            technical_score=8.0,
            score_decile=1,
            raw_returns={5: -0.02},
            benchmark_returns={5: 0.01},
            beta_asof=1.0,
        ),
        SelectorObservation(
            cohort="population",
            signal_date="2026-01-02",
            symbol="BBB",
            regime="bull_above_sma200",
            selector_score=0.04,
            technical_score=12.0,
            score_decile=10,
            raw_returns={5: 0.06},
            benchmark_returns={5: 0.01},
            beta_asof=1.2,
        ),
        SelectorObservation(
            cohort="top_n",
            signal_date="2026-01-02",
            symbol="BBB",
            regime="bull_above_sma200",
            selector_score=0.04,
            technical_score=12.0,
            score_decile=10,
            raw_returns={5: 0.06},
            benchmark_returns={5: 0.01},
            beta_asof=1.2,
        ),
    ]

    summary = summarize_selector_observations(observations, horizons=(5,), cost_bps=10.0)

    population = summary["overall"]["population"]["return_5d"]["raw"]
    assert population["n"] == 2
    assert population["mean"] == 0.02
    assert population["mean_net"] == 0.019

    top_n = summary["overall"]["top_n"]["return_5d"]["raw"]
    assert top_n["n"] == 1
    assert top_n["mean"] == 0.06

    delta = summary["delta_top_n_minus_population"]["return_5d"]["raw"]
    assert delta["mean_delta"] == 0.04

    decile_10 = summary["score_deciles"]["10"]["return_5d"]["excess_vs_spy"]
    assert decile_10["mean_net"] == 0.049
    monotonic = summary["score_monotonicity"]["return_5d"]["raw"]
    assert monotonic["d10_minus_d1"] == 0.08
    assert top_n["sharpe_simple"] is None
    assert top_n["tail_loss_rate_lt_10pct"] == 0.0
    assert top_n["max_drawdown"] == 0.0


def test_extension_gate_delta_compares_rejected_minus_pass():
    observations = [
        SelectorObservation(
            cohort="extension_pass",
            signal_date="2026-01-02",
            symbol="AAA",
            regime="bull_above_sma200",
            selector_score=0.03,
            technical_score=10.0,
            score_decile=None,
            raw_returns={5: 0.01},
            benchmark_returns={5: 0.0},
            beta_asof=1.0,
        ),
        SelectorObservation(
            cohort="extension_rejected",
            signal_date="2026-01-02",
            symbol="BBB",
            regime="bull_above_sma200",
            selector_score=0.04,
            technical_score=12.0,
            score_decile=None,
            raw_returns={5: -0.03},
            benchmark_returns={5: 0.0},
            beta_asof=1.0,
        ),
    ]

    summary = summarize_selector_observations(observations, horizons=(5,), cost_bps=10.0)
    delta = strategy_edge_backtest._delta_between_cohorts(
        summary,
        left="extension_rejected",
        right="extension_pass",
        horizons=(5,),
    )

    assert summary["overall"]["extension_pass"]["return_5d"]["raw"]["mean_net"] == 0.009
    assert summary["overall"]["extension_rejected"]["return_5d"]["raw"]["mean_net"] == -0.031
    assert delta["return_5d"]["raw"]["mean_delta"] == -0.04
    assert delta["return_5d"]["raw"]["mean_net_delta"] == -0.04
    assert delta["return_5d"]["raw"]["sharpe_simple_delta"] is None
    assert delta["return_5d"]["raw"]["tail_loss_rate_lt_10pct_delta"] == 0.0


def test_selector_risk_metrics_include_drawdown_downside_and_tail_rate():
    observations = [
        SelectorObservation(
            cohort="population",
            signal_date="2026-01-02",
            symbol="AAA",
            regime="bull_above_sma200",
            selector_score=0.01,
            technical_score=8.0,
            score_decile=1,
            raw_returns={5: 0.04},
            benchmark_returns={5: 0.0},
            beta_asof=1.0,
        ),
        SelectorObservation(
            cohort="population",
            signal_date="2026-01-09",
            symbol="BBB",
            regime="bull_above_sma200",
            selector_score=0.02,
            technical_score=9.0,
            score_decile=2,
            raw_returns={5: -0.12},
            benchmark_returns={5: 0.0},
            beta_asof=1.0,
        ),
        SelectorObservation(
            cohort="population",
            signal_date="2026-01-16",
            symbol="CCC",
            regime="bull_above_sma200",
            selector_score=0.03,
            technical_score=10.0,
            score_decile=3,
            raw_returns={5: 0.02},
            benchmark_returns={5: 0.0},
            beta_asof=1.0,
        ),
    ]

    summary = summarize_selector_observations(observations, horizons=(5,), cost_bps=10.0)
    stats = summary["overall"]["population"]["return_5d"]["raw"]

    assert stats["n"] == 3
    assert stats["mean_net"] == -0.021
    assert stats["sharpe_simple"] < 0
    assert stats["downside_deviation"] > 0
    assert stats["tail_loss_rate_lt_10pct"] == 0.3333
    assert stats["max_drawdown"] < 0
