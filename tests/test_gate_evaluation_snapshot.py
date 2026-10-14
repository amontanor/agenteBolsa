import pytest

from agente_bolsa.models import TradeRecommendation
from agente_bolsa.storage import Store
from agente_bolsa.tools.gate_evaluation import (
    GATE_ORDER,
    build_gate_effectiveness_quality,
    collect_gate_path,
    validate_gate_snapshot,
)


def _candidate(*, signal="sig-1", candidate="cand-1", capture=None, action="buy"):
    lineage = {"signal_id": signal, "candidate_id": candidate, "cycle_id": "cycle-1"}
    if capture:
        lineage["signal_capture_id"] = capture
    return TradeRecommendation(
        symbol="AAA",
        action=action,
        confidence=0.8,
        reason="test",
        entry_price=100.0,
        decision_lineage=lineage,
        decision_context_snapshot={
            "snapshot_id": "ctx-1",
            "captured_at": "2026-07-12T10:00:00+00:00",
            "market_state_ref": {"content_hash": "mkt-hash"},
        },
    )


def _rows(*, blocked=False):
    return {
        "deterministic_review": [{"candidate_id": "cand-1", "signal_id": "sig-1", "cycle_id": "cycle-1", "symbol": "AAA", "action": "buy", "approved": True}],
        "adversarial_review": [{"candidate_id": "cand-1", "signal_id": "sig-1", "cycle_id": "cycle-1", "approved": True}],
        "entry_quality": [{"candidate_id": "cand-1", "signal_id": "sig-1", "cycle_id": "cycle-1", "approved": not blocked, "reason": "entry_quality_failed" if blocked else None}],
    }


def test_collector_initializes_full_order_without_running_gates():
    snap = collect_gate_path(cycle_id="cycle-1", candidates=[_candidate()], stage_rows=_rows(blocked=True), captured_at="2026-07-12T10:01:00+00:00")["cand-1"]
    assert [x["gate_name"] for x in snap["gate_path"]] == [x[0] for x in GATE_ORDER]
    assert snap["terminal_gate"] == "entry_quality"
    assert all(x["status"] == "not_evaluated" for x in snap["gate_path"][3:])
    assert snap["decision"] == "blocked"
    assert validate_gate_snapshot(snap) == (True, None)


def test_admitted_requires_final_plan_and_keeps_missing_gates_unavailable():
    candidate = _candidate()
    snap = collect_gate_path(
        cycle_id="cycle-1", candidates=[candidate], stage_rows=_rows(), final_plans=[type("Plan", (), {"recommendation": candidate})()], captured_at="2026-07-12T10:01:00+00:00"
    )["cand-1"]
    assert snap["decision"] == "admitted"
    assert snap["gate_path"][3]["status"] == "unavailable"
    assert snap["identity_status"] == "verified"


def test_shared_signal_id_keeps_buy_and_exit_gate_paths_separate():
    buy = _candidate(signal="daily:AAA", candidate="buy-candidate", action="buy")
    exit = _candidate(signal="daily:AAA", candidate="exit-candidate", action="exit")
    rows = {
        "duplicate_symbol": [{
            "candidate_id": "buy-candidate",
            "signal_id": "daily:AAA",
            "cycle_id": "cycle-1",
            "action": "buy",
            "approved": False,
            "reason": "buy-only",
        }],
    }
    plan = type("Plan", (), {"recommendation": exit})()
    result = collect_gate_path(
        cycle_id="cycle-1",
        candidates=[buy, exit],
        stage_rows=rows,
        final_plans=[plan],
        captured_at="2026-07-12T10:01:00+00:00",
    )

    buy_snapshot = result["buy-candidate"]
    exit_snapshot = result["exit-candidate"]
    buy_duplicate = buy_snapshot["gate_path"][10]
    exit_duplicate = exit_snapshot["gate_path"][10]
    assert buy_duplicate["status"] == "blocked"
    assert buy_snapshot["decision"] == "blocked"
    assert exit_duplicate["status"] == "unavailable"
    assert exit_snapshot["decision"] == "admitted"


def test_signal_only_gate_row_with_other_action_is_unavailable():
    candidate = _candidate(signal="daily:AAA", candidate="exit-candidate", action="exit")
    snapshot = collect_gate_path(
        cycle_id="cycle-1",
        candidates=[candidate],
        stage_rows={
            "duplicate_symbol": [{
                "signal_id": "daily:AAA",
                "action": "buy",
                "approved": False,
            }],
        },
        captured_at="2026-07-12T10:01:00+00:00",
    )["exit-candidate"]
    duplicate = snapshot["gate_path"][10]
    assert duplicate["status"] == "unavailable"
    assert duplicate["identity_link_status"] == "unavailable"


@pytest.mark.parametrize("field, value", [("signal_capture_id", "capture-other"), ("signal_id", "sig-other")])
def test_same_candidate_with_conflicting_canonical_id_is_unavailable(field, value):
    candidate = _candidate(capture="capture-1")
    row = {
        "candidate_id": "cand-1",
        "signal_capture_id": "capture-1",
        "signal_id": "sig-1",
        "cycle_id": "cycle-1",
        "action": "buy",
        "approved": False,
    }
    row[field] = value
    snapshot = collect_gate_path(
        cycle_id="cycle-1",
        candidates=[candidate],
        stage_rows={"duplicate_symbol": [row]},
        captured_at="2026-07-12T10:01:00+00:00",
    )["cand-1"]
    duplicate = snapshot["gate_path"][10]
    assert duplicate["status"] == "unavailable"
    assert duplicate["identity_link_status"] == "conflict"


def test_same_capture_with_conflicting_candidate_is_unavailable():
    candidate = _candidate(capture="capture-1")
    snapshot = collect_gate_path(
        cycle_id="cycle-1",
        candidates=[candidate],
        stage_rows={
            "duplicate_symbol": [{
                "candidate_id": "cand-other",
                "signal_capture_id": "capture-1",
                "signal_id": "sig-1",
                "cycle_id": "cycle-1",
                "action": "buy",
                "approved": False,
            }],
        },
        captured_at="2026-07-12T10:01:00+00:00",
    )["cand-1"]
    duplicate = snapshot["gate_path"][10]
    assert duplicate["status"] == "unavailable"
    assert duplicate["identity_link_status"] == "conflict"


def test_same_candidate_without_row_cycle_is_unavailable():
    candidate = _candidate()
    snapshot = collect_gate_path(
        cycle_id="cycle-1",
        candidates=[candidate],
        stage_rows={
            "duplicate_symbol": [{
                "candidate_id": "cand-1",
                "signal_id": "sig-1",
                "action": "buy",
                "approved": False,
            }],
        },
        captured_at="2026-07-12T10:01:00+00:00",
    )["cand-1"]
    duplicate = snapshot["gate_path"][10]
    assert duplicate["status"] == "unavailable"
    assert duplicate["identity_link_status"] == "conflict"


def test_terminal_rejection_cannot_become_admitted_from_final_plan():
    candidate = _candidate()
    snapshot = collect_gate_path(
        cycle_id="cycle-1",
        candidates=[candidate],
        stage_rows={
            "duplicate_symbol": [{
                "candidate_id": "cand-1",
                "signal_id": "sig-1",
                "cycle_id": "cycle-1",
                "action": "buy",
                "approved": False,
                "reason": "duplicate_symbol",
            }],
        },
        final_plans=[type("Plan", (), {"recommendation": candidate})()],
        captured_at="2026-07-12T10:01:00+00:00",
    )["cand-1"]
    assert snapshot["decision"] == "unavailable"
    assert snapshot["terminal_gate"] == "duplicate_symbol"
    assert snapshot["authority_conflict"] is True
    assert snapshot["gate_path"][10]["status"] == "blocked"


def test_duplicate_rows_same_identity_are_conflict_and_cannot_admit():
    candidate = _candidate()
    row = {
        "candidate_id": "cand-1",
        "signal_id": "sig-1",
        "cycle_id": "cycle-1",
        "action": "buy",
        "approved": False,
    }
    snapshot = collect_gate_path(
        cycle_id="cycle-1",
        candidates=[candidate],
        stage_rows={"duplicate_symbol": [dict(row), dict(row)]},
        final_plans=[type("Plan", (), {"recommendation": candidate})()],
        captured_at="2026-07-12T10:01:00+00:00",
    )["cand-1"]
    duplicate = snapshot["gate_path"][10]
    assert snapshot["decision"] == "unavailable"
    assert snapshot["identity_conflict"] is True
    assert duplicate["status"] == "unavailable"
    assert duplicate["identity_link_status"] == "conflict"


def test_duplicate_rejected_plans_are_conflict_and_do_not_use_first_match():
    candidate = _candidate()
    snapshot = collect_gate_path(
        cycle_id="cycle-1",
        candidates=[candidate],
        stage_rows={},
        rejected_order_plans=[
            {"stage": "cycle_order_limit", "candidate_id": "cand-1", "signal_id": "sig-1", "cycle_id": "cycle-1", "action": "buy", "reason": "daily_capacity"},
            {"stage": "cycle_order_limit", "candidate_id": "cand-1", "signal_id": "sig-1", "cycle_id": "cycle-1", "action": "buy", "reason": "daily_capacity_other"},
        ],
        final_plans=[type("Plan", (), {"recommendation": candidate})()],
        captured_at="2026-07-12T10:01:00+00:00",
    )["cand-1"]
    capacity = snapshot["gate_path"][14]
    assert snapshot["decision"] == "unavailable"
    assert snapshot["identity_conflict"] is True
    assert capacity["status"] == "unavailable"
    assert capacity["identity_link_status"] == "conflict"


def test_symbol_only_link_is_weak_and_not_verified():
    candidate = _candidate(candidate="")
    candidate = TradeRecommendation(symbol="AAA", action="buy", confidence=0.8, reason="test", entry_price=100, decision_lineage={"signal_id": "sig-1"})
    snap = collect_gate_path(cycle_id="cycle-1", candidates=[candidate], stage_rows=_rows(), captured_at="2026-07-12T10:01:00+00:00")["sig-1"]
    assert snap["identity_status"] == "weak"


def test_post_decision_payload_rejected_recursively():
    rows = _rows()
    rows["entry_quality"][0]["checks"] = {"nested": {"return_10d": 0.1}}
    with pytest.raises(ValueError, match="post_decision_field"):
        collect_gate_path(cycle_id="cycle-1", candidates=[_candidate()], stage_rows=rows, captured_at="2026-07-12T10:01:00+00:00")


def test_content_hash_excludes_captured_at():
    a = collect_gate_path(cycle_id="cycle-1", candidates=[_candidate()], stage_rows=_rows(), captured_at="2026-07-12T10:01:00+00:00")["cand-1"]
    b = collect_gate_path(cycle_id="cycle-1", candidates=[_candidate()], stage_rows=_rows(), captured_at="2026-07-12T11:01:00+00:00")["cand-1"]
    assert a["content_hash"] == b["content_hash"]


def test_market_context_cycle_mismatch_is_not_verified():
    candidate = _candidate()
    candidate = TradeRecommendation(
        symbol=candidate.symbol,
        action=candidate.action,
        confidence=candidate.confidence,
        reason=candidate.reason,
        entry_price=candidate.entry_price,
        decision_lineage={**candidate.decision_lineage, "cycle_id": "other-cycle"},
        decision_context_snapshot=candidate.decision_context_snapshot,
    )
    snap = collect_gate_path(cycle_id="cycle-1", candidates=[candidate], stage_rows=_rows(), captured_at="2026-07-12T10:01:00+00:00")["cand-1"]
    assert snap["identity_status"] == "unavailable"


def test_store_attachment_is_exact_and_idempotent(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="sig-1", source_run_id="run", source="test", symbol="AAA", signal_date="2026-07-12",
        decision="candidate", features={}, gate={}, outcome={}
    )
    snap = collect_gate_path(cycle_id="cycle-1", candidates=[_candidate()], stage_rows=_rows(), captured_at="2026-07-12T10:01:00+00:00")["cand-1"]
    assert store.attach_gate_evaluation_snapshot("sig-1", snap) == "attached"
    assert store.attach_gate_evaluation_snapshot("sig-1", snap) == "idempotent"
    loaded = store.signal_outcome_by_id("sig-1")
    assert loaded["features"]["gate_evaluation_snapshot"]["snapshot_id"] == snap["snapshot_id"]


def test_quality_without_data_is_collecting_with_null_denominators():
    report = build_gate_effectiveness_quality([])
    assert report["status"] == "collecting"
    assert report["snapshots"] == 0
    assert report["gates"]["evaluated"] == 0


def test_quality_excludes_authority_conflicts_from_learning_denominators():
    candidate = _candidate()
    snapshot = collect_gate_path(
        cycle_id="cycle-1",
        candidates=[candidate],
        stage_rows={
            "duplicate_symbol": [{
                "candidate_id": "cand-1", "signal_id": "sig-1", "cycle_id": "cycle-1",
                "action": "buy", "approved": False, "reason": "duplicate_symbol",
            }],
        },
        final_plans=[type("Plan", (), {"recommendation": candidate})()],
        captured_at="2026-07-12T10:01:00+00:00",
    )["cand-1"]
    report = build_gate_effectiveness_quality([snapshot])
    assert report["snapshots"] == 0
    assert report["conflicts"] == 1
    assert report["gates"]["candidates_reaching_gate"] == 0
    assert report["warnings"] == ["identity_conflicts_excluded"]
