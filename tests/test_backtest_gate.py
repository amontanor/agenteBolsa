from __future__ import annotations

from agente_bolsa.tools.backtest import evaluate_backtest_gate


def _base_report() -> dict:
    return {
        "metrics": {
            "trades": 24,
            "hit_rate": 0.54,
            "profit_factor": 1.54,
            "max_drawdown": -0.02,
        },
        "benchmark": {
            "metrics": {
                "alpha_vs_benchmark": -0.4474,
                "trade_window_alpha": 0.00518,
                "trade_windows_compared": 24,
            }
        },
        "regime_summary": {},
    }


def test_backtest_gate_prefers_trade_window_alpha_for_episodic_strategy():
    result = evaluate_backtest_gate(
        _base_report(),
        min_trades=10,
        min_hit_rate=0.45,
        min_profit_factor=1.05,
        max_drawdown=0.1,
        min_alpha_vs_benchmark=0.0,
        min_trade_window_alpha=0.0,
        min_regime_trades=0,
        max_negative_regimes=None,
    )

    assert result["approved"] is True


def test_backtest_gate_uses_period_alpha_when_trade_window_benchmark_is_unavailable():
    report = _base_report()
    report["benchmark"]["metrics"]["trade_window_alpha"] = None
    report["benchmark"]["metrics"]["trade_windows_compared"] = 0

    result = evaluate_backtest_gate(
        report,
        min_trades=10,
        min_hit_rate=0.45,
        min_profit_factor=1.05,
        max_drawdown=0.1,
        min_alpha_vs_benchmark=0.0,
        min_trade_window_alpha=0.0,
        min_regime_trades=0,
        max_negative_regimes=None,
    )

    assert result["approved"] is False
    assert "alpha vs benchmark" in result["reason"]
