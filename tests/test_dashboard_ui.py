"""Exercise Streamlit's real rendering with a deliberately stalled broker."""

from threading import Event

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from agente_bolsa import dashboard_loading, web_app
from agente_bolsa.tools.trade_history import build_trade_history
from test_dashboard_loading import portfolio, settings_for


def test_dashboard_shows_local_content_during_loading_then_keeps_cached_data(monkeypatch, tmp_path):
    settings = settings_for(tmp_path)
    entered, publish_portfolio, published, release = Event(), Event(), Event(), Event()
    calls = []
    snapshot = portfolio()

    def slow_load(settings, progress=None):
        calls.append("load")
        entered.set()
        assert publish_portfolio.wait(10)
        if progress is not None:
            progress.set_result({
                "portfolio": snapshot, "history": {}, "portfolio_history": {},
                "fetched_at": "2026-10-05T10:00:00+00:00", "timings": {},
            })
        published.set()
        assert release.wait(10)
        return {
            "portfolio": snapshot,
            "history": build_trade_history(settings, portfolio=snapshot, fills=[]),
            "portfolio_history": {}, "errors": [], "timings": {"total": 2},
            "fetched_at": "2026-10-05T10:00:00+00:00",
        }

    monkeypatch.setattr(web_app, "_settings", lambda: settings)
    monkeypatch.setattr(web_app, "_load_web_preferences", lambda: {"refresh_interval_seconds": 0})
    monkeypatch.setattr(web_app, "_save_web_preferences", lambda preferences: None)
    monkeypatch.setattr(dashboard_loading, "load_dashboard_data", slow_load)
    app = AppTest.from_string("from agente_bolsa.web_app import main\nmain()", default_timeout=10)
    try:
        app.run()
        assert entered.wait(2)
        assert not app.exception
        assert app.title[0].value == "Resumen operativo"
        assert any("segundo plano" in info.value for info in app.info)
        assert calls == ["load"]
        app.run()
        assert not app.exception
        assert calls == ["load"]
        publish_portfolio.set()
        assert published.wait(2)
        app.run()
        assert not app.exception
        assert any("Cartera recibida; cargando" in caption.value for caption in app.caption)
        assert app.session_state["dashboard_load"].loading
    finally:
        publish_portfolio.set()
        release.set()
        app.session_state["dashboard_load"].future.result(timeout=10)
    app.run()
    assert not app.exception
    assert any("Datos Alpaca:" in caption.value for caption in app.caption)
    # A chart range change reruns the app without reloading remote data.
    app.selectbox(key="portfolio_chart_days").set_value(15).run()
    assert not app.exception
    assert calls == ["load"]
    app.sidebar.button[0].click().run()
    assert not app.exception
    state = app.session_state["dashboard_load"]
    if state.future:
        state.future.result(timeout=10)
    app.run()
    assert not app.exception
    assert calls == ["load", "load"]
