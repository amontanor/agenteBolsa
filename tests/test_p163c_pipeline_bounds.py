"""P-L163c: ventana acotada de outcomes y materializacion fail-open.

Traza real 2026-10-29T23:10:55Z (ya con 0.4.406):
  daily_learning.py:1871 -> _materialize_observations_spooled
  -> storage.upsert_learning_observations_batch -> BEGIN IMMEDIATE
  -> LearningObservationBatchError: database is locked
"""

from __future__ import annotations

import sqlite3

import pytest

from agente_bolsa.storage import LearningObservationBatchError, Store
from agente_bolsa.tools import post_market_review


def _batch_error(*, retry_possible: bool) -> LearningObservationBatchError:
    return LearningObservationBatchError(
        "fallo persistiendo learning_observations en chunk 0: database is locked",
        result={"status": "failed"},
        failed_chunk=0,
        cause="database is locked",
        retry_possible=retry_possible,
    )


def test_outcome_update_uses_bounded_window(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    def _update(_settings, _store, *, since_date, limit):  # noqa: ANN001
        captured["since_date"] = since_date
        captured["limit"] = limit
        return {"updated": 0}

    monkeypatch.setattr(post_market_review, "update_signal_outcomes", _update)
    monkeypatch.setattr(post_market_review, "build_learning_status", lambda *_a, **_k: {})
    monkeypatch.setattr(
        post_market_review,
        "build_learning_daily_run",
        lambda *_a, **_k: {"path": "x", "health": {}, "digest": {}, "policy_candidates": []},
    )

    post_market_review._build_learning_pipeline(
        object(), object(), tmp_path, "run", "2026-10-30"
    )

    assert captured["since_date"] == "2026-09-15"  # 45 dias antes
    assert captured["limit"] == 200000


def test_daily_learning_degrades_when_batch_is_locked(tmp_path, monkeypatch):
    stages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        post_market_review,
        "update_signal_outcomes",
        lambda *_a, **_k: {"updated": 0},
    )
    monkeypatch.setattr(post_market_review, "build_learning_status", lambda *_a, **_k: {})

    def _locked(*_args, **_kwargs):
        raise _batch_error(retry_possible=True)

    monkeypatch.setattr(post_market_review, "build_learning_daily_run", _locked)

    _update, _learning, daily = post_market_review._build_learning_pipeline(
        object(),
        object(),
        tmp_path,
        "run",
        "2026-10-30",
        stage_recorder=lambda stage, status, error=None: stages.append((stage, status)),
    )

    assert daily["deferred"] is True
    assert daily["warnings"] == ["daily_learning_deferred"]
    assert daily["error"] == "LearningObservationBatchError"
    assert ("daily_learning", "failed") in stages
    assert ("daily_learning", "completed") not in stages


def test_daily_learning_reraises_when_retry_is_not_possible(tmp_path, monkeypatch):
    monkeypatch.setattr(
        post_market_review,
        "update_signal_outcomes",
        lambda *_a, **_k: {"updated": 0},
    )
    monkeypatch.setattr(post_market_review, "build_learning_status", lambda *_a, **_k: {})

    def _broken(*_args, **_kwargs):
        raise _batch_error(retry_possible=False)

    monkeypatch.setattr(post_market_review, "build_learning_daily_run", _broken)

    with pytest.raises(LearningObservationBatchError):
        post_market_review._build_learning_pipeline(
            object(), object(), tmp_path, "run", "2026-10-30"
        )


class _LockedConnection:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.begins = 0

    def execute(self, sql, *_args):
        if sql.strip().upper() == "BEGIN IMMEDIATE":
            self.begins += 1
            if self.begins <= self.failures:
                raise sqlite3.OperationalError("database is locked")
            return self
        return self

    def cursor(self):
        return self

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None


def test_learning_observation_chunk_retries_locked_begin(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    connection = _LockedConnection(failures=2)
    monkeypatch.setattr(store, "connect", lambda: connection)
    monkeypatch.setattr(
        "agente_bolsa.storage._prepare_learning_observation_parameters",
        lambda item, now: ((), 0),
    )
    monkeypatch.setattr(
        "agente_bolsa.storage._execute_learning_observation_upsert",
        lambda cursor, parameters: None,
    )

    result = store.upsert_learning_observations_batch(
        [{"observation_id": "obs_1", "signal_date": "2026-10-29", "symbol": "AAPL"}],
        chunk_size=10,
    )

    assert connection.begins == 3
    assert result["written"] == 1
    assert result["status"] == "available"
