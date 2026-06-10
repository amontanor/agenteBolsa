"""Tests del watchdog de cambios aplicados (T0.5)."""

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.change_watchdog import (
    evaluate_applied_changes,
    execute_rollbacks,
)


def _settings(tmp_path, **overrides):
    return Settings(DATA_DIR=tmp_path, **overrides)


def _store(settings):
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def _perf_row(date, iq, hit, buys=3):
    return {
        "session_date": date,
        "equity": 100000.0,
        "pnl_pct": 0.0,
        "iq_score": iq,
        "hit_rate_20": hit,
        "payload": {"buys": buys, "sells": 0},
    }


def _applied_change(change_id, *, created_at="2026-06-05T20:00:00+00:00", status="APPLIED"):
    return {
        "applied_change_id": change_id,
        "change_type": "CODE_CHANGE",
        "status": status,
        "target_key": "strategies/x",
        "created_at": created_at,
        "before": {},
        "after": {},
        "rollback": {"git": {"commit": "abc123", "tag": "ci-auto/x"}},
        "decision": {},
        "validation_ids": [],
    }


def _seed(store, rows):
    for row in rows:
        store.upsert_performance_daily(row)


def test_watchdog_requests_rollback_on_iq_drop(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    _seed(
        store,
        [
            _perf_row("2026-06-03", 70, 0.6),
            _perf_row("2026-06-04", 72, 0.6),
            _perf_row("2026-06-05", 71, 0.6),
            _perf_row("2026-06-06", 45, 0.5),
            _perf_row("2026-06-07", 48, 0.5),
        ],
    )
    store.save_continuous_improvement_applied_change(_applied_change("c_drop"))

    decisions = evaluate_applied_changes(store, settings)

    assert decisions[0]["verdict"] == "ROLLBACK_REQUESTED"
    persisted = store.continuous_improvement_applied_changes(statuses=["ROLLBACK_REQUESTED"])
    assert len(persisted) == 1
    assert persisted[0]["applied_change_id"] == "c_drop"


def test_watchdog_holds_when_metrics_improve(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    _seed(
        store,
        [
            _perf_row("2026-06-03", 50, 0.4),
            _perf_row("2026-06-04", 51, 0.4),
            _perf_row("2026-06-05", 50, 0.4),
            _perf_row("2026-06-06", 72, 0.6),
            _perf_row("2026-06-07", 75, 0.6),
        ],
    )
    store.save_continuous_improvement_applied_change(_applied_change("c_up"))

    decisions = evaluate_applied_changes(store, settings)

    assert decisions[0]["verdict"] == "HOLD"
    assert store.continuous_improvement_applied_changes(statuses=["ROLLBACK_REQUESTED"]) == []


def test_watchdog_waits_with_insufficient_window(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    _seed(
        store,
        [
            _perf_row("2026-06-04", 70, 0.6),
            _perf_row("2026-06-05", 71, 0.6),
            _perf_row("2026-06-06", 40, 0.4),  # solo 1 sesion post
        ],
    )
    store.save_continuous_improvement_applied_change(_applied_change("c_wait"))

    decisions = evaluate_applied_changes(store, settings)

    assert decisions[0]["verdict"] == "WAIT"
    assert store.continuous_improvement_applied_changes(statuses=["ROLLBACK_REQUESTED"]) == []


def test_watchdog_graduates_changes_past_window(tmp_path):
    settings = _settings(tmp_path, CHANGE_WATCHDOG_WINDOW_SESSIONS=3)
    store = _store(settings)
    rows = [_perf_row("2026-06-01", 70, 0.6), _perf_row("2026-06-02", 70, 0.6)]
    rows += [_perf_row(f"2026-06-0{i}", 40, 0.4) for i in range(3, 8)]  # 5 sesiones post > 3
    _seed(store, rows)
    store.save_continuous_improvement_applied_change(
        _applied_change("c_old", created_at="2026-06-02T20:00:00+00:00")
    )

    decisions = evaluate_applied_changes(store, settings)
    assert decisions[0]["verdict"] == "GRADUATED"


def test_execute_rollbacks_invokes_agent(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    store = _store(settings)
    change = _applied_change("c_exec", status="ROLLBACK_REQUESTED")
    change["decision"] = {"watchdog": {"metrics": {"iq_drop": 20.0}}}
    store.save_continuous_improvement_applied_change(change)

    captured = {}

    def fake_rollback(self, *, settings, store, applied_change_id, actor="api"):
        captured["id"] = applied_change_id
        captured["actor"] = actor
        return {"applied_change_id": applied_change_id, "status": "ROLLED_BACK"}

    monkeypatch.setattr(
        "agente_bolsa.continuous_improvement.experiments.AutoApplyCodeAgent.rollback",
        fake_rollback,
    )

    results = execute_rollbacks(store, settings)

    assert captured["id"] == "c_exec"
    assert captured["actor"] == "change_watchdog"
    assert results[0]["status"] == "ROLLED_BACK"
