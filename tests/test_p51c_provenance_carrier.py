"""P-L51C-T: caracterizacion del carrier minimo de provenance BUY -> SELL.

El carrier vive deliberadamente en tests. La suite usa los builders, modelos y
serializadores existentes, pero no implementa wiring productivo ni modifica
``src``. La frontera candidata es metadata del order plan transportada dentro
del payload local de broker_order; el broker solo recibe el request operativo.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.scheduler import _risk_exit_plan
from agente_bolsa.storage import Store
from agente_bolsa.tools.broker_reconciliation import reconcile_broker_orders
from agente_bolsa.tools.canonical_operation_telemetry import build_canonical_operation_telemetry
from agente_bolsa.tools.canonical_trade_attribution import build_canonical_trade_attribution
from agente_bolsa.tools.execution import build_market_order_request

SCHEMA_VERSION = "p-l51c.exit-lot-provenance.v1"
CAPTURED_AT = "2026-07-21T19:30:00+00:00"
SELL_TERMINAL_STATUSES = {"filled", "partially_filled"}
UNAVAILABLE_STATUSES = {"pending", "pending_new", "accepted", "rejected", "cancelled", "canceled"}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _canonical_hash(value: dict[str, Any]) -> str:
    content = copy.deepcopy(value)
    content.pop("captured_at", None)
    content.pop("content_hash", None)
    encoded = json.dumps(content, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _reason_quality(reasons: list[str]) -> str:
    return "conflict" if any(reason.startswith(("duplicate", "allocation_exceeds", "qty_", "source_plan")) for reason in reasons) else "unavailable"


def _fill_rows(raw: Any) -> list[dict[str, Any]] | None:
    if raw is None:
        return None
    if not isinstance(raw, list) or not raw:
        return []
    result = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("fill_id") or _number(item.get("qty")) is None:
            return None
        result.append({"fill_id": str(item["fill_id"]), "qty": float(item["qty"])})
    return sorted(result, key=lambda item: item["fill_id"])


def build_exit_lot_provenance(
    sell_plan: dict[str, Any],
    buy_lots: list[dict[str, Any]],
    allocations: list[dict[str, Any]] | None = None,
    *,
    order_status: str = "planned",
    captured_at: str = CAPTURED_AT,
) -> dict[str, Any]:
    """Test-only carrier builder using exact BUY lot IDs and allocations."""

    payload = dict(sell_plan.get("payload") or {})
    checks = dict((payload.get("risk_decision") or {}).get("checks") or {})
    source_plan_id = str(checks.get("source_plan_id") or "").strip() or None
    sell_qty = _number(payload.get("qty"))
    lots_by_order = {str(lot.get("broker_order_id")): lot for lot in buy_lots if lot.get("broker_order_id")}
    reasons: list[str] = []
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    if not source_plan_id:
        reasons.append("missing_source_plan_id")
    if sell_qty is None or sell_qty <= 0:
        reasons.append("qty_sell_unavailable")
    if order_status.lower() in UNAVAILABLE_STATUSES:
        reasons.append("sell_order_not_filled")
    if not allocations:
        reasons.append("missing_allocations")
    declared_plan_ids = {
        str(item.get("buy_plan_id") or "").strip()
        for item in allocations or []
        if isinstance(item, dict) and str(item.get("buy_plan_id") or "").strip()
    }
    if len(declared_plan_ids) > 1:
        # A multi-lot exit has no single source plan. Exact buy_plan_id values
        # remain on each allocation; the top-level field is intentionally null.
        source_plan_id = None

    allocated_total = 0.0
    for raw in allocations or []:
        if not isinstance(raw, dict):
            reasons.append("incomplete_allocation")
            continue
        buy_id = str(raw.get("buy_broker_order_id") or "").strip()
        buy_plan_id = str(raw.get("buy_plan_id") or "").strip()
        allocated_qty = _number(raw.get("allocated_qty"))
        available_qty = _number(raw.get("available_open_qty_at_decision"))
        fill_rows = _fill_rows(raw.get("canonical_buy_fill_ids"))
        fill_key = ",".join(item["fill_id"] for item in fill_rows or [])
        key = (buy_id, buy_plan_id, fill_key)
        if key in seen:
            reasons.append("duplicate_allocation")
        seen.add(key)
        lot = lots_by_order.get(buy_id)
        if not buy_id or not buy_plan_id or allocated_qty is None or available_qty is None:
            reasons.append("incomplete_allocation")
            continue
        if lot is None:
            reasons.append("unknown_buy_broker_order_id")
            continue
        if str(lot.get("order_plan_id") or "") != buy_plan_id:
            reasons.append("source_plan_or_buy_plan_mismatch")
        if available_qty <= 0 or allocated_qty <= 0 or allocated_qty > available_qty + 1e-9:
            reasons.append("allocation_exceeds_open_qty")
        if fill_rows is not None and allocated_qty > sum(item["qty"] for item in fill_rows) + 1e-9:
            reasons.append("allocation_exceeds_canonical_fill_qty")
        allocated_total += allocated_qty
        normalized.append(
            {
                "buy_broker_order_id": buy_id,
                "buy_plan_id": buy_plan_id,
                "allocated_qty": allocated_qty,
                "available_open_qty_at_decision": available_qty,
                "canonical_buy_fill_ids": fill_rows,
            }
        )

    normalized.sort(key=lambda item: (item["buy_broker_order_id"], item["buy_plan_id"], json.dumps(item["canonical_buy_fill_ids"], sort_keys=True)))
    if sell_qty is not None and normalized and abs(allocated_total - sell_qty) > 1e-9:
        reasons.append("qty_allocation_mismatch")
    if source_plan_id and normalized:
        for item in normalized:
            lot = lots_by_order.get(item["buy_broker_order_id"], {})
            if source_plan_id not in {str(lot.get("source_plan_id") or ""), str(lot.get("order_plan_id") or "")}:
                reasons.append("source_plan_id_mismatch")

    lot_identities = [str(lot.get("lot_identity")) for lot in buy_lots if lot.get("lot_identity")]
    position_identities = [str(lot.get("position_identity")) for lot in buy_lots if lot.get("position_identity")]
    carrier: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sell_plan_id": str(sell_plan.get("plan_id") or "") or None,
        "source_plan_id": source_plan_id,
        "allocations": normalized or None,
        "position_identity": position_identities[0] if len(set(position_identities)) == 1 else None,
        "lot_identity": lot_identities[0] if len(set(lot_identities)) == 1 else None,
        "captured_at": captured_at,
        "content_hash": None,
        "provenance_quality": "exact" if not reasons else _reason_quality(reasons),
        "reason_codes": list(dict.fromkeys(reasons)),
    }
    carrier["content_hash"] = _canonical_hash(carrier)
    return carrier


def append_carrier_event(existing: dict[str, dict[str, Any]], carrier: dict[str, Any]) -> dict[str, Any]:
    """Test-only append-only event model: identical no-op, changed conflict."""

    event_id = f"exit_lot_provenance:{carrier.get('sell_plan_id')}"
    previous = existing.get(event_id)
    if previous is None:
        existing[event_id] = copy.deepcopy(carrier)
        return {"status": "inserted", "event_id": event_id}
    if _canonical_hash(previous) == _canonical_hash(carrier):
        return {"status": "idempotent", "event_id": event_id}
    return {"status": "conflict", "event_id": event_id}


def _buy_lot(order_id: str, plan_id: str, qty: float, *, lot_identity: str | None = None) -> dict[str, Any]:
    return {
        "broker_order_id": order_id,
        "order_plan_id": plan_id,
        "source_plan_id": plan_id,
        "filled_qty": qty,
        "open_qty": qty,
        "lot_identity": lot_identity,
        "position_identity": "position-ACME" if lot_identity else None,
    }


def _exit_plan(qty: float, *, trigger: str = "stop_loss") -> dict[str, Any]:
    source_plan = {
        "plan_id": "buy-plan-1",
        "payload": {"stop_loss": 95.0, "take_profit": 110.0},
    }
    plan = _risk_exit_plan(
        symbol="ACME",
        notional=qty * 100.0,
        qty=qty,
        current_price=99.0,
        trigger=trigger,
        level=95.0,
        source_plan=source_plan,
        time_stop_evidence={"completed_sessions": 5} if trigger == "time_stop_v2" else None,
    )
    plan["plan_id"] = f"sell-plan-{trigger}"
    plan["cycle_id"] = "cycle-exit"
    return plan


def test_schema_is_exact_and_stop_time_stop_share_the_same_carrier_contract() -> None:
    lot = _buy_lot("buy-1", "buy-plan-1", 10, lot_identity="lot-1")
    allocation = [{"buy_broker_order_id": "buy-1", "buy_plan_id": "buy-plan-1", "allocated_qty": 10, "available_open_qty_at_decision": 10, "canonical_buy_fill_ids": [{"fill_id": "buy-fill-1", "qty": 10}]}]
    stop_plan = _exit_plan(10, trigger="stop_loss")
    time_plan = _exit_plan(10, trigger="time_stop_v2")
    stop = build_exit_lot_provenance(stop_plan, [lot], allocation)
    time = build_exit_lot_provenance(time_plan, [lot], allocation)

    assert stop["schema_version"] == time["schema_version"] == SCHEMA_VERSION
    assert stop["provenance_quality"] == time["provenance_quality"] == "exact"
    assert stop["allocations"][0]["buy_broker_order_id"] == "buy-1"
    assert stop["position_identity"] == "position-ACME"
    assert stop["content_hash"] != time["content_hash"]
    assert stop_plan["payload"]["risk_decision"]["checks"]["trigger"] == "stop_loss"
    assert time_plan["payload"]["risk_decision"]["checks"]["trigger"] == "time_stop_v2"


def test_partial_fills_rebuys_and_multilot_require_exact_allocations() -> None:
    lots = [_buy_lot("buy-1", "buy-plan-1", 10, lot_identity="lot-1"), _buy_lot("buy-2", "buy-plan-2", 10, lot_identity="lot-2")]
    plan = _exit_plan(5)
    partial = build_exit_lot_provenance(
        plan,
        lots,
        [
            {"buy_broker_order_id": "buy-1", "buy_plan_id": "buy-plan-1", "allocated_qty": 4, "available_open_qty_at_decision": 10, "canonical_buy_fill_ids": [{"fill_id": "fill-1", "qty": 4}]},
            {"buy_broker_order_id": "buy-1", "buy_plan_id": "buy-plan-1", "allocated_qty": 1, "available_open_qty_at_decision": 6, "canonical_buy_fill_ids": [{"fill_id": "fill-2", "qty": 6}]},
        ],
    )
    assert partial["provenance_quality"] == "exact"
    assert sum(item["allocated_qty"] for item in partial["allocations"]) == 5

    multilot = build_exit_lot_provenance(
        _exit_plan(6),
        lots,
        [
            {"buy_broker_order_id": "buy-1", "buy_plan_id": "buy-plan-1", "allocated_qty": 3, "available_open_qty_at_decision": 10, "canonical_buy_fill_ids": None},
            {"buy_broker_order_id": "buy-2", "buy_plan_id": "buy-plan-2", "allocated_qty": 3, "available_open_qty_at_decision": 10, "canonical_buy_fill_ids": None},
        ],
    )
    assert multilot["provenance_quality"] == "exact"
    assert {item["buy_broker_order_id"] for item in multilot["allocations"]} == {"buy-1", "buy-2"}

    rebuy_one = build_exit_lot_provenance(_exit_plan(10), lots, [{"buy_broker_order_id": "buy-2", "buy_plan_id": "buy-plan-2", "allocated_qty": 10, "available_open_qty_at_decision": 10, "canonical_buy_fill_ids": None}])
    assert [item["buy_broker_order_id"] for item in rebuy_one["allocations"]] == ["buy-2"]


@pytest.mark.parametrize(
    ("allocations", "expected_quality", "expected_reason"),
    [
        (None, "unavailable", "missing_allocations"),
        ([{"buy_broker_order_id": None, "buy_plan_id": "buy-plan-1", "allocated_qty": 10, "available_open_qty_at_decision": 10}], "unavailable", "incomplete_allocation"),
        ([{"buy_broker_order_id": "buy-1", "buy_plan_id": "buy-plan-1", "allocated_qty": 11, "available_open_qty_at_decision": 10}], "conflict", "allocation_exceeds_open_qty"),
        ([{"buy_broker_order_id": "buy-1", "buy_plan_id": "buy-plan-1", "allocated_qty": 10, "available_open_qty_at_decision": 10}, {"buy_broker_order_id": "buy-1", "buy_plan_id": "buy-plan-1", "allocated_qty": 10, "available_open_qty_at_decision": 10}], "conflict", "duplicate_allocation"),
    ],
)
def test_missing_excessive_or_duplicate_provenance_never_falls_back_to_fifo(allocations, expected_quality, expected_reason) -> None:
    result = build_exit_lot_provenance(_exit_plan(10), [_buy_lot("buy-1", "buy-plan-1", 10)], allocations)
    assert result["provenance_quality"] == expected_quality
    assert expected_reason in result["reason_codes"]


@pytest.mark.parametrize("status", sorted(UNAVAILABLE_STATUSES))
def test_pending_rejected_cancelled_and_unfilled_statuses_are_unavailable(status: str) -> None:
    result = build_exit_lot_provenance(
        _exit_plan(10),
        [_buy_lot("buy-1", "buy-plan-1", 10)],
        [{"buy_broker_order_id": "buy-1", "buy_plan_id": "buy-plan-1", "allocated_qty": 10, "available_open_qty_at_decision": 10}],
        order_status=status,
    )
    assert result["provenance_quality"] == "unavailable"
    assert "sell_order_not_filled" in result["reason_codes"]


def test_source_plan_without_buy_order_is_unavailable_and_missing_is_null() -> None:
    plan = _exit_plan(10)
    plan["payload"]["risk_decision"]["checks"]["source_plan_id"] = "buy-plan-1"
    result = build_exit_lot_provenance(
        plan,
        [_buy_lot("buy-1", "buy-plan-1", 10)],
        [{"buy_broker_order_id": None, "buy_plan_id": "buy-plan-1", "allocated_qty": 10, "available_open_qty_at_decision": 10}],
    )
    assert result["provenance_quality"] == "unavailable"
    assert result["source_plan_id"] == "buy-plan-1"
    assert result["allocations"] is None


def test_hash_excludes_captured_at_and_append_only_conflicts_preserve_original() -> None:
    lot = _buy_lot("buy-1", "buy-plan-1", 10)
    allocation = [{"buy_broker_order_id": "buy-1", "buy_plan_id": "buy-plan-1", "allocated_qty": 10, "available_open_qty_at_decision": 10}]
    first = build_exit_lot_provenance(_exit_plan(10), [lot], allocation, captured_at="2026-07-21T19:00:00+00:00")
    repeated = build_exit_lot_provenance(_exit_plan(10), [lot], list(reversed(allocation)), captured_at="2026-07-21T19:01:00+00:00")
    repeated["allocations"] = list(reversed(repeated["allocations"] or []))
    repeated["content_hash"] = _canonical_hash(repeated)
    original = copy.deepcopy(first)
    events: dict[str, dict[str, Any]] = {}
    assert append_carrier_event(events, first)["status"] == "inserted"
    assert append_carrier_event(events, repeated)["status"] == "idempotent"
    conflict = copy.deepcopy(first)
    conflict["allocations"][0]["allocated_qty"] = 9
    conflict["content_hash"] = _canonical_hash(conflict)
    assert append_carrier_event(events, conflict)["status"] == "conflict"
    assert events["exit_lot_provenance:sell-plan-stop_loss"] == original


def _persisted_buy(store: Store) -> list[dict[str, Any]]:
    buy_plan = {"plan_id": "buy-plan-1", "cycle_id": "cycle-buy", "symbol": "ACME", "side": "buy", "payload": {"qty": 10, "entry_price": 100}}
    store.save_order_plan(plan_id="buy-plan-1", cycle_id="cycle-buy", symbol="ACME", side="buy", notional=1000, approved=True, dry_run=True, payload=buy_plan)
    store.save_broker_order(
        broker_order_id="buy-1",
        plan_id="buy-plan-1",
        cycle_id="cycle-buy",
        symbol="ACME",
        side="buy",
        status="filled",
        payload={"plan": buy_plan, "broker_order": {"id": "buy-1", "status": "filled", "qty": 10, "filled_qty": 10, "filled_at": "2026-07-21T15:40:00+00:00"}, "broker_order_reconciled": {"id": "buy-1", "status": "filled", "qty": 10, "filled_qty": 10, "filled_at": "2026-07-21T15:40:00+00:00"}},
    )
    return store.executed_open_buy_lots_by_symbol(position_quantities={"ACME": 10})["ACME"]


def test_selected_order_plan_metadata_survives_store_and_reconciliation_but_current_p48_drops_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(DATA_DIR=tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    lots = _persisted_buy(store)
    assert {"broker_order_id", "order_plan_id", "filled_qty", "open_qty"} <= set(lots[0])
    sell_plan = _exit_plan(10)
    carrier = build_exit_lot_provenance(
        sell_plan,
        lots,
        [{"buy_broker_order_id": lots[0]["broker_order_id"], "buy_plan_id": lots[0]["order_plan_id"], "allocated_qty": 10, "available_open_qty_at_decision": lots[0]["open_qty"]}],
    )
    sell_plan["payload"]["exit_lot_provenance"] = carrier
    store.save_order_plan(plan_id=sell_plan["plan_id"], cycle_id=sell_plan["cycle_id"], symbol="ACME", side="sell", notional=1000, approved=True, dry_run=True, payload=sell_plan)
    stored_plan = next(item for item in store.order_plans(cycle_id="cycle-exit") if item["plan_id"] == sell_plan["plan_id"])
    assert stored_plan["payload"]["payload"]["exit_lot_provenance"] == carrier
    assert "exit_lot_provenance" not in stored_plan["payload"]["execution_quality_snapshot"]
    store.save_broker_order(
        broker_order_id="sell-1",
        plan_id=sell_plan["plan_id"],
        cycle_id=sell_plan["cycle_id"],
        symbol="ACME",
        side="sell",
        status="pending_new",
        payload={"plan": stored_plan["payload"], "broker_order": {"id": "sell-1", "status": "pending_new", "qty": 10}},
    )

    class _Factory:
        def __init__(self, _settings: Settings) -> None:
            pass

        def alpaca_trading_client(self) -> Any:
            order = type(
                "FakeOrder",
                (),
                {
                    "id": "sell-1",
                    "status": "filled",
                    "qty": 10,
                    "filled_qty": 10,
                    "filled_avg_price": 101,
                    "filled_at": "2026-07-21T16:00:00+00:00",
                    "client_order_id": "",
                    "notional": None,
                    "submitted_at": None,
                    "updated_at": "2026-07-21T16:00:00+00:00",
                },
            )()
            return type("FakeClient", (), {"get_order_by_id": lambda _self, _id: order})()

    monkeypatch.setattr("agente_bolsa.tools.broker_reconciliation.BrokerClientFactory", _Factory)
    result = reconcile_broker_orders(settings, store, apply=True, update_learning=False)
    assert result["changes"][0]["new"] == "filled"
    with store.connect() as conn:
        row = conn.execute("SELECT payload_json FROM broker_orders WHERE broker_order_id = 'sell-1'").fetchone()
    reconciled_payload = json.loads(row["payload_json"])
    assert reconciled_payload["plan"]["payload"]["exit_lot_provenance"] == carrier
    assert "exit_lot_provenance" not in reconciled_payload["plan"]["execution_quality_snapshot"]

    telemetry = build_canonical_operation_telemetry(store, "2026-07-21", captured_at=datetime(2026, 7, 21, 16, 5, tzinfo=timezone.utc))
    sell_operation = next(item for item in telemetry["operations"] if item["broker_order_id"] == "sell-1")
    assert "exit_lot_provenance" not in sell_operation
    attribution = build_canonical_trade_attribution(telemetry, "2026-07-21", captured_at=datetime(2026, 7, 21, 16, 5, tzinfo=timezone.utc))
    assert attribution["denominators"]["attributed_sell_count"] == 0
    assert attribution["metrics"]["net_realized_pl"] is None


def test_carrier_metadata_does_not_change_broker_request_or_exit_controls() -> None:
    plan = _exit_plan(10)
    baseline = copy.deepcopy(plan)
    with_carrier = copy.deepcopy(plan)
    with_carrier["payload"]["exit_lot_provenance"] = build_exit_lot_provenance(
        with_carrier,
        [_buy_lot("buy-1", "buy-plan-1", 10)],
        [{"buy_broker_order_id": "buy-1", "buy_plan_id": "buy-plan-1", "allocated_qty": 10, "available_open_qty_at_decision": 10}],
    )
    base_request = build_market_order_request(baseline, client_order_id="client-sell-1", use_bracket_orders=False)
    carrier_request = build_market_order_request(with_carrier, client_order_id="client-sell-1", use_bracket_orders=False)
    assert repr(base_request) == repr(carrier_request)
    assert baseline["payload"]["qty"] == with_carrier["payload"]["qty"] == 10
    assert baseline["payload"]["risk_decision"] == with_carrier["payload"]["risk_decision"]
    assert baseline["side"] == with_carrier["side"] == "sell"


def test_carrier_has_no_postdecision_or_profit_fields() -> None:
    carrier = build_exit_lot_provenance(
        _exit_plan(10),
        [_buy_lot("buy-1", "buy-plan-1", 10)],
        [{"buy_broker_order_id": "buy-1", "buy_plan_id": "buy-plan-1", "allocated_qty": 10, "available_open_qty_at_decision": 10}],
    )
    forbidden = {"realized_pl", "net_realized_pl", "mfe", "mae", "future_return", "outcome", "fill_at", "exit_origin"}

    def keys(value: Any) -> set[str]:
        if isinstance(value, dict):
            return {str(key) for key in value} | set().union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value)) if value else set()
        return set()

    assert keys(carrier).isdisjoint(forbidden)


BOUNDARY_MATRIX = {
    "order_plan_metadata": {"identity": "exact", "pre_post": "decision", "survives_reconciliation": True, "changes_broker_payload": False, "protected_file": False, "risk": "P48 projection required", "verdict": "minimum_storage_frontier"},
    "broker_order_local_metadata": {"identity": "exact", "pre_post": "decision", "survives_reconciliation": True, "changes_broker_payload": False, "protected_file": False, "risk": "P48 projection required", "verdict": "selected_transport"},
    "execution_quality_snapshot": {"identity": "partial", "pre_post": "mixed", "survives_reconciliation": True, "changes_broker_payload": False, "protected_file": False, "risk": "wrong semantic contract", "verdict": "not_viable"},
    "agent_event_sidecar": {"identity": "exact", "pre_post": "decision", "survives_reconciliation": True, "changes_broker_payload": False, "protected_file": False, "risk": "current P51 reader does not consume it", "verdict": "not_minimal"},
}


def test_boundary_matrix_selects_only_local_order_plan_to_broker_metadata() -> None:
    selected = BOUNDARY_MATRIX["broker_order_local_metadata"]
    assert selected["identity"] == "exact"
    assert selected["survives_reconciliation"] is True
    assert selected["changes_broker_payload"] is False
    assert selected["protected_file"] is False
    assert selected["verdict"] == "selected_transport"
    assert BOUNDARY_MATRIX["execution_quality_snapshot"]["verdict"] == "not_viable"
    assert BOUNDARY_MATRIX["agent_event_sidecar"]["verdict"] == "not_minimal"
