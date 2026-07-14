"""Adversarial P-L37B-QA tests for concurrent capture merges."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import agente_bolsa.storage as storage_module
from agente_bolsa.storage import Store
from agente_bolsa.tools.signal_identity import build_signal_capture, signal_identity_block
from agente_bolsa.tools.signal_learning import record_signal_candidates


def _store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "state" / "qa.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    return store


def _capture(source_run_id: str) -> dict:
    capture = build_signal_capture(
        {
            "signal_id": "sig-1",
            "signal_date": "2026-07-13",
            "symbol": "FDS",
            "strategy_name": "builtin_breakout",
            "strategy_version": "v1",
        },
        source_run_id=source_run_id,
        captured_at="2026-07-13T20:00:00+00:00",
    )
    assert capture
    return capture


def test_concurrent_capture_writers_serialize_append_only_merge(tmp_path, monkeypatch):
    store = _store(tmp_path)
    capture_a = _capture("run-A")
    capture_b = _capture("run-B")
    capture_c = _capture("run-C")
    store.save_signal_outcome(
        signal_id="sig-1",
        source_run_id="run-A",
        source="learning_experiment",
        symbol="FDS",
        signal_date="2026-07-13",
        decision="candidate",
        features={"signal_identity": signal_identity_block(capture_a)},
    )

    first_merge_entered = threading.Event()
    release_first = threading.Event()
    original_merge = storage_module.merge_signal_identity_blocks
    calls = {"count": 0}
    calls_lock = threading.Lock()

    def pause_first_merge(existing, incoming):
        with calls_lock:
            calls["count"] += 1
            first = calls["count"] == 1
        if first:
            first_merge_entered.set()
            assert release_first.wait(timeout=5)
        return original_merge(existing, incoming)

    monkeypatch.setattr("agente_bolsa.storage.merge_signal_identity_blocks", pause_first_merge)
    results: list[tuple[str, str]] = []

    def writer(capture: dict, source_run_id: str) -> None:
        try:
            store.save_signal_outcome(
                signal_id="sig-1",
                source_run_id=source_run_id,
                source="learning_experiment",
                symbol="FDS",
                signal_date="2026-07-13",
                decision="candidate",
                features={"signal_identity": signal_identity_block(capture)},
            )
            results.append((source_run_id, "ok"))
        except Exception as exc:  # pragma: no cover - diagnostic assertion below
            results.append((source_run_id, type(exc).__name__))

    first = threading.Thread(target=writer, args=(capture_b, "run-B"))
    second = threading.Thread(target=writer, args=(capture_c, "run-C"))
    first.start()
    assert first_merge_entered.wait(timeout=5)
    second.start()
    release_first.set()
    first.join(timeout=5)
    second.join(timeout=5)
    assert not first.is_alive() and not second.is_alive()
    assert sorted(results) == [("run-B", "ok"), ("run-C", "ok")]

    row = store.signal_outcome_by_id("sig-1")
    assert row
    captures = row["features"]["signal_identity"]["captures"]
    assert set(captures) == {
        capture_a["signal_capture_id"],
        capture_b["signal_capture_id"],
        capture_c["signal_capture_id"],
    }
    json.dumps(row["features"], ensure_ascii=False, allow_nan=False)


def test_partial_upsert_preserves_json_branches_and_capture_history(tmp_path):
    store = _store(tmp_path)
    capture_a = _capture("run-A")
    capture_b = _capture("run-B")
    store.save_signal_outcome(
        signal_id="sig-1",
        source_run_id="run-A",
        source="learning_experiment",
        symbol="FDS",
        signal_date="2026-07-13",
        decision="candidate",
        features={
            "branch_a": {"value_a": 1},
            "signal_identity": signal_identity_block(capture_a),
        },
    )
    store.save_signal_outcomes_bulk(
        [
            {
                "signal_id": "sig-1",
                "source_run_id": "run-B",
                "source": "learning_experiment",
                "symbol": "FDS",
                "signal_date": "2026-07-13",
                "decision": "candidate",
                "features": {
                    "branch_b": {"value_b": 2},
                    "signal_identity": signal_identity_block(capture_b),
                },
            }
        ]
    )
    store.save_signal_outcome(
        signal_id="sig-1",
        source_run_id="legacy-run",
        source="legacy",
        symbol="FDS",
        signal_date="2026-07-13",
        decision="candidate",
        features={"legacy_branch": {"kept": True}},
    )
    row = store.signal_outcome_by_id("sig-1")
    assert row
    assert row["features"]["branch_a"] == {"value_a": 1}
    assert row["features"]["branch_b"] == {"value_b": 2}
    assert row["features"]["legacy_branch"] == {"kept": True}
    assert set(row["features"]["signal_identity"]["captures"]) == {
        capture_a["signal_capture_id"],
        capture_b["signal_capture_id"],
    }


def test_identity_persistence_failure_fails_open_for_decision_flow(tmp_path, monkeypatch):
    store = _store(tmp_path)
    report = {
        "run_id": "run-A",
        "as_of": "2026-07-13T20:00:00+00:00",
        "all_candidates": [
            {
                "symbol": "FDS",
                "strategy_name": "builtin_breakout",
                "strategy_version": "v1",
                "last_date": "2026-07-13",
                "technical_state": {},
            }
        ],
        "warnings": [],
    }

    def fail_persistence(_items):
        raise RuntimeError("synthetic database lock")

    monkeypatch.setattr(store, "save_signal_outcomes_bulk", fail_persistence)
    assert record_signal_candidates(store, report, source="learning_experiment") == 0
    assert "signal_identity_persistence_failed" in report["warnings"]
