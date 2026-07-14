from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.digest import build_lab_digest, format_lab_digest_text
from agente_bolsa.scheduler import (
    _run_post_market_measurement_pipeline,
    scheduler_status,
    weekly_learning_review_job,
)
from agente_bolsa.storage import Store
from agente_bolsa.tools import operational_health
from agente_bolsa.tools.autonomous_research import build_autonomous_research_report
from agente_bolsa.tools.operational_health import build_production_health_report


def _settings(tmp_path):
    return Settings(
        _env_file=None,
        DATA_DIR=tmp_path,
        CONTINUOUS_IMPROVEMENT_RUNTIME_INTERVAL_SECONDS=60,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
        TRADING_MODE="paper",
        ALLOW_LIVE_TRADING=False,
    )


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
        "agente_bolsa.scheduler.write_rr_cohort_report",
        lambda *args, **kwargs: {"path": "rr_cohort.json", "overall_status": "collecting"},
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
            "gate_effectiveness_quality",
            "learning_scoreboard",
        "rr_cohort",
        "autonomous_research",
        "continuous_improvement_digest",
    ]
    assert (tmp_path / "reports" / "latest_continuous_improvement_digest.md").read_text(encoding="utf-8") == "digest\n"


def test_post_market_rr_cohort_failure_is_tolerated(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    store = _store(settings)
    monkeypatch.setattr("agente_bolsa.scheduler.build_learning_scoreboard", lambda *args, **kwargs: {"path": "score", "evaluation": {}, "lineage_coverage": {}, "control_coverage": {}})
    monkeypatch.setattr("agente_bolsa.scheduler.build_autonomous_research_report", lambda *args, **kwargs: {"path": "research", "sample": {}})
    monkeypatch.setattr("agente_bolsa.scheduler.build_lab_digest", lambda *args, **kwargs: {"director_brief": {"decision_requested": {}}})
    monkeypatch.setattr("agente_bolsa.scheduler.format_lab_digest_text", lambda *_args: "digest\n")
    monkeypatch.setattr("agente_bolsa.scheduler.write_rr_cohort_report", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("observability failed")))

    report = _run_post_market_measurement_pipeline(settings, store, session_date="2026-07-10", run_id="rr_failure")

    assert report["rr_cohort"]["status"] == "failed"


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


def test_production_health_tracks_ttl_coherence_fallback_and_overlap(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    store = _store(settings)
    now = datetime(2026, 7, 14, 22, 0, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = now
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    monkeypatch.setattr(operational_health, "datetime", FrozenDateTime)
    monkeypatch.setattr(operational_health, "_pid_running", lambda pid: pid == 1234)
    reports = tmp_path / "reports"
    reports.mkdir(parents=True)
    (reports / "latest_market_data_quality.json").write_text(
        json.dumps({"as_of": now.isoformat()}), encoding="utf-8"
    )
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    (settings.state_dir / "scheduler.lock").write_text(
        json.dumps({"pid": 1234, "kind": "scheduler"}), encoding="utf-8"
    )
    post_start = now - timedelta(minutes=10)
    post_end = now - timedelta(minutes=5)
    cycle_start = now - timedelta(minutes=8)
    cycle_end = now - timedelta(minutes=7)
    for job, start, end, duration in (
        ("post_market_review", post_start, post_end, 300),
        ("market_cycle", cycle_start, cycle_end, 60),
    ):
        store.set_runtime_value(
            f"scheduler_job_status:{job}",
            {
                "status": "completed",
                "started_at": start.isoformat(),
                "finished_at": end.isoformat(),
                "duration_seconds": duration,
            },
        )
    (reports / "latest_post_market_learning.json").write_text(
        json.dumps(
            {
                "session_date": "2026-07-14",
                "pipeline_steps": {"learning_pipeline_seconds": 42.0},
            }
        ),
        encoding="utf-8",
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
    assert report["scheduler_heartbeat"]["is_fresh"] is True
    assert report["llm_quality"]["basis"] == "trade_recommendations"
    assert report["llm_quality"]["fallback_ratio"] == 0.6667
    assert report["llm_quality"]["fallback_reasons"] == {"unknown": 2}
    assert report["llm_decision_quality"]["summary"]["fallback_decisions"] == 2
    assert report["post_market_runtime"]["overlapping_jobs"] == ["market_cycle"]
    assert report["post_market_runtime"]["reported_pipeline_duration_seconds"] == 42.0

    # Un solapamiento cero debe seguir siendo medido como cero, no unavailable.
    store.set_runtime_value(
        "scheduler_job_status:market_cycle",
        {
            "status": "completed",
            "started_at": (now - timedelta(minutes=3)).isoformat(),
            "finished_at": (now - timedelta(minutes=2)).isoformat(),
            "duration_seconds": 60,
        },
    )
    no_overlap = build_production_health_report(settings, store, reports, "health-no-overlap")
    assert no_overlap["post_market_runtime"]["overlap_count"] == 0
    assert no_overlap["post_market_runtime"]["overlap_status"] == "measured"

    # TTL fuera de límite y PID/lock incoherentes se diagnostican por separado.
    store.set_runtime_value(
        "scheduler_job_status:post_market_review",
        {
            "status": "completed",
            "started_at": (now - timedelta(hours=2, minutes=10)).isoformat(),
            "finished_at": (now - timedelta(hours=2)).isoformat(),
            "duration_seconds": 600,
        },
    )
    store.set_runtime_value(
        "scheduler_job_status:market_cycle",
        {
            "status": "completed",
            "started_at": (now - timedelta(hours=2, minutes=8)).isoformat(),
            "finished_at": (now - timedelta(hours=2, minutes=7)).isoformat(),
            "duration_seconds": 60,
        },
    )
    (reports / "latest_market_data_quality.json").write_text(
        json.dumps({"as_of": (now - timedelta(hours=27)).isoformat()}), encoding="utf-8"
    )
    (settings.state_dir / "scheduler.lock").write_text(
        json.dumps({"pid": 9999, "kind": "scheduler"}), encoding="utf-8"
    )
    stale = build_production_health_report(settings, store, reports, "health-stale")
    assert stale["market_data_quality"]["is_fresh"] is False
    assert stale["scheduler_heartbeat"]["is_fresh"] is False
    assert stale["scheduler_coherence"]["pid_alive"] is False
    assert stale["scheduler_coherence"]["heartbeat_fresh"] is False
    assert stale["scheduler_coherence"]["coherent"] is False


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
