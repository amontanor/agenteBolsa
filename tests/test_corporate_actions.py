"""Tests de huecos operativos: earnings, splits, dividendos, halts (T5.10)."""

from agente_bolsa.tools.corporate_actions import (
    adjust_outcome_for_split,
    apply_dividend,
    detect_halt,
    detect_split_factor,
    earnings_hold_decision,
)


def test_earnings_hold_reduces_or_exits():
    # Sin earnings cercanos: hold.
    assert earnings_hold_decision(unrealized_pnl=100, days_to_earnings=5, max_days=2)["action"] == "hold"
    # Earnings manana con PnL positivo: reducir 50%.
    d = earnings_hold_decision(unrealized_pnl=100, days_to_earnings=1, max_days=2)
    assert d["action"] == "reduce" and d["qty_factor"] == 0.5
    # Earnings manana con PnL negativo: cerrar.
    d2 = earnings_hold_decision(unrealized_pnl=-50, days_to_earnings=1, max_days=2)
    assert d2["action"] == "exit"
    # Politica explicita.
    assert earnings_hold_decision(unrealized_pnl=10, days_to_earnings=1, policy="hold")["action"] == "hold"
    assert earnings_hold_decision(unrealized_pnl=10, days_to_earnings=1, policy="exit")["action"] == "exit"


def test_detect_split_factor():
    assert detect_split_factor(200.0, 100.0) == 2.0   # 2:1
    assert detect_split_factor(300.0, 100.0) == 3.0   # 3:1
    assert detect_split_factor(50.0, 100.0) == 0.5    # reverse 1:2
    assert detect_split_factor(101.0, 100.0) is None  # cambio normal, no split


def test_split_does_not_count_as_loss():
    # Un 2:1 sin cambio real de valor no debe contar como -50%.
    outcome = {"return_pct": -0.50, "verdict": "loser"}
    adjusted = adjust_outcome_for_split(outcome, prev_close=200.0, new_price=100.0)
    assert adjusted["corporate_action_adjusted"] == 1
    assert abs(adjusted["return_pct"]) < 0.01  # ~0


def test_dividend_added_to_return():
    out = apply_dividend({"return_pct": 0.02}, dividend_per_share=1.0, entry_price=100.0)
    assert out["return_pct"] == 0.03
    assert out["dividend_adjusted"] == 1


def test_detect_halt():
    assert detect_halt(2) is True
    assert detect_halt(1) is False
