from __future__ import annotations

from pathlib import Path

from agente_bolsa.storage import Store
from agente_bolsa.tools.canonical_eod_account_snapshot import build_canonical_eod_account_snapshot
from agente_bolsa.tools.cash_flow_ledger import read_cash_flow_ledger, record_cash_flow


def _store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "state" / "test.sqlite3", tmp_path / "logs" / "agents")
    store.ensure_schema()
    return store


def test_deposit_and_withdrawal_sum_signed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert record_cash_flow(
        store, flow_id="f1", kind="deposit", amount=1000.0,
        occurred_at="2026-09-01T10:00:00+00:00",
    )["status"] == "inserted"
    assert record_cash_flow(
        store, flow_id="f2", kind="withdrawal", amount=200.0,
        occurred_at="2026-09-02T10:00:00+00:00",
    )["status"] == "inserted"

    ledger = read_cash_flow_ledger(store, start="2026-09-01T00:00:00+00:00", end="2026-09-03T00:00:00+00:00")

    assert ledger["count"] == 2
    assert ledger["total"] == 800.0
    assert ledger["coverage"]["status"] == "exact"
    assert [flow["flow_id"] for flow in ledger["flows"]] == ["f1", "f2"]


def test_rerecord_is_idempotent_and_rewrite_conflicts(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = {"flow_id": "f1", "kind": "deposit", "amount": 1000.0, "occurred_at": "2026-09-01T10:00:00+00:00"}
    assert record_cash_flow(store, **first)["status"] == "inserted"
    assert record_cash_flow(store, **first)["status"] == "idempotent"

    changed = dict(first, amount=500.0)
    result = record_cash_flow(store, **changed)
    assert result["status"] == "conflict"

    ledger = read_cash_flow_ledger(store)
    assert ledger["total"] == 1000.0
    assert ledger["conflicts"] == 1


def test_invalid_flow_is_rejected_without_write(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert record_cash_flow(
        store, flow_id="bad-kind", kind="gift", amount=10.0, occurred_at="2026-09-01T10:00:00+00:00"
    )["status"] == "rejected"
    assert record_cash_flow(
        store, flow_id="bad-amount", kind="deposit", amount=-5.0, occurred_at="2026-09-01T10:00:00+00:00"
    )["status"] == "rejected"
    assert record_cash_flow(
        store, flow_id="bad-date", kind="deposit", amount=5.0, occurred_at="2026-09-01"
    )["status"] == "rejected"
    assert record_cash_flow(
        store, flow_id="", kind="deposit", amount=5.0, occurred_at="2026-09-01T10:00:00+00:00"
    )["status"] == "rejected"

    assert read_cash_flow_ledger(store)["count"] == 0


def test_window_filters_by_occurred_at(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record_cash_flow(store, flow_id="in", kind="deposit", amount=100.0, occurred_at="2026-09-02T12:00:00+00:00")
    record_cash_flow(store, flow_id="out", kind="deposit", amount=900.0, occurred_at="2026-08-01T12:00:00+00:00")

    ledger = read_cash_flow_ledger(store, start="2026-09-01T00:00:00+00:00", end="2026-09-03T00:00:00+00:00")

    assert ledger["count"] == 1
    assert ledger["total"] == 100.0


def test_ledger_feeds_eod_flow_coverage(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record_cash_flow(store, flow_id="f1", kind="deposit", amount=500.0, occurred_at="2026-09-02T12:00:00+00:00")
    ledger = read_cash_flow_ledger(store, start="2026-09-02T00:00:00+00:00", end="2026-09-03T00:00:00+00:00")

    snapshot = build_canonical_eod_account_snapshot(
        session_date="2026-09-02",
        account_id="paper",
        currency="USD",
        window_start_at="2026-09-02T00:00:00+00:00",
        window_end_at="2026-09-03T00:00:00+00:00",
        generated_at="2026-09-03T00:00:00+00:00",
        as_of="2026-09-03T00:00:00+00:00",
        captured_at="2026-09-03T00:00:00+00:00",
        external_flow_ledger=ledger["flows"],
    )

    assert snapshot["coverage"]["flow_coverage"]["status"] == "exact"
    assert snapshot["external_cash_flows"] == 500.0
