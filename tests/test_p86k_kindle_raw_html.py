from __future__ import annotations

import asyncio
import inspect

from agente_bolsa import web_app


class _Request:
    def __init__(self, view: str | None = None):
        self.query_params = {} if view is None else {"view": view}


def _model() -> dict:
    return {
        "daily": {"amount": 1.69, "pct": 0.0000239, "status": "available"},
        "spy": {"pct": None, "status": "unavailable", "reason": "not_comparable"},
        "positions": [
            {
                "symbol": "<AAPL>",
                "qty": 2,
                "entry": 100,
                "current": 101,
                "total_pl_pct": 0.01,
                "today_pl_pct": -0.002,
            }
        ],
        "as_of": "2026-08-06T12:00:00+00:00",
        "as_of_label": "06/08/2026 14:00 CEST",
    }


def test_streamlit_app_declares_clean_raw_kindle_route_without_menu_change():
    source = inspect.getsource(web_app)
    assert "st.App" in source
    assert 'Route("/kindle"' in source
    assert "_kindle_raw_route" in source
    assert 'url_path="kindle"' in inspect.getsource(web_app.main)
    assert 'visibility="hidden"' in inspect.getsource(web_app.main)


def test_loading_response_is_raw_html_and_refreshes_to_loaded_view():
    response = asyncio.run(web_app._kindle_raw_route(_Request()))
    body = response.body.decode("utf-8")
    assert response.media_type == "text/html"
    assert "Cargando..." in body
    assert 'http-equiv="refresh"' in body
    assert "view=loaded" in body
    assert "streamlit" not in body.lower()


def test_loaded_response_has_300_second_refresh_and_only_requested_position_columns(monkeypatch):
    monkeypatch.setattr(web_app, "_kindle_raw_model", lambda: _model())
    response = asyncio.run(web_app._kindle_raw_route(_Request("loaded")))
    body = response.body.decode("utf-8")
    assert response.media_type == "text/html"
    assert 'content="300;url=/kindle"' in body
    assert "Cargando..." not in body
    assert "Cantidad" not in body
    assert all(label in body for label in ("Accion", "Entrada", "Actual", "P/L total", "P/L hoy"))
    assert "&lt;AAPL&gt;" in body
    assert "<script" not in body.lower()
    assert "https://" not in body


def test_loaded_route_keeps_spy_unavailable_without_exact_comparable_carrier(monkeypatch):
    model = _model()
    model["spy"] = {"pct": 0.01, "status": "comparable"}
    monkeypatch.setattr(web_app, "_kindle_raw_model", lambda: model)
    response = asyncio.run(web_app._kindle_raw_route(_Request("loaded")))
    body = response.body.decode("utf-8")
    assert "SPY: n/d" in body or "n/d" in body


def test_raw_model_uses_one_snapshot_and_no_store_or_history(monkeypatch):
    calls = []

    class FakeBroker:
        def alpaca_portfolio_snapshot(self):
            calls.append("snapshot")
            return None

    monkeypatch.setattr(web_app, "_settings", lambda: object())
    monkeypatch.setattr(web_app, "BrokerClientFactory", lambda _settings: FakeBroker())
    monkeypatch.setattr(web_app, "_store", lambda: (_ for _ in ()).throw(AssertionError("store")))
    model = web_app._kindle_raw_model()
    assert calls == ["snapshot"]
    assert model["spy"]["status"] == "unavailable"


def test_loaded_html_preserves_as_of_and_n_d_for_missing_values():
    model = _model()
    model["daily"] = {"amount": None, "pct": None, "status": "unavailable"}
    model["positions"] = []
    html = web_app._kindle_loaded_html(model)
    assert "06/08/2026 14:00 CEST" in html
    assert "n/d" in html
    assert "sin posiciones" in html
