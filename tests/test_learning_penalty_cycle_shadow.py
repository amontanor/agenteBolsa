"""Caracterizacion focal del ledger de ciclo P-L44B-W2."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.learning_penalty_cycle_shadow import (
    SCHEMA_VERSION,
    build_learning_penalty_cycle_shadow,
    learning_penalty_shadow_digest,
    persist_learning_penalty_cycle_shadow,
)


def _candidate(symbol: str, index: int, *, penalty: float = 0.05, expected: float = 0.01) -> dict:
    return {
        "candidate_id": f"candidate-{index}",
        "signal_id": f"signal-{index}",
        "symbol": symbol,
        "direction": "long",
        "score": 14,
        "rank_priority_score": 0.10 - index / 1000,
        "strategy_name": "builtin_breakout",
        "strategy_version": "v1",
        "learning_prior": {
            "expected_edge_3d": expected,
            "setup_edge_3d_raw": 0.01,
            "sample_size_3d": 8,
            "confidence_weight_3d": 1.0,
            "operational_penalty": penalty,
        },
    }


def _settings(tmp_path: Path) -> Settings:
    return Settings(DATA_DIR=tmp_path, _env_file=None, max_orders_per_cycle=2)


def test_cycle_snapshot_is_bounded_and_preserves_denominators(tmp_path: Path):
    candidates = [_candidate(f"S{index:02d}", index) for index in range(45)]
    snapshot = build_learning_penalty_cycle_shadow(
        "cycle-1",
        {"all_candidates": candidates},
        selected_candidates=candidates[:3],
        configured_capacity=2,
        settings=_settings(tmp_path),
        captured_at="2026-07-15T10:00:00+00:00",
    )

    assert snapshot["schema_version"] == SCHEMA_VERSION
    assert snapshot["policy_mode"] == "shadow_only"
    assert snapshot["active_policy"] == "legacy_double_application"
    assert snapshot["candidate_counts"]["ranked_buy_total"] == 45
    assert snapshot["candidate_counts"]["shadow_available"] == 45
    assert snapshot["candidate_counts"]["detail_persisted"] <= 40
    assert snapshot["candidate_counts"]["detail_omitted"] >= 5
    assert len(snapshot["bounded_candidates"]) == snapshot["candidate_counts"]["detail_persisted"]
    assert snapshot["configured_capacity"] == 2
    assert snapshot["content_hash"]


def test_missing_or_ambiguous_identity_is_unavailable_without_symbol_fallback(tmp_path: Path):
    missing = _candidate("AAPL", 1)
    missing.pop("candidate_id")
    missing.pop("signal_id")
    duplicate_a = _candidate("MSFT", 2)
    duplicate_b = copy.deepcopy(duplicate_a)
    duplicate_b["symbol"] = "GOOG"
    snapshot = build_learning_penalty_cycle_shadow(
        "cycle-identity",
        {"all_candidates": [missing, duplicate_a, duplicate_b]},
        settings=_settings(tmp_path),
    )

    assert snapshot["candidate_counts"]["ranked_buy_total"] == 3
    assert snapshot["candidate_counts"]["identity_unavailable"] == 3
    assert all(item.get("symbol") != "AAPL" for item in snapshot["bounded_candidates"])
    assert "UNKNOWN" not in json.dumps(snapshot)


def test_persist_is_idempotent_and_conflict_safe(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite", tmp_path / "logs")
    store.ensure_schema()
    candidate = _candidate("AAPL", 1)
    snapshot = build_learning_penalty_cycle_shadow(
        "cycle-persist",
        {"all_candidates": [candidate]},
        selected_candidates=[candidate],
        settings=_settings(tmp_path),
        captured_at="2026-07-15T10:00:00+00:00",
    )

    assert persist_learning_penalty_cycle_shadow(store, snapshot)["status"] == "inserted"
    repeated = dict(snapshot)
    repeated["captured_at"] = "2026-07-15T10:01:00+00:00"
    assert persist_learning_penalty_cycle_shadow(store, repeated)["status"] == "idempotent"
    changed = dict(snapshot)
    changed["rank_changed_count"] = 99
    changed["content_hash"] = "different-hash"
    conflict = persist_learning_penalty_cycle_shadow(store, changed)
    assert conflict["status"] == "conflict"
    assert len(store.learning_penalty_cycle_shadow_events()) == 1
    digest = learning_penalty_shadow_digest(store)
    assert digest["observations"] == 1
    assert digest["conflicts"] == 1


def test_digest_without_events_is_collecting_and_not_zero(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite", tmp_path / "logs")
    store.ensure_schema()
    digest = learning_penalty_shadow_digest(store)

    assert digest["status"] == "collecting"
    assert digest["shadow_only"] is True
    assert digest["observations"] is None
    assert digest["candidate_counts"] is None


def test_snapshot_excludes_post_decision_fields(tmp_path: Path):
    candidate = _candidate("AAPL", 1)
    candidate.update({"pnl": 10.0, "fills": [{"price": 1}], "return_5d": 0.2, "verdict": "win"})
    snapshot = build_learning_penalty_cycle_shadow(
        "cycle-temporal",
        {"all_candidates": [candidate]},
        settings=_settings(tmp_path),
    )
    encoded = json.dumps(snapshot)
    assert '"pnl"' not in encoded
    assert '"fills"' not in encoded
    assert '"return_5d"' not in encoded
    assert '"verdict"' not in encoded


def test_shadow_can_change_top5_and_capacity_membership_without_selecting(tmp_path: Path):
    candidates = [_candidate("AAPL", 0, penalty=0.05, expected=0.05)]
    candidates.extend(_candidate(f"S{index}", index, penalty=0.0) for index in range(1, 6))
    snapshot = build_learning_penalty_cycle_shadow(
        "cycle-top-change",
        {"all_candidates": candidates},
        selected_candidates=candidates[:2],
        configured_capacity=5,
        settings=_settings(tmp_path),
    )

    assert snapshot["legacy_top_ids"][0] != snapshot["shadow_top_ids"][0]
    assert snapshot["top_5_membership_changed"] is True
    assert snapshot["configured_capacity_membership_changed"] is True
    assert snapshot["selected_candidates"] == ["candidate-0", "candidate-1"]


def test_two_store_writers_are_idempotent_without_lost_original(tmp_path: Path):
    store_a = Store(tmp_path / "db.sqlite", tmp_path / "logs-a")
    store_b = Store(tmp_path / "db.sqlite", tmp_path / "logs-b")
    store_a.ensure_schema()
    candidate = _candidate("AAPL", 1)
    snapshot = build_learning_penalty_cycle_shadow(
        "cycle-concurrent",
        {"all_candidates": [candidate]},
        settings=_settings(tmp_path),
    )

    first = persist_learning_penalty_cycle_shadow(store_a, snapshot)
    second = persist_learning_penalty_cycle_shadow(store_b, snapshot)
    assert first["status"] == "inserted"
    assert second["status"] == "idempotent"
    assert len(store_a.learning_penalty_cycle_shadow_events()) == 1


def test_shadow_hook_failure_is_fail_open_for_active_path(tmp_path: Path):
    from agente_bolsa.scheduler import _capture_learning_penalty_cycle_shadow

    class Reporter:
        def __init__(self):
            self.events = []

        def emit(self, *args, **kwargs):
            self.events.append((args, kwargs))

    class FailingStore:
        def record_learning_penalty_cycle_shadow(self, *args, **kwargs):
            raise RuntimeError("synthetic telemetry failure")

    report = {"_learning_penalty_ranked_context": {"all_candidates": [_candidate("AAPL", 1)]}}
    reporter = Reporter()
    _capture_learning_penalty_cycle_shadow(_settings(tmp_path), FailingStore(), reporter, report, "cycle-fail-open")

    assert "_learning_penalty_ranked_context" not in report
    assert any(item[0][1] == "learning_penalty_cycle_shadow_failed" for item in reporter.events)
