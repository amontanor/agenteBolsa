from __future__ import annotations

import ast
import hashlib
import importlib
import subprocess
from contextlib import contextmanager
from pathlib import Path

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.comparable_controls import SCHEMA_VERSION, build_comparable_control_quality

BASE_COMMIT = "43325d7b8c6525fa3665537f5109d570f2f2f5a9"
BASE_FUNCTION_SHA256 = "50add4204610883ff2dffddf56988d69cc80e905eb7d5817638419c25b4ac92a"
BASE_AST_SHA256 = "dc01653387ae3d47b10cfe905027edebfa6463f4bd82e912f9f7dd4814157351"


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


def _frozen_base_quality():
    module = importlib.import_module("agente_bolsa.tools.comparable_controls")
    root = Path(__file__).resolve().parents[1]
    source = subprocess.check_output(
        ["git", "show", f"{BASE_COMMIT}:src/agente_bolsa/tools/comparable_controls.py"],
        cwd=root,
    ).decode("utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "build_comparable_control_quality"
    )
    segment = ast.get_source_segment(source, function)
    assert segment is not None
    assert hashlib.sha256(segment.encode("utf-8")).hexdigest() == BASE_FUNCTION_SHA256
    assert hashlib.sha256(
        ast.dump(function, annotate_fields=True, include_attributes=False).encode("utf-8")
    ).hexdigest() == BASE_AST_SHA256
    namespace = dict(module.__dict__)
    exec(compile(ast.Module(body=[function], type_ignores=[]), "<frozen-base>", "exec"), namespace)
    return namespace["build_comparable_control_quality"]


def test_streaming_quality_matches_legacy_lists_and_preserves_last_wins():
    legacy = build_comparable_control_quality(_LegacyStore())
    streamed = build_comparable_control_quality(_StreamingStore())

    assert streamed == legacy
    assert streamed["outcome_maturity_by_arm"] == {"treatment": 2, "controls": 0, "total": 0}


def test_streaming_quality_matches_exact_frozen_base_ast_fixture():
    frozen = _frozen_base_quality()
    assert build_comparable_control_quality(_StreamingStore()) == frozen(_LegacyStore())


def test_frozen_base_and_stream_preserve_invalid_final_duplicate_error():
    class InvalidFinalStore(_LegacyStore):
        def signal_outcomes(self, **_kwargs):
            return [
                {"signal_id": "treatment", "outcome": {"matured_horizons": {"10d": True}}},
                {"signal_id": "treatment", "outcome": ["invalid-final-row"]},
            ]

    frozen = _frozen_base_quality()
    for handler in (frozen, build_comparable_control_quality):
        try:
            handler(InvalidFinalStore())
        except AttributeError as exc:
            assert str(exc) == "'list' object has no attribute 'get'"
        else:
            raise AssertionError("invalid final duplicate must preserve base error")


def test_frozen_base_and_stream_ignore_invalid_early_duplicate_when_last_row_valid():
    class InvalidEarlyStore(_LegacyStore):
        def signal_outcomes(self, **_kwargs):
            return [
                {"signal_id": "treatment", "outcome": ["invalid-early-row"]},
                {"signal_id": "treatment", "outcome": {"matured_horizons": {"10d": True}}},
            ]

    frozen = _frozen_base_quality()
    assert build_comparable_control_quality(InvalidEarlyStore()) == frozen(InvalidEarlyStore())


def test_frozen_base_and_stream_preserve_control_shape_error_order():
    class InvalidControlStore(_LegacyStore):
        def trade_recommendations(self, *, limit: int):
            item = _control_set(controls=())
            item["controls"] = [[]]
            return [
                {
                    "recommendation_id": "invalid-control",
                    "created_at": "2026-10-09T12:00:00+00:00",
                    "payload": {"comparable_control_set": item},
                }
            ]

    frozen = _frozen_base_quality()
    errors = []
    for handler in (frozen, build_comparable_control_quality):
        try:
            handler(InvalidControlStore())
        except Exception as exc:  # Exact type/message are the characterization contract.
            errors.append((type(exc), str(exc)))
    assert errors[0] == errors[1] == (AttributeError, "'list' object has no attribute 'get'")


def test_frozen_base_and_stream_preserve_verified_scalar_controls_error():
    class ScalarControlsStore(_LegacyStore):
        def trade_recommendations(self, *, limit: int):
            item = _control_set(controls=())
            item["controls"] = 1
            return [
                {
                    "recommendation_id": "scalar-controls",
                    "created_at": "2026-10-09T12:00:00+00:00",
                    "payload": {"comparable_control_set": item},
                }
            ]

    frozen = _frozen_base_quality()
    errors = []
    for handler in (frozen, build_comparable_control_quality):
        try:
            handler(ScalarControlsStore())
        except Exception as exc:  # The base iterates verified controls before outcomes.
            errors.append((type(exc), str(exc)))
    assert errors[0] == errors[1] == (TypeError, "'int' object is not iterable")


def test_frozen_base_and_stream_preserve_metric_error_field_order():
    class InvalidMetricStore(_LegacyStore):
        def trade_recommendations(self, *, limit: int):
            item = _control_set(controls=())
            item["blocked_candidates"] = 1
            item["eligible_controls_omitted"] = "invalid-int"
            return [
                {
                    "recommendation_id": "invalid-metric",
                    "created_at": "2026-10-09T12:00:00+00:00",
                    "payload": {"comparable_control_set": item},
                }
            ]

    frozen = _frozen_base_quality()
    errors = []
    for handler in (frozen, build_comparable_control_quality):
        try:
            handler(InvalidMetricStore())
        except Exception as exc:  # Field order is part of the frozen error behavior.
            errors.append((type(exc), str(exc)))
    assert errors[0] == errors[1] == (TypeError, "object of type 'int' has no len()")


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
    settings = Settings(
        _env_file=None,
        DATA_DIR=tmp_path,
        DATABASE_PATH=tmp_path / "state.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "logs",
    )
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
