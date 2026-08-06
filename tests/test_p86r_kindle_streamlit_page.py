from __future__ import annotations

import inspect
from datetime import datetime, timezone
from types import SimpleNamespace

import streamlit as st

from agente_bolsa import web_app
from agente_bolsa.models import PortfolioSnapshot, PositionSnapshot


def _portfolio(*positions: PositionSnapshot, equity: float = 1005.0, previous_close: float | None = 1000.0):
    return PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=900.0,
        portfolio_value=equity,
        buying_power=900.0,
        positions=list(positions),
        open_orders=[],
        previous_close_equity=previous_close,
    )


def test_streamlit_hidden_kindle_route_is_declared_without_replacing_manual_menu():
    source = inspect.getsource(web_app.main)
    assert "st.navigation" in source
    assert 'url_path="kindle"' in source
    assert 'visibility="hidden"' in source
    assert 'position="hidden"' in source

    shell_source = inspect.getsource(web_app._render_manual_navigation)
    assert 'st.sidebar.radio(' in shell_source
    assert '"Dashboard"' in shell_source


def test_streamlit_158_supports_exact_hidden_kindle_page():
    page = st.Page(lambda: None, title="Kindle", url_path="kindle", visibility="hidden")
    # Bare-mode Streamlit has no ScriptRunContext, so URL materialization is
    # deferred to navigation; the visibility contract is still available.
    assert "url_path" in inspect.signature(st.Page).parameters
    assert page._visibility == "hidden"


def test_main_keeps_dashboard_styles_off_hidden_kindle_page(monkeypatch):
    calls = []

    class FakeNavigation:
        url_path = "kindle"

        def run(self):
            calls.append("run")

    class FakeStreamlit:
        def set_page_config(self, **kwargs):
            calls.append(("config", kwargs))

        def Page(self, *args, **kwargs):
            calls.append(("page", kwargs))
            return object()

        def navigation(self, pages, *, position):
            calls.append(("navigation", position))
            return FakeNavigation()

    monkeypatch.setattr(web_app, "st", FakeStreamlit())
    monkeypatch.setattr(web_app, "_setup_page_styles", lambda: calls.append("dashboard_styles"))

    web_app.main()

    assert "dashboard_styles" not in calls
    assert "run" in calls
    assert ("navigation", "hidden") in calls


def test_kindle_view_model_uses_daily_equity_contract_and_minimal_position_fields():
    position = PositionSnapshot(
        symbol="<AAPL>",
        qty=2.0,
        market_value=210.0,
        avg_entry_price=100.0,
        current_price=105.0,
        unrealized_pl=10.0,
        unrealized_plpc=0.05,
        side="long",
        unrealized_intraday_pl=3.0,
        unrealized_intraday_plpc=0.015,
    )
    model = web_app._kindle_view_model(
        _portfolio(position),
        {},
        as_of=datetime(2026, 8, 6, 10, 0, tzinfo=timezone.utc),
    )
    assert model["daily"]["amount"] == 5.0
    assert model["daily"]["pct"] == 0.005
    assert model["positions"] == [
        {
            "symbol": "<AAPL>",
            "qty": 2.0,
            "entry": 100.0,
            "current": 105.0,
            "total_pl_pct": 0.05,
            "today_pl_pct": 0.015,
        }
    ]


def test_kindle_positions_are_sorted_and_missing_values_are_not_zero():
    model = web_app._kindle_view_model(
        _portfolio(
            PositionSnapshot(
                symbol="zeta",
                qty=None,
                market_value=None,
                avg_entry_price=None,
                current_price=None,
                unrealized_pl=None,
                unrealized_plpc=None,
                side="long",
                unrealized_intraday_pl=None,
                unrealized_intraday_plpc=None,
            ),
            PositionSnapshot(
                symbol="alpha",
                qty=1.0,
                market_value=100.0,
                avg_entry_price=100.0,
                current_price=100.0,
                unrealized_pl=0.0,
                unrealized_plpc=0.0,
                side="long",
                unrealized_intraday_pl=0.0,
                unrealized_intraday_plpc=0.0,
            ),
        ),
        {},
        as_of=datetime(2026, 8, 6, 10, 0, tzinfo=timezone.utc),
    )
    assert [row["symbol"] for row in model["positions"]] == ["ALPHA", "ZETA"]
    assert model["positions"][1]["qty"] is None
    assert model["positions"][1]["total_pl_pct"] is None


def test_kindle_spy_is_only_shown_for_existing_comparable_dashboard_context():
    as_of = datetime(2026, 8, 6, 10, 0, tzinfo=timezone.utc)
    comparable = {"current": {"comparison_status": "comparable", "spy_pct": 0.012, "spy_end_at": as_of.isoformat()}}
    unavailable = {"current": {"comparison_status": "pending", "reason_codes": ["spy_as_of_mismatch"]}}

    assert web_app._kindle_view_model(_portfolio(), comparable, as_of=as_of)["spy"] == {
        "pct": 0.012,
        "status": "comparable",
        "reason": None,
    }
    assert web_app._kindle_view_model(_portfolio(), unavailable, as_of=as_of)["spy"]["pct"] is None
    assert web_app._kindle_view_model(_portfolio(), unavailable, as_of=as_of)["spy"]["status"] == "unavailable"


def test_kindle_html_is_basic_escaped_and_contains_only_requested_content():
    model = web_app._kindle_view_model(
        _portfolio(
            PositionSnapshot(
                symbol="<AAPL>",
                qty=1.0,
                market_value=100.0,
                avg_entry_price=100.0,
                current_price=101.0,
                unrealized_pl=1.0,
                unrealized_plpc=0.01,
                side="long",
                unrealized_intraday_pl=0.5,
                unrealized_intraday_plpc=0.005,
            )
        ),
        {},
        as_of=datetime(2026, 8, 6, 10, 0, tzinfo=timezone.utc),
    )
    html = web_app._kindle_html(model)
    assert "&lt;AAPL&gt;" in html
    assert "Ganancia/pérdida global de hoy" in html
    assert "S&amp;P 500 de hoy" in html
    assert "Cantidad" in html and "P/L hoy" in html
    assert "<script" not in html.lower()
    assert "https://" not in html
    assert "Actualizar" in html


def test_kindle_page_reuses_one_snapshot_and_no_scheduler_or_persistent_carrier(monkeypatch):
    calls = []

    class FakeBroker:
        def alpaca_portfolio_snapshot(self):
            calls.append("snapshot")
            return _portfolio()

        def alpaca_portfolio_history(self, *, period, timeframe):
            calls.append((period, timeframe))
            return {"timestamp": [], "equity": []}

    class FakeStreamlit:
        def __init__(self):
            self.markdown_calls = []

        def markdown(self, value, **kwargs):
            self.markdown_calls.append((value, kwargs))

    fake_st = FakeStreamlit()
    monkeypatch.setattr(web_app, "st", fake_st)
    monkeypatch.setattr(web_app, "_settings", lambda: SimpleNamespace(local_timezone="Europe/Madrid"))
    monkeypatch.setattr(web_app, "_store", lambda: object())
    monkeypatch.setattr(web_app, "BrokerClientFactory", lambda _settings: FakeBroker())
    monkeypatch.setattr(web_app, "opening_performance_context", lambda *args, **kwargs: {})

    web_app.page_kindle()

    assert calls == ["snapshot", ("2W", "15Min")]
    assert len(fake_st.markdown_calls) == 1
    assert "kindle_server" not in inspect.getsource(web_app)
    assert "publish_kindle_snapshot" not in inspect.getsource(web_app)
