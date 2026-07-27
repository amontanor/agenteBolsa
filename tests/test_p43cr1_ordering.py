from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import agente_bolsa.scheduler as scheduler


def _evidence() -> dict:
    return {
        "policy_version": "time_stop_xnys.v1",
        "active_policy_version": "legacy.v1",
        "legacy_eligible": True,
        "legacy_calendar_elapsed_days": 5,
        "legacy_return_condition_met": True,
        "xnys_eligible": False,
        "comparison_status": "legacy_only",
        "required_xnys_sessions": 5,
        "completed_sessions": 0,
        "fill_authority": "first_fill_at",
        "fill_timestamp": "2026-07-15T13:30:00+00:00",
        "shadow_only": True,
        "shadow_authority": "time_stop_xnys.v1",
    }


def _lot() -> dict:
    return {
        "broker_order_id": "buy-order-1",
        "order_plan_id": "buy-plan",
        "source_plan_id": "buy-plan",
        "entry_fill_at": "2026-07-15T13:30:00+00:00",
        "fill_authority": "first_fill_at",
        "open_qty": 2.0,
    }


class _Store:
    def __init__(
        self,
        calls: list[str],
        *,
        save_error: BaseException | None = None,
        persist_error: BaseException | None = None,
    ) -> None:
        self.calls = calls
        self.save_error = save_error
        self.persist_error = persist_error
        self.links: list[dict] = []

    def latest_executed_buy_plans_by_symbol(self):
        return {
            "AAPL": {
                "plan": {
                    "plan_id": "buy-plan",
                    "payload": {"stop_loss": 90.0, "take_profit": 200.0},
                }
            }
        }

    def executed_open_buy_lots_by_symbol(self, *, position_quantities):
        return {"AAPL": [_lot()]}

    def get_runtime_value(self, _key):
        return {}

    def set_runtime_value(self, *_args):
        return None

    def save_broker_order(self, **_kwargs):
        self.calls.append("save_broker_order")
        if self.save_error is not None:
            raise self.save_error

    def record_time_stop_exit_authority(self, _capture, link, **_kwargs):
        self.calls.append("persist_time_stop_exit_authority")
        self.links.append(link)
        if self.persist_error is not None:
            raise self.persist_error
        return {"status": "inserted"}


def _run_exit(monkeypatch, store: _Store, submit_result):
    position = SimpleNamespace(
        symbol="AAPL",
        qty=2.0,
        current_price=95.0,
        market_value=190.0,
        avg_entry_price=100.0,
        unrealized_plpc=-0.05,
        side="long",
    )
    portfolio = SimpleNamespace(open_orders=[], positions=[position])
    settings = SimpleNamespace(
        auto_paper_trading=True,
        require_human_approval=False,
        trading_mode="paper",
        alpaca_paper=True,
        allow_live_trading=False,
    )
    reporter = SimpleNamespace(emit=lambda *_args, **_kwargs: None)

    monkeypatch.setattr(
        scheduler,
        "_exit_policy_v2_runtime_trigger",
        lambda *_args, **_kwargs: {
            "trigger": "time_stop_v2",
            "level": 95.0,
            "qty_fraction": 1.0,
            "state_key": None,
            "time_stop_evidence": _evidence(),
        },
    )

    def submit(_settings, _plan, *, client_order_id):
        store.calls.append("submit")
        return submit_result(client_order_id)

    monkeypatch.setattr(scheduler, "submit_paper_order_plan", submit)
    return scheduler._execute_stop_take_exits(
        settings,
        store,
        reporter,
        "watch-1",
        portfolio,
        evaluation_at=datetime.fromisoformat("2026-07-22T13:30:00+00:00"),
    )


def _successful_order(client_order_id: str) -> dict:
    return {
        "id": "sell-order-1",
        "client_order_id": client_order_id,
        "status": "accepted",
        "submitted_at": "2026-07-22T13:30:01+00:00",
    }


def test_broker_order_is_saved_before_p43c_telemetry(monkeypatch) -> None:
    calls: list[str] = []
    store = _Store(calls)
    _run_exit(monkeypatch, store, _successful_order)
    assert calls == ["submit", "save_broker_order", "persist_time_stop_exit_authority"]


def test_p43c_failure_after_save_keeps_active_order_result(monkeypatch) -> None:
    calls: list[str] = []
    store = _Store(calls, persist_error=RuntimeError("telemetry unavailable"))
    exits = _run_exit(monkeypatch, store, _successful_order)
    assert exits[0]["status"] == "accepted"
    assert "error" not in exits[0]
    assert calls == ["submit", "save_broker_order", "persist_time_stop_exit_authority"]


def test_save_failure_does_not_persist_a_durable_p43c_link(monkeypatch) -> None:
    calls: list[str] = []
    store = _Store(calls, save_error=RuntimeError("local broker order unavailable"))
    exits = _run_exit(monkeypatch, store, _successful_order)
    assert "error" in exits[0]
    assert calls == ["submit", "save_broker_order"]
    assert store.links == []


def test_submit_exception_keeps_failed_link_without_broker_order_id(monkeypatch) -> None:
    calls: list[str] = []
    store = _Store(calls)

    def submit_failure(_client_order_id: str):
        raise RuntimeError("submit unavailable")

    exits = _run_exit(monkeypatch, store, submit_failure)
    assert "error" in exits[0]
    assert calls == ["submit", "persist_time_stop_exit_authority"]
    assert store.links[0]["submission_status"] == "failed"
    assert store.links[0]["broker_order_id"] is None
