from concurrent.futures import Future
from threading import Barrier, Event

from agente_bolsa import dashboard_loading as loading
from agente_bolsa.config import Settings
from agente_bolsa.models import PortfolioSnapshot
from agente_bolsa.storage import Store
from agente_bolsa.tools.trade_history import build_trade_history


def portfolio():
    return PortfolioSnapshot(
        account_id="test", status="ACTIVE", currency="USD", cash=100,
        portfolio_value=100, buying_power=100, positions=[], open_orders=[],
    )


def settings_for(tmp_path):
    settings = Settings(DATA_DIR=tmp_path, _env_file=None)
    Store(settings.database_path, settings.agent_logs_dir).ensure_schema()
    return settings


def test_dashboard_reads_run_concurrently_and_reuse_portfolio(monkeypatch, tmp_path):
    barrier = Barrier(3, timeout=5)
    calls = []
    snapshot = portfolio()

    class Broker:
        def __init__(self, settings):
            pass

        def alpaca_portfolio_snapshot(self):
            calls.append("portfolio")
            barrier.wait()
            return snapshot

        def alpaca_trade_activities(self, **kwargs):
            calls.append("fills")
            barrier.wait()
            return []

        def alpaca_portfolio_history(self, **kwargs):
            calls.append("chart")
            barrier.wait()
            return {"equity": [100]}

    monkeypatch.setattr(loading, "BrokerClientFactory", Broker)
    result = loading.load_dashboard_data(settings_for(tmp_path))
    assert sorted(calls) == ["chart", "fills", "portfolio"]
    assert result["portfolio"] is snapshot
    assert result["history"]["current_statistics"]["equity"] == 100
    assert result["errors"] == []


def test_supplied_empty_fills_does_not_trigger_any_network_read(monkeypatch, tmp_path):
    def unexpected(*args, **kwargs):
        raise AssertionError("Network should not be used")

    monkeypatch.setattr(loading.BrokerClientFactory, "alpaca_portfolio_snapshot", unexpected)
    monkeypatch.setattr(loading.BrokerClientFactory, "alpaca_trade_activities", unexpected)
    result = build_trade_history(settings_for(tmp_path), portfolio=portfolio(), fills=[])
    assert result["summary"]["fills"] == 0
    assert result["warnings"] == []


def test_loading_is_nonblocking_and_only_one_job_runs(monkeypatch):
    entered, release = Event(), Event()
    calls = []

    def slow_read(settings, progress=None):
        calls.append(settings)
        entered.set()
        assert release.wait(5)
        return {"portfolio": portfolio(), "errors": []}

    monkeypatch.setattr(loading, "load_dashboard_data", slow_read)
    state = loading.DashboardLoadState()
    try:
        assert state.update("settings", 30)
        assert entered.wait(2)
        for _ in range(10):
            assert not state.update("settings", 30)
        assert state.loading
        assert calls == ["settings"]
    finally:
        release.set()
        state.future.result(timeout=5)
    assert state.update("settings", 30)
    assert not state.loading
    assert not state.update("settings", 30)
    assert state.data["portfolio"].account_id == "test"


def test_refresh_failure_keeps_last_portfolio_and_disabled_refresh_keeps_cache(monkeypatch):
    state = loading.DashboardLoadState()
    original = {"portfolio": portfolio(), "errors": [], "fetched_at": "earlier"}
    state.data = original
    state.completed_at = 0
    assert not state.update(None, float("inf"))
    state.future = Future()
    state.future.set_result({"portfolio": None, "errors": ["Alpaca unavailable"]})
    assert state.update(None, 30)
    assert state.data is original
    assert state.errors == ["Alpaca unavailable"]
    assert not state.update(None, 30)
    monkeypatch.setattr(loading, "load_dashboard_data", lambda settings, progress=None: original)
    state.refresh_requested = True
    assert state.update(None, float("inf"))
    state.future.result(timeout=5)
    assert state.update(None, float("inf"))


def test_failed_fills_does_not_make_a_second_request_or_invent_pl(monkeypatch, tmp_path):
    class Broker:
        def __init__(self, settings):
            pass

        def alpaca_portfolio_snapshot(self):
            return portfolio()

        def alpaca_trade_activities(self, **kwargs):
            raise RuntimeError("timeout")

        def alpaca_portfolio_history(self, **kwargs):
            return {}

    monkeypatch.setattr(loading, "BrokerClientFactory", Broker)
    result = loading.load_dashboard_data(settings_for(tmp_path))
    assert result["portfolio"] is not None
    assert result["history"] == {}
    assert result["errors"] == ["fills: timeout"]
