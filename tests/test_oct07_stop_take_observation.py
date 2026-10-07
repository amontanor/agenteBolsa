from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agente_bolsa.config import Settings
from agente_bolsa import scheduler


class Store:
    def __init__(self, source=None):
        self.source = source or {}
        self.reads = 0

    def latest_executed_buy_plans_by_symbol(self):
        self.reads += 1
        return self.source

    def executed_open_buy_lots_by_symbol(self, **kwargs):
        return {}


class Reporter:
    def emit(self, *args, **kwargs):
        raise AssertionError("No exit event expected")


def portfolio(*, order=False):
    return SimpleNamespace(
        positions=[SimpleNamespace(symbol="APO", qty=7, current_price=115, market_value=805)],
        open_orders=[SimpleNamespace(symbol="APO")] if order else [],
    )


def run(tmp_path, monkeypatch, store, snapshot, observation):
    monkeypatch.setattr(scheduler, "_exit_policy_v2_runtime_trigger", lambda *a, **kw: None)
    settings = Settings(_env_file=None, DATA_DIR=tmp_path, AUTO_PAPER_TRADING=True,
                        REQUIRE_HUMAN_APPROVAL=False, ALLOW_LIVE_TRADING=False,
                        TRADING_MODE="paper", ALPACA_PAPER=True)
    return scheduler._execute_stop_take_exits(
        settings, store, Reporter(), "watch-exact", snapshot,
        evaluation_at=datetime(2026, 10, 7, 18, 0, tzinfo=timezone.utc),
        observation=observation,
    )


@pytest.mark.parametrize("order,source,expected", [
    (False, {}, "source_unavailable"),
    (True, {}, "skipped_open_order"),
    (False, {"APO": {"plan": {"payload": {"stop_loss": 90, "take_profit": 160}}}}, "local_levels_available"),
    (False, {"APO": {"plan": {"payload": {}}}}, "local_levels_absent"),
])
def test_observation_explains_silent_skip_without_claiming_broker_protection(tmp_path, monkeypatch, order, source, expected):
    store = Store(source)
    audit = {}
    assert run(tmp_path, monkeypatch, store, portfolio(order=order), audit) == []
    assert store.reads == 1
    assert audit["positions"][0]["status"] == expected
    assert audit["positions"][0]["broker_protection_status"] == "unavailable"
    assert audit["source_lookup_basis"] == "legacy_latest_registered_buy_by_symbol"
    assert "plan_id" not in audit["positions"][0]


def test_observation_failure_does_not_change_exit_path(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("audit_unavailable")
    monkeypatch.setattr(scheduler, "_stop_take_observation", fail)
    store = Store()
    audit = {}
    assert run(tmp_path, monkeypatch, store, portfolio(), audit) == []
    assert audit["status"] == "unavailable"
    assert audit["reason"] == "RuntimeError"


def test_disabled_exits_do_not_read_source_and_remain_not_evaluated(tmp_path):
    store = Store()
    audit = {}
    settings = Settings(_env_file=None, DATA_DIR=tmp_path, AUTO_PAPER_TRADING=False)
    assert scheduler._execute_stop_take_exits(settings, store, Reporter(), "watch", portfolio(), observation=audit) == []
    assert store.reads == 0
    assert audit["status"] == "not_evaluated"
