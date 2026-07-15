from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

from agente_bolsa.config import Settings
from agente_bolsa.market_calendar import MarketCalendar
from agente_bolsa.scheduler import _exit_policy_v2_runtime_trigger
from agente_bolsa.storage import Store
from agente_bolsa.tools.time_stop_policy import (
    record_shadow_time_stop_observation,
    shadow_time_stop_digest_summary,
)


def _calendar() -> MarketCalendar:
    calendar = MarketCalendar("XNYS", "Europe/Madrid")
    assert calendar._calendar is not None
    return calendar


def _evidence(*, comparison_status: str, completed: int, evaluation_at: str, xnys: bool = False) -> dict:
    return {
        "schema_version": "p-l43b.time-stop-xnys.v1",
        "policy_version": "time_stop_xnys.v1",
        "time_stop_semantics": "completed_xnys_sessions_after_fill",
        "status": "available",
        "comparison_status": comparison_status,
        "comparison": "legacy_only" if comparison_status == "legacy_only" else "same",
        "legacy_eligible": comparison_status in {"legacy_only", "both_eligible"},
        "legacy_calendar_eligible": comparison_status in {"legacy_only", "both_eligible"},
        "xnys_eligible": xnys,
        "completed_xnys_sessions_after_entry": completed,
        "required_xnys_sessions": 5,
        "fill_authority": "first_fill_at",
        "fill_timestamp": "2026-07-08T16:00:00+00:00",
        "evaluation_at": evaluation_at,
        "logical_eligibility_at": "2026-07-15T20:00:00+00:00",
        "first_actionable_market_time": "2026-07-16T13:30:00+00:00",
        "unavailable_reason": None,
        "ambiguity_reason": None,
        "warnings": [],
        "shadow_only": True,
        "active_policy": "legacy_calendar_days",
        "shadow_policy": "time_stop_xnys.v1",
    }


def _lots(order_id: str, *, open_qty: float | None = None) -> list[dict]:
    lot = {
        "broker_order_id": order_id,
        "entry_fill_at": "2026-07-08T16:00:00Z",
        "fill_authority": "first_fill_at",
        "filled_qty": 1,
    }
    if open_qty is not None:
        lot["open_qty"] = open_qty
    return [lot]


def _record(store: Store, *, symbol: str, order_id: str, evaluation_at: str, status: str, completed: int, xnys: bool = False, qty: float = 1) -> dict:
    return record_shadow_time_stop_observation(
        store,
        symbol=symbol,
        evidence=_evidence(
            comparison_status=status,
            completed=completed,
            evaluation_at=evaluation_at,
            xnys=xnys,
        ),
        lots=_lots(order_id, open_qty=qty),
        position_qty=qty,
        calendar=_calendar(),
        evaluation_at=evaluation_at,
    )


def test_sixty_ticks_same_position_and_session_are_one_event(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    for _ in range(60):
        _record(
            store,
            symbol="AAPL",
            order_id="buy-a",
            evaluation_at="2026-07-13T20:00:00Z",
            status="both_ineligible",
            completed=3,
        )
    events = store.agent_events(event_type_prefix="time_stop_shadow_observation")
    assert len(events) == 1
    assert events[0]["payload"]["observation_session"] == "2026-07-13"


def test_restart_is_idempotent_and_does_not_duplicate(tmp_path):
    db = tmp_path / "state.sqlite3"
    store = Store(db, tmp_path / "logs")
    store.ensure_schema()
    _record(store, symbol="AAPL", order_id="buy-a", evaluation_at="2026-07-13T20:00:00Z", status="both_ineligible", completed=3)
    restarted = Store(db, tmp_path / "logs")
    restarted.ensure_schema()
    result = _record(restarted, symbol="AAPL", order_id="buy-a", evaluation_at="2026-07-13T20:00:00Z", status="both_ineligible", completed=3)
    assert result["history_status"] == "idempotent"
    assert len(restarted.agent_events(event_type_prefix="time_stop_shadow_observation")) == 1


def test_comparison_transition_and_logical_eligibility_are_distinct_events(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    _record(store, symbol="AAPL", order_id="buy-a", evaluation_at="2026-07-10T20:00:00Z", status="both_ineligible", completed=2)
    _record(store, symbol="AAPL", order_id="buy-a", evaluation_at="2026-07-13T20:00:00Z", status="legacy_only", completed=3)
    _record(store, symbol="AAPL", order_id="buy-a", evaluation_at="2026-07-15T20:00:01Z", status="both_eligible", completed=5, xnys=True)
    events = store.agent_events(event_type_prefix="time_stop_shadow_observation")
    assert len(events) == 3
    assert events[1]["payload"]["observation_reason"] == "comparison_transition"
    assert events[2]["payload"]["observation_reason"] == "logical_eligibility"


def test_legacy_time_stop_activation_is_historical_and_does_not_change_trigger(tmp_path):
    settings = Settings(DATA_DIR=tmp_path, EXIT_POLICY_V2_ENABLED=True, EXIT_POLICY_V2_TIME_STOP_DAYS=5, EXIT_POLICY_V2_TIME_STOP_MIN_RETURN=0.0)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    position = SimpleNamespace(avg_entry_price=100.0, qty=1.0, current_price=99.0, unrealized_plpc=-0.01)
    source = {
        "created_at": "2026-07-08T16:00:00Z",
        "cycle_id": "cycle-a",
        "plan": {"plan_id": "plan-a"},
        "lots": _lots("buy-a"),
    }
    result = _exit_policy_v2_runtime_trigger(
        settings,
        store,
        symbol="AAPL",
        position=position,
        source=source,
        payload={"entry_price": 100.0, "stop_loss": 95.0},
        calendar=_calendar(),
        evaluation_at=datetime.fromisoformat("2026-07-13T20:00:00+00:00"),
    )
    assert result and result["trigger"] == "time_stop_v2"
    reasons = [item["payload"]["observation_reason"] for item in store.agent_events(event_type_prefix="time_stop_shadow_observation")]
    assert "legacy_time_stop_activated" in reasons


def test_rebuy_same_symbol_and_multiple_lots_keep_exact_identity(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    first = _record(store, symbol="AAPL", order_id="buy-a", evaluation_at="2026-07-13T20:00:00Z", status="legacy_only", completed=3)
    second = _record(store, symbol="AAPL", order_id="buy-b", evaluation_at="2026-07-14T20:00:00Z", status="both_ineligible", completed=4)
    assert first["position_identity"] != second["position_identity"]
    multi = record_shadow_time_stop_observation(
        store,
        symbol="AAPL",
        evidence=_evidence(comparison_status="both_ineligible", completed=3, evaluation_at="2026-07-13T20:00:00Z"),
        lots=[
            {**_lots("buy-a", open_qty=2)[0]},
            {**_lots("buy-b", open_qty=3)[0], "entry_fill_at": "2026-07-09T16:00:00Z"},
        ],
        position_qty=5,
        calendar=_calendar(),
        evaluation_at="2026-07-13T20:00:00Z",
    )
    assert multi["position_identity"] not in {first["position_identity"], second["position_identity"]}


def test_partial_without_first_fill_is_unavailable_without_fabricated_identity(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    result = record_shadow_time_stop_observation(
        store,
        symbol="AAPL",
        evidence={**_evidence(comparison_status="xnys_unavailable", completed=0, evaluation_at="2026-07-13T20:00:00Z"), "status": "unavailable", "unavailable_reason": "fill_authority_unavailable"},
        lots=[{"broker_order_id": "buy-partial", "filled_qty": 2, "fill_authority": "unavailable"}],
        position_qty=2,
        calendar=_calendar(),
        evaluation_at="2026-07-13T20:00:00Z",
    )
    assert result["position_identity"] is None
    assert result["identity_reason"] == "fill_authority_unavailable"
    event = store.agent_events(event_type_prefix="time_stop_shadow_observation")[0]["payload"]
    assert event["position_identity"] is None


def test_same_id_conflict_preserves_original_and_is_auditable(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    first = _record(store, symbol="AAPL", order_id="buy-a", evaluation_at="2026-07-13T20:00:00Z", status="legacy_only", completed=3)
    original = store.agent_events(event_type_prefix="time_stop_shadow_observation")[0]["payload"]
    changed = dict(original)
    changed["content_hash"] = "different-content"
    result = store.record_time_stop_shadow_observation(changed, event_id=first["shadow_observation_id"])
    assert result["status"] == "conflict"
    assert store.agent_events(event_type_prefix="time_stop_shadow_observation")[0]["payload"] == original
    assert store.agent_events(event_type_prefix="time_stop_shadow_observation_conflict")


def test_digest_counts_history_not_ticks_and_runtime_is_latest_view(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    for _ in range(60):
        _record(store, symbol="AAPL", order_id="buy-a", evaluation_at="2026-07-13T20:00:00Z", status="legacy_only", completed=3)
    summary = shadow_time_stop_digest_summary(store)
    assert summary["unique_positions"] == 1
    assert summary["unique_observations"] == 1
    assert summary["legacy_only"] == 1
    assert summary["current_positions"] == 0
    store.set_runtime_value("time_stop_v2_evidence:AAPL", {"position_identity": "position-current", "status": "available"})
    assert shadow_time_stop_digest_summary(store)["unique_observations"] == 1


def test_shadow_event_payload_has_no_post_decision_fields(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    _record(store, symbol="AAPL", order_id="buy-a", evaluation_at="2026-07-13T20:00:00Z", status="legacy_only", completed=3)
    payload = store.agent_events(event_type_prefix="time_stop_shadow_observation")[0]["payload"]
    encoded = json.dumps(payload)
    for forbidden in ("pnl", "return_1d", "mfe", "mae", "first_hit", "outcome", "prompt", "llm"):
        assert forbidden not in encoded.lower()


def test_shadow_history_failure_is_fail_open(tmp_path):
    class BrokenStore:
        def time_stop_shadow_observations(self, **kwargs):
            raise RuntimeError("ledger unavailable")

        def record_time_stop_shadow_observation(self, *args, **kwargs):
            raise RuntimeError("ledger unavailable")

    result = record_shadow_time_stop_observation(
        BrokenStore(),
        symbol="AAPL",
        evidence=_evidence(comparison_status="legacy_only", completed=3, evaluation_at="2026-07-13T20:00:00Z"),
        lots=_lots("buy-a"),
        position_qty=1,
        calendar=_calendar(),
        evaluation_at="2026-07-13T20:00:00Z",
    )
    assert result["history_status"] == "unavailable"
