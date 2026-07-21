"""P-L51B-W: product API and fail-open wiring for exact BUY -> SELL attribution."""

from __future__ import annotations

import copy
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from test_p48br1_adversarial_qa import (
    _job_harness,
    _seed_store_from_fixture,
    _seeded_fixture,
)
from test_p48br1_adversarial_qa import (
    _settings as _pmr_settings,
)
from test_p48br1_adversarial_qa import (
    _store as _pmr_store,
)
from test_p51b_canonical_trade_attribution import (
    _buy,
    _fill,
    _p51a_defect_fixture,
    _sell,
    _valid_fixture,
)

from agente_bolsa import scheduler
from agente_bolsa.storage import Store
from agente_bolsa.tools import canonical_trade_attribution as attribution_mod
from agente_bolsa.tools.canonical_operation_telemetry import _operation_for_order
from agente_bolsa.tools.canonical_trade_attribution import (
    SCHEMA_VERSION,
    build_canonical_trade_attribution,
    calculate_risk_metrics,
    calculate_slippage,
    canonical_trade_attribution_digest,
    persist_canonical_trade_attribution,
    read_canonical_trade_attribution,
)
from agente_bolsa.tools.execution import build_market_order_request

CAPTURED_AT = datetime(2026, 7, 21, 18, 30, tzinfo=timezone.utc)
SESSION = "2026-07-21"


def _telemetry(fixture: dict[str, Any]) -> dict[str, Any]:
    """Adapt the sanitized contract fixture to the P-L48 product snapshot."""

    source = copy.deepcopy(fixture)
    fragments = list(source.get("fill_fragments") or [])
    by_order: dict[str, list[dict[str, Any]]] = {}
    for fragment in fragments:
        by_order.setdefault(str(fragment.get("broker_order_id") or ""), []).append(fragment)
    mappings: dict[str, list[dict[str, Any]]] = {}
    for mapping in source.get("attributions") or []:
        sell_id = str(mapping.get("sell_broker_order_id") or "")
        if sell_id:
            mappings.setdefault(sell_id, []).append(copy.deepcopy(mapping))
    plans = {
        str(order.get("broker_order_id")): str(order.get("plan_id") or "")
        for order in source.get("broker_orders") or []
    }
    operations: list[dict[str, Any]] = []
    for order in source.get("broker_orders") or []:
        order_id = str(order.get("broker_order_id") or "")
        side = str(order.get("side") or "").upper()
        order_fragments = by_order.get(order_id, [])
        filled_qty = order.get("filled_qty")
        if filled_qty is None:
            filled_qty = sum(float(fragment.get("qty") or 0.0) for fragment in order_fragments)
        status = str(order.get("status") or "").lower()
        operation: dict[str, Any] = {
            "broker_order_id": order_id,
            "client_order_id": order.get("client_order_id"),
            "side": side,
            "status": status,
            "reconciliation_status": "reconciled_filled" if status in {"filled", "partially_filled"} else "pending",
            "filled_qty": filled_qty,
            "plan_id": order.get("plan_id"),
            "source_plan_id": order.get("source_plan_id"),
            "fill_fragments": order_fragments,
        }
        if side == "SELL":
            sell_mappings = mappings.get(order_id, [])
            normalized_mappings: list[dict[str, Any]] = []
            for mapping in sell_mappings:
                normalized = copy.deepcopy(mapping)
                allocation_plans = {
                    str(item.get("source_plan_id"))
                    for item in normalized.get("allocations") or []
                    if item.get("source_plan_id")
                }
                if len(allocation_plans) == 1:
                    normalized["source_plan_id"] = next(iter(allocation_plans))
                if len(normalized.get("allocations") or []) == 1:
                    buy_id = normalized["allocations"][0].get("buy_broker_order_id")
                    if buy_id in plans:
                        normalized["entry_plan_id"] = plans[buy_id]
                normalized_mappings.append(normalized)
            if len(normalized_mappings) == 1:
                operation["trade_attribution"] = normalized_mappings[0]
            elif normalized_mappings:
                operation["trade_attribution"] = normalized_mappings
        operations.append(operation)
    return {
        "schema_version": "p-l48b.canonical-operation-telemetry.v1",
        "session_date": SESSION,
        "denominators": {
            "fill_fragment_count": len({str(item.get("fill_fragment_id")) for item in fragments}),
        },
        "operations": operations,
        "fill_fragments": fragments,
        "execution_costs": copy.deepcopy(source.get("execution_costs") or {}),
    }


def _snapshot(fixture: dict[str, Any]) -> dict[str, Any]:
    return build_canonical_trade_attribution(_telemetry(fixture), SESSION, captured_at=CAPTURED_AT)


def _store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "state" / "attribution.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    return store


def test_product_api_accepts_exact_mapping_and_keeps_denominators_separate() -> None:
    fixture = _valid_fixture()
    before = copy.deepcopy(fixture)
    result = _snapshot(fixture)

    assert result["schema_version"] == SCHEMA_VERSION
    assert result["status"] == "available"
    assert result["denominators"] == {
        "buy_order_count": 1,
        "sell_order_count": 1,
        "fill_fragment_count": 2,
        "attributed_sell_count": 1,
        "unavailable_sell_count": 0,
        "ambiguous_sell_count": 0,
        "conflict_count": 0,
        "closed_lot_count": 1,
        "partially_closed_lot_count": 0,
        "open_lot_count": 0,
    }
    assert result["metrics"]["gross_realized_pl"] == 100.0
    assert result["metrics"]["net_realized_pl"] == pytest.approx(94.75)
    assert fixture == before


def test_p51a_descriptive_ledger_stays_unavailable_without_exact_buy_identity() -> None:
    result = _snapshot(_p51a_defect_fixture())

    assert result["denominators"]["sell_order_count"] == 18
    assert result["denominators"]["attributed_sell_count"] == 0
    assert result["metrics"]["gross_realized_pl"] is None
    assert result["metrics"]["net_realized_pl"] is None
    assert result["coverage"]["gross_pl_coverage"]["total"] == 0
    assert result["status"] == "unavailable"


def test_p48_preserves_only_explicit_canonical_fill_metadata() -> None:
    attribution = {"source_plan_id": "source-plan-1", "allocations": []}
    fills = [{"fill_fragment_id": "fill-1", "broker_order_id": "buy-1", "lot_id": "lot-1", "qty": 1.0, "side": "BUY"}]
    operation = _operation_for_order(
        {
            "broker_order_id": "sell-1",
            "plan_id": "plan-sell-1",
            "cycle_id": "cycle-1",
            "symbol": "ACME",
            "side": "SELL",
            "status": "filled",
            "payload": {
                "trade_attribution": attribution,
                "canonical_fill_fragments": fills,
            },
        },
        plans={},
        recommendations={},
        signals={},
        fragments={},
        captured_at=CAPTURED_AT,
    )
    assert operation["trade_attribution"] == attribution
    assert operation["fill_fragments"] == fills


def _pmr_counts() -> dict[str, Any]:
    return {
        "build_calls": 0,
        "persist_calls": 0,
        "attribution_build_calls": 0,
        "attribution_persist_calls": 0,
        "reconcile_calls": 0,
        "outcome_updates": 0,
        "portfolio_snapshots": 0,
        "performance_calls": 0,
    }


def test_pmr_attribution_build_failure_is_fail_open_and_terminal_continues(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _pmr_settings(tmp_path)
    store = _pmr_store(tmp_path)
    _seed_store_from_fixture(store, "2026-07-17", _seeded_fixture())
    counts = _pmr_counts()
    _job_harness(monkeypatch, store, counts=counts)

    def broken_build(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("attribution builder unavailable")

    monkeypatch.setattr(scheduler, "build_canonical_trade_attribution", broken_build)
    report = scheduler.post_market_review_job(settings, store, use_llm=False, verbose=False, force=True)

    assert report is not None
    assert report["canonical_trade_attribution"]["status"] == "unavailable"
    assert report["canonical_trade_attribution_persistence"]["status"] == "inserted"
    assert counts["performance_calls"] == 1


def test_pmr_attribution_persistence_failure_is_fail_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _pmr_settings(tmp_path)
    store = _pmr_store(tmp_path)
    _seed_store_from_fixture(store, "2026-07-17", _seeded_fixture())
    counts = _pmr_counts()
    _job_harness(monkeypatch, store, counts=counts)

    def broken_persist(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        counts["attribution_persist_calls"] += 1
        raise RuntimeError("attribution persistence unavailable")

    monkeypatch.setattr(scheduler, "persist_canonical_trade_attribution", broken_persist)
    report = scheduler.post_market_review_job(settings, store, use_llm=False, verbose=False, force=True)

    assert report is not None
    assert report["canonical_trade_attribution_persistence"] is None
    assert counts["performance_calls"] == 1


@pytest.mark.parametrize(
    ("mutation", "state"),
    [
        ("missing_mapping", "ambiguous"),
        ("missing_source_plan", "unavailable"),
        ("pending_sell", "unavailable"),
        ("excess_qty", "conflict"),
        ("partial_costs", "attributed"),
        ("duplicate_mapping", "conflict"),
    ],
)
def test_product_api_preserves_unavailable_ambiguous_conflict_and_missing_costs(
    mutation: str,
    state: str,
) -> None:
    fixture = _valid_fixture()
    if mutation == "missing_mapping":
        fixture["attributions"] = []
    elif mutation == "missing_source_plan":
        fixture["attributions"][0]["allocations"][0].pop("source_plan_id")
    elif mutation == "pending_sell":
        fixture["broker_orders"][1]["status"] = "pending"
    elif mutation == "excess_qty":
        fixture["attributions"][0]["allocations"][0]["qty"] = 11.0
    elif mutation == "partial_costs":
        fixture["execution_costs"]["sell-1"].pop("slippage_cost")
    elif mutation == "duplicate_mapping":
        fixture["attributions"].append(copy.deepcopy(fixture["attributions"][0]))

    result = _snapshot(fixture)
    operation = result["operations"][0]
    assert operation["status"] == state
    if mutation == "partial_costs":
        assert operation["net_realized_pl"] is None
        assert result["metrics"]["net_realized_pl"] is None
    if mutation == "pending_sell":
        assert "sell_status_not_terminal" in operation["reason_codes"]


def test_partial_exit_and_explicit_multi_lot_exit_never_use_fifo() -> None:
    partial = _valid_fixture()
    partial["broker_orders"][1]["filled_qty"] = 4.0
    partial["fill_fragments"][1]["qty"] = 4.0
    partial["attributions"][0]["allocations"][0]["qty"] = 4.0
    partial_result = _snapshot(partial)
    assert partial_result["denominators"]["partially_closed_lot_count"] == 1
    assert partial_result["denominators"]["open_lot_count"] == 0

    first = _buy("buy-1", symbol="ACME", plan_id="plan-1", source_plan_id="source-plan-1")
    second = _buy("buy-2", symbol="ACME", plan_id="plan-2", source_plan_id="source-plan-2")
    sell = _sell(qty=20.0)
    sell["filled_qty"] = 20.0
    fixture = {
        "broker_orders": [first, second, sell],
        "fill_fragments": [
            _fill("buy-1", "buy-fill-1", lot_id="lot-1", qty=10.0, side="BUY"),
            _fill("buy-2", "buy-fill-2", lot_id="lot-2", qty=10.0, side="BUY"),
            _fill("sell-1", "sell-fill-1", lot_id="lot-1", qty=20.0, side="SELL"),
        ],
        "attributions": [
            {
                "sell_broker_order_id": "sell-1",
                "allocations": [
                    {"buy_broker_order_id": "buy-1", "lot_id": "lot-1", "fill_fragment_id": "buy-fill-1", "qty": 10.0, "source_plan_id": "source-plan-1"},
                    {"buy_broker_order_id": "buy-2", "lot_id": "lot-2", "fill_fragment_id": "buy-fill-2", "qty": 10.0, "source_plan_id": "source-plan-2"},
                ],
            }
        ],
        "execution_costs": {},
    }
    result = _snapshot(fixture)
    assert result["denominators"]["attributed_sell_count"] == 1
    assert result["denominators"]["closed_lot_count"] == 2

    no_mapping = copy.deepcopy(fixture)
    no_mapping["attributions"] = []
    assert _snapshot(no_mapping)["operations"][0]["status"] == "ambiguous"


def test_persistence_is_append_only_captured_at_independent_and_conflicts_separate(tmp_path: Path) -> None:
    store = _store(tmp_path)
    snapshot = _snapshot(_valid_fixture())
    assert persist_canonical_trade_attribution(store, snapshot)["status"] == "inserted"

    repeated = copy.deepcopy(snapshot)
    repeated["captured_at"] = "2026-07-21T18:31:00+00:00"
    assert repeated["content_hash"] == snapshot["content_hash"]
    assert persist_canonical_trade_attribution(store, repeated)["status"] == "idempotent"

    conflict = copy.deepcopy(snapshot)
    conflict["metrics"]["gross_realized_pl"] = 101.0
    conflict["content_hash"] = attribution_mod._stable_hash(conflict)
    outcome = persist_canonical_trade_attribution(store, conflict)
    assert outcome["status"] == "conflict"
    assert read_canonical_trade_attribution(store, SESSION)["metrics"]["gross_realized_pl"] == 100.0
    assert canonical_trade_attribution_digest(store, SESSION)["conflict_events"] == 1


def test_persistence_concurrency_is_inserted_plus_idempotent_without_lock_error(tmp_path: Path) -> None:
    store = _store(tmp_path)
    snapshot = _snapshot(_valid_fixture())
    barrier = threading.Barrier(2)
    results: list[dict[str, Any]] = []

    def worker() -> None:
        local = Store(store.database_path, store.agent_history.agent_logs_dir)
        barrier.wait()
        results.append(persist_canonical_trade_attribution(local, copy.deepcopy(snapshot)))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert len(results) == 2
    assert sorted(item["status"] for item in results) == ["idempotent", "inserted"]


def test_readers_do_not_rebuild_and_collecting_is_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store(tmp_path)
    assert read_canonical_trade_attribution(store, SESSION)["status"] == "collecting"
    snapshot = _snapshot(_valid_fixture())
    persist_canonical_trade_attribution(store, snapshot)
    monkeypatch.setattr(attribution_mod, "build_canonical_trade_attribution", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("rebuild")))
    assert read_canonical_trade_attribution(store, SESSION)["content_hash"] == snapshot["content_hash"]


def test_risk_and_slippage_require_explicit_inputs() -> None:
    assert calculate_slippage(
        side="BUY",
        benchmark_price=100,
        fill_price=101,
        benchmark_at="2026-07-21T15:30:00+00:00",
        filled_at="2026-07-21T15:31:00+00:00",
    )["slippage_bps"] == pytest.approx(100.0)
    assert calculate_slippage(
        side="SELL",
        benchmark_price=100,
        fill_price=101,
        benchmark_at="2026-07-21T15:31:00+00:00",
        filled_at="2026-07-21T15:30:00+00:00",
    )["status"] == "unavailable"
    metrics = calculate_risk_metrics(
        {
            "entry_price": 100,
            "stop_price": 95,
            "entry_qty": 10,
            "net_realized_pl": 25,
            "entry_at": "2026-07-21T15:30:00+00:00",
            "exit_at": "2026-07-21T15:31:00+00:00",
        }
    )
    assert metrics["initial_risk"] == 50.0
    assert metrics["realized_r_multiple"] == 0.5
    assert metrics["holding_seconds"] == 60.0
    assert metrics["holding_sessions"] is None


def test_future_metadata_keeps_broker_payload_byte_equal() -> None:
    base = {
        "symbol": "ACME",
        "side": "buy",
        "notional": 100.0,
        "payload": {"qty": 1.0, "entry_price": 100.0},
    }
    with_metadata = copy.deepcopy(base)
    with_metadata["payload"]["trade_attribution"] = {
        "source_plan_id": "source-plan-1",
        "buy_broker_order_id": "buy-1",
    }
    baseline_request = build_market_order_request(
        base,
        client_order_id="client-1",
        use_bracket_orders=False,
    )
    metadata_request = build_market_order_request(
        with_metadata,
        client_order_id="client-1",
        use_bracket_orders=False,
    )
    assert repr(metadata_request) == repr(baseline_request)
