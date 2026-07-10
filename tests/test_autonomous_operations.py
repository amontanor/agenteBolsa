from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.digest import build_lab_digest, format_lab_digest_text
from agente_bolsa.scheduler import (
    _run_post_market_measurement_pipeline,
    scheduler_status,
    weekly_learning_review_job,
)
from agente_bolsa.storage import Store
from agente_bolsa.tools.autonomous_research import build_autonomous_research_report
from agente_bolsa.tools.operational_health import build_production_health_report


def _settings(tmp_path):
    return Settings(DATA_DIR=tmp_path, CONTINUOUS_IMPROVEMENT_RUNTIME_INTERVAL_SECONDS=60)


def _store(settings):
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def _observation(observation_id, *, strategy, source, value, matured=True, blocked=False):
    return {
        "observation_id": observation_id,
        "signal_date": "2026-07-08",
        "symbol": observation_id[-3:],
        "source_family": "learning_experiment",
        "decision": "blocked_backtest" if blocked else "approved_buy",
        "blocked_backtest": blocked,
        "executed_buy": not blocked,
        "features": {
            "setup": strategy,
            "regime": "bull",
            "decision_lineage": {
                "strategy_name": strategy,
                "decision_source": source,
                "low_sample_exploration": source == "capacity_fill",
            },
        },
        "outcome": {
            "return_5d": value,
            "matured_horizons": {"5d": matured},
        },
    }


def test_autonomous_research_uses_only_mature_forward_returns(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    store.upsert_learning_observation(
        _observation("obs_breakout_AAA", strategy="builtin_breakout", source="llm", value=0.02)
    )
    store.upsert_learning_observation(
        _observation("obs_blocked_BBB", strategy="builtin_pullback", source="deterministic", value=-0.03, blocked=True)
    )
    store.upsert_learning_observation(
        _observation("obs_immature_CCC", strategy="builtin_breakout", source="capacity_fill", value=0.50, matured=False)
    )

    report = build_autonomous_research_report(store, tmp_path / "reports", "research_test", end_date="2026-07-10")

    breakout = next(item for item in report["strategy_edge"]["items"] if item["group"] == "builtin_breakout")
    assert breakout["n_5d"] == 1
    assert breakout["expectancy_5d_net_10bps"] == 0.019
    assert report["gate_effectiveness"]["losses_avoided"] == 1
    assert report["excursion_and_exits"]["status"] == "unavailable"
    assert report["pullback_promotion_gate"]["eligible"] is False
    assert report["pullback_promotion_gate"]["action"] == "keep_shadow"
    assert report["policy_frozen"] is True


def test_post_market_measurement_pipeline_publishes_sequence(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    store = _store(settings)
    monkeypatch.setattr(
        "agente_bolsa.scheduler.build_learning_scoreboard",
        lambda *args, **kwargs: {
            "path": "scoreboard.json",
            "evaluation": {"status": "pending_maturity"},
            "lineage_coverage": {"pct": 1.0},
            "control_coverage": {"pct": 0.9},
        },
    )
    monkeypatch.setattr(
        "agente_bolsa.scheduler.build_autonomous_research_report",
        lambda *args, **kwargs: {"path": "research.json", "sample": {"matured_5d": 0}},
    )
    monkeypatch.setattr(
        "agente_bolsa.scheduler.build_lab_digest",
        lambda *args, **kwargs: {
            "days": 1,
            "generated_at": "2026-07-10T00:00:00+00:00",
            "director_brief": {
                "decision_requested": {"required": False, "question": "Mantener politica."}
            },
        },
    )
    monkeypatch.setattr("agente_bolsa.scheduler.format_lab_digest_text", lambda _digest: "digest\n")

    report = _run_post_market_measurement_pipeline(
        settings,
        store,
        session_date="2026-07-10",
        run_id="pipeline_test",
    )

    assert report["sequence"] == [
        "broker_reconciliation",
        "market_forward_outcomes",
        "learning_observations_and_lineage",
        "learning_scoreboard",
        "autonomous_research",
        "continuous_improvement_digest",
    ]
    assert (tmp_path / "reports" / "latest_continuous_improvement_digest.md").read_text(encoding="utf-8") == "digest\n"


def test_weekly_review_is_idempotent_and_visible_in_scheduler(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    store = _store(settings)
    monkeypatch.setattr(
        "agente_bolsa.scheduler._run_post_market_measurement_pipeline",
        lambda *args, **kwargs: {
            "path": "weekly.json",
            "digest": {"decision_requested": {"required": False}},
        },
    )

    first = weekly_learning_review_job(settings, store, verbose=False, force=True)
    second = weekly_learning_review_job(settings, store, verbose=False)
    status = scheduler_status(settings)

    assert first is not None
    assert second is None
    assert "weekly_learning_review" in {item["id"] for item in status["jobs"]}
    assert status["job_runtime"]["weekly_learning_review"]["status"] == "skipped"


def test_digest_has_exactly_one_director_decision(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    reports = tmp_path / "reports"
    reports.mkdir(parents=True)
    (reports / "latest_learning_scoreboard.json").write_text(
        json.dumps(
            {
                "evaluation": {"status": "pending_maturity"},
                "lineage_coverage": {"pct": 1.0},
                "control_coverage": {"pct": 0.9},
                "maturity_by_horizon": {"5d": {"executed": 0}},
            }
        ),
        encoding="utf-8",
    )

    digest = build_lab_digest(store, data_dir=tmp_path)
    text = format_lab_digest_text(digest)

    assert set(digest["director_brief"]["decision_requested"]) >= {"required", "kind", "question"}
    assert digest["llm_decision_quality"]["summary"]["status"] == "unavailable"
    assert "- LLM decision:" in text
    assert text.count("- decision solicitada:") == 1


def test_digest_includes_actionable_market_data_quality(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    reports = tmp_path / "reports"
    reports.mkdir(parents=True)
    (reports / "latest_market_data_quality.json").write_text(
        json.dumps(
            {
                "summary": {"coverage_ratio": 1.0, "real_blockers": 1, "anomalies_unique": 2},
                "required_action": "Revisar las anomalías bloqueantes antes del siguiente escaneo operativo.",
            }
        ),
        encoding="utf-8",
    )

    digest = build_lab_digest(store, data_dir=tmp_path)
    text = format_lab_digest_text(digest)

    assert digest["director_brief"]["market_data_quality"] == {
        "status": "available",
        "coverage": 1.0,
        "real_blockers": 1,
        "anomalies_unique": 2,
        "required_action": "Revisar las anomalías bloqueantes antes del siguiente escaneo operativo.",
    }
    assert "market-data-quality: cobertura=1.0 | bloqueos_reales=1 | anomalías_únicas=2" in text


def test_production_health_tracks_ttl_coherence_fallback_and_overlap(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    now = datetime.now(timezone.utc)
    reports = tmp_path / "reports"
    reports.mkdir(parents=True)
    (reports / "latest_market_data_quality.json").write_text(
        json.dumps({"as_of": now.isoformat()}), encoding="utf-8"
    )
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    (settings.state_dir / "scheduler.lock").write_text(
        json.dumps({"pid": os.getpid(), "kind": "scheduler"}), encoding="utf-8"
    )
    for job, start, end in (
        ("post_market_review", "20:00:00", "20:10:00"),
        ("market_cycle", "20:05:00", "20:06:00"),
    ):
        store.set_runtime_value(
            f"scheduler_job_status:{job}",
            {
                "status": "completed",
                "started_at": f"{now.date().isoformat()}T{start}+00:00",
                "finished_at": f"{now.date().isoformat()}T{end}+00:00",
                "duration_seconds": 600 if job == "post_market_review" else 60,
            },
        )
    store.record_llm_usage(
        usage_id="real",
        source="trade_decision",
        model="test",
        request_count=1,
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        payload={"fallback_used": False},
    )
    store.record_llm_usage(
        usage_id="fallback",
        source="trade_decision_fallback",
        model="test",
        request_count=2,
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        payload={"fallback_used": True},
    )
    for recommendation_id, source in (
        ("rec_real", "llm"),
        ("rec_fallback_1", "deterministic_fallback"),
        ("rec_fallback_2", "deterministic_capacity_fill"),
    ):
        store.save_trade_recommendation(
            recommendation_id=recommendation_id,
            cycle_id="cycle_health",
            symbol="AAPL",
            action="hold",
            confidence=0.5,
            payload={"source": source},
        )

    report = build_production_health_report(settings, store, reports, "health_test")

    assert report["market_data_quality"]["max_age_seconds"] == 26 * 60 * 60
    assert report["scheduler_coherence"]["coherent"] is True
    assert report["llm_quality"]["basis"] == "trade_recommendations"
    assert report["llm_quality"]["fallback_ratio"] == 0.6667
    assert report["llm_quality"]["fallback_reasons"] == {"unknown": 2}
    assert report["llm_decision_quality"]["summary"]["fallback_decisions"] == 2
    assert report["post_market_runtime"]["overlapping_jobs"] == ["market_cycle"]


def test_production_health_marks_market_data_quality_stale_after_26_hours(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    reports = tmp_path / "reports"
    reports.mkdir(parents=True)
    stale = datetime(2020, 1, 1, tzinfo=timezone.utc)
    (reports / "latest_market_data_quality.json").write_text(
        json.dumps({"as_of": stale.isoformat()}), encoding="utf-8"
    )

    report = build_production_health_report(settings, store, reports, "health_stale")

    assert report["market_data_quality"]["is_fresh"] is False
    assert "market_data_quality_stale" in {item["kind"] for item in report["alerts"]}
