from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agente_bolsa import scheduler
from agente_bolsa.config import Settings
from agente_bolsa.storage import Store as SQLiteStore


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


def test_triggered_stop_preserves_submission_when_audit_fails(tmp_path, monkeypatch):
    from agente_bolsa.tools import exit_lot_provenance

    class FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 7, 18, 0, tzinfo=timezone.utc)

    def run_mode(mode):
        with monkeypatch.context() as patch:
            patch.setattr(scheduler, "datetime", FrozenClock)
            patch.setattr(exit_lot_provenance, "datetime", FrozenClock)
            patch.setattr(scheduler, "new_id", lambda prefix: f"{prefix}_exact")
            settings = Settings(_env_file=None, DATA_DIR=tmp_path / mode,
                                AUTO_PAPER_TRADING=True, REQUIRE_HUMAN_APPROVAL=False,
                                TRADING_MODE="paper", ALPACA_PAPER=True, ALLOW_LIVE_TRADING=False)
            store = SQLiteStore(settings.database_path, settings.agent_logs_dir)
            store.ensure_schema()
            patch.setattr(store, "executed_open_buy_lots_by_symbol", lambda **kwargs: {})
            store.save_broker_order(broker_order_id="buy-exact", plan_id="plan-source", cycle_id="buy-cycle",
                                    symbol="APO", side="buy", status="filled", payload={
                "plan": {"plan_id": "plan-source", "payload": {"stop_loss": 120, "take_profit": 160}},
                "broker_order": {"id": "buy-exact", "qty": 7, "filled_qty": 7},
            })
            submitted, events = [], []

            def submit(_settings, plan, *, client_order_id):
                submitted.append((plan, client_order_id))
                return {"id": "sell-exact", "status": "accepted"}

            class Capture:
                def emit(self, *args, **kwargs):
                    events.append((args, kwargs))

            if mode == "failed":
                def fail(*args, **kwargs):
                    raise RuntimeError("audit_unavailable")
                patch.setattr(scheduler, "_stop_take_observation", fail)
            patch.setattr(scheduler, "submit_paper_order_plan", submit)
            audit = None if mode == "legacy" else {}
            result = scheduler._execute_stop_take_exits(
                settings, store, Capture(), "watch-exact", portfolio(), observation=audit,
                evaluation_at=datetime(2026, 10, 7, 18, 0, tzinfo=timezone.utc),
            )
            assert len(submitted) == 1
            assert result[0]["trigger"] == "stop_loss"
            if mode == "failed":
                assert audit["status"] == "unavailable"
            return submitted, result, events
    results = [run_mode(mode) for mode in ("legacy", "normal", "failed")]
    assert results[0] == results[1] == results[2]


@pytest.mark.parametrize("value", [True, "bad", float("nan"), float("inf")])
def test_invalid_level_is_unavailable_and_inputs_are_unchanged(value):
    snapshot = portfolio()
    source = {"APO": {"plan": {"payload": {"stop_loss": value, "take_profit": 160}}}}
    audit = scheduler._stop_take_observation(snapshot, source)
    assert audit["positions"][0]["status"] == "levels_unavailable"
    assert audit["positions"][0]["stop_loss"] is None
    assert source["APO"]["plan"]["payload"]["stop_loss"] is value
    assert snapshot.positions[0].qty == 7


@pytest.mark.parametrize("snapshot_state,expected", [("error", "unavailable"), ("empty", "not_required"), ("orphan", "observed")])
def test_watch_publishes_observation_in_existing_event_only(tmp_path, monkeypatch, snapshot_state, expected):
    status = SimpleNamespace(is_open=True, session_date="2026-10-07", as_dict=lambda: {"is_open": True})
    monkeypatch.setattr(scheduler, "MarketCalendar", lambda *args: SimpleNamespace(status=lambda: status))
    monkeypatch.setattr(scheduler, "_check_kernel_integrity_once_per_session", lambda *args: None)
    monkeypatch.setattr(scheduler, "_set_job_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(scheduler, "_earnings_hold_guard", lambda *args: None)
    monkeypatch.setattr(scheduler, "_run_open_position_news_guard", lambda *args: None)
    monkeypatch.setattr(scheduler, "read_session_open_snapshots", lambda *args: [{"session_date": "2026-10-07"}])
    events, broker_reads = [], []

    class Capture:
        def emit(self, *args, **kwargs):
            events.append(args)

    def snapshot():
        broker_reads.append(1)
        if snapshot_state == "error":
            raise RuntimeError("snapshot_unavailable")
        value = portfolio()
        if snapshot_state == "empty":
            value.positions = []
        value.cash, value.portfolio_value = 10000, 10805
        return value

    monkeypatch.setattr(scheduler, "BrokerClientFactory", lambda *args: SimpleNamespace(alpaca_portfolio_snapshot=snapshot))
    monkeypatch.setattr(scheduler, "_reporter", lambda *args: Capture())
    store = Store()
    store.set_runtime_value = lambda *args: None
    settings = Settings(_env_file=None, DATA_DIR=tmp_path, AUTO_PAPER_TRADING=True,
                        REQUIRE_HUMAN_APPROVAL=False, ALLOW_LIVE_TRADING=False)
    scheduler.portfolio_watch_job(settings, store)
    completed = [event for event in events if event[1] in {"portfolio_watch_completed", "portfolio_watch_heartbeat_completed"}]
    assert len(completed) == 1
    assert completed[0][4]["stop_take_observation"]["status"] == expected
    assert len(broker_reads) == 1
    assert store.reads == (1 if snapshot_state == "orphan" else 0)
