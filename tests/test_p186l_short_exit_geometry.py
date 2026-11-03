"""P-L186L: short exits must use the short entry plan and valid geometry."""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agente_bolsa import cycle_runner, scheduler
from agente_bolsa.config import Settings
from agente_bolsa.tools import broker_reconciliation

EVALUATION_AT = datetime(2026, 11, 3, 15, 16, tzinfo=timezone.utc)

LEGACY_LONG_PLAN = {
    "created_at": "2026-09-02T14:12:18+00:00",
    "plan": {
        "plan_id": "plan_legacy_long",
        "payload": {"stop_loss": 79.1801, "take_profit": 92.5928},
    },
}

SHORT_ENTRY_PLAN = {
    "direction": "short",
    "position_effect": "open_short",
    "created_at": "2026-11-03T15:10:11+00:00",
    "plan": {
        "plan_id": "plan_short_adm",
        "payload": {"stop_loss": 76.7186, "take_profit": 67.1971},
    },
}


class _Store:
    def __init__(self, *, buy_plans=None, entry_plans=None):
        self.buy_plans = buy_plans or {}
        self.entry_plans = entry_plans or {}
        self.saved_orders = []
        self.saved_plans = []

    def latest_executed_buy_plans_by_symbol(self):
        return self.buy_plans

    def latest_entry_plans_by_symbol(self):
        return self.entry_plans

    def executed_open_buy_lots_by_symbol(self, **_kwargs):
        return {}

    def save_order_plan(self, **kwargs):
        self.saved_plans.append(kwargs)

    def save_broker_order(self, **kwargs):
        self.saved_orders.append(kwargs)

    def record_exit_lot_provenance(self, *_args, **_kwargs):
        return None

    def set_runtime_value(self, *_args, **_kwargs):
        return None

    def get_runtime_value(self, *_args, **_kwargs):
        return {}


class _Reporter:
    def __init__(self):
        self.events = []

    def emit(self, *args, **kwargs):
        self.events.append((args, kwargs))


def _settings(tmp_path):
    return Settings(
        _env_file=None,
        DATA_DIR=tmp_path,
        AUTO_PAPER_TRADING=True,
        REQUIRE_HUMAN_APPROVAL=False,
        TRADING_MODE="paper",
        ALPACA_PAPER=True,
        ALLOW_LIVE_TRADING=False,
    )


def _position(*, qty=-28.0, price=71.6, entry=72.91, side="short", symbol="ADM"):
    return SimpleNamespace(
        symbol=symbol,
        qty=qty,
        current_price=price,
        market_value=abs(qty * price),
        avg_entry_price=entry,
        side=side,
    )


def _portfolio(position):
    return SimpleNamespace(open_orders=[], positions=[position])


def _submit_capture(monkeypatch):
    submitted = []

    def fake_submit(_settings, plan, *, client_order_id):
        submitted.append(plan)
        return {"id": f"order-{len(submitted)}", "status": "accepted", "client_order_id": client_order_id}

    monkeypatch.setattr(scheduler, "submit_paper_order_plan", fake_submit)
    return submitted


def test_short_uses_its_own_entry_plan_not_legacy_long(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "_exit_policy_v2_runtime_trigger", lambda *_a, **_k: None)
    store = _Store(
        buy_plans={"ADM": LEGACY_LONG_PLAN},
        entry_plans={"ADM": SHORT_ENTRY_PLAN},
    )
    audit = {}
    exits = scheduler._execute_stop_take_exits(
        _settings(tmp_path),
        store,
        _Reporter(),
        "watch-p186l",
        _portfolio(_position()),
        evaluation_at=EVALUATION_AT,
        observation=audit,
    )
    assert exits == []
    assert audit["positions"][0]["take_profit"] == pytest.approx(67.1971)
    assert audit["positions"][0]["stop_loss"] == pytest.approx(76.7186)


def test_short_ignores_inverted_take_from_legacy_long_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "_exit_policy_v2_runtime_trigger", lambda *_a, **_k: None)
    store = _Store(buy_plans={"ADM": LEGACY_LONG_PLAN}, entry_plans={})
    exits = scheduler._execute_stop_take_exits(
        _settings(tmp_path),
        store,
        _Reporter(),
        "watch-p186l",
        _portfolio(_position()),
        evaluation_at=EVALUATION_AT,
        observation={},
    )
    assert exits == []


def test_short_take_triggers_with_correct_geometry(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "_exit_policy_v2_runtime_trigger", lambda *_a, **_k: None)
    submitted = _submit_capture(monkeypatch)
    exits = scheduler._execute_stop_take_exits(
        _settings(tmp_path),
        _Store(entry_plans={"ADM": SHORT_ENTRY_PLAN}),
        _Reporter(),
        "watch-p186l",
        _portfolio(_position(price=67.0)),
        evaluation_at=EVALUATION_AT,
        observation={},
    )
    assert exits[0]["trigger"] == "take_profit"
    assert exits[0]["level"] == pytest.approx(67.1971)
    assert submitted[0]["side"] == "buy"
    assert submitted[0]["payload"]["position_effect"] == "close_short"
    assert submitted[0]["payload"]["qty"] == pytest.approx(28.0)


def test_short_stop_triggers_with_correct_geometry(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "_exit_policy_v2_runtime_trigger", lambda *_a, **_k: None)
    submitted = _submit_capture(monkeypatch)
    exits = scheduler._execute_stop_take_exits(
        _settings(tmp_path),
        _Store(entry_plans={"ADM": SHORT_ENTRY_PLAN}),
        _Reporter(),
        "watch-p186l",
        _portfolio(_position(price=77.0)),
        evaluation_at=EVALUATION_AT,
        observation={},
    )
    assert exits[0]["trigger"] == "stop_loss"
    assert exits[0]["level"] == pytest.approx(76.7186)
    assert submitted[0]["payload"]["position_effect"] == "close_short"


def test_long_exit_keeps_legacy_buy_plan_behavior(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "_exit_policy_v2_runtime_trigger", lambda *_a, **_k: None)
    submitted = _submit_capture(monkeypatch)
    long_plan = {
        "created_at": "2026-11-03T15:10:11+00:00",
        "plan": {"plan_id": "plan_long", "payload": {"stop_loss": 90.0, "take_profit": 160.0}},
    }
    exits = scheduler._execute_stop_take_exits(
        _settings(tmp_path),
        _Store(buy_plans={"APO": long_plan}),
        _Reporter(),
        "watch-p186l",
        _portfolio(_position(symbol="APO", qty=7.0, price=85.0, entry=100.0, side="long")),
        evaluation_at=EVALUATION_AT,
        observation={},
    )
    assert exits[0]["trigger"] == "stop_loss"
    assert submitted[0]["side"] == "sell"
    assert submitted[0]["payload"]["position_effect"] == "close_long"


def test_reconcile_only_bootstraps_new_database():
    source = inspect.getsource(broker_reconciliation.reconcile_broker_orders)
    assert "if not settings.database_path.exists()" in source
    assert source.count("ensure_schema") == 1


COVER_SHORT_PLAN = {
    "created_at": "2026-11-03T15:16:35+00:00",
    "plan": {
        "plan_id": "plan_cover_short",
        "payload": {
            "position_effect": "close_short",
            "stop_loss": 79.1801,
            "take_profit": 92.5928,
        },
    },
}

LONG_ENTRY_PLAN = {
    "direction": "long",
    "created_at": "2026-11-03T15:20:00+00:00",
    "plan": {
        "plan_id": "plan_long_adm",
        "payload": {"stop_loss": 70.0, "take_profit": 85.0},
    },
}


def test_long_uses_long_entry_after_short_cover(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "_exit_policy_v2_runtime_trigger", lambda *_a, **_k: None)
    store = _Store(
        buy_plans={"ADM": COVER_SHORT_PLAN},
        entry_plans={"ADM": LONG_ENTRY_PLAN},
    )
    audit = {}
    exits = scheduler._execute_stop_take_exits(
        _settings(tmp_path),
        store,
        _Reporter(),
        "watch-p186l",
        _portfolio(_position(qty=10.0, price=78.0, entry=80.0, side="long")),
        evaluation_at=EVALUATION_AT,
        observation=audit,
    )
    assert exits == []
    assert audit["positions"][0]["stop_loss"] == pytest.approx(70.0)
    assert audit["positions"][0]["take_profit"] == pytest.approx(85.0)


def test_crew_success_is_not_downgraded_by_late_telemetry_failure():
    source = inspect.getsource(cycle_runner.run_observable_cycle)
    assert 'attempt_run.terminal == "succeeded"' in source
    assert "telemetry cannot fail a completed crew" in source


def test_long_ignores_cover_plan_without_long_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "_exit_policy_v2_runtime_trigger", lambda *_a, **_k: None)
    store = _Store(buy_plans={"ADM": COVER_SHORT_PLAN}, entry_plans={})
    exits = scheduler._execute_stop_take_exits(
        _settings(tmp_path),
        store,
        _Reporter(),
        "watch-p186l",
        _portfolio(_position(qty=10.0, price=78.0, entry=80.0, side="long")),
        evaluation_at=EVALUATION_AT,
        observation={},
    )
    assert exits == []
