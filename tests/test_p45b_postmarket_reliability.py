from __future__ import annotations

import json
import threading
from pathlib import Path

from agente_bolsa import scheduler
from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools import daily_learning, post_market_review
from agente_bolsa.tools.postmarket_coordination import PostmarketCoordinator


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        DATA_DIR=tmp_path / "data",
        DATABASE_PATH=tmp_path / "data" / "state" / "test.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "data" / "logs" / "agents",
        TRADING_MODE="paper",
        ALLOW_LIVE_TRADING=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )


def _events(store: Store, *, event_type: str = "postmarket_run") -> list[dict]:
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT event_id, event_type, payload_json FROM agent_events WHERE event_type = ? ORDER BY created_at",
            (event_type,),
        ).fetchall()
    return [dict(row) for row in rows]


def test_two_postmarket_triggers_one_effective_and_terminal(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    first = PostmarketCoordinator(settings, store).acquire(
        session_date="2026-07-15", run_id="pmr-a", trigger="bootstrap"
    )
    second = PostmarketCoordinator(settings, store).acquire(
        session_date="2026-07-15", run_id="pmr-b", trigger="scheduled"
    )
    assert first.effective is True
    assert second.effective is False
    assert second.reason == "postmarket_already_running"
    PostmarketCoordinator(settings, store).terminal(first, "completed", reason="test_completed")
    payloads = [json.loads(row["payload_json"]) for row in _events(store)]
    assert sum(item["stage"] == "terminal" and item["status"] == "completed" for item in payloads) == 1
    assert sum(item["stage"] == "terminal" and item["status"] == "skipped" for item in payloads) == 1


def test_completed_session_is_durable_skip(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.set_runtime_value("post_market_review_last_session", "2026-07-15")
    lease = PostmarketCoordinator(settings, store).acquire(
        session_date="2026-07-15", run_id="pmr-retry", trigger="scheduled"
    )
    assert lease.effective is False
    assert lease.reason == "session_already_completed"
    assert any(json.loads(row["payload_json"])["status"] == "skipped" for row in _events(store))


def test_reconciliation_is_deferred_while_postmarket_active(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    pmr = PostmarketCoordinator(settings, store).acquire(
        session_date="2026-07-15", run_id="pmr-owner", trigger="scheduled"
    )
    recon = PostmarketCoordinator(settings, store).acquire_reconciliation(
        session_date="2026-07-15", run_id="recon-1"
    )
    assert pmr.effective is True
    assert recon.effective is False
    assert recon.reason == "postmarket_already_running"
    PostmarketCoordinator(settings, store).terminal(pmr, "failed", reason="test_failure")


def test_two_reconciliations_have_one_owner(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    first = PostmarketCoordinator(settings, store).acquire_reconciliation(
        session_date="2026-07-15", run_id="recon-a"
    )
    second = PostmarketCoordinator(settings, store).acquire_reconciliation(
        session_date="2026-07-15", run_id="recon-b"
    )
    assert first.effective is True
    assert second.effective is False
    assert second.reason == "reconciliation_already_running"
    PostmarketCoordinator(settings, store).finish_reconciliation(first, "completed")


def test_dead_owner_is_recovered_with_failed_terminal(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.set_runtime_value(
        "post_market_coordination:active",
        {
            "status": "active",
            "session_date": "2026-07-15",
            "run_id": "pmr-dead",
            "trigger": "scheduled",
            "owner_pid": 999999,
            "owner_token": "dead",
            "started_at": "2026-07-15T20:00:00+00:00",
        },
    )
    lease = PostmarketCoordinator(settings, store).acquire(
        session_date="2026-07-15", run_id="pmr-recovered", trigger="bootstrap"
    )
    assert lease.effective is True
    payloads = [json.loads(row["payload_json"]) for row in _events(store)]
    assert any(item["run_id"] == "pmr-dead" and item["status"] == "failed" for item in payloads)


def test_dead_reconciliation_owner_is_recovered(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.set_runtime_value(
        "post_market_coordination:reconciliation",
        {
            "status": "active",
            "session_date": "2026-07-15",
            "run_id": "recon-dead",
            "trigger": "scheduled",
            "owner_pid": 999999,
            "owner_token": "dead",
            "started_at": "2026-07-15T20:00:00+00:00",
        },
    )
    lease = PostmarketCoordinator(settings, store).acquire_reconciliation(
        session_date="2026-07-15", run_id="recon-recovered"
    )
    assert lease.effective is True
    payloads = [json.loads(row["payload_json"]) for row in _events(store)]
    assert any(item["run_id"] == "recon-dead" and item["status"] == "failed" for item in payloads)


def test_event_idempotence_and_conflict_are_append_only(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    payload = {"schema_version": "p-l45b1.postmarket-run.v1", "status": "completed", "content_hash": "h1"}
    assert store.record_append_only_event(event_id="pmr:e", event_type="postmarket_run", cycle_id="pmr:e", payload=payload)["status"] == "inserted"
    assert store.record_append_only_event(event_id="pmr:e", event_type="postmarket_run", cycle_id="pmr:e", payload=payload)["status"] == "idempotent"
    conflict = {**payload, "status": "failed", "content_hash": "h2"}
    assert store.record_append_only_event(event_id="pmr:e", event_type="postmarket_run", cycle_id="pmr:e", payload=conflict)["status"] == "conflict"
    with store.connect() as conn:
        row = conn.execute("SELECT payload_json FROM agent_events WHERE event_id = 'pmr:e'").fetchone()
    assert json.loads(row["payload_json"])["status"] == "completed"


def test_concurrent_same_observation_has_one_canonical_event(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    Store(settings.database_path, settings.agent_logs_dir).ensure_schema()
    payload = {"schema_version": "p-l45b1.postmarket-run.v1", "status": "completed", "content_hash": "same"}
    results: list[str] = []
    barrier = threading.Barrier(2)

    def writer() -> None:
        local = Store(settings.database_path, settings.agent_logs_dir)
        barrier.wait()
        results.append(local.record_append_only_event(event_id="pmr:race", event_type="postmarket_run", cycle_id="pmr:race", payload=payload)["status"])

    threads = [threading.Thread(target=writer) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["idempotent", "inserted"]
    with Store(settings.database_path, settings.agent_logs_dir).connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_events WHERE event_id = 'pmr:race'").fetchone()[0] == 1


def test_learning_pipeline_passes_one_outcome_result(monkeypatch, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    calls: list[dict] = []
    result = {"updated": 3, "signals": 3}
    monkeypatch.setattr(post_market_review, "update_signal_outcomes", lambda *args, **kwargs: result)
    monkeypatch.setattr(post_market_review, "build_learning_status", lambda *args, **kwargs: {"status": "ok"})

    def daily(*args, **kwargs):
        calls.append(kwargs["update_result"])
        return {"path": None, "health": {}, "digest": {}, "policy_candidates": []}

    monkeypatch.setattr(post_market_review, "build_learning_daily_run", daily)
    update, _, _ = post_market_review._build_learning_pipeline(
        settings, store, tmp_path / "reports", "pmr-one", "2026-07-15"
    )
    assert update is result
    assert calls == [result]


def test_daily_learning_without_argument_keeps_legacy_call(monkeypatch, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    marker = {"updated": 1}
    monkeypatch.setattr(daily_learning, "update_signal_outcomes", lambda *args, **kwargs: marker)
    monkeypatch.setattr(daily_learning, "_rebuild_signal_cohorts", lambda *args, **kwargs: [])
    monkeypatch.setattr(daily_learning, "_materialize_observations", lambda *args, **kwargs: [])
    monkeypatch.setattr(daily_learning, "sync_rr_cohort_observations", lambda *args, **kwargs: {})
    monkeypatch.setattr(daily_learning, "_session_dates", lambda *args, **kwargs: [])
    monkeypatch.setattr(daily_learning, "_build_health", lambda *args, **kwargs: {})
    monkeypatch.setattr(daily_learning, "_upsert_policy_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(daily_learning, "_llm_status_snapshot", lambda *args, **kwargs: {})
    monkeypatch.setattr(daily_learning, "load_pre_earnings_learning_context", lambda *args, **kwargs: {})
    monkeypatch.setattr(daily_learning, "_build_same_session_opportunity_ledger", lambda *args, **kwargs: {})
    monkeypatch.setattr(daily_learning, "_build_learning_experiment_section", lambda *args, **kwargs: {})
    monkeypatch.setattr(daily_learning, "_build_digest", lambda *args, **kwargs: {})
    monkeypatch.setattr(daily_learning, "rr_cohort_digest_summary", lambda *args, **kwargs: {})
    monkeypatch.setattr(daily_learning, "execution_quality_digest_summary", lambda *args, **kwargs: {})
    monkeypatch.setattr(daily_learning, "shadow_time_stop_digest_summary", lambda *args, **kwargs: {})
    output = daily_learning.build_learning_daily_run(settings, store, tmp_path / "reports", "legacy")
    assert output["update_result"] is marker


def test_postmarket_job_reuses_single_coordinator_and_internal_reconciliation(monkeypatch, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    calls: list[dict] = []

    class Status:
        now_market = "2026-07-15T23:00:00+00:00"

        def as_dict(self):
            return {"now_market": self.now_market}

    class Calendar:
        def __init__(self, *args, **kwargs):
            pass

        def should_run_daily_study(self):
            return True, Status()

    class Reporter:
        def emit(self, *args, **kwargs):
            return None

    class BrokerFactory:
        def __init__(self, *args, **kwargs):
            pass

        def alpaca_portfolio_snapshot(self):
            return None

    monkeypatch.setattr(scheduler, "MarketCalendar", Calendar)
    monkeypatch.setattr(scheduler, "_reporter", lambda *args, **kwargs: Reporter())
    monkeypatch.setattr(scheduler, "BrokerClientFactory", BrokerFactory)

    def reconcile(*args, **kwargs):
        calls.append(kwargs)
        return {"changes": [], "signal_execution_updates": 0, "learning_execution_updates": 0}

    monkeypatch.setattr(scheduler, "reconcile_broker_orders", reconcile)
    monkeypatch.setattr(
        scheduler,
        "build_post_market_review",
        lambda *args, **kwargs: {"path": "report.json", "summary": {"trades_evaluated": 0}, "proposed_improvements": [], "next_session_guidance": []},
    )
    monkeypatch.setattr(scheduler, "_persist_daily_performance", lambda *args, **kwargs: None)
    monkeypatch.setattr(scheduler, "_run_post_market_measurement_pipeline", lambda *args, **kwargs: {"path": "measure.json"})
    monkeypatch.setattr(scheduler, "_run_change_watchdog", lambda *args, **kwargs: None)
    monkeypatch.setattr(scheduler, "_run_macro_thesis", lambda *args, **kwargs: None)
    monkeypatch.setattr(scheduler, "_run_nightly_retrospective", lambda *args, **kwargs: None)
    monkeypatch.setattr(scheduler, "_run_hypothesis_factory", lambda *args, **kwargs: None)
    monkeypatch.setattr(scheduler, "_set_job_status", lambda *args, **kwargs: None)
    first = scheduler.post_market_review_job(settings, store, use_llm=False, verbose=False, force=True, trigger="bootstrap")
    second = scheduler.post_market_review_job(settings, store, use_llm=False, verbose=False, force=True, trigger="scheduled")
    assert first is not None
    assert second is None
    assert len(calls) == 1
    assert calls[0]["update_learning"] is False
