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
    finalize_learning_penalty_cycle_shadow,
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
    # The first list is the exact legacy order delivered to the active path;
    # the shadow score must be allowed to reorder it without changing that
    # active order.
    candidates = [_candidate(f"S{index}", index, penalty=0.0) for index in range(1, 6)]
    candidates.append(_candidate("AAPL", 0, penalty=0.05, expected=0.05))
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
    assert snapshot["selected_candidates"] == []


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


def test_phase_a_preparation_failure_is_fail_open_for_active_path(tmp_path: Path):
    from agente_bolsa.scheduler import _prepare_learning_penalty_cycle_shadow

    class Reporter:
        def __init__(self):
            self.events = []

        def emit(self, *args, **kwargs):
            self.events.append((args, kwargs))

    reporter = Reporter()
    result = _prepare_learning_penalty_cycle_shadow(_settings(tmp_path), reporter, None, [], "cycle-fail-open")
    assert result is None


def test_phase_a_preserves_active_legacy_order_and_phase_b_uses_real_outcomes(tmp_path: Path):
    candidates = [_candidate("AAPL", 1), _candidate("MSFT", 2), _candidate("GOOG", 3)]
    phase_a = build_learning_penalty_cycle_shadow(
        "cycle-two-phase",
        {"all_candidates": candidates},
        active_candidates=candidates,
        settings=_settings(tmp_path),
    )
    assert phase_a["phase"] == "pre_decision"
    assert phase_a["legacy_top_ids"][:3] == ["candidate-1", "candidate-2", "candidate-3"]
    assert all(not row["selected_by_decision"] for row in phase_a["bounded_candidates"])

    rec = {
        "action": "buy",
        "decision_lineage": {
            "candidate_id": "candidate-2",
            "signal_id": "signal-2",
            "decision_source": "capacity_fill",
        },
    }
    plan = {"side": "buy", "recommendation": rec}
    controls = {
        "signal-2": {
            "controls": [{"candidate_id": "candidate-3", "signal_id": "signal-3"}]
        }
    }
    final = finalize_learning_penalty_cycle_shadow(
        phase_a,
        recommendations=[rec],
        plans=[plan],
        comparable_control_sets=controls,
        rejected_order_plans=[
            {"candidate_id": "candidate-1", "signal_id": "signal-1", "reason": "gate_blocked"}
        ],
        cycle_id="cycle-two-phase",
        captured_at="2026-07-15T10:00:00+00:00",
    )
    rows = {row["candidate_id"]: row for row in final["bounded_candidates"]}
    assert rows["candidate-2"]["selected_by_decision"] is True
    assert rows["candidate-2"]["planned_by_active_path"] is True
    assert rows["candidate-2"]["decision_source"] == "capacity_fill"
    assert rows["candidate-3"]["comparable_control"] is True
    assert rows["candidate-1"]["blocked_candidate"] is True
    assert rows["candidate-1"]["final_non_execution_reason"] == "gate_blocked"
    assert final["phase"] == "post_selection"
    assert final["selected_candidates"] == ["candidate-2"]
    assert final["planned_candidates"] == ["candidate-2"]
    assert final["comparable_control_candidates"] == ["candidate-3"]


def test_phase_b_missing_identity_is_unavailable_and_partial_is_terminal(tmp_path: Path):
    candidate = _candidate("AAPL", 1)
    phase_a = build_learning_penalty_cycle_shadow(
        "cycle-partial",
        {"all_candidates": [candidate]},
        active_candidates=[candidate],
        settings=_settings(tmp_path),
    )
    unrelated = {"action": "buy", "symbol": "AAPL"}
    final = finalize_learning_penalty_cycle_shadow(
        phase_a,
        recommendations=[unrelated],
        cycle_id="cycle-partial",
        phase_b_available=False,
        captured_at="2026-07-15T10:00:00+00:00",
    )
    row = final["bounded_candidates"][0]
    assert final["status"] == "partial"
    assert row["selected_by_decision"] is False
    assert row["decision_source_status"] == "unavailable"
    assert "phase_b_unavailable" in final["warnings"]


def test_phase_b_rejects_conflicting_ids_even_when_symbol_matches(tmp_path: Path):
    candidate = _candidate("AAPL", 1)
    phase_a = build_learning_penalty_cycle_shadow(
        "cycle-conflicting-ids",
        {"all_candidates": [candidate]},
        active_candidates=[candidate],
        settings=_settings(tmp_path),
    )
    recommendation = {
        "action": "buy",
        "symbol": "AAPL",
        "decision_lineage": {"candidate_id": "candidate-1", "signal_id": "signal-other"},
    }
    final = finalize_learning_penalty_cycle_shadow(
        phase_a,
        recommendations=[recommendation],
        cycle_id="cycle-conflicting-ids",
    )
    row = final["bounded_candidates"][0]
    assert row["selected_by_decision"] is False


def test_final_shadow_hash_excludes_capture_time(tmp_path: Path):
    candidate = _candidate("AAPL", 1)
    phase_a = build_learning_penalty_cycle_shadow(
        "cycle-hash",
        {"all_candidates": [candidate]},
        active_candidates=[candidate],
        settings=_settings(tmp_path),
        captured_at="2026-07-15T10:00:00+00:00",
    )
    first = finalize_learning_penalty_cycle_shadow(phase_a, cycle_id="cycle-hash", captured_at="2026-07-15T10:00:00+00:00")
    second = finalize_learning_penalty_cycle_shadow(phase_a, cycle_id="cycle-hash", captured_at="2026-07-15T11:00:00+00:00")
    assert first["content_hash"] == second["content_hash"]
