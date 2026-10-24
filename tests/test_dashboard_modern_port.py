"""Modern field parity and bounded, offline dashboard publication."""

from concurrent.futures import Future
from datetime import datetime, timezone
from threading import Event

import pytest

from agente_bolsa import dashboard_loading as loading
from agente_bolsa.config import Settings
from agente_bolsa.dashboard_broker import DashboardBroker, _decode_activity_page
from agente_bolsa.dashboard_snapshot import SnapshotRepository
from agente_bolsa.models import PortfolioSnapshot, PositionSnapshot
from agente_bolsa.storage import Store


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network prohibited")
    monkeypatch.setattr("socket.create_connection", forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)
    loading.reset_remote_state()
    yield
    loading.reset_remote_state()


def settings_for(tmp_path):
    settings = Settings(DATA_DIR=tmp_path, _env_file=None)
    Store(settings.database_path, settings.agent_logs_dir).ensure_schema()
    return settings


def portfolio():
    return PortfolioSnapshot(
        account_id="synthetic", status="ACTIVE", currency="USD", cash=80,
        portfolio_value=100, buying_power=80, previous_close_equity=95,
        positions=[PositionSnapshot("TEST", 1, 20, 18, 20, 2, .11,
                                    unrealized_intraday_pl=1, unrealized_intraday_plpc=.05)],
        open_orders=[],
    )


def install_broker(monkeypatch, release=None, entered=None):
    calls = []

    class Broker:
        def __init__(self, settings):
            pass

        def alpaca_portfolio_snapshot(self):
            calls.append("portfolio")
            if entered:
                entered.set()
            if release:
                assert release.wait(10)
            return portfolio()

        def alpaca_trade_activities(self, **kwargs):
            calls.append("fills")
            return []

        def alpaca_portfolio_history(self, **kwargs):
            calls.append(kwargs["timeframe"])
            return {"equity": [95, 100], "timeframe": kwargs["timeframe"]}

    monkeypatch.setattr(loading, "BrokerClientFactory", Broker)
    monkeypatch.setattr(loading, "DashboardBroker", Broker)
    return calls


def test_cold_update_returns_before_provider_and_preserves_modern_fields(monkeypatch, tmp_path):
    settings = settings_for(tmp_path)
    release, entered = Event(), Event()
    calls = install_broker(monkeypatch, release, entered)
    state = loading.DashboardLoadState(market_open=lambda _: False)
    try:
        assert state.update(settings, 2)
        assert entered.wait(5)
        assert state._portfolio() is None
        assert not release.is_set()  # update did not wait for the provider
    finally:
        release.set()
        state.wait(timeout=5)
    assert state.data["portfolio"] == portfolio()
    assert state.data["history"]["open_positions"][0]["unrealized_intraday_pl"] == 1
    assert state.data["portfolio_history"]["timeframe"] == "1D"
    assert state.data["intraday_portfolio_history"]["timeframe"] == "15Min"
    assert sorted(calls) == ["15Min", "1D", "fills", "portfolio"]
    restored = loading.DashboardLoadState(market_open=lambda _: False)
    restored._wire(settings)
    assert restored.hydrate()
    assert restored.data["portfolio"] == portfolio()
    assert restored.data["intraday_portfolio_history"]["timeframe"] == "15Min"


def test_portfolio_published_while_fills_and_curves_still_pending(monkeypatch, tmp_path):
    settings = settings_for(tmp_path)
    state = loading.DashboardLoadState(market_open=lambda _: True)
    state._wire(settings)
    state.repository.ensure_schema()
    state.futures = {resource: Future() for resource in loading.REMOTE_RESOURCES}
    state.futures[loading.REMOTE_PORTFOLIO].set_result({"value": portfolio()})
    assert state._collect()
    assert state.data["portfolio"] == portfolio()
    assert len(state.data["history"]["open_positions"]) == 1
    assert state.data["fills_count"] is None
    assert state.data["fills_coverage"]["status"] != "complete"
    assert state.loading


def test_budget_discards_late_result_without_replacing_cached_account(tmp_path):
    settings = settings_for(tmp_path)
    now = [100.0]
    state = loading.DashboardLoadState(clock=lambda: now[0], market_open=lambda _: True)
    state._wire(settings)
    state.repository.ensure_schema()
    state._publish(loading.REMOTE_PORTFOLIO, {"value": portfolio()})
    future = Future()
    state.futures[loading.REMOTE_PORTFOLIO] = future
    state._attempt_started[loading.REMOTE_PORTFOLIO] = 100
    state._generation[loading.REMOTE_PORTFOLIO] = 1
    now[0] = 111
    assert state._expire_budgets(now[0])
    future.set_result({"value": None, "generation": 1})
    state._collect()
    assert state.data["portfolio"] == portfolio()
    assert state.stale_results == 1
    assert state.degraded[loading.REMOTE_PORTFOLIO]
    assert state._transport_report()["portfolio_sdk_timeout"] == "unavailable"


def test_cadences_do_not_follow_ui_poll_interval(monkeypatch, tmp_path):
    settings = settings_for(tmp_path)
    calls = install_broker(monkeypatch)
    now = [100.0]
    state = loading.DashboardLoadState(clock=lambda: now[0], market_open=lambda _: True)
    state.update(settings, 2)
    state.wait(timeout=5)
    assert len(calls) == 4
    now[0] += 29
    assert state.update(settings, 2) is False
    now[0] += 2
    assert state.update(settings, 2)
    state.wait(timeout=5)
    assert calls.count("portfolio") == 2
    assert calls.count("fills") == 1
    assert calls.count("1D") == calls.count("15Min") == 1


def test_global_queue_bounded_and_identical_reads_shared():
    release = Event()
    def work():
        assert release.wait(10)
        return {}
    futures = []
    try:
        first, created = loading.submit_remote("account", "resource", work)
        futures.append(first)
        same, created_again = loading.submit_remote("account", "resource", work)
        assert created and not created_again and same is first
        for i in range(20):
            future, _ = loading.submit_remote(str(i), "resource", work)
            if future:
                futures.append(future)
        assert len(loading.inflight_keys()) == len(loading.REMOTE_RESOURCES)
    finally:
        release.set()
        for future in futures:
            future.result(timeout=5)


@pytest.mark.parametrize("payload", [["invalid"], {"items": ["invalid"]}, {"items": [{}]}, {}])
def test_malformed_page_is_not_empty_history(payload):
    with pytest.raises(ValueError):
        _decode_activity_page(payload)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_transport_timeout_rejected(tmp_path, timeout):
    with pytest.raises(ValueError):
        DashboardBroker(settings_for(tmp_path), read_timeout=timeout)


def test_fresh_hydration_reuses_cadence_without_remote_read(monkeypatch, tmp_path):
    settings = settings_for(tmp_path)
    state = loading.DashboardLoadState(market_open=lambda _: False)
    state._wire(settings)
    state.repository.ensure_schema()
    observed = datetime.now(timezone.utc).isoformat()
    state._publish(loading.REMOTE_PORTFOLIO, {"value": portfolio(), "observed_at": observed})
    for resource in (loading.REMOTE_FILLS, loading.REMOTE_CURVE, loading.REMOTE_INTRADAY):
        state._publish(resource, {"value": [] if resource == "fills" else {}, "observed_at": observed})
    restored = loading.DashboardLoadState(market_open=lambda _: False)
    calls = install_broker(monkeypatch)
    restored.update(settings, 2)
    assert calls == []
    assert restored.data["portfolio"] == portfolio()


def test_snapshot_reads_are_query_only(tmp_path):
    repo = SnapshotRepository(tmp_path / "cache.sqlite3")
    repo.ensure_schema()
    connection = repo.read_connection()
    try:
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
    finally:
        connection.close()


def test_conflicting_duplicate_activity_is_rejected(monkeypatch, tmp_path):
    from agente_bolsa import dashboard_broker
    payload = [{"id": "same", "qty": "1"}, {"id": "same", "qty": "2"}]
    monkeypatch.setattr(dashboard_broker, "_read_activity_page", lambda *args: (payload, None))
    with pytest.raises(ValueError, match="contenido distinto"):
        DashboardBroker(settings_for(tmp_path)).alpaca_trade_activities_page()
