"""BR2 performance decomposition for the cycle-scoped selection ledger.

The measurement is deliberately isolated from the active route.  It uses the
same public builder and persistence functions as production, a temporary
SQLite database, and records the transaction boundary separately from the
work performed before ``BEGIN IMMEDIATE``.
"""

from __future__ import annotations

import json
import math
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import agente_bolsa.tools.canonical_selection_ledger as selection_ledger
from agente_bolsa.storage import Store
from agente_bolsa.tools.canonical_selection_ledger import (
    build_canonical_selection_ledger,
    persist_canonical_selection_ledger,
)
from test_p53b_selection_ledger_shadow import (
    _candidate as p53_candidate,
    _plan_record,
    _recommendation,
)

CAPTURED_AT = datetime(2026, 7, 22, tzinfo=timezone.utc)


def _percentiles(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    p50_index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.50) - 1))
    p95_index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.95) - 1))
    return {
        "p50": round(ordered[p50_index], 4),
        "p95": round(ordered[p95_index], 4),
        "max": round(ordered[-1], 4),
    }


class _MeasuredConnection:
    def __init__(self, connection: Any, metrics: dict[str, Any]) -> None:
        self._connection = connection
        self._metrics = metrics
        self._transaction_started: float | None = None

    def execute(self, sql: str, *parameters: Any) -> Any:
        if str(sql).strip().upper() == "BEGIN IMMEDIATE":
            started = time.perf_counter()
            result = self._connection.execute(sql, *parameters)
            self._metrics["begin_wait_ms"].append((time.perf_counter() - started) * 1000)
            self._transaction_started = time.perf_counter()
            return result
        return self._connection.execute(sql, *parameters)

    def commit(self) -> None:
        self._connection.commit()
        if self._transaction_started is not None:
            self._metrics["transaction_ms"].append(
                (time.perf_counter() - self._transaction_started) * 1000
            )
            self._transaction_started = None

    def rollback(self) -> None:
        self._connection.rollback()
        self._transaction_started = None

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> _MeasuredConnection:
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


class _MeasuredStore(Store):
    def __init__(self, database_path: Path, logs_path: Path) -> None:
        super().__init__(database_path, logs_path)
        self.measure = False
        self.metrics: dict[str, Any] = {
            "connections": 0,
            "begin_wait_ms": [],
            "transaction_ms": [],
        }

    def connect(self) -> Any:
        connection = super().connect()
        if not self.measure:
            return connection
        self.metrics["connections"] += 1
        return _MeasuredConnection(connection, self.metrics)


def _phase(count: int, cycle_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidates = [
        p53_candidate(index, cycle_id=cycle_id, selected=index < 20)
        for index in range(count)
    ]
    phase = {
        "all_candidates": candidates,
        "selected_candidates": candidates[:20],
    }
    recommendations = [_recommendation(candidates[index], index) for index in range(20)]
    recommendations[3]["source"] = "capacity_fill"
    recommendations[3]["decision_origin"] = "capacity_fill"
    plans = [_plan_record(candidates[index], index) for index in range(10)]
    return phase, recommendations + [{"_plans": plans}]


def test_br2_volume_decomposition_and_scaling_is_per_cycle(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    store = _MeasuredStore(tmp_path / "volume.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.measure = True

    phase_a_ms: list[float] = []
    finalization_ms: list[float] = []
    serialization_ms: list[float] = []
    build_ms: list[float] = []
    persist_ms: list[float] = []
    total_shadow_ms: list[float] = []
    event_sizes: list[float] = []
    wal_sizes: list[float] = []
    scale_records: dict[int, list[dict[str, float]]] = {250: [], 500: [], 1000: []}

    original_phase_a = selection_ledger._phase_a_rows
    original_attach = selection_ledger._attach_phase_b
    original_hash = selection_ledger.stable_content_hash

    def timed_phase_a(*args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        result = original_phase_a(*args, **kwargs)
        phase_a_ms.append((time.perf_counter() - started) * 1000)
        return result

    def timed_attach(*args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        result = original_attach(*args, **kwargs)
        finalization_ms.append((time.perf_counter() - started) * 1000)
        return result

    def timed_hash(payload: Any) -> str:
        if not isinstance(payload, dict) or payload.get("event_type") != "canonical_selection_ledger":
            return original_hash(payload)
        started = time.perf_counter()
        result = original_hash(payload)
        serialization_ms.append((time.perf_counter() - started) * 1000)
        return result

    monkeypatch.setattr(selection_ledger, "_phase_a_rows", timed_phase_a)
    monkeypatch.setattr(selection_ledger, "_attach_phase_b", timed_attach)
    monkeypatch.setattr(selection_ledger, "stable_content_hash", timed_hash)

    tracemalloc.start()
    for cycle_index in range(100):
        count = 500
        cycle_id = f"br2-volume-{count}-{cycle_index:03d}"
        phase, recommendation_bundle = _phase(count, cycle_id)
        plans = recommendation_bundle.pop()["_plans"]
        started = time.perf_counter()
        build_started = time.perf_counter()
        payload = build_canonical_selection_ledger(
            cycle_id,
            phase,
            recommendations=recommendation_bundle,
            plan_records=plans,
            ordered_records=[],
            captured_at=CAPTURED_AT,
        )
        build_ms.append((time.perf_counter() - build_started) * 1000)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        event_sizes.append(float(len(encoded.encode("utf-8"))))
        persist_started = time.perf_counter()
        assert persist_canonical_selection_ledger(store, payload)["status"] == "inserted"
        persist_ms.append((time.perf_counter() - persist_started) * 1000)
        total_shadow_ms.append((time.perf_counter() - started) * 1000)
        wal_path = Path(f"{store.database_path}-wal")
        wal_sizes.append(float(wal_path.stat().st_size if wal_path.exists() else 0))

    for count in (250, 500, 1000):
        for repetition in range(3):
            cycle_id = f"br2-scale-{count}-{repetition:02d}"
            phase, recommendation_bundle = _phase(count, cycle_id)
            plans = recommendation_bundle.pop()["_plans"]
            started = time.perf_counter()
            payload = build_canonical_selection_ledger(
                cycle_id,
                phase,
                recommendations=recommendation_bundle,
                plan_records=plans,
                ordered_records=[],
                captured_at=CAPTURED_AT,
            )
            build_duration = (time.perf_counter() - started) * 1000
            encoded_size = len(
                json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
            )
            persist_started = time.perf_counter()
            assert persist_canonical_selection_ledger(store, payload)["status"] == "inserted"
            persist_duration = (time.perf_counter() - persist_started) * 1000
            scale_records[count].append(
                {
                    "build_ms": round(build_duration, 4),
                    "event_bytes": float(encoded_size),
                    "persist_ms": round(persist_duration, 4),
                }
            )

    _current, memory_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    store.measure = False

    measured_cycles = 109
    assert len(phase_a_ms) == len(finalization_ms) == len(serialization_ms) == measured_cycles
    assert len(build_ms) == len(persist_ms) == len(total_shadow_ms) == len(event_sizes) == 100
    assert len(store.metrics["begin_wait_ms"]) == len(store.metrics["transaction_ms"]) == measured_cycles
    assert store.metrics["connections"] == measured_cycles

    with store.connect() as connection:
        event_count = connection.execute(
            "SELECT COUNT(*) AS count FROM agent_events WHERE event_type = ?",
            ("canonical_selection_ledger",),
        ).fetchone()["count"]
    wal_path = Path(f"{store.database_path}-wal")
    wal_final = wal_path.stat().st_size if wal_path.exists() else 0
    metrics = {
        "cycles": 100,
        "candidates_per_cycle": 500,
        "phase_a_ms": _percentiles(phase_a_ms[:100]),
        "finalization_ms": _percentiles(finalization_ms[:100]),
        "serialization_ms": _percentiles(serialization_ms[:100]),
        "build_total_ms": _percentiles(build_ms[:100]),
        "begin_wait_ms": _percentiles(store.metrics["begin_wait_ms"][:100]),
        "transaction_ms": _percentiles(store.metrics["transaction_ms"][:100]),
        "persist_total_ms": _percentiles(persist_ms[:100]),
        "total_shadow_ms": _percentiles(total_shadow_ms[:100]),
        "event_bytes": _percentiles(event_sizes),
        "wal_peak_bytes": max(wal_sizes, default=0),
        "wal_final_bytes": wal_final,
        "memory_peak_bytes": memory_peak,
        "connections": store.metrics["connections"],
        "transactions": len(store.metrics["transaction_ms"]),
        "event_count": event_count,
        "scaling": {
            str(count): {
                "build_ms": _percentiles([item["build_ms"] for item in values]),
                "build_ms_per_candidate": _percentiles(
                    [item["build_ms"] / count for item in values]
                ),
                "build_ms_per_candidate_squared": _percentiles(
                    [item["build_ms"] / (count * count) for item in values]
                ),
                "event_bytes": _percentiles([item["event_bytes"] for item in values]),
                "event_bytes_per_candidate": _percentiles(
                    [item["event_bytes"] / count for item in values]
                ),
            }
            for count, values in scale_records.items()
        },
    }
    print("P-L53BR2_VOLUME " + json.dumps(metrics, sort_keys=True))
    assert event_count == measured_cycles
