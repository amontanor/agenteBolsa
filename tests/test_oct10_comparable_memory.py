from __future__ import annotations

from contextlib import contextmanager

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.comparable_controls import SCHEMA_VERSION, build_comparable_control_quality


def _control_set(*, status: str = "verified", treatment: str = "treatment", controls: tuple[str, ...] = ("control",)):
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "cycle_id": "cycle-1",
        "market_state_ref_hash": "market-hash",
        "treatment": {"signal_id": treatment, "signal_price": 100.0},
        "controls": [
            {"signal_id": signal_id, "gate_ledger": [{"gate_name": "capacity"}], "non_execution_reason": "capacity_limit"}
            for signal_id in controls
        ],
        "blocked_candidates": [{"candidate_id": "blocked"}],
        "eligible_controls_omitted": 2,
        "selection_source": "actual_final_plans",
    }


def _recommendations():
    return [
        {
            "recommendation_id": "new",
            "created_at": "2026-10-09T12:00:00+00:00",
            "payload": {"comparable_control_set": _control_set()},
        },
        {
            "recommendation_id": "partial",
            "created_at": "2026-10-08T12:00:00+00:00",
            "payload": {"comparable_control_set": _control_set(status="partially_comparable", controls=())},
        },
        {
            "recommendation_id": "legacy",
            "created_at": "2026-10-09T11:00:00+00:00",
            "payload": {},
        },
    ]


def _outcomes():
    # Existing readers process DESC rows and assign every duplicate, so the
    # final (oldest) duplicate remains authoritative.
    return [
        {"signal_id": "treatment", "outcome": {"matured_horizons": {"10d": True}}},
        {"signal_id": "control", "outcome": {"matured_horizons": {"10d": True}}},
        {"signal_id": "control", "outcome": {"matured_horizons": {"10d": False}}},
    ]


class _LegacyStore:
    def trade_recommendations(self, *, limit: int):
        assert limit == 50000
        return _recommendations()

    def signal_outcomes(self, *, limit: int, include_lab_book: bool, include_learning_experiment: bool):
        assert (limit, include_lab_book, include_learning_experiment) == (200000, True, True)
        return _outcomes()


class _StreamingStore(_LegacyStore):
    @contextmanager
    def comparable_control_quality_record_stream(self, *, batch_size: int):
        assert batch_size == 512

        def records():
            yield from (("recommendation", item) for item in _recommendations())
            yield from (("outcome", item) for item in _outcomes())

        stream = records()
        try:
            yield stream
        finally:
            stream.close()


def test_streaming_quality_matches_legacy_lists_and_preserves_last_wins():
    legacy = build_comparable_control_quality(_LegacyStore())
    streamed = build_comparable_control_quality(_StreamingStore())

    assert streamed == legacy
    assert streamed["outcome_maturity_by_arm"] == {"treatment": 2, "controls": 0, "total": 0}


def test_streaming_quality_preserves_window_and_status_filters():
    legacy = build_comparable_control_quality(
        _LegacyStore(), start="2026-10-09", end="2026-10-09", status="verified"
    )
    streamed = build_comparable_control_quality(
        _StreamingStore(), start="2026-10-09", end="2026-10-09", status="verified"
    )

    assert streamed == legacy
    assert streamed["treatments_total_new"] == 1
    assert streamed["legacy_without_control_set"] == 1


def test_streaming_quality_closes_store_stream_when_decoder_fails():
    closed = []

    class BrokenStore(_StreamingStore):
        @contextmanager
        def comparable_control_quality_record_stream(self, *, batch_size: int):
            def records():
                yield "unexpected", {}

            stream = records()
            try:
                yield stream
            finally:
                closed.append(True)
                stream.close()

    try:
        build_comparable_control_quality(BrokenStore())
    except ValueError as exc:
        assert str(exc) == "comparable_control_quality_record_kind_invalid:unexpected"
    else:
        raise AssertionError("invalid stream kind must fail")
    assert closed == [True]


def test_store_quality_stream_uses_readonly_fetchmany_and_closes(tmp_path, monkeypatch):
    settings = Settings(DATA_DIR=tmp_path, DATABASE_PATH=tmp_path / "state.sqlite3", AGENT_LOGS_DIR=tmp_path / "logs")
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.save_trade_recommendation(
        recommendation_id="rec-1",
        cycle_id="cycle-1",
        symbol="TREAT",
        action="buy",
        confidence=0.9,
        payload={"comparable_control_set": _control_set()},
    )
    store.save_signal_outcome(
        signal_id="treatment",
        source_run_id="run-1",
        source="paper",
        symbol="TREAT",
        signal_date="2026-10-09",
        decision="approved_buy",
        features={},
        outcome={"matured_horizons": {"10d": True}},
    )

    fetch_sizes: list[int] = []
    closed_cursors: list[bool] = []
    closed_connections: list[bool] = []
    original_open = store._decision_context_read_connection

    class TrackedCursor:
        def __init__(self, cursor):
            self._cursor = cursor

        def fetchmany(self, size):
            rows = self._cursor.fetchmany(size)
            fetch_sizes.append(size)
            return rows

        def close(self):
            closed_cursors.append(True)
            self._cursor.close()

    class TrackedConnection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, *args, **kwargs):
            return TrackedCursor(self._connection.execute(*args, **kwargs))

        def close(self):
            closed_connections.append(True)
            self._connection.close()

    monkeypatch.setattr(
        store,
        "_decision_context_read_connection",
        lambda: TrackedConnection(original_open()),
    )
    with store.comparable_control_quality_record_stream(batch_size=512) as records:
        streamed = list(records)

    assert [kind for kind, _item in streamed] == ["recommendation", "outcome"]
    assert fetch_sizes
    assert max(fetch_sizes) <= 512
    assert closed_cursors == [True, True]
    assert closed_connections == [True, True]
