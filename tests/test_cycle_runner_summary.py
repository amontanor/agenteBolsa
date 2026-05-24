from agente_bolsa.config import Settings
from agente_bolsa.cycle_runner import (
    _backtest_gate_decision,
    _record_trade_summary,
    _submitted_order_summary,
)


def test_submitted_order_summary_includes_trade_evidence():
    text = _submitted_order_summary(
        {
            "symbol": "SNDK",
            "notional": 1000.0,
            "status": "accepted",
            "confidence": 0.72,
            "entry_price": 1200,
            "stop_loss": 1100,
            "take_profit": 1350,
            "reason": "Score tecnico fuerte, patron alcista confirmado y riesgo definido.",
        }
    )

    assert "SNDK $1000.00 (accepted)" in text
    assert "conf 0.72" in text
    assert "entrada 1200.00, stop 1100.00, take 1350.00" in text
    assert "cumple: Score tecnico fuerte" in text


def test_auto_summary_does_not_show_stale_pending_manual_plans():
    emitted = {}

    class FakeStore:
        def pending_order_plans(self, limit=20):  # pragma: no cover - must not be called.
            raise AssertionError("stale pending plans should not be queried for auto result")

    class FakeReporter:
        def emit(self, agent, event_type, cycle_id, message, payload=None):
            emitted["message"] = message
            emitted["payload"] = payload or {}

    _record_trade_summary(
        Settings(AUTO_PAPER_TRADING=True, REQUIRE_HUMAN_APPROVAL=False),
        FakeStore(),
        FakeReporter(),
        "cycle",
        {
            "submitted": [],
            "failed": [],
            "recommendations": [
                {"symbol": "AMZN", "action": "hold", "confidence": 0.9},
                {"symbol": "PWR", "action": "hold", "confidence": 0.9},
            ],
        },
    )

    assert "No compra ni vende en este ciclo" in emitted["message"]
    assert "AMZN:hold:0.90" in emitted["message"]
    assert "Planes paper pendientes" not in emitted["message"]


def test_auto_summary_explains_approved_buy_not_sent_due_to_rejections():
    emitted = {}

    class FakeStore:
        def pending_order_plans(self, limit=20):  # pragma: no cover - should not be called here.
            raise AssertionError("pending plans should not be queried")

    class FakeReporter:
        def emit(self, agent, event_type, cycle_id, message, payload=None):
            emitted["message"] = message
            emitted["payload"] = payload or {}

    _record_trade_summary(
        Settings(AUTO_PAPER_TRADING=True, REQUIRE_HUMAN_APPROVAL=False),
        FakeStore(),
        FakeReporter(),
        "cycle",
        {
            "submitted": [],
            "failed": [],
            "recommendations": [{"symbol": "STX", "action": "buy", "confidence": 0.85}],
            "approved_buys": ["STX"],
            "rejected_order_plans": [
                {
                    "symbol": "STX",
                    "stage": "position_sizing",
                    "reason": "below_min_order_notional",
                }
            ],
        },
    )

    assert "Compras aprobadas por señal: STX" in emitted["message"]
    assert "position_sizing:below_min_order_notional" in emitted["message"]
    assert emitted["payload"]["approved_buys"] == ["STX"]


def test_backtest_gate_approves_when_metrics_pass_thresholds():
    settings = Settings(
        BACKTEST_GATE_MIN_TRADES=10,
        BACKTEST_GATE_MIN_HIT_RATE=0.45,
        BACKTEST_GATE_MIN_PROFIT_FACTOR=1.05,
        BACKTEST_GATE_MAX_DRAWDOWN=0.10,
    )

    approved, reason = _backtest_gate_decision(
        settings,
        {
            "metrics": {
                "trades": 12,
                "hit_rate": 0.50,
                "profit_factor": 1.20,
                "max_drawdown": -0.05,
            }
        },
    )

    assert approved is True
    assert reason == "backtest aprobado"


def test_backtest_gate_blocks_weak_profit_factor():
    settings = Settings(
        BACKTEST_GATE_MIN_TRADES=10,
        BACKTEST_GATE_MIN_HIT_RATE=0.45,
        BACKTEST_GATE_MIN_PROFIT_FACTOR=1.05,
        BACKTEST_GATE_MAX_DRAWDOWN=0.10,
    )

    approved, reason = _backtest_gate_decision(
        settings,
        {
            "metrics": {
                "trades": 12,
                "hit_rate": 0.50,
                "profit_factor": 0.90,
                "max_drawdown": -0.05,
            }
        },
    )

    assert approved is False
    assert "profit-factor" in reason


def test_backtest_gate_blocks_excessive_drawdown():
    settings = Settings(
        BACKTEST_GATE_MIN_TRADES=10,
        BACKTEST_GATE_MIN_HIT_RATE=0.45,
        BACKTEST_GATE_MIN_PROFIT_FACTOR=1.05,
        BACKTEST_GATE_MAX_DRAWDOWN=0.10,
    )

    approved, reason = _backtest_gate_decision(
        settings,
        {
            "metrics": {
                "trades": 12,
                "hit_rate": 0.50,
                "profit_factor": 1.20,
                "max_drawdown": -0.15,
            }
        },
    )

    assert approved is False
    assert "max drawdown" in reason
