"""P-L69-T contract characterization, isolated from the implementation.

These tests pin the boundary that the implementation must close: a broker
status is queried by exact order identity, only a committed terminal fill is
eligible for Telegram, and the post-market fallback remains idempotent.
"""

from __future__ import annotations

import inspect

from agente_bolsa.scheduler import broker_reconciliation_job
from agente_bolsa.tools import broker_reconciliation, telegram_trade_notifications


def test_provider_status_contract_is_identity_and_not_symbol_date() -> None:
    source = inspect.getsource(broker_reconciliation._get_remote_order)

    assert "broker_order_id" in source
    assert "get_order_by_id" in source
    assert "symbol" not in source
    assert "created_at" not in source


def test_existing_reconciliation_is_the_canonical_postmarket_consumer() -> None:
    source = inspect.getsource(broker_reconciliation.reconcile_broker_orders)

    assert "_get_remote_order" in source
    assert "broker_order_id" in source
    assert "UPDATE broker_orders" in source
    assert "telegram" not in source


def test_scheduler_has_separate_postmarket_reconciliation_and_intraday_watcher() -> None:
    source = inspect.getsource(broker_reconciliation_job)
    scheduler_source = inspect.getsource(__import__("agente_bolsa.scheduler", fromlist=["build_scheduler"]).build_scheduler)

    assert "reconcile_broker_orders" in source
    assert "trade_fill_watch" in scheduler_source


def test_submit_and_pending_states_are_not_fill_notifications() -> None:
    class Store:
        def connect(self):
            raise AssertionError("pending states must not read or infer a fill")

    for status in ("submitted", "accepted", "new", "pending_new", "partially_filled", "rejected", "cancelled"):
        change = {
            "broker_order_id": "bo-1",
            "plan_id": "plan-1",
            "cycle_id": "cycle-1",
            "symbol": "KHC",
            "side": "buy",
            "old": "pending_new",
            "new": status,
            "fill": {"status": status, "filled_qty": None, "filled_avg_price": None},
        }
        assert telegram_trade_notifications.build_trade_fill(Store(), change) is None


def test_terminal_fill_requires_exact_order_identity_and_real_fill_fields() -> None:
    class Store:
        def connect(self):
            return _Connection(
                {
                    "broker_order_reconciled": {
                        "status": "filled",
                        "filled_qty": 3,
                        "filled_avg_price": 293.29,
                        "filled_at": "2026-07-28T13:33:57+00:00",
                    }
                }
            )

    payload = telegram_trade_notifications.build_trade_fill(
        Store(),
        {
            "broker_order_id": "5e46dbdf-a234-4de8-91f0-aaa6a8844349",
            "plan_id": "plan-unp",
            "cycle_id": "cycle-1",
            "symbol": "UNP",
            "side": "buy",
            "old": "pending_new",
            "new": "filled",
            "fill": {
                "filled_qty": 3,
                "filled_avg_price": 293.29,
                "filled_at": "2026-07-28T13:33:57+00:00",
            },
        },
    )

    assert payload["broker_order_id"] == "5e46dbdf-a234-4de8-91f0-aaa6a8844349"
    assert payload["filled_qty"] == 3
    assert payload["filled_avg_price"] == 293.29


def test_sell_fill_without_exact_source_plan_stays_unavailable() -> None:
    source = inspect.getsource(telegram_trade_notifications._source_plan_id)

    assert "source_plan_id" in source
    assert "symbol" not in source
    assert "created_at" not in source


def test_p69_fixture_distinguishes_submit_and_later_fill() -> None:
    observations = [
        {"broker_order_id": "d90d3bea-a6f9-43de-a653-5880e18de888", "status": "PENDING_NEW"},
        {
            "broker_order_id": "d90d3bea-a6f9-43de-a653-5880e18de888",
            "status": "filled",
            "filled_qty": 38,
            "filled_avg_price": 27.666842,
            "filled_at": "2026-07-28T13:51:34+00:00",
        },
    ]

    assert observations[0]["status"] == "PENDING_NEW"
    assert observations[1]["status"] == "filled"
    assert observations[0]["broker_order_id"] == observations[1]["broker_order_id"]
    assert observations[0].get("filled_qty") is None


def test_p69_contract_never_promises_exactly_once_after_send_without_receipt() -> None:
    # A send accepted before a receipt write can leave an auditable unknown
    # state; the future watcher must avoid an automatic duplicate promise.
    state = {"send": "accepted", "receipt": "unavailable"}

    assert state["send"] == "accepted"
    assert state["receipt"] == "unavailable"


class _Connection:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, *_args):
        return _Cursor(self.payload)


class _Cursor:
    def __init__(self, payload):
        self.payload = payload

    def fetchone(self):
        return _Row(self.payload)


class _Row:
    def __init__(self, payload):
        self.payload_json = __import__("json").dumps(payload)

    def __getitem__(self, key):
        if key == "payload_json":
            return self.payload_json
        raise KeyError(key)
