"""QA integrado P-L49B + P-L50B sobre un ciclo sintético aislado."""

from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools import data_quality_decision_shadow as p49_shadow
from agente_bolsa.tools import learning_penalty_cycle_shadow as p50_shadow
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


def test_combined_adversarial_cycle_covers_finals_controls_rejections_and_freshness(tmp_path: Path):
    cycle_id = "combined-adversarial-cycle"
    observations = [_observation(f"SYM{index:03d}", blocking=index < 37) for index in range(500)]
    candidates = [_candidate(index, observations[index]) for index in range(443)]
    for candidate in candidates:
        candidate["cycle_id"] = cycle_id
    # P-L49 must stay unavailable when the exact observation is absent; P-L50
    # still has a verified signal identity and only its inputs are unavailable.
    candidates[-1]["market_data_observation_id"] = None
    candidates[-1].pop("learning_prior")
    active_before = copy.deepcopy(candidates)

    quality_phase = capture_data_quality_phase_a(
        cycle_id=cycle_id,
        market_snapshot={
            "snapshot_id": "market-snapshot-adversarial",
            "provider": "fixture",
            "symbols": {row["symbol"]: {} for row in observations},
            "observations": observations,
        },
        candidates=candidates,
        decision_at=DECISION_AT,
        captured_at=DECISION_AT,
    )
    lineage_phase = build_learning_penalty_cycle_shadow(
        cycle_id,
        {"all_candidates": candidates},
        active_candidates=candidates,
        settings=_settings(tmp_path),
        captured_at="2026-07-20T14:00:00+00:00",
    )

    finalists = candidates[:20]
    recommendations = []
    for index, candidate in enumerate(finalists):
        recommendation = {
            "action": "buy" if index % 2 == 0 else "exit",
            "recommendation_id": f"rec-finalist-{index}",
            "cycle_id": cycle_id,
            "symbol": candidate["symbol"],
            "signal_capture_id": candidate["signal_capture_id"],
            "signal_id": candidate["signal_id"],
            "candidate_id": candidate["candidate_id"],
            "decision_lineage": {
                "cycle_id": cycle_id,
                "signal_capture_id": candidate["signal_capture_id"],
                "signal_id": candidate["signal_id"],
                "candidate_id": candidate["candidate_id"],
            },
            "signal_at": "2026-07-20T13:45:21.140341+00:00",
            "recommendation_at": "2026-07-20T16:08:27.168281+00:00",
            "submitted_at": "2026-07-20T16:08:45.140012+00:00",
            "signal_price": 100.0,
            "recommendation_price": 100.0,
            "plan_price": 100.0,
        }
        if index == 7:
            recommendation["comparable_control_set"] = {"status": "verified", "controls": []}
        recommendations.append(recommendation)

    plans = [
        {
            "plan_id": f"plan-finalist-{index}",
            "side": "buy",
            "cycle_id": cycle_id,
            "signal_capture_id": candidate["signal_capture_id"],
            "signal_id": candidate["signal_id"],
            "candidate_id": candidate["candidate_id"],
            "action": "buy",
        }
        for index, candidate in enumerate(finalists[:10])
    ]
    controls = {
        recommendations[4]["signal_id"]: {"status": "verified", "controls": []},
        recommendations[5]["signal_id"]: {"status": "unavailable", "reason": "no_alternative", "controls": []},
        recommendations[8]["signal_id"]: {"status": "unavailable", "reason": "treatment_identity_unavailable", "controls": []},
    }
    canonical_rejections = [
        {
            "event_id": f"rejection:combined:{index}",
            "cycle_id": cycle_id,
            "candidate_id": finalists[index]["candidate_id"],
            "signal_id": finalists[index]["signal_id"],
            "action": "buy",
            "reason_code": "position_sizing",
            "stage": "position_sizing",
        }
        for index in range(4)
    ]
    rejected = canonical_rejections + [
        {**row, "event_id": f"evt_combined:{index}"}
        for index, row in enumerate(canonical_rejections)
    ]
    gate_snapshots = {
        "gate-finalist-14": {
            "cycle_id": cycle_id,
            "signal_capture_id": finalists[14]["signal_capture_id"],
            "signal_id": finalists[14]["signal_id"],
            "candidate_id": finalists[14]["candidate_id"],
            "identity_status": "verified",
            "gate_path": [{"status": "blocked", "identity_link_status": "verified", "reason_code": "risk_limit"}],
        }
    }

    quality_final = finalize_quality(
        quality_phase,
        recommendations=recommendations,
        plans=plans,
        rejected_order_plans=rejected,
        cycle_id=cycle_id,
    )
    lineage_final = finalize_learning_penalty_cycle_shadow(
        lineage_phase,
        recommendations=recommendations,
        plans=plans,
        comparable_control_sets=controls,
        rejected_order_plans=rejected,
        gate_snapshots=gate_snapshots,
        cycle_id=cycle_id,
    )

    assert quality_final["denominators"]["blocking_observations"] == 37
    assert quality_final["denominators"]["shadow_blocked_count"] == 37
    assert any(row.get("shadow_reason") in {"unavailable_identity", "unavailable_temporal"} for row in quality_final["details"])
    assert lineage_phase["candidate_counts"]["identity_verified"] == 443
    assert lineage_phase["candidate_counts"]["shadow_inputs_unavailable"] == 1
    assert len(lineage_final["decision_observations"]) == 20
    assert {row["action"] for row in lineage_final["decision_observations"]} == {"buy", "exit"}
    assert lineage_final["candidate_counts"]["planned_by_active_path"] == 10
    assert lineage_final["control_counts"]["comparable_control"] >= 1
    assert lineage_final["control_counts"]["control_unavailable"] >= 1
    assert lineage_final["control_counts"]["control_not_generated"] >= 1
    assert lineage_final["control_counts"]["control_persistence_missing"] >= 1
    assert lineage_final["control_counts"]["control_identity_unavailable"] >= 1
    assert lineage_final["rejection_counts"] == {
        "raw": 8,
        "canonical": 4,
        "generic_rows_ignored": 4,
        "duplicates": 0,
        "identity_unavailable": 0,
    }
    freshness = lineage_final["decision_observations"][0]["freshness"]
    assert freshness["stale_signal"] is True
    assert freshness["price_refresh_status"] == "unverified"
    assert candidates == active_before


def test_phase_a_failure_keeps_other_shadow_and_trading_active(tmp_path: Path, monkeypatch):
    row = _observation("INDEPENDENT", blocking=True)
    candidate = _candidate(0, row)
    active = {"candidates": [candidate], "recommendations": [{"signal_id": "active-signal"}], "plans": [{"plan_id": "active-plan"}], "orders": []}
    active_before = copy.deepcopy(active)

    def fail_p49(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("p49_phase_a_fixture_failure")

    monkeypatch.setattr(p49_shadow, "capture_data_quality_phase_a", fail_p49)
    try:
        p49_shadow.capture_data_quality_phase_a(cycle_id="combined-cycle", market_snapshot={}, candidates=[])
    except RuntimeError as exc:
        assert "p49_phase_a" in str(exc)
    p50_phase = build_learning_penalty_cycle_shadow(
        "combined-cycle", {"all_candidates": [candidate]}, active_candidates=[candidate], settings=_settings(tmp_path)
    )
    assert p50_phase["candidate_counts"]["identity_verified"] == 1
    assert active == active_before

    monkeypatch.undo()

    def fail_p50(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("p50_phase_a_fixture_failure")

    monkeypatch.setattr(p50_shadow, "build_learning_penalty_cycle_shadow", fail_p50)
    p49_phase = p49_shadow.capture_data_quality_phase_a(
        cycle_id="combined-cycle",
        market_snapshot={"observations": [row]},
        candidates=[candidate],
        decision_at=DECISION_AT,
        captured_at=DECISION_AT,
    )
    try:
        p50_shadow.build_learning_penalty_cycle_shadow("combined-cycle", {"all_candidates": [candidate]})
    except RuntimeError as exc:
        assert "p50_phase_a" in str(exc)
    assert p49_phase["denominators"]["blocking_observations"] == 1
    assert active == active_before


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


def test_p50_phase_a_failure_does_not_change_p49(tmp_path: Path, monkeypatch):
    row = _observation("MPC", blocking=True)
    candidate = _candidate(0, row)

    def fail_p50(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("p50_phase_a_fixture_failure")

    monkeypatch.setattr(p50_shadow, "build_learning_penalty_cycle_shadow", fail_p50)
    quality = p49_shadow.capture_data_quality_phase_a(
        cycle_id="combined-cycle",
        market_snapshot={"observations": [row]},
        candidates=[candidate],
        decision_at=DECISION_AT,
        captured_at=DECISION_AT,
    )
    assert quality["denominators"]["blocking_observations"] == 1
    try:
        p50_shadow.build_learning_penalty_cycle_shadow("combined-cycle", {"all_candidates": [candidate]})
    except RuntimeError as exc:
        assert "p50_phase_a" in str(exc)


def test_persistence_failures_are_independent_and_active_objects_unchanged(tmp_path: Path):
    row = _observation("PSX", blocking=True)
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
        "combined-cycle", {"all_candidates": [candidate]}, active_candidates=[candidate], settings=_settings(tmp_path)
    )
    before = copy.deepcopy(candidate)

    class QualityFailP50Ok:
        def record_data_quality_decision_shadow(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("p49_persist_fixture_failure")

        def record_learning_penalty_cycle_shadow(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {"status": "inserted"}

    class P50FailQualityOk:
        def record_data_quality_decision_shadow(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {"status": "inserted"}

        def record_learning_penalty_cycle_shadow(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("p50_persist_fixture_failure")

    try:
        persist_data_quality_decision_shadow(QualityFailP50Ok(), quality)
    except RuntimeError as exc:
        assert "p49_persist" in str(exc)
    assert persist_learning_penalty_cycle_shadow(QualityFailP50Ok(), lineage)["status"] == "inserted"
    assert persist_data_quality_decision_shadow(P50FailQualityOk(), quality)["status"] == "inserted"
    try:
        persist_learning_penalty_cycle_shadow(P50FailQualityOk(), lineage)
    except RuntimeError as exc:
        assert "p50_persist" in str(exc)
    assert candidate == before


def test_both_shadow_failures_leave_active_fixture_unchanged(tmp_path: Path):
    row = _observation("EIX", blocking=True)
    candidate = _candidate(0, row)
    active = {"candidates": [candidate], "recommendations": [], "plans": [], "orders": []}
    before = copy.deepcopy(active)

    class BothFail:
        def record_data_quality_decision_shadow(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("p49_persist_failure")

        def record_learning_penalty_cycle_shadow(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("p50_persist_failure")

    for operation in (
        lambda: persist_data_quality_decision_shadow(BothFail(), {"cycle_id": "combined-cycle"}),
        lambda: persist_learning_penalty_cycle_shadow(BothFail(), {"cycle_id": "combined-cycle"}),
    ):
        try:
            operation()
        except RuntimeError:
            pass
    assert active == before


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


def test_combined_persistence_is_concurrent_idempotent_and_conflict_separate(tmp_path: Path):
    cycle_id = "combined-persistence-cycle"
    store = Store(tmp_path / "state.sqlite", tmp_path / "logs")
    store.ensure_schema()
    row = _observation("PERSIST", blocking=True)
    candidate = _candidate(0, row)
    quality = finalize_quality(
        capture_data_quality_phase_a(
            cycle_id=cycle_id,
            market_snapshot={"observations": [row]},
            candidates=[candidate],
            decision_at=DECISION_AT,
            captured_at=DECISION_AT,
        ),
        cycle_id=cycle_id,
    )
    lineage = build_learning_penalty_cycle_shadow(
        cycle_id,
        {"all_candidates": [candidate]},
        active_candidates=[candidate],
        settings=_settings(tmp_path),
        captured_at="2026-07-20T14:00:00+00:00",
    )
    barrier = Barrier(2)

    def persist_pair() -> tuple[str, str]:
        barrier.wait()
        return (
            persist_data_quality_decision_shadow(store, quality)["status"],
            persist_learning_penalty_cycle_shadow(store, lineage)["status"],
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [future.result() for future in [executor.submit(persist_pair), executor.submit(persist_pair)]]

    assert [result for pair in results for result in pair].count("inserted") == 2
    assert [result for pair in results for result in pair].count("idempotent") == 2
    events = store.agent_events(cycle_id=cycle_id)
    canonical_ids = {event["event_id"] for event in events if not event["event_type"].endswith("_conflict")}
    assert canonical_ids == {
        f"data_quality_decision_shadow:{cycle_id}",
        f"learning_penalty_cycle_shadow:{cycle_id}",
    }

    quality_conflict = copy.deepcopy(quality)
    quality_conflict["warnings"] = ["different-content"]
    quality_conflict["content_hash"] = p49_shadow.canonical_content_hash(quality_conflict)
    lineage_conflict = copy.deepcopy(lineage)
    lineage_conflict["candidate_counts"]["ranked_buy_total"] = 2
    lineage_conflict["content_hash"] = "different-lineage-content"
    assert persist_data_quality_decision_shadow(store, quality_conflict)["status"] == "conflict"
    assert persist_learning_penalty_cycle_shadow(store, lineage_conflict)["status"] == "conflict"
    conflict_types = {event["event_type"] for event in store.agent_events(cycle_id=cycle_id) if event["event_type"].endswith("_conflict")}
    assert conflict_types == {"data_quality_decision_shadow_conflict", "learning_penalty_cycle_shadow_conflict"}


def test_phase_b_order_is_p49_then_p50_before_active_plan_persistence():
    source = (Path(__file__).parents[1] / "src" / "agente_bolsa" / "cycle_runner.py").read_text(encoding="utf-8")
    p49 = source.index("_data_quality_shadow_final = _persist_data_quality_decision_shadow_final")
    p50 = source.index("learning_penalty_shadow_final = _persist_learning_penalty_cycle_shadow_final")
    plans = source.index('optional_measure(timing, "persistence", "order_plan_records")')
    orders = source.index("submit_paper_order_plan", plans)
    assert p49 < p50 < plans < orders
