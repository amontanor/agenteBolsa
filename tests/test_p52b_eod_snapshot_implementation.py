"""P-L52B-W: API productiva, persistencia y consumidores read-only."""

from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from agente_bolsa.storage import Store
from agente_bolsa.tools.canonical_eod_account_snapshot import (
    COST_FIELDS,
    SCHEMA_VERSION,
    build_canonical_eod_account_snapshot,
    canonical_eod_account_snapshot_digest,
    content_hash,
    persist_canonical_eod_account_snapshot,
    read_canonical_eod_account_snapshot,
)

START = "2026-07-21T13:30:00Z"
END = "2026-07-21T20:00:00Z"


def _snapshot(**changes: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "session_date": "2026-07-21",
        "account_id": "paper-account",
        "currency": "USD",
        "window_start_at": START,
        "window_end_at": END,
        "generated_at": END,
        "as_of": END,
        "captured_at": "2026-07-21T20:01:00Z",
        "equity_start": 10_000.0,
        "equity_end": 10_030.0,
        "cash_start": 8_000.0,
        "cash_end": 8_000.0,
        "open_pl_start": 10.0,
        "open_pl_end": 25.0,
        "gross_realized_pl": 15.0,
        "costs": {field: 0.0 for field in COST_FIELDS},
        "external_flow_ledger": [],
        "positions": [{
            "broker_order_id": "buy-1",
            "lot_identity": "lot-1",
            "side": "long",
            "market_value_start": 1_000.0,
            "market_value_end": 1_010.0,
            "currency": "USD",
        }],
        "contributions": [{"broker_order_id": "buy-1", "lot_identity": "lot-1", "amount": 15.0}],
        "benchmark": {
            "symbol": "SPY",
            "window_start_at": START,
            "window_end_at": END,
            "start_at": START,
            "end_at": END,
            "start_price": 500.0,
            "end_price": 505.0,
            "price_basis": "unadjusted_close",
            "quality": "exact",
            "as_of": END,
        },
        "session_count": 5,
        "comparable_session_count": 5,
        "outcomes_matured": True,
    }
    args.update(changes)
    return build_canonical_eod_account_snapshot(**args)


def _store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "state" / "test.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    return store


def test_product_api_preserves_accounting_equation_and_json() -> None:
    snapshot = _snapshot()
    assert snapshot["schema_version"] == SCHEMA_VERSION
    assert snapshot["status"] == "available"
    assert snapshot["event_id"] == "canonical_eod_account_snapshot:2026-07-21"
    assert snapshot["delta_equity"] == 30.0
    assert snapshot["net_realized_pl"] == 15.0
    assert snapshot["delta_open_pl"] == 15.0
    assert snapshot["residual_amount"] == 0.0
    assert snapshot["residual_status"] == "balanced"
    assert snapshot["benchmark"]["comparable"] is True
    json.dumps(snapshot, allow_nan=False)


def test_missing_flows_or_partial_costs_never_become_zero() -> None:
    missing = _snapshot(external_flow_ledger=None, costs=None)
    assert missing["external_cash_flows"] is None
    assert missing["flow_adjusted_return"] is None
    assert missing["net_realized_pl"] is None
    assert missing["residual_amount"] is None
    partial_costs = {field: 0.0 for field in COST_FIELDS if field != "slippage_cost"}
    partial = _snapshot(costs=partial_costs)
    assert partial["net_realized_pl"] is None
    assert partial["coverage"]["cost_coverage"]["status"] == "partial"


def test_p52a_sanitized_loss_does_not_promote_descriptive_realized_pl() -> None:
    snapshot = _snapshot(
        equity_start=10_009.87,
        equity_end=10_000.0,
        cash_start=8_920.0,
        cash_end=8_915.0,
        open_pl_start=0.0,
        open_pl_end=-18.97,
        gross_realized_pl=None,
        costs=None,
        external_flow_ledger=None,
        positions=None,
        contributions=None,
        benchmark={"symbol": "SPY", "start_at": START, "end_at": END, "window_start_at": START, "window_end_at": END, "start_price": 500.0, "end_price": 503.546, "price_basis": None, "quality": "partial"},
        session_count=1,
        comparable_session_count=0,
        outcomes_matured=False,
        descriptive_realized_pl=9.12,
    )
    assert snapshot["delta_equity"] == -9.87
    assert snapshot["cash_ratio_end"] == 0.8915
    assert snapshot["gross_realized_pl"] is None
    assert snapshot["net_realized_pl"] is None
    assert snapshot["residual_amount"] is None
    assert snapshot["descriptive_realized_pl"] == 9.12
    assert snapshot["interpretation"]["cash_opportunity_status"] == "descriptive_only"
    assert snapshot["interpretation"]["causality_status"] == "unavailable"


def test_append_only_reader_idempotency_and_conflict_preserve_original(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _snapshot()
    repeated = _snapshot(captured_at="2026-07-21T20:02:00Z")
    assert first["content_hash"] == repeated["content_hash"]
    assert persist_canonical_eod_account_snapshot(store, first)["status"] == "inserted"
    assert persist_canonical_eod_account_snapshot(store, repeated)["status"] == "idempotent"
    changed = copy.deepcopy(first)
    changed["equity_end"] = 9_999.0
    changed["delta_equity"] = -1.0
    changed["content_hash"] = content_hash(changed)
    conflict = persist_canonical_eod_account_snapshot(store, changed)
    assert conflict["status"] == "conflict"
    original = read_canonical_eod_account_snapshot(store, "2026-07-21")
    assert original["equity_end"] == 10_030.0
    assert len(store.canonical_eod_account_snapshot_conflicts("2026-07-21")) == 1
    assert canonical_eod_account_snapshot_digest(store, "2026-07-21")["conflict_events"] == 1


def test_concurrent_writers_are_inserted_or_idempotent_without_lock_error(tmp_path: Path) -> None:
    _store(tmp_path)
    snapshots = [_snapshot(captured_at=f"2026-07-21T20:0{i}:00Z") for i in (1, 2)]

    def write(snapshot: dict[str, Any]) -> str:
        store = _store(tmp_path)
        return str(persist_canonical_eod_account_snapshot(store, snapshot)["status"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(write, snapshots))
    assert statuses == ["idempotent", "inserted"]
    assert read_canonical_eod_account_snapshot(_store(tmp_path), "2026-07-21")["content_hash"] == snapshots[0]["content_hash"]


def test_collecting_reader_has_null_denominators_and_no_reconstruction(tmp_path: Path) -> None:
    store = _store(tmp_path)
    report = read_canonical_eod_account_snapshot(store, "2026-07-22")
    digest = canonical_eod_account_snapshot_digest(store, "2026-07-22")
    assert report["status"] == "collecting"
    assert report["coverage"] is None
    assert digest["status"] == "collecting"
    assert digest["conflict_events"] == 0
