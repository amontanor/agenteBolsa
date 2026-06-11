"""Tests de benchmarks ingenuos, edge_report y freeze (T5.1)."""

import random

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.experiments import AutoApplyCodeAgent
from agente_bolsa.continuous_improvement.promotion import PromotionManager
from agente_bolsa.storage import Store
from agente_bolsa.tools.adaptive_tuning import update_adaptive_config
from agente_bolsa.tools.naive_benchmarks import edge_report


def _setup(tmp_path, **overrides):
    settings = Settings(DATA_DIR=tmp_path, **overrides)
    settings.ensure_runtime_dirs()
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return settings, store


def _seed_edge(store, *, base_pnl, base_spy, base_naive, n=60, seed=1):
    rng = random.Random(seed)
    for i in range(n):
        store.upsert_performance_daily(
            {
                "session_date": f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                "pnl_pct": base_pnl + rng.gauss(0, 0.003),
                "spy_pct": base_spy + rng.gauss(0, 0.003),
                "payload": {"benchmarks": {"naive_momentum_pct": base_naive + rng.gauss(0, 0.003)}},
            }
        )


def test_edge_confirmed_when_clearly_above_benchmarks(tmp_path):
    settings, store = _setup(tmp_path)
    _seed_edge(store, base_pnl=0.012, base_spy=0.002, base_naive=0.004)
    report = edge_report(store, sessions=60)
    assert report["verdict"] == "EDGE_CONFIRMED"
    assert report["alpha_vs_naive_momentum"] > 0


def test_no_edge_when_matching_benchmark(tmp_path):
    settings, store = _setup(tmp_path)
    rng = random.Random(3)
    for i in range(60):
        store.upsert_performance_daily(
            {
                "session_date": f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                "pnl_pct": 0.002 + rng.gauss(0, 0.012),
                "spy_pct": 0.002 + rng.gauss(0, 0.012),
                "payload": {},
            }
        )
    report = edge_report(store, sessions=60)
    assert report["verdict"] in {"NO_EDGE", "EDGE_WEAK"}


def test_freeze_blocks_code_apply(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    settings = Settings(
        DATA_DIR=tmp_path / "state",
        SYSTEM_FREEZE_MODE=True,
        IMPROVEMENT_DRY_RUN=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=True,
        CONTINUOUS_IMPROVEMENT_WORKSPACE_DIR=workspace,
    )
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    proposal = {
        "proposal_id": "p", "cycle_id": "c", "proposal_type": "CODE_CHANGE", "status": "READY_TO_APPLY",
        "risk_level": "LOW", "payload": {"proposal_type": "CODE_CHANGE", "rollback_plan": "x", "file_edits": [{"path": "docs/x.md", "content": "y"}]},
    }
    result = AutoApplyCodeAgent().try_apply(
        settings=settings, store=store, initiative=None, proposal=proposal,
        validation={"validation_id": "v", "status": "READY_TO_APPLY", "payload": {}},
    )
    assert result["status"] == "BLOCKED"
    assert result["error"] == "system_freeze"


def test_freeze_blocks_promotion(tmp_path):
    settings, store = _setup(tmp_path, SYSTEM_FREEZE_MODE=True)
    result = PromotionManager(store, settings).start_shadow("chal", "1")
    assert result.get("status") == "BLOCKED"
    assert PromotionManager(store, settings).evaluate_windows() == []


def test_freeze_blocks_adaptive_tuning(tmp_path):
    settings, store = _setup(tmp_path, SYSTEM_FREEZE_MODE=True)
    result = update_adaptive_config(settings, store)
    assert result["status"] == "blocked"
    assert result["reason"] == "system_freeze"
