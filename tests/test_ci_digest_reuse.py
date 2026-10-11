from __future__ import annotations

import json
from datetime import datetime, timezone

import agente_bolsa.continuous_improvement.digest as digest_module
from agente_bolsa.continuous_improvement.digest import (
    build_lab_digest,
    ready_for_human_approval_requests,
)


class _SpyConnection:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, query, params):
        return self

    def __iter__(self):
        return iter(self._rows)

    def close(self):
        pass


class _SpyStore:
    def __init__(self, proposals, applied_changes, rows):
        self.proposals_data = proposals
        self.applied_changes_data = applied_changes
        self.rows = rows
        self.calls: list[tuple[str, int]] = []

    def continuous_improvement_proposals(self, *, limit=0):
        self.calls.append(("proposals", limit))
        return self.proposals_data

    def continuous_improvement_applied_changes(self, *, limit=0):
        self.calls.append(("applied_changes", limit))
        return self.applied_changes_data

    def read_connection(self):
        self.calls.append(("artifacts", 200))
        return _SpyConnection(self.rows)

    def close_read_connection(self):
        pass


def _approval_fixture():
    proposals = [
        {"proposal_id": "p-open", "status": "READY_TO_APPLY", "payload": {"title": "fixed title"}},
        {"proposal_id": "p-applied", "status": "READY_TO_APPLY", "payload": {"title": "already applied"}},
    ]
    applied_changes = [{"proposal_id": "p-applied", "status": "APPLIED"}]
    rows = [
        {
            "artifact_id": "a-open",
            "proposal_id": "p-open",
            "content_text": "diff --git a/x b/x",
            "payload_json": json.dumps(
                {"status": "READY_FOR_HUMAN_REVIEW", "tests_ok": True, "target_paths": ["x"]}
            ),
            "created_at": "2026-10-08T00:00:00+00:00",
            "updated_at": "2026-10-08T00:00:00+00:00",
        },
        {
            "artifact_id": "a-applied",
            "proposal_id": "p-applied",
            "content_text": "diff --git a/y b/y",
            "payload_json": json.dumps(
                {"status": "READY_FOR_HUMAN_REVIEW", "tests_ok": True, "target_paths": ["y"]}
            ),
            "created_at": "2026-10-08T00:00:00+00:00",
            "updated_at": "2026-10-08T00:00:00+00:00",
        },
    ]
    return proposals, applied_changes, rows


def test_ready_requests_reuses_preloaded_lists_and_preserves_full_payload():
    proposals, applied_changes, rows = _approval_fixture()

    legacy_store = _SpyStore(proposals, applied_changes, rows)
    legacy = ready_for_human_approval_requests(legacy_store, limit=200)
    assert legacy_store.calls == [("proposals", 50000), ("applied_changes", 50000), ("artifacts", 200)]

    reuse_store = _SpyStore(proposals, applied_changes, rows)
    reused = ready_for_human_approval_requests(
        reuse_store,
        limit=200,
        proposals=proposals,
        applied_changes=applied_changes,
    )

    assert reused == legacy == [
        {
            "artifact_id": "a-open",
            "proposal_id": "p-open",
            "targets": ["x"],
            "title": "fixed title",
            "updated_at": "2026-10-08T00:00:00+00:00",
        }
    ]
    assert reuse_store.calls == [("artifacts", 200)]


def test_empty_preloaded_lists_are_data_and_do_not_trigger_reload():
    store = _SpyStore([], [], [])

    assert ready_for_human_approval_requests(store, proposals=[], applied_changes=[]) == []
    assert store.calls == [("artifacts", 200)]


def test_build_lab_digest_passes_its_loaded_lists_to_approval_helper(monkeypatch, tmp_path):
    proposals = [
        {"proposal_id": "p-open", "status": "PENDING", "payload": {"title": "fixed title"}},
        {"proposal_id": "p-applied", "status": "PENDING", "payload": {"title": "already applied"}},
    ]
    applied_changes = [{"proposal_id": "p-applied", "status": "APPLIED"}]
    rows = _approval_fixture()[2]

    class Store:
        def __init__(self):
            self.calls: list[tuple[str, int]] = []

        def continuous_improvement_proposals(self, *, limit=0):
            self.calls.append(("proposals", limit))
            return proposals

        def continuous_improvement_experiments(self, *, limit=0):
            self.calls.append(("experiments", limit))
            return []

        def continuous_improvement_applied_changes(self, *, limit=0):
            self.calls.append(("applied_changes", limit))
            return applied_changes

        def continuous_improvement_decisions(self, *, limit=0):
            self.calls.append(("decisions", limit))
            return []

        def continuous_improvement_proposal_artifacts(self, *, limit=0):
            self.calls.append(("artifacts", limit))
            return []

        def get_runtime_value(self, key):
            return {}

        def performance_daily(self, *, limit=0):
            self.calls.append(("performance_daily", limit))
            return []

        def read_connection(self):
            self.calls.append(("artifacts", 200))
            return _SpyConnection(rows)

        def close_read_connection(self):
            pass

    captured = []
    monkeypatch.setattr(digest_module, "_enrich_safety_context", lambda *args, **kwargs: {})
    monkeypatch.setattr(digest_module, "_learning_mode_low_sample_snapshot", lambda *args, **kwargs: {})
    monkeypatch.setattr(digest_module, "build_llm_decision_quality", lambda *args, **kwargs: {})
    monkeypatch.setattr(digest_module, "build_agent_run_productivity", lambda *args, **kwargs: {})
    monkeypatch.setattr(digest_module, "load_agent_config", lambda: {})
    monkeypatch.setattr(digest_module, "build_agent_group_conclusions", lambda *args, **kwargs: {})
    monkeypatch.setattr(digest_module, "build_research_mode_usage", lambda *args, **kwargs: {})

    original_ready = ready_for_human_approval_requests
    mode = {"value": "legacy"}

    def capture_approval_requests(store, *args, **kwargs):
        captured.append(kwargs)
        if mode["value"] == "legacy":
            return original_ready(store, limit=kwargs["limit"], workspace=kwargs["workspace"])
        return original_ready(store, *args, **kwargs)

    monkeypatch.setattr(digest_module, "ready_for_human_approval_requests", capture_approval_requests)
    monkeypatch.setattr(digest_module, "build_research_agenda_snapshot", lambda *args, **kwargs: {})
    monkeypatch.setattr(digest_module, "_director_brief", lambda *args, **kwargs: {})
    monkeypatch.setattr(digest_module, "_load_gate_effectiveness_quality", lambda *args, **kwargs: {})
    monkeypatch.setattr(digest_module, "adaptive_governance_status", lambda *args, **kwargs: {})
    monkeypatch.setattr(digest_module, "benchmark_summary", lambda *args, **kwargs: {})
    monkeypatch.setattr(digest_module, "build_kpi_funnel", lambda *args, **kwargs: {})
    monkeypatch.setattr(digest_module, "build_proposal_quality_report", lambda *args, **kwargs: {})
    monkeypatch.setattr(digest_module, "build_evidence_factory_metrics", lambda *args, **kwargs: {})
    monkeypatch.setattr(digest_module, "build_origin_utility_metrics", lambda *args, **kwargs: {})
    monkeypatch.setattr(digest_module, "build_decision_context_quality", lambda *args, **kwargs: {})
    monkeypatch.setattr(digest_module, "build_comparable_control_quality", lambda *args, **kwargs: {})
    monkeypatch.setattr(digest_module, "latest_overlay_shadow_signal", lambda *args, **kwargs: {})
    monkeypatch.setattr(digest_module, "latest_core_sleeve_signal", lambda *args, **kwargs: {})
    monkeypatch.setattr(digest_module, "latest_codegen_nightly_run", lambda *args, **kwargs: {})
    monkeypatch.setattr(digest_module, "learning_penalty_shadow_digest", lambda *args, **kwargs: {})
    monkeypatch.setattr(digest_module, "canonical_operation_telemetry_digest", lambda *args, **kwargs: {})
    monkeypatch.setattr(digest_module, "capital_deployment_funnel_digest", lambda *args, **kwargs: {})

    legacy_store = Store()
    mode["value"] = "legacy"
    legacy_digest = build_lab_digest(legacy_store, data_dir=tmp_path, now=datetime(2026, 10, 8, tzinfo=timezone.utc))

    reuse_store = Store()
    mode["value"] = "reuse"
    reuse_digest = build_lab_digest(reuse_store, data_dir=tmp_path, now=datetime(2026, 10, 8, tzinfo=timezone.utc))

    assert reuse_digest == legacy_digest
    assert captured[0]["proposals"] is proposals
    assert captured[0]["applied_changes"] is applied_changes
    assert legacy_store.calls.count(("proposals", 50000)) == 2
    assert legacy_store.calls.count(("applied_changes", 50000)) == 2
    assert reuse_store.calls.count(("proposals", 50000)) == 1
    assert reuse_store.calls.count(("applied_changes", 50000)) == 1




def test_approval_stream_closes_cursor_and_reader_on_malformed_payload():
    import pytest

    events = []

    class Cursor:
        def __iter__(self):
            yield {"payload_json": "{broken"}

        def close(self):
            events.append("cursor_closed")

    class Connection:
        def execute(self, query, params):
            assert params == (200,)
            return Cursor()

    class Reader:
        def read_connection(self):
            return Connection()

        def close_read_connection(self):
            events.append("reader_closed")

    with pytest.raises(json.JSONDecodeError):
        ready_for_human_approval_requests(Reader(), proposals=[], applied_changes=[])
    assert events == ["cursor_closed", "reader_closed"]


def test_approval_stream_does_not_prefetch_rejected_content():
    events = []

    class Cursor:
        def __iter__(self):
            for i in range(200):
                events.append(i)
                yield {"payload_json": "{}", "content_text": "X" * 10000}

        def fetchall(self):
            raise AssertionError("unbounded_fetch_forbidden")

        def close(self):
            events.append("cursor_closed")

    class Reader:
        def read_connection(self):
            return self

        def execute(self, query, params):
            return Cursor()

        def close_read_connection(self):
            events.append("reader_closed")

    assert ready_for_human_approval_requests(Reader(), proposals=[], applied_changes=[]) == []
    assert events == list(range(200)) + ["cursor_closed", "reader_closed"]
