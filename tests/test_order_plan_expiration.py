from datetime import datetime, timezone

from agente_bolsa.storage import (
    ORDER_PLAN_STATUS_EXPIRED,
    ORDER_PLAN_STATUS_PENDING,
    ORDER_PLAN_STATUS_SUBMITTED,
    Store,
)


def test_expire_stale_pending_order_plan_after_session_close(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_order_plan(
        plan_id="plan_old",
        cycle_id="cycle_1",
        symbol="HPE",
        side="buy",
        notional=3158.05,
        approved=True,
        dry_run=True,
        payload={"source": "test"},
    )
    with store.connect() as conn:
        conn.execute(
            """
            UPDATE order_plans
            SET created_at = ?, status_updated_at = ?
            WHERE plan_id = ?
            """,
            ("2026-07-07T20:30:00+00:00", "2026-07-07T20:30:00+00:00", "plan_old"),
        )

    expired = store.expire_stale_pending_order_plans(now=datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc))

    assert [item["plan_id"] for item in expired] == ["plan_old"]
    row = store.order_plans(limit=10)[0]
    assert row["status"] == ORDER_PLAN_STATUS_EXPIRED
    assert row["status_reason"] == "TTL fin de sesion: sesion 2026-07-07 cerrada"


def test_expire_stale_pending_order_plan_keeps_same_session_before_close(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_order_plan(
        plan_id="plan_fresh",
        cycle_id="cycle_1",
        symbol="AAPL",
        side="buy",
        notional=500.0,
        approved=True,
        dry_run=True,
        payload={"source": "test"},
    )
    with store.connect() as conn:
        conn.execute(
            """
            UPDATE order_plans
            SET created_at = ?, status_updated_at = ?
            WHERE plan_id = ?
            """,
            ("2026-07-08T15:00:00+00:00", "2026-07-08T15:00:00+00:00", "plan_fresh"),
        )

    expired = store.expire_stale_pending_order_plans(now=datetime(2026, 7, 8, 18, 30, tzinfo=timezone.utc))

    assert expired == []
    row = store.order_plans(limit=10)[0]
    assert row["status"] == ORDER_PLAN_STATUS_PENDING


def test_save_broker_order_marks_order_plan_submitted(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_order_plan(
        plan_id="plan_exec",
        cycle_id="cycle_1",
        symbol="MSFT",
        side="buy",
        notional=700.0,
        approved=True,
        dry_run=True,
        payload={"source": "test"},
    )

    store.save_broker_order(
        broker_order_id="ord_1",
        plan_id="plan_exec",
        cycle_id="cycle_1",
        symbol="MSFT",
        side="buy",
        status="accepted",
        payload={"source": "broker"},
    )

    row = store.order_plans(limit=10)[0]
    assert row["status"] == ORDER_PLAN_STATUS_SUBMITTED
    assert row["status_reason"] == "broker_order:ord_1"
    assert store.pending_order_plans(limit=10) == []


def test_expire_order_plans_marks_requested_reason(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    for plan_id in ("plan_1", "plan_2"):
        store.save_order_plan(
            plan_id=plan_id,
            cycle_id="cycle_1",
            symbol="HPE",
            side="buy",
            notional=1000.0,
            approved=True,
            dry_run=True,
            payload={"source": "test"},
        )

    changed = store.expire_order_plans(
        ["plan_1", "plan_2"],
        reason="huerfanos pre-P-L9, incluye planes de proceso intruso fuera de presupuesto",
        current_statuses=[ORDER_PLAN_STATUS_PENDING],
    )

    assert changed == 2
    rows = {item["plan_id"]: item for item in store.order_plans(limit=10)}
    assert rows["plan_1"]["status"] == ORDER_PLAN_STATUS_EXPIRED
    assert rows["plan_2"]["status_reason"] == "huerfanos pre-P-L9, incluye planes de proceso intruso fuera de presupuesto"
