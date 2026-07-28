from __future__ import annotations

import copy
import json
import time
import tracemalloc
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.scheduler import _risk_exit_plan
from agente_bolsa.storage import Store
from agente_bolsa.tools.broker_reconciliation import reconcile_broker_orders
from agente_bolsa.tools.canonical_eod_account_snapshot import (
    COST_FIELDS,
    build_canonical_eod_account_snapshot,
    build_from_postmarket_inputs,
)
from agente_bolsa.tools.canonical_operation_telemetry import build_canonical_operation_telemetry
from agente_bolsa.tools.canonical_trade_attribution import build_canonical_trade_attribution
from agente_bolsa.tools.execution import build_market_order_request
from agente_bolsa.tools.exit_lot_provenance import CARRIER_FIELD

SESSION = "2026-07-21"
CAPTURED_AT = datetime(2026, 7, 21, 16, 0, tzinfo=timezone.utc)


def _store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "state" / "combined.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    return store


def _save_buy(store: Store) -> list[dict[str, Any]]:
    plan = {
        "plan_id": "buy-plan-1",
        "cycle_id": "cycle-buy",
        "symbol": "ACME",
        "side": "buy",
        "payload": {"qty": 10, "entry_price": 100, "lot_identity": "lot-1", "position_identity": "position-ACME"},
    }
    fill = {"fill_fragment_id": "buy-fill-1", "broker_order_id": "buy-1", "side": "BUY", "lot_id": "lot-1", "qty": 10}
    store.save_order_plan(
        plan_id="buy-plan-1",
        cycle_id="cycle-buy",
        symbol="ACME",
        side="buy",
        notional=1000,
        approved=True,
        dry_run=True,
        payload=plan,
    )
    store.save_broker_order(
        broker_order_id="buy-1",
        plan_id="buy-plan-1",
        cycle_id="cycle-buy",
        symbol="ACME",
        side="buy",
        status="filled",
        payload={
            "plan": plan,
            "broker_order": {"id": "buy-1", "status": "filled", "qty": 10, "filled_qty": 10, "filled_at": "2026-07-21T15:40:00+00:00"},
            "canonical_fill_fragments": [fill],
        },
    )
    return store.executed_open_buy_lots_by_symbol(position_quantities={"ACME": 10})["ACME"]


def test_e2e_carrier_reconciliation_p48_p51_p52_keeps_exact_contribution_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agente_bolsa.storage._utc_iso", lambda: "2026-07-21T16:05:00+00:00")
    settings = Settings(DATA_DIR=tmp_path)
    store = _store(tmp_path)
    lots = _save_buy(store)
    sell_plan = _risk_exit_plan(
        symbol="ACME",
        notional=1000,
        qty=10,
        current_price=99,
        trigger="stop_loss",
        level=95,
        source_plan={"plan_id": "buy-plan-1", "payload": {"stop_loss": 95, "take_profit": 110}},
        open_buy_lots=lots,
    )
    carrier = sell_plan["payload"][CARRIER_FIELD]
    assert carrier["provenance_quality"] == "exact"
    store.save_order_plan(
        plan_id=sell_plan["plan_id"],
        cycle_id=sell_plan["cycle_id"],
        symbol="ACME",
        side="sell",
        notional=1000,
        approved=True,
        dry_run=True,
        payload=sell_plan,
    )
    costs = {"gross_realized_pl": 100.0, "commissions": 0.5, "regulatory_fees": 0.2, "spread_cost": 0.1, "slippage_cost": 0.3, "other_costs": 0.4}
    store.save_broker_order(
        broker_order_id="sell-1",
        plan_id=sell_plan["plan_id"],
        cycle_id=sell_plan["cycle_id"],
        symbol="ACME",
        side="sell",
        status="pending_new",
        payload={
            "plan": sell_plan,
            "broker_order": {"id": "sell-1", "status": "pending_new", "qty": 10},
            "canonical_fill_fragments": [{"fill_fragment_id": "sell-fill-1", "broker_order_id": "sell-1", "side": "SELL", "lot_id": "lot-1", "qty": 10}],
            "execution_costs": costs,
        },
    )
    remote = SimpleNamespace(
        id="sell-1",
        client_order_id="",
        status="filled",
        filled_qty=10,
        filled_avg_price=101,
        qty=10,
        notional=None,
        submitted_at=None,
        filled_at="2026-07-21T16:00:00+00:00",
        updated_at="2026-07-21T16:00:00+00:00",
    )

    class _Factory:
        def __init__(self, _settings: Settings) -> None:
            pass

        def alpaca_trading_client(self) -> Any:
            return SimpleNamespace(get_order_by_id=lambda _order_id: remote)

    monkeypatch.setattr("agente_bolsa.tools.broker_reconciliation.BrokerClientFactory", _Factory)
    reconciliation = reconcile_broker_orders(settings, store, apply=True, update_learning=False)
    assert reconciliation["changes"][0]["new"] == "filled"

    telemetry = build_canonical_operation_telemetry(store, SESSION, captured_at=CAPTURED_AT)
    attribution = build_canonical_trade_attribution(telemetry, SESSION, captured_at=CAPTURED_AT)
    assert attribution["status"] == "available"
    assert attribution["denominators"]["attributed_sell_count"] == 1
    assert attribution["metrics"]["net_realized_pl"] == pytest.approx(98.5)

    portfolio = SimpleNamespace(account_id="paper", currency="USD", portfolio_value=1000.0, cash=900.0, positions=[], open_orders=[])
    report = {
        "window_start_at": "2026-07-21T13:30:00Z",
        "as_of": "2026-07-21T20:00:00Z",
        "benchmark": None,
    }
    snapshot = build_from_postmarket_inputs(
        SESSION,
        portfolio=portfolio,
        canonical_telemetry=telemetry,
        canonical_trade_attribution=attribution,
        report=report,
        captured_at=CAPTURED_AT,
    )
    assert snapshot["gross_realized_pl"] == 100.0
    assert snapshot["net_realized_pl"] == pytest.approx(98.5)
    assert snapshot["coverage"]["contribution_coverage"]["status"] == "exact"
    assert snapshot["contributions"] == [{"broker_order_id": "buy-1", "lot_identity": "lot-1", "amount": pytest.approx(98.5), "currency": "USD", "origin": "canonical_trade_attribution"}]

    baseline = copy.deepcopy(sell_plan)
    with_carrier = copy.deepcopy(sell_plan)
    baseline["payload"].pop(CARRIER_FIELD, None)
    assert repr(build_market_order_request(baseline, client_order_id="client-sell", use_bracket_orders=False)) == repr(
        build_market_order_request(with_carrier, client_order_id="client-sell", use_bracket_orders=False)
    )


def test_volume_100_sessions_1000_exact_operations_has_no_lock_errors(tmp_path: Path) -> None:
    store = _store(tmp_path)
    start = datetime(2026, 1, 2, 13, 30, tzinfo=timezone.utc)
    statuses: list[str] = []
    event_sizes: list[int] = []
    tracemalloc.start()
    started = time.perf_counter()
    for session_index in range(100):
        session = (start.date() + timedelta(days=session_index)).isoformat()
        window_start = (start + timedelta(days=session_index)).isoformat().replace("+00:00", "Z")
        window_end = (start + timedelta(days=session_index, hours=7)).isoformat().replace("+00:00", "Z")
        positions = [
            {"broker_order_id": f"buy-{session_index:03d}-{op:02d}", "lot_identity": f"lot-{session_index:03d}-{op:02d}", "side": "long", "market_value_start": 100.0, "market_value_end": 101.0, "currency": "USD"}
            for op in range(10)
        ]
        contributions = [
            {"broker_order_id": f"buy-{session_index:03d}-{op:02d}", "lot_identity": f"lot-{session_index:03d}-{op:02d}", "amount": 1.0, "currency": "USD", "origin": "canonical_trade_attribution"}
            for op in range(10)
        ]
        snapshot = build_canonical_eod_account_snapshot(
            session_date=session,
            account_id="paper",
            currency="USD",
            window_start_at=window_start,
            window_end_at=window_end,
            generated_at=window_end,
            as_of=window_end,
            captured_at=window_end,
            equity_start=10000.0,
            equity_end=10010.0,
            cash_start=9000.0,
            cash_end=9000.0,
            open_pl_start=0.0,
            open_pl_end=0.0,
            gross_realized_pl=10.0,
            costs={field: 0.0 for field in COST_FIELDS},
            external_flow_ledger=[],
            positions=positions,
            contributions=contributions,
            benchmark={"symbol": "SPY", "window_start_at": window_start, "window_end_at": window_end, "start_at": window_start, "end_at": window_end, "start_price": 500.0, "end_price": 505.0, "price_basis": "unadjusted_close", "quality": "exact", "as_of": window_end},
            session_count=5,
            comparable_session_count=5,
            outcomes_matured=True,
        )
        result = store.record_canonical_eod_account_snapshot(snapshot, event_id=snapshot["event_id"])
        statuses.append(result["status"])
        event_sizes.append(len(json.dumps(snapshot, sort_keys=True, separators=(",", ":"))))
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    elapsed = time.perf_counter() - started
    db_path = Path(store.database_path)
    wal_path = Path(f"{db_path}-wal")
    with store.connect() as conn:
        event_count = conn.execute("SELECT COUNT(*) FROM agent_events WHERE event_type = 'canonical_eod_account_snapshot'").fetchone()[0]
    metrics = {"sessions": 100, "operations": 1000, "elapsed_seconds": round(elapsed, 3), "peak_bytes": peak, "event_bytes_max": max(event_sizes), "wal_bytes": wal_path.stat().st_size if wal_path.exists() else 0, "event_count": event_count}
    print("P-L52BR1_VOLUME " + json.dumps(metrics, sort_keys=True))
    assert statuses == ["inserted"] * 100
    assert event_count == 100
    assert len(event_sizes) == 100


def test_multilot_and_partial_costs_never_prorate_or_turn_missing_net_into_zero() -> None:
    portfolio = SimpleNamespace(account_id="paper", currency="USD", portfolio_value=1000.0, cash=900.0, positions=[], open_orders=[])
    base = {
        "window_start_at": "2026-07-21T13:30:00Z",
        "as_of": "2026-07-21T20:00:00Z",
        "benchmark": None,
    }
    multilot = {
        "metrics": {"gross_realized_pl": 100.0, "commissions": 0.5, "regulatory_fees": 0.2, "spread_cost": 0.1, "slippage_cost": 0.3, "other_costs": 0.4},
        "operations": [{
            "status": "attributed",
            "net_realized_pl": 98.5,
            "allocations": [
                {"buy_broker_order_id": "buy-a", "lot_id": "lot-a", "qty": 5},
                {"buy_broker_order_id": "buy-b", "lot_id": "lot-b", "qty": 5},
            ],
        }],
    }
    snapshot = build_from_postmarket_inputs(SESSION, portfolio=portfolio, canonical_telemetry={}, canonical_trade_attribution=multilot, report=base, captured_at=CAPTURED_AT)
    assert [item["broker_order_id"] for item in snapshot["contributions"]] == ["buy-a", "buy-b"]
    assert all(item["amount"] is None for item in snapshot["contributions"])
    assert snapshot["coverage"]["contribution_coverage"]["status"] == "unavailable"
    assert snapshot["net_realized_pl"] == pytest.approx(98.5)

    partial_costs = {
        "metrics": {"gross_realized_pl": 100.0, "commissions": 0.5, "regulatory_fees": None, "spread_cost": 0.1, "slippage_cost": 0.3, "other_costs": 0.4},
        "operations": [{
            "status": "attributed",
            "gross_realized_pl": 100.0,
            "net_realized_pl": None,
            "allocations": [{"buy_broker_order_id": "buy-a", "lot_id": "lot-a", "qty": 10}],
        }],
    }
    incomplete = build_from_postmarket_inputs(SESSION, portfolio=portfolio, canonical_telemetry={}, canonical_trade_attribution=partial_costs, report=base, captured_at=CAPTURED_AT)
    assert incomplete["net_realized_pl"] is None
    assert incomplete["contributions"][0]["amount"] is None
    assert incomplete["residual_amount"] is None
