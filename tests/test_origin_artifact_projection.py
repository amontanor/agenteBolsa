from __future__ import annotations

import json
import sqlite3

import pytest

from agente_bolsa.continuous_improvement.digest import (
    _origin_utility_artifacts,
    build_origin_utility_metrics,
    ready_for_human_approval_requests,
)
from agente_bolsa.storage import Store


def _origin() -> dict[str, object]:
    return {
        "origin_role": "findings_to_proposals",
        "origin_run_id": "run-origin-memory",
        "origin_kind": "deterministic",
        "evidence_class": "observability",
        "producer": "tests.origin_projection",
        "producer_version": "test",
        "observed_at": "2026-10-10T00:00:00+00:00",
        "source_event_ids": ["event-origin-memory"],
    }


def _proposal(proposal_id: str = "proposal-1") -> dict[str, object]:
    contract = {
        "change_class": "observability",
        "hypothesis_id": "hyp-origin-memory",
        "evidence_refs": ["event-origin-memory"],
        "metric_name": "coverage",
        "baseline": 0.4,
        "target": 0.6,
        "evaluation_window": "30 sessions",
        "min_sample": 30,
        "target_paths": ["src/agente_bolsa/continuous_improvement/digest.py"],
        "rollback": "revert the isolated change",
        "origin": _origin(),
    }
    return {
        "proposal_id": proposal_id,
        "status": "READY_TO_APPLY",
        "payload": {
            "experiment_contract": contract,
            "target_paths": contract["target_paths"],
            "expected_impact": "coverage measured against the declared baseline",
        },
    }


class _FakeCursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.closed = False
        self.fetch_sizes: list[int] = []

    def fetchmany(self, size: int) -> list[dict[str, object]]:
        self.fetch_sizes.append(size)
        if not self.rows:
            return []
        rows, self.rows = self.rows[:size], self.rows[size:]
        return rows

    def close(self) -> None:
        self.closed = True


class _FakeConnection:
    def __init__(self, rows: list[dict[str, object]], *, execute_error: Exception | None = None) -> None:
        self.rows = rows
        self.cursor: _FakeCursor | None = None
        self.cursors: list[_FakeCursor] = []
        self.execute_error = execute_error
        self.closed = False
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, params: tuple[object, ...]) -> _FakeCursor:
        self.calls.append((query, params))
        if self.execute_error is not None:
            raise self.execute_error
        self.cursor = _FakeCursor(self.rows.copy())
        self.cursors.append(self.cursor)
        return self.cursor

    def close(self) -> None:
        self.closed = True


def _projection_store(connection: _FakeConnection) -> Store:
    store = Store.__new__(Store)
    store._decision_context_read_connection = lambda: connection  # type: ignore[method-assign]
    return store


def test_projection_keeps_order_limit_and_json_falsy_contract() -> None:
    rows = [
        {"proposal_id": "p-null", "payload_json": None},
        {"proposal_id": "p-empty", "payload_json": ""},
        {"proposal_id": "p-zero", "payload_json": 0},
        {"proposal_id": "p-false", "payload_json": False},
        {"proposal_id": "p-json-zero", "payload_json": "0"},
        {"proposal_id": "p-json-false", "payload_json": "false"},
        {"proposal_id": "p-json-null", "payload_json": "null"},
    ]
    connection = _FakeConnection(rows.copy())
    projected = list(_projection_store(connection).iter_continuous_improvement_proposal_artifact_summaries(limit=7, batch_size=2))

    assert projected == [
        {"proposal_id": "p-null", "payload": {}},
        {"proposal_id": "p-empty", "payload": {}},
        {"proposal_id": "p-zero", "payload": {}},
        {"proposal_id": "p-false", "payload": {}},
        {"proposal_id": "p-json-zero", "payload": 0},
        {"proposal_id": "p-json-false", "payload": False},
        {"proposal_id": "p-json-null", "payload": None},
    ]
    assert connection.calls
    query, params = connection.calls[0]
    assert "SELECT proposal_id, payload_json" in query
    assert "ORDER BY updated_at DESC" in query
    assert "LIMIT ?" in query
    assert params == (7,)
    assert connection.cursor is not None
    assert connection.cursor.fetch_sizes == [2, 2, 2, 2, 2]
    assert all(cursor.closed for cursor in connection.cursors)
    assert connection.closed is True


def test_projection_closes_cursor_and_connection_on_early_close() -> None:
    connection = _FakeConnection([{"proposal_id": "p", "payload_json": "{}"}])
    stream = _projection_store(connection).iter_continuous_improvement_proposal_artifact_summaries(batch_size=1)
    assert next(stream) == {"proposal_id": "p", "payload": {}}
    stream.close()
    assert all(cursor.closed for cursor in connection.cursors)
    assert connection.closed is True


def test_projection_preserves_sql_and_decode_errors_and_closes() -> None:
    failed_sql = _FakeConnection([], execute_error=sqlite3.OperationalError("synthetic SQL failure"))
    with pytest.raises(sqlite3.OperationalError, match="synthetic SQL failure"):
        list(_projection_store(failed_sql).iter_continuous_improvement_proposal_artifact_summaries())
    assert failed_sql.closed is True

    failed_decode = _FakeConnection([{"proposal_id": "p", "payload_json": "{bad-json"}])
    with pytest.raises(json.JSONDecodeError):
        list(_projection_store(failed_decode).iter_continuous_improvement_proposal_artifact_summaries())
    assert failed_decode.cursor is not None
    assert failed_decode.cursor.closed is True
    assert failed_decode.closed is True

    setup_failure = Store.__new__(Store)
    setup_failure._decision_context_read_connection = lambda: (_ for _ in ()).throw(  # type: ignore[method-assign]
        sqlite3.OperationalError("synthetic PRAGMA failure")
    )
    with pytest.raises(sqlite3.OperationalError, match="synthetic PRAGMA failure"):
        list(setup_failure.iter_continuous_improvement_proposal_artifact_summaries())


def test_preflight_decode_error_precedes_malformed_consumer_payload() -> None:
    connection = _FakeConnection(
        [
            {"proposal_id": "p-first", "payload_json": "[1]"},
            {"proposal_id": "p-later", "payload_json": "{bad-json"},
        ]
    )
    with pytest.raises(json.JSONDecodeError):
        _projection_store(connection).iter_continuous_improvement_proposal_artifact_summaries(batch_size=1)
    assert all(cursor.closed for cursor in connection.cursors)
    assert connection.closed is True


def test_consumer_error_closes_stream_after_successful_preflight() -> None:
    connection = _FakeConnection([{"proposal_id": "proposal-1", "payload_json": "[1]"}])
    artifacts = _projection_store(connection).iter_continuous_improvement_proposal_artifact_summaries(batch_size=1)
    with pytest.raises(AttributeError, match="get"):
        build_origin_utility_metrics([_proposal()], [], artifacts=artifacts)
    assert len(connection.cursors) == 2
    assert all(cursor.closed for cursor in connection.cursors)
    assert connection.closed is True


def test_artifact_preflight_runs_before_proposal_consumer_error() -> None:
    connection = _FakeConnection([{"proposal_id": "proposal-1", "payload_json": "{}"}])
    store = _projection_store(connection)
    artifacts = _origin_utility_artifacts(store)
    with pytest.raises(AttributeError, match="get"):
        build_origin_utility_metrics([{"proposal_id": "bad", "payload": "not-a-mapping"}], [], artifacts=artifacts)
    assert len(connection.calls) == 1
    assert all(cursor.closed for cursor in connection.cursors)
    assert connection.closed is True


def test_projection_matches_legacy_fields_and_legacy_reader_retains_content(tmp_path) -> None:
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    rows = [
        ("a-old", "p-old", "2026-10-10T00:00:01+00:00", "old content", {"status": "OLD"}),
        ("a-new", "p-new", "2026-10-10T00:00:02+00:00", "new content", {"status": "READY_FOR_HUMAN_REVIEW"}),
        ("a-tie", "p-tie", "2026-10-10T00:00:02+00:00", "tie content", {"status": "TIE"}),
    ]
    with store.connect() as conn:
        for artifact_id, proposal_id, updated_at, content_text, payload in rows:
            conn.execute(
                """
                INSERT INTO continuous_improvement_proposal_artifacts
                    (artifact_id, proposal_id, artifact_type, content_text, payload_json, created_at, updated_at)
                VALUES (?, ?, 'text', ?, ?, ?, ?)
                """,
                (artifact_id, proposal_id, content_text, json.dumps(payload), updated_at, updated_at),
            )

    legacy = store.continuous_improvement_proposal_artifacts(limit=3)
    projected = list(store.iter_continuous_improvement_proposal_artifact_summaries(limit=3, batch_size=1))
    assert [{"proposal_id": item["proposal_id"], "payload": item["payload"]} for item in legacy] == projected
    assert all(item["content_text"] for item in legacy)


def test_origin_consumer_accepts_stream_and_preserves_truthiness_literals() -> None:
    artifacts = (
        item
        for item in [
            {"proposal_id": "proposal-1", "payload": {"status": "READY_FOR_HUMAN_REVIEW", "tests_ok": True}},
            {"proposal_id": "proposal-1", "payload": {"status": "READY_FOR_HUMAN_REVIEW", "tests_ok": 1}},
            {"proposal_id": "proposal-1", "payload": {"status": True, "tests_ok": True}},
            {"proposal_id": None, "payload": {"status": "READY_FOR_HUMAN_REVIEW", "tests_ok": True}},
            {"proposal_id": "unmatched", "payload": {"status": "READY_FOR_HUMAN_REVIEW", "tests_ok": True}},
        ]
    )
    result = build_origin_utility_metrics([_proposal()], [], artifacts=artifacts)
    metrics = result["origins"]["findings_to_proposals"]
    assert metrics["codegen_attempted"] == 3
    assert metrics["codegen_succeeded"] == 1


def test_origin_artifact_selector_falls_back_for_legacy_fakes() -> None:
    class LegacyStore:
        def __init__(self) -> None:
            self.calls: list[int] = []

        def continuous_improvement_proposal_artifacts(self, *, limit: int):
            self.calls.append(limit)
            return [{"proposal_id": "legacy", "payload": {}}]

    class ModernStore(LegacyStore):
        def iter_continuous_improvement_proposal_artifact_summaries(self, *, limit: int):
            self.calls.append(limit)
            return iter([{"proposal_id": "stream", "payload": {}}])

    legacy = LegacyStore()
    modern = ModernStore()
    assert list(_origin_utility_artifacts(legacy)) == [{"proposal_id": "legacy", "payload": {}}]
    assert list(_origin_utility_artifacts(modern)) == [{"proposal_id": "stream", "payload": {}}]
    assert legacy.calls == [50000]
    assert modern.calls == [50000]


def test_human_approval_still_reads_full_content_text(tmp_path) -> None:
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    content = "diff --git a/src/demo.py b/src/demo.py\n--- a/src/demo.py\n+++ b/src/demo.py\n"
    with store.connect() as conn:
        conn.execute(
            """
            INSERT INTO continuous_improvement_proposal_artifacts
                (artifact_id, proposal_id, artifact_type, content_text, payload_json, created_at, updated_at)
            VALUES ('approval-artifact', 'approval-proposal', 'code_diff_preview', ?, ?,
                    '2026-10-10T00:00:00+00:00', '2026-10-10T00:00:00+00:00')
            """,
            (content, json.dumps({"status": "READY_FOR_HUMAN_REVIEW", "tests_ok": True})),
        )
    requests = ready_for_human_approval_requests(store, proposals=[], applied_changes=[])
    assert requests[0]["targets"] == ["src/demo.py"]
    assert requests[0]["artifact_id"] == "approval-artifact"
