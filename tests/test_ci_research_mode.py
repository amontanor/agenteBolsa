import json

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.digest import build_lab_digest, format_lab_digest_text
from agente_bolsa.continuous_improvement.research_mode import load_ci_research_mode_config
from agente_bolsa.continuous_improvement.runtime import ContinuousImprovementLabRuntime
from agente_bolsa.storage import Store


def _settings(tmp_path, **overrides):
    values = {
        "DATA_DIR": tmp_path,
        "CONTINUOUS_IMPROVEMENT_ENABLED": True,
        "IMPROVEMENT_LLM_ENABLED": False,
        "IMPROVEMENT_DRY_RUN": True,
        "ALLOW_AUTO_APPLY_IMPROVEMENTS": False,
        "ALLOW_LIVE_TRADING": False,
        "CONTINUOUS_IMPROVEMENT_GROUP_COOLDOWN_SECONDS": 0,
        "CONTINUOUS_IMPROVEMENT_EVENT_COOLDOWN_SECONDS": 0,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _closed_market_window():
    return (False, "Mercado cerrado para test.", {"is_open": False})


def _write_research_config(tmp_path, *, enabled: bool) -> None:
    config_path = tmp_path / "config" / "ci_research_mode.json"
    config = load_ci_research_mode_config(config_path)
    config["enabled"] = enabled
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def test_closed_market_research_mode_off_keeps_market_blocked(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    _write_research_config(tmp_path, enabled=False)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    runtime = ContinuousImprovementLabRuntime(settings, store)
    monkeypatch.setattr(runtime, "_market_window", _closed_market_window)

    result = runtime.run_once(mode="scheduled")

    assert result["status"] == "MARKET_BLOCKED"
    assert store.continuous_improvement_cycles(limit=10) == []


def test_closed_market_research_mode_on_runs_research_cycle(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    _write_research_config(tmp_path, enabled=True)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    runtime = ContinuousImprovementLabRuntime(settings, store)
    monkeypatch.setattr(runtime, "_market_window", _closed_market_window)

    result = runtime.run_once(mode="scheduled")

    assert result["mode"] == "research"
    assert result["status"] in {"COMPLETED", "PARTIAL"}
    runtime_state = store.continuous_improvement_runtime_state("lab")
    assert (runtime_state["payload"] or {}).get("status") in {"COMPLETED", "PARTIAL"}


def test_research_mode_blocks_trading_events_before_task_execution(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    _write_research_config(tmp_path, enabled=True)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    runtime = ContinuousImprovementLabRuntime(settings, store)
    monkeypatch.setattr(runtime, "_market_window", _closed_market_window)
    runtime.enqueue_event(
        event_type="latest_daily_learning_digest",
        source="test",
        domain="trading-improvement",
        payload={"path": "data/reports/latest_daily_learning_digest.json"},
        force_unique=True,
    )
    original_create = runtime.orchestrator.create_tasks_for_event

    def _spy_create_tasks(*, cycle_id, event, context):
        assert event["domain"] != "trading-improvement"
        return original_create(cycle_id=cycle_id, event=event, context=context)

    monkeypatch.setattr(runtime.orchestrator, "create_tasks_for_event", _spy_create_tasks)

    runtime.run_once(mode="scheduled")

    trading_events = [
        item
        for item in store.continuous_improvement_events(limit=20)
        if item["domain"] == "trading-improvement"
    ]
    assert trading_events
    assert all(item["status"] == "CANCELLED" for item in trading_events)


def test_lab_digest_includes_research_mode_usage(tmp_path):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.create_continuous_improvement_cycle(
        {
            "cycle_id": "ci_cycle_research_digest",
            "trace_id": "trace",
            "job_id": "job",
            "status": "COMPLETED",
            "mode": "research",
            "dry_run": True,
        }
    )

    digest = build_lab_digest(store, days=1, data_dir=tmp_path)
    text = format_lab_digest_text(digest)

    assert digest["research_mode"]["cycles"] == 1
    assert "Research-mode cerrado" in text
