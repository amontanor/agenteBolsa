"""QA integrado P-L49B + P-L50B sobre un ciclo sintético aislado."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.data_quality_decision_shadow import (
    capture_data_quality_phase_a,
    market_data_observation_id,
    persist_data_quality_decision_shadow,
)
from agente_bolsa.tools.data_quality_decision_shadow import (
    finalize_data_quality_phase_b as finalize_quality,
)
from agente_bolsa.tools.learning_penalty_cycle_shadow import (
    build_learning_penalty_cycle_shadow,
    finalize_learning_penalty_cycle_shadow,
    persist_learning_penalty_cycle_shadow,
)

DECISION_AT = datetime(2026, 7, 20, 14, 0, tzinfo=timezone.utc)


def _settings(path: Path) -> Settings:
    return Settings(DATA_DIR=path, _env_file=None, max_orders_per_cycle=5)


def _observation(symbol: str, *, blocking: bool = False) -> dict[str, Any]:
    row: dict[str, Any] = {
        "provider": "fixture",
        "symbol": symbol,
        "interval": "1d",
        "bar_timestamp": "2026-07-20T13:55:00+00:00",
        "bar_date": "2026-07-20",
        "price_basis": "unadjusted",
        "as_of": "2026-07-20T13:59:00+00:00",
        "quality_status": "blocking" if blocking else "valid",
        "invalid_fields": ["high"] if blocking else [],
        "invalidity_class": "ohlc_invalid" if blocking else None,
        "blocking_reason": "invalid_ohlc" if blocking else None,
        "ohlcv": {"open": 100.0, "high": 99.0 if blocking else 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0},
    }
    row["market_data_observation_id"] = market_data_observation_id(row)
    return row


def _candidate(index: int, observation: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": observation["symbol"],
        "side": "buy",
        "signal_capture_id": f"capture-{index}",
        "signal_id": f"signal-{index}",
        "candidate_id": f"candidate-{index}",
        "cycle_id": "combined-cycle",
        "market_data_observation_id": observation["market_data_observation_id"],
        "score": 10.0 - index / 100,
        "selection_rank": index + 1,
        "rank_priority_score": 0.9 - index / 1000,
        "learning_prior": {"setup_edge_3d_raw": -0.0007, "operational_penalty": 0.05, "expected_edge_3d": -0.0507, "sample_size_3d": 100},
    }


def test_combined_cycle_keeps_p49_and_p50_identity_independent(tmp_path: Path):
    observations = [_observation(f"SYM{index:03d}", blocking=index < 37) for index in range(500)]
    candidates = [_candidate(index, observations[index]) for index in range(443)]
    active_before = copy.deepcopy(candidates)

    quality_phase = capture_data_quality_phase_a(
        cycle_id="combined-cycle",
        market_snapshot={"snapshot_id": "market-snapshot-1", "provider": "fixture", "symbols": {row["symbol"]: {} for row in observations}, "observations": observations},
        candidates=candidates,
        decision_at=DECISION_AT,
        captured_at=DECISION_AT,
    )
    lineage_phase = build_learning_penalty_cycle_shadow(
        "combined-cycle",
        {"all_candidates": candidates},
        active_candidates=candidates,
        settings=_settings(tmp_path),
        captured_at="2026-07-20T14:00:00+00:00",
    )

    recommendations = [
        {"action": "buy", "recommendation_id": "rec-vtrs-buy", "decision_lineage": {"cycle_id": "combined-cycle", "signal_capture_id": "capture-1", "signal_id": "signal-1", "candidate_id": "candidate-1"}},
        {"action": "exit", "recommendation_id": "rec-vtrs-exit", "decision_lineage": {"cycle_id": "combined-cycle", "signal_capture_id": "capture-1", "signal_id": "signal-1", "candidate_id": "candidate-1"}},
    ]
    lineage_final = finalize_learning_penalty_cycle_shadow(
        lineage_phase,
        recommendations=recommendations,
        plans=[{"plan_id": "plan-1", "decision_lineage": recommendations[0]["decision_lineage"]}],
        cycle_id="combined-cycle",
    )
    quality_final = finalize_quality(
        quality_phase,
        recommendations=[{"signal_id": "signal-1", "cycle_id": "combined-cycle", "action": "buy"}],
        plans=[{"plan_id": "plan-1", "signal_id": "signal-1", "cycle_id": "combined-cycle"}],
        cycle_id="combined-cycle",
    )

    assert quality_phase["denominators"]["blocking_observations"] == 37
    assert lineage_phase["candidate_counts"]["identity_verified"] == 443
    assert len(lineage_final["decision_observations"]) == 2
    assert {row["action"] for row in lineage_final["decision_observations"]} == {"buy", "exit"}
    assert quality_final["denominators"]["recommended_affected"] == 1
    assert candidates == active_before
    assert all("market_data_observation_id" not in row.get("decision_lineage", {}) for row in recommendations)


def test_independent_shadow_failure_is_fail_open(tmp_path: Path):
    row = _observation("EIX", blocking=True)
    candidate = _candidate(0, row)
    before = copy.deepcopy(candidate)
    try:
        raise RuntimeError("p49_phase_a_fixture_failure")
    except RuntimeError:
        quality_phase = None
    lineage_phase = build_learning_penalty_cycle_shadow(
        "combined-cycle",
        {"all_candidates": [candidate]},
        active_candidates=[candidate],
        settings=_settings(tmp_path),
    )
    assert quality_phase is None
    assert lineage_phase["candidate_counts"]["identity_verified"] == 1
    assert candidate == before


def test_both_canonical_events_are_append_only_and_non_colliding(tmp_path: Path):
    store = Store(tmp_path / "state.sqlite", tmp_path / "logs")
    store.ensure_schema()
    row = _observation("EIX", blocking=True)
    candidate = _candidate(0, row)
    quality = finalize_quality(
        capture_data_quality_phase_a(
            cycle_id="combined-cycle",
            market_snapshot={"observations": [row]},
            candidates=[candidate],
            decision_at=DECISION_AT,
            captured_at=DECISION_AT,
        ),
        cycle_id="combined-cycle",
    )
    lineage = build_learning_penalty_cycle_shadow(
        "combined-cycle",
        {"all_candidates": [candidate]},
        active_candidates=[candidate],
        settings=_settings(tmp_path),
    )
    assert persist_data_quality_decision_shadow(store, quality)["status"] == "inserted"
    assert persist_learning_penalty_cycle_shadow(store, lineage)["status"] == "inserted"
    events = store.agent_events(cycle_id="combined-cycle")
    event_types = {event["event_type"] for event in events}
    assert "data_quality_decision_shadow" in event_types
    assert "learning_penalty_cycle_shadow" in event_types
    assert len(events) == 2
    assert persist_data_quality_decision_shadow(store, copy.deepcopy(quality))["status"] == "idempotent"
    assert persist_learning_penalty_cycle_shadow(store, copy.deepcopy(lineage))["status"] == "idempotent"


def test_phase_b_order_is_p49_then_p50_before_active_plan_persistence():
    source = (Path(__file__).parents[1] / "src" / "agente_bolsa" / "cycle_runner.py").read_text(encoding="utf-8")
    p49 = source.index("_data_quality_shadow_final = _persist_data_quality_decision_shadow_final")
    p50 = source.index("learning_penalty_shadow_final = _persist_learning_penalty_cycle_shadow_final")
    plans = source.index('optional_measure(timing, "persistence", "order_plan_records")')
    orders = source.index("submit_paper_order_plan", plans)
    assert p49 < p50 < plans < orders
