"""P-L163b: los outcomes no pueden tumbar el postmarket por un lock de SQLite.

Traza real 2026-10-29T21:20:48Z:
  post_market_review.py:855 update_signal_outcomes(...)
  -> signal_learning.py:1640 store.update_signal_outcomes_bulk(...)
  -> storage.py:4563 conn.executemany(...)
  -> sqlite3.OperationalError: database is locked
"""

from __future__ import annotations

import sqlite3

import pytest

from agente_bolsa.storage import Store
from agente_bolsa.tools import post_market_review


class _FakeConnection:
    def __init__(self, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.calls: list[int] = []

    def executemany(self, sql, rows):  # noqa: ANN001
        self.calls.append(len(rows))
        if len(self.calls) <= self.fail_times:
            raise sqlite3.OperationalError("database is locked")


class _FakeContext:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> _FakeConnection:
        return self.connection

    def __exit__(self, *_exc) -> bool:
        return False


@pytest.fixture()
def store(tmp_path) -> Store:
    return Store(tmp_path / "state.sqlite3", tmp_path / "logs")


def test_bulk_update_chunks_rows_in_short_transactions(store, monkeypatch):
    connection = _FakeConnection()
    monkeypatch.setattr(store, "connect", lambda: _FakeContext(connection))

    outcomes = {f"sig_{index}": {"return_1d": 0.1} for index in range(1201)}
    store.update_signal_outcomes_bulk(outcomes)

    assert connection.calls == [500, 500, 201]


def test_bulk_update_retries_locked_chunks(store, monkeypatch):
    connection = _FakeConnection(fail_times=2)
    monkeypatch.setattr(store, "connect", lambda: _FakeContext(connection))

    store.update_signal_outcomes_bulk({"sig_1": {"return_1d": 0.1}})

    assert connection.calls == [1, 1, 1]


def test_bulk_update_reraises_non_busy_errors_immediately(store, monkeypatch):
    class _BrokenConnection(_FakeConnection):
        def executemany(self, sql, rows):  # noqa: ANN001
            self.calls.append(len(rows))
            raise sqlite3.OperationalError("no such column: nope")

    connection = _BrokenConnection()
    monkeypatch.setattr(store, "connect", lambda: _FakeContext(connection))

    with pytest.raises(sqlite3.OperationalError, match="no such column"):
        store.update_signal_outcomes_bulk({"sig_1": {"return_1d": 0.1}})
    assert connection.calls == [1]


def test_learning_pipeline_degrades_when_outcome_update_is_locked(tmp_path, monkeypatch):
    stages: list[tuple[str, str]] = []

    def _recorder(stage, status, error=None):  # noqa: ANN001
        stages.append((stage, status))

    def _locked(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(post_market_review, "update_signal_outcomes", _locked)
    monkeypatch.setattr(
        post_market_review, "build_learning_status", lambda *_a, **_k: {"available": True}
    )
    monkeypatch.setattr(
        post_market_review,
        "build_learning_daily_run",
        lambda *_a, **_k: {"path": "report.json", "health": {}, "digest": {}, "policy_candidates": []},
    )

    signal_update, signal_learning, daily_learning = post_market_review._build_learning_pipeline(
        object(), object(), tmp_path, "run_p163b", "2026-10-29", stage_recorder=_recorder
    )

    assert signal_update["deferred"] is True
    assert signal_update["updated"] == 0
    assert signal_update["warnings"] == ["outcome_update_locked"]
    assert signal_update["error"] == "OperationalError"
    assert signal_learning == {"available": True}
    assert daily_learning["path"] == "report.json"
    assert ("outcome_update", "failed") in stages
    assert ("daily_learning", "started") in stages
    assert ("daily_learning", "completed") in stages
    assert ("outcome_update", "completed") not in stages


def test_learning_pipeline_still_raises_on_programming_errors(tmp_path, monkeypatch):
    def _broken(*_args, **_kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(post_market_review, "update_signal_outcomes", _broken)

    with pytest.raises(ValueError, match="boom"):
        post_market_review._build_learning_pipeline(
            object(), object(), tmp_path, "run", "2026-10-29"
        )
