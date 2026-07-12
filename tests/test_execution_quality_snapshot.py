from agente_bolsa.storage import Store
from agente_bolsa.tools.execution_quality import (
    append_stage,
    build_execution_quality_report,
    build_planned_snapshot,
    reconciled_snapshot,
    submitted_snapshot,
    validate_snapshot,
)


def _payload():
    return {
        "symbol": "AAA",
        "side": "buy",
        "entry_price": 100.0,
        "qty": 10.0,
        "recommendation": {
            "recommendation_id": "rec-1",
            "entry_price": 99.5,
            "decision_lineage": {
                "signal_id": "sig-1",
                "candidate_id": "cand-1",
                "lineage_id": "lineage-1",
                "cycle_id": "cycle-1",
            },
            "decision_context_snapshot": {"signal_link_status": "verified", "captured_at": "2026-07-13T14:00:00+00:00"},
        },
        "decision_lineage": {"signal_id": "sig-1", "candidate_id": "cand-1", "lineage_id": "lineage-1", "cycle_id": "cycle-1"},
    }


def _planned():
    return build_planned_snapshot(
        plan_id="plan-1", cycle_id="cycle-1", symbol="AAA", side="buy", payload=_payload(),
        planned_at="2026-07-13T14:00:01+00:00", signal_price=98.0, signal_at="2026-07-13T13:59:00+00:00",
    )


def test_full_chain_becomes_verified_and_calculates_buy_metrics():
    snapshot = submitted_snapshot(_planned(), broker_order={"id": "broker-1", "client_order_id": "client-1", "status": "pending_new", "qty": 10, "submitted_at": "2026-07-13T14:00:02+00:00"}, observed_at="2026-07-13T14:00:02+00:00")
    snapshot = reconciled_snapshot(snapshot, broker_snapshot={"id": "broker-1", "client_order_id": "client-1", "status": "filled", "qty": 10, "filled_qty": 10, "filled_avg_price": 101, "submitted_at": "2026-07-13T14:00:02+00:00", "filled_at": "2026-07-13T14:00:04+00:00"}, observed_at="2026-07-13T14:00:04+00:00", plan_status="SUBMITTED")
    assert snapshot["lineage_status"] == "verified"
    assert snapshot["status"] == "filled"
    assert round(snapshot["metrics"]["signal_to_plan_bps"], 4) == 204.0816
    assert round(snapshot["metrics"]["plan_to_fill_bps"], 4) == 100.0
    assert snapshot["metrics"]["submit_to_complete_seconds"] == 2.0
    assert "plan_broker_status_mismatch" in snapshot["data_quality_warnings"]
    assert validate_snapshot(snapshot) == (True, None)


def test_reconciliation_repetition_does_not_duplicate_history_or_revert_terminal():
    snapshot = submitted_snapshot(_planned(), broker_order={"id": "broker-1", "status": "pending_new"}, observed_at="2026-07-13T14:00:02+00:00")
    filled = {"id": "broker-1", "status": "filled", "qty": 10, "filled_qty": 10, "filled_avg_price": 101, "filled_at": "2026-07-13T14:00:04+00:00"}
    snapshot = reconciled_snapshot(snapshot, broker_snapshot=filled, observed_at="2026-07-13T14:00:04+00:00")
    repeated = reconciled_snapshot(snapshot, broker_snapshot=filled, observed_at="2026-07-13T14:05:00+00:00")
    assert repeated["status"] == "filled"
    assert len(repeated["stage_history"]) == len(snapshot["stage_history"])
    reverted = append_stage(repeated, stage="reconciled", status="submitted", observed_at="2026-07-13T14:06:00+00:00", source="test")
    assert reverted["status"] == "filled"


def test_partial_fill_and_inverted_timestamp_are_diagnostic_not_inferred():
    snapshot = submitted_snapshot(_planned(), broker_order={"id": "broker-1", "status": "pending_new", "qty": 10, "submitted_at": "2026-07-13T14:00:02+00:00"}, observed_at="2026-07-13T14:00:02+00:00")
    snapshot = reconciled_snapshot(snapshot, broker_snapshot={"id": "broker-1", "status": "partially_filled", "qty": 10, "filled_qty": 5, "filled_avg_price": 101, "submitted_at": "2026-07-13T14:00:02+00:00", "filled_at": "2026-07-13T14:00:01+00:00"}, observed_at="2026-07-13T14:00:03+00:00")
    assert snapshot["status"] == "partially_filled"
    assert snapshot["quantities"]["remaining"] == 5.0
    assert "timestamp_inverted:submitted_at_to_first_fill_at" in snapshot["data_quality_warnings"]


def test_store_uses_existing_submit_response_and_only_propagates_exact_signal(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(signal_id="sig-1", source_run_id="run", source="test", symbol="AAA", signal_date="2026-07-13", decision="candidate", features={"entry_price": 98.0}, gate={}, outcome={})
    store.save_order_plan(plan_id="plan-1", cycle_id="cycle-1", symbol="AAA", side="buy", notional=1000, approved=True, dry_run=True, payload=_payload())
    plan = store.order_plans(cycle_id="cycle-1")[0]
    assert plan["payload"]["execution_quality_snapshot"]["status"] == "planned"
    store.save_broker_order(broker_order_id="broker-1", plan_id="plan-1", cycle_id="cycle-1", symbol="AAA", side="buy", status="pending_new", payload={"plan": plan, "broker_order": {"id": "broker-1", "client_order_id": "client-1", "status": "pending_new", "qty": 10, "submitted_at": "2026-07-13T14:00:02+00:00"}})
    outcome = store.signal_outcome_by_id("sig-1")
    snapshot = outcome["features"]["execution_quality_snapshot"]
    assert snapshot["broker_order_id"] == "broker-1"
    assert snapshot["lineage_status"] == "verified"


def test_report_is_collecting_without_prospective_data_and_keeps_legacy_separate():
    report = build_execution_quality_report([], legacy_orders=40)
    assert report["status"] == "collecting"
    assert report["legacy"] == 40
    assert report["lineage_coverage"] is None


def test_prohibited_outcome_field_is_rejected():
    snapshot = _planned()
    snapshot["metrics"]["return_10d"] = 0.1
    assert validate_snapshot(snapshot) == (False, "prohibited")
