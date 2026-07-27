"""Adversarial contract tests for the P-L44BR3 shadow reader."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from agente_bolsa.config import Settings
from agente_bolsa.models import AgentEvent
from agente_bolsa.storage import Store
from agente_bolsa.tools.learning_penalty_cycle_shadow import (
    build_learning_penalty_cycle_shadow,
    learning_penalty_shadow_digest,
    persist_learning_penalty_cycle_shadow,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(DATA_DIR=tmp_path, _env_file=None, max_orders_per_cycle=5)


def _raw(index: int, *, enriched: bool = False, signal: str | None = None) -> dict:
    item = {
        "signal_id": signal or f"signal-{index}",
        "signal_capture_id": f"capture-{index}",
        "symbol": f"S{index:03d}",
        "direction": "long",
    }
    if enriched:
        item.update(
            {
                "candidate_id": f"candidate-{index}",
                "rank_priority_score": 0.4 - index / 1000,
                "learning_prior": {
                    "expected_edge_3d": 0.01,
                    "setup_edge_3d_raw": 0.01,
                    "sample_size_3d": 12,
                    "confidence_weight_3d": 1.0,
                    "operational_penalty": 0.05,
                },
            }
        )
    return item


def test_443_identified_raw_candidates_are_not_identity_unavailable(tmp_path: Path):
    snapshot = build_learning_penalty_cycle_shadow(
        "cycle-443",
        {"all_candidates": [_raw(index) for index in range(443)]},
        settings=_settings(tmp_path),
        captured_at="2026-07-18T08:00:00+00:00",
    )
    counts = snapshot["candidate_counts"]
    assert counts["ranked_buy_total"] == 443
    assert counts["identity_verified"] == 443
    assert counts["identity_unavailable"] == 0
    assert counts["identity_ambiguous"] == 0
    assert counts["shadow_inputs_available"] == 0
    assert counts["shadow_inputs_unavailable"] == 443
    assert counts["shadow_inputs_invalid"] == 0
    assert snapshot["status"] == "partial"


def test_enriched_candidate_has_shadow_inputs_and_no_second_active_path(tmp_path: Path):
    candidate = _raw(1, enriched=True)
    snapshot = build_learning_penalty_cycle_shadow(
        "cycle-enriched",
        {"all_candidates": [candidate]},
        active_candidates=[candidate],
        settings=_settings(tmp_path),
    )
    counts = snapshot["candidate_counts"]
    assert counts["identity_verified"] == 1
    assert counts["shadow_inputs_available"] == 1
    assert snapshot["legacy_top_ids"] == ["candidate-1"]
    assert snapshot["selected_candidates"] == []
    assert snapshot["active_policy"] == "legacy_double_application"
    assert snapshot["shadow_policy"] == "single_application"


def test_missing_signal_is_unavailable_and_well_does_not_block_other_candidates(tmp_path: Path):
    well = _raw(1)
    well.pop("signal_id")
    well.pop("signal_capture_id")
    other = _raw(2)
    snapshot = build_learning_penalty_cycle_shadow(
        "mkt_00eee0e184d6",
        {"all_candidates": [well, other]},
        settings=_settings(tmp_path),
    )
    counts = snapshot["candidate_counts"]
    assert counts["identity_unavailable"] == 1
    assert counts["identity_verified"] == 1
    # v2 keeps identity and input denominators independent: the missing WELL
    # identity and the identified row without scoring inputs are both input-unavailable.
    assert counts["shadow_inputs_unavailable"] == 2
    assert "WELL" not in json.dumps(snapshot)


def test_duplicate_signal_or_cycle_mismatch_is_ambiguous(tmp_path: Path):
    first = _raw(1, signal="same-signal")
    second = _raw(2, signal="same-signal")
    mismatched = _raw(3)
    mismatched["cycle_id"] = "other-cycle"
    snapshot = build_learning_penalty_cycle_shadow(
        "cycle-contract",
        {"all_candidates": [first, second, mismatched]},
        settings=_settings(tmp_path),
    )
    assert snapshot["candidate_counts"]["identity_ambiguous"] == 3
    assert snapshot["candidate_counts"]["identity_unavailable"] == 0
    assert "cycle_id_mismatch" in snapshot["warnings"]


def _persisted_snapshot(tmp_path: Path, cycle_id: str = "cycle-ledger") -> tuple[Store, dict]:
    store = Store(tmp_path / "db.sqlite", tmp_path / "logs")
    store.ensure_schema()
    snapshot = build_learning_penalty_cycle_shadow(
        cycle_id,
        {"all_candidates": [_raw(1, enriched=True)]},
        settings=_settings(tmp_path),
        captured_at="2026-07-18T08:00:00+00:00",
    )
    assert persist_learning_penalty_cycle_shadow(store, snapshot)["status"] == "inserted"
    return store, snapshot


def test_reader_ignores_generic_reporter_row_and_deduplicates_canonical(tmp_path: Path):
    store, snapshot = _persisted_snapshot(tmp_path)
    store.record_agent_event(
        AgentEvent(
            agent="reporter",
            event_type="learning_penalty_cycle_shadow",
            cycle_id="cycle-ledger",
            payload={"message": "generic duplicate", "status": "partial"},
        )
    )
    readout = store.learning_penalty_cycle_shadow_read()
    assert readout["canonical_cycles"] == 1
    assert readout["canonical_events"] == 1
    assert readout["generic_reporter_rows_ignored"] == 1
    assert len(store.learning_penalty_cycle_shadow_events()) == 1
    digest = learning_penalty_shadow_digest(store, now=datetime(2026, 7, 18, 9, tzinfo=timezone.utc))
    assert digest["canonical_cycles"] == 1
    assert digest["generic_reporter_rows_ignored"] == 1
    assert digest["candidate_counts"]["ranked_buy_total"] == 1
    assert digest["freshness"]["status"] == "fresh"


def test_canonical_conflict_preserves_original_and_is_visible(tmp_path: Path):
    store, snapshot = _persisted_snapshot(tmp_path, "cycle-conflict")
    changed = copy.deepcopy(snapshot)
    changed["candidate_counts"]["ranked_buy_total"] = 2
    changed["content_hash"] = "different"
    assert persist_learning_penalty_cycle_shadow(store, changed)["status"] == "conflict"
    readout = store.learning_penalty_cycle_shadow_read()
    assert readout["canonical_events"] == 1
    assert readout["conflicts"] == 1
    assert readout["events"][0]["candidate_counts"]["ranked_buy_total"] == 1
    digest = learning_penalty_shadow_digest(store)
    assert digest["conflicts"] == 1


def test_no_events_are_collecting_with_null_denominators(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite", tmp_path / "logs")
    store.ensure_schema()
    digest = learning_penalty_shadow_digest(store)
    assert digest["status"] == "collecting"
    assert digest["canonical_cycles"] is None
    assert digest["candidate_counts"] is None
    assert digest["freshness"]["status"] == "unavailable"


def test_snapshot_contains_no_post_decision_fields(tmp_path: Path):
    candidate = _raw(1, enriched=True)
    candidate.update({"pnl": 1.0, "fills": [{"price": 1}], "slippage": 0.1, "return_5d": 0.2, "prompt": "secret"})
    snapshot = build_learning_penalty_cycle_shadow(
        "cycle-safe",
        {"all_candidates": [candidate]},
        settings=_settings(tmp_path),
    )
    payload = json.dumps(snapshot)
    assert all(field not in payload for field in ("pnl", "fills", "slippage", "return_5d", "prompt"))
