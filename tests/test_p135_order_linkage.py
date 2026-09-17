from __future__ import annotations

from pathlib import Path

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
