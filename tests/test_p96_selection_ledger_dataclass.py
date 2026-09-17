import copy
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from agente_bolsa import cycle_runner
from agente_bolsa.models import TradeRecommendation
from agente_bolsa.storage import Store
from agente_bolsa.tools.canonical_selection_ledger import build_canonical_selection_ledger

CAPTURED_AT = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


def _candidate() -> dict[str, object]:
    return {
        "cycle_id": "cycle-p96",
        "action": "buy",
        "signal_capture_id": "capture-p96",
        "signal_id": "signal-p96",
        "candidate_id": "candidate-p96",
        "symbol": "AAPL",
        "eligible_at_selection": True,
    }


def _recommendation() -> TradeRecommendation:
    return TradeRecommendation(
        symbol="AAPL",
        action="buy",
        confidence=0.8,
        reason="offline fixture",
        recommendation_id="recommendation-p96",
        decision_lineage={
            "cycle_id": "cycle-p96",
            "signal_capture_id": "capture-p96",
            "signal_id": "signal-p96",
            "candidate_id": "candidate-p96",
        },
    )


def _build(recommendations):
    return build_canonical_selection_ledger(
        "cycle-p96",
        {"all_candidates": [_candidate()]},
        recommendations=recommendations,
        captured_at=CAPTURED_AT,
    )


def test_trade_recommendation_dataclass_is_consumed_without_mutation():
    recommendation = _recommendation()
    before = copy.deepcopy(asdict(recommendation))

    result = _build([recommendation])

    assert result["decision_rows"][0]["decision_id"] == "recommendation-p96"
    assert result["decision_rows"][0]["decision_identity"] == "verified"
    assert asdict(recommendation) == before


def test_mapping_and_tuple_sequence_keep_same_canonical_result():
    recommendation = _recommendation()
    mapping_result = _build([asdict(recommendation)])
    sequence_result = _build((recommendation,))

    assert mapping_result["content_hash"] == sequence_result["content_hash"]
    assert mapping_result["decision_rows"] == sequence_result["decision_rows"]


def test_invalid_non_mapping_item_degrades_to_unavailable_without_throwing():
    result = _build([object()])

    assert "recommendation_identity_unavailable" in result["warnings"]
    assert result["decision_rows"][0]["decision_identity"] == "unavailable"


def test_repeated_build_is_idempotent_for_fixed_capture_time():
    recommendation = _recommendation()

    first = _build([recommendation])
    second = _build([recommendation])

    assert first == second


def test_cycle_runner_shadow_forwards_dataclass_sequence_without_fail_open_error(tmp_path: Path):
    store = Store(tmp_path / "agent.sqlite3", tmp_path / "logs")
    store.ensure_schema()

    class Reporter:
        def __init__(self):
            self.events = []

        def emit(self, *args, **kwargs):
            self.events.append((args, kwargs))

    reporter = Reporter()
    result = cycle_runner._persist_selection_ledger_shadow(
        store=store,
        reporter=reporter,
        phase_a={"all_candidates": [_candidate()]},
        run_id="cycle-p96",
        recommendations=[_recommendation()],
    )

    assert result["status"] == "verified"
    assert result["persist_status"] == "inserted"
    assert not any("failed" in str(event).lower() for event in reporter.events)
