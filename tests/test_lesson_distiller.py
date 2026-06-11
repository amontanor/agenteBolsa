"""Tests de la memoria destilada / lecciones (T2.4)."""

import json

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.lesson_distiller import (
    aggregate_by_setup,
    distill_lessons,
    promote_qualified_lessons,
    relevant_lessons,
    revalidate_lessons,
    wilson_interval,
)
from agente_bolsa.storage import Store


def _setup(tmp_path):
    settings = Settings(DATA_DIR=tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return settings, store


def _seed(store, setup, ret, winner, idx):
    store.save_signal_outcome(
        signal_id=f"{setup}_{idx}",
        source_run_id="run",
        source="test",
        symbol="AAA",
        signal_date="2026-06-10",
        decision="buy",
        features={"setup": setup},
        gate={},
        outcome={"verdict": "winner_fast" if winner else "loser", "return_pct": ret},
    )


def _seed_breakout_strong(store):
    for i in range(8):
        _seed(store, "breakout", 0.03, True, i)
    for i in range(2):
        _seed(store, "breakout", -0.02, False, 100 + i)


def _llm(messages):
    return json.dumps(
        {
            "lessons": [
                {"scope": "setup", "statement": "breakout con volumen funciona", "setup": "breakout"},
                {"scope": "setup", "statement": "inventado sin datos", "setup": "nonexistent"},
            ]
        }
    )


def test_aggregate_by_setup():
    outcomes = [
        {"features": {"setup": "breakout"}, "outcome": {"verdict": "winner_fast", "return_pct": 0.03}},
        {"features": {"setup": "breakout"}, "outcome": {"verdict": "loser", "return_pct": -0.02}},
        {"features": {"setup": "breakout"}, "outcome": {"verdict": "pending"}},
    ]
    agg = aggregate_by_setup(outcomes)
    assert agg["breakout"]["win_rate"] == 0.5
    assert agg["breakout"]["n"] == 2


def test_distill_discards_unsupported_lessons(tmp_path):
    settings, store = _setup(tmp_path)
    _seed_breakout_strong(store)
    result = distill_lessons(store, settings, llm=_llm)
    assert result["distilled"] == 1  # la 'inventada' se descarta
    lessons = store.distilled_lessons()
    assert lessons[0]["confidence"] == 0.8


def test_revalidate_weakens_then_retires(tmp_path):
    settings, store = _setup(tmp_path)
    _seed_breakout_strong(store)
    distill_lessons(store, settings, llm=_llm)

    # Borra outcomes y siembra un breakout debil (30% win).
    store2 = Store(settings.database_path, settings.agent_logs_dir)
    for i in range(3):
        _seed(store2, "breakout_weak_marker", 0.0, False, 900 + i)
    # Sobrescribe el historico relevante: nuevas señales breakout debiles.
    for i in range(3):
        _seed(store2, "breakout", 0.03, True, 200 + i)
    for i in range(7):
        _seed(store2, "breakout", -0.02, False, 300 + i)

    first = revalidate_lessons(store, settings)
    assert any(t["to"] in {"WEAKENED", "RETIRED"} for t in first["transitions"])
    revalidate_lessons(store, settings)
    statuses = {row["status"] for row in store.distilled_lessons()}
    assert "WEAKENED" in statuses or "RETIRED" in statuses


def test_distilled_lessons_start_as_hypothesis(tmp_path):
    settings, store = _setup(tmp_path)
    _seed_breakout_strong(store)
    distill_lessons(store, settings, llm=_llm)
    lessons = store.distilled_lessons()
    assert lessons[0]["status"] == "HYPOTHESIS"
    # No se inyectan al prompt hasta validarse (relevant_lessons filtra ACTIVE).
    assert relevant_lessons(store, setup="breakout", k=5) == []


def test_wilson_interval_bounds():
    lo, hi = wilson_interval(8, 10)
    assert 0.0 <= lo <= 0.8 <= hi <= 1.0
    lo2, _ = wilson_interval(45, 50)
    assert lo2 > 0.5  # 90% de 45/50 esta claramente por encima de 0.5


def test_promotion_requires_n_ci_and_confirmed_variant(tmp_path):
    settings, store = _setup(tmp_path)
    # Leccion con n alto y CI por encima de la base, pero variante sin confirmar.
    agg = {"decided": 50, "winners": 45}
    store.upsert_distilled_lesson(
        {
            "lesson_id": "L1", "scope": "setup", "statement": "x",
            "supporting_cases": 45, "contradicting_cases": 5, "confidence": 0.9, "status": "HYPOTHESIS",
            "source_refs": {"setup": "breakout", "aggregate": agg, "variant_confirmed": False},
        }
    )
    assert promote_qualified_lessons(store, settings)["promoted"] == []  # variante no confirmada

    store.upsert_distilled_lesson(
        {
            "lesson_id": "L1", "scope": "setup", "statement": "x",
            "supporting_cases": 45, "contradicting_cases": 5, "confidence": 0.9, "status": "HYPOTHESIS",
            "source_refs": {"setup": "breakout", "aggregate": agg, "variant_confirmed": True},
        }
    )
    assert "L1" in promote_qualified_lessons(store, settings)["promoted"]
    assert {r["status"] for r in store.distilled_lessons()} == {"ACTIVE"}


def test_promotion_rejects_small_sample(tmp_path):
    settings, store = _setup(tmp_path)
    agg = {"decided": 10, "winners": 8}
    store.upsert_distilled_lesson(
        {
            "lesson_id": "L2", "scope": "setup", "statement": "x",
            "supporting_cases": 8, "contradicting_cases": 2, "confidence": 0.8, "status": "HYPOTHESIS",
            "source_refs": {"setup": "breakout", "aggregate": agg, "variant_confirmed": True},
        }
    )
    assert promote_qualified_lessons(store, settings)["promoted"] == []  # n<30
