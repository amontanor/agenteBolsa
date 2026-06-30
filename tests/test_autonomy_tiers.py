"""Tests de niveles de autonomia de codigo (T1.1)."""

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.autonomy import (
    active_autonomy_level,
    ast_import_violation,
    autonomy_promotion_check,
    path_violation,
)
from agente_bolsa.continuous_improvement.experiments import AutoApplyCodeAgent
from agente_bolsa.storage import Store


# -- path_violation por nivel ----------------------------------------------
def test_tools_file_blocked_at_level1_allowed_at_level2():
    rel = "src/agente_bolsa/tools/breakout_scanner.py"
    assert path_violation(rel, 1) is not None
    assert path_violation(rel, 2) is None


def test_kernel_and_broker_blocked_at_all_levels():
    for level in (1, 2, 3):
        assert path_violation("src/agente_bolsa/kernel.py", level) is not None
        assert path_violation("src/agente_bolsa/tools/broker.py", level) is not None
        assert path_violation("src/agente_bolsa/tools/execution.py", level) is not None
        assert path_violation("src/agente_bolsa/tools/risk.py", level) is not None
        assert path_violation("src/agente_bolsa/config.py", level) is not None
        assert path_violation(".env", level) is not None


def test_decision_core_requires_level3():
    rel = "src/agente_bolsa/tools/trade_decision.py"
    assert path_violation(rel, 2) is not None
    assert path_violation(rel, 3) is None


def test_order_term_blocked_only_at_level1():
    rel = "tests/test_order_flow.py"
    assert path_violation(rel, 1) is not None
    assert path_violation(rel, 2) is None


# -- AST import guard -------------------------------------------------------
def test_ast_import_violation_flags_new_broker_import():
    before = "import os\n"
    after = "from agente_bolsa.tools.broker import BrokerClientFactory\nimport os\n"
    assert ast_import_violation(before, after) is not None
    assert ast_import_violation(after, after) is None
    assert ast_import_violation("import os", "import sys") is None


# -- promocion/degradacion automatica --------------------------------------
def _settings(tmp_path, **overrides):
    return Settings(DATA_DIR=tmp_path, **overrides)


def _store(settings):
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def _seed_iq(store, prior, recent):
    idx = 1
    for value in prior + recent:
        store.upsert_performance_daily({"session_date": f"2026-05-{idx:02d}", "iq_score": value})
        idx += 1


def test_promotion_to_level2_with_clean_history(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    _seed_iq(store, [50] * 10, [60] * 10)  # tendencia no decreciente
    for i in range(10):
        store.save_continuous_improvement_applied_change(
            {
                "applied_change_id": f"c{i}",
                "change_type": "CODE_CHANGE",
                "status": "APPLIED",
                "target_key": "x",
                "decision": {"autonomy_level": 1},
            }
        )

    progress = autonomy_promotion_check(store, settings)
    assert progress["changed"] is True
    assert progress["new_level"] == 2
    assert active_autonomy_level(store, settings) == 2


def test_demotion_on_watchdog_rollbacks(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    store.set_runtime_value("code_autonomy_level", {"level": 2})
    for i in range(2):
        store.save_continuous_improvement_applied_change(
            {
                "applied_change_id": f"r{i}",
                "change_type": "CODE_CHANGE",
                "status": "ROLLED_BACK",
                "target_key": "x",
                "decision": {"rollback_actor": "change_watchdog"},
            }
        )

    progress = autonomy_promotion_check(store, settings)
    assert progress["changed"] is True
    assert progress["new_level"] == 1


def test_status_recompute_does_not_persist(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    _seed_iq(store, [50] * 10, [60] * 10)
    for i in range(10):
        store.save_continuous_improvement_applied_change(
            {
                "applied_change_id": f"c{i}",
                "change_type": "CODE_CHANGE",
                "status": "APPLIED",
                "target_key": "x",
                "decision": {"autonomy_level": 1},
            }
        )
    autonomy_promotion_check(store, settings, persist=False)
    assert active_autonomy_level(store, settings) == 1


# -- integracion: try_apply respeta el nivel (workspace no-git -> legacy) ---
def test_try_apply_blocks_tools_file_at_level1(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = Settings(
        DATA_DIR=tmp_path / "state",
        IMPROVEMENT_DRY_RUN=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=True,
        REQUIRE_HUMAN_APPROVAL_FOR_CODE_CHANGES=False,
        CONTINUOUS_IMPROVEMENT_WORKSPACE_DIR=workspace,
        CODE_AUTONOMY_LEVEL=1,
    )
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    proposal = {
        "proposal_id": "ci_prop_tier",
        "cycle_id": "ci_cycle_tier",
        "proposal_type": "CODE_CHANGE",
        "status": "READY_TO_APPLY",
        "risk_level": "LOW",
        "payload": {
            "proposal_type": "CODE_CHANGE",
            "rollback_plan": "restore",
            "file_edits": [{"path": "src/agente_bolsa/tools/breakout_scanner.py", "content": "# x\n"}],
        },
    }
    validation = {"validation_id": "v", "status": "READY_TO_APPLY", "payload": {}}

    result = AutoApplyCodeAgent().try_apply(
        settings=settings, store=store, initiative=None, proposal=proposal, validation=validation
    )
    assert result["status"] == "BLOCKED"
    assert "allowlist" in result["error"]
    assert not (workspace / "src" / "agente_bolsa" / "tools" / "breakout_scanner.py").exists()


@pytest.mark.parametrize(
    "protected_path",
    [
        "src/agente_bolsa/kernel.py",
        "src/agente_bolsa/tools/broker.py",
        "src/agente_bolsa/tools/execution.py",
        "src/agente_bolsa/tools/risk.py",
        "src/agente_bolsa/config.py",
        ".env",
    ],
)
@pytest.mark.parametrize("level", [1, 2, 3])
def test_auto_apply_blocks_kernel_floor_paths_at_every_autonomy_level(tmp_path, protected_path, level):
    workspace = tmp_path / f"workspace_{level}_{protected_path.replace('/', '_').replace('.', '_')}"
    workspace.mkdir()
    settings = Settings(
        DATA_DIR=tmp_path / f"state_{level}_{protected_path.replace('/', '_').replace('.', '_')}",
        IMPROVEMENT_DRY_RUN=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=True,
        REQUIRE_HUMAN_APPROVAL_FOR_CODE_CHANGES=False,
        CONTINUOUS_IMPROVEMENT_WORKSPACE_DIR=workspace,
        CODE_AUTONOMY_LEVEL=level,
    )
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    proposal = {
        "proposal_id": f"ci_prop_floor_{level}",
        "cycle_id": f"ci_cycle_floor_{level}",
        "proposal_type": "CODE_CHANGE",
        "status": "READY_TO_APPLY",
        "risk_level": "LOW",
        "target_component": "continuous_improvement",
        "payload": {
            "proposal_type": "CODE_CHANGE",
            "rollback_plan": "restore",
            "file_edits": [{"path": protected_path, "content": "# blocked\n"}],
            "test_commands": ["python -c \"assert True\""],
        },
    }
    validation = {"validation_id": f"ci_val_floor_{level}", "status": "READY_TO_APPLY", "payload": {}}

    result = AutoApplyCodeAgent().try_apply(
        settings=settings,
        store=store,
        initiative=None,
        proposal=proposal,
        validation=validation,
    )

    assert result["status"] == "BLOCKED"
    assert "bloqueado" in result["error"]
    assert not (workspace / protected_path).exists()
