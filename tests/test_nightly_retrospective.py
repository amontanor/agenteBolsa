"""Tests de la retrospectiva generativa nocturna (T2.3)."""

import json

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.nightly_retrospective import (
    collect_evidence,
    generate_hypotheses,
    run_nightly_retrospective,
)


def _setup(tmp_path):
    settings = Settings(DATA_DIR=tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return settings, store


def _seed(store, signal_id, decision, verdict, date="2026-06-10"):
    store.save_signal_outcome(
        signal_id=signal_id,
        source_run_id="run",
        source="test",
        symbol="AAA",
        signal_date=date,
        decision=decision,
        features={"setup": "breakout"},
        gate={},
        outcome={"verdict": verdict},
    )


def _llm_two_hypotheses(messages):
    return json.dumps(
        {
            "hypotheses": [
                {
                    "pattern_description": "buy breakout tras pullback con volumen",
                    "entry_rule": "close > high_20",
                    "exit_rule": "atr_stop_2x",
                    "invalidation": "perder soporte",
                    "expected_improvement": "+5% hit rate",
                    "evidence_refs": ["s1", "s2", "s3"],
                },
                {
                    "pattern_description": "hipotesis sin evidencia",
                    "entry_rule": "x",
                    "evidence_refs": ["s1"],
                },
            ]
        }
    )


def test_collect_evidence_separates_losses_and_misses(tmp_path):
    settings, store = _setup(tmp_path)
    _seed(store, "s1", "buy", "loser")
    _seed(store, "s2", "hold", "winner_fast")
    _seed(store, "s3", "buy", "winner_fast")

    evidence = collect_evidence(store, settings, "2026-06-10")
    assert evidence["counts"]["losses"] == 1
    assert evidence["counts"]["misses"] == 1


def test_generate_hypotheses_filters_low_evidence(tmp_path):
    settings, store = _setup(tmp_path)
    _seed(store, "s1", "buy", "loser")
    _seed(store, "s2", "hold", "winner_fast")
    evidence = collect_evidence(store, settings, "2026-06-10")

    hypotheses = generate_hypotheses(evidence, settings, llm=_llm_two_hypotheses)
    assert len(hypotheses) == 1  # la de 1 ref se descarta


def test_run_nightly_retrospective_inserts_and_dedups(tmp_path):
    settings, store = _setup(tmp_path)
    _seed(store, "s1", "buy", "loser")
    _seed(store, "s2", "hold", "winner_fast")

    first = run_nightly_retrospective(store, settings, "2026-06-10", llm=_llm_two_hypotheses)
    assert first["hypotheses_inserted"] == 1
    second = run_nightly_retrospective(store, settings, "2026-06-10", llm=_llm_two_hypotheses)
    assert second["hypotheses_inserted"] == 0  # dedup por fingerprint


def test_day_without_activity_generates_nothing(tmp_path):
    settings, store = _setup(tmp_path)
    result = run_nightly_retrospective(store, settings, "2026-06-10", llm=_llm_two_hypotheses)
    assert result["hypotheses_inserted"] == 0
