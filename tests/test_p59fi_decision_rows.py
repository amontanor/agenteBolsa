"""P-L59F-I: focal tests for decision_rows v2 in canonical selection ledger.

Tests the full contract: 8-state candidate summary, decision_rows identity,
plan/order/failure attachments, bounded 600, v1 reader backward compat,
P-L59C authority from decision_rows, no mutation, fail-open.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from agente_bolsa.storage import Store
from agente_bolsa.tools.canonical_selection_ledger import (
    DECISION_ROW_LIMIT,
    SCHEMA_VERSION,
    V1_SCHEMA_VERSION,
    build_canonical_selection_ledger,
    persist_canonical_selection_ledger,
    read_canonical_selection_ledger,
    stable_content_hash,
)

CAPTURED_AT = datetime(2026, 7, 27, 19, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "agent.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    return store


def _candidate_row(
    *,
    cycle_id: str = "cycle-test",
    session_date: str = "2026-07-27",
    signal_capture_id: str = "capture:tsla:buy",
    signal_id: str = "signal:tsla:buy",
    candidate_id: str = "candidate:tsla:buy",
    symbol: str = "TSLA",
    action: str = "buy",
    eligible: bool | None = True,
    selected: bool = True,
) -> dict[str, Any]:
    signal_at = datetime(2026, 7, 27, 15, 0, tzinfo=timezone.utc)
    return {
        "cycle_id": cycle_id,
        "session_date": session_date,
        "signal_capture_id": signal_capture_id,
        "signal_id": signal_id,
        "candidate_id": candidate_id,
        "source_run_id": "scan-A",
        "symbol": symbol,
        "action": action,
        "strategy": "builtin_breakout",
        "setup": "continuation",
        "score_universe": "domain-A",
        "score": 15.0,
        "selection_score": 0.8,
        "score_rank": 1,
        "selection_rank": 1,
        "data_quality": "good",
        "freshness": "fresh",
        "price_basis": "close_unadjusted",
        "signal_at": signal_at.isoformat(),
        "decision_at": signal_at.isoformat(),
        "eligible_at_selection": eligible,
        "gate_frontier": "entry_eligibility_v1",
        "selected_for_llm": selected,
    }


def _phase_a(*rows: dict[str, Any]) -> dict[str, Any]:
    return {"all_candidates": list(rows), "selected_candidates": list(rows)}


def _lineage(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "cycle_id": row["cycle_id"],
        "action": row["action"],
        "signal_capture_id": row["signal_capture_id"],
        "signal_id": row["signal_id"],
        "candidate_id": row["candidate_id"],
    }


def _recommendation(
    row: dict[str, Any],
    *,
    recommendation_id: str = "rec:A",
    source: str = "llm",
    llm_selected: bool | None = True,
    confidence: float = 0.85,
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "llm_considered": source in {"llm", "deterministic_capacity_fill"},
        "gate_frontier": row.get("gate_frontier"),
        "llm_selected": llm_selected,
    }
    if confidence is not None:
        snapshot["confidence"] = confidence
    return {
        "cycle_id": row["cycle_id"],
        "action": row["action"],
        "recommendation_id": recommendation_id,
        "source": source,
        "decision_origin": source,
        "confidence": confidence,
        "decision_lineage": _lineage(row),
        "decision_context_snapshot": snapshot,
    }


# ===================================================================
# 1. 8-STATE CANDIDATE SUMMARY TABLE
# ===================================================================


def test_state_0_observed_unavailable() -> None:
    """State 1: 0 observed -> unavailable, all singulars null."""
    row = _candidate_row()
    result = build_canonical_selection_ledger("cycle-0", _phase_a(row), captured_at=CAPTURED_AT)
    r = result["candidate_rows"][0]
    assert r["decision_summary_status"] == "unavailable"
    assert r["recommendation_id"] is None
    assert r["llm_selected"] is None
    assert r["decision_ids"] is None
    assert r["decision_rows_count"] is None
    assert len(result["decision_rows"]) == 0


def test_state_1_canonical() -> None:
    """State 2: exactly 1 canonical -> singular fields populated."""
    row = _candidate_row()
    rec = _recommendation(row, recommendation_id="rec:canon", llm_selected=True, confidence=0.90)
    result = build_canonical_selection_ledger(
        "cycle-1", _phase_a(row), recommendations=[rec], captured_at=CAPTURED_AT,
    )
    r = result["candidate_rows"][0]
    assert r["decision_summary_status"] == "canonical"
    assert r["recommendation_id"] == "rec:canon"
    assert r["llm_selected"] is True
    assert r["decision_source"] == "llm"
    assert r["confidence"] == 0.90
    assert r["decision_ids"] == ["rec:canon"]
    assert r["decision_rows_count"] == 1
    assert len(result["decision_rows"]) == 1
    assert result["decision_rows"][0]["decision_id"] == "rec:canon"


def test_state_2_ambiguous_multiple_canonical() -> None:
    """State 3: >1 canonical, different rec_id -> ambiguous, singulars null."""
    row = _candidate_row()
    rec_a = _recommendation(row, recommendation_id="rec:A")
    rec_b = _recommendation(row, recommendation_id="rec:B")
    result = build_canonical_selection_ledger(
        "cycle-2", _phase_a(row), recommendations=[rec_a, rec_b], captured_at=CAPTURED_AT,
    )
    r = result["candidate_rows"][0]
    assert r["decision_summary_status"] == "ambiguous"
    assert r["recommendation_id"] is None
    assert r["llm_selected"] is None
    assert r["decision_ids"] == ["rec:A", "rec:B"]
    assert r["decision_rows_count"] == 2
    assert len(result["decision_rows"]) == 2


def test_state_3_one_missing_id_partial() -> None:
    """State 4: 1 missing-ID -> partial, singulars null."""
    row = _candidate_row()
    rec = _recommendation(row, recommendation_id="")
    rec["recommendation_id"] = None
    result = build_canonical_selection_ledger(
        "cycle-3", _phase_a(row), recommendations=[rec], captured_at=CAPTURED_AT,
    )
    r = result["candidate_rows"][0]
    assert r["decision_summary_status"] == "partial"
    assert r["recommendation_id"] is None
    assert r["recommended"] is True
    assert len(result["decision_rows"]) == 0


def test_state_4_multiple_missing_id_ambiguous() -> None:
    """State 5: multiple missing-ID -> ambiguous, singulars null, 0 decision_rows."""
    row = _candidate_row()
    rec_a = _recommendation(row, recommendation_id="")
    rec_a["recommendation_id"] = None
    rec_b = _recommendation(row, recommendation_id="")
    rec_b["recommendation_id"] = None
    result = build_canonical_selection_ledger(
        "cycle-4", _phase_a(row), recommendations=[rec_a, rec_b], captured_at=CAPTURED_AT,
    )
    r = result["candidate_rows"][0]
    assert r["decision_summary_status"] == "ambiguous"
    assert r["recommendation_id"] is None
    assert len(result["decision_rows"]) == 0
    assert result["decision_detail_total"] == 0


def test_state_5_canonical_plus_missing_ambiguous() -> None:
    """State 6: 1 canonical + 1 missing-ID -> ambiguous."""
    row = _candidate_row()
    rec_ok = _recommendation(row, recommendation_id="rec:ok")
    rec_legacy = _recommendation(row, recommendation_id="")
    rec_legacy["recommendation_id"] = None
    result = build_canonical_selection_ledger(
        "cycle-5", _phase_a(row), recommendations=[rec_ok, rec_legacy], captured_at=CAPTURED_AT,
    )
    r = result["candidate_rows"][0]
    assert r["decision_summary_status"] == "ambiguous"
    assert r["recommendation_id"] is None
    assert len(result["decision_rows"]) == 1
    assert result["decision_rows"][0]["decision_id"] == "rec:ok"


def test_state_6_same_id_idempotent_duplicate_canonical() -> None:
    """State 7: same-ID duplicate (idempotent) -> canonical, 1 decision_row."""
    row = _candidate_row()
    rec_a = _recommendation(row, recommendation_id="rec:idem", llm_selected=True, confidence=0.80)
    rec_b = _recommendation(row, recommendation_id="rec:idem", llm_selected=True, confidence=0.80)
    result = build_canonical_selection_ledger(
        "cycle-6", _phase_a(row), recommendations=[rec_a, rec_b], captured_at=CAPTURED_AT,
    )
    r = result["candidate_rows"][0]
    assert r["decision_summary_status"] == "canonical"
    assert r["recommendation_id"] == "rec:idem"
    assert r["decision_ids"] == ["rec:idem"]
    assert len(result["decision_rows"]) == 1
    assert "decision_idempotent_duplicate" in result["warnings"]


def test_state_7_same_id_conflict_ambiguous() -> None:
    """State 8: same-ID different content -> ambiguous, original canonical + conflict."""
    row = _candidate_row()
    rec_a = _recommendation(row, recommendation_id="rec:conflict", source="llm", llm_selected=True, confidence=0.90)
    rec_b = _recommendation(row, recommendation_id="rec:conflict", source="capacity_fill", llm_selected=False, confidence=0.40)
    result = build_canonical_selection_ledger(
        "cycle-7", _phase_a(row), recommendations=[rec_a, rec_b], captured_at=CAPTURED_AT,
    )
    r = result["candidate_rows"][0]
    assert r["decision_summary_status"] == "ambiguous"
    assert r["recommendation_id"] is None
    # Original preserved as canonical, conflict entry added
    canonicals = [d for d in result["decision_rows"] if d["decision_identity"] == "verified"]
    conflicts = [d for d in result["decision_rows"] if d["decision_identity"] == "conflict"]
    assert len(canonicals) == 1
    assert canonicals[0]["llm_selected"] is True
    assert len(conflicts) == 1
    assert result["decision_conflict_count"] == 1


# ===================================================================
# 2. PLAN / ORDER / FAILURE ATTACHMENTS
# ===================================================================


def test_plan_attached_to_decision_row_by_recommendation_id() -> None:
    """Plan ID and status attached to decision_row via payload.recommendation."""
    row = _candidate_row()
    rec = _recommendation(row, recommendation_id="rec:planned")
    plan_record: dict[str, Any] = {
        "cycle_id": row["cycle_id"],
        "action": row["action"],
        "plan_id": "plan:xyz",
        "status": "PENDING",
        "decision_lineage": _lineage(row),
        "payload": {
            "recommendation": {"recommendation_id": "rec:planned"},
            "decision_lineage": _lineage(row),
        },
    }
    result = build_canonical_selection_ledger(
        "cycle-plan", _phase_a(row),
        recommendations=[rec],
        plan_records=[plan_record],
        captured_at=CAPTURED_AT,
    )
    # Decision row has plan attachment
    assert len(result["decision_rows"]) == 1
    d = result["decision_rows"][0]
    assert d["plan_id"] == "plan:xyz"
    assert d["plan_status"] == "PENDING"
    # Candidate row has planned=True
    assert result["candidate_rows"][0]["planned"] is True


def test_order_attached_to_decision_row_via_plan_id() -> None:
    """Broker order attached via plan_id -> plan_record -> recommendation_id."""
    row = _candidate_row()
    rec = _recommendation(row, recommendation_id="rec:ordered")
    plan_record: dict[str, Any] = {
        "cycle_id": row["cycle_id"],
        "action": row["action"],
        "plan_id": "plan:abc",
        "status": "SUBMITTED",
        "decision_lineage": _lineage(row),
        "payload": {
            "recommendation": {"recommendation_id": "rec:ordered"},
            "decision_lineage": _lineage(row),
        },
    }
    ordered_record: dict[str, Any] = {
        "cycle_id": row["cycle_id"],
        "action": row["action"],
        "plan_id": "plan:abc",
        "broker_order_id": "broker:123",
        "status": "accepted",
        "decision_lineage": _lineage(row),
    }
    result = build_canonical_selection_ledger(
        "cycle-order", _phase_a(row),
        recommendations=[rec],
        plan_records=[plan_record],
        ordered_records=[ordered_record],
        captured_at=CAPTURED_AT,
    )
    assert len(result["decision_rows"]) == 1
    d = result["decision_rows"][0]
    assert d["broker_order_id"] == "broker:123"
    assert d["order_status"] == "accepted"
    assert result["candidate_rows"][0]["ordered"] is True


def test_order_without_plan_record_does_not_attach_to_decision() -> None:
    """Order with plan_id not in any plan_record -> decision_row not attached.
    
    The candidate_row still gets marked ordered=True (by identity_key)."""
    row = _candidate_row()
    rec = _recommendation(row, recommendation_id="rec:orphan")
    ordered_record: dict[str, Any] = {
        "cycle_id": row["cycle_id"],
        "action": row["action"],
        "plan_id": "plan:no-match",
        "broker_order_id": "broker:orphan",
        "status": "accepted",
        "decision_lineage": _lineage(row),
    }
    result = build_canonical_selection_ledger(
        "cycle-orphan", _phase_a(row),
        recommendations=[rec],
        ordered_records=[ordered_record],
        captured_at=CAPTURED_AT,
    )
    # Decision row has no order attached (plan_id unknown)
    d = result["decision_rows"][0]
    assert d["broker_order_id"] is None
    # Candidate row still marked ordered
    assert result["candidate_rows"][0]["ordered"] is True


def test_rejection_attached_by_identity_and_recommendation_id() -> None:
    """Rejection updates both candidate_row (gated_out) and decision_row (rejection_reason)."""
    row = _candidate_row()
    rec = _recommendation(row, recommendation_id="rec:rejected")
    rejection: dict[str, Any] = {
        "cycle_id": row["cycle_id"],
        "action": row["action"],
        "recommendation_id": "rec:rejected",
        "reason": "cycle_capacity_limit",
        "decision_lineage": _lineage(row),
    }
    result = build_canonical_selection_ledger(
        "cycle-reject", _phase_a(row),
        recommendations=[rec],
        rejected_order_plans=[rejection],
        captured_at=CAPTURED_AT,
    )
    # Candidate: gated_out, rejected
    c = result["candidate_rows"][0]
    assert c["rejected"] is True
    assert c["gated_out"] is True
    assert c["planned"] is False
    assert c["exclusion_reason"] == "cycle_capacity_limit"
    # Decision: rejection_reason
    d = result["decision_rows"][0]
    assert d["rejection_reason"] == "cycle_capacity_limit"
    assert d["plan_status"] == "REJECTED"


def test_no_join_by_symbol_decision_rows_use_exact_ids() -> None:
    """Decision rows never join by symbol. Only exact recommendation_id/plan_id."""
    row = _candidate_row(symbol="AAPL")
    rec = _recommendation(row, recommendation_id="rec:aapl")
    # Different candidate, different symbol, no recommendation match
    row2 = _candidate_row(symbol="MSFT", signal_capture_id="capture:msft:buy",
                          signal_id="signal:msft", candidate_id="candidate:msft")
    rec2 = _recommendation(row2, recommendation_id="rec:msft")
    result = build_canonical_selection_ledger(
        "cycle-no-join", _phase_a(row, row2),
        recommendations=[rec, rec2], captured_at=CAPTURED_AT,
    )
    assert len(result["decision_rows"]) == 2
    aapl = [d for d in result["decision_rows"] if d["decision_id"] == "rec:aapl"]
    msft = [d for d in result["decision_rows"] if d["decision_id"] == "rec:msft"]
    assert len(aapl) == 1
    assert len(msft) == 1
    assert aapl[0]["signal_capture_id"] == "capture:tsla:buy"
    assert msft[0]["signal_capture_id"] == "capture:msft:buy"


def test_failed_order_attached_to_candidate_not_decision() -> None:
    """Failed orders update candidate (ordered=False) but not decision_row."""
    row = _candidate_row()
    rec = _recommendation(row, recommendation_id="rec:failed")
    failed: dict[str, Any] = {
        "cycle_id": row["cycle_id"],
        "action": row["action"],
        "reason": "risk_limit",
        "decision_lineage": _lineage(row),
    }
    result = build_canonical_selection_ledger(
        "cycle-fail-rec", _phase_a(row),
        recommendations=[rec],
        failed_records=[failed],
        captured_at=CAPTURED_AT,
    )
    assert result["candidate_rows"][0]["ordered"] is False
    assert result["candidate_rows"][0]["exclusion_reason"] == "risk_limit"
    # Decision row not affected
    d = result["decision_rows"][0]
    assert d["broker_order_id"] is None


# ===================================================================
# 3. BOUNDED 600
# ===================================================================


def test_bounded_600_decision_rows_truncated() -> None:
    """When >600 decision rows exist, only 600 persisted, counts correct."""
    rows = [_candidate_row(signal_capture_id=f"capture:{i}:buy", signal_id=f"signal:{i}",
                           candidate_id=f"candidate:{i}", symbol=f"SYM{i}")
            for i in range(650)]
    recs = [_recommendation(rows[i], recommendation_id=f"rec:{i}") for i in range(650)]
    result = build_canonical_selection_ledger(
        "cycle-601", _phase_a(*rows),
        recommendations=recs, captured_at=CAPTURED_AT,
    )
    assert result["decision_detail_total"] == 650
    assert result["decision_detail_persisted"] == DECISION_ROW_LIMIT  # 600
    assert result["decision_truncated_count"] == 50
    assert result["decision_conflict_count"] == 0
    assert len(result["decision_rows"]) == DECISION_ROW_LIMIT
    assert "decision_rows_truncated" in result["warnings"]
    assert result["status"] == "partial"


def test_bounded_600_order_stable() -> None:
    """Decision rows are sorted by identity_key + decision_id before truncation."""
    rows = [_candidate_row(signal_capture_id=f"capture:{i}:buy", signal_id=f"signal:{i}",
                           candidate_id=f"candidate:{i}", symbol=f"SYM{i}")
            for i in range(10)]
    recs = [_recommendation(rows[i], recommendation_id=f"rec:{i}") for i in range(10)]
    result = build_canonical_selection_ledger(
        "cycle-sorted", _phase_a(*rows),
        recommendations=recs, captured_at=CAPTURED_AT,
    )
    decision_ids = [d["decision_id"] for d in result["decision_rows"]]
    # Should be sorted: by identity_key then decision_id
    assert decision_ids == sorted(decision_ids)
    # All identity_keys are different but structured
    identity_keys = [d["identity_key"] for d in result["decision_rows"]]
    assert identity_keys == sorted(identity_keys)


def test_bounded_under_limit_all_persisted() -> None:
    """Under limit: all decision rows persisted, no truncation."""
    rows = [_candidate_row(signal_capture_id=f"capture:{i}:buy", signal_id=f"signal:{i}",
                           candidate_id=f"candidate:{i}", symbol=f"SYM{i}")
            for i in range(50)]
    recs = [_recommendation(rows[i], recommendation_id=f"rec:{i}") for i in range(50)]
    result = build_canonical_selection_ledger(
        "cycle-under", _phase_a(*rows),
        recommendations=recs, captured_at=CAPTURED_AT,
    )
    assert result["decision_detail_total"] == 50
    assert result["decision_detail_persisted"] == 50
    assert result["decision_truncated_count"] == 0
    assert len(result["decision_rows"]) == 50
    assert "decision_rows_truncated" not in result["warnings"]


# ===================================================================
# 4. V1 READER BACKWARD COMPATIBILITY
# ===================================================================


def test_v2_persist_read_idempotent(tmp_path: Path) -> None:
    """V2 payload persists and reads with decision_rows."""
    store = _store(tmp_path)
    row = _candidate_row()
    rec = _recommendation(row, recommendation_id="rec:v2")
    payload = build_canonical_selection_ledger(
        "cycle-v2", _phase_a(row), recommendations=[rec], captured_at=CAPTURED_AT,
    )
    assert payload["schema_version"] == SCHEMA_VERSION
    assert len(payload["decision_rows"]) == 1

    # Persist and read back
    result = persist_canonical_selection_ledger(store, payload)
    assert result["status"] == "inserted"

    read_back = read_canonical_selection_ledger(store, "cycle-v2")
    assert read_back["schema_version"] == SCHEMA_VERSION
    assert len(read_back["decision_rows"]) == 1
    assert read_back["decision_rows"][0]["decision_id"] == "rec:v2"
    assert read_back["denominators"]["recommendation_canonical"] == 1


def test_v2_persist_idempotent(tmp_path: Path) -> None:
    """Same v2 payload persisted twice -> idempotent."""
    store = _store(tmp_path)
    row = _candidate_row()
    rec = _recommendation(row, recommendation_id="rec:idem")
    p1 = build_canonical_selection_ledger(
        "cycle-idem", _phase_a(row), recommendations=[rec], captured_at=CAPTURED_AT,
    )
    p2 = build_canonical_selection_ledger(
        "cycle-idem", _phase_a(row), recommendations=[rec], captured_at=CAPTURED_AT,
    )
    assert persist_canonical_selection_ledger(store, p1)["status"] == "inserted"
    assert persist_canonical_selection_ledger(store, p2)["status"] == "idempotent"


def test_v2_persist_conflict_different_decision_rows(tmp_path: Path) -> None:
    """Different v2 payloads (different decision content) -> conflict."""
    store = _store(tmp_path)
    row = _candidate_row()
    rec_a = _recommendation(row, recommendation_id="rec:A", llm_selected=True)
    rec_b = _recommendation(row, recommendation_id="rec:A", llm_selected=False)
    p1 = build_canonical_selection_ledger(
        "cycle-conflict", _phase_a(row), recommendations=[rec_a], captured_at=CAPTURED_AT,
    )
    p2 = build_canonical_selection_ledger(
        "cycle-conflict", _phase_a(row), recommendations=[rec_b], captured_at=CAPTURED_AT,
    )
    assert persist_canonical_selection_ledger(store, p1)["status"] == "inserted"
    assert persist_canonical_selection_ledger(store, p2)["status"] == "conflict"
    read_back = read_canonical_selection_ledger(store, "cycle-conflict")
    # Original preserved
    assert read_back["decision_rows"][0]["llm_selected"] is True


def test_v1_payload_reads_as_legacy(tmp_path: Path) -> None:
    """V1 payload (simulated) reads with decision_rows=None and v2 denoms null."""
    store = _store(tmp_path)
    # Manually construct a v1 payload and write it directly
    v1_payload = {
        "schema_version": V1_SCHEMA_VERSION,
        "event_id": "canonical_selection_ledger:cycle-v1",
        "event_type": "canonical_selection_ledger",
        "cycle_id": "cycle-v1",
        "status": "verified",
        "candidate_rows": [
            {
                "identity_key": "cycle-v1|buy|capture:x",
                "identity_status": "verified",
                "cycle_id": "cycle-v1",
                "action": "buy",
                "session_date": "2026-07-27",
                "recommended": True,
                "recommendation_id": "rec:old",
                "llm_selected": True,
                "symbol": "TSLA",
            }
        ],
        "denominators": {
            "raw_count": 1, "canonical_count": 1, "eligible_count": 1,
            "selected_count": 1, "recommended_count": 1, "planned_count": 0,
            "ordered_count": 0, "identity_unavailable": 0, "identity_ambiguous": 0,
            "shadow_inputs_unavailable": 0, "conflict_count": 0, "truncated_count": 0,
        },
        "warnings": [],
        "captured_at": CAPTURED_AT.isoformat(),
        "conflicts": 0,
        "outcomes": None,
    }
    v1_payload["content_hash"] = stable_content_hash(v1_payload)
    store.record_canonical_selection_ledger(v1_payload, event_id=v1_payload["event_id"])

    read_back = read_canonical_selection_ledger(store, "cycle-v1")
    assert read_back["schema_version"] == V1_SCHEMA_VERSION
    assert read_back["decision_rows"] is None
    assert read_back["decision_detail_total"] is None
    assert read_back["denominators"]["recommendation_canonical"] is None
    # V1 candidate gets v2 summary fields as None
    assert read_back["candidate_rows"][0]["decision_summary_status"] is None


# ===================================================================
# 5. P-L59C AUTHORITY FROM decision_rows
# ===================================================================


def test_llm_selected_true_in_decision_row() -> None:
    """P-L59C: llm_selected=True set by LLM producer, readable from decision_row."""
    row = _candidate_row()
    rec = _recommendation(row, recommendation_id="rec:llm", source="llm", llm_selected=True)
    result = build_canonical_selection_ledger(
        "cycle-llm", _phase_a(row), recommendations=[rec], captured_at=CAPTURED_AT,
    )
    d = result["decision_rows"][0]
    assert d["llm_selected"] is True
    assert d["decision_source"] == "llm"


def test_llm_selected_false_in_decision_row() -> None:
    """P-L59C: llm_selected=False set by capacity_fill producer."""
    row = _candidate_row()
    rec = _recommendation(row, recommendation_id="rec:cf", source="capacity_fill", llm_selected=False)
    result = build_canonical_selection_ledger(
        "cycle-cf", _phase_a(row), recommendations=[rec], captured_at=CAPTURED_AT,
    )
    d = result["decision_rows"][0]
    assert d["llm_selected"] is False
    assert d["decision_source"] == "deterministic_capacity_fill"


def test_llm_selected_none_legacy_in_decision_row() -> None:
    """P-L59C: llm_selected=None for legacy/missing in decision_row."""
    row = _candidate_row()
    snapshot: dict[str, Any] = {
        "llm_considered": False,
        "gate_frontier": row["gate_frontier"],
    }
    # No llm_selected in snapshot
    rec: dict[str, Any] = {
        "cycle_id": row["cycle_id"],
        "action": row["action"],
        "recommendation_id": "rec:legacy",
        "source": "unknown",
        "decision_lineage": _lineage(row),
        "decision_context_snapshot": snapshot,
    }
    result = build_canonical_selection_ledger(
        "cycle-legacy", _phase_a(row), recommendations=[rec], captured_at=CAPTURED_AT,
    )
    d = result["decision_rows"][0]
    assert d["llm_selected"] is None


# ===================================================================
# 6. NO MUTATION
# ===================================================================


def test_input_objects_not_mutated() -> None:
    """build_canonical_selection_ledger does not mutate input objects."""
    phase = _phase_a(_candidate_row())
    before_phase = copy.deepcopy(phase)
    rec_a = _recommendation(phase["all_candidates"][0])
    rec_b = _recommendation(phase["all_candidates"][0], recommendation_id="rec:B")
    before_recs = copy.deepcopy([rec_a, rec_b])

    build_canonical_selection_ledger(
        "cycle-no-mut", phase,
        recommendations=[rec_a, rec_b], captured_at=CAPTURED_AT,
    )
    assert phase == before_phase
    assert [rec_a, rec_b] == before_recs


def test_decision_row_fields_no_forward_looking() -> None:
    """Decision rows reject forward-looking fields."""
    row = _candidate_row()
    rec = _recommendation(row, recommendation_id="rec:ok")
    rec["return_3d"] = 0.12
    with pytest.raises(ValueError, match="predecision_forbidden_field:return_3d"):
        build_canonical_selection_ledger(
            "cycle-forbidden", _phase_a(row),
            recommendations=[rec], captured_at=CAPTURED_AT,
        )


# ===================================================================
# 7. FAIL-OPEN
# ===================================================================


def test_decision_rows_fail_open_does_not_block_payload() -> None:
    """Even if decision_rows builder encounters issues, the payload is still built.
    
    The build_canonical_selection_ledger function must not fail when
    decision-related inputs are problematic - it degrades gracefully."""
    row = _candidate_row()
    # Empty recommendations: fine, no decision rows
    result = build_canonical_selection_ledger(
        "cycle-empty", _phase_a(row),
        recommendations=[], captured_at=CAPTURED_AT,
    )
    assert len(result["decision_rows"]) == 0
    assert result["status"] in {"verified", "partial"}
    assert len(result["candidate_rows"]) == 1

    # None recommendations: fine
    result2 = build_canonical_selection_ledger(
        "cycle-none", _phase_a(row),
        recommendations=None, captured_at=CAPTURED_AT,
    )
    assert len(result2["decision_rows"]) == 0
    assert result2["status"] in {"verified", "partial"}


def test_missing_phase_a_returns_collecting_with_null_decision_rows() -> None:
    """When phase_a is None, status=collecting and decision_rows=[]."""
    result = build_canonical_selection_ledger("cycle-null", None, captured_at=CAPTURED_AT)
    assert result["status"] == "collecting"
    assert result["decision_rows"] == []
    assert result["candidate_rows"] == []
    assert result["denominators"]["raw_count"] is None


# ===================================================================
# 8. DENOMINATORS V2
# ===================================================================


def test_v2_denominators_count_correctly() -> None:
    """V2 denominators: candidate_count, recommendation_observed/canonical/conflict/unavailable."""
    row = _candidate_row()
    rec = _recommendation(row, recommendation_id="rec:den", llm_selected=True)
    result = build_canonical_selection_ledger(
        "cycle-den", _phase_a(row), recommendations=[rec], captured_at=CAPTURED_AT,
    )
    denom = result["denominators"]
    assert denom["candidate_count"] == 1
    assert denom["recommendation_observed"] == 1
    assert denom["recommendation_canonical"] == 1
    assert denom["recommendation_conflict"] == 0
    assert denom["recommendation_unavailable"] == 0


def test_v2_denominators_with_missing_id() -> None:
    """Missing-ID recommendations contribute to recommendation_unavailable."""
    row = _candidate_row()
    rec = _recommendation(row, recommendation_id="")
    rec["recommendation_id"] = None
    result = build_canonical_selection_ledger(
        "cycle-unavail", _phase_a(row), recommendations=[rec], captured_at=CAPTURED_AT,
    )
    denom = result["denominators"]
    assert denom["recommendation_observed"] == 0
    assert denom["recommendation_canonical"] == 0
    assert denom["recommendation_unavailable"] == 1


def test_v2_denominators_ambiguous_candidate_counts_unavailable() -> None:
    """Ambiguous candidate (2 rec IDs) -> recommendation_unavailable = 1."""
    row = _candidate_row()
    rec_a = _recommendation(row, recommendation_id="rec:A")
    rec_b = _recommendation(row, recommendation_id="rec:B")
    result = build_canonical_selection_ledger(
        "cycle-ambig-den", _phase_a(row), recommendations=[rec_a, rec_b], captured_at=CAPTURED_AT,
    )
    denom = result["denominators"]
    assert denom["recommendation_observed"] == 2
    assert denom["recommendation_canonical"] == 2
    # recommendation_unavailable: candidate has decision_summary_status=ambiguous
    # and recommendation_id is None and decision_rows_count > 0
    assert denom["recommendation_unavailable"] == 1


# ===================================================================
# 9. CONTENT HASH STABILITY
# ===================================================================


def test_decision_row_hash_stable() -> None:
    """Same inputs produce same decision_row content_hash."""
    row = _candidate_row()
    rec = _recommendation(row, recommendation_id="rec:hash")
    r1 = build_canonical_selection_ledger(
        "cycle-hash", _phase_a(row), recommendations=[rec], captured_at=CAPTURED_AT,
    )
    r2 = build_canonical_selection_ledger(
        "cycle-hash", _phase_a(row), recommendations=[rec],
        captured_at=datetime(2026, 7, 27, 20, 0, tzinfo=timezone.utc),
    )
    # Different captured_at -> different payload hash
    assert r1["content_hash"] != r2["content_hash"]
    # But decision row content hash should be the same (captured_at excluded)
    assert r1["decision_rows"][0]["content_hash"] == r2["decision_rows"][0]["content_hash"]


def test_decision_row_hash_ignores_captured_at() -> None:
    """Decision row content_hash excludes captured_at."""
    row = _candidate_row()
    rec = _recommendation(row, recommendation_id="rec:capture")
    r1 = build_canonical_selection_ledger(
        "cycle-cap1", _phase_a(row), recommendations=[rec],
        captured_at=datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc),
    )
    r2 = build_canonical_selection_ledger(
        "cycle-cap2", _phase_a(row), recommendations=[rec],
        captured_at=datetime(2026, 7, 27, 11, 0, tzinfo=timezone.utc),
    )
    assert r1["decision_rows"][0]["content_hash"] == r2["decision_rows"][0]["content_hash"]
