"""P-L48BR1 — QA adversarial y ensayo de integración de P-L48B.

Batería aislada sobre el worktree de ensayo.  Ninguna prueba toca red, broker,
LLM, servicios ni SQLite productiva; todo corre sobre ``tmp_path`` y relojes
explícitos.  Los contadores de llamadas demuestran la fuente única de verdad y
el orden postmarket exigidos por el dictamen.
"""

from __future__ import annotations

import copy
import json
import sqlite3
import threading
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from test_p48b_canonical_operation_telemetry_characterization import _raw_fixture

from agente_bolsa import scheduler
from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools import canonical_operation_telemetry as telemetry_mod
from agente_bolsa.tools.canonical_operation_telemetry import (
    _stable_hash,
    build_canonical_operation_telemetry,
    canonical_operation_telemetry_digest,
    normalize_exit_origin,
    persist_canonical_operation_telemetry,
    read_canonical_operation_telemetry,
)
from agente_bolsa.tools.performance_baseline import build_daily_performance

CAPTURED_AT = datetime(2026, 7, 18, tzinfo=timezone.utc)
SESSION = "2026-07-17"


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        DATA_DIR=tmp_path / "data",
        DATABASE_PATH=tmp_path / "data" / "state" / "test.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "data" / "logs" / "agents",
        TRADING_MODE="paper",
        ALLOW_LIVE_TRADING=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )


def _store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "data" / "state" / "test.sqlite3", tmp_path / "data" / "logs" / "agents")
    store.ensure_schema()
    return store


_ORDER_COLUMNS = {"broker_order_id", "plan_id", "cycle_id", "symbol", "side", "status", "created_at"}


def _seed_store_from_fixture(store: Store, session_date: str, fixture: dict[str, Any]) -> None:
    """Seed local lineage tables so the real producer reads from SQLite."""

    created = f"{session_date}T20:30:00+00:00"
    with store.connect() as conn:
        for order in fixture.get("broker_orders", []):
            payload = {key: value for key, value in order.items() if key not in _ORDER_COLUMNS}
            conn.execute(
                "INSERT INTO broker_orders (broker_order_id, plan_id, cycle_id, symbol, side, status, payload_json, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    order["broker_order_id"],
                    order.get("plan_id") or f"plan-{order['broker_order_id']}",
                    order.get("cycle_id") or "cycle",
                    order["symbol"],
                    order["side"],
                    order["status"],
                    json.dumps(payload),
                    created,
                ),
            )
        for plan in fixture.get("order_plans", []):
            conn.execute(
                "INSERT INTO order_plans (plan_id, cycle_id, symbol, side, notional, approved, dry_run, payload_json, created_at, status)"
                " VALUES (?, ?, ?, ?, ?, 1, 0, ?, ?, 'SUBMITTED')",
                (
                    plan["plan_id"],
                    plan.get("cycle_id") or "cycle",
                    plan.get("symbol") or "X",
                    plan.get("side") or "buy",
                    float(plan.get("notional") or 100.0),
                    json.dumps(plan.get("payload") or {}),
                    created,
                ),
            )
        for recommendation in fixture.get("trade_recommendations", []):
            conn.execute(
                "INSERT INTO trade_recommendations (recommendation_id, cycle_id, symbol, action, confidence, payload_json, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    recommendation["recommendation_id"],
                    recommendation.get("cycle_id") or "cycle",
                    recommendation.get("symbol") or "X",
                    recommendation.get("action") or "buy",
                    float(recommendation.get("confidence") or 0.5),
                    json.dumps(recommendation.get("payload") or {}),
                    created,
                ),
            )
        for signal in fixture.get("signal_outcomes", []):
            conn.execute(
                "INSERT INTO signal_outcomes (signal_id, source_run_id, source, symbol, signal_date, decision,"
                " features_json, gate_json, outcome_json, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    signal["signal_id"],
                    signal.get("source_run_id") or "run",
                    signal.get("source") or "scanner",
                    signal.get("symbol") or "X",
                    signal.get("signal_date") or session_date,
                    signal.get("decision") or "candidate",
                    json.dumps(signal.get("features") or {}),
                    json.dumps(signal.get("gate") or {}),
                    json.dumps(signal.get("outcome") or {}),
                    created,
                    created,
                ),
            )
        for index, fragment in enumerate(fixture.get("fill_fragments", []), 1):
            features = {
                "broker_order_id": fragment.get("broker_order_id"),
                "fragment_id": fragment.get("fragment_id") or f"fragment-{index}",
                "filled_qty": fragment.get("qty"),
            }
            conn.execute(
                "INSERT INTO trade_memory (memory_id, trade_time, trade_date, symbol, side, qty, price, notional,"
                " verdict, features_json, thesis_json, outcome_json, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"memory-{session_date}-{index}",
                    created,
                    session_date,
                    fragment.get("symbol") or "X",
                    fragment.get("side") or "buy",
                    float(fragment.get("qty") or 1.0),
                    float(fragment.get("price") or 100.0),
                    float(fragment.get("qty") or 1.0) * float(fragment.get("price") or 100.0),
                    "pendiente",
                    json.dumps(features),
                    json.dumps({}),
                    json.dumps({}),
                    created,
                    created,
                ),
            )


def _seeded_fixture(session_date: str = SESSION) -> dict[str, Any]:
    """Full lineage fixture matching the 16-17 jul audit denominators."""

    fixture = _raw_fixture()
    fixture["order_plans"] = [
        {"plan_id": f"plan-{order['broker_order_id']}", "cycle_id": order["cycle_id"], "symbol": order["symbol"], "side": order["side"], "payload": {"recommendation_id": f"rec-{order['broker_order_id']}"}}
        for order in fixture["broker_orders"]
    ]
    fixture["trade_recommendations"] = [
        {"recommendation_id": f"rec-{order['broker_order_id']}", "cycle_id": order["cycle_id"], "symbol": order["symbol"], "payload": {"signal_id": order.get("signal_id") or f"signal-{index}"}}
        for index, order in enumerate(fixture["broker_orders"], 1)
    ]
    fixture["signal_outcomes"] = [
        {
            "signal_id": order["signal_id"],
            "symbol": order["symbol"],
            "signal_date": session_date,
            "decision": "candidate",
            "features": {"signal_price": order["signal_price"], "candidate_id": order.get("candidate_id")},
        }
        for order in fixture["broker_orders"]
        if order.get("signal_id")
    ]
    fixture.pop("signal_count", None)
    fixture.pop("candidate_count", None)
    fixture.pop("recommendation_count", None)
    fixture.pop("plan_count", None)
    return fixture


class _Calendar:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def should_run_daily_study(self) -> tuple[bool, Any]:
        class _Status:
            now_market = f"{SESSION}T23:00:00+00:00"

            def as_dict(self) -> dict[str, Any]:
                return {"now_market": self.now_market}

        return True, _Status()


class _Reporter:
    def __init__(self) -> None:
        self.events: list[str] = []

    def emit(self, _agent: str, event_type: str, *_args: Any, **_kwargs: Any) -> None:
        self.events.append(event_type)


def _pmr_stage_events(store: Store) -> list[tuple[str, str]]:
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT payload_json FROM agent_events WHERE event_type = 'postmarket_run' ORDER BY created_at, rowid"
        ).fetchall()
    stages: list[tuple[str, str]] = []
    for row in rows:
        payload = json.loads(row["payload_json"] or "{}")
        stages.append((str(payload.get("stage")), str(payload.get("status"))))
    return stages


def _job_harness(monkeypatch: pytest.MonkeyPatch, store: Store, *, counts: dict[str, int]) -> None:
    """Mock only external/heavy edges; keep the real telemetry path."""

    reporter = _Reporter()
    monkeypatch.setattr(scheduler, "MarketCalendar", _Calendar)
    monkeypatch.setattr(scheduler, "_reporter", lambda *_args, **_kwargs: reporter)

    class _Broker:
        def alpaca_portfolio_snapshot(self) -> None:
            counts["portfolio_snapshots"] += 1
            return None

    monkeypatch.setattr(scheduler, "BrokerClientFactory", lambda *_args, **_kwargs: _Broker())

    def _reconcile(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        counts["reconcile_calls"] += 1
        assert kwargs.get("update_learning") is False
        return {"changes": [], "signal_execution_updates": 0, "learning_execution_updates": 0}

    monkeypatch.setattr(scheduler, "reconcile_broker_orders", _reconcile)

    def _fake_review(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        recorder = kwargs.get("stage_recorder")
        counts["outcome_updates"] += 1
        if recorder:
            recorder("outcome_update", "started")
            recorder("outcome_update", "completed")
            recorder("daily_learning", "started")
            recorder("daily_learning", "completed")
            recorder("postmarket_report", "completed")
        return {"path": "report.json", "summary": {"trades_evaluated": 0}, "proposed_improvements": [], "next_session_guidance": []}

    monkeypatch.setattr(scheduler, "build_post_market_review", _fake_review)
    monkeypatch.setattr(scheduler, "_run_post_market_measurement_pipeline", lambda *_args, **_kwargs: {"path": "measure.json"})
    monkeypatch.setattr(scheduler, "_run_change_watchdog", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scheduler, "_run_macro_thesis", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scheduler, "_run_nightly_retrospective", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scheduler, "_run_hypothesis_factory", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scheduler, "_set_job_status", lambda *_args, **_kwargs: None)

    real_build = scheduler.build_canonical_operation_telemetry
    real_persist = scheduler.persist_canonical_operation_telemetry

    def _build_spy(*args: Any, **kwargs: Any) -> dict[str, Any]:
        counts["build_calls"] += 1
        snapshot = real_build(*args, **kwargs)
        counts.setdefault("built_snapshots", []).append(snapshot)
        return snapshot

    def _persist_spy(*args: Any, **kwargs: Any) -> dict[str, Any]:
        counts["persist_calls"] += 1
        return real_persist(*args, **kwargs)

    monkeypatch.setattr(scheduler, "build_canonical_operation_telemetry", _build_spy)
    monkeypatch.setattr(scheduler, "persist_canonical_operation_telemetry", _persist_spy)

    real_performance = scheduler._persist_daily_performance

    def _performance_spy(*args: Any, **kwargs: Any) -> None:
        counts["performance_calls"] += 1
        counts.setdefault("performance_snapshots", []).append(kwargs.get("canonical_telemetry"))
        return real_performance(*args, **kwargs)

    monkeypatch.setattr(scheduler, "_persist_daily_performance", _performance_spy)


# ---------------------------------------------------------------------------
# QA-1 / QA-2 — fuente única de verdad y orden postmarket
# ---------------------------------------------------------------------------


def test_qa1_qa2_single_snapshot_and_postmarket_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = _store(tmp_path)
    _seed_store_from_fixture(store, SESSION, _seeded_fixture())
    counts: dict[str, int] = {
        "build_calls": 0,
        "persist_calls": 0,
        "reconcile_calls": 0,
        "outcome_updates": 0,
        "portfolio_snapshots": 0,
        "performance_calls": 0,
    }
    _job_harness(monkeypatch, store, counts=counts)

    report = scheduler.post_market_review_job(settings, store, use_llm=False, verbose=False, force=True, trigger="scheduled")

    assert report is not None
    # Fuente única: una construcción y una persistencia por PMR efectivo.
    assert counts["build_calls"] == 1
    assert counts["persist_calls"] == 1
    # Cero segunda reconciliación / outcomes / captura de cartera.
    assert counts["reconcile_calls"] == 1
    assert counts["outcome_updates"] == 1
    assert counts["portfolio_snapshots"] == 1
    # performance_daily reutiliza el mismo objeto (identidad, no reconstrucción).
    assert counts["performance_calls"] == 1
    snapshot = counts["built_snapshots"][0]
    assert counts["performance_snapshots"][0] is snapshot
    assert report["canonical_operation_telemetry"] is snapshot
    # Persistencia canónica insertada una vez.
    assert snapshot["persistence"]["status"] == "inserted"
    events = store.agent_events(event_type_prefix="canonical_operation_telemetry", limit=20)
    assert len([item for item in events if item["event_type"] == "canonical_operation_telemetry"]) == 1
    # Orden efectivo de stages P-L47 (secuencia exacta de hitos).
    stages = _pmr_stage_events(store)
    expected = [
        ("coordination", "started"),
        ("coordination", "completed"),
        ("reconciliation", "started"),
        ("reconciliation", "completed"),
        ("postmarket_report", "started"),
        ("outcome_update", "started"),
        ("outcome_update", "completed"),
        ("daily_learning", "started"),
        ("daily_learning", "completed"),
        ("postmarket_report", "completed"),
        ("canonical_operation_telemetry", "started"),
        ("canonical_operation_telemetry", "completed"),
        ("performance", "started"),
        ("performance", "completed"),
        ("measurement_pipeline", "started"),
        ("measurement_pipeline", "completed"),
        ("thesis", "started"),
        ("thesis", "completed"),
        ("terminal", "completed"),
    ]
    assert stages == expected
    # Denominadores reales de la fixture leídos desde SQLite.
    assert snapshot["denominators"]["broker_order_count"] == 8
    assert snapshot["denominators"]["buy_order_count"] == 7
    assert snapshot["denominators"]["sell_order_count"] == 1
    assert snapshot["denominators"]["fill_fragment_count"] == 16
    assert snapshot["denominators"]["plan_count"] == 8
    # performance_daily persistió los campos canónicos separados.
    rows = store.performance_daily(limit=0)
    assert len(rows) == 1
    payload = rows[0]["payload"] if "payload" in rows[0] else rows[0]
    if not isinstance(payload, dict):
        payload = json.loads(rows[0]["payload_json"])
    assert payload["canonical_buy_order_count"] == 7
    assert payload["canonical_sell_order_count"] == 1
    assert payload["fill_fragment_count"] == 16
    assert payload["signal_count"] == 7


def test_qa2_second_run_after_terminal_completed_is_noop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = _store(tmp_path)
    _seed_store_from_fixture(store, SESSION, _seeded_fixture())
    counts: dict[str, int] = {"build_calls": 0, "persist_calls": 0, "reconcile_calls": 0, "outcome_updates": 0, "portfolio_snapshots": 0, "performance_calls": 0}
    _job_harness(monkeypatch, store, counts=counts)
    first = scheduler.post_market_review_job(settings, store, use_llm=False, verbose=False, force=True, trigger="bootstrap")
    second = scheduler.post_market_review_job(settings, store, use_llm=False, verbose=False, force=True, trigger="scheduled")
    assert first is not None
    assert second is None  # session_already_completed, sin reconstruir telemetría.
    assert counts["build_calls"] == 1
    assert counts["persist_calls"] == 1
    assert counts["reconcile_calls"] == 1
    events = store.agent_events(event_type_prefix="canonical_operation_telemetry", limit=20)
    assert len(events) == 1


def test_qa1_consumers_never_rebuild(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Digest/health/CLI reutilizan el evento persistido; nunca reconstruyen."""

    store = _store(tmp_path)
    snapshot = build_canonical_operation_telemetry(None, SESSION, source_data=_raw_fixture(), captured_at=CAPTURED_AT)
    assert persist_canonical_operation_telemetry(store, snapshot)["status"] == "inserted"

    builds = {"count": 0}
    real_build = telemetry_mod.build_canonical_operation_telemetry

    def _spy(*args: Any, **kwargs: Any) -> dict[str, Any]:
        builds["count"] += 1
        return real_build(*args, **kwargs)

    monkeypatch.setattr(telemetry_mod, "build_canonical_operation_telemetry", _spy)
    from agente_bolsa.continuous_improvement.digest import build_lab_digest
    from agente_bolsa.tools.operational_health import build_operational_health_report

    digest = build_lab_digest(store, days=1, data_dir=tmp_path / "data")
    assert digest["canonical_operation_telemetry"]["status"] == "available"
    settings = _settings(tmp_path)
    health = build_operational_health_report(settings, store, settings.data_dir / "reports", "run-health-qa1")
    assert health["report_health"]["canonical_operation_telemetry"]["status"] == "available"
    reader = read_canonical_operation_telemetry(store, SESSION)
    assert reader["content_hash"] == snapshot["content_hash"]
    session_digest = canonical_operation_telemetry_digest(store, SESSION)
    assert session_digest["status"] == "available"
    assert builds["count"] == 0
    # El mismo objeto persistido alimenta a todos los lectores (mismo hash).
    assert digest["canonical_operation_telemetry"]["content_hash"] == snapshot["content_hash"]
    assert health["report_health"]["canonical_operation_telemetry"]["content_hash"] == snapshot["content_hash"]


# ---------------------------------------------------------------------------
# QA-3 — fallos y comportamiento fail-open
# ---------------------------------------------------------------------------


def test_qa3_build_failure_degrades_to_unavailable_without_raising(tmp_path: Path) -> None:
    class _BrokenStore:
        def read_connection(self) -> Any:
            raise RuntimeError("store roto")

        def trade_memory(self, **_kwargs: Any) -> list[dict[str, Any]]:
            raise RuntimeError("store roto")

    snapshot = build_canonical_operation_telemetry(_BrokenStore(), SESSION, captured_at=CAPTURED_AT)
    assert snapshot["status"] == "unavailable"
    assert any(warning.startswith("producer_failed:") for warning in snapshot["data_quality_warnings"])
    assert snapshot["denominators"]["broker_order_count"] is None
    assert snapshot["content_hash"]


def test_qa3_persistence_failure_is_fail_open_and_terminal_is_recorded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = _store(tmp_path)
    _seed_store_from_fixture(store, SESSION, _seeded_fixture())
    counts: dict[str, int] = {"build_calls": 0, "persist_calls": 0, "reconcile_calls": 0, "outcome_updates": 0, "portfolio_snapshots": 0, "performance_calls": 0}
    _job_harness(monkeypatch, store, counts=counts)

    def _failing_persist(*_args: Any, **_kwargs: Any) -> None:
        counts["persist_calls"] += 1
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(scheduler, "persist_canonical_operation_telemetry", _failing_persist)
    report = scheduler.post_market_review_job(settings, store, use_llm=False, verbose=False, force=True, trigger="scheduled")
    assert report is not None  # el fallo telemétrico no tumbó el PMR.
    stages = _pmr_stage_events(store)
    assert stages[-1] == ("terminal", "completed")
    snapshot = report["canonical_operation_telemetry"]
    assert any(warning.startswith("persistence_failed:") for warning in snapshot["data_quality_warnings"])
    # performance_daily siguió degradando solo lo telemétrico, nunca a cero.
    assert counts["performance_calls"] == 1
    assert counts["reconcile_calls"] == 1  # sin segunda reconciliación.


def test_qa3_serialization_failure_is_caught_by_caller(tmp_path: Path) -> None:
    store = _store(tmp_path)
    snapshot = build_canonical_operation_telemetry(None, SESSION, source_data=_raw_fixture(), captured_at=CAPTURED_AT)
    poisoned = copy.deepcopy(snapshot)
    circular: dict[str, Any] = {"broker_order_id": "x"}
    circular["self"] = circular  # referencia circular: la serialización falla siempre.
    poisoned["operations"] = [circular]
    with pytest.raises(ValueError):
        persist_canonical_operation_telemetry(store, poisoned)
    # La base queda intacta y reintentable.
    assert persist_canonical_operation_telemetry(store, snapshot)["status"] == "inserted"


def test_qa3_locked_sqlite_raises_catchable_error_and_recovers(tmp_path: Path) -> None:
    store = _store(tmp_path)
    snapshot = build_canonical_operation_telemetry(None, SESSION, source_data=_raw_fixture(), captured_at=CAPTURED_AT)
    blocker = sqlite3.connect(str(tmp_path / "data" / "state" / "test.sqlite3"), timeout=5)
    blocker.execute("BEGIN IMMEDIATE")
    blocker.execute("CREATE TABLE IF NOT EXISTS lock_probe (id INTEGER)")
    try:
        with pytest.raises(sqlite3.OperationalError):
            persist_canonical_operation_telemetry(store, snapshot)
    finally:
        blocker.rollback()
        blocker.close()
    # Retry tras liberar el bloqueo: inserta exactamente una vez.
    assert persist_canonical_operation_telemetry(store, snapshot)["status"] == "inserted"
    assert persist_canonical_operation_telemetry(store, copy.deepcopy(snapshot))["status"] == "idempotent"


def test_qa3_invalid_payload_and_wrong_hash_read_as_legacy(tmp_path: Path) -> None:
    store = _store(tmp_path)
    created = f"{SESSION}T21:00:00+00:00"
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO agent_events (event_id, agent, event_type, cycle_id, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (f"canonical_operation_telemetry:{SESSION}", "postmarket_telemetry", "canonical_operation_telemetry", None, "not-json{{{", created),
        )
    report = read_canonical_operation_telemetry(store, SESSION)
    assert report["status"] == "legacy_without_canonical_telemetry"
    assert report["denominators"] is None

    store2 = Store(tmp_path / "data2" / "state" / "test.sqlite3", tmp_path / "data2" / "logs")
    store2.ensure_schema()
    snapshot = build_canonical_operation_telemetry(None, SESSION, source_data=_raw_fixture(), captured_at=CAPTURED_AT)
    tampered = copy.deepcopy(snapshot)
    tampered["denominators"]["broker_order_count"] = 99  # hash ya no coincide
    with store2.connect() as conn:
        conn.execute(
            "INSERT INTO agent_events (event_id, agent, event_type, cycle_id, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (f"canonical_operation_telemetry:{SESSION}", "postmarket_telemetry", "canonical_operation_telemetry", None, json.dumps(tampered), created),
        )
    assert read_canonical_operation_telemetry(store2, SESSION)["status"] == "legacy_without_canonical_telemetry"

    store3 = Store(tmp_path / "data3" / "state" / "test.sqlite3", tmp_path / "data3" / "logs")
    store3.ensure_schema()
    wrong_schema = copy.deepcopy(snapshot)
    wrong_schema["schema_version"] = "p-l48b.canonical-operation-telemetry.v0"
    wrong_schema["content_hash"] = _stable_hash(wrong_schema)
    with store3.connect() as conn:
        conn.execute(
            "INSERT INTO agent_events (event_id, agent, event_type, cycle_id, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (f"canonical_operation_telemetry:{SESSION}", "postmarket_telemetry", "canonical_operation_telemetry", None, json.dumps(wrong_schema), created),
        )
    assert read_canonical_operation_telemetry(store3, SESSION)["status"] == "legacy_without_canonical_telemetry"


def test_qa3_digest_read_failure_degrades_health_not_trading(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = _store(tmp_path)
    from agente_bolsa.tools import operational_health

    def _broken_digest(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("digest roto")

    monkeypatch.setattr(
        "agente_bolsa.tools.canonical_operation_telemetry.canonical_operation_telemetry_digest",
        _broken_digest,
    )
    settings = _settings(tmp_path)
    report = operational_health.build_operational_health_report(settings, store, settings.data_dir / "reports", "run-health-qa3")
    assert report["report_health"]["canonical_operation_telemetry"]["status"] == "degraded_observability"
    assert report["report_health"]["canonical_operation_telemetry"]["denominators"] is None


def test_qa3_real_operational_error_is_not_hidden_as_telemetry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = _store(tmp_path)
    counts: dict[str, int] = {"build_calls": 0, "persist_calls": 0, "reconcile_calls": 0, "outcome_updates": 0, "portfolio_snapshots": 0, "performance_calls": 0}
    _job_harness(monkeypatch, store, counts=counts)

    def _failing_reconcile(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("broker reconciliation failed")

    monkeypatch.setattr(scheduler, "reconcile_broker_orders", _failing_reconcile)
    report = scheduler.post_market_review_job(settings, store, use_llm=False, verbose=False, force=True, trigger="scheduled")
    assert report is None
    stages = _pmr_stage_events(store)
    assert ("reconciliation", "failed") in stages
    assert stages[-1] == ("terminal", "failed")
    # Nunca se construyó telemetría para ocultar el fallo operativo.
    assert counts["build_calls"] == 0
    events = store.agent_events(event_type_prefix="canonical_operation_telemetry", limit=20)
    assert events == []


# ---------------------------------------------------------------------------
# QA-4 — idempotencia y revisiones
# ---------------------------------------------------------------------------


def test_qa4_json_key_reorder_does_not_change_hash() -> None:
    snapshot = build_canonical_operation_telemetry(None, SESSION, source_data=_raw_fixture(), captured_at=CAPTURED_AT)

    def _reorder(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: _reorder(value[key]) for key in sorted(value, reverse=True)}
        if isinstance(value, list):
            return [_reorder(item) for item in value]
        return value

    reordered = json.loads(json.dumps(_reorder(snapshot)))
    assert _stable_hash(reordered) == snapshot["content_hash"]


def test_qa4_two_processes_same_content_single_event(tmp_path: Path) -> None:
    db = tmp_path / "data" / "state" / "test.sqlite3"
    store_a = Store(db, tmp_path / "data" / "logs")
    store_a.ensure_schema()
    store_b = Store(db, tmp_path / "data" / "logs")
    one = build_canonical_operation_telemetry(None, SESSION, source_data=_raw_fixture(), captured_at=CAPTURED_AT)
    two = build_canonical_operation_telemetry(None, SESSION, source_data=_raw_fixture(), captured_at=datetime(2026, 7, 19, tzinfo=timezone.utc))
    assert one["content_hash"] == two["content_hash"]
    assert persist_canonical_operation_telemetry(store_a, one)["status"] == "inserted"
    assert persist_canonical_operation_telemetry(store_b, two)["status"] == "idempotent"
    events = store_a.agent_events(event_type_prefix="canonical_operation_telemetry", limit=20)
    assert len(events) == 1


def test_qa4_concurrent_identical_and_distinct_content(tmp_path: Path) -> None:
    db = tmp_path / "data" / "state" / "test.sqlite3"
    store = Store(db, tmp_path / "data" / "logs")
    store.ensure_schema()
    base = build_canonical_operation_telemetry(None, SESSION, source_data=_raw_fixture(), captured_at=CAPTURED_AT)
    changed = copy.deepcopy(base)
    changed["data_quality_warnings"] = ["economic-content-changed"]
    changed["content_hash"] = _stable_hash(changed)
    assert changed["content_hash"] != base["content_hash"]

    barrier = threading.Barrier(3)
    results: list[dict[str, Any]] = []

    def _writer(payload: dict[str, Any]) -> None:
        local = Store(db, tmp_path / "data" / "logs")
        barrier.wait()
        results.append(persist_canonical_operation_telemetry(local, payload))

    threads = [threading.Thread(target=_writer, args=(copy.deepcopy(base),)), threading.Thread(target=_writer, args=(copy.deepcopy(changed),))]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    statuses = sorted(result["status"] for result in results)
    assert statuses == ["conflict", "inserted"]
    # El original ganador se conserva; el perdedor queda como conflicto auditable.
    reader = read_canonical_operation_telemetry(store, SESSION)
    assert reader["status"] == "available"
    conflicts = store.agent_events(event_type_prefix="canonical_operation_telemetry_conflict", limit=20)
    assert len(conflicts) == 1
    # Conflicto no cuenta como snapshot válido.
    valid = store.agent_events(event_type_prefix="canonical_operation_telemetry", limit=20)
    assert len([item for item in valid if item["event_type"] == "canonical_operation_telemetry"]) == 1

    # Repetición concurrente idéntica: exactamente un insert y un idempotente.
    store2 = Store(tmp_path / "b" / "state" / "test.sqlite3", tmp_path / "b" / "logs")
    store2.ensure_schema()
    barrier2 = threading.Barrier(3)
    results2: list[dict[str, Any]] = []

    def _writer2() -> None:
        local = Store(tmp_path / "b" / "state" / "test.sqlite3", tmp_path / "b" / "logs")
        barrier2.wait()
        results2.append(persist_canonical_operation_telemetry(local, copy.deepcopy(base)))

    threads2 = [threading.Thread(target=_writer2), threading.Thread(target=_writer2)]
    for thread in threads2:
        thread.start()
    barrier2.wait()
    for thread in threads2:
        thread.join()
    assert sorted(result["status"] for result in results2) == ["idempotent", "inserted"]


def test_qa4_no_replace_semantics_anywhere(tmp_path: Path) -> None:
    """Repetición nunca sobrescribe: el payload persistido permanece byte a byte."""

    store = _store(tmp_path)
    snapshot = build_canonical_operation_telemetry(None, SESSION, source_data=_raw_fixture(), captured_at=CAPTURED_AT)
    assert persist_canonical_operation_telemetry(store, snapshot)["status"] == "inserted"
    with store.connect() as conn:
        before = conn.execute("SELECT payload_json, created_at FROM agent_events WHERE event_id = ?", (f"canonical_operation_telemetry:{SESSION}",)).fetchone()
    later = copy.deepcopy(snapshot)
    later["captured_at"] = "2026-07-19T00:00:00+00:00"
    assert persist_canonical_operation_telemetry(store, later)["status"] == "idempotent"
    with store.connect() as conn:
        after = conn.execute("SELECT payload_json, created_at FROM agent_events WHERE event_id = ?", (f"canonical_operation_telemetry:{SESSION}",)).fetchone()
    assert dict(before) == dict(after)


# ---------------------------------------------------------------------------
# QA-5 — unidad canónica y fragmentación adversarial
# ---------------------------------------------------------------------------


def _order(**overrides: Any) -> dict[str, Any]:
    base = {
        "broker_order_id": "bo-1",
        "client_order_id": "client-1",
        "symbol": "X",
        "side": "buy",
        "status": "filled",
        "cycle_id": "cycle",
        "submitted_qty": 10,
        "filled_qty": 10,
        "signal_at": "2026-07-17T13:45:00+00:00",
        "plan_created_at": "2026-07-17T13:55:00+00:00",
    }
    base.update(overrides)
    return base


def test_qa5_repeated_fragments_warn_without_inflating_operations() -> None:
    fixture = {
        "broker_orders": [_order()],
        "fill_fragments": [
            {"broker_order_id": "bo-1", "fragment_id": "frag-1", "qty": 4},
            {"broker_order_id": "bo-1", "fragment_id": "frag-1", "qty": 4},
        ],
    }
    result = build_canonical_operation_telemetry(None, SESSION, source_data=fixture, captured_at=CAPTURED_AT)
    assert result["denominators"]["broker_order_count"] == 1
    assert result["denominators"]["fill_fragment_count"] == 2
    assert "duplicate_fill_fragments" in result["operations"][0]["warnings"]


@pytest.mark.parametrize("qtys", [(6, 6), (2, 2)])
def test_qa5_fragment_sum_mismatch_never_rewrites_filled_qty(qtys: tuple[int, int]) -> None:
    # filled_qty procede exclusivamente de la autoridad de reconciliación.
    order = _order()
    order["broker_order_reconciled"] = {"reconciliation_status": "reconciled_filled", "filled_qty": 10}
    fixture = {
        "broker_orders": [order],
        "fill_fragments": [
            {"broker_order_id": "bo-1", "fragment_id": "frag-1", "qty": qtys[0]},
            {"broker_order_id": "bo-1", "fragment_id": "frag-2", "qty": qtys[1]},
        ],
    }
    result = build_canonical_operation_telemetry(None, SESSION, source_data=fixture, captured_at=CAPTURED_AT)
    operation = result["operations"][0]
    assert operation["filled_qty"] == 10  # la suma de fragmentos jamás inventa el fill.
    assert operation["fill_fragment_count"] == 2


def test_qa5_fragments_without_broker_order_id_never_join_by_symbol() -> None:
    fixture = {
        "broker_orders": [_order(symbol="VTR")],
        "fill_fragments": [
            {"broker_order_id": None, "fragment_id": "huerfano", "qty": 5, "symbol": "VTR"},
            {"fragment_id": "sin-id", "qty": 3, "symbol": "VTR"},
        ],
    }
    result = build_canonical_operation_telemetry(None, SESSION, source_data=fixture, captured_at=CAPTURED_AT)
    operation = result["operations"][0]
    assert operation["symbol"] == "VTR"
    # Cero unión por símbolo/fecha: sin enlace exacto no hay evidencia (null, no cero inventado).
    assert operation["fill_fragment_count"] is None


def test_qa5_two_orders_same_symbol_and_rebuy_stay_separate() -> None:
    fixture = {
        "broker_orders": [
            _order(broker_order_id="bo-a", symbol="VTR", client_order_id="c-a"),
            _order(broker_order_id="bo-b", symbol="VTR", client_order_id="c-b"),
            _order(broker_order_id="bo-c", symbol="VTR", client_order_id="c-c", cycle_id="cycle-2"),
        ],
        "fill_fragments": [],
    }
    result = build_canonical_operation_telemetry(None, SESSION, source_data=fixture, captured_at=CAPTURED_AT)
    assert result["denominators"]["broker_order_count"] == 3
    assert {item["broker_order_id"] for item in result["operations"]} == {"bo-a", "bo-b", "bo-c"}


def test_qa5_duplicate_broker_and_client_order_ids() -> None:
    duplicated = _order()
    fixture = {
        "broker_orders": [_order(), copy.deepcopy(duplicated), _order(broker_order_id="bo-2", client_order_id="client-1")],
        "fill_fragments": [],
    }
    result = build_canonical_operation_telemetry(None, SESSION, source_data=fixture, captured_at=CAPTURED_AT)
    assert result["denominators"]["broker_order_count"] == 2
    warnings = result["data_quality_warnings"]
    assert any("duplicate_broker_order_id:bo-1" in warning for warning in warnings)
    assert any("duplicate_client_order_id:client-1" in warning for warning in warnings)


def test_qa5_partial_sell_and_cancelled_with_spurious_fragment() -> None:
    partial = _order(broker_order_id="bo-sell", side="sell", submitted_qty=10, raw_exit_trigger="manual")
    partial["broker_order_reconciled"] = {"reconciliation_status": "reconciled_filled", "filled_qty": 4}
    fixture = {
        "broker_orders": [
            partial,
            _order(broker_order_id="bo-cancel", status="cancelled", filled_qty=None),
        ],
        "fill_fragments": [{"broker_order_id": "bo-cancel", "fragment_id": "espurio", "qty": 10}],
    }
    result = build_canonical_operation_telemetry(None, SESSION, source_data=fixture, captured_at=CAPTURED_AT)
    operations = {item["broker_order_id"]: item for item in result["operations"]}
    assert operations["bo-sell"]["filled_qty"] == 4
    assert operations["bo-sell"]["side"] == "sell"
    # El fragmento espurio no convierte la cancelada en filled.
    assert operations["bo-cancel"]["reconciliation_status"] == "reconciled_rejected"
    assert operations["bo-cancel"]["fill_fragment_count"] == 1
    assert result["execution"]["cancelled_count"] == 1
    assert result["execution"]["filled_count"] == 1


def test_qa5_full_fixture_denominators_from_seeded_store(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed_store_from_fixture(store, SESSION, _seeded_fixture())
    result = build_canonical_operation_telemetry(store, SESSION, captured_at=CAPTURED_AT)
    assert result["denominators"] == {
        "broker_order_count": 8,
        "buy_order_count": 7,
        "sell_order_count": 1,
        "fill_fragment_count": 16,
        "signal_count": 7,
        "candidate_count": 7,
        "recommendation_count": 8,
        "plan_count": 8,
    }


# ---------------------------------------------------------------------------
# QA-6 — ANET y atribución de salidas
# ---------------------------------------------------------------------------


def test_qa6_anet_full_attribution() -> None:
    result = build_canonical_operation_telemetry(None, SESSION, source_data=_raw_fixture(), captured_at=CAPTURED_AT)
    anet = next(item for item in result["operations"] if item["symbol"] == "ANET")
    assert anet["broker_order_id"] == "bo-anet-17"
    assert result["denominators"]["broker_order_count"] == 8
    assert result["denominators"]["sell_order_count"] == 1
    assert anet["fill_fragment_count"] == 2
    assert anet["raw_exit_trigger"] == "stop_loss"
    assert anet["normalized_exit_origin"] == "automatic_stop_loss"
    assert result["exits"] == {
        "automatic_exit_count": 1,
        "manual_exit_count": 0,
        "unknown_exit_origin_count": 0,
        "by_normalized_origin": {"automatic_stop_loss": 1},
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("stop_loss", "automatic_stop_loss"),
        ("take_profit", "automatic_take_profit"),
        ("trailing_stop", "automatic_trailing_stop"),
        ("time_stop_v2", "automatic_time_stop"),
        ("manual", "manual"),
        ("manual_exit", "manual"),
        ("unknown", "unknown_exit_origin"),
        ("not-a-trigger", "unknown_exit_origin"),
        ("", "unknown_exit_origin"),
        (None, "unknown_exit_origin"),
        ("  STOP_LOSS  ", "automatic_stop_loss"),
    ],
)
def test_qa6_exit_normalization_matrix(raw: Any, expected: str) -> None:
    assert normalize_exit_origin(raw) == expected


def test_qa6_missing_invalid_nested_and_conflicting_triggers() -> None:
    # Ausente: unknown pero jamás inventado.
    missing = build_canonical_operation_telemetry(
        None, SESSION, source_data={"broker_orders": [_order(side="sell")], "fill_fragments": []}, captured_at=CAPTURED_AT
    )
    assert missing["operations"][0]["raw_exit_trigger"] is None
    assert missing["operations"][0]["normalized_exit_origin"] == "unknown_exit_origin"
    # Anidado: se encuentra en bloques de linaje conocidos sin unión por símbolo.
    nested_order = _order(side="sell", broker_order_id="bo-nested")
    nested_order["payload"] = {"plan": {"payload": {"risk_decision": {"checks": {"trigger": "take_profit"}}}}}
    nested = build_canonical_operation_telemetry(
        None, SESSION, source_data={"broker_orders": [nested_order], "fill_fragments": []}, captured_at=CAPTURED_AT
    )
    assert nested["operations"][0]["normalized_exit_origin"] == "automatic_take_profit"
    # Conflictivo: el campo explícito de la orden tiene autoridad sobre el plan.
    conflict_order = _order(side="sell", broker_order_id="bo-conflict", raw_exit_trigger="stop_loss")
    conflict_order["payload"] = {"exit_trigger": "take_profit"}
    conflict = build_canonical_operation_telemetry(
        None,
        SESSION,
        source_data={
            "broker_orders": [conflict_order],
            "order_plans": [{"plan_id": "plan-bo-conflict", "payload": {"exit_trigger": "manual"}}],
            "fill_fragments": [],
        },
        captured_at=CAPTURED_AT,
    )
    operation = conflict["operations"][0]
    assert operation["raw_exit_trigger"] == "stop_loss"
    assert operation["normalized_exit_origin"] == "automatic_stop_loss"


def test_qa6_authority_priority_is_deterministic() -> None:
    """Prioridad: raw_exit_trigger > exit_trigger > trigger; nivel externo antes que anidado."""

    order = _order(side="sell", broker_order_id="bo-priority", exit_trigger="trailing_stop", trigger="manual")
    result = build_canonical_operation_telemetry(None, SESSION, source_data={"broker_orders": [order], "fill_fragments": []}, captured_at=CAPTURED_AT)
    assert result["operations"][0]["raw_exit_trigger"] == "trailing_stop"
    again = build_canonical_operation_telemetry(None, SESSION, source_data={"broker_orders": [order], "fill_fragments": []}, captured_at=CAPTURED_AT)
    assert again["content_hash"] == result["content_hash"]


# ---------------------------------------------------------------------------
# QA-7 — performance_daily y consumidores
# ---------------------------------------------------------------------------


class _PerformanceStore:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    def performance_daily(self, *, limit: int) -> list[dict[str, Any]]:
        return []

    def signal_outcomes(self, **_kwargs: Any) -> list[dict[str, Any]]:
        return self.rows

    def continuous_improvement_applied_changes(self, **_kwargs: Any) -> list[dict[str, Any]]:
        return []


def test_qa7_performance_publishes_separate_denominators() -> None:
    telemetry = build_canonical_operation_telemetry(None, SESSION, source_data=_raw_fixture(), captured_at=CAPTURED_AT)
    legacy_rows = [{"signal_date": SESSION, "decision": "candidate"} for _ in range(576)]
    payload = build_daily_performance(_PerformanceStore(legacy_rows), object(), SESSION, canonical_telemetry=telemetry)
    assert payload["signal_count"] == 7
    assert payload["candidate_count"] == 7
    assert payload["canonical_buy_order_count"] == 7
    assert payload["canonical_sell_order_count"] == 1
    assert payload["fill_fragment_count"] == 16
    # Contrato documentado: los nombres legacy reflejan operaciones canónicas.
    assert payload["buys"] == 7
    assert payload["sells"] == 1
    # signal_count jamás sustituye compras; fragmentos jamás son ventas.
    assert payload["signals"] == 7  # dominio señal
    assert payload["process_metrics"]["legacy_actionable_signal_count"] == 0
    assert payload["process_metrics"]["fill_fragment_count"] == 16


def test_qa7_legacy_base_without_telemetry_keeps_legacy_counts() -> None:
    legacy_rows = [{"signal_date": SESSION, "decision": "candidate"} for _ in range(576)]
    payload = build_daily_performance(_PerformanceStore(legacy_rows), object(), SESSION, canonical_telemetry=None)
    assert payload["signals"] == 576
    assert payload["buys"] == 0
    assert payload["sells"] == 0
    assert payload["signal_count"] == 576
    assert payload["candidate_count"] is None
    assert payload["fill_fragment_count"] is None


def test_qa7_unavailable_telemetry_degrades_to_null_never_zero() -> None:
    class _BrokenStore:
        def read_connection(self) -> Any:
            raise RuntimeError("store roto")

        def trade_memory(self, **_kwargs: Any) -> list[dict[str, Any]]:
            raise RuntimeError("store roto")

    unavailable = build_canonical_operation_telemetry(_BrokenStore(), SESSION, captured_at=CAPTURED_AT)
    assert unavailable["status"] == "unavailable"
    assert unavailable["denominators"]["buy_order_count"] is None
    payload = build_daily_performance(_PerformanceStore(), object(), SESSION, canonical_telemetry=unavailable)
    assert payload["signal_count"] is None
    assert payload["candidate_count"] is None
    assert payload["canonical_buy_order_count"] is None
    assert payload["canonical_sell_order_count"] is None
    assert payload["fill_fragment_count"] is None
    assert payload["buys"] is None and payload["sells"] is None and payload["signals"] is None


def test_qa7_partial_telemetry_keeps_available_domains() -> None:
    telemetry = build_canonical_operation_telemetry(None, SESSION, source_data={"broker_orders": [_order()], "fill_fragments": []}, captured_at=CAPTURED_AT)
    assert telemetry["status"] == "available"
    assert telemetry["denominators"]["signal_count"] is None
    payload = build_daily_performance(_PerformanceStore(), object(), SESSION, canonical_telemetry=telemetry)
    assert payload["canonical_buy_order_count"] == 1
    assert payload["signal_count"] is None
    assert payload["candidate_count"] is None


# ---------------------------------------------------------------------------
# QA-8 — reconciliación
# ---------------------------------------------------------------------------


def test_qa8_pending_to_observed_to_terminal_filled_timeline() -> None:
    base = _order(status="PENDING_NEW", filled_qty=None, first_fill_at=None)
    submitted = build_canonical_operation_telemetry(None, SESSION, source_data={"broker_orders": [base], "fill_fragments": []}, captured_at=CAPTURED_AT)
    assert submitted["operations"][0]["reconciliation_status"] == "pending_local"

    observed = copy.deepcopy(base)
    observed["position_observed"] = True
    middle = build_canonical_operation_telemetry(None, SESSION, source_data={"broker_orders": [observed], "fill_fragments": []}, captured_at=CAPTURED_AT)
    assert middle["operations"][0]["reconciliation_status"] == "position_observed_without_exact_order_link"
    assert middle["execution"]["position_observed_without_exact_order_link_count"] == 1
    assert middle["execution"]["filled_count"] == 0

    terminal = copy.deepcopy(base)
    terminal["status"] = "filled"
    terminal["reconciliation_status"] = "reconciled_filled"
    terminal["broker_order_reconciled"] = {
        "reconciliation_status": "reconciled_filled",
        "reconciliation_terminal_at": "2026-07-17T20:20:41.194830+00:00",
        "filled_qty": 10,
    }
    done = build_canonical_operation_telemetry(None, SESSION, source_data={"broker_orders": [terminal], "fill_fragments": [{"broker_order_id": "bo-1", "fragment_id": "f1", "qty": 10}]}, captured_at=CAPTURED_AT)
    assert done["operations"][0]["reconciliation_status"] == "reconciled_filled"
    assert done["operations"][0]["filled_qty"] == 10
    assert done["execution"]["filled_count"] == 1


def test_qa8_same_symbol_position_does_not_confirm_identity() -> None:
    fixture = {
        "broker_orders": [_order(symbol="BBY", status="PENDING_NEW", position_observed=True, filled_qty=None)],
        "fill_fragments": [{"broker_order_id": "otra-orden", "fragment_id": "fx", "qty": 2, "symbol": "BBY"}],
    }
    result = build_canonical_operation_telemetry(None, SESSION, source_data=fixture, captured_at=CAPTURED_AT)
    operation = result["operations"][0]
    assert operation["reconciliation_status"] == "position_observed_without_exact_order_link"
    # El fragmento de otra orden jamás enlaza por símbolo: sin evidencia (null).
    assert operation["fill_fragment_count"] is None
    # Una posición observada jamás inventa first_fill_at.
    assert operation["freshness"]["first_fill_at"] is None


def test_qa8_rejected_cancelled_never_become_filled_and_unavailable_never_zero() -> None:
    fixture = {
        "broker_orders": [
            _order(broker_order_id="bo-rej", status="rejected"),
            _order(broker_order_id="bo-can", status="cancelled"),
            _order(broker_order_id="bo-mystery", status="¿unknown_state?"),
        ],
        "fill_fragments": [],
    }
    result = build_canonical_operation_telemetry(None, SESSION, source_data=fixture, captured_at=CAPTURED_AT)
    statuses = {item["broker_order_id"]: item["reconciliation_status"] for item in result["operations"]}
    assert statuses["bo-rej"] == "reconciled_rejected"
    assert statuses["bo-can"] == "reconciled_rejected"
    assert statuses["bo-mystery"] == "reconciliation_unavailable"
    assert result["execution"]["filled_count"] == 0
    assert result["execution"]["reconciliation_unavailable_count"] == 1


def test_qa8_later_unrelated_reconciliation_does_not_replace_terminal() -> None:
    order = _order(status="filled", reconciliation_status="reconciled_filled")
    order["broker_order_reconciled"] = {
        "reconciliation_status": "reconciled_filled",
        "reconciliation_terminal_at": "2026-07-17T20:20:41.194830+00:00",
        "filled_qty": 10,
    }
    order["other_reconciliation_event_at"] = "2026-07-17T23:59:59+00:00"
    first = build_canonical_operation_telemetry(None, SESSION, source_data={"broker_orders": [order], "fill_fragments": []}, captured_at=CAPTURED_AT)
    second = build_canonical_operation_telemetry(None, SESSION, source_data={"broker_orders": [order], "fill_fragments": []}, captured_at=CAPTURED_AT)
    operation = first["operations"][0]
    assert operation["reconciliation_status"] == "reconciled_filled"
    assert operation["filled_qty"] == 10
    assert first["content_hash"] == second["content_hash"]


# ---------------------------------------------------------------------------
# QA-9 — freshness
# ---------------------------------------------------------------------------


def _freshness_of(order: dict[str, Any], *, captured_at: datetime = CAPTURED_AT) -> dict[str, Any]:
    result = build_canonical_operation_telemetry(None, SESSION, source_data={"broker_orders": [order], "fill_fragments": []}, captured_at=captured_at)
    return result["operations"][0]["freshness"]


def test_qa9_units_are_seconds_and_aged_is_observation_only() -> None:
    fresh = _freshness_of(_order(signal_at="2026-07-17T13:45:00+00:00", plan_created_at="2026-07-17T13:54:50+00:00"))
    assert fresh["signal_to_plan_seconds"] == pytest.approx(590.0)
    assert fresh["freshness_status"] == "fresh_signal"
    aged = _freshness_of(_order(signal_at="2026-07-17T13:45:09.746725+00:00", plan_created_at="2026-07-17T16:08:34.286506+00:00"))
    assert aged["signal_to_plan_seconds"] == pytest.approx(8604.539781)
    assert aged["signal_to_plan_seconds"] / 60 == pytest.approx(143.408996, rel=1e-4)
    assert aged["freshness_status"] == "aged_signal"
    # aged_signal no crea gate, bloqueo ni cambio de ranking: solo observación.
    result = build_canonical_operation_telemetry(
        None,
        SESSION,
        source_data={"broker_orders": [_order(signal_at="2026-07-17T13:45:09.746725+00:00", plan_created_at="2026-07-17T16:08:34.286506+00:00")], "fill_fragments": []},
        captured_at=CAPTURED_AT,
    )
    assert "gate" not in json.dumps(result["operations"][0]).lower()
    assert result["operations"][0]["status"] == "filled"


def test_qa9_timezone_variants_dst_and_previous_session() -> None:
    # DST America/New_York: EDT (-04:00) en julio; un timestamp EST (-05:00) se normaliza a UTC.
    order = _order(signal_at="2026-07-17T09:45:00-04:00", plan_created_at="2026-07-17T09:55:00-04:00")
    freshness = _freshness_of(order)
    assert freshness["signal_at"] == "2026-07-17T13:45:00+00:00"
    assert freshness["signal_to_plan_seconds"] == pytest.approx(600.0)
    winter = _order(signal_at="2026-01-16T09:45:00-05:00", plan_created_at="2026-01-16T10:00:00-05:00")
    winter_freshness = _freshness_of(winter, captured_at=datetime(2026, 1, 17, tzinfo=timezone.utc))
    assert winter_freshness["signal_to_plan_seconds"] == pytest.approx(900.0)
    # Señal de sesión anterior: duración enorme, jamás negativa ni cero.
    previous = _order(signal_at="2026-07-16T13:45:00+00:00", plan_created_at="2026-07-17T16:08:34+00:00", status="filled")
    previous_freshness = _freshness_of(previous)
    assert previous_freshness["signal_to_plan_seconds"] > 86_000
    assert previous_freshness["freshness_status"] == "aged_signal"
    # Cierre de mercado exacto (20:00 UTC).
    close = _order(signal_at="2026-07-17T20:00:00+00:00", plan_created_at="2026-07-17T20:00:00+00:00")
    assert _freshness_of(close)["signal_to_plan_seconds"] == 0.0


def test_qa9_naive_inverted_future_and_missing_timestamps() -> None:
    naive = _freshness_of(_order(signal_at="2026-07-17T13:45:00"))
    assert naive["signal_at"] is None
    assert "naive_timestamp:signal_at" in naive["warnings"]
    inverted = _freshness_of(_order(signal_at="2026-07-17T17:00:00+00:00", plan_created_at="2026-07-17T16:00:00+00:00"))
    assert inverted["signal_to_plan_seconds"] is None
    assert "inverted:plan_created_at" in inverted["warnings"]
    future = _freshness_of(_order(first_fill_at="2026-07-19T00:00:00+00:00"), captured_at=CAPTURED_AT)
    assert future["first_fill_at"] is None
    assert "future_timestamp:first_fill_at" in future["warnings"]
    missing = _freshness_of(_order(first_fill_at=None))
    assert missing["signal_to_fill_seconds"] is None
    assert "missing:first_fill_at" in missing["warnings"]


def test_qa9_equal_prices_do_not_imply_refresh_and_quotes_need_verifiable_timestamp() -> None:
    order = _order(signal_price=100.0, recommendation_price=100.0, plan_price=100.0)
    freshness = _freshness_of(order)
    assert freshness["signal_to_plan_bps"] == 0.0
    assert freshness["price_refresh_status"] == "unverified"
    # Cotización nueva con timestamp verificable.
    with_quote = _order(signal_price=100.0, plan_price=100.0)
    with_quote["execution_quality_snapshot"] = {"timestamps": {"quote_at": "2026-07-17T15:00:00+00:00"}, "prices": {"fill_price": 100.5}}
    verified = _freshness_of(with_quote)
    assert verified["price_refresh_status"] == "verified"
    # Cotización sin timestamp verificable.
    bad_quote = _order()
    bad_quote["execution_quality_snapshot"] = {"timestamps": {"quote_at": "no-es-fecha"}}
    assert _freshness_of(bad_quote)["price_refresh_status"] == "unverified"


def test_qa9_nan_infinity_and_fill_without_first_fill_at() -> None:
    order = _order(signal_price=float("nan"), fill_price=float("inf"))
    freshness = _freshness_of(order)
    assert freshness["signal_price"] is None
    assert freshness["fill_price"] is None
    assert "invalid:signal_price" in freshness["warnings"]
    assert freshness["signal_to_fill_bps"] is None
    no_fill = _freshness_of(_order(first_fill_at=None, fill_price=None))
    assert no_fill["signal_to_fill_seconds"] is None
    assert no_fill["signal_to_fill_bps"] is None
    assert "missing:first_fill_at" in no_fill["warnings"]


# ---------------------------------------------------------------------------
# QA-10 — volumen sintético
# ---------------------------------------------------------------------------


def _volume_fixture(orders: int, signals: int, fragments_per_order: int) -> dict[str, Any]:
    fixture_orders = []
    fragments = []
    for index in range(orders):
        order_id = f"bo-vol-{index:04d}"
        side = "sell" if index % 10 == 9 else "buy"
        fixture_orders.append(
            _order(
                broker_order_id=order_id,
                client_order_id=f"client-vol-{index:04d}",
                symbol=f"SYM{index % 25}",
                side=side,
                signal_id=f"signal-vol-{index:04d}",
                candidate_id=f"candidate-vol-{index:04d}",
                raw_exit_trigger="stop_loss" if side == "sell" else None,
            )
        )
        for fragment_index in range(fragments_per_order):
            fragments.append({"broker_order_id": order_id, "fragment_id": f"frag-{order_id}-{fragment_index}", "qty": 1})
    signal_rows = [
        {"signal_id": f"signal-vol-{index:04d}", "symbol": f"SYM{index % 25}", "signal_date": SESSION, "decision": "candidate", "features": {"signal_price": 100.0 + index * 0.01}}
        for index in range(signals)
    ]
    return {"broker_orders": fixture_orders, "fill_fragments": fragments, "signal_outcomes": signal_rows}


def test_qa10_volume_two_sessions_bounds_and_canonical_unit(tmp_path: Path) -> None:
    store = _store(tmp_path)
    metrics: dict[str, Any] = {}
    for session in ("2026-07-16", "2026-07-17"):
        fixture = _volume_fixture(orders=100, signals=1000, fragments_per_order=5)
        tracemalloc.start()
        started = time.perf_counter()
        snapshot = build_canonical_operation_telemetry(None, session, source_data=fixture, captured_at=CAPTURED_AT)
        build_seconds = time.perf_counter() - started
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        started = time.perf_counter()
        result = persist_canonical_operation_telemetry(store, snapshot)
        persist_seconds = time.perf_counter() - started
        assert result["status"] == "inserted"
        encoded = json.dumps(snapshot)
        metrics[session] = {
            "event_bytes": len(encoded.encode("utf-8")),
            "build_seconds": round(build_seconds, 4),
            "persist_seconds": round(persist_seconds, 4),
            "peak_memory_bytes": peak,
        }
        # operations contiene operaciones canónicas, no los 1000 candidatos.
        assert len(snapshot["operations"]) == 100
        assert snapshot["denominators"]["broker_order_count"] == 100
        assert snapshot["denominators"]["signal_count"] == 1000
        assert snapshot["denominators"]["fill_fragment_count"] == 500
    # Dos sesiones = exactamente dos eventos canónicos; sin crecimiento por eventos raw.
    events = store.agent_events(event_type_prefix="canonical_operation_telemetry", limit=20)
    assert len(events) == 2
    assert metrics["2026-07-16"]["event_bytes"] < 2_000_000
    assert metrics["2026-07-16"]["build_seconds"] < 10
    assert metrics["2026-07-16"]["persist_seconds"] < 5
    print("VOLUME_METRICS=" + json.dumps(metrics, sort_keys=True))


# ---------------------------------------------------------------------------
# QA-11 — eventos y lectores
# ---------------------------------------------------------------------------


def test_qa11_readers_distinguish_all_states(tmp_path: Path) -> None:
    store = _store(tmp_path)
    # collecting: sin eventos.
    assert read_canonical_operation_telemetry(store, SESSION)["status"] == "collecting"
    assert canonical_operation_telemetry_digest(store, SESSION)["status"] == "collecting"
    assert canonical_operation_telemetry_digest(store)["status"] == "collecting"
    # available.
    snapshot = build_canonical_operation_telemetry(None, SESSION, source_data=_raw_fixture(), captured_at=CAPTURED_AT)
    persist_canonical_operation_telemetry(store, snapshot)
    assert read_canonical_operation_telemetry(store, SESSION)["status"] == "available"
    # partial: operaciones sin broker_order_id no existen; una operación con
    # lineage parcial sigue disponible, así que forzamos un payload partial.
    partial = copy.deepcopy(snapshot)
    partial["status"] = "partial"
    partial["content_hash"] = _stable_hash(partial)
    store_partial = Store(tmp_path / "p" / "state" / "t.sqlite3", tmp_path / "p" / "logs")
    store_partial.ensure_schema()
    persist_canonical_operation_telemetry(store_partial, partial)
    assert read_canonical_operation_telemetry(store_partial, SESSION)["status"] == "partial"
    # unavailable persistido se lee como unavailable (fail-open honesto).
    unavailable = build_canonical_operation_telemetry(None, "2026-07-18", source_data=None, captured_at=CAPTURED_AT)
    persist_canonical_operation_telemetry(store, unavailable)
    assert read_canonical_operation_telemetry(store, "2026-07-18")["status"] == "unavailable"
    # legacy_without_canonical_telemetry cubierto en QA-3.


def test_qa11_conflict_is_not_counted_as_valid_snapshot(tmp_path: Path) -> None:
    store = _store(tmp_path)
    snapshot = build_canonical_operation_telemetry(None, SESSION, source_data=_raw_fixture(), captured_at=CAPTURED_AT)
    persist_canonical_operation_telemetry(store, snapshot)
    changed = copy.deepcopy(snapshot)
    changed["denominators"]["broker_order_count"] = 9
    changed["content_hash"] = _stable_hash(changed)
    assert persist_canonical_operation_telemetry(store, changed)["status"] == "conflict"
    reader = read_canonical_operation_telemetry(store, SESSION)
    assert reader["status"] == "available"
    assert reader["denominators"]["broker_order_count"] == 8
    digest = canonical_operation_telemetry_digest(store, SESSION)
    assert digest["status"] == "available"
    assert digest["denominators"]["broker_order_count"] == 8


def test_qa11_global_digest_after_conflict_still_reads_valid_snapshot(tmp_path: Path) -> None:
    store = _store(tmp_path)
    snapshot = build_canonical_operation_telemetry(None, SESSION, source_data=_raw_fixture(), captured_at=CAPTURED_AT)
    persist_canonical_operation_telemetry(store, snapshot)
    changed = copy.deepcopy(snapshot)
    changed["denominators"]["broker_order_count"] = 9
    changed["content_hash"] = _stable_hash(changed)
    persist_canonical_operation_telemetry(store, changed)
    digest = canonical_operation_telemetry_digest(store)
    assert digest["status"] == "available", f"digest global ocultó el snapshot válido: {digest}"
    assert digest["denominators"]["broker_order_count"] == 8
    # Los conflictos no se cuentan como snapshots válidos, pero quedan auditables.
    assert digest["canonical_events"] == 1
    assert digest["conflict_events"] == 1
    session_digest = canonical_operation_telemetry_digest(store, SESSION)
    assert session_digest["status"] == "available"
    assert session_digest["conflict_events"] == 1


def test_qa11_global_digest_conflict_only_reports_conflict(tmp_path: Path) -> None:
    store = _store(tmp_path)
    snapshot = build_canonical_operation_telemetry(None, SESSION, source_data=_raw_fixture(), captured_at=CAPTURED_AT)
    other = build_canonical_operation_telemetry(None, "2026-07-18", source_data=_raw_fixture(), captured_at=CAPTURED_AT)
    assert snapshot["content_hash"] != other["content_hash"]
    # Dos procesos escriben contenido distinto para la misma sesión: solo conflicto.
    event_id = f"canonical_operation_telemetry:{SESSION}"
    store.record_canonical_operation_telemetry(dict(snapshot), event_id=event_id)
    store.record_canonical_operation_telemetry(dict(other), event_id=event_id)
    # Borrar el snapshot válido deja únicamente el rastro de conflicto.
    with store.connect() as conn:
        conn.execute("DELETE FROM agent_events WHERE event_id = ?", (event_id,))
    digest = canonical_operation_telemetry_digest(store)
    assert digest["status"] == "conflict"
    assert digest["canonical_events"] == 0
    assert digest["conflict_events"] == 1
    assert digest["denominators"] is None


def test_qa11_duplicate_generic_rows_are_not_counted(tmp_path: Path) -> None:
    store = _store(tmp_path)
    snapshot = build_canonical_operation_telemetry(None, SESSION, source_data=_raw_fixture(), captured_at=CAPTURED_AT)
    persist_canonical_operation_telemetry(store, snapshot)
    # Una fila genérica duplicada con el mismo tipo pero ID distinto no puede
    # existir por PK; un intento de inserción duplicada se rechaza.
    with pytest.raises(sqlite3.IntegrityError):
        with store.connect() as conn:
            conn.execute(
                "INSERT INTO agent_events (event_id, agent, event_type, cycle_id, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (f"canonical_operation_telemetry:{SESSION}", "postmarket_telemetry", "canonical_operation_telemetry", None, "{}", "2026-07-17T22:00:00+00:00"),
            )
    events = store.agent_events(event_type_prefix="canonical_operation_telemetry", limit=20)
    assert len([item for item in events if item["event_type"] == "canonical_operation_telemetry"]) == 1


def test_qa11_cli_reads_persisted_event(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path)
    # El CLI lee settings.database_path: la semilla vive exactamente ahí.
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    snapshot = build_canonical_operation_telemetry(None, SESSION, source_data=_raw_fixture(), captured_at=CAPTURED_AT)
    persist_canonical_operation_telemetry(store, snapshot)

    from agente_bolsa import main

    monkeypatch.setattr(main, "get_settings", lambda: settings)
    args = type("Args", (), {"session": SESSION, "json": True})()
    main.command_canonical_operation_telemetry(args)
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["status"] == "available"
    assert output["denominators"]["broker_order_count"] == 8
    # Sin evento: collecting con denominadores null.
    args_empty = type("Args", (), {"session": "2026-07-20", "json": True})()
    main.command_canonical_operation_telemetry(args_empty)
    empty = json.loads(capsys.readouterr().out)
    assert empty["status"] == "collecting"
    assert empty["denominators"] is None


def test_qa11_readers_do_not_use_runtime_state_as_history(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set_runtime_value("canonical_operation_telemetry", {"status": "available", "denominators": {"broker_order_count": 42}})
    reader = read_canonical_operation_telemetry(store, SESSION)
    assert reader["status"] == "collecting"  # runtime_state jamás sustituye al evento.


# ---------------------------------------------------------------------------
# QA-12 — paridad combinada
# ---------------------------------------------------------------------------


def test_qa12_fixture_and_active_fields_keep_parity() -> None:
    fixture = _raw_fixture()
    before = copy.deepcopy(fixture)
    active = {
        "signals": ["s1"], "scores": [15.2], "ranks": [3], "selection": ["VTR"],
        "capacity_fill": {"reason": "capacity_fill_tras_llm_ok"}, "gates": ["passed"],
        "entry_quality": 0.7, "sizing": {"multiplier": 0.5}, "micro_experiments": ["mx-1"],
        "plans": ["p1"], "stops": [90.1], "takes": [110.2], "quantities": [10],
        "prices": [100.0], "order_types": ["limit"], "orders": ["o1"],
        "exposure": 0.12, "limits": {"daily": 3}, "scheduler": {"jobs": 8}, "job_frequency": {"pmr": "daily"},
    }
    active_before = copy.deepcopy(active)
    build_canonical_operation_telemetry(None, SESSION, source_data=fixture, captured_at=CAPTURED_AT)
    assert fixture == before
    assert active == active_before


def test_qa12_no_post_decision_or_broker_payload_fields_leak() -> None:
    result = build_canonical_operation_telemetry(None, SESSION, source_data=_raw_fixture(), captured_at=CAPTURED_AT)
    encoded = json.dumps(result, ensure_ascii=False).lower()
    for forbidden in ("mfe", "mae", "first_hit", "llm_response", "matured_outcome", "prompt"):
        assert forbidden not in encoded
    operation_keys = set(result["operations"][0].keys())
    assert "pnl" not in operation_keys
    assert "order_type" not in operation_keys  # la telemetría no describe instrucciones al broker.


# ---------------------------------------------------------------------------
# Regresión de defectos detectados por P-L48BR1
# ---------------------------------------------------------------------------


def test_defect_d1_absent_identity_fields_are_null_never_sentinel_leak() -> None:
    """D1: el centinela _MISSING jamás aparece en campos publicados."""

    order = {"broker_order_id": "bo-min", "symbol": "X", "side": "buy", "status": "filled"}
    result = build_canonical_operation_telemetry(None, SESSION, source_data={"broker_orders": [order], "fill_fragments": []}, captured_at=CAPTURED_AT)
    operation = result["operations"][0]
    for field in (
        "client_order_id",
        "signal_id",
        "candidate_id",
        "recommendation_id",
        "plan_id",
        "source_plan_id",
        "cycle_id",
        "signal_capture_id",
        "strategy",
        "decision_source",
        "capacity_fill_reason_code",
    ):
        assert operation[field] is None, f"{field} filtró centinela: {operation[field]!r}"
    assert operation["lineage_quality"] == "partial"  # ausencia honesta, nunca verified inventado.
    assert result["freshness"]["operations_with_signal"] == 0
    encoded = json.dumps(result)
    assert "object object at" not in encoded


def test_defect_d1_fallback_chain_reaches_later_sources() -> None:
    """D1: los fallbacks signal_id/candidate_id/filled_qty llegan a su segunda fuente."""

    order = _order(broker_order_id="bo-fallback")
    order["payload"] = {"signal_id": "signal-payload", "candidate_id": "candidate-payload", "average_fill_price": 101.5}
    order["broker_order_reconciled"] = {"reconciliation_status": "reconciled_filled", "filled_qty": 7}
    result = build_canonical_operation_telemetry(None, SESSION, source_data={"broker_orders": [order], "fill_fragments": []}, captured_at=CAPTURED_AT)
    operation = result["operations"][0]
    assert operation["signal_id"] == "signal-payload"
    assert operation["candidate_id"] == "candidate-payload"
    assert operation["filled_qty"] == 7
    assert operation["average_fill_price"] == 101.5
    # La autoridad de execution quality gana al payload cuando ambos existen.
    order2 = _order(broker_order_id="bo-authority")
    order2["execution_quality_snapshot"] = {"signal_id": "signal-execution"}
    order2["payload"] = {"signal_id": "signal-payload"}
    result2 = build_canonical_operation_telemetry(None, SESSION, source_data={"broker_orders": [order2], "fill_fragments": []}, captured_at=CAPTURED_AT)
    assert result2["operations"][0]["signal_id"] == "signal-execution"


def test_defect_d1_fragment_id_falls_back_to_memory_id_and_detects_duplicates(tmp_path: Path) -> None:
    """D1: trade_memory sin fragment_id usa memory_id; los duplicados se detectan."""

    store = _store(tmp_path)
    fixture = {
        "broker_orders": [_order(broker_order_id="bo-mem")],
        "fill_fragments": [
            {"broker_order_id": "bo-mem", "qty": 2},
            {"broker_order_id": "bo-mem", "qty": 3},
        ],
    }
    _seed_store_from_fixture(store, SESSION, fixture)
    result = build_canonical_operation_telemetry(store, SESSION, captured_at=CAPTURED_AT)
    operation = result["operations"][0]
    assert operation["fill_fragment_count"] == 2
    assert "duplicate_fill_fragments" not in operation["warnings"]  # memory-1 y memory-2 son distintos.
    # Mismo fragment_id explícito repetido: warning determinista.
    fixture["fill_fragments"] = [
        {"broker_order_id": "bo-mem", "fragment_id": "dup", "qty": 2},
        {"broker_order_id": "bo-mem", "fragment_id": "dup", "qty": 3},
    ]
    store2 = Store(tmp_path / "b2" / "state" / "t.sqlite3", tmp_path / "b2" / "logs")
    store2.ensure_schema()
    _seed_store_from_fixture(store2, SESSION, fixture)
    result2 = build_canonical_operation_telemetry(store2, SESSION, captured_at=CAPTURED_AT)
    assert "duplicate_fill_fragments" in result2["operations"][0]["warnings"]


def test_defect_d1_candidate_count_not_inflated_by_missing_ids() -> None:
    """D1: filas sin candidate_id no cuentan como candidatos únicos."""

    fixture = {
        "broker_orders": [_order()],
        "signal_outcomes": [
            {"signal_id": "s1", "signal_date": SESSION, "features": {}},
            {"signal_id": "s2", "signal_date": SESSION, "features": {}},
        ],
        "trade_recommendations": [{"recommendation_id": "r1", "payload": {}}],
        "order_plans": [{"plan_id": "p1", "payload": {}}],
        "fill_fragments": [],
    }
    result = build_canonical_operation_telemetry(None, SESSION, source_data=fixture, captured_at=CAPTURED_AT)
    assert result["denominators"]["candidate_count"] is None  # ausente, jamás inflado.
    assert result["denominators"]["signal_count"] == 2
    with_ids = copy.deepcopy(fixture)
    with_ids["signal_outcomes"][0]["features"] = {"candidate_id": "cand-1"}
    with_ids["signal_outcomes"][1]["features"] = {"candidate_id": "cand-1"}
    with_ids["trade_recommendations"][0]["payload"] = {"candidate_id": "cand-2"}
    result2 = build_canonical_operation_telemetry(None, SESSION, source_data=with_ids, captured_at=CAPTURED_AT)
    assert result2["denominators"]["candidate_count"] == 2
    # Filas de otros dominios (plan de venta sin candidato) no vetan el denominador.
    with_ids["order_plans"].append({"plan_id": "p-sell", "payload": {"side": "sell"}})
    result3 = build_canonical_operation_telemetry(None, SESSION, source_data=with_ids, captured_at=CAPTURED_AT)
    assert result3["denominators"]["candidate_count"] == 2
