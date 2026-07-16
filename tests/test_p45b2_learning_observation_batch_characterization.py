from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import statistics
import sys
import threading
import time
from collections.abc import Iterable
from itertools import islice
from pathlib import Path
from typing import Any

import pytest

from agente_bolsa.storage import Store, _dumps
from agente_bolsa.tools import daily_learning
from agente_bolsa.tools.rr_cohort import sync_rr_cohort_observations

FIXED_NOW = "2026-07-16T00:00:00+00:00"


class _InstrumentedStore(Store):
    """Store wrapper used only to count current per-row transactions."""

    def __init__(self, database_path: Path, agent_logs_dir: Path) -> None:
        super().__init__(database_path, agent_logs_dir)
        self.metrics = {"connections": 0, "transactions": 0, "commits": 0, "rollbacks": 0}

    def reset_metrics(self) -> None:
        for key in self.metrics:
            self.metrics[key] = 0

    def connect(self) -> sqlite3.Connection:
        conn = super().connect()
        self.metrics["connections"] += 1

        def trace(statement: str) -> None:
            normalized = statement.strip().upper()
            if normalized == "BEGIN" or normalized.startswith("BEGIN "):
                self.metrics["transactions"] += 1
            elif normalized == "COMMIT":
                self.metrics["commits"] += 1
            elif normalized.startswith("ROLLBACK"):
                self.metrics["rollbacks"] += 1

        conn.set_trace_callback(trace)
        return conn


class _BatchFailure(RuntimeError):
    pass


def _observation(
    index: int,
    *,
    observation_id: str | None = None,
    signal_date: str | None = None,
    symbol: str | None = None,
    source_family: str = "deterministic",
    features: dict[str, Any] | None = None,
    created_at: str = FIXED_NOW,
) -> dict[str, Any]:
    return {
        "observation_id": observation_id or f"obs-{index:06d}",
        "signal_date": signal_date or f"2026-07-{(index % 20) + 1:02d}",
        "symbol": symbol or f"SYM{index:06d}",
        "source_family": source_family,
        "source_run_ids": [f"run-{index:06d}"],
        "first_seen_at": created_at,
        "last_seen_at": created_at,
        "best_signal_id": f"sig-{index:06d}",
        "best_score": index / 1000.0,
        "decision": "candidate",
        "explanation": "synthetic characterization row",
        "llm_considered": False,
        "approved_buy": False,
        "blocked_entry_quality": False,
        "blocked_backtest": False,
        "executed_buy": False,
        "duplicate_count": 0,
        "rank_path": [{"rank": index}],
        "features": features if features is not None else {"edge": index, "nested": {"index": index}},
        "gate": {"status": "pass"},
        "outcome": {"available": False},
        "execution": {"status": "not_executed"},
        "created_at": created_at,
    }


def _store(tmp_path: Path, name: str = "state") -> _InstrumentedStore:
    store = _InstrumentedStore(tmp_path / f"{name}.sqlite3", tmp_path / f"{name}-logs")
    store.ensure_schema()
    store.reset_metrics()
    return store


def _json_normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_normalize(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_json_normalize(item) for item in value]
    return value


def _rows(store: Store) -> list[dict[str, Any]]:
    with store.connect() as conn:
        result = conn.execute(
            """
            SELECT observation_id, signal_date, symbol, source_family, source_run_ids_json,
                   first_seen_at, last_seen_at, best_signal_id, best_score, decision,
                   explanation, llm_considered, approved_buy, blocked_entry_quality,
                   blocked_backtest, executed_buy, duplicate_count, rank_path_json,
                   features_json, gate_json, outcome_json, execution_json, created_at, updated_at
            FROM learning_observations ORDER BY observation_id
            """
        ).fetchall()
    rows: list[dict[str, Any]] = []
    for row in result:
        item = dict(row)
        for key in ("source_run_ids", "rank_path", "features", "gate", "outcome", "execution"):
            item[key] = json.loads(item.pop(f"{key}_json"))
        rows.append(item)
    return rows


def _row_hashes(store: Store) -> list[str]:
    return [
        hashlib.sha256(
            json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        for row in _rows(store)
    ]


def _upsert_sql(conn: sqlite3.Connection, item: dict[str, Any], now: str) -> None:
    """Reference SQL mirrors Store.upsert_learning_observation without new production code."""
    conn.execute(
        """
        INSERT INTO learning_observations (
            observation_id, signal_date, symbol, source_family, source_run_ids_json,
            first_seen_at, last_seen_at, best_signal_id, best_score, decision,
            explanation, llm_considered, approved_buy, blocked_entry_quality,
            blocked_backtest, executed_buy, duplicate_count, rank_path_json,
            features_json, gate_json, outcome_json, execution_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(observation_id) DO UPDATE SET
            signal_date=excluded.signal_date,
            symbol=excluded.symbol,
            source_family=excluded.source_family,
            source_run_ids_json=excluded.source_run_ids_json,
            first_seen_at=excluded.first_seen_at,
            last_seen_at=excluded.last_seen_at,
            best_signal_id=excluded.best_signal_id,
            best_score=excluded.best_score,
            decision=excluded.decision,
            explanation=excluded.explanation,
            llm_considered=excluded.llm_considered,
            approved_buy=excluded.approved_buy,
            blocked_entry_quality=excluded.blocked_entry_quality,
            blocked_backtest=excluded.blocked_backtest,
            executed_buy=excluded.executed_buy,
            duplicate_count=excluded.duplicate_count,
            rank_path_json=excluded.rank_path_json,
            features_json=excluded.features_json,
            gate_json=excluded.gate_json,
            outcome_json=excluded.outcome_json,
            execution_json=excluded.execution_json,
            updated_at=excluded.updated_at
        """,
        (
            item["observation_id"],
            item["signal_date"],
            str(item["symbol"]).upper(),
            item["source_family"],
            _dumps(item.get("source_run_ids", [])),
            item.get("first_seen_at"),
            item.get("last_seen_at"),
            item.get("best_signal_id"),
            item.get("best_score"),
            item.get("decision", "candidate"),
            item.get("explanation", ""),
            int(bool(item.get("llm_considered"))),
            int(bool(item.get("approved_buy"))),
            int(bool(item.get("blocked_entry_quality"))),
            int(bool(item.get("blocked_backtest"))),
            int(bool(item.get("executed_buy"))),
            int(item.get("duplicate_count") or 0),
            _dumps(item.get("rank_path", [])),
            _dumps(item.get("features", {})),
            _dumps(item.get("gate", {})),
            _dumps(item.get("outcome", {})),
            _dumps(item.get("execution", {})),
            item.get("created_at") or now,
            now,
        ),
    )


def _batch_reference(
    store: Store,
    items: Iterable[dict[str, Any]],
    *,
    chunk_size: int,
    fail_at: int | None = None,
    fail_stage: str = "before",
    now: str = FIXED_NOW,
) -> dict[str, Any]:
    """Test-only future contract: one short transaction per bounded chunk."""
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    iterator = iter(items)
    result = {
        "received": 0,
        "valid": 0,
        "written": 0,
        "failed": 0,
        "chunks_completed": 0,
        "chunks_failed": 0,
        "connections": 0,
        "transactions": 0,
        "commits": 0,
        "rollbacks": 0,
        "durations": [],
        "wal_bytes_max": 0,
        "peak_chunk_payload_bytes": 0,
        "errors": [],
    }
    absolute_index = 0
    while True:
        chunk = list(islice(iterator, chunk_size))
        if not chunk:
            break
        result["received"] += len(chunk)
        result["valid"] += len(chunk)
        result["connections"] += 1
        started = time.perf_counter()
        conn = sqlite3.connect(store.database_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            conn.execute("BEGIN IMMEDIATE")
            result["transactions"] += 1
            result["peak_chunk_payload_bytes"] = max(
                result["peak_chunk_payload_bytes"],
                sum(len(_dumps(item).encode("utf-8")) for item in chunk),
            )
            for item in chunk:
                if fail_at == absolute_index and fail_stage == "before":
                    raise _BatchFailure(f"synthetic failure before row {absolute_index}")
                _upsert_sql(conn, item, now)
                if fail_at == absolute_index and fail_stage == "after":
                    raise _BatchFailure(f"synthetic failure after row {absolute_index}")
                absolute_index += 1
            conn.commit()
            result["commits"] += 1
            result["written"] += len(chunk)
            result["chunks_completed"] += 1
            wal_path = Path(store.database_path).with_name(Path(store.database_path).name + "-wal")
            result["wal_bytes_max"] = max(result["wal_bytes_max"], wal_path.stat().st_size if wal_path.exists() else 0)
        except Exception as exc:  # noqa: BLE001 - error path is the contract under test.
            conn.rollback()
            result["rollbacks"] += 1
            result["chunks_failed"] += 1
            result["failed"] += len(chunk)
            result["errors"].append(str(exc))
            absolute_index += len(chunk)
        finally:
            result["durations"].append(time.perf_counter() - started)
            conn.close()
    return result


def _concurrent_two_writers(store: Store, left: list[dict[str, Any]], right: list[dict[str, Any]], *, chunk_size: int) -> dict[str, Any]:
    barrier = threading.Barrier(2)
    results: list[dict[str, Any]] = []
    errors: list[BaseException] = []

    def writer(items: list[dict[str, Any]]) -> None:
        try:
            conn = sqlite3.connect(store.database_path, timeout=5.0)
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA journal_mode=WAL")
            chunks = [items[index : index + chunk_size] for index in range(0, len(items), chunk_size)]
            barrier.wait()
            started = time.perf_counter()
            begin_started = time.perf_counter()
            commits = 0
            transactions = 0
            wait_seconds: list[float] = []
            for chunk in chunks:
                conn.execute("BEGIN IMMEDIATE")
                wait_seconds.append(time.perf_counter() - begin_started)
                transactions += 1
                for item in chunk:
                    _upsert_sql(conn, item, FIXED_NOW)
                conn.commit()
                commits += 1
                begin_started = time.perf_counter()
            wal_path = Path(store.database_path).with_name(Path(store.database_path).name + "-wal")
            results.append(
                {
                    "duration": time.perf_counter() - started,
                    "commits": commits,
                    "transactions": transactions,
                    "wait_seconds": wait_seconds,
                    "wal_bytes": wal_path.stat().st_size if wal_path.exists() else 0,
                }
            )
            conn.close()
        except BaseException as exc:  # pragma: no cover - asserted by caller.
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(left,)), threading.Thread(target=writer, args=(right,))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert all(not thread.is_alive() for thread in threads)
    assert not errors, errors
    return {
        "writers": len(results),
        "commits": sum(item["commits"] for item in results),
        "transactions": sum(item["transactions"] for item in results),
        "durations": [item["duration"] for item in results],
        "max_duration": max((item["duration"] for item in results), default=0.0),
        "p95_duration": statistics.quantiles([item["duration"] for item in results], n=20)[-1]
        if len(results) >= 2
        else 0.0,
        "wait_seconds": [wait for item in results for wait in item["wait_seconds"]],
        "max_wait_seconds": max(
            (wait for item in results for wait in item["wait_seconds"]),
            default=0.0,
        ),
        "wal_bytes": max((item["wal_bytes"] for item in results), default=0),
    }


@pytest.mark.parametrize("size", [1, 50, 250, 500, 1_000, 5_000, 33_336])
def test_current_sequential_baseline_records_one_connection_and_commit_per_row(tmp_path: Path, size: int) -> None:
    store = _store(tmp_path, f"sequential-{size}")
    rows = [_observation(index) for index in range(size)]
    started = time.perf_counter()
    for row in rows:
        store.upsert_learning_observation(row)
    duration = time.perf_counter() - started
    metrics = dict(store.metrics)
    persisted = _rows(store)
    assert len(persisted) == size
    assert metrics["connections"] == size
    assert metrics["transactions"] == size
    assert metrics["commits"] == size
    assert metrics["rollbacks"] == 0
    memory_approx = sum(sys.getsizeof(row) + len(_dumps(row).encode("utf-8")) for row in rows)
    print(
        {
            "mode": "sequential",
            "rows": size,
            "seconds": round(duration, 4),
            "memory_approx_bytes": memory_approx,
            **metrics,
        }
    )


@pytest.mark.parametrize("chunk_size", [50, 100, 250, 500, 1_000])
def test_chunk_sizes_are_atomic_and_have_bounded_transactions(tmp_path: Path, chunk_size: int) -> None:
    store = _store(tmp_path, f"chunk-{chunk_size}")
    rows = [_observation(index) for index in range(chunk_size * 2 + 3)]
    result = _batch_reference(store, (row for row in rows), chunk_size=chunk_size)
    assert result["received"] == len(rows)
    assert result["valid"] == len(rows)
    assert result["written"] == len(rows)
    assert result["failed"] == 0
    assert result["chunks_completed"] == 3
    assert result["chunks_failed"] == 0
    assert result["commits"] == result["transactions"] == result["chunks_completed"]
    assert len(_rows(store)) == len(rows)
    concurrent = _concurrent_two_writers(
        _store(tmp_path, f"concurrent-{chunk_size}"),
        [_observation(index, symbol=f"LEFT{index:04d}") for index in range(chunk_size)],
        [_observation(index + chunk_size, symbol=f"RIGHT{index:04d}") for index in range(chunk_size)],
        chunk_size=chunk_size,
    )
    assert concurrent["writers"] == 2
    assert concurrent["transactions"] == concurrent["commits"] == 2
    assert concurrent["max_duration"] >= 0
    print({"chunk_size": chunk_size, "batch": result, "concurrent": concurrent})


def test_batch_parity_matches_current_upsert_and_preserves_column_semantics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agente_bolsa.storage._utc_iso", lambda: FIXED_NOW)
    sequential = _store(tmp_path, "parity-sequential")
    batched = _store(tmp_path, "parity-batched")
    rows = [_observation(index) for index in range(80)]
    rows[4]["features"] = {"a": {"b": 1}, "stable": True}
    rows[4]["features"] = {**rows[4]["features"], "later": [1, 2, 3]}
    for row in rows:
        sequential.upsert_learning_observation(row)
    result = _batch_reference(batched, rows, chunk_size=25)
    assert result["written"] == len(rows)
    assert _rows(sequential) == _rows(batched)
    assert _row_hashes(sequential) == _row_hashes(batched)
    assert all(
        _json_normalize(left) == _json_normalize(right)
        for left, right in zip(_rows(sequential), _rows(batched), strict=True)
    )


def test_atomic_chunk_failure_keeps_previous_chunks_and_retry_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    rows = [_observation(index) for index in range(12)]
    failed = _batch_reference(store, rows, chunk_size=4, fail_at=8, fail_stage="after")
    assert failed["chunks_completed"] == 2
    assert failed["chunks_failed"] == 1
    assert failed["written"] == 8
    assert failed["failed"] == 4
    assert {row["observation_id"] for row in _rows(store)} == {row["observation_id"] for row in rows[:8]}
    retry = _batch_reference(store, rows, chunk_size=4)
    assert retry["written"] == len(rows)
    before = _rows(store)
    repeat = _batch_reference(store, rows, chunk_size=4)
    assert repeat["written"] == len(rows)
    assert _rows(store) == before


def test_duplicate_ids_and_natural_key_conflicts_match_current_semantics(tmp_path: Path) -> None:
    store = _store(tmp_path)
    original = _observation(1)
    changed = {**original, "features": {"changed": True}, "best_score": 9.9}
    store.upsert_learning_observation(original)
    store.upsert_learning_observation(changed)
    row = _rows(store)[0]
    assert row["best_score"] == 9.9
    assert row["features"] == {"changed": True}
    conflict = _observation(2, signal_date=original["signal_date"], symbol=original["symbol"])
    with pytest.raises(sqlite3.IntegrityError):
        store.upsert_learning_observation(conflict)
    assert len(_rows(store)) == 1


def test_repeated_same_content_is_not_a_noop_when_timestamp_changes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    item = _observation(1)
    first = _batch_reference(store, [item], chunk_size=1, now="2026-07-16T00:00:00+00:00")
    assert first["written"] == 1
    created = _rows(store)[0]["updated_at"]
    second = _batch_reference(store, [item], chunk_size=1, now="2026-07-16T00:00:01+00:00")
    assert second["written"] == 1
    assert _rows(store)[0]["updated_at"] != created


def test_daily_learning_and_rr_cohort_use_batch_for_both_write_phases(tmp_path: Path) -> None:
    store = _store(tmp_path)
    original_batch = store.upsert_learning_observations_batch
    batch_sizes: list[int] = []

    def counted_batch(items: Iterable[dict[str, Any]], *, chunk_size: int = 250) -> dict[str, Any]:
        materialized = list(items)
        batch_sizes.append(len(materialized))
        return original_batch(materialized, chunk_size=chunk_size)

    store.upsert_learning_observations_batch = counted_batch  # type: ignore[method-assign]
    rows = [{**_observation(1, signal_date="2026-07-13", symbol="AAPL"), "source": "deterministic"}]
    observations = daily_learning._materialize_observations(store, rows)
    rr_result = sync_rr_cohort_observations(store, observations)
    assert batch_sizes == [1, 1]
    assert rr_result["batch"]["phase"] == "rr_sync"


def test_json_null_nan_infinity_and_key_order_are_characterized_without_coercing_missing_to_zero(tmp_path: Path) -> None:
    store = _store(tmp_path)
    item = _observation(1, features={"z": 1, "a": 2, "nan": math.nan, "inf": math.inf, "missing": None})
    store.upsert_learning_observation(item)
    row = _rows(store)[0]
    assert row["features"]["missing"] is None
    assert math.isnan(row["features"]["nan"])
    assert math.isinf(row["features"]["inf"])
    with store.connect() as conn:
        raw = conn.execute("SELECT features_json FROM learning_observations").fetchone()[0]
    assert "NaN" in raw and "Infinity" in raw
    reordered = _observation(1, features={"missing": None, "inf": math.inf, "nan": math.nan, "a": 2, "z": 1})
    _batch_reference(store, [reordered], chunk_size=1)
    assert _rows(store)[0]["features"]["missing"] is None


def test_empty_and_generator_inputs_are_valid_batch_contract(tmp_path: Path) -> None:
    store = _store(tmp_path)
    empty = _batch_reference(store, [], chunk_size=50)
    assert empty["received"] == empty["valid"] == empty["written"] == empty["failed"] == 0
    generated = _batch_reference(store, (_observation(index) for index in range(7)), chunk_size=3)
    assert generated["received"] == generated["written"] == 7
    assert generated["chunks_completed"] == 3


def test_json_branch_update_is_last_writer_wins_and_not_a_merge(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _observation(1, features={"branch_a": {"value": 1}, "shared": {"first": True}})
    second = _observation(1, features={"branch_b": {"value": 2}, "shared": {"second": True}})
    store.upsert_learning_observation(first)
    _batch_reference(store, [second], chunk_size=1)
    features = _rows(store)[0]["features"]
    assert features == second["features"]
    assert "branch_a" not in features


def test_large_payload_and_legacy_row_use_existing_schema_only(tmp_path: Path) -> None:
    store = _store(tmp_path)
    large = _observation(1, features={"legacy": True, "blob": "x" * 100_000})
    result = _batch_reference(store, [large], chunk_size=1)
    assert result["written"] == 1
    with store.connect() as conn:
        table_names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
    assert "learning_observations" in table_names
    assert not any(name.startswith("learning_observation_batch") for name in table_names)
    assert _rows(store)[0]["features"]["legacy"] is True


def test_missing_required_field_is_not_silently_filled_by_current_upsert(tmp_path: Path) -> None:
    store = _store(tmp_path)
    invalid = _observation(1)
    invalid.pop("symbol")
    with pytest.raises(KeyError, match="symbol"):
        store.upsert_learning_observation(invalid)
    assert _rows(store) == []


def test_busy_timeout_exhaustion_is_explicit_and_does_not_corrupt_previous_rows(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert_learning_observation(_observation(1))
    holder = sqlite3.connect(store.database_path, timeout=5.0)
    holder.execute("BEGIN IMMEDIATE")
    contender = sqlite3.connect(store.database_path, timeout=0.0)
    contender.execute("PRAGMA busy_timeout=0")
    try:
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            contender.execute("BEGIN IMMEDIATE")
    finally:
        contender.close()
        holder.rollback()
        holder.close()
    assert len(_rows(store)) == 1
