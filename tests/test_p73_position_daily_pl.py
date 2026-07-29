from __future__ import annotations

from copy import deepcopy
from inspect import getsource

import agente_bolsa.web_app as web_app
from agente_bolsa.models import PortfolioSnapshot, PositionSnapshot
from agente_bolsa.tools.trade_history import _open_positions_summary
from agente_bolsa.web_app import (
    _portfolio_action_table,
    _position_pl_chip,
    _position_rows,
)


def _position(
    symbol: str = "AAPL",
    *,
    total: float = 25.0,
    total_pct: float = 0.025,
    today: float | None = 7.5,
    today_pct: float | None = 0.0075,
) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=symbol,
        qty=2.0,
        market_value=1025.0,
        avg_entry_price=500.0,
        current_price=512.5,
        unrealized_pl=total,
        unrealized_plpc=total_pct,
        unrealized_intraday_pl=today,
        unrealized_intraday_plpc=today_pct,
    )


def _history() -> dict:
    return {
        "open_positions": [
            {
                "symbol": "AAPL",
                "qty": 2.0,
                "market_value": 900.0,
                "avg_entry_price": 450.0,
                "current_price": 455.0,
                "unrealized_pl": 10.0,
                "unrealized_plpc": 0.01,
                "stop_loss": 430.0,
                "take_profit": 540.0,
            }
        ],
        "risk_levels": {},
        "executed_buy_lots_by_symbol": {},
        "local_broker_orders": [],
    }


def _portfolio(*positions: PositionSnapshot) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        account_id="paper-account",
        status="ACTIVE",
        currency="USD",
        cash=10_000.0,
        portfolio_value=11_000.0,
        buying_power=10_000.0,
        positions=list(positions),
        open_orders=[],
    )


def test_position_rows_use_one_canonical_snapshot_for_total_and_daily_pl_without_mutation():
    history = _history()
    history["open_positions"] = _open_positions_summary(_portfolio(_position()))
    before = deepcopy(history)

    [row] = _position_rows(history)

    assert row["Valor"] == 1025.0
    assert row["Qty"] == 2.0
    assert row["Entrada"] == 500.0
    assert row["Actual"] == 512.5
    assert row["P/L $"] == 25.0
    assert row["P/L %"] == 0.025
    assert row["P/L día $"] == 7.5
    assert row["P/L día %"] == 0.0075
    assert row["P/L fuente"] == "alpaca_position_snapshot"
    assert history == before


def test_missing_daily_pl_remains_unavailable_and_is_never_rendered_as_zero():
    history = _history()
    history["open_positions"] = _open_positions_summary(
        _portfolio(_position(today=None, today_pct=None))
    )
    [row] = _position_rows(history)

    assert row["P/L día $"] is None
    assert row["P/L día %"] is None
    assert _position_pl_chip(row["P/L día $"], row["P/L día %"]) == (
        "<span class='portfolio-native-unavailable'>n/d</span>"
    )
    assert "$0.00" not in _position_pl_chip(row["P/L día $"], row["P/L día %"])


def test_open_positions_summary_preserves_each_broker_position_without_identity_join():
    summary = _open_positions_summary(
        _portfolio(_position("AAPL", total=25.0), _position("MSFT", total=50.0))
    )

    assert [item["symbol"] for item in summary] == ["AAPL", "MSFT"]
    assert [item["unrealized_pl"] for item in summary] == [25.0, 50.0]
    assert [item["unrealized_intraday_pl"] for item in summary] == [7.5, 7.5]


def test_pl_chip_formats_amount_and_percentage_with_independent_sign():
    gain = _position_pl_chip(7.5, 0.0075)
    loss = _position_pl_chip(-4.25, -0.004)

    assert "$7.50" in gain
    assert "0.75%" in gain
    assert "gain" in gain
    assert "$-4.25" in loss
    assert "-0.40%" in loss
    assert "loss" in loss


class _Column:
    def __init__(self, output: list[str]):
        self.output = output

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def markdown(self, value: str, **_kwargs):
        self.output.append(value)

    def button(self, *_args, **_kwargs):
        return False


class _Streamlit:
    def __init__(self):
        self.output: list[str] = []

    def caption(self, value: str):
        self.output.append(value)

    def columns(self, widths):
        return [_Column(self.output) for _ in widths]

    def button(self, *_args, **_kwargs):
        return False


def test_open_portfolio_table_shows_total_and_daily_columns(monkeypatch):
    fake = _Streamlit()
    monkeypatch.setattr(web_app, "st", fake)
    history = _history()
    history["open_positions"] = _open_positions_summary(_portfolio(_position()))
    [row] = _position_rows(history)

    assert _portfolio_action_table([row], key_prefix="test") is None
    rendered = "\n".join(fake.output)
    assert "P/L total" in rendered
    assert "P/L día" in rendered
    assert "$25.00" in rendered
    assert "2.50%" in rendered
    assert "$7.50" in rendered
    assert "0.75%" in rendered


def test_dashboard_reuses_loaded_portfolio_snapshot_without_extra_broker_call():
    dashboard_source = getsource(web_app.page_dashboard)
    portfolio_source = getsource(web_app.page_portfolio)

    assert dashboard_source.count("alpaca_portfolio_snapshot(") == 1
    assert "portfolio_snapshot=portfolio" in dashboard_source
    assert "broker_client=broker_client" in dashboard_source
    assert portfolio_source.count("alpaca_portfolio_snapshot(") == 1
    assert "portfolio_snapshot=portfolio" in portfolio_source
    assert "broker_client=broker_client" in portfolio_source
