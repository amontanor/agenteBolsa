"""P-L152: dashboard cards tell the truth outside a session and show today."""

from agente_bolsa.tools.equity_metrics import position_intraday_pl_reconciliation
from agente_bolsa.web_app import (
    _intraday_metric_display,
    _outside_trading_session,
    _today_breakdown,
)


class _Position:
    def __init__(self, value):
        self.unrealized_intraday_pl = value


def test_all_zero_intraday_is_not_a_real_zero():
    result = position_intraday_pl_reconciliation(
        [_Position(0.0), _Position(0.0), _Position(0.0)]
    )

    assert result["all_zero"] is True
    assert result["status"] == "unavailable"
    assert result["amount"] == 0.0


def test_mixed_values_are_a_real_measurement():
    result = position_intraday_pl_reconciliation([_Position(0.0), _Position(4.2)])

    assert result["all_zero"] is False
    assert result["status"] == "complete"


def test_closed_market_all_zero_shows_nd_not_money():
    metric = {"amount": 0.0, "known": 5, "total": 5, "status": "unavailable", "all_zero": True}

    amount, coverage = _intraday_metric_display(metric, market_open=False)

    assert amount == "n/d · mercado cerrado"
    assert coverage == "5/5 posiciones"


def test_open_market_all_zero_keeps_real_zero():
    metric = {"amount": 0.0, "known": 5, "total": 5, "status": "complete", "all_zero": True}

    amount, _ = _intraday_metric_display(metric, market_open=True)

    assert amount == "$0.00"


def test_genuine_value_is_shown_when_closed():
    metric = {"amount": 12.5, "known": 5, "total": 5, "status": "complete", "all_zero": False}

    amount, _ = _intraday_metric_display(metric, market_open=False)

    assert amount == "$12.50"


def test_weekend_timestamp_is_outside_session():
    assert _outside_trading_session("2026-09-19T09:27:53+00:00") is True


def test_session_timestamp_is_inside():
    assert _outside_trading_session("2026-09-18T15:30:00+00:00") is False


def _opening_context(start_at: str) -> dict:
    return {"account_current": {"system_start_at": start_at}}


def test_today_breakdown_counts_only_session_fills():
    history = {
        "days": [{"date": "2026-09-18", "realized_pl": 25.0}],
        "trades": [
            {"time": "2026-09-18T15:39:24+00:00", "side": "buy", "notional": 941.03, "realized_pl": None},
            {"time": "2026-09-18T16:10:00+00:00", "side": "sell", "notional": 500.0, "realized_pl": 12.5},
            {"time": "2026-09-14T20:00:00+00:00", "side": "sell", "notional": 999.0, "realized_pl": 99.0},
        ],
    }

    breakdown = _today_breakdown(history, _opening_context("2026-09-18T15:30:00+00:00"))

    assert breakdown["status"] == "available"
    assert breakdown["buy_count"] == 1
    assert breakdown["sell_count"] == 1
    assert breakdown["buy_notional"] == 941.03
    assert breakdown["sell_notional"] == 500.0
    assert breakdown["realized_pl"] == 12.5
    assert breakdown["realized_unknown"] == 0


def test_today_breakdown_marks_unknown_realized():
    history = {
        "days": [],
        "trades": [
            {"time": "2026-09-18T16:10:00+00:00", "side": "sell", "notional": 500.0, "realized_pl": None},
        ],
    }

    breakdown = _today_breakdown(history, _opening_context("2026-09-18T15:30:00+00:00"))

    assert breakdown["realized_pl"] is None
    assert breakdown["realized_unknown"] == 1


def test_today_breakdown_unavailable_without_opening():
    breakdown = _today_breakdown({"trades": []}, {"account_current": {}})

    assert breakdown["status"] == "unavailable"
    assert breakdown["reason"] == "opening_unavailable"
