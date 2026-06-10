"""Tests del dashboard de autonomia y freno humano (T4.2)."""

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.autonomy_digest import (
    LAB_ENABLED_KEY,
    build_autonomy_digest,
    collect_autonomy_state,
    pause_all,
    resume_all,
)


def _setup(tmp_path):
    settings = Settings(DATA_DIR=tmp_path)
    settings.ensure_runtime_dirs()
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return settings, store


def test_collect_autonomy_state_counts(tmp_path):
    settings, store = _setup(tmp_path)
    store.save_continuous_improvement_applied_change(
        {"applied_change_id": "a1", "change_type": "CODE_CHANGE", "status": "APPLIED", "target_key": "x", "decision": {}}
    )
    store.save_continuous_improvement_applied_change(
        {"applied_change_id": "r1", "change_type": "CODE_CHANGE", "status": "ROLLED_BACK", "target_key": "x", "decision": {}}
    )
    store.upsert_performance_daily({"session_date": "2026-06-10", "iq_score": 62, "equity": 101000.0, "alpha": 0.001})

    state = collect_autonomy_state(store, settings)
    assert state["applied"] == 1
    assert state["rolled_back"] == 1
    assert state["iq_score"] == 62
    assert state["autonomy_level"] == 1


def test_build_autonomy_digest_writes_file(tmp_path):
    settings, store = _setup(tmp_path)
    result = build_autonomy_digest(store, settings)
    assert "Digest de autonomia" in result["markdown"]
    assert result["path"] is not None


def test_pause_and_resume_toggle_lab_and_kill_switch(tmp_path):
    settings, store = _setup(tmp_path)
    from agente_bolsa.tools.operational_health import load_persistent_kill_switch

    pause_all(store, settings)
    assert store.get_runtime_value(LAB_ENABLED_KEY) is False
    assert load_persistent_kill_switch(settings.data_dir)  # kill switch activo

    resume_all(store, settings)
    assert store.get_runtime_value(LAB_ENABLED_KEY) is True
    assert not load_persistent_kill_switch(settings.data_dir)
