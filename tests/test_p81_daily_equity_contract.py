from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agente_bolsa.models import PortfolioSnapshot, PositionSnapshot
from agente_bolsa.tools.broker import BrokerClientFactory
from agente_bolsa.tools.equity_metrics import daily_equity_change, position_intraday_pl_reconciliation
from agente_bolsa.web_app import _daily_equity_detail, _daily_equity_metric_for_portfolio, _daily_vs_spy_chart


def _portfolio(*, equity: float = 1005.0, previous_close: float | None = 1000.0) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=900.0,
        portfolio_value=equity,
        buying_power=1000.0,
        positions=[],
        open_orders=[],
        previous_close_equity=previous_close,
    )


def test_daily_equity_change_uses_previous_close_as_denominator_and_preserves_window():
    metric = daily_equity_change(
        1005.0,
        1000.0,
        previous_close_at="2026-07-31T20:00:00+00:00",
        as_of="2026-08-03T12:00:00+00:00",
    )

    assert metric["status"] == "available"
    assert metric["daily_equity_pl"] == 5.0
    assert metric["daily_equity_return"] == pytest.approx(0.005)
    assert metric["previous_close_equity"] == 1000.0
    assert metric["window_start"] == "2026-07-31T20:00:00+00:00"
    assert metric["window_end"] == "2026-08-03T12:00:00+00:00"


@pytest.mark.parametrize("previous_close", [None, 0.0, -1.0, "not-a-number"])
def test_daily_equity_change_is_unavailable_without_valid_provider_close(previous_close):
    metric = daily_equity_change(1005.0, previous_close)

    assert metric["status"] == "unavailable"
    assert metric["daily_equity_pl"] is None
    assert metric["daily_equity_return"] is None
    assert metric["reason"] in {
        "previous_close_equity_unavailable",
        "previous_close_equity_invalid",
    }


def test_portfolio_daily_metric_prefers_account_last_equity_over_opening_context_or_history():
    metric = _daily_equity_metric_for_portfolio(
        _portfolio(equity=1005.0, previous_close=1000.0),
        {"timestamp": ["2026-07-31T20:00:00+00:00"], "equity": [1000.0]},
        as_of=datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc),
    )

    assert metric["daily_equity_pl"] == 5.0
    assert metric["daily_equity_return"] == pytest.approx(0.005)
    assert metric["source"] == "Alpaca account.last_equity"
    assert "31/07/2026" in _daily_equity_detail(metric)
    assert "03/08/2026" in _daily_equity_detail(metric)


def test_portfolio_daily_metric_does_not_silently_fallback_to_period_history():
    metric = _daily_equity_metric_for_portfolio(
        _portfolio(equity=1005.0, previous_close=None),
        {"timestamp": ["2026-07-31T20:00:00+00:00"], "equity": [1000.0]},
        as_of=datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc),
    )

    assert metric["status"] == "unavailable"
    assert metric["daily_equity_pl"] is None
    assert "n/d" in _daily_equity_detail(metric)


def test_position_intraday_pl_is_secondary_reconciliation_with_partial_coverage():
    positions = [
        SimpleNamespace(unrealized_intraday_pl=43.7655),
        SimpleNamespace(unrealized_intraday_pl=6.78),
        SimpleNamespace(unrealized_intraday_pl=None),
    ]

    result = position_intraday_pl_reconciliation(positions)

    assert result == {
        "amount": pytest.approx(50.5455),
        "known": 2,
        "total": 3,
        "status": "partial",
        "source": "portfolio_snapshot",
    }


def test_broker_snapshot_carries_last_equity_without_extra_account_call(monkeypatch):
    calls = []

    class _Client:
        def get_account(self):
            calls.append("account")
            return SimpleNamespace(
                id="paper",
                status="ACTIVE",
                currency="USD",
                cash="900",
                portfolio_value="1005",
                buying_power="1000",
                last_equity="1000",
            )

        def get_all_positions(self):
            calls.append("positions")
            return []

        def get_orders(self, *, filter):  # noqa: ARG002
            calls.append("orders")
            return []

    factory = BrokerClientFactory.__new__(BrokerClientFactory)
    monkeypatch.setattr(factory, "alpaca_trading_client", lambda: _Client())
    snapshot = factory.alpaca_portfolio_snapshot()

    assert snapshot.previous_close_equity == 1000.0
    assert calls.count("account") == 1


def test_legacy_snapshot_without_last_equity_remains_unavailable():
    snapshot = PortfolioSnapshot("paper", "ACTIVE", "USD", 0, 1005, 0, [], [])
    metric = _daily_equity_metric_for_portfolio(snapshot, {}, as_of=datetime.now(timezone.utc))

    assert metric["status"] == "unavailable"


def test_current_opening_point_uses_visual_as_of_and_dashed_connector():
    rows = [
        {
            "session_date": "2026-07-30",
            "status": "final",
            "system_pct": 0.01,
            "spy_pct": 0.008,
            "system_start_at": "2026-07-30T13:30:00+00:00",
            "system_end_at": "2026-07-31T13:30:00+00:00",
        },
        {
            "session_date": "2026-07-31",
            "status": "in_progress",
            "system_pct": 0.0006,
            "spy_pct": 0.0032,
            "system_start_at": "2026-07-31T13:30:00+00:00",
            "system_end_at": "2026-08-03T12:00:00+00:00",
        },
    ]

    chart = _daily_vs_spy_chart(rows)
    assert chart is not None
    spec = chart.to_dict()
    assert any(
        layer.get("mark", {}).get("type") == "line"
        and layer.get("mark", {}).get("strokeDash") == [6, 4]
        for layer in spec["layer"]
    )
    assert any(
        item.get("field") == "fecha_visual" and item.get("title") == "Fecha visible"
        for layer in spec["layer"]
        for item in layer.get("encoding", {}).get("tooltip", [])
    )

