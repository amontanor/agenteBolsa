"""Tests del camino a live con capital progresivo (T4.3)."""

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.live_readiness import (
    _autonomous_metrics,
    build_live_readiness_report,
    live_capital_recommendation,
)


def _setup(tmp_path, **overrides):
    settings = Settings(DATA_DIR=tmp_path, **overrides)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return settings, store


def _seed_perf(store, n, *, alpha=0.001, sharpe=1.2, max_dd=0.05, pnl=0.001):
    for i in range(n):
        store.upsert_performance_daily(
            {
                "session_date": f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                "alpha": alpha,
                "sharpe_60": sharpe,
                "max_dd": max_dd,
                "pnl_pct": pnl,
                "iq_score": 60,
            }
        )


def test_autonomous_metrics_counts(tmp_path):
    settings, store = _setup(tmp_path)
    _seed_perf(store, 60)
    store.save_continuous_improvement_applied_change(
        {"applied_change_id": "a1", "change_type": "CODE_CHANGE", "status": "APPLIED", "target_key": "x", "decision": {}}
    )
    store.save_continuous_improvement_applied_change(
        {
            "applied_change_id": "r1",
            "change_type": "CODE_CHANGE",
            "status": "ROLLED_BACK",
            "target_key": "x",
            "decision": {"rollback_actor": "change_watchdog"},
        }
    )
    metrics = _autonomous_metrics(settings, store)
    assert metrics["sessions"] == 60
    assert metrics["alpha_cum"] > 0
    assert metrics["rollback_ratio"] == 0.5


def test_live_capital_deescalates_on_bad_week(tmp_path):
    settings, store = _setup(tmp_path, LIVE_CAPITAL_FRACTION=0.10)
    # 5 sesiones que suman -4% -> des-escalado a la mitad.
    for i in range(5):
        store.upsert_performance_daily({"session_date": f"2026-06-0{i + 1}", "pnl_pct": -0.008})
    rec = live_capital_recommendation(settings, store)
    assert rec["recommended_fraction"] == 0.05
    assert "des-escalado" in rec["reason"]


def test_live_capital_stable_on_good_week(tmp_path):
    settings, store = _setup(tmp_path, LIVE_CAPITAL_FRACTION=0.10)
    for i in range(5):
        store.upsert_performance_daily({"session_date": f"2026-06-0{i + 1}", "pnl_pct": 0.004})
    rec = live_capital_recommendation(settings, store)
    assert rec["recommended_fraction"] == 0.10


def test_readiness_blocks_without_enough_sessions(tmp_path):
    settings, store = _setup(tmp_path)
    report = build_live_readiness_report(settings, store, tmp_path / "reports", "ready1")
    checks = {c["key"]: c["status"] for c in report["checks"]}
    assert checks["paper_sessions_60"] == "block"
    assert report["summary"]["ready_for_live"] is False
