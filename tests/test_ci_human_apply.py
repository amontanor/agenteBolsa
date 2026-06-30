"""Tests del apply humano de diffs validados."""

import subprocess

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.human_apply import (
    approve_and_apply_code_diff,
    review_code_diff_artifacts,
)
from agente_bolsa.storage import Store


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), text=True, capture_output=True)


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    (path / "docs").mkdir(exist_ok=True)
    (path / "src" / "agente_bolsa" / "tools").mkdir(parents=True, exist_ok=True)
    (path / "src" / "agente_bolsa" / "tools" / "risk.py").write_text("# risk\n", encoding="utf-8")
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "a@b.c")
    _git(path, "config", "user.name", "t")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "init")
    return path


def _settings(tmp_path, repo, **overrides):
    values = {
        "DATA_DIR": tmp_path / "state",
        "CONTINUOUS_IMPROVEMENT_WORKSPACE_DIR": repo,
        "ALLOW_LIVE_TRADING": False,
        "TRADING_MODE": "paper",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _proposal_with_artifact(store, *, proposal_id="ci_prop_human", diff_text=None):
    cycle_id = f"{proposal_id}_cycle"
    store.upsert_continuous_improvement_proposal(
        {
            "proposal_id": proposal_id,
            "cycle_id": cycle_id,
            "fingerprint": proposal_id,
            "proposal_type": "CODE_CHANGE",
            "target_component": "docs",
            "target_identifier": "docs/human_apply.md",
            "status": "READY_TO_APPLY",
            "priority": "LOW",
            "risk_level": "LOW",
            "payload": {"rollback_plan": "git revert"},
            "guard": {"status": "READY_TO_APPLY"},
        }
    )
    diff_text = diff_text or """diff --git a/docs/human_apply.md b/docs/human_apply.md
new file mode 100644
index 0000000..f9328a1
--- /dev/null
+++ b/docs/human_apply.md
@@ -0,0 +1 @@
+human apply ok
"""
    store.save_continuous_improvement_proposal_artifact(
        {
            "artifact_id": f"{proposal_id}_artifact",
            "proposal_id": proposal_id,
            "artifact_type": "code_diff_preview",
            "content_text": diff_text,
            "payload": {
                "status": "READY_FOR_HUMAN_REVIEW",
                "tests_ok": True,
                "validation_id": f"{proposal_id}_validation",
                "validation": {"ok": True, "steps": []},
            },
        }
    )
    return proposal_id


pytestmark = pytest.mark.skipif(
    subprocess.run(["git", "--version"], capture_output=True).returncode != 0,
    reason="git no disponible",
)


def test_review_lists_ready_diff_without_changing_state(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    settings = _settings(tmp_path, repo)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    proposal_id = _proposal_with_artifact(store)

    result = review_code_diff_artifacts(store, proposal_id=proposal_id)

    assert result["count"] == 1
    assert result["artifacts"][0]["proposal_id"] == proposal_id
    assert result["artifacts"][0]["target_paths"] == ["docs/human_apply.md"]
    assert store.continuous_improvement_applied_changes(limit=10) == []


def test_human_approve_applies_allowlisted_diff_and_records_applied_change(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    settings = _settings(tmp_path, repo)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    proposal_id = _proposal_with_artifact(store)

    result = approve_and_apply_code_diff(
        settings=settings,
        store=store,
        proposal_id=proposal_id,
        actor="pytest",
        validation_steps=[("unit", ["python", "-c", "from pathlib import Path; assert Path('docs/human_apply.md').exists()"])],
        backup=False,
    )

    assert result["ok"] is True
    assert result["status"] == "APPLIED"
    assert (repo / "docs" / "human_apply.md").read_text(encoding="utf-8") == "human apply ok\n"
    changes = store.continuous_improvement_applied_changes(proposal_id=proposal_id, statuses=["APPLIED"], limit=10)
    assert len(changes) == 1
    assert changes[0]["decision"]["manual_approval"] is True
    assert changes[0]["after"]["commit"] == result["commit"]
    assert _git(repo, "status", "--short").stdout.strip() == ""


@pytest.mark.parametrize(
    "target,diff_text",
    [
        (
            ".env",
            """diff --git a/.env b/.env
new file mode 100644
index 0000000..8baef1b
--- /dev/null
+++ b/.env
@@ -0,0 +1 @@
+SECRET=blocked
""",
        ),
        (
            "src/agente_bolsa/tools/risk.py",
            """diff --git a/src/agente_bolsa/tools/risk.py b/src/agente_bolsa/tools/risk.py
index 7427b25..1f2a48f 100644
--- a/src/agente_bolsa/tools/risk.py
+++ b/src/agente_bolsa/tools/risk.py
@@ -1 +1 @@
-# risk
+# blocked
""",
        ),
    ],
)
def test_human_approve_rejects_kernel_floor_even_with_approval(tmp_path, target, diff_text):
    repo = _init_repo(tmp_path / "repo")
    settings = _settings(tmp_path, repo)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    proposal_id = _proposal_with_artifact(store, proposal_id=f"ci_prop_block_{target.replace('/', '_').replace('.', '_')}", diff_text=diff_text)

    result = approve_and_apply_code_diff(
        settings=settings,
        store=store,
        proposal_id=proposal_id,
        actor="pytest",
        validation_steps=[("unit", ["python", "-c", "assert True"])],
        backup=False,
    )

    assert result["ok"] is False
    assert result["status"] == "BLOCKED"
    assert "bloqueado" in result["error"]
    assert store.continuous_improvement_applied_changes(limit=10) == []
    assert not (repo / ".env").exists()
    assert (repo / "src" / "agente_bolsa" / "tools" / "risk.py").read_text(encoding="utf-8") == "# risk\n"
    assert _git(repo, "status", "--short").stdout.strip() == ""


def test_human_approve_rejects_failing_suite_and_leaves_no_residue(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    settings = _settings(tmp_path, repo)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    proposal_id = _proposal_with_artifact(store, proposal_id="ci_prop_failing_suite")

    result = approve_and_apply_code_diff(
        settings=settings,
        store=store,
        proposal_id=proposal_id,
        actor="pytest",
        validation_steps=[("fail", ["python", "-c", "import sys; sys.exit(1)"])],
        backup=False,
    )

    assert result["ok"] is False
    assert result["status"] == "REJECTED_BY_TESTS"
    assert not (repo / "docs" / "human_apply.md").exists()
    assert store.continuous_improvement_applied_changes(limit=10) == []
    assert store.continuous_improvement_proposal(proposal_id)["status"] == "REJECTED_BY_TESTS"
    assert _git(repo, "status", "--short").stdout.strip() == ""
