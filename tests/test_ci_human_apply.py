"""Tests del apply humano de diffs validados."""

import subprocess

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.human_apply import (
    _repair_cp1252_mojibake,
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


def test_human_approve_skips_newer_rejected_preview_and_applies_previous_ready(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    settings = _settings(tmp_path, repo)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    proposal_id = _proposal_with_artifact(store, proposal_id="ci_prop_limit_before_filter")
    store.save_continuous_improvement_proposal_artifact(
        {
            "artifact_id": f"{proposal_id}_rejected_artifact",
            "proposal_id": proposal_id,
            "artifact_type": "code_diff_preview",
            "content_text": "diff --git a/docs/rejected.md b/docs/rejected.md\n",
            "payload": {
                "status": "REJECTED_BY_HUMAN_REVIEW",
                "tests_ok": False,
                "human_review_reason": "new_code_without_tests",
            },
        }
    )

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
    assert result["artifact"]["payload"]["diff_artifact_id"] == f"{proposal_id}_artifact"
    assert (repo / "docs" / "human_apply.md").read_text(encoding="utf-8") == "human apply ok\n"
    assert not (repo / "docs" / "rejected.md").exists()


def test_human_approve_applies_lf_diff_to_crlf_worktree_file(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    target = repo / "docs" / "human_apply.md"
    target.write_bytes(b"alpha\r\nbeta\r\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "crlf file")
    settings = _settings(tmp_path, repo)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    diff_text = """diff --git a/docs/human_apply.md b/docs/human_apply.md
index fbbee86..c2ee3cc 100644
--- a/docs/human_apply.md
+++ b/docs/human_apply.md
@@ -1,2 +1,2 @@
-alpha
+alpha updated
 beta
"""
    proposal_id = _proposal_with_artifact(store, proposal_id="ci_prop_crlf_apply", diff_text=diff_text)

    result = approve_and_apply_code_diff(
        settings=settings,
        store=store,
        proposal_id=proposal_id,
        actor="pytest",
        validation_steps=[("unit", ["python", "-c", "from pathlib import Path; assert 'alpha updated' in Path('docs/human_apply.md').read_text()"])],
        backup=False,
    )

    assert result["ok"] is True
    assert "alpha updated" in target.read_text(encoding="utf-8")
    assert result["artifact"]["payload"]["apply_strategy"] in {"3way", "ignore_whitespace"}


def test_human_approve_repairs_cp1252_mojibake_context(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    target = repo / "docs" / "human_apply.md"
    target.write_text('PIDE APROBACIÓN\nnext\n', encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "utf8 file")
    settings = _settings(tmp_path, repo)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    mojibake = "PIDE APROBACIÓN".encode().decode("cp1252")
    diff_text = f"""diff --git a/docs/human_apply.md b/docs/human_apply.md
index 274dbf4..94a86be 100644
--- a/docs/human_apply.md
+++ b/docs/human_apply.md
@@ -1,2 +1,2 @@
-{mojibake}
+PIDE OK
 next
"""
    proposal_id = _proposal_with_artifact(store, proposal_id="ci_prop_mojibake_apply", diff_text=diff_text)

    result = approve_and_apply_code_diff(
        settings=settings,
        store=store,
        proposal_id=proposal_id,
        actor="pytest",
        validation_steps=[("unit", ["python", "-c", "from pathlib import Path; assert Path('docs/human_apply.md').read_text(encoding='utf-8').startswith('PIDE OK')"])],
        backup=False,
    )

    assert result["ok"] is True
    assert target.read_text(encoding="utf-8").startswith("PIDE OK")
    assert result["artifact"]["payload"]["apply_strategy"] in {
        "ignore_whitespace",
        "repair_cp1252_mojibake",
        "repair_cp1252_mojibake_ignore_whitespace",
    }


def test_repair_cp1252_mojibake_restores_utf8_text():
    mojibake = "PIDE APROBACIÓN".encode().decode("cp1252")

    assert _repair_cp1252_mojibake(mojibake) == "PIDE APROBACIÓN"


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
