"""QA P-L50B para linaje e inputs estructurados del shadow P-L44."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.cycle_runner import _persist_learning_penalty_cycle_shadow_final
from agente_bolsa.scheduler import _prepare_learning_penalty_cycle_shadow, _selected_candidates
from agente_bolsa.storage import Store
from agente_bolsa.tools.learning_penalty_cycle_shadow import (
    LEGACY_SCHEMA_VERSION,
    SCHEMA_VERSION,
    build_learning_penalty_cycle_shadow,
    finalize_learning_penalty_cycle_shadow,
    learning_penalty_shadow_digest,
    persist_learning_penalty_cycle_shadow,
    project_learning_penalty_phase_a_context,
)
from agente_bolsa.tools.signal_learning import prepare_signal_candidate_identities


def _settings(tmp_path: Path) -> Settings:
    return Settings(DATA_DIR=tmp_path, _env_file=None, max_orders_per_cycle=5)


def _candidate(index: int, *, cycle_id: str | None = None, with_inputs: bool = True) -> dict[str, Any]:
    row: dict[str, Any] = {
        "symbol": f"S{index:03d}",
        "direction": "long",
        "signal_capture_id": f"capture-{index}",
        "signal_id": f"signal-{index}",
        "candidate_id": f"candidate-{index}",
        "strategy_name": "builtin_breakout",
        "strategy_version": "v1",
        "last_date": "2026-07-20",
        "score": 14.0,
        "selection_rank": index + 1,
        "rank_priority_score": round(0.9 - index / 1000, 4),
    }
    if cycle_id is not None:
        row["cycle_id"] = cycle_id
    if with_inputs:
        row["learning_prior"] = {
            "setup_edge_3d_raw": -0.0007,
            "operational_penalty": 0.05,
            "expected_edge_3d": -0.0507,
            "sample_size_3d": 27957,
            "confidence_weight_3d": 0.8,
        }
    return row


def _decision(index: int, *, action: str = "buy", control: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "action": action,
        "recommendation_id": f"rec-{index}",
        "decision_lineage": {
            "cycle_id": "cycle-qa",
            "signal_capture_id": f"capture-{index}",
            "signal_id": f"signal-{index}",
            "candidate_id": f"candidate-{index}",
            "decision_source": "capacity_fill",
        },
        **({"comparable_control_set": control} if control is not None else {}),
    }


class _Reporter:
    def __init__(self) -> None:
        self.events: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def emit(self, *args: Any, **kwargs: Any) -> None:
        self.events.append((args, kwargs))


def test_443_fixture_preserves_characterized_denominators(tmp_path: Path):
    rows = [_candidate(index) for index in range(420)]
    rows.extend(
        {
            "symbol": f"M{index}",
            "direction": "long",
            "learning_prior": _candidate(index)["learning_prior"],
        }
        for index in range(8)
    )
    duplicated = _candidate(500)
    rows.extend([duplicated, copy.deepcopy(duplicated)])
    rows.extend(_candidate(510 + index, cycle_id="cycle-other") for index in range(8))
    rows.extend(_candidate(600 + index, with_inputs=False) for index in range(5))

    snapshot = build_learning_penalty_cycle_shadow(
        "cycle-qa",
        {"all_candidates": rows},
        active_candidates=rows,
        settings=_settings(tmp_path),
        captured_at="2026-07-20T13:00:00+00:00",
    )

    counts = snapshot["candidate_counts"]
    assert len(rows) == 443
    assert counts["identity_verified"] == 425
    assert counts["identity_unavailable"] == 8
    assert counts["identity_ambiguous"] == 10
    assert counts["shadow_inputs_available"] == 420
    assert counts["shadow_inputs_unavailable"] == 23
    assert snapshot["schema_version"] == SCHEMA_VERSION


def test_producer_identity_reaches_phase_a_without_reannotation_or_mutation(tmp_path: Path):
    report = {
        "run_id": "cycle-producer",
        "as_of": "2026-07-20T13:00:00+00:00",
        "all_candidates": [_candidate(1)],
        "top_longs": [_candidate(1)],
        "selected_candidates": [_candidate(1)],
    }
    for bucket in report:
        if isinstance(report[bucket], list):
            for row in report[bucket]:
                row.pop("signal_capture_id", None)
                row.pop("signal_id", None)
                row.pop("candidate_id", None)

    prepared = prepare_signal_candidate_identities(report, source="intraday_scan")
    selected, _symbols = _selected_candidates(report, _settings(tmp_path))
    ranked = report["_learning_penalty_ranked_context"]
    before_ranked = copy.deepcopy(ranked)
    reporter = _Reporter()
    snapshot = _prepare_learning_penalty_cycle_shadow(
        _settings(tmp_path),
        reporter,
        ranked,
        selected,
        "cycle-producer",
    )

    assert prepared["source_run_id"] == "cycle-producer"
    assert snapshot is not None
    assert snapshot["candidate_counts"]["identity_verified"] == 1
    assert snapshot["input_wiring"]["signal_capture_id_present"] == 1
    assert ranked == before_ranked
    assert reporter.events == []


def test_phase_a_projection_is_deep_and_excludes_post_decision_fields():
    candidate = _candidate(1)
    candidate.update(
        {
            "pnl": 10.0,
            "fills": [{"price": 1.0}],
            "return_5d": 0.2,
            "prompt": "not-allowed",
        }
    )
    source = {"all_candidates": [candidate]}
    projected = project_learning_penalty_phase_a_context(source)
    projected["all_candidates"][0]["learning_prior"]["expected_edge_3d"] = 99

    assert candidate["learning_prior"]["expected_edge_3d"] == -0.0507
    encoded = json.dumps(projected)
    assert all(field not in encoded for field in ("pnl", "fills", "return_5d", "prompt"))


def test_vtrs_buy_and_exit_are_distinct_decisions_without_silent_dedup(tmp_path: Path):
    candidate = _candidate(1)
    candidate.update(
        {
            "symbol": "VTRS",
            "signal_capture_id": "capture-vtrs",
            "signal_id": "signal-vtrs",
            "candidate_id": "candidate-vtrs",
        }
    )
    phase_a = build_learning_penalty_cycle_shadow(
        "cycle-qa",
        {"all_candidates": [candidate]},
        active_candidates=[candidate],
        settings=_settings(tmp_path),
    )
    decisions = [
        {
            "action": action,
            "recommendation_id": f"rec-{action}",
            "decision_lineage": {
                "cycle_id": "cycle-qa",
                "signal_capture_id": "capture-vtrs",
                "signal_id": "signal-vtrs",
                "candidate_id": "candidate-vtrs",
            },
        }
        for action in ("buy", "exit")
    ]
    before = copy.deepcopy(decisions)
    final = finalize_learning_penalty_cycle_shadow(
        phase_a,
        recommendations=decisions,
        cycle_id="cycle-qa",
    )

    assert decisions == before
    assert [(row["action"], row["recommendation_id"]) for row in final["decision_observations"]] == [
        ("buy", "rec-buy"),
        ("exit", "rec-exit"),
    ]
    assert all(
        row["decision_identity_status"] == "identity_verified"
        for row in final["decision_observations"]
    )


def test_rejection_reader_counts_six_canonical_and_ignores_six_generic(tmp_path: Path):
    candidates = [_candidate(index) for index in range(6)]
    phase_a = build_learning_penalty_cycle_shadow(
        "cycle-qa",
        {"all_candidates": candidates},
        active_candidates=candidates,
        settings=_settings(tmp_path),
    )
    canonical = [
        {
            "event_id": f"rejection:{index}",
            "cycle_id": "cycle-qa",
            "candidate_id": f"candidate-{index}",
            "signal_id": f"signal-{index}",
            "action": "buy",
            "reason_code": "position_sizing",
            "stage": "position_sizing",
        }
        for index in range(6)
    ]
    raw = canonical + [
        {**row, "event_id": f"evt_{index}"}
        for index, row in enumerate(canonical)
    ]
    final = finalize_learning_penalty_cycle_shadow(
        phase_a,
        rejected_order_plans=raw,
        cycle_id="cycle-qa",
    )

    assert final["rejection_counts"] == {
        "raw": 12,
        "canonical": 6,
        "generic_rows_ignored": 6,
        "duplicates": 0,
        "identity_unavailable": 0,
    }
    assert len(final["rejection_observations"]) == 6


def test_control_denominators_distinguish_all_required_states(tmp_path: Path):
    candidates = [_candidate(index) for index in range(5)]
    phase_a = build_learning_penalty_cycle_shadow(
        "cycle-qa",
        {"all_candidates": candidates},
        active_candidates=candidates,
        settings=_settings(tmp_path),
    )
    decisions = [
        _decision(0),
        _decision(1),
        _decision(2),
        _decision(3, control={"status": "verified"}),
        {"action": "buy", "recommendation_id": "rec-4", "decision_lineage": {"cycle_id": "cycle-qa"}},
    ]
    controls = {
        "signal-0": {"status": "verified", "controls": []},
        "signal-1": {"status": "unavailable", "reason": "no_alternative", "controls": []},
    }
    final = finalize_learning_penalty_cycle_shadow(
        phase_a,
        recommendations=decisions,
        comparable_control_sets=controls,
        cycle_id="cycle-qa",
    )

    assert final["control_counts"] == {
        "comparable_control": 1,
        "control_unavailable": 1,
        "control_not_generated": 1,
        "control_identity_unavailable": 1,
        "control_persistence_missing": 1,
    }


def test_freshness_stale_and_unverified_is_descriptive_only(tmp_path: Path):
    candidate = _candidate(1)
    phase_a = build_learning_penalty_cycle_shadow(
        "cycle-qa",
        {"all_candidates": [candidate]},
        active_candidates=[candidate],
        settings=_settings(tmp_path),
    )
    decision = _decision(1) | {
        "signal_at": "2026-07-20T13:45:21.140341+00:00",
        "recommendation_at": "2026-07-20T16:08:27.168281+00:00",
        "plan_at": "2026-07-20T16:08:43.435757+00:00",
        "submitted_at": "2026-07-20T16:08:45.140012+00:00",
        "signal_price": 339.9,
        "recommendation_price": 339.9,
        "plan_price": 339.9,
    }
    final = finalize_learning_penalty_cycle_shadow(
        phase_a,
        recommendations=[decision],
        cycle_id="cycle-qa",
    )
    freshness = final["decision_observations"][0]["freshness"]

    assert freshness["signal_to_submit_seconds"] == 8603.999671
    assert freshness["stale_signal"] is True
    assert freshness["price_refresh_status"] == "unverified"
    assert final["active_policy"] == "legacy_double_application"
    assert final["shadow_policy"] == "single_application"


def test_v2_persistence_is_idempotent_conflict_safe_and_v1_readable(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite", tmp_path / "logs")
    store.ensure_schema()
    snapshot = build_learning_penalty_cycle_shadow(
        "cycle-v2",
        {"all_candidates": [_candidate(1)]},
        settings=_settings(tmp_path),
        captured_at="2026-07-20T13:00:00+00:00",
    )
    assert persist_learning_penalty_cycle_shadow(store, snapshot)["status"] == "inserted"
    repeated = copy.deepcopy(snapshot)
    repeated["captured_at"] = "2026-07-20T14:00:00+00:00"
    assert persist_learning_penalty_cycle_shadow(store, repeated)["status"] == "idempotent"
    changed = copy.deepcopy(snapshot)
    changed["candidate_counts"]["ranked_buy_total"] = 2
    changed["content_hash"] = "different"
    assert persist_learning_penalty_cycle_shadow(store, changed)["status"] == "conflict"

    legacy = build_learning_penalty_cycle_shadow(
        "cycle-v1",
        {"all_candidates": [_candidate(2)]},
        settings=_settings(tmp_path),
        captured_at="2026-07-20T13:00:00+00:00",
    )
    legacy["schema_version"] = LEGACY_SCHEMA_VERSION
    body = {key: value for key, value in legacy.items() if key not in {"captured_at", "content_hash"}}
    legacy["content_hash"] = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    assert persist_learning_penalty_cycle_shadow(store, legacy)["status"] == "inserted"
    digest = learning_penalty_shadow_digest(store)

    assert digest["canonical_cycles"] == 2
    assert digest["conflicts"] == 1
    assert digest["schema_versions"] == {LEGACY_SCHEMA_VERSION: 1, SCHEMA_VERSION: 1}


def test_persistence_failure_is_fail_open_and_does_not_mutate_active_objects(tmp_path: Path):
    class FailingStore:
        def record_learning_penalty_cycle_shadow(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("sqlite_temporarily_locked")

    candidate = _candidate(1)
    phase_a = build_learning_penalty_cycle_shadow(
        "cycle-qa",
        {"all_candidates": [candidate]},
        settings=_settings(tmp_path),
    )
    recommendations = [_decision(1)]
    plans = [
        {
            "side": "buy",
            "qty": 1,
            "entry_price": 100.0,
            "decision_lineage": recommendations[0]["decision_lineage"],
            "recommendation": recommendations[0],
        }
    ]
    before = copy.deepcopy((recommendations, plans))
    reporter = _Reporter()
    result = _persist_learning_penalty_cycle_shadow_final(
        store=FailingStore(),
        reporter=reporter,
        phase_a=phase_a,
        run_id="cycle-qa",
        recommendations=recommendations,
        plans=plans,
        comparable_control_sets={},
        rejected_order_plans=[],
    )

    assert result is None
    assert (recommendations, plans) == before
    assert reporter.events
    assert reporter.events[-1][0][1] == "learning_penalty_cycle_shadow_failed"


def test_phase_order_and_sql_transaction_are_short_and_explicit():
    root = Path(__file__).parents[1]
    scheduler = (root / "src" / "agente_bolsa" / "scheduler.py").read_text(encoding="utf-8")
    cycle_runner = (root / "src" / "agente_bolsa" / "cycle_runner.py").read_text(encoding="utf-8")
    storage = (root / "src" / "agente_bolsa" / "storage.py").read_text(encoding="utf-8")

    producer = scheduler.index("prepared_signal_identity = prepare_signal_candidate_identities")
    ranking = scheduler.index("selected_candidates, selected_symbols = _selected_candidates", producer)
    phase_a = scheduler.index("learning_penalty_shadow = _prepare_learning_penalty_cycle_shadow", ranking)
    phase_b = cycle_runner.index("learning_penalty_shadow_final = _persist_learning_penalty_cycle_shadow_final")
    plan_persistence = cycle_runner.index('optional_measure(timing, "persistence", "order_plan_records")')
    order_send = cycle_runner.index("submit_paper_order_plan", phase_b)

    assert producer < ranking < phase_a
    assert phase_b < plan_persistence < order_send
    assert 'conn.execute("BEGIN IMMEDIATE")' in storage
    assert "INSERT OR REPLACE" not in storage[storage.index("def record_learning_penalty_cycle_shadow"): storage.index("def learning_penalty_cycle_shadow_read")]


def test_identity_preparation_does_not_change_active_selection_order(tmp_path: Path):
    base = {
        "run_id": "cycle-parity",
        "as_of": "2026-07-20T13:00:00+00:00",
        "all_candidates": [_candidate(index) for index in range(12)],
        "top_longs": [_candidate(index) for index in range(12)],
    }
    enriched = copy.deepcopy(base)
    prepare_signal_candidate_identities(enriched, source="intraday_scan")
    before, _ = _selected_candidates(base, _settings(tmp_path))
    after, _ = _selected_candidates(enriched, _settings(tmp_path))

    assert [item["symbol"] for item in before] == [item["symbol"] for item in after]
    active_fields = ("score", "rank_priority_score", "selection_rank", "direction")
    assert [tuple(item.get(key) for key in active_fields) for item in before] == [
        tuple(item.get(key) for key in active_fields) for item in after
    ]
