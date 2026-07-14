"""P-L37B-T/W: isolated characterization and candidate contract tests.

The first cases preserve the pre-P-L37B failure shape in their fixtures while
asserting that the candidate repair keeps the original capture resolvable.
The future P-L37B contract is kept as test-only documentation so that the
implementation remains independent of trading policy:

* ``signal_id`` is a logical signal identity;
* ``signal_capture_id`` is unique for each capture;
* capture history is append-only;
* ``signal_source_run_id`` and the decision ``cycle_id`` stay separate;
* identity is transported literally and resolved by an exact capture ID;
* legacy rows remain explicitly legacy/unavailable.

The direct stale-report case remains a current-behavior characterization;
the scheduler path is tested separately after identity enrichment.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

from agente_bolsa.cycle_runner import _decision_context_snapshot_for_recommendation
from agente_bolsa.models import TradeRecommendation
from agente_bolsa.scheduler import _compact_scan_context
from agente_bolsa.storage import Store
from agente_bolsa.tools.decision_lineage import build_decision_lineage
from agente_bolsa.tools.reporting import write_json_report
from agente_bolsa.tools.signal_identity import resolve_signal_capture
from agente_bolsa.tools.signal_learning import record_signal_candidates

IDENTITY_FIELDS = (
    "signal_id",
    "signal_source_run_id",
    "candidate_id",
    "strategy_name",
    "strategy_version",
    "signal_date",
    "symbol",
)


def _store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "state" / "test.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    return store


def _candidate(*, strategy: str = "builtin_breakout", symbol: str = "FDS") -> dict:
    return {
        "symbol": symbol,
        "direction": "long",
        "action": "buy",
        "score": 9.25,
        "selection_rank": 1,
        "strategy_name": strategy,
        "strategy_version": "v1",
        "setup_name": "breakout",
        "setup_quality": "strong",
        "last_date": "2026-07-13",
        "technical_state": {
            "close": 100.0,
            "sma_20": 97.0,
            "gates": {"entry_quality": {"passed": True}},
        },
        "risk_plan": {
            "entry_price": 100.0,
            "stop_loss": 90.0,
            "take_profit": 120.0,
            "quantity": 3,
        },
    }


def _report(run_id: str, candidate: dict, *, copies: bool = False) -> dict:
    all_candidate = copy.deepcopy(candidate)
    selected_candidate = copy.deepcopy(candidate) if copies else all_candidate
    top_long = copy.deepcopy(candidate) if copies else all_candidate
    top_short = copy.deepcopy(candidate) if copies else all_candidate
    return {
        "run_id": run_id,
        "as_of": "2026-07-13T20:00:00+00:00",
        "all_candidates": [all_candidate],
        "selected_candidates": [selected_candidate],
        "top_longs": [top_long],
        "top_shorts": [top_short],
        "symbols_scanned": 1,
        "symbols_with_data": 1,
        "analysis_plan_counts": {},
        "warnings": [],
    }


def _exact_store_resolution(store: Store, lineage: dict) -> str:
    """Test-only exact resolver; symbol/date is deliberately not a fallback."""

    capture_id = str(lineage.get("signal_capture_id") or "").strip()
    if capture_id:
        return str(resolve_signal_capture(store, capture_id, signal_id=lineage.get("signal_id")).get("status"))
    signal_id = str(lineage.get("signal_id") or "").strip()
    source_run_id = str(lineage.get("signal_source_run_id") or "").strip()
    if not signal_id or not source_run_id:
        return "unavailable"
    row = store.signal_outcome_by_id(signal_id)
    if row is None:
        return "missing"
    return "exact_match" if row.get("source_run_id") == source_run_id else "mismatch"


def test_capture_history_preserves_first_cycle_exact_match_after_second_capture(tmp_path):
    """The candidate solution keeps capture-A while top-level metadata advances."""

    store = _store(tmp_path)
    candidate_a = _candidate()
    report_a = _report("source-run-A", candidate_a)
    assert record_signal_candidates(store, report_a, source="learning_experiment") == 1
    producer_candidate_a = report_a["all_candidates"][0]
    signal_id = producer_candidate_a["signal_id"]
    assert store.signal_outcome_by_id(signal_id)["source_run_id"] == "source-run-A"

    lineage_a = build_decision_lineage(
        TradeRecommendation(symbol="FDS", action="buy", confidence=0.8, reason="test", strategy_name="builtin_breakout"),
        {"selected_candidates": [producer_candidate_a]},
        cycle_id="cycle-A",
        policy_version="test",
        source_run_id="cycle-A",
    )
    assert lineage_a["signal_source_run_id"] == "source-run-A"

    candidate_b = _candidate()
    report_b = _report("source-run-B", candidate_b)
    assert record_signal_candidates(store, report_b, source="learning_experiment") == 1
    producer_candidate_b = report_b["all_candidates"][0]
    row_after_b = store.signal_outcome_by_id(signal_id)
    assert row_after_b["source_run_id"] == "source-run-B"

    recommendation_a = TradeRecommendation(
        symbol="FDS",
        action="buy",
        confidence=0.8,
        reason="first cycle",
        source="deterministic",
        decision_lineage=lineage_a,
    )
    snapshot = _decision_context_snapshot_for_recommendation(
        store,
        recommendation_a,
        cycle_id="cycle-A",
        source_run_id="cycle-A",
        market_state={
            "run_id": "cycle-A",
            "as_of": "2026-07-13T18:00:00+00:00",
            "prompt_version": "market_state.v2",
            "market_regime": "neutral",
            "volatility_regime": "normal",
            "risk_posture": "normal",
            "data_quality": {"status": "available"},
        },
        agent_run_id=None,
    )
    assert snapshot["signal_id"] == signal_id
    assert snapshot["cycle_id"] == "cycle-A"
    assert snapshot["signal_link_status"] == "verified"
    assert _exact_store_resolution(store, lineage_a) == "exact_match"
    assert store.signal_outcome_by_id(signal_id)["source_run_id"] == "source-run-B"
    assert len(store.signal_outcomes(include_learning_experiment=True)) == 1
    identity = store.signal_outcome_by_id(signal_id)["features"]["signal_identity"]
    assert identity["latest_signal_capture_id"] == producer_candidate_b["signal_capture_id"]
    assert len(identity["captures"]) == 2
    assert lineage_a["signal_capture_id"] in identity["captures"]
    # The weak symbol/date lookup still returns only the latest top-level row.
    latest = store.latest_signal_for_symbol("FDS")
    assert latest["signal_id"] == signal_id
    assert latest["signal_date"] == "2026-07-13"
    assert latest["source_run_id"] == "source-run-B"


def test_current_persisted_technical_report_precedes_identity_enrichment(tmp_path, monkeypatch):
    """Independent buckets are enriched in memory after the report was written."""

    store = _store(tmp_path)
    candidate = _candidate()
    report = _report("source-run-A", candidate, copies=True)
    report_path = tmp_path / "reports"
    monkeypatch.setattr(
        "agente_bolsa.tools.reporting.get_settings",
        lambda: SimpleNamespace(retention_enabled=False, disabled_report_prefix_list=[]),
    )

    persisted = write_json_report(report, report_path, "closed_market_technical_study", "source-run-A")
    persisted_path = Path(persisted["path"])
    before = json.loads(persisted_path.read_text(encoding="utf-8"))
    assert len({id(report[name][0]) for name in ("all_candidates", "selected_candidates", "top_longs", "top_shorts")}) == 4
    for bucket in ("all_candidates", "selected_candidates", "top_longs", "top_shorts"):
        row = before[bucket][0]
        assert all(row.get(field) is None for field in ("signal_id", "signal_source_run_id", "candidate_id", "signal_date"))
        assert row["strategy_name"] == "builtin_breakout"
        assert row["strategy_version"] == "v1"
        assert row["last_date"] == "2026-07-13"
        assert row["symbol"] == "FDS"

    original_economic = {
        key: copy.deepcopy(report["all_candidates"][0].get(key))
        for key in ("score", "selection_rank", "direction", "action", "risk_plan", "technical_state")
    }
    assert record_signal_candidates(store, report, source="learning_experiment") == 1
    for bucket in ("all_candidates", "selected_candidates", "top_longs", "top_shorts"):
        enriched = report[bucket][0]
        assert enriched["signal_id"] == "learning_experiment:2026-07-13:BUILTIN_BREAKOUT:FDS"
        assert enriched["signal_source_run_id"] == "source-run-A"
        assert enriched.get("candidate_id") is None
        assert enriched["strategy_name"] == "builtin_breakout"
        assert enriched["strategy_version"] == "v1"
        assert enriched["last_date"] == "2026-07-13"
        assert enriched["symbol"] == "FDS"
    assert {key: report["all_candidates"][0].get(key) for key in original_economic} == original_economic

    # No second write occurs in the real scheduler path, so the persisted JSON stays stale.
    after = json.loads(persisted_path.read_text(encoding="utf-8"))
    assert all(after[bucket][0].get("signal_id") is None for bucket in ("all_candidates", "selected_candidates", "top_longs", "top_shorts"))
    compact = _compact_scan_context(after, after["selected_candidates"])
    lineage = build_decision_lineage(
        TradeRecommendation(symbol="FDS", action="buy", confidence=0.8, reason="test", strategy_name="builtin_breakout"),
        compact,
        cycle_id="decision-cycle",
        policy_version="test",
    )
    assert lineage["signal_id"] is None
    assert lineage["lineage_status"] == "unavailable"
    assert lineage["lineage_reason"] == "missing_canonical_signal_id"


def test_first_recommendation_resolves_by_capture_not_latest_symbol_row(tmp_path):
    """Capture-A remains resolvable even though the top-level row is B."""

    store = _store(tmp_path)
    first = _candidate()
    second = _candidate()
    first_report = _report("source-run-A", first)
    record_signal_candidates(store, first_report, source="learning_experiment")
    first_producer_candidate = first_report["all_candidates"][0]
    lineage = build_decision_lineage(
        TradeRecommendation(symbol="FDS", action="buy", confidence=0.8, reason="test", strategy_name="builtin_breakout"),
        {"selected_candidates": [first_producer_candidate]},
        cycle_id="cycle-A",
        policy_version="test",
        source_run_id="cycle-A",
    )
    record_signal_candidates(store, _report("source-run-B", second), source="learning_experiment")
    current = store.signal_outcome_by_id(lineage["signal_id"])
    assert current["symbol"] == "FDS"
    assert current["signal_date"] == "2026-07-13"
    assert current["features"]["signal_strategy_name"] == "builtin_breakout"
    assert current["source_run_id"] != lineage["signal_source_run_id"]
    assert _exact_store_resolution(store, lineage) == "exact_match"
    assert lineage["signal_capture_id"] in current["features"]["signal_identity"]["captures"]
    assert lineage["signal_id"] == "learning_experiment:2026-07-13:BUILTIN_BREAKOUT:FDS"


def test_same_symbol_date_with_two_strategies_is_ambiguous_not_unknown(tmp_path):
    """A symbol/date key cannot choose between two strategy captures."""

    store = _store(tmp_path)
    breakout = _candidate(strategy="builtin_breakout")
    pullback = _candidate(strategy="builtin_pullback")
    record_signal_candidates(store, _report("source-run", breakout), source="learning_experiment")
    record_signal_candidates(store, _report("source-run", pullback), source="learning_experiment")
    rows = store.signal_outcomes(include_learning_experiment=True)
    assert {row["signal_id"] for row in rows} == {
        "learning_experiment:2026-07-13:BUILTIN_BREAKOUT:FDS",
        "learning_experiment:2026-07-13:BUILTIN_PULLBACK:FDS",
    }
    recommendation = TradeRecommendation(symbol="FDS", action="buy", confidence=0.8, reason="ambiguous")
    lineage = build_decision_lineage(
        recommendation,
        {
            "selected_candidates": [breakout, pullback],
            "top_longs": [breakout, pullback],
            "all_candidates": [breakout, pullback],
        },
        cycle_id="cycle-A",
        policy_version="test",
    )
    assert lineage["signal_id"] is None
    assert lineage["lineage_status"] == "unavailable"
    assert lineage["lineage_reason"] == "missing_canonical_signal_id"
    assert store.latest_signal_for_symbol("FDS")["signal_id"] in {row["signal_id"] for row in rows}


def test_future_p37b_contract_is_documented_without_changing_functional_fields(tmp_path):
    """Current producer enrichment must not alter ranking or economic payloads."""

    store = _store(tmp_path)
    report = _report("source-run-A", _candidate(), copies=True)
    before = {
        bucket: {
            key: copy.deepcopy(report[bucket][0].get(key))
            for key in ("score", "selection_rank", "direction", "action", "setup_name", "setup_quality", "risk_plan", "technical_state")
        }
        for bucket in ("all_candidates", "selected_candidates", "top_longs", "top_shorts")
    }
    record_signal_candidates(store, report, source="learning_experiment")
    after = {
        bucket: {
            key: copy.deepcopy(report[bucket][0].get(key))
            for key in before[bucket]
        }
        for bucket in before
    }
    assert after == before
    assert [item["symbol"] for item in report["selected_candidates"]] == ["FDS"]
    assert report["selected_candidates"][0]["signal_id"] == "learning_experiment:2026-07-13:BUILTIN_BREAKOUT:FDS"
