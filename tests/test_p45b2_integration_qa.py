from __future__ import annotations

import threading
from pathlib import Path

import pytest
from test_p45b2_batch_writes import _observation, _rows

import agente_bolsa.storage as storage_module
from agente_bolsa.storage import LearningObservationBatchError, Store


def _store(tmp_path: Path, name: str) -> Store:
    store = Store(tmp_path / f"{name}.sqlite3", tmp_path / f"{name}-logs")
    store.ensure_schema()
    return store


def test_chunk_is_prepared_before_connection_and_begin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store(tmp_path, "tracked")
    prepared = threading.Event()
    release = threading.Event()
    connected = threading.Event()
    original_prepare = storage_module._prepare_learning_observation_parameters

    class TrackedStore(Store):
        def connect(self):  # type: ignore[override]
            connected.set()
            return super().connect()

    store = TrackedStore(store.database_path, tmp_path / "tracked-logs")
    store.ensure_schema()
    connected.clear()
    errors: list[BaseException] = []

    def wrapped_prepare(item, now):
        prepared.set()
        assert not connected.is_set()
        assert release.wait(5)
        return original_prepare(item, now)

    monkeypatch.setattr(storage_module, "_prepare_learning_observation_parameters", wrapped_prepare)

    thread = threading.Thread(
        target=lambda: store.upsert_learning_observations_batch([_observation(1)], chunk_size=1),
    )
    thread.start()
    assert prepared.wait(5)
    assert not connected.is_set()
    release.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert not errors
    assert connected.is_set()
    assert len(_rows(store)) == 1


def test_slow_generator_does_not_hold_writer_lock(tmp_path: Path) -> None:
    slow_store = _store(tmp_path, "slow")
    writer_store = Store(slow_store.database_path, tmp_path / "writer-logs")
    writer_store.ensure_schema()
    generator_started = threading.Event()
    release_generator = threading.Event()
    writer_done = threading.Event()
    errors: list[BaseException] = []

    def slow_generator():
        generator_started.set()
        assert release_generator.wait(5)
        yield _observation(1)

    def run_slow_batch() -> None:
        try:
            slow_store.upsert_learning_observations_batch(slow_generator(), chunk_size=1)
        except BaseException as exc:  # pragma: no cover - asserted below.
            errors.append(exc)

    def run_writer() -> None:
        try:
            writer_store.upsert_learning_observations_batch([_observation(2)], chunk_size=1)
        except BaseException as exc:  # pragma: no cover - asserted below.
            errors.append(exc)
        finally:
            writer_done.set()

    slow_thread = threading.Thread(target=run_slow_batch)
    slow_thread.start()
    assert generator_started.wait(5)
    writer_thread = threading.Thread(target=run_writer)
    writer_thread.start()
    assert writer_done.wait(5)
    release_generator.set()
    slow_thread.join(timeout=10)
    writer_thread.join(timeout=10)
    assert not slow_thread.is_alive()
    assert not writer_thread.is_alive()
    assert not errors
    assert {row["observation_id"] for row in _rows(slow_store)} == {"obs-000001", "obs-000002"}


def test_preparation_failure_opens_no_connection_or_transaction(tmp_path: Path) -> None:
    store = _store(tmp_path, "preparation")
    connect_calls = 0

    def forbidden_connect():
        nonlocal connect_calls
        connect_calls += 1
        raise AssertionError("no debe abrirse una conexión antes de preparar el chunk")

    store.connect = forbidden_connect  # type: ignore[method-assign]

    def failing_generator():
        raise RuntimeError("generator failure before BEGIN")
        yield  # pragma: no cover

    with pytest.raises(LearningObservationBatchError) as raised:
        store.upsert_learning_observations_batch(failing_generator(), chunk_size=1)
    assert connect_calls == 0
    assert raised.value.result["connections_opened"] == 0
    assert raised.value.result["chunks_completed"] == 0
    assert raised.value.result["failed_chunk"] == 0


def test_fifty_concurrent_repetitions_have_no_lock_error(tmp_path: Path) -> None:
    database_path = tmp_path / "shared.sqlite3"
    left = Store(database_path, tmp_path / "left-logs")
    left.ensure_schema()
    right = Store(database_path, tmp_path / "right-logs")
    errors: list[BaseException] = []
    for iteration in range(50):
        barrier = threading.Barrier(2)

        def writer(store: Store, offset: int, *, sync: threading.Barrier = barrier) -> None:
            try:
                sync.wait()
                store.upsert_learning_observations_batch(
                    (_observation(offset + index, symbol=f"QA{offset + index:06d}") for index in range(2)),
                    chunk_size=250,
                )
            except BaseException as exc:  # pragma: no cover - asserted below.
                errors.append(exc)

        threads = [
            threading.Thread(target=writer, args=(left, iteration * 4)),
            threading.Thread(target=writer, args=(right, iteration * 4 + 2)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert all(not thread.is_alive() for thread in threads)
    assert not errors, errors
    assert len(_rows(left)) == 200


def test_busy_timeout_exhaustion_is_structured_and_rolls_back_chunk(tmp_path: Path) -> None:
    store = _store(tmp_path, "holder")
    holder = store.connect()
    holder.execute("BEGIN IMMEDIATE")

    class ZeroTimeoutStore(Store):
        def connect(self):  # type: ignore[override]
            connection = super().connect()
            connection.execute("PRAGMA busy_timeout=0")
            return connection

    contender = ZeroTimeoutStore(store.database_path, tmp_path / "contender-logs")
    try:
        with pytest.raises(LearningObservationBatchError, match="chunk 0") as raised:
            contender.upsert_learning_observations_batch([_observation(1)], chunk_size=1)
        assert raised.value.result["status"] == "failed"
        assert "locked" in raised.value.cause.lower()
        assert raised.value.result["written"] == 0
        assert raised.value.result["chunks_completed"] == 0
    finally:
        holder.rollback()
        holder.close()
