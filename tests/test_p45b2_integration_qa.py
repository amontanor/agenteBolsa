from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from test_p45b2_batch_writes import _observation, _rows

import agente_bolsa.storage as storage_module
from agente_bolsa import scheduler
from agente_bolsa.config import Settings
from agente_bolsa.storage import LearningObservationBatchError, Store
from agente_bolsa.tools.postmarket_coordination import PostmarketCoordinator


def _store(tmp_path: Path, name: str) -> Store:
    store = Store(tmp_path / f"{name}.sqlite3", tmp_path / f"{name}-logs")
    store.ensure_schema()
    return store


def _pmr_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        DATA_DIR=tmp_path / "data",
        DATABASE_PATH=tmp_path / "data" / "state.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "data" / "logs",
        TRADING_MODE="paper",
        ALLOW_LIVE_TRADING=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )


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


def test_batch_failure_publishes_pmr_failed_and_releases_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _pmr_settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()

    class Status:
        now_market = "2026-07-15T23:00:00+00:00"

        def as_dict(self):
            return {"now_market": self.now_market}

    class Calendar:
        def __init__(self, *args, **kwargs):
            pass

        def should_run_daily_study(self):
            return True, Status()

    class Reporter:
        def emit(self, *args, **kwargs):
            return None

    class BrokerFactory:
        def __init__(self, *args, **kwargs):
            pass

        def alpaca_portfolio_snapshot(self):
            return None

    batch_error = LearningObservationBatchError(
        "synthetic batch failure",
        result={"status": "failed", "failed_chunk": 0, "written": 0},
        failed_chunk=0,
        cause="synthetic batch failure",
        retry_possible=True,
    )
    monkeypatch.setattr(scheduler, "MarketCalendar", Calendar)
    monkeypatch.setattr(scheduler, "_reporter", lambda *args, **kwargs: Reporter())
    monkeypatch.setattr(scheduler, "BrokerClientFactory", BrokerFactory)
    monkeypatch.setattr(
        scheduler,
        "reconcile_broker_orders",
        lambda *args, **kwargs: {"changes": [], "signal_execution_updates": 0, "learning_execution_updates": 0},
    )
    monkeypatch.setattr(
        scheduler,
        "build_post_market_review",
        lambda *args, **kwargs: {
            "path": "report.json",
            "summary": {"trades_evaluated": 0},
            "proposed_improvements": [],
            "next_session_guidance": [],
        },
    )
    monkeypatch.setattr(scheduler, "_persist_daily_performance", lambda *args, **kwargs: (_ for _ in ()).throw(batch_error))
    monkeypatch.setattr(scheduler, "_set_job_status", lambda *args, **kwargs: None)

    assert scheduler.post_market_review_job(settings, store, use_llm=False, verbose=False, force=True) is None
    with store.connect() as conn:
        payloads = [
            json.loads(row["payload_json"])
            for row in conn.execute("SELECT payload_json FROM agent_events WHERE event_type = 'postmarket_run'")
        ]
    assert any(item["stage"] == "terminal" and item["status"] == "failed" for item in payloads)
    assert store.get_runtime_value("post_market_coordination:active") is None
    retry = PostmarketCoordinator(settings, store).acquire(
        session_date="2026-07-15", run_id="pmr-retry-after-batch", trigger="scheduled"
    )
    assert retry.effective is True
    PostmarketCoordinator(settings, store).terminal(retry, "failed", reason="test_cleanup")
