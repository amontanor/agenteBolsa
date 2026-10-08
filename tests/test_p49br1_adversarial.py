"""Adversarial rehearsal checks for the P-L49B shadow integration.

These tests use only in-memory objects and temporary SQLite.  They deliberately
exercise provenance, failure-open behaviour and consumer isolation rather than
running a market cycle or any external provider.
"""

from __future__ import annotations

import copy
import inspect
import json
import multiprocessing
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path

from agente_bolsa.storage import Store
from agente_bolsa.tools import daily_learning
from agente_bolsa.tools.data_quality_decision_shadow import (
    capture_data_quality_phase_a,
    finalize_data_quality_phase_b,
    market_data_observation_id,
    persist_data_quality_decision_shadow,
)

DECISION = datetime(2026, 7, 20, 14, 0, tzinfo=timezone.utc)


def _observation(symbol: str, *, quality: str = "valid", timestamp: str = "2026-07-20T13:55:00+00:00") -> dict:
    row = {
        "provider": "fixture",
        "symbol": symbol,
        "interval": "1d",
        "bar_timestamp": timestamp,
        "price_basis": "unadjusted",
        "data_as_of": "2026-07-20T13:59:00+00:00",
        "quality_status": quality,
        "invalid_fields": ["high"] if quality == "blocking" else [],
        "invalidity_class": "ohlc_invalid" if quality == "blocking" else None,
        "blocking_reason": "invalid_ohlc" if quality == "blocking" else None,
        "ohlcv": {"open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000},
    }
    row["market_data_observation_id"] = market_data_observation_id(row)
    return row


def _candidate(symbol: str, row: dict, *, side: str = "buy", **extra: object) -> dict:
    return {
        "symbol": symbol,
        "side": side,
        "signal_capture_id": f"capture_{symbol}",
        "signal_id": f"signal_{symbol}",
        "candidate_id": f"candidate_{symbol}",
        "cycle_id": "qa_cycle",
        "market_data_observation_id": row.get("market_data_observation_id"),
        **extra,
    }


def _persist_worker(args: tuple[str, dict]) -> str:
    db_path, snapshot = args
    store = Store(Path(db_path), Path(db_path).with_suffix(".logs"))
    try:
        store.ensure_schema()
        return str(persist_data_quality_decision_shadow(store, snapshot).get("status"))
    finally:
        store.close_read_connection()


def test_observation_identity_normalizes_equivalent_timezones_and_negative_zero() -> None:
    base = _observation("EIX")
    base["ohlcv"]["open"] = 0.0
    equivalent = {**base, "bar_timestamp": "2026-07-20T15:55:00+02:00"}
    equivalent["ohlcv"] = {**base["ohlcv"], "open": -0.0}
    equivalent["market_data_observation_id"] = None
    assert market_data_observation_id(base) == market_data_observation_id(equivalent)


def test_identity_gap_is_temporal_not_retroactively_blocking() -> None:
    candidate = _candidate("EIX", {"market_data_observation_id": None})
    phase = capture_data_quality_phase_a(
        cycle_id="qa_cycle",
        market_snapshot={"observations": []},
        candidates=[candidate],
        decision_at=DECISION,
        captured_at=DECISION,
    )
    assert phase["details"][0]["shadow_reason"] == "unavailable_temporal"
    assert phase["status"] == "partial"
    late = _observation("EIX", quality="blocking", timestamp="2026-07-20T14:01:00+00:00")
    later = capture_data_quality_phase_a(
        cycle_id="qa_cycle",
        market_snapshot={"observations": [late]},
        candidates=[_candidate("EIX", late)],
        decision_at=DECISION,
        captured_at=DECISION,
    )
    assert later["details"][0]["shadow_reason"] == "unavailable_temporal"


def test_phase_a_and_b_preserve_active_objects_and_exact_lineage() -> None:
    bad = _observation("MPC", quality="blocking")
    good = _observation("WELL")
    candidates = [_candidate("MPC", bad, legacy_selected=True), _candidate("WELL", good)]
    before = copy.deepcopy(candidates)
    phase = capture_data_quality_phase_a(
        cycle_id="qa_cycle",
        market_snapshot={"symbols": {"MPC": {}, "WELL": {}}, "observations": [bad, good]},
        candidates=candidates,
        decision_at=DECISION,
        captured_at=DECISION,
    )
    finalized = finalize_data_quality_phase_b(
        phase,
        recommendations=[{"signal_id": "signal_MPC", "cycle_id": "qa_cycle", "selected": True, "rank": 1}],
        plans=[{"signal_id": "signal_MPC", "cycle_id": "qa_cycle", "plan_id": "plan_mpc"}],
        rejected_order_plans=[{"symbol": "MPC", "cycle_id": "qa_cycle", "signal_id": "signal_MPC", "reason": "control"}],
        cycle_id="qa_cycle",
    )
    assert candidates == before
    assert finalized["denominators"]["recommended_affected"] == 1
    assert finalized["denominators"]["planned_affected"] == 1
    assert finalized["details"][0]["shadow_reason"] == "blocked_exact_quality"
    # A same-symbol row without canonical identity cannot contaminate Phase B.
    unrelated = finalize_data_quality_phase_b(
        phase, recommendations=[{"symbol": "MPC", "cycle_id": "qa_cycle"}], cycle_id="qa_cycle"
    )
    assert unrelated["denominators"]["recommended_affected"] == 0


def test_partial_quality_is_local_and_protective_sells_are_exempt() -> None:
    bad = _observation("EIX", quality="blocking")
    good = _observation("WELL")
    sells = [_candidate(symbol, bad, side="sell") for symbol in ("DDOG", "BNY", "JPM", "BAC")]
    phase = capture_data_quality_phase_a(
        cycle_id="qa_cycle",
        market_snapshot={"observations": [bad, good]},
        candidates=[_candidate("EIX", bad), _candidate("WELL", good), *sells],
        decision_at=DECISION,
        captured_at=DECISION,
    )
    reasons = [item["shadow_reason"] for item in phase["details"]]
    assert reasons[:2] == ["blocked_exact_quality", "eligible"]
    assert reasons[-4:] == ["not_applicable_exit"] * 4
    assert phase["denominators"]["protective_exits_exempt"] == 4


def test_volume_details_are_bounded_and_planned_rows_are_forced(tmp_path: Path) -> None:
    observations = [_observation(f"SYM{i:03d}", quality="blocking" if i < 37 else "valid") for i in range(500)]
    candidates = [_candidate(row["symbol"], row, legacy_selected=i < 20) for i, row in enumerate(observations[:20])]
    for row in candidates:
        row["cycle_id"] = "volume_cycle"
    tracemalloc.start()
    started = time.perf_counter()
    phase = capture_data_quality_phase_a(
        cycle_id="volume_cycle",
        market_snapshot={"symbols": {row["symbol"]: {} for row in observations}, "observations": observations},
        candidates=candidates,
        decision_at=DECISION,
        captured_at=DECISION,
        detail_limit=500,
    )
    built_ms = (time.perf_counter() - started) * 1000
    final = finalize_data_quality_phase_b(
        phase,
        recommendations=[{"signal_id": f"signal_SYM{i:03d}", "cycle_id": "volume_cycle", "selected": i < 10} for i in range(10)],
        plans=[{"signal_id": f"signal_SYM{i:03d}", "cycle_id": "volume_cycle", "plan_id": f"plan_{i}"} for i in range(4)],
        rejected_order_plans=[{"signal_id": f"signal_SYM{i:03d}", "cycle_id": "volume_cycle", "reason": "control"} for i in range(4)],
        cycle_id="volume_cycle",
    )
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    payload_bytes = len(json.dumps(final, sort_keys=True, separators=(",", ":")))
    volume_store = Store(tmp_path / "volume.sqlite", tmp_path / "volume.logs")
    volume_store.ensure_schema()
    persist_started = time.perf_counter()
    persist_result = persist_data_quality_decision_shadow(volume_store, final)
    persist_ms = (time.perf_counter() - persist_started) * 1000
    wal_path = tmp_path / "volume.sqlite-wal"
    wal_bytes = wal_path.stat().st_size if wal_path.exists() else 0
    volume_store.close_read_connection()
    assert phase["denominators"]["market_observations"] == 500
    assert phase["denominators"]["blocking_observations"] == 37
    assert phase["denominators"]["candidates_evaluated"] == 20
    assert final["denominators"]["recommended_affected"] == 10
    assert final["denominators"]["planned_affected"] == 4
    assert final["details_omitted"] == 0
    assert persist_result["status"] == "inserted"
    print(
        "P-L49BR1 volume: "
        f"build_phase_a_ms={built_ms:.2f} persist_ms={persist_ms:.2f} "
        f"peak_bytes={peak} event_bytes={payload_bytes} wal_bytes={wal_bytes} "
        "transactions=1 commits=1"
    )


def test_persistence_is_append_only_and_two_processes_are_idempotent(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.sqlite", tmp_path / "logs")
    store.ensure_schema()
    row = _observation("EIX", quality="blocking")
    snapshot = capture_data_quality_phase_a(
        cycle_id="process_cycle", market_snapshot={"observations": [row]}, candidates=[_candidate("EIX", row)], decision_at=DECISION, captured_at=DECISION
    )
    final = finalize_data_quality_phase_b(snapshot, cycle_id="process_cycle")
    store.close_read_connection()
    context = multiprocessing.get_context("spawn")
    with context.Pool(2) as pool:
        # A dead worker must fail the check instead of respawning forever.
        # Pool.__exit__ terminates remaining children when get raises TimeoutError.
        results = pool.map_async(_persist_worker, [(str(tmp_path / "state.sqlite"), final)] * 2).get(timeout=45)
    assert sorted(results) == ["idempotent", "inserted"]
    check = Store(tmp_path / "state.sqlite", tmp_path / "logs")
    events = check.data_quality_decision_shadow_events(limit=20)
    check.close_read_connection()
    assert len([event for event in events if event.get("event_id") == "data_quality_decision_shadow:process_cycle"]) == 1


def test_daily_learning_is_not_a_shadow_feature_or_authority() -> None:
    source = inspect.getsource(daily_learning._materialize_observations)
    assert "data_quality_decision_shadow" not in source
    assert "upsert_learning_observations_batch" in source


def test_shadow_is_not_in_active_payload_modules() -> None:
    import importlib

    broker = importlib.import_module("agente_bolsa.tools.broker")
    execution = importlib.import_module("agente_bolsa.tools.execution")
    risk = importlib.import_module("agente_bolsa.tools.risk")
    from agente_bolsa import cycle_runner

    assert "data_quality_decision_shadow" not in inspect.getsource(broker)
    assert "data_quality_decision_shadow" not in inspect.getsource(execution)
    assert "data_quality_decision_shadow" not in inspect.getsource(risk)
    # The cycle runner owns the fail-open boundary, but the shadow is not
    # passed into the broker payload builders.
    auto_source = inspect.getsource(cycle_runner._auto_paper_trade)
    assert "save_order_plan" in auto_source and "submit" in auto_source
    assert "data_quality_decision_shadow" in auto_source
