"""Observation identity collisions must never discard decision rows."""
from agente_bolsa.models import TradeRecommendation
from agente_bolsa.tools.gate_evaluation import build_gate_effectiveness_quality, collect_gate_path


def candidate(action="buy", *, capture=None, candidate_id=None):
    lineage = {"cycle_id": "cycle", "signal_id": "signal"}
    if capture:
        lineage["signal_capture_id"] = capture
    if candidate_id:
        lineage["candidate_id"] = candidate_id
    return TradeRecommendation(symbol="AAA", action=action, confidence=0.8,
                               reason="local", decision_lineage=lineage)


def collect(candidates):
    return collect_gate_path(cycle_id="cycle", candidates=candidates, stage_rows={},
                             captured_at="2026-10-19T16:00:00+00:00")


def test_legacy_buy_exit_sharing_signal_preserve_both_rows():
    rows = list(collect([candidate("buy"), candidate("exit")]).values())
    assert len(rows) == 2
    assert {row["action"] for row in rows} == {"buy", "exit"}
    assert len({row["snapshot_id"] for row in rows}) == 2


def test_different_capture_with_same_candidate_has_distinct_snapshot_identity():
    rows = list(collect([candidate(capture="a", candidate_id="same"),
                         candidate(capture="b", candidate_id="same")]).values())
    assert len(rows) == 2
    assert len({row["snapshot_id"] for row in rows}) == 2
    assert {row["signal_capture_id"] for row in rows} == {"a", "b"}


def test_exact_duplicate_identity_is_preserved_but_excluded_from_learning():
    rec = candidate(capture="a", candidate_id="same")
    rows = list(collect([rec, rec]).values())
    assert len(rows) == 2
    assert all(row["identity_conflict"] and row["decision"] == "unavailable" for row in rows)
    quality = build_gate_effectiveness_quality(rows)
    assert quality["snapshots"] == 0
    assert quality["conflicts"] == 2


def test_unique_legacy_collection_key_remains_compatible():
    assert list(collect([candidate()])) == ["signal"]
