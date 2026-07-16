from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from agente_bolsa.market_calendar import MarketCalendar
from agente_bolsa.storage import Store
from agente_bolsa.tools.time_stop_policy import (
    canonical_order_side,
    evaluate_position_time_stop,
    record_shadow_time_stop_observation,
)


def _calendar() -> MarketCalendar:
    calendar = MarketCalendar("XNYS", "Europe/Madrid")
    assert calendar._calendar is not None
    return calendar


def _lot(
    order_id: str = "buy-a",
    *,
    side: object = "buy",
    status_verified: bool = True,
    fill: str | None = "2026-07-14T18:16:48.802336+00:00",
    authority: str | None = "first_fill_at",
    filled_qty: float | None = 5,
    partial: bool = False,
) -> dict:
    return {
        "broker_order_id": order_id,
        "order_side": side,
        "order_status": "filled" if status_verified else "pending",
        "order_status_verified": status_verified,
        "entry_fill_at": fill,
        "filled_at": fill,
        "fill_authority": authority,
        "filled_qty": filled_qty,
        "submitted_qty": 10 if partial else filled_qty,
        "is_partial": partial,
    }


def _evaluate(lot: dict) -> dict:
    return evaluate_position_time_stop(
        lots=[lot],
        position_qty=5,
        side="PositionSide.LONG",
        evaluation_at="2026-07-16T14:00:00+00:00",
        required_completed_sessions=5,
        calendar=_calendar(),
    )


@pytest.mark.parametrize("side", ["buy", "BUY", "OrderSide.BUY"])
def test_verified_buy_side_representations_are_accepted(side):
    result = _evaluate(_lot(side=side))
    assert result["status"] == "available"
    assert result["fill_authority"] == "first_fill_at"
    assert result["xnys_eligible"] is False
    assert result["lots"][0]["broker_order_id"] == "buy-a"


def test_enum_like_buy_is_normalized_without_accepting_long_as_buy():
    assert canonical_order_side(SimpleNamespace(value="buy")) == "buy"
    assert canonical_order_side(SimpleNamespace(value="long")) is None
    assert _evaluate(_lot(side="long"))["unavailable_reason"] == "unsupported_order_side"


@pytest.mark.parametrize("side", ["sell", "OrderSide.SELL"])
def test_sell_is_unavailable(side):
    result = _evaluate(_lot(side=side))
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "unsupported_order_side"


@pytest.mark.parametrize("status", ["pending", "rejected", "cancelled"])
def test_pending_rejected_or_cancelled_are_unavailable(status):
    lot = _lot(status_verified=False)
    lot["order_status"] = status
    result = _evaluate(lot)
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "order_not_filled"


def test_filled_order_with_only_aggregated_filled_at_is_allowed():
    result = _evaluate(_lot(authority="aggregated_filled_at"))
    assert result["status"] == "available"
    assert result["fill_authority"] == "aggregated_filled_at"


def test_store_derives_authority_from_exact_filled_buy_order(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_broker_order(
        broker_order_id="buy-exact",
        plan_id="plan-exact",
        cycle_id="cycle-exact",
        symbol="ANET",
        side="buy",
        status="filled",
        payload={
            "broker_order": {
                "id": "buy-exact",
                "side": "OrderSide.BUY",
                "status": "OrderStatus.FILLED",
                "qty": 5,
                "filled_qty": 5,
                "first_fill_at": "2026-07-14T18:16:48.802336+00:00",
                "filled_at": "2026-07-14T18:16:48.802336+00:00",
            }
        },
    )
    lot = store.executed_buy_lots_by_symbol()["ANET"][0]
    assert lot["broker_order_id"] == "buy-exact"
    assert lot["order_side"] == "buy"
    assert lot["order_status_verified"] is True
    assert lot["fill_authority"] == "first_fill_at"
    assert lot["entry_fill_at"] == "2026-07-14T18:16:48.802336+00:00"


def test_store_rejects_partial_nested_status_without_first_fill(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_broker_order(
        broker_order_id="buy-partial",
        plan_id="plan-partial",
        cycle_id="cycle-partial",
        symbol="ANET",
        side="buy",
        status="filled",
        payload={
            "broker_order": {
                "id": "buy-partial",
                "side": "OrderSide.BUY",
                "status": "OrderStatus.PARTIALLY_FILLED",
                "qty": 5,
                "filled_qty": 2,
                "filled_at": "2026-07-14T18:16:48.802336+00:00",
            }
        },
    )
    lot = store.executed_buy_lots_by_symbol()["ANET"][0]
    assert lot["is_partial"] is True
    assert lot["fill_authority"] == "unavailable"
    result = _evaluate(lot)
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "fill_authority_unavailable"


def test_partial_fill_requires_first_fill_at():
    verified = _evaluate(_lot(partial=True, authority="first_fill_at"))
    missing = _evaluate(_lot(partial=True, authority="unavailable"))
    assert verified["status"] == "available"
    assert missing["status"] == "unavailable"
    assert missing["unavailable_reason"] == "fill_authority_unavailable"


@pytest.mark.parametrize("filled_qty", [0, None, float("nan"), float("inf")])
def test_zero_or_invalid_filled_qty_is_unavailable(filled_qty):
    result = _evaluate(_lot(filled_qty=filled_qty))
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "invalid_filled_qty"


def test_missing_broker_order_id_is_unavailable():
    lot = _lot()
    lot["broker_order_id"] = None
    result = _evaluate(lot)
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "missing_broker_order_id"


def test_two_verified_lots_keep_independent_clocks_and_identity():
    lots = [_lot("buy-a"), _lot("buy-b", fill="2026-07-15T14:00:00+00:00")]
    for lot in lots:
        lot["open_qty"] = 2.5
    result = evaluate_position_time_stop(
        lots=lots,
        position_qty=5,
        side="PositionSide.LONG",
        evaluation_at="2026-07-16T14:00:00+00:00",
        required_completed_sessions=5,
        calendar=_calendar(),
    )
    assert result["status"] == "available"
    assert [item["completed_xnys_sessions_after_entry"] for item in result["lots"]] == [1, 0]


def test_two_lots_without_open_qty_are_ambiguous():
    lots = [_lot("buy-a"), _lot("buy-b")]
    result = evaluate_position_time_stop(
        lots=lots,
        position_qty=5,
        side="PositionSide.LONG",
        evaluation_at="2026-07-16T14:00:00+00:00",
        required_completed_sessions=5,
        calendar=_calendar(),
    )
    assert result["status"] == "ambiguous"
    assert result["ambiguity_reason"] == "open_lot_quantities_not_verifiable"


def _evidence(status: str, *, evaluation_at: str, completed: int) -> dict:
    return {
        "schema_version": "p-l43b.time-stop-xnys.v1",
        "policy_version": "time_stop_xnys.v1",
        "time_stop_semantics": "completed_xnys_sessions_after_fill",
        "status": status,
        "comparison_status": status == "available" and "both_ineligible" or "xnys_unavailable",
        "comparison": "same" if status == "available" else None,
        "legacy_eligible": False,
        "legacy_calendar_eligible": False,
        "xnys_eligible": False if status == "available" else None,
        "completed_xnys_sessions_after_entry": completed if status == "available" else None,
        "required_xnys_sessions": 5,
        "fill_authority": "first_fill_at" if status == "available" else None,
        "fill_timestamp": "2026-07-14T18:16:48.802336+00:00" if status == "available" else None,
        "evaluation_at": evaluation_at,
        "logical_eligibility_at": "2026-07-21T20:00:00+00:00" if status == "available" else None,
        "first_actionable_market_time": "2026-07-22T13:30:00+00:00" if status == "available" else None,
        "unavailable_reason": "unsupported_side" if status != "available" else None,
        "ambiguity_reason": None,
        "warnings": ["unsupported_side"] if status != "available" else [],
        "shadow_only": True,
        "active_policy": "legacy_calendar_days",
        "shadow_policy": "time_stop_xnys.v1",
    }


def test_unavailable_to_available_is_append_only_and_idempotent(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    lot = _lot()
    unavailable = record_shadow_time_stop_observation(
        store,
        symbol="ANET",
        evidence=_evidence("unavailable", evaluation_at="2026-07-16T13:30:00+00:00", completed=0),
        lots=[lot],
        position_qty=5,
        calendar=_calendar(),
        evaluation_at="2026-07-16T13:30:00+00:00",
    )
    available = record_shadow_time_stop_observation(
        store,
        symbol="ANET",
        evidence=_evidence("available", evaluation_at="2026-07-16T14:00:00+00:00", completed=1),
        lots=[lot],
        position_qty=5,
        calendar=_calendar(),
        evaluation_at="2026-07-16T14:00:00+00:00",
    )
    assert unavailable["position_identity"] == available["position_identity"]
    assert available["history_status"] == "inserted"
    events = store.agent_events(event_type_prefix="time_stop_shadow_observation")
    assert len(events) == 2
    assert events[0]["payload"]["temporal"]["status"] == "unavailable"
    assert events[1]["payload"]["temporal"]["status"] == "available"
    for _ in range(60):
        repeated = record_shadow_time_stop_observation(
            store,
            symbol="ANET",
            evidence=_evidence("available", evaluation_at="2026-07-16T14:59:00+00:00", completed=1),
            lots=[lot],
            position_qty=5,
            calendar=_calendar(),
            evaluation_at="2026-07-16T14:59:00+00:00",
        )
        assert repeated["history_status"] == "idempotent"
    assert len(store.agent_events(event_type_prefix="time_stop_shadow_observation")) == 2


def test_conflict_preserves_original_and_is_auditable(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    lot = _lot()
    first = record_shadow_time_stop_observation(
        store,
        symbol="ANET",
        evidence=_evidence("available", evaluation_at="2026-07-16T14:00:00+00:00", completed=1),
        lots=[lot], position_qty=5, calendar=_calendar(), evaluation_at="2026-07-16T14:00:00+00:00",
    )
    original = store.agent_events(event_type_prefix="time_stop_shadow_observation")[0]["payload"]
    changed = dict(original)
    changed["content_hash"] = "different"
    conflict = store.record_time_stop_shadow_observation(changed, event_id=first["shadow_observation_id"])
    assert conflict["status"] == "conflict"
    assert store.agent_events(event_type_prefix="time_stop_shadow_observation")[0]["payload"] == original
    assert store.agent_events(event_type_prefix="time_stop_shadow_observation_conflict")


@pytest.mark.parametrize(
    "symbol,order_id,fill,expected_sessions",
    [
        ("ANET", "a916133a-7889-4b30-8d92-9ccf6f307881", "2026-07-14T18:16:48.802336+00:00", 1),
        ("DDOG", "27d65736-4030-47c2-bdb6-61033c4c0e81", "2026-07-14T13:48:57.746200+00:00", 1),
        ("BAC", "a0b0ab77-94f2-4f7a-b147-2157b331f1e7", "2026-07-15T14:06:03.339846+00:00", 0),
        ("BNY", "e1dc1981-df58-4ba5-a16d-09905428db24", "2026-07-15T13:53:48.967354+00:00", 0),
        ("JPM", "ff91476a-ab63-44d8-9920-81bd19ce39f3", "2026-07-15T13:53:47.236927+00:00", 0),
    ],
)
def test_sanitized_real_lots_have_exact_authority(symbol, order_id, fill, expected_sessions):
    lot = _lot(order_id, fill=fill)
    result = _evaluate(lot)
    assert result["status"] == "available"
    assert result["fill_authority"] == "first_fill_at"
    assert result["fill_timestamp"] == fill
    assert result["xnys_eligible"] is False
    assert result["lots"][0]["broker_order_id"] == order_id
    assert result["lots"][0]["completed_xnys_sessions_after_entry"] == expected_sessions
    assert "unsupported_side" not in result["warnings"]
    assert result["logical_eligibility_at"] is not None
    assert result["first_actionable_market_time"] is not None


def test_legacy_trigger_and_risk_path_remain_unchanged(tmp_path):
    from agente_bolsa.config import Settings
    from agente_bolsa.scheduler import _exit_policy_v2_runtime_trigger

    settings = Settings(DATA_DIR=tmp_path, EXIT_POLICY_V2_ENABLED=True, EXIT_POLICY_V2_TIME_STOP_DAYS=5, EXIT_POLICY_V2_TIME_STOP_MIN_RETURN=0.0)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    position = SimpleNamespace(avg_entry_price=100.0, qty=5.0, current_price=99.0, unrealized_plpc=-0.01, side="PositionSide.LONG")
    source = {
        "created_at": "2026-07-08T16:00:00Z",
        "plan": {"plan_id": "plan-a"},
        "lots": [{**_lot("buy-a"), "fill": None, "entry_fill_at": "2026-07-08T16:00:00Z"}],
    }
    result = _exit_policy_v2_runtime_trigger(
        settings, store, symbol="AAPL", position=position, source=source,
        payload={"entry_price": 100.0, "stop_loss": 95.0},
        calendar=_calendar(), evaluation_at=datetime.fromisoformat("2026-07-13T20:00:00+00:00"),
    )
    assert result["trigger"] == "time_stop_v2"
    assert result["time_stop_evidence"]["active_policy"] == "legacy_calendar_days"
    assert result["time_stop_evidence"]["shadow_only"] is True


def test_shadow_payload_has_no_future_or_llm_fields(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    record_shadow_time_stop_observation(
        store, symbol="ANET", evidence=_evidence("available", evaluation_at="2026-07-16T14:00:00+00:00", completed=1),
        lots=[_lot()], position_qty=5, calendar=_calendar(), evaluation_at="2026-07-16T14:00:00+00:00",
    )
    payload = store.agent_events(event_type_prefix="time_stop_shadow_observation")[0]["payload"]
    encoded = json.dumps(payload).lower()
    for forbidden in ("pnl", "return_1d", "mfe", "mae", "first_hit", "outcome", "prompt", "llm"):
        assert forbidden not in encoded
