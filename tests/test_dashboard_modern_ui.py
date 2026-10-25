"""Real Streamlit render against blocked synthetic providers and temporary data."""

import sys
from threading import Event

import pytest
from streamlit.testing.v1 import AppTest
from test_dashboard_modern_port import install_broker, portfolio, settings_for

from agente_bolsa import dashboard_loading as loading
from agente_bolsa import web_app


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    attempts = []
    def forbidden(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("Network prohibited")
    monkeypatch.setattr("socket.create_connection", forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.setattr("curl_cffi.requests.Session.request", forbidden)
    monkeypatch.setattr("yfinance.download", forbidden)
    loading.reset_remote_state()
    yield
    loading.reset_remote_state()
    assert not attempts, "A swallowed exception must not hide attempted network"


@pytest.mark.parametrize("cached", [False, True])
def test_dashboard_renders_before_account_provider_finishes(monkeypatch, tmp_path, cached):
    settings = settings_for(tmp_path)
    monkeypatch.setattr(web_app, "_settings", lambda: settings)
    monkeypatch.setattr(web_app, "_cached_market_status", lambda: {"is_open": False})
    def forbidden_cleanup(*args, **kwargs):
        raise AssertionError("Retention must not run during dashboard render")
    monkeypatch.setattr(web_app, "cleanup_runtime_data", forbidden_cleanup)
    if cached:
        seed = loading.DashboardLoadState(market_open=lambda _: False)
        seed._wire(settings)
        seed.repository.ensure_schema()
        seed._publish(loading.REMOTE_PORTFOLIO,
                      {"value": portfolio(), "observed_at": "2026-10-23T10:00:00+00:00"})
    release, entered = Event(), Event()
    install_broker(monkeypatch, release, entered)
    app = AppTest.from_string(
        "from agente_bolsa.web_app import page_dashboard, _render_refreshable_page\n_render_refreshable_page(page_dashboard, 0)", default_timeout=10)
    state = None
    try:
        app.run()
        assert not app.exception
        assert entered.wait(5)
        assert not release.is_set()
        state = app.session_state["dashboard_load_state"]
        if cached:
            assert state.data["portfolio"] == portfolio()
            assert "2026-10-23" in " ".join(item.value for item in app.caption)
        else:
            assert any("segundo plano" in item.value for item in app.info)
            assert state._portfolio() is None
    finally:
        release.set()
        if state:
            state.wait(timeout=5)


@pytest.fixture(autouse=True)
def restore_main_after_apptest():
    """Streamlit replaces __main__; preserve the caller for Windows spawn."""
    original_main = sys.modules["__main__"]
    try:
        yield
    finally:
        sys.modules["__main__"] = original_main
