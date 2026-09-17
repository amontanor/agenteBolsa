"""P-L123 caracterizacion: dedupe de lecciones y cuadro de mejora diaria (rojo)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agente_bolsa.continuous_improvement.lesson_distiller import dedupe_lessons, relevant_lessons
from agente_bolsa.tools.improvement_dashboard import build_improvement_dashboard


def _setup(tmp_path):
    from agente_bolsa.config import Settings
    from agente_bolsa.storage import Store

    settings = Settings(DATA_DIR=tmp_path)
    settings.ensure_runtime_dirs()
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return settings, store


def _now():
    return datetime.now(timezone.utc)


def _lesson(lesson_id, statement, status, validated_days_ago):
    agg = {"n": 100, "decided": 80, "winners": 60}
    return {
        "lesson_id": lesson_id,
        "scope": "setup",
        "statement": statement,
        "supporting_cases": 60,
        "contradicting_cases": 20,
        "confidence": 0.75,
        "status": status,
        "last_validated_at": (_now() - timedelta(days=validated_days_ago)).isoformat(),
        "source_refs": {"setup": "breakout", "aggregate": agg},
    }


def test_dedupe_retires_semantic_duplicates_and_keeps_newest(tmp_path):
    settings, store = _setup(tmp_path)
    store.upsert_distilled_lesson(_lesson("L_EN", "Strong setup wins often", "ACTIVE", 2))
    store.upsert_distilled_lesson(_lesson("L_ES", "El setup strong gana a menudo", "ACTIVE", 1))
    result = dedupe_lessons(store)
    assert result["retired"] == ["L_EN"]
    assert result["kept"] == ["L_ES"]
    by_id = {row["lesson_id"]: row for row in store.distilled_lessons(limit=10)}
    assert by_id["L_EN"]["status"] == "RETIRED"
    assert by_id["L_EN"]["source_refs"]["duplicate_of"] == "L_ES"
    assert by_id["L_ES"]["status"] == "ACTIVE"


def test_relevant_requires_fresh_evidence_and_skips_duplicates(tmp_path):
    settings, store = _setup(tmp_path)
    store.upsert_distilled_lesson(_lesson("L_FRESH", "Fresh evidence lesson", "ACTIVE", 1))
    store.upsert_distilled_lesson(_lesson("L_STALE", "Stale evidence lesson", "ACTIVE", 30))
    store.upsert_distilled_lesson(_lesson("L_DUP", "Dup marked lesson", "ACTIVE", 1))
    dup = {row["lesson_id"]: row for row in store.distilled_lessons(limit=10)}["L_DUP"]
    store.upsert_distilled_lesson({**dup, "source_refs": {**dup["source_refs"], "duplicate_of": "L_FRESH"}})
    got = relevant_lessons(store, k=10)
    ids = [item["lesson_id"] for item in got]
    assert "L_FRESH" in ids
    assert "L_STALE" not in ids
    assert "L_DUP" not in ids


def test_dashboard_answers_three_questions_with_verdict(tmp_path):
    settings, store = _setup(tmp_path)
    today = _now().date().isoformat()
    store.upsert_performance_daily({
        "session_date": "2026-09-16", "iq_score": 40.0, "equity": 71000.0,
        "pnl_pct": 0.001, "alpha": None,
    })
    dashboard = build_improvement_dashboard(store, settings, today=today)
    assert dashboard["verdict"] in {"SI", "NO"}
    assert dashboard["system_vs_spy"]["equity"] == 71000.0
    assert dashboard["system_vs_spy"]["provisional"] is True
    assert "coverage" in dashboard["system_vs_spy"]
    assert dashboard["daily_learning"]["observations_today"] == 0
    assert dashboard["real_improvement"]["applied_total"] == 0
    assert dashboard["verdict"] == "NO"
    assert "RESULTADO" in dashboard["markdown"]
    assert "PROCESO" in dashboard["markdown"]
