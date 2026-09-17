from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apscheduler.events import EVENT_JOB_MAX_INSTANCES, EVENT_JOB_MISSED
from apscheduler.events import JobExecutionEvent, JobSubmissionEvent

from agente_bolsa import scheduler
from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.operational_health import (
    build_production_health_report,
    scheduler_skip_summary,
    signal_outcome_emptiness,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        DATA_DIR=tmp_path,
        DATABASE_PATH=tmp_path / "state" / "test.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "logs" / "agents",
        ALLOW_LIVE_TRADING=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )


def _skip_payloads(store: Store) -> list[dict]:
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT payload_json FROM agent_events WHERE event_type = 'scheduler_job_skipped'"
        ).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]


def test_missed_event_persists_delay_seconds(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    scheduled = datetime.now(timezone.utc) - timedelta(seconds=13)
    event = JobExecutionEvent(EVENT_JOB_MISSED, "market_cycle_15m", "default", scheduled)

    scheduler._persist_scheduler_control_event(settings, store, event)

    (payload,) = _skip_payloads(store)
    assert payload["reason"] == "missed"
    assert payload["job_id"] == "market_cycle_15m"
    assert payload["delay_seconds"] is not None
    assert 10.0 <= float(payload["delay_seconds"]) <= 20.0


def test_unparseable_scheduled_time_yields_null_delay(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()

    class _BadEvent:
        code = EVENT_JOB_MISSED
        job_id = "portfolio_watch_1m"
        scheduled_run_times = None
        scheduled_run_time = "not-a-date"

    scheduler._persist_scheduler_control_event(settings, store, _BadEvent())

    (payload,) = _skip_payloads(store)
    assert payload["delay_seconds"] is None
    assert payload["status"] == "skipped"


def test_skip_summary_aggregates_per_job(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    base = datetime.now(timezone.utc)
    scheduler._persist_scheduler_control_event(
        settings, store,
        JobExecutionEvent(EVENT_JOB_MISSED, "job_a", "default", base - timedelta(seconds=5)),
    )
    scheduler._persist_scheduler_control_event(
        settings, store,
        JobSubmissionEvent(
            EVENT_JOB_MAX_INSTANCES, "job_a", "default", [base - timedelta(seconds=2)]
        ),
    )
    scheduler._persist_scheduler_control_event(
        settings, store,
        JobExecutionEvent(EVENT_JOB_MISSED, "job_b", "default", base - timedelta(seconds=9)),
    )

    summary = scheduler_skip_summary(store)

    assert summary["total"] == 3
    assert summary["jobs"]["job_a"]["missed"] == 1
    assert summary["jobs"]["job_a"]["max_instances"] == 1
    assert summary["jobs"]["job_b"]["missed"] == 1
    assert summary["jobs"]["job_b"]["max_delay_seconds"] is not None
    assert summary["jobs"]["job_b"]["max_delay_seconds"] >= 5.0


def _save_outcome(store: Store, signal_id: str, *, outcome: dict | None) -> None:
    store.save_signal_outcome(
        signal_id=signal_id,
        source_run_id="run-1",
        source="test",
        symbol="AAA",
        signal_date="2026-09-01",
        decision="executed_buy",
        features={},
        gate={},
        outcome=outcome,
    )


def test_outcome_emptiness_reports_pct(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    _save_outcome(store, "sig-1", outcome=None)
    _save_outcome(store, "sig-2", outcome={})
    _save_outcome(store, "sig-3", outcome={"return_5d": 0.01})

    result = signal_outcome_emptiness(store)

    assert result["total"] == 3
    assert result["empty"] == 2
    assert result["pct_empty"] == round(2 / 3, 4)


def test_outcome_emptiness_empty_store(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()

    result = signal_outcome_emptiness(store)

    assert result == {"total": 0, "empty": 0, "pct_empty": None}


def test_production_health_includes_skip_and_emptiness_fail_open(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    report = build_production_health_report(settings, store, reports_dir, "p133")

    assert report["summary"]["scheduler_skips"]["total"] == 0
    assert report["summary"]["outcome_emptiness"] == {"total": 0, "empty": 0, "pct_empty": None}


def test_production_health_sections_degrade_to_unavailable(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(store, "agent_events", _boom)
    monkeypatch.setattr(store, "signal_outcomes", _boom)

    report = build_production_health_report(settings, store, reports_dir, "p133")

    assert report["summary"]["scheduler_skips"]["status"] == "unavailable"
    assert report["summary"]["outcome_emptiness"]["status"] == "unavailable"
