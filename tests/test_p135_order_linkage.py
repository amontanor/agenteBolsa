from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import agente_bolsa.storage as storage_module
from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.operational_health import build_production_health_report


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        DATA_DIR=tmp_path,
        DATABASE_PATH=tmp_path / "state" / "test.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "logs" / "agents",
        ALLOW_LIVE_TRADING=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )


def _plan_kwargs(plan_id: str) -> dict:
    return {
        "plan_id": plan_id,
        "cycle_id": "cycle-1",
        "symbol": "AAA",
        "side": "buy",
        "notional": 1000.0,
        "approved": True,
        "dry_run": True,
        "payload": {},
    }


def _order_kwargs(broker_order_id: str, plan_id: str, *, status: str = "filled") -> dict:
    return {
        "broker_order_id": broker_order_id,
        "plan_id": plan_id,
        "cycle_id": "cycle-1",
        "symbol": "AAA",
        "side": "buy",
        "status": status,
        "payload": {},
    }


def test_linked_chain_reports_full_coverage(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.save_order_plan(**_plan_kwargs("plan-1"))
    store.save_broker_order(**_order_kwargs("order-1", "plan-1"))

    summary = store.order_plan_linkage_summary()

    assert summary["total"] == 1
    assert summary["filled"] == 1
    assert summary["filled_with_plan"] == 1
    assert summary["filled_without_plan"] == 0
    assert summary["coverage"] == 1.0


def test_dangling_filled_order_is_legacy_unverified(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    # Orden historica cuyo plan nunca se persistio: se cuenta, no se inventa.
    store.save_broker_order(**_order_kwargs("order-ghost", "plan-missing"))

    summary = store.order_plan_linkage_summary()

    assert summary["filled"] == 1
    assert summary["filled_with_plan"] == 0
    assert summary["filled_without_plan"] == 1
    assert summary["coverage"] == 0.0
    assert summary["unverified_label"] == "legacy_unverified"


def test_empty_store_reports_no_coverage(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()

    summary = store.order_plan_linkage_summary()

    assert summary["total"] == 0
    assert summary["coverage"] is None


def test_aggregate_preserves_cutoff_statuses_and_rows(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.save_order_plan(**_plan_kwargs("plan-filled"))
    store.save_order_plan(**_plan_kwargs("plan-partial"))
    store.save_broker_order(**_order_kwargs("order-filled", "plan-filled", status="FILLED"))
    store.save_broker_order(**_order_kwargs("order-partial", "plan-partial", status="partially_filled"))
    store.save_broker_order(**_order_kwargs("order-ghost", "plan-missing", status="filled"))
    store.save_broker_order(**_order_kwargs("order-cancelled", "plan-missing", status="cancelled"))

    fixed_now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
    cutoff = fixed_now - timedelta(days=2)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is timezone.utc else fixed_now.replace(tzinfo=None)

    monkeypatch.setattr(storage_module, "datetime", FrozenDateTime)
    with store.connect() as conn:
        conn.execute(
            "UPDATE broker_orders SET created_at = CASE broker_order_id "
            "WHEN 'order-filled' THEN ? "
            "WHEN 'order-partial' THEN ? "
            "ELSE ? END",
            (cutoff.isoformat(), (cutoff - timedelta(microseconds=1)).isoformat(), fixed_now.isoformat()),
        )
    before = store.count_broker_orders()

    summary = store.order_plan_linkage_summary(recent_days=2)

    assert summary == {
        "total": 4,
        "filled": 3,
        "filled_with_plan": 2,
        "filled_without_plan": 1,
        "coverage": round(2 / 3, 4),
        "recent": {
            "total": 3,
            "filled": 2,
            "filled_with_plan": 1,
            "filled_without_plan": 1,
            "coverage": 0.5,
        },
        "recent_days": 2,
        "unverified_label": "legacy_unverified",
    }
    assert store.count_broker_orders() == before


def test_missing_database_is_not_created_by_read(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)

    assert not settings.database_path.exists()
    with pytest.raises(sqlite3.OperationalError):
        store.order_plan_linkage_summary()
    assert not settings.database_path.exists()


def test_production_health_includes_linkage_fail_open(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.save_order_plan(**_plan_kwargs("plan-1"))
    store.save_broker_order(**_order_kwargs("order-1", "plan-1"))
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    report = build_production_health_report(settings, store, reports_dir, "p135")
    assert report["summary"]["order_linkage"]["coverage"] == 1.0

    def _boom(*_args, **_kwargs):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(store, "order_plan_linkage_summary", _boom)
    report = build_production_health_report(settings, store, reports_dir, "p135b")
    assert report["summary"]["order_linkage"]["status"] == "unavailable"
