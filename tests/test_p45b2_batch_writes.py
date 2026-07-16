from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest

from agente_bolsa.storage import LearningObservationBatchError, Store
from agente_bolsa.tools import daily_learning

FIXED_NOW = "2026-07-16T00:00:00+00:00"


def _store(tmp_path: Path, name: str = "state") -> Store:
    store = Store(tmp_path / f"{name}.sqlite3", tmp_path / f"{name}-logs")
    store.ensure_schema()
    return store


def _observation(
    index: int,
    *,
    observation_id: str | None = None,
    signal_date: str | None = None,
    symbol: str | None = None,
    features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "observation_id": observation_id or f"obs-{index:06d}",
        "signal_date": signal_date or "2026-07-16",
        "symbol": symbol or f"SYM{index:06d}",
        "source_family": "deterministic",
        "source_run_ids": [f"run-{index:06d}"],
        "first_seen_at": FIXED_NOW,
        "last_seen_at": FIXED_NOW,
        "best_signal_id": f"sig-{index:06d}",
        "best_score": index / 1000,
        "decision": "candidate",
        "explanation": "batch test",
        "llm_considered": False,
        "approved_buy": False,
        "blocked_entry_quality": False,
        "blocked_backtest": False,
        "executed_buy": False,
        "duplicate_count": 0,
        "rank_path": [{"rank": index}],
        "features": features if features is not None else {"index": index},
        "gate": {"status": "pass"},
        "outcome": {"available": False},
        "execution": {"status": "not_executed"},
        "created_at": FIXED_NOW,
    }


def _rows(store: Store) -> list[dict[str, Any]]:
    with store.connect() as conn:
        rows = conn.execute(
            """
            SELECT observation_id, signal_date, symbol, source_family, source_run_ids_json,
                   best_score, features_json, gate_json, outcome_json, execution_json, created_at, updated_at
            FROM learning_observations ORDER BY observation_id
            """
        ).fetchall()
    return [
        {
            **{key: row[key] for key in row.keys() if not key.endswith("_json")},
            **{key[:-5]: json.loads(row[f"{key}"] or "{}") for key in ("source_run_ids_json", "features_json", "gate_json", "outcome_json", "execution_json")},
        }
        for row in rows
    ]


def test_batch_accepts_generator_empty_and_exact_250(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.upsert_learning_observations_batch([], chunk_size=250)["written"] == 0
    result = store.upsert_learning_observations_batch(_observation(index) for index in range(250))
    assert result["received"] == result["valid"] == result["written"] == 250
    assert result["chunks_completed"] == 1
    assert result["commits"] == result["connections_opened"] == 1
    assert result["busy_timeout_ms"] == 30_000
    assert len(_rows(store)) == 250


def test_33336_rows_use_134_commits_and_no_global_transaction(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = store.upsert_learning_observations_batch(_observation(index) for index in range(33_336))
    assert result["received"] == result["written"] == 33_336
    assert result["chunks_completed"] == result["commits"] == result["connections_opened"] == 134
    assert result["chunk_size"] == 250
    assert result["failed_chunk"] is None
    assert result["max_chunk_duration_ms"] >= 0


def test_daily_materialization_uses_batch_and_reports_134_chunks(tmp_path: Path) -> None:
    store = _store(tmp_path)
    raw_rows = [_observation(index) for index in range(33_336)]
    observations, batch = daily_learning._materialize_observations(store, raw_rows, return_batch_result=True)
    assert len(observations) == 33_336
    assert batch["chunks_completed"] == batch["commits"] == 134
    assert batch["rows_received"] == batch["rows_written"] == 33_336


def test_batch_preserves_legacy_overwrite_nulls_nan_and_natural_key_conflict(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _observation(1, features={"first": True, "nan": float("nan"), "inf": float("inf")})
    first_result = store.upsert_learning_observations_batch([first], chunk_size=1)
    assert first_result["non_strict_json_values_detected"] == 2
    changed = {**first, "features": {"second": True}, "best_score": None}
    result = store.upsert_learning_observations_batch([changed], chunk_size=1)
    assert result["non_strict_json_values_detected"] == 0
    assert _rows(store)[0]["features"] == {"second": True}
    assert _rows(store)[0]["best_score"] is None
    conflict = _observation(2, signal_date=first["signal_date"], symbol=first["symbol"])
    with pytest.raises(LearningObservationBatchError) as raised:
        store.upsert_learning_observations_batch([conflict], chunk_size=1)
    assert isinstance(raised.value.__cause__, sqlite3.IntegrityError)
    assert raised.value.result["failed_chunk"] == 0
    assert _rows(store)[0]["features"] == {"second": True}


@pytest.mark.parametrize("position", [0, 1, 2])
def test_failed_chunk_rolls_back_and_keeps_previous_commits(tmp_path: Path, position: int) -> None:
    store = _store(tmp_path)
    first = _observation(1)
    duplicate_natural_key = _observation(2, signal_date=first["signal_date"], symbol=first["symbol"])
    valid_tail = _observation(3)
    rows = [first, duplicate_natural_key, valid_tail]
    if position == 0:
        store.upsert_learning_observation(first)
        rows = [duplicate_natural_key, valid_tail]
    elif position == 2:
        rows = [first, valid_tail, duplicate_natural_key]
    with pytest.raises(LearningObservationBatchError) as raised:
        store.upsert_learning_observations_batch(rows, chunk_size=3)
    assert raised.value.result["status"] == "failed"
    assert raised.value.result["written"] == 0
    assert len(_rows(store)) == (1 if position == 0 else 0)


def test_failure_after_previous_chunk_preserves_previous_and_retry_is_explicit(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first_chunk = [_observation(index) for index in range(250)]
    conflict = _observation(999, signal_date=first_chunk[250 - 1]["signal_date"], symbol=first_chunk[250 - 1]["symbol"])
    rows = first_chunk + [conflict]
    with pytest.raises(LearningObservationBatchError) as raised:
        store.upsert_learning_observations_batch(rows, chunk_size=250)
    assert raised.value.result["written"] == 250
    assert raised.value.result["failed_chunk"] == 1
    assert len(_rows(store)) == 250
    retry_rows = first_chunk + [_observation(1000)]
    retry = store.upsert_learning_observations_batch(retry_rows, chunk_size=250)
    assert retry["written"] == 251
    assert len(_rows(store)) == 251


def test_two_store_instances_25_concurrent_repetitions_without_lock_errors(tmp_path: Path) -> None:
    database_path = tmp_path / "shared.sqlite3"
    left_store = Store(database_path, tmp_path / "left-logs")
    right_store = Store(database_path, tmp_path / "right-logs")
    left_store.ensure_schema()
    errors: list[BaseException] = []
    for iteration in range(25):
        barrier = threading.Barrier(2)

        def writer(store: Store, offset: int, *, sync: threading.Barrier = barrier) -> None:
            try:
                sync.wait()
                store.upsert_learning_observations_batch(
                    (_observation(offset + index, symbol=f"W{offset + index:06d}") for index in range(4)),
                    chunk_size=250,
                )
            except BaseException as exc:  # pragma: no cover - asserted below.
                errors.append(exc)

        threads = [
            threading.Thread(target=writer, args=(left_store, iteration * 8)),
            threading.Thread(target=writer, args=(right_store, iteration * 8 + 4)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert all(not thread.is_alive() for thread in threads)
    assert not errors, errors
    assert len(_rows(left_store)) == 25 * 8


def test_connections_are_closed_after_success_and_failure(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert_learning_observations_batch([_observation(1)], chunk_size=1)
    invalid = _observation(2)
    invalid.pop("symbol")
    with pytest.raises(LearningObservationBatchError):
        store.upsert_learning_observations_batch([invalid], chunk_size=1)
    with sqlite3.connect(store.database_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM learning_observations").fetchone()[0] == 1
