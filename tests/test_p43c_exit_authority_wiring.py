from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier
from types import SimpleNamespace

import pytest

import agente_bolsa.scheduler as scheduler
from agente_bolsa.storage import Store
from agente_bolsa.tools.execution import build_market_order_request
from agente_bolsa.tools.time_stop_exit_authority import (
    SCHEMA_DECISION,
    SCHEMA_LINK,
    attach_time_stop_exit_authority_reference,
    build_time_stop_exit_authority_capture,
    build_time_stop_exit_order_link,
    content_hash,
    submit_with_time_stop_exit_authority,
    time_stop_exit_authority_digest,
)


def _evidence(
    *,
    legacy: bool | None = True,
    xnys: bool | None = False,
    comparison: str | None = "legacy_only",
) -> dict:
    return {
        "policy_version": "time_stop_xnys.v1",
        "legacy_eligible": legacy,
        "legacy_calendar_elapsed_days": 5,
        "legacy_return_condition_met": True,
        "xnys_eligible": xnys,
        "required_xnys_sessions": 5,
        "completed_sessions": 0,
        "comparison_status": comparison,
        "fill_authority": "first_fill_at",
        "fill_timestamp": "2026-07-15T13:30:00+00:00",
        "shadow_only": True,
        "shadow_authority": "time_stop_xnys.v1",
        "logical_eligibility_at": "2026-07-22T20:00:00+00:00",
        "first_actionable_market_time": "2026-07-23T13:30:00+00:00",
    }


def _lot(order_id: str, *, plan_id: str = "buy-plan") -> dict:
    return {
        "broker_order_id": order_id,
        "order_plan_id": plan_id,
        "source_plan_id": plan_id,
        "entry_fill_at": "2026-07-15T13:30:00+00:00",
        "fill_authority": "first_fill_at",
        "open_qty": 2.0,
    }


def _capture(**overrides: object) -> dict:
    values = {
        "cycle_id": "watch-1",
        "watch_id": "watch-1",
        "position_identity": "position-buy-1",
        "plan_id": "risk-exit-1",
        "symbol": "AAPL",
        "qty": 2.0,
        "trigger": "time_stop_v2",
        "time_stop_evidence": _evidence(),
        "lots": [_lot("buy-order-1")],
        "source_plan": {"plan_id": "buy-plan"},
        "decided_at": "2026-07-22T13:30:00+00:00",
        "captured_at": "2026-07-22T13:30:00.100000+00:00",
    }
    values.update(overrides)
    return build_time_stop_exit_authority_capture(**values)


def test_product_capture_hash_excludes_capture_time_and_contains_exact_identity() -> None:
    first = _capture(captured_at="2026-07-22T13:30:00.100000+00:00")
    second = _capture(captured_at="2026-07-22T13:31:00.100000+00:00")
    assert first["schema_version"] == SCHEMA_DECISION
    assert first["decision_id"] == second["decision_id"]
    assert first["content_hash"] == second["content_hash"]
    assert first["buy_broker_order_id"] == "buy-order-1"
    assert first["source_plan_id"] == "buy-plan"


def test_multi_lot_is_ambiguous_without_fifo_or_symbol_fallback() -> None:
    capture = _capture(lots=[_lot("buy-a", plan_id="plan-a"), _lot("buy-b", plan_id="plan-b")])
    assert capture["authority_status"] == "ambiguous"
    assert capture["buy_broker_order_id"] is None
    assert "multiple_open_lots_no_exact_allocation" in capture["reason_codes"]


def test_source_plan_context_mismatch_is_unavailable() -> None:
    capture = _capture(
        source_plan={"plan_id": "different-context-plan"},
    )
    assert capture["authority_status"] == "unavailable"
    assert "source_plan_context_mismatch" in capture["reason_codes"]


def test_xnys_shadow_does_not_authorize_an_exit() -> None:
    capture = _capture(
        time_stop_evidence=_evidence(legacy=False, xnys=True, comparison="xnys_only"),
    )
    assert capture["active_authority"] == "legacy_calendar_days"
    assert capture["active_eligible"] is False
    assert capture["shadow_only"] is True
    assert capture["authority_status"] == "not_generated"


def test_stop_and_take_are_not_time_stop_authority() -> None:
    capture = _capture(trigger="stop_loss")
    assert capture["authority_status"] == "not_applicable"
    assert capture["active_authority"] == "other"
    assert capture["buy_broker_order_id"] is None


def test_local_reference_does_not_change_execution_request() -> None:
    plan = {
        "plan_id": "entry-plan",
        "symbol": "AAPL",
        "side": "buy",
        "notional": 100.0,
        "payload": {"qty": 1.0, "entry_price": 100.0, "take_profit": 110.0, "stop_loss": 95.0},
    }
    capture = _capture()
    before = build_market_order_request(
        plan,
        client_order_id="client-entry",
        use_bracket_orders=False,
    )
    attach_time_stop_exit_authority_reference(plan, capture)
    after = build_market_order_request(
        plan,
        client_order_id="client-entry",
        use_bracket_orders=False,
    )
    assert before.model_dump() == after.model_dump()


def test_storage_persists_decision_and_link_once_and_preserves_conflict(tmp_path) -> None:
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    capture = _capture()
    link = build_time_stop_exit_order_link(
        capture,
        broker_order_id="sell-order-1",
        client_order_id="client-1",
        submitted_at="2026-07-22T13:30:01+00:00",
        completed_at=None,
        submission_status="filled",
        request_descriptor={"operation": "close_position", "symbol": "AAPL"},
        captured_at="2026-07-22T13:30:01.100000+00:00",
    )
    first = store.record_time_stop_exit_authority(capture, link, cycle_id="watch-1")
    second = store.record_time_stop_exit_authority(
        {**capture, "captured_at": "2026-07-22T13:31:00+00:00"},
        {**link, "captured_at": "2026-07-22T13:31:00+00:00"},
        cycle_id="watch-1",
    )
    conflict_capture = {**capture, "active_reason_code": "different_reason"}
    conflict_capture["content_hash"] = content_hash(conflict_capture)
    conflict = store.record_time_stop_exit_authority(
        conflict_capture,
        link,
        cycle_id="watch-1",
    )
    assert first["status"] == "inserted"
    assert second["status"] == "idempotent"
    assert conflict["status"] == "conflict"
    events = store.time_stop_exit_authority_events()
    assert sum(event["event_type"] == "time_stop_exit_authority" for event in events) == 1
    assert sum(event["event_type"] == "time_stop_exit_order_link" for event in events) == 1
    assert sum(event["event_type"].endswith("_conflict") for event in events) == 1
    report = time_stop_exit_authority_digest(store)
    assert report["canonical_decisions"] == 1
    assert report["linked_orders"] == 1
    assert report["conflicts"] == 1


def test_storage_concurrent_retry_is_inserted_then_idempotent(tmp_path) -> None:
    store = Store(tmp_path / "concurrent.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    capture = _capture()
    link = build_time_stop_exit_order_link(
        capture,
        broker_order_id="sell-concurrent",
        client_order_id="client-concurrent",
        submitted_at="2026-07-22T13:30:01+00:00",
        completed_at=None,
        submission_status="filled",
        request_descriptor={"operation": "close_position", "symbol": "AAPL"},
    )
    barrier = Barrier(2)

    def writer() -> dict:
        barrier.wait()
        return store.record_time_stop_exit_authority(capture, link, cycle_id="watch-1")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _item: writer(), (0, 1)))
    assert {result["status"] for result in results} == {"inserted", "idempotent"}
    events = store.time_stop_exit_authority_events()
    assert sum(event["event_type"] == "time_stop_exit_authority" for event in events) == 1
    assert sum(event["event_type"] == "time_stop_exit_order_link" for event in events) == 1


def test_submit_persists_only_after_call_and_preserves_submission_exception() -> None:
    capture = _capture()
    calls: list[str] = []

    class RecordingStore:
        def record_time_stop_exit_authority(self, *_args, **_kwargs):
            calls.append("persist")
            return {"status": "inserted"}

    def submit():
        calls.append("submit")
        return {
            "id": "sell-order-1",
            "client_order_id": "client-1",
            "status": "filled",
            "submitted_at": "2026-07-22T13:30:01+00:00",
        }

    order, link = submit_with_time_stop_exit_authority(
        submit=submit,
        store=RecordingStore(),
        capture=capture,
        client_order_id="client-1",
        request_descriptor={"operation": "close_position", "symbol": "AAPL"},
    )
    assert order["id"] == "sell-order-1"
    assert link["schema_version"] == SCHEMA_LINK
    assert calls == ["submit", "persist"]

    def failing_submit():
        calls.append("submit_failed")
        raise RuntimeError("expected")

    with pytest.raises(RuntimeError, match="expected"):
        submit_with_time_stop_exit_authority(
            submit=failing_submit,
            store=RecordingStore(),
            capture=capture,
            client_order_id="client-1",
            request_descriptor={"operation": "close_position", "symbol": "AAPL"},
        )
    assert calls[-2:] == ["submit_failed", "persist"]


def test_scheduler_wiring_keeps_close_position_call_and_persists_after_submit(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    class FakeStore:
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
            return {"AAPL": [_lot("buy-order-1")]}

        def get_runtime_value(self, _key):
            return {}

        def set_runtime_value(self, *_args):
            return None

        def record_time_stop_exit_authority(self, *_args, **_kwargs):
            calls.append(("persist", None))
            return {"status": "inserted"}

        def save_broker_order(self, **_kwargs):
            calls.append(("save_broker_order", None))

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

    def fake_submit(_settings, plan, *, client_order_id):
        calls.append(("submit", plan["payload"]["risk_decision"]["checks"]["time_stop_exit_authority"]))
        assert client_order_id.startswith("agente-")
        return {
            "id": "sell-order-1",
            "client_order_id": client_order_id,
            "status": "accepted",
            "submitted_at": "2026-07-22T13:30:01+00:00",
        }

    monkeypatch.setattr(scheduler, "submit_paper_order_plan", fake_submit)
    exits = scheduler._execute_stop_take_exits(
        settings,
        FakeStore(),
        reporter,
        "watch-1",
        portfolio,
        evaluation_at=datetime.fromisoformat("2026-07-22T13:30:00+00:00"),
    )
    assert exits[0]["status"] == "accepted"
    assert [item[0] for item in calls] == ["submit", "persist", "save_broker_order"]


def test_empty_reader_is_collecting_with_null_denominators(tmp_path) -> None:
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    report = time_stop_exit_authority_digest(store)
    assert report["status"] == "collecting"
    assert report["canonical_decisions"] is None
    assert report["conflicts"] is None
