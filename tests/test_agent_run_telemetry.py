from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agente_bolsa.agent_run import (
    SCHEMA_VERSION,
    AgentRunTracker,
    build_agent_run_productivity,
    safe_refs,
    sanitize_error,
)
from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.digest import build_lab_digest
from agente_bolsa.continuous_improvement.findings_to_proposals import persist_findings_to_proposals
from agente_bolsa.models import AgentEvent
from agente_bolsa.storage import Store


def make_store(tmp_path):
    settings = Settings(
        DATA_DIR=tmp_path,
        DATABASE_PATH=tmp_path / "state" / "test.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "logs" / "agents",
        ALLOW_LIVE_TRADING=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return settings, store


@pytest.mark.parametrize(
    ("method", "status"),
    [
        ("succeed", "succeeded"),
        ("fail", "failed"),
        ("timeout", "timeout"),
        ("skip", "skipped"),
        ("block", "blocked"),
    ],
)
def test_real_store_lifecycle_terminal_states(tmp_path, method, status):
    _, store = make_store(tmp_path)
    tracker = AgentRunTracker(
        store, role="test_role", task_name="task", cycle_id="cycle", execution_kind="deterministic"
    )
    if method == "succeed":
        tracker.succeed()
    else:
        getattr(tracker, method)(reason="reason")
    events = store.agent_events(event_type_prefix="agent_run_")
    assert [event["event_type"] for event in events] == ["agent_run_started", f"agent_run_{status}"]
    payload = events[-1]["payload"]
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["agent_run_id"] == tracker.agent_run_id
    assert payload["duration_seconds"] >= 0
    assert datetime.fromisoformat(payload["started_at"]).tzinfo == timezone.utc
    assert datetime.fromisoformat(payload["finished_at"]).tzinfo == timezone.utc


def test_context_manager_propagates_original_exception(tmp_path):
    _, store = make_store(tmp_path)
    with pytest.raises(RuntimeError, match="original"):
        with AgentRunTracker(store, role="role", task_name="task", execution_kind="deterministic"):
            raise RuntimeError("original")
    assert (
        store.agent_events(event_type_prefix="agent_run_")[-1]["event_type"] == "agent_run_failed"
    )


def test_manual_terminal_is_idempotent_and_conflict_is_audited(tmp_path):
    _, store = make_store(tmp_path)
    tracker = AgentRunTracker(store, role="role", task_name="task", execution_kind="deterministic")
    tracker.succeed()
    tracker.succeed()
    assert len(store.agent_events(event_type_prefix="agent_run_succeeded")) == 1
    with pytest.raises(ValueError, match="terminal_conflict"):
        tracker.fail(reason="contradiction")
    assert store.agent_events(event_type_prefix="agent_run_conflict")


def test_same_run_is_idempotent_after_tracker_recreation(tmp_path):
    _, store = make_store(tmp_path)
    first = AgentRunTracker(
        store,
        agent_run_id="agent_run_retry_safe",
        role="role",
        task_name="task",
        execution_kind="system",
    )
    first.succeed()
    repeated = AgentRunTracker(
        store,
        agent_run_id="agent_run_retry_safe",
        role="role",
        task_name="task",
        execution_kind="system",
    )
    repeated.succeed()
    events = [
        item
        for item in store.agent_events(event_type_prefix="agent_run_")
        if item["payload"]["agent_run_id"] == "agent_run_retry_safe"
    ]
    assert [item["event_type"] for item in events] == ["agent_run_started", "agent_run_succeeded"]


def test_telemetry_failure_does_not_change_main_result(tmp_path, monkeypatch):
    _, store = make_store(tmp_path)
    monkeypatch.setattr(
        store, "record_agent_event", lambda _event: (_ for _ in ()).throw(OSError("telemetry down"))
    )
    with AgentRunTracker(store, role="role", task_name="task", execution_kind="deterministic"):
        result = 42
    assert result == 42


def test_privacy_sanitizes_errors_and_references():
    assert "secret-value" not in sanitize_error("api_key=secret-value")
    assert "abc.def" not in sanitize_error("Bearer abc.def")
    assert safe_refs(
        ["task-1", "reports/a.json", "../secret", ".env", "Authorization: Bearer x"]
    ) == [
        "task-1",
        "reports/a.json",
    ]


def test_nullable_tokens_and_cost_are_persisted_without_estimation(tmp_path):
    _, store = make_store(tmp_path)
    tracker = AgentRunTracker(
        store, role="role", task_name="task", execution_kind="llm", model=None
    )
    tracker.succeed()
    payload = store.agent_events(event_type_prefix="agent_run_succeeded")[-1]["payload"]
    assert payload["input_tokens"] is None
    assert payload["output_tokens"] is None
    assert payload["estimated_cost"] is None


def test_fallback_requires_reason_and_keeps_parent_failed(tmp_path):
    _, store = make_store(tmp_path)
    with pytest.raises(ValueError, match="fallback_reason_required"):
        AgentRunTracker(store, role="role", task_name="fallback", execution_kind="fallback")
    parent = AgentRunTracker(store, role="role", task_name="primary", execution_kind="llm")
    parent.fail(reason="quota")
    child = AgentRunTracker(
        store,
        role="role",
        task_name="fallback",
        execution_kind="fallback",
        parent_run_id=parent.agent_run_id,
        fallback_reason="primary_failed",
    )
    child.succeed()
    runs = build_agent_run_productivity(store)["runs_by_role"]["role"]
    assert runs["states"] == {"failed": 1, "succeeded": 1}
    assert runs["fallbacks"] == 1


def test_findings_to_proposals_uses_real_run_as_origin(tmp_path):
    settings, store = make_store(tmp_path)
    result = persist_findings_to_proposals(settings=settings, store=store, limit=0, dry_run=False)
    run = store.agent_events(event_type_prefix="agent_run_succeeded")[-1]["payload"]
    assert run["role"] == "findings_to_proposals"
    assert run["finding_ids"]
    assert all(
        item["origin"]["origin_run_id"] == run["agent_run_id"] for item in result["findings"]
    )
    assert all(run["input_refs"] == [] for _ in [0])


def test_multiple_proposals_and_source_event_are_linked(tmp_path, monkeypatch):
    settings, store = make_store(tmp_path)
    monkeypatch.setattr(
        "agente_bolsa.continuous_improvement.findings_to_proposals._latest_not_code_change_count",
        lambda _data: 1,
    )
    result = persist_findings_to_proposals(settings=settings, store=store, limit=2, dry_run=False)
    terminal = store.agent_events(event_type_prefix="agent_run_succeeded")[-1]["payload"]
    assert terminal["proposal_ids"] == [item["proposal_id"] for item in result["created"]]
    for finding in result["findings"]:
        assert finding["origin"]["source_event_ids"]


def test_orphan_and_invalid_event_detection_is_read_only(tmp_path):
    _, store = make_store(tmp_path)
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "agent_run_id": "old-run",
        "role": "role",
        "status": "started",
        "started_at": old.isoformat(),
        "execution_kind": "system",
    }
    store.record_agent_event(
        AgentEvent(agent="role", event_type="agent_run_started", cycle_id="cycle", payload=payload)
    )
    before = len(store.agent_events(event_type_prefix="agent_run_"))
    report = build_agent_run_productivity(store)
    after = len(store.agent_events(event_type_prefix="agent_run_"))
    assert report["orphan_runs"] == 1
    assert before == after


def test_recent_open_run_is_not_orphan(tmp_path):
    _, store = make_store(tmp_path)
    AgentRunTracker(store, role="role", task_name="task", execution_kind="system")
    report = build_agent_run_productivity(store)
    assert report["open_runs"] == 1
    assert report["orphan_runs"] == 0


def test_terminal_without_started_is_invalid_and_query_is_read_only(tmp_path):
    _, store = make_store(tmp_path)
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "agent_run_id": "agent_run_missing_start",
        "role": "role",
        "status": "failed",
        "started_at": now,
        "finished_at": now,
        "duration_seconds": 0.1,
    }
    store.record_agent_event(
        AgentEvent(agent="role", event_type="agent_run_failed", payload=payload)
    )
    before = store.agent_events(event_type_prefix="agent_run_")
    report = build_agent_run_productivity(store)
    after = store.agent_events(event_type_prefix="agent_run_")
    assert report["invalid_runs"] == 1
    assert before == after


def test_digest_counts_runs_not_individual_events(tmp_path):
    _, store = make_store(tmp_path)
    first = AgentRunTracker(store, role="role", task_name="one", execution_kind="deterministic")
    first.add_outputs(output_refs=["out-1"], proposal_ids=["proposal-1"])
    first.succeed()
    second = AgentRunTracker(store, role="role", task_name="two", execution_kind="deterministic")
    second.skip(reason="market_closed")
    report = build_lab_digest(store, days=1, data_dir=tmp_path)["agent_run_productivity"]
    assert report["total_runs"] == 2
    assert report["terminal_runs"] == 2
    assert report["succeeded"] == 1
    assert report["skipped"] == 1
    assert report["failed"] == 0
    assert report["success_rate"] == 0.5
    assert report["attribution_link_coverage"] == 0.5
    assert report["runs_by_role"]["role"]["runs"] == 2


def test_empty_digest_rates_are_unavailable(tmp_path):
    _, store = make_store(tmp_path)
    report = build_agent_run_productivity(store)
    assert report["total_runs"] == 0
    assert report["success_rate"] is None
    assert report["failure_rate"] is None
    assert report["fallback_rate"] is None
