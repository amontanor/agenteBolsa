"""Caracterizacion pura de la frontera de linaje e inputs de P-L50T.

Este modulo modela contratos observados con fixtures sanitizadas. No importa
Store, no escribe SQLite y no ejecuta ninguna etapa activa del ciclo.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

IDENTITY_FIELDS = (
    "cycle_id",
    "signal_capture_id",
    "signal_id",
    "candidate_id",
    "recommendation_id",
    "plan_id",
    "action",
)


def _candidate(index: int, *, cycle_id: str = "cycle-1") -> dict[str, Any]:
    return {
        "symbol": f"S{index:03d}",
        "cycle_id": cycle_id,
        "signal_capture_id": f"capture-{index}",
        "signal_id": f"signal-{index}",
        "candidate_id": f"candidate-{index}",
        "candidate_rank": index + 1,
        "rank_priority_score": 0.9 - index / 1000,
        "learning_prior": {
            "setup_edge_3d_raw": -0.0007,
            "operational_penalty": 0.05,
            "expected_edge_3d": -0.0507,
            "sample_size": 27957,
        },
        "action": "buy",
    }


def classify_identity(row: dict[str, Any], outer_cycle_id: str, seen: set[tuple[str, str]]) -> str:
    """Clasifica solo por IDs; nunca por simbolo o fecha."""

    capture = str(row.get("signal_capture_id") or "").strip()
    signal = str(row.get("signal_id") or "").strip()
    cycle = str(row.get("cycle_id") or "").strip()
    if not capture and not signal:
        return "identity_unavailable"
    if cycle != outer_cycle_id or (capture and signal and (capture, signal) in seen):
        return "identity_ambiguous"
    seen.add((capture, signal))
    return "identity_verified"


def classify_shadow_inputs(row: dict[str, Any], identity: str) -> str:
    if identity != "identity_verified":
        return "shadow_inputs_unavailable"
    if isinstance(row.get("rank_priority_score"), (int, float)) and isinstance(
        row.get("learning_prior"), dict
    ):
        return "shadow_inputs_available"
    return "shadow_inputs_unavailable"


def classify_vtrs_collision(rows: list[dict[str, Any]]) -> dict[str, Any]:
    signal_keys = {
        (
            row.get("cycle_id"),
            row.get("signal_capture_id"),
            row.get("candidate_id"),
        )
        for row in rows
    }
    decision_keys = {
        (
            row.get("cycle_id"),
            row.get("signal_capture_id"),
            row.get("candidate_id"),
            row.get("recommendation_id"),
            row.get("action"),
        )
        for row in rows
    }
    actions = {row.get("action") for row in rows}
    return {
        "signal_identity": "ambiguous" if len(signal_keys) == 1 and len(actions) > 1 else "distinct",
        "decision_identity": "distinct" if len(decision_keys) == len(rows) else "ambiguous",
        "deduplicated": False,
    }


def deduplicate_rejections(rows: list[dict[str, Any]]) -> dict[str, Any]:
    canonical = [row for row in rows if str(row.get("event_id", "")).startswith("rejection:")]
    generic = [row for row in rows if not str(row.get("event_id", "")).startswith("rejection:")]
    keys = {
        (
            row.get("cycle_id"),
            row.get("candidate_id"),
            row.get("signal_id"),
            row.get("reason_code"),
            row.get("stage"),
        )
        for row in canonical
    }
    return {
        "raw": len(rows),
        "canonical_raw": len(canonical),
        "generic_ignored": len(generic),
        "unique_exact": len(keys),
    }


def structured_learning(row: dict[str, Any]) -> dict[str, Any]:
    """Solo lee campos estructurados; el texto libre no es una fuente valida."""

    prior = row.get("learning_prior") if isinstance(row.get("learning_prior"), dict) else {}
    return {
        "candidate_rank": row.get("candidate_rank"),
        "score_rank": row.get("score_rank"),
        "score": row.get("score"),
        "setup_edge_3d_raw": prior.get("setup_edge_3d_raw"),
        "operational_penalty": prior.get("operational_penalty"),
        "expected_edge_3d": prior.get("expected_edge_3d"),
        "sample_size": prior.get("sample_size"),
    }


def control_coverage(rows: list[dict[str, Any]]) -> dict[str, int]:
    explicit_unavailable = sum(
        isinstance(row.get("comparable_control_set"), dict)
        and row["comparable_control_set"].get("status") == "unavailable"
        for row in rows
    )
    verified = sum(
        isinstance(row.get("comparable_control_set"), dict)
        and row["comparable_control_set"].get("status") == "verified"
        for row in rows
    )
    return {
        "recommendations": len(rows),
        "explicit_unavailable": explicit_unavailable,
        "missing": len(rows) - explicit_unavailable - verified,
        "verified": verified,
    }


def characterize_freshness(
    *, signal_at: str, submitted_at: str, signal_price: float, plan_price: float, quote_at: str | None
) -> dict[str, Any]:
    signal = datetime.fromisoformat(signal_at)
    submitted = datetime.fromisoformat(submitted_at)
    delay = (submitted - signal).total_seconds()
    return {
        "signal_to_submit_seconds": delay,
        "stale_signal": delay > 600,
        "price_refresh_status": "verified" if quote_at else "unverified",
        "same_price_without_refresh": signal_price == plan_price and quote_at is None,
        "decision_unchanged": True,
    }


def frontier_matrix() -> list[dict[str, Any]]:
    fields = {field: None for field in IDENTITY_FIELDS}
    return [
        {"boundary": "technical/raw candidates", **fields, "classification": "produced"},
        {
            "boundary": "annotated learning context",
            **fields,
            "classification": "present only when producer enriches the copy",
        },
        {
            "boundary": "ranked/P-L44 Phase A",
            **fields,
            "classification": "object received without canonical IDs in observed wiring",
        },
        {
            "boundary": "recommendation",
            **fields,
            "classification": "lineage rebuilt/persisted after decision",
        },
        {
            "boundary": "gate/rejection",
            **fields,
            "classification": "partial identity for rejection rows",
        },
        {
            "boundary": "plan",
            **fields,
            "classification": "plan_id appears only after decision",
        },
    ]


def test_mass_fixture_separates_identity_and_learning_inputs():
    rows = [_candidate(index) for index in range(420)]
    rows.extend({"symbol": f"M{index}", "cycle_id": "cycle-1"} for index in range(8))
    rows.extend(deepcopy(rows[index]) for index in range(5))
    rows.extend(_candidate(500 + index, cycle_id="cycle-other") for index in range(5))
    rows.extend(
        {key: value for key, value in _candidate(600 + index).items() if key != "learning_prior"}
        for index in range(5)
    )

    assert len(rows) == 443
    seen: set[tuple[str, str]] = set()
    identities = [classify_identity(row, "cycle-1", seen) for row in rows]
    inputs = [
        classify_shadow_inputs(row, identity)
        for row, identity in zip(rows, identities, strict=True)
    ]
    assert identities.count("identity_verified") == 425
    assert identities.count("identity_unavailable") == 8
    assert identities.count("identity_ambiguous") == 10
    assert inputs.count("shadow_inputs_available") == 420
    assert inputs.count("shadow_inputs_unavailable") == 23
    assert not any("UNKNOWN" in str(row) for row in rows)


def test_vtrs_signal_collision_is_ambiguous_without_silent_deduplication():
    rows = [
        {
            "cycle_id": "mkt-vtrs",
            "signal_capture_id": "capture-vtrs",
            "signal_id": "signal-vtrs",
            "candidate_id": "candidate-vtrs",
            "recommendation_id": "rec-buy",
            "action": "buy",
        },
        {
            "cycle_id": "mkt-vtrs",
            "signal_capture_id": "capture-vtrs",
            "signal_id": "signal-vtrs",
            "candidate_id": "candidate-vtrs",
            "recommendation_id": "rec-exit",
            "action": "exit",
        },
    ]
    result = classify_vtrs_collision(rows)
    assert result == {
        "signal_identity": "ambiguous",
        "decision_identity": "distinct",
        "deduplicated": False,
    }


def test_rejection_rows_are_six_exact_events_and_six_generic_duplicates():
    canonical = [
        {
            "event_id": f"rejection:cycle-{index}",
            "cycle_id": f"cycle-{index}",
            "candidate_id": f"candidate-{index}",
            "signal_id": f"signal-{index}",
            "reason_code": "position_sizing",
            "stage": "position_sizing",
        }
        for index in range(6)
    ]
    rows = canonical + [
        {**row, "event_id": f"evt-generic-{index}"} for index, row in enumerate(canonical)
    ]
    result = deduplicate_rejections(rows)
    assert result == {"raw": 12, "canonical_raw": 6, "generic_ignored": 6, "unique_exact": 6}


def test_structured_score_and_prior_missing_stay_unavailable_not_zero():
    row = {
        "candidate_rank": 7,
        "reason": "score_rank=2; score=14.3",  # no se debe parsear
        "learning_prior": {"operational_penalty": 0.05},
    }
    result = structured_learning(row)
    assert result["candidate_rank"] == 7
    assert result["score_rank"] is None
    assert result["score"] is None
    assert result["setup_edge_3d_raw"] is None
    assert result["expected_edge_3d"] is None
    assert result["sample_size"] is None


def test_controls_51_recommendations_have_zero_verified_controls():
    rows = [{"recommendation_id": f"rec-{index}"} for index in range(50)]
    rows.append(
        {
            "recommendation_id": "rec-unavailable",
            "comparable_control_set": {"status": "unavailable", "reason": "no_alternative"},
        }
    )
    assert control_coverage(rows) == {
        "recommendations": 51,
        "explicit_unavailable": 1,
        "missing": 50,
        "verified": 0,
    }


def test_freshness_is_descriptive_and_does_not_create_a_gate():
    result = characterize_freshness(
        signal_at="2026-07-20T13:45:21.140341+00:00",
        submitted_at="2026-07-20T16:08:45.140012+00:00",
        signal_price=339.9,
        plan_price=339.9,
        quote_at=None,
    )
    assert result["signal_to_submit_seconds"] == pytest.approx(8603.999671)
    assert result["stale_signal"] is True
    assert result["price_refresh_status"] == "unverified"
    assert result["same_price_without_refresh"] is True
    assert result["decision_unchanged"] is True


def test_frontier_matrix_keeps_post_decision_fields_distinct():
    matrix = frontier_matrix()
    assert [row["boundary"] for row in matrix] == [
        "technical/raw candidates",
        "annotated learning context",
        "ranked/P-L44 Phase A",
        "recommendation",
        "gate/rejection",
        "plan",
    ]
    assert matrix[2]["classification"].startswith("object received without")
    assert matrix[3]["classification"].startswith("lineage rebuilt")
    assert matrix[-1]["plan_id"] is None


def test_helpers_are_pure_and_do_not_invoke_active_stages():
    active_stages_called: list[str] = []

    def forbidden(stage: str) -> None:
        active_stages_called.append(stage)
        raise AssertionError(f"active stage invoked: {stage}")

    original = {"candidate": _candidate(1), "recommendation": {"action": "buy"}}
    before = deepcopy(original)
    _ = classify_identity(original["candidate"], "cycle-1", set())
    _ = classify_shadow_inputs(original["candidate"], "identity_verified")
    _ = structured_learning(original["candidate"])
    _ = characterize_freshness(
        signal_at="2026-07-20T13:45:21+00:00",
        submitted_at="2026-07-20T13:45:22+00:00",
        signal_price=1.0,
        plan_price=1.0,
        quote_at=None,
    )
    assert original == before
    assert active_stages_called == []
    assert forbidden.__name__ == "forbidden"


def test_source_inventory_matches_observed_phase_boundary():
    root = Path(__file__).parents[1]
    scheduler = (root / "src" / "agente_bolsa" / "scheduler.py").read_text(encoding="utf-8")
    shadow = (
        root / "src" / "agente_bolsa" / "tools" / "learning_penalty_cycle_shadow.py"
    ).read_text(encoding="utf-8")
    lineage = (root / "src" / "agente_bolsa" / "tools" / "decision_lineage.py").read_text(
        encoding="utf-8"
    )

    assert "report[\"_learning_penalty_ranked_context\"] = ranked_report" in scheduler
    assert "project_learning_penalty_phase_a_context(ranked_context)" in scheduler
    assert "phase_a_context.get(\"all_candidates\")" in scheduler
    assert "ranked_context = report.pop(\"_learning_penalty_ranked_context\", None)" in scheduler
    assert "signal_capture_id" in shadow and "signal_id" in shadow
    assert "build_decision_lineage" in lineage
