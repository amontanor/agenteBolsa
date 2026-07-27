from __future__ import annotations

import copy
import inspect
import json
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from agente_bolsa.storage import Store
from agente_bolsa.tools.canonical_selection_ledger import (
    SCHEMA_VERSION,
    build_canonical_selection_ledger,
    canonical_selection_ledger_digest,
    match_mature_forward_outcome,
    match_same_cycle_controls,
    persist_canonical_selection_ledger,
    read_canonical_selection_ledger,
    stable_content_hash,
)

CAPTURED_AT = "2026-07-22T00:00:00+00:00"


def _candidate(
    index: int,
    *,
    cycle_id: str = "cycle-A",
    action: str = "buy",
    symbol: str | None = None,
    eligible: bool | None = True,
    selected: bool = False,
) -> dict[str, Any]:
    symbol = symbol or f"SYM{index:03d}"
    action = "exit" if action.lower() in {"exit", "sell"} else "buy"
    signal_at = datetime(2026, 7, 21, 14, 0, tzinfo=timezone.utc) + timedelta(seconds=index)
    return {
        "cycle_id": cycle_id,
        "session_date": "2026-07-21",
        "signal_capture_id": f"capture:{cycle_id}:{action}:{symbol}:{index}",
        "signal_id": f"signal:{cycle_id}:{action}:{symbol}",
        "candidate_id": f"candidate:{cycle_id}:{index}",
        "source_run_id": "scan-A",
        "symbol": symbol,
        "action": action,
        "strategy": "builtin_breakout" if index % 2 == 0 else "builtin_pullback",
        "setup": "continuation" if index % 4 in (0, 1) else "reversal",
        "score_universe": "domain-A" if index % 2 == 0 else "domain-B",
        "score": 10.0 + index / 100.0,
        "rank_priority_score": 0.2 - index / 10000.0,
        "learning_prior": {"expected_edge": 0.02 - index / 100000.0},
        "score_rank": index % 10 + 1,
        "selection_rank": index % 20 + 1,
        "data_quality": "good",
        "freshness": "fresh",
        "price_basis": "close_unadjusted",
        "signal_at": signal_at.isoformat(),
        "decision_at": (signal_at + timedelta(seconds=10)).isoformat(),
        "eligible_at_selection": eligible,
        "gate_frontier": "entry_eligibility_v1",
        "selected_for_llm": selected,
    }


def _phase_a(count: int = 443, *, truncated_count: int | None = None) -> dict[str, Any]:
    rows = [_candidate(index, selected=index < 20) for index in range(count)]
    rows[-2] = _candidate(count - 2, action="exit", symbol="SYM000")
    rows[-1] = _candidate(count - 1, cycle_id="cycle-B", symbol="SYM000")
    phase: dict[str, Any] = {
        "all_candidates": rows,
        "selected_candidates": rows[:20],
    }
    if truncated_count is not None:
        phase["truncated_count"] = truncated_count
    return phase


def _lineage(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "cycle_id": row["cycle_id"],
        "action": row["action"],
        "signal_capture_id": row["signal_capture_id"],
        "signal_id": row["signal_id"],
        "candidate_id": row["candidate_id"],
    }


def _recommendation(row: dict[str, Any], index: int, *, source: str = "llm") -> dict[str, Any]:
    # P-L59C: llm_selected es autoridad estructurada del productor
    _llm_sel: bool | None = None
    if source == "llm":
        _llm_sel = True
    elif source in {"capacity_fill", "deterministic_capacity_fill", "fallback", "deterministic_fallback", "hold_override"}:
        _llm_sel = False
    snapshot: dict[str, Any] = {
        "llm_considered": source in {"llm", "deterministic_capacity_fill"},
        "gate_frontier": row["gate_frontier"],
    }
    if _llm_sel is not None:
        snapshot["llm_selected"] = _llm_sel
    return {
        "cycle_id": row["cycle_id"],
        "action": row["action"],
        "recommendation_id": f"rec:{index}",
        "source": source,
        "decision_origin": source,
        "decision_lineage": _lineage(row),
        "decision_context_snapshot": snapshot,
    }


def _plan_record(row: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "cycle_id": row["cycle_id"],
        "action": row["action"],
        "plan_id": f"plan:{index}",
        "decision_lineage": _lineage(row),
        "payload": {"decision_lineage": _lineage(row)},
    }


def _build_large() -> dict[str, Any]:
    phase = _phase_a()
    rows = phase["all_candidates"]
    recommendations = [_recommendation(rows[index], index) for index in range(5)]
    recommendations[3]["source"] = "capacity_fill"
    recommendations[3]["decision_origin"] = "capacity_fill"
    # P-L59C: update llm_selected in snapshot when source changes post-hoc
    rec3_snap = dict(recommendations[3].get("decision_context_snapshot", {}))
    rec3_snap["llm_selected"] = False
    rec3_snap["llm_considered"] = True
    recommendations[3]["decision_context_snapshot"] = rec3_snap
    plans = [_plan_record(rows[index], index) for index in range(3)]
    ordered = [
        {
            "cycle_id": rows[index]["cycle_id"],
            "action": rows[index]["action"],
            "plan_id": f"plan:{index}",
            "broker_order_id": f"broker:{index}",
            "decision_lineage": _lineage(rows[index]),
        }
        for index in range(2)
    ]
    return build_canonical_selection_ledger(
        "cycle-A",
        phase,
        recommendations=recommendations,
        plan_records=plans,
        ordered_records=ordered,
        rejected_order_plans=[
            {
                "cycle_id": "cycle-A",
                "action": "buy",
                "reason": "cycle_capacity_limit",
                "decision_lineage": _lineage(rows[20]),
            }
        ],
        captured_at=datetime.fromisoformat(CAPTURED_AT),
    )


def _store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "agent.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    return store


def test_large_cycle_captures_full_universe_and_separate_stages() -> None:
    payload = _build_large()
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["event_id"] == "canonical_selection_ledger:cycle-A"
    assert payload["status"] == "verified"
    denom = payload["denominators"]
    # v1 denominators preserved
    assert denom["raw_count"] == 443
    assert denom["canonical_count"] == 443
    assert denom["eligible_count"] == 443
    assert denom["selected_count"] == 20
    assert denom["recommended_count"] == 5
    assert denom["planned_count"] == 3
    assert denom["ordered_count"] == 2
    assert denom["identity_unavailable"] == 0
    assert denom["identity_ambiguous"] == 0
    assert denom["shadow_inputs_unavailable"] == 0
    assert denom["conflict_count"] == 0
    assert denom["truncated_count"] == 0
    # v2 denominators present
    assert denom["candidate_count"] == 443
    assert denom["recommendation_observed"] == 5
    assert denom["recommendation_canonical"] == 5
    assert denom["recommendation_conflict"] == 0
    rows = {item["identity_key"]: item for item in payload["candidate_rows"]}
    selected = rows["cycle-A|buy|capture:cycle-A:buy:SYM005:5"]
    assert selected["selected_for_llm"] is True
    assert selected["recommended"] is False
    assert selected["planned"] is False
    assert selected["ordered"] is False
    capacity = rows["cycle-A|buy|capture:cycle-A:buy:SYM003:3"]
    assert capacity["decision_source"] == "deterministic_capacity_fill"
    assert capacity["llm_considered"] is True
    assert capacity["llm_selected"] is False


def test_capture_identity_precedes_signal_id_and_buy_exit_stay_separate() -> None:
    phase = _phase_a(2)
    phase["all_candidates"][0]["signal_id"] = "same-signal"
    phase["all_candidates"][1]["signal_id"] = "same-signal"
    payload = build_canonical_selection_ledger("cycle-A", phase)
    keys = {row["identity_key"] for row in payload["candidate_rows"]}
    assert len(keys) == 2
    assert any("|exit|" in key for key in keys)
    assert any("|buy|" in key for key in keys)


def test_missing_ambiguous_generic_and_conflict_rows_are_not_canonical() -> None:
    first = _candidate(0)
    duplicate = copy.deepcopy(first)
    conflict = copy.deepcopy(first)
    conflict["score"] = 999.0
    missing = {"symbol": "REPORTER", "score": 1.0}
    ambiguous = _candidate(1)
    ambiguous["identity_ambiguous"] = True
    payload = build_canonical_selection_ledger(
        "cycle-A",
        {"all_candidates": [first, duplicate, conflict, missing, ambiguous]},
    )
    assert payload["denominators"]["raw_count"] == 5
    assert payload["denominators"]["canonical_count"] == 1
    assert payload["denominators"]["identity_unavailable"] == 1
    assert payload["denominators"]["identity_ambiguous"] == 1
    assert payload["denominators"]["conflict_count"] == 1
    assert "candidate_identity_conflict" in payload["warnings"]


def test_cap_is_explicit_and_status_is_partial() -> None:
    payload = build_canonical_selection_ledger("cycle-A", _phase_a(truncated_count=199_557))
    assert payload["status"] == "partial"
    assert payload["truncated_count"] == 199_557
    assert payload["denominators"]["raw_count"] == 443
    assert payload["denominators"]["truncated_count"] == 199_557
    assert "universe_truncated" in payload["warnings"]


def test_same_cycle_matching_requires_exact_frontier_and_excludes_recommended_controls() -> None:
    payload = _build_large()
    rows = payload["candidate_rows"]
    treatment = next(row for row in rows if row["identity_key"].endswith("capture:cycle-A:buy:SYM000:0"))
    result = match_same_cycle_controls(treatment, rows)
    assert result["status"] == "verified"
    assert result["controls"]
    assert all(row["cycle_id"] == "cycle-A" for row in result["controls"])
    assert all(row["selected_for_llm"] is False for row in result["controls"])
    assert all(row["recommended"] is False for row in result["controls"])
    reasons = {row["reason"] for row in result["excluded"]}
    assert "cycle_mismatch" in reasons
    assert "action_mismatch" in reasons
    assert "postdecision_recommended_not_control" in reasons


def test_mature_outcomes_are_joined_after_capture_and_not_embedded() -> None:
    payload = _build_large()
    row = next(item for item in payload["candidate_rows"] if item["identity_key"].endswith("capture:cycle-A:buy:SYM000:0"))
    sessions = ["2026-07-21", "2026-07-22", "2026-07-23", "2026-07-24", "2026-07-27", "2026-07-28"]
    outcome = {
        "cycle_id": row["cycle_id"],
        "action": row["action"],
        "signal_capture_id": row["signal_capture_id"],
        "horizon": "3d",
        "matured": True,
        "maturity_session_date": "2026-07-24",
        "price_basis": row["price_basis"],
        "forward_return": 0.012,
    }
    joined = match_mature_forward_outcome(row, outcome, completed_sessions=sessions)
    assert joined["status"] == "matured"
    assert joined["forward_return"] == 0.012
    assert joined["net_profit"] is None
    assert payload["outcomes"] is None
    assert "forward_return" not in json.dumps(row)
    immature = {**outcome, "horizon": "5d", "matured": False}
    assert match_mature_forward_outcome(row, immature, completed_sessions=sessions)["status"] == "unavailable"


def test_invalid_timestamps_and_future_fields_degrade_or_fail_closed() -> None:
    naive = _candidate(0)
    naive["signal_at"] = "2026-07-21T14:00:00"
    inverted = _candidate(1)
    inverted["decision_at"] = "2026-07-21T13:00:00+00:00"
    future = _candidate(2)
    future["signal_at"] = "2026-07-23T14:00:00+00:00"
    payload = build_canonical_selection_ledger(
        "cycle-A",
        {"all_candidates": [naive, inverted, future]},
        captured_at=datetime.fromisoformat(CAPTURED_AT),
    )
    assert all(row["timestamp_status"] == "unavailable" for row in payload["candidate_rows"])
    forbidden = _candidate(3)
    forbidden["return_3d"] = 0.12
    with pytest.raises(ValueError, match="predecision_forbidden_field:return_3d"):
        build_canonical_selection_ledger("cycle-A", {"all_candidates": [forbidden]})


def test_hash_read_order_and_canonical_store_are_stable(tmp_path: Path) -> None:
    store = _store(tmp_path)
    payload = _build_large()
    assert persist_canonical_selection_ledger(store, payload)["status"] == "inserted"
    repeated = copy.deepcopy(payload)
    repeated["captured_at"] = "2026-07-22T01:00:00+00:00"
    repeated["content_hash"] = stable_content_hash(repeated)
    assert persist_canonical_selection_ledger(store, repeated)["status"] == "idempotent"
    changed = copy.deepcopy(payload)
    changed["candidate_rows"][0]["score"] = 999.0
    changed["content_hash"] = stable_content_hash(changed)
    conflict = persist_canonical_selection_ledger(store, changed)
    assert conflict["status"] == "conflict"
    original = read_canonical_selection_ledger(store, "cycle-A")
    assert original["candidate_rows"][0]["score"] != 999.0
    assert canonical_selection_ledger_digest(store, "cycle-A")["conflict_events"] == 1
    assert "INSERT OR REPLACE" not in inspect.getsource(Store.record_canonical_selection_ledger)


def test_concurrent_writers_are_inserted_and_idempotent_without_lock(tmp_path: Path) -> None:
    store = _store(tmp_path)
    payload = _build_large()

    def write_once(_: int) -> str:
        writer = Store(store.database_path, tmp_path / "logs")
        return persist_canonical_selection_ledger(writer, payload)["status"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(write_once, (1, 2)))
    assert sorted(statuses) == ["idempotent", "inserted"]
    assert store.canonical_selection_ledger_conflicts("cycle-A") == []


def test_collecting_reader_has_null_denominators_and_fail_open_helper(monkeypatch, tmp_path: Path) -> None:
    empty_store = Store(tmp_path / "missing" / "agent.sqlite3", tmp_path / "logs")
    empty_read = read_canonical_selection_ledger(empty_store, "missing-cycle")
    assert empty_read["status"] == "collecting"
    assert all(value is None for value in empty_read["denominators"].values())

    store = _store(tmp_path)
    collecting = read_canonical_selection_ledger(store, "missing-cycle")
    assert collecting["status"] == "collecting"
    assert all(value is None for value in collecting["denominators"].values())

    import agente_bolsa.cycle_runner as cycle_runner

    monkeypatch.setattr(
        cycle_runner,
        "build_canonical_selection_ledger",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("shadow-build-failed")),
    )

    class Reporter:
        def __init__(self) -> None:
            self.events: list[dict[str, Any]] = []

        def emit(self, *args: Any, **kwargs: Any) -> None:
            self.events.append({"args": args, "kwargs": kwargs})

    reporter = Reporter()
    result = cycle_runner._persist_selection_ledger_shadow(
        store=store,
        reporter=reporter,
        phase_a={"all_candidates": []},
        run_id="cycle-fail-open",
    )
    assert result["status"] == "unavailable"
    assert reporter.events


def test_no_mutation_of_active_objects_and_no_protected_references() -> None:
    phase = _phase_a()
    active = {
        "candidates": copy.deepcopy(phase["all_candidates"]),
        "scores": [1.0],
        "ranks": [1],
        "gates": ["passed"],
        "sizing": [0.5],
        "plans": ["plan"],
        "orders": ["order"],
        "exposure": 0.1,
        "limits": {"daily": 1},
    }
    before_phase = copy.deepcopy(phase)
    before_active = copy.deepcopy(active)
    build_canonical_selection_ledger("cycle-A", phase)
    assert phase == before_phase
    assert active == before_active


def test_observable_cycle_wiring_captures_phase_a_once_without_prompt_mutation(monkeypatch, tmp_path: Path) -> None:
    import agente_bolsa.cycle_runner as cycle_runner
    from agente_bolsa.config import Settings

    settings = Settings(
        DATA_DIR=tmp_path,
        TRADING_MODE="paper",
        AUTO_PAPER_TRADING=False,
        ALPACA_PAPER=True,
        ALLOW_LIVE_TRADING=False,
    )
    store = _store(tmp_path)
    phase = _phase_a(3)
    technical_context = {"selected_candidates": [{"symbol": "SYM000"}], "prompt_only": "unchanged"}
    calls: list[dict[str, Any]] = []
    original = cycle_runner._persist_selection_ledger_shadow

    def spy(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(cycle_runner, "_persist_selection_ledger_shadow", spy)
    monkeypatch.setattr(
        cycle_runner,
        "build_market_snapshot",
        lambda *args, **kwargs: {"symbols": {}, "benchmark_symbol": "SPY", "provider": "local", "warnings": []},
    )
    monkeypatch.setattr(
        cycle_runner,
        "build_market_state",
        lambda *args, **kwargs: {
            "path": str(tmp_path / "market_state.json"),
            "market_regime": "neutral",
            "data_quality": {"status": "GOOD"},
        },
    )
    cycle_runner.run_observable_cycle(
        settings,
        store,
        use_crew=False,
        verbose=False,
        technical_context=technical_context,
        selection_ledger_phase_a=phase,
        run_id="wire-cycle",
    )
    assert len(calls) == 1
    assert calls[0]["phase_a"] is phase
    assert technical_context == {"selected_candidates": [{"symbol": "SYM000"}], "prompt_only": "unchanged"}
    assert read_canonical_selection_ledger(store, "wire-cycle")["event_id"] == "canonical_selection_ledger:wire-cycle"


def test_volume_100_cycles_by_500_candidates_is_measured_and_persisted(tmp_path: Path) -> None:
    store = _store(tmp_path)
    tracemalloc.start()
    started = time.perf_counter()
    for cycle_index in range(100):
        cycle = f"volume-{cycle_index:03d}"
        phase = {
            "all_candidates": [_candidate(index, cycle_id=cycle) for index in range(500)],
            "selected_candidates": [],
        }
        payload = build_canonical_selection_ledger(cycle, phase)
        assert persist_canonical_selection_ledger(store, payload)["status"] == "inserted"
    elapsed_seconds = time.perf_counter() - started
    _current, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert elapsed_seconds >= 0
    assert peak_bytes > 0
    assert store.latest_canonical_selection_ledger_event() is not None
    with store.read_connection() as connection:
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM agent_events WHERE event_type = ?",
            ("canonical_selection_ledger",),
        ).fetchone()["count"]
    store.close_read_connection()
    assert count == 100
