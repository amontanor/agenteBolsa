"""QA integrada de P-L53B-W sobre la cadena validada P-L52BR1.

Las pruebas son sanitizadas y usan únicamente SQLite temporal.  Verifican que
el ledger de selección convive con P-L49/P-L50/P-L51/P-L52 sin compartir IDs,
reconstruir etapas ni entrar en la ruta activa de trading.
"""

from __future__ import annotations

import copy
import inspect
import json
import math
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from test_p48b_canonical_operation_telemetry_characterization import _raw_fixture
from test_p49br1_adversarial import (
    DECISION as P49_DECISION,
)
from test_p49br1_adversarial import (
    _candidate as p49_candidate,
)
from test_p49br1_adversarial import (
    _observation as p49_observation,
)
from test_p51b_canonical_trade_attribution import _valid_fixture
from test_p51b_trade_attribution_shadow import _snapshot as p51_snapshot
from test_p53b_selection_ledger_shadow import (
    _build_large,
    _plan_record,
    _recommendation,
)
from test_p53b_selection_ledger_shadow import (
    _candidate as p53_candidate,
)

from agente_bolsa import cycle_runner, scheduler
from agente_bolsa.storage import Store
from agente_bolsa.tools.canonical_eod_account_snapshot import (
    COST_FIELDS,
    build_canonical_eod_account_snapshot,
    persist_canonical_eod_account_snapshot,
)
from agente_bolsa.tools.canonical_operation_telemetry import (
    build_canonical_operation_telemetry,
    persist_canonical_operation_telemetry,
    read_canonical_operation_telemetry,
)
from agente_bolsa.tools.canonical_selection_ledger import (
    _attach_phase_b,
    _phase_a_rows,
    build_canonical_selection_ledger,
    persist_canonical_selection_ledger,
    stable_content_hash,
)
from agente_bolsa.tools.canonical_trade_attribution import persist_canonical_trade_attribution
from agente_bolsa.tools.data_quality_decision_shadow import (
    capture_data_quality_phase_a,
    finalize_data_quality_phase_b,
    persist_data_quality_decision_shadow,
)

SESSION = "2026-07-21"
CAPTURED_AT = datetime(2026, 7, 22, 0, 0, tzinfo=timezone.utc)


def _store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "data" / "state" / "combined.sqlite3", tmp_path / "data" / "logs")
    store.ensure_schema()
    return store


def _p49_snapshot(cycle_id: str = "combined-p49") -> dict[str, Any]:
    observations = [
        p49_observation(f"SYM{i:03d}", quality="blocking" if i < 37 else "valid")
        for i in range(500)
    ]
    candidates = []
    for _i, observation in enumerate(observations[:20]):
        candidate = p49_candidate(observation["symbol"], observation)
        candidate["cycle_id"] = cycle_id
        candidates.append(candidate)
    phase = capture_data_quality_phase_a(
        cycle_id=cycle_id,
        market_snapshot={
            "symbols": {item["symbol"]: {} for item in observations},
            "observations": observations,
        },
        candidates=candidates,
        decision_at=P49_DECISION,
        captured_at=P49_DECISION,
        detail_limit=500,
    )
    return finalize_data_quality_phase_b(
        phase,
        recommendations=[
            {"signal_id": f"signal_{item['symbol']}", "cycle_id": cycle_id, "selected": i < 10}
            for i, item in enumerate(candidates[:10])
        ],
        plans=[
            {"signal_id": f"signal_{item['symbol']}", "cycle_id": cycle_id, "plan_id": f"plan-{i}"}
            for i, item in enumerate(candidates[:4])
        ],
        rejected_order_plans=[
            {"signal_id": f"signal_{item['symbol']}", "cycle_id": cycle_id, "reason": "gate_rejected"}
            for item in candidates[4:8]
        ],
        cycle_id=cycle_id,
    )


def _p52_snapshot() -> dict[str, Any]:
    window_start = "2026-07-21T13:30:00Z"
    window_end = "2026-07-21T20:00:00Z"
    return build_canonical_eod_account_snapshot(
        session_date=SESSION,
        account_id="paper",
        currency="USD",
        window_start_at=window_start,
        window_end_at=window_end,
        generated_at=window_end,
        as_of=window_end,
        captured_at=CAPTURED_AT,
        equity_start=1000.0,
        equity_end=1098.5,
        cash_start=900.0,
        cash_end=900.0,
        open_pl_start=0.0,
        open_pl_end=0.0,
        gross_realized_pl=100.0,
        costs={field: 0.0 for field in COST_FIELDS},
        external_flow_ledger=[],
        positions=[],
        contributions=[
            {
                "broker_order_id": "buy-1",
                "lot_identity": "lot-1",
                "amount": 98.5,
                "currency": "USD",
                "origin": "canonical_trade_attribution",
            }
        ],
        benchmark={
            "symbol": "SPY",
            "window_start_at": window_start,
            "window_end_at": window_end,
            "start_at": window_start,
            "end_at": window_end,
            "start_price": 500.0,
            "end_price": 505.0,
            "price_basis": "unadjusted_close",
            "quality": "exact",
            "as_of": window_end,
        },
        session_count=5,
        comparable_session_count=5,
        outcomes_matured=True,
    )


def test_combined_500_37_443_funnel_has_independent_events_and_exact_denominators(tmp_path: Path) -> None:
    store = _store(tmp_path)

    p49 = _p49_snapshot()
    assert p49["denominators"]["market_observations"] == 500
    assert p49["denominators"]["blocking_observations"] == 37
    assert persist_data_quality_decision_shadow(store, p49)["status"] == "inserted"

    p48 = build_canonical_operation_telemetry(
        None,
        SESSION,
        source_data=_raw_fixture(),
        captured_at=CAPTURED_AT,
    )
    assert persist_canonical_operation_telemetry(store, p48)["status"] == "inserted"

    p51 = p51_snapshot(_valid_fixture())
    assert p51["denominators"]["attributed_sell_count"] == 1
    assert persist_canonical_trade_attribution(store, p51)["status"] == "inserted"

    p52 = _p52_snapshot()
    assert persist_canonical_eod_account_snapshot(store, p52)["status"] == "inserted"

    p53 = _build_large()
    assert p53["denominators"] == {
        "raw_count": 443,
        "canonical_count": 443,
        "eligible_count": 443,
        "selected_count": 20,
        "recommended_count": 5,
        "planned_count": 3,
        "ordered_count": 2,
        "identity_unavailable": 0,
        "identity_ambiguous": 0,
        "shadow_inputs_unavailable": 0,
        "conflict_count": 0,
        "truncated_count": 0,
    }
    assert p53["outcomes"] is None
    assert all("return_3d" not in row and "fill_price" not in row for row in p53["candidate_rows"])
    assert persist_canonical_selection_ledger(store, p53)["status"] == "inserted"

    events = store.agent_events(limit=5000)
    event_ids = [item["event_id"] for item in events if item["event_type"] in {
        "data_quality_decision_shadow",
        "canonical_operation_telemetry",
        "canonical_trade_attribution",
        "canonical_eod_account_snapshot",
        "canonical_selection_ledger",
    }]
    assert len(event_ids) == len(set(event_ids)) == 5
    assert {item["event_type"] for item in events} >= {
        "data_quality_decision_shadow",
        "canonical_operation_telemetry",
        "canonical_trade_attribution",
        "canonical_eod_account_snapshot",
        "canonical_selection_ledger",
    }
    assert read_canonical_operation_telemetry(store, SESSION)["content_hash"] == p48["content_hash"]


def test_combined_conflict_isolated_and_concurrent_shadow_writers_do_not_lock(tmp_path: Path) -> None:
    store = _store(tmp_path)
    p49 = _p49_snapshot("concurrent-p49")
    p48 = build_canonical_operation_telemetry(None, SESSION, source_data=_raw_fixture(), captured_at=CAPTURED_AT)
    p53 = _build_large()
    db_path = store.database_path
    logs_path = tmp_path / "data" / "logs"

    def write(kind: str) -> str:
        local = Store(db_path, logs_path)
        if kind == "p49":
            return str(persist_data_quality_decision_shadow(local, p49)["status"])
        if kind == "p48":
            return str(persist_canonical_operation_telemetry(local, p48)["status"])
        return str(persist_canonical_selection_ledger(local, p53)["status"])

    with ThreadPoolExecutor(max_workers=3) as executor:
        statuses = list(executor.map(write, ("p49", "p48", "p53")))
    assert statuses == ["inserted", "inserted", "inserted"]

    changed = copy.deepcopy(p53)
    changed["candidate_rows"][0]["score"] = 999.0
    changed["content_hash"] = stable_content_hash(changed)
    assert persist_canonical_selection_ledger(store, changed)["status"] == "conflict"
    assert read_canonical_operation_telemetry(store, SESSION)["content_hash"] == p48["content_hash"]
    assert len(store.canonical_selection_ledger_conflicts("cycle-A")) == 1


def test_p53_stage_is_after_active_submission_and_outside_pmr_pipeline() -> None:
    market_source = inspect.getsource(scheduler.market_cycle_job)
    auto_source = inspect.getsource(cycle_runner._auto_paper_trade)
    pmr_source = inspect.getsource(scheduler.post_market_review_job)
    assert "selection_ledger_phase_a=ranked_context" in market_source
    assert auto_source.rfind("_persist_selection_ledger_shadow") > auto_source.rfind("submit_paper_order_plan")
    assert "canonical_selection_ledger" not in pmr_source
    assert "build_canonical_trade_attribution" in pmr_source
    assert "build_from_postmarket_inputs" in pmr_source


def _percentiles(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    p50_index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.50) - 1))
    p95_index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.95) - 1))
    return {
        "p50": round(ordered[p50_index], 4),
        "p95": round(ordered[p95_index], 4),
        "max": round(ordered[-1], 4),
    }


class _TimedConnection:
    def __init__(self, connection: Any, metrics: dict[str, list[float] | int]) -> None:
        self._connection = connection
        self._metrics = metrics
        self._begin_at: float | None = None

    def execute(self, sql: str, *parameters: Any) -> Any:
        if str(sql).strip().upper() == "BEGIN IMMEDIATE":
            self._begin_at = time.perf_counter()
        return self._connection.execute(sql, *parameters)

    def commit(self) -> None:
        self._connection.commit()
        if self._begin_at is not None:
            self._metrics["begin_immediate_ms"].append((time.perf_counter() - self._begin_at) * 1000)
            self._begin_at = None

    def rollback(self) -> None:
        self._connection.rollback()
        self._begin_at = None

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> _TimedConnection:
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


class _MeasuredStore(Store):
    def __init__(self, database_path: Path, logs_path: Path) -> None:
        super().__init__(database_path, logs_path)
        self.measure = False
        self.metrics: dict[str, list[float] | int] = {
            "connections": 0,
            "begin_immediate_ms": [],
        }

    def connect(self) -> Any:
        connection = super().connect()
        if not self.measure:
            return connection
        self.metrics["connections"] += 1
        return _TimedConnection(connection, self.metrics)


def test_volume_decomposition_100_cycles_x_500_candidates(tmp_path: Path) -> None:
    store = _MeasuredStore(tmp_path / "volume.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.measure = True
    capture_ms: list[float] = []
    finalization_ms: list[float] = []
    build_ms: list[float] = []
    serialization_ms: list[float] = []
    persist_ms: list[float] = []
    event_sizes: list[float] = []
    wal_sizes: list[float] = []
    tracemalloc.start()
    for cycle_index in range(100):
        cycle_id = f"combined-volume-{cycle_index:03d}"
        phase = {
            "all_candidates": [
                p53_candidate(index, cycle_id=cycle_id, selected=index < 20)
                for index in range(500)
            ],
            "selected_candidates": [
                p53_candidate(index, cycle_id=cycle_id, selected=True)
                for index in range(20)
            ],
        }
        recommendations = [_recommendation(phase["all_candidates"][index], index) for index in range(20)]
        plan_records = [_plan_record(phase["all_candidates"][index], index) for index in range(10)]
        warnings: list[str] = []
        capture_started = time.perf_counter()
        rows, conflicts, _selected = _phase_a_rows(
            phase,
            cycle_id=cycle_id,
            captured_at=CAPTURED_AT,
            warnings=warnings,
        )
        capture_ms.append((time.perf_counter() - capture_started) * 1000)
        assert rows is not None and conflicts == 0
        finalization_started = time.perf_counter()
        _attach_phase_b(
            rows,
            cycle_id=cycle_id,
            recommendations=recommendations,
            plans=None,
            plan_records=plan_records,
            rejected_order_plans=[],
            ordered_records=[],
            failed_records=[],
            gate_snapshots={},
            warnings=warnings,
        )
        finalization_ms.append((time.perf_counter() - finalization_started) * 1000)
        build_started = time.perf_counter()
        payload = build_canonical_selection_ledger(
            cycle_id,
            phase,
            recommendations=recommendations,
            plan_records=plan_records,
            ordered_records=[],
            captured_at=CAPTURED_AT,
        )
        build_ms.append((time.perf_counter() - build_started) * 1000)
        serialization_started = time.perf_counter()
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        serialization_ms.append((time.perf_counter() - serialization_started) * 1000)
        persist_started = time.perf_counter()
        assert persist_canonical_selection_ledger(store, payload)["status"] == "inserted"
        persist_ms.append((time.perf_counter() - persist_started) * 1000)
        event_sizes.append(float(len(encoded)))
        wal_path = Path(f"{store.database_path}-wal")
        wal_sizes.append(float(wal_path.stat().st_size if wal_path.exists() else 0))
    _current, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    begin_values = list(store.metrics["begin_immediate_ms"])
    assert len(capture_ms) == len(finalization_ms) == len(build_ms) == len(serialization_ms) == len(persist_ms) == 100
    assert len(begin_values) == 100
    assert store.metrics["connections"] == 100
    store.measure = False
    with store.connect() as connection:
        event_count = connection.execute(
            "SELECT COUNT(*) AS count FROM agent_events WHERE event_type = ?",
            ("canonical_selection_ledger",),
        ).fetchone()["count"]
    metrics = {
        "cycles": 100,
        "candidates_per_cycle": 500,
        "capture_phase_a_ms": _percentiles(capture_ms),
        "finalization_ms": _percentiles(finalization_ms),
        "build_total_ms": _percentiles(build_ms),
        "serialization_ms": _percentiles(serialization_ms),
        "begin_immediate_ms": _percentiles(begin_values),
        "persist_total_ms": _percentiles(persist_ms),
        "event_bytes": _percentiles(event_sizes),
        "wal_bytes": _percentiles(wal_sizes),
        "memory_peak_bytes": peak_bytes,
        "connections": store.metrics["connections"],
        "transactions": len(begin_values),
        "event_count": event_count,
    }
    print("P-L53BR1_VOLUME " + json.dumps(metrics, sort_keys=True))
    assert event_count == 100
