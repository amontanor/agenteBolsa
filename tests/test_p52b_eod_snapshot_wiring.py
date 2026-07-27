"""P-L52B-W: stage order, single build/persist and protected-route parity."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from test_p48br1_adversarial_qa import (
    SESSION,
    _job_harness,
    _pmr_stage_events,
    _seed_store_from_fixture,
    _seeded_fixture,
    _settings,
    _store,
)

from agente_bolsa import scheduler
from agente_bolsa.tools.canonical_eod_account_snapshot import (
    read_canonical_eod_account_snapshot,
)


def test_pmr_builds_and_persists_eod_once_before_performance(monkeypatch, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = _store(tmp_path)
    _seed_store_from_fixture(store, SESSION, _seeded_fixture())
    counts: dict[str, int] = {"build": 0, "persist": 0}
    _job_harness(monkeypatch, store, counts={
        "build_calls": 0,
        "persist_calls": 0,
        "attribution_build_calls": 0,
        "attribution_persist_calls": 0,
        "reconcile_calls": 0,
        "outcome_updates": 0,
        "portfolio_snapshots": 0,
        "performance_calls": 0,
    })
    real_build = scheduler.build_from_postmarket_inputs
    real_persist = scheduler.persist_canonical_eod_account_snapshot
    built: list[dict[str, Any]] = []
    persisted: list[dict[str, Any]] = []

    def build_spy(*args: Any, **kwargs: Any) -> dict[str, Any]:
        counts["build"] += 1
        snapshot = real_build(*args, **kwargs)
        built.append(snapshot)
        return snapshot

    def persist_spy(*args: Any, **kwargs: Any) -> dict[str, Any]:
        counts["persist"] += 1
        persisted.append(args[1])
        return real_persist(*args, **kwargs)

    monkeypatch.setattr(scheduler, "build_from_postmarket_inputs", build_spy)
    monkeypatch.setattr(scheduler, "persist_canonical_eod_account_snapshot", persist_spy)
    old_performance = scheduler._persist_daily_performance
    seen: list[dict[str, Any] | None] = []

    def performance_spy(*args: Any, **kwargs: Any) -> None:
        seen.append(kwargs.get("canonical_eod_snapshot"))
        return old_performance(*args, **kwargs)

    monkeypatch.setattr(scheduler, "_persist_daily_performance", performance_spy)
    report = scheduler.post_market_review_job(settings, store, use_llm=False, verbose=False, force=True, trigger="scheduled")

    assert report is not None
    assert counts == {"build": 1, "persist": 1}
    assert built[0] is persisted[0]
    assert report["canonical_eod_account_snapshot"] is built[0]
    assert seen[0] is built[0]
    assert report["canonical_eod_account_snapshot_persistence"]["status"] == "inserted"
    readback = read_canonical_eod_account_snapshot(store, SESSION)
    assert readback["event_id"] == f"canonical_eod_account_snapshot:{SESSION}"
    performance_rows = store.performance_daily(limit=0)
    assert performance_rows
    assert performance_rows[-1]["payload"]["canonical_eod_account_snapshot"]["content_hash"] == built[0]["content_hash"]
    stages = _pmr_stage_events(store)
    eod_started = stages.index(("canonical_eod_account_snapshot", "started"))
    attribution_completed = stages.index(("canonical_trade_attribution", "completed"))
    performance_started = stages.index(("performance", "started"))
    assert attribution_completed < eod_started < performance_started


def test_build_failure_is_fail_open_and_terminal_completes(monkeypatch, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = _store(tmp_path)
    _seed_store_from_fixture(store, SESSION, _seeded_fixture())
    _job_harness(monkeypatch, store, counts={
        "build_calls": 0,
        "persist_calls": 0,
        "attribution_build_calls": 0,
        "attribution_persist_calls": 0,
        "reconcile_calls": 0,
        "outcome_updates": 0,
        "portfolio_snapshots": 0,
        "performance_calls": 0,
    })

    def broken_build(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("synthetic builder failure")

    monkeypatch.setattr(scheduler, "build_from_postmarket_inputs", broken_build)
    report = scheduler.post_market_review_job(settings, store, use_llm=False, verbose=False, force=True, trigger="scheduled")
    assert report is not None
    assert report["canonical_eod_account_snapshot"]["status"] == "unavailable"
    assert _pmr_stage_events(store)[-1] == ("terminal", "completed")


def test_persist_failure_is_fail_open_and_terminal_completes(monkeypatch, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = _store(tmp_path)
    _seed_store_from_fixture(store, SESSION, _seeded_fixture())
    _job_harness(monkeypatch, store, counts={
        "build_calls": 0,
        "persist_calls": 0,
        "attribution_build_calls": 0,
        "attribution_persist_calls": 0,
        "reconcile_calls": 0,
        "outcome_updates": 0,
        "portfolio_snapshots": 0,
        "performance_calls": 0,
    })

    def broken_persist(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("synthetic persistence failure")

    monkeypatch.setattr(scheduler, "persist_canonical_eod_account_snapshot", broken_persist)
    report = scheduler.post_market_review_job(settings, store, use_llm=False, verbose=False, force=True, trigger="scheduled")
    assert report is not None
    assert any(item.startswith("persistence_failed:") for item in report["canonical_eod_account_snapshot"]["warnings"])
    assert _pmr_stage_events(store)[-1] == ("terminal", "completed")


def test_eod_consumer_reads_event_and_does_not_enter_active_routes() -> None:
    source_files = [
        "src/agente_bolsa/cycle_runner.py",
        "src/agente_bolsa/tools/trade_decision.py",
        "src/agente_bolsa/tools/gate_evaluation.py",
        "src/agente_bolsa/tools/risk.py",
        "src/agente_bolsa/tools/broker.py",
        "src/agente_bolsa/tools/execution.py",
        "src/agente_bolsa/kernel.py",
        "src/agente_bolsa/config.py",
    ]
    root = Path(__file__).parents[1]
    for relative in source_files:
        assert "canonical_eod_account_snapshot" not in (root / relative).read_text(encoding="utf-8")
    assert "build_from_postmarket_inputs" in inspect.getsource(scheduler.post_market_review_job)
