"""Tests del sandbox git real para cambios autonomos (T0.3)."""

import subprocess

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.experiments import AutoApplyCodeAgent, CodeDiffPreviewAgent
from agente_bolsa.continuous_improvement.sandbox import (
    GitSandbox,
    GitSandboxError,
    apply_payload_to_worktree,
    run_validation_steps,
    sandbox_supported,
)
from agente_bolsa.storage import Store


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), text=True, capture_output=True)


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    (path / "docs").mkdir(exist_ok=True)
    (path / "tests").mkdir(exist_ok=True)
    (path / "docs" / "base.md").write_text("base\n", encoding="utf-8")
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "a@b.c")
    _git(path, "config", "user.name", "t")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "init")
    return path


def _settings(tmp_path, workspace):
    return Settings(
        DATA_DIR=tmp_path / "state",
        IMPROVEMENT_DRY_RUN=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=True,
        REQUIRE_HUMAN_APPROVAL_FOR_CODE_CHANGES=False,
        ALLOW_LIVE_TRADING=False,
        CONTINUOUS_IMPROVEMENT_WORKSPACE_DIR=workspace,
        CI_SANDBOX_ENABLED=True,
        CI_SANDBOX_FULL_SUITE=False,
    )


def _proposal(file_edits, *, proposal_id="ci_prop_sbx"):
    payload = {
        "proposal_type": "CODE_CHANGE",
        "target_component": "docs",
        "rationale": "sandbox test",
        "expected_impact": "n/a",
        "risk_level": "LOW",
        "rollback_plan": "git revert",
        "file_edits": file_edits,
    }
    return {
        "proposal_id": proposal_id,
        "cycle_id": "ci_cycle_sbx",
        "proposal_type": "CODE_CHANGE",
        "target_component": "docs",
        "status": "READY_TO_APPLY",
        "risk_level": "LOW",
        "payload": payload,
    }


def _validation():
    return {
        "validation_id": "ci_val_sbx",
        "proposal_id": "ci_prop_sbx",
        "cycle_id": "ci_cycle_sbx",
        "status": "READY_TO_APPLY",
        "payload": {"objective_status": "READY_TO_APPLY"},
    }


pytestmark = pytest.mark.skipif(
    subprocess.run(["git", "--version"], capture_output=True).returncode != 0,
    reason="git no disponible",
)


# -- GitSandbox directo ----------------------------------------------------
def test_git_sandbox_lifecycle_apply_validate_merge(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    settings = _settings(tmp_path, repo)
    sandbox = GitSandbox(settings, repo_root=repo)

    worktree = sandbox.open("c1")
    assert worktree.exists()
    sandbox.apply([{"path": "docs/new.md", "content": "hola\n"}], "")
    result = sandbox.validate(steps=[("noop", ["python", "-c", "print(1)"])])
    assert result["ok"] is True
    merge = sandbox.merge()
    assert merge["commit"]
    assert (repo / "docs" / "new.md").read_text(encoding="utf-8") == "hola\n"
    sandbox.destroy()
    assert not worktree.exists()


def test_git_sandbox_failing_validation_destroys_worktree(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    settings = _settings(tmp_path, repo)
    sandbox = GitSandbox(settings, repo_root=repo)
    worktree = sandbox.open("c2")
    sandbox.apply([{"path": "docs/bad.md", "content": "x\n"}], "")
    result = sandbox.validate(steps=[("fail", ["python", "-c", "import sys; sys.exit(1)"])])
    assert result["ok"] is False
    sandbox.destroy()
    assert not worktree.exists()
    assert not (repo / "docs" / "bad.md").exists()


# -- AutoApplyCodeAgent a traves del sandbox -------------------------------
def test_try_apply_sandbox_applies_valid_change(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")
    settings = _settings(tmp_path, repo)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()

    monkeypatch.setattr(GitSandbox, "validate", lambda self, **kw: {"ok": True, "steps": []})

    result = AutoApplyCodeAgent().try_apply(
        settings=settings,
        store=store,
        initiative=None,
        proposal=_proposal([{"path": "docs/note.md", "content": "contenido\n"}]),
        validation=_validation(),
    )

    assert result["status"] == "APPLIED"
    assert result["rollback"]["git"]["commit"]
    assert (repo / "docs" / "note.md").exists()
    assert not (repo / "sandboxes" / result["applied_change_id"]).exists()


def test_try_apply_sandbox_rejects_when_validation_fails(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")
    settings = _settings(tmp_path, repo)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()

    monkeypatch.setattr(
        GitSandbox,
        "validate",
        lambda self, **kw: {"ok": False, "steps": [{"step": "pytest", "ok": False, "returncode": 1, "output": "boom"}]},
    )

    result = AutoApplyCodeAgent().try_apply(
        settings=settings,
        store=store,
        initiative=None,
        proposal=_proposal([{"path": "docs/note.md", "content": "contenido\n"}]),
        validation=_validation(),
    )

    assert result["status"] == "REJECTED_BY_TESTS"
    assert not (repo / "docs" / "note.md").exists()
    assert not (repo / "sandboxes" / result["applied_change_id"]).exists()
    artifact = store.continuous_improvement_proposal_artifact("ci_prop_sbx")
    assert artifact is not None


def test_try_apply_sandbox_blocks_kernel_without_worktree(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    settings = _settings(tmp_path, repo)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()

    result = AutoApplyCodeAgent().try_apply(
        settings=settings,
        store=store,
        initiative=None,
        proposal=_proposal([{"path": "src/agente_bolsa/kernel.py", "content": "# hack\n"}]),
        validation=_validation(),
    )

    assert result["status"] == "BLOCKED"
    assert "bloqueado" in result["error"]
    sandboxes = repo / "sandboxes"
    assert not sandboxes.exists() or not any(sandboxes.iterdir())


def test_sandbox_supported_detects_non_git(tmp_path):
    assert sandbox_supported(_init_repo(tmp_path / "repo")) is True
    plain = tmp_path / "plain"
    plain.mkdir()
    assert sandbox_supported(plain) is False


def test_validation_steps_report_missing_command_as_failed_step(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    settings = _settings(tmp_path, repo)

    result = run_validation_steps(settings, repo, steps=[("missing", ["missing-command-for-ci-test"])])

    assert result["ok"] is False
    assert result["steps"][0]["ok"] is False
    assert "FileNotFoundError" in result["steps"][0]["output"]


# -- Diff preview para revision humana -------------------------------------
def test_code_diff_preview_generates_artifact_without_applied_change(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")
    settings = _settings(tmp_path, repo)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    monkeypatch.setattr(
        GitSandbox,
        "validate",
        lambda self, **kw: {"ok": True, "steps": [{"step": "pytest", "ok": True, "returncode": 0, "output": "ok"}]},
    )
    proposal = _proposal(
        [{"path": "docs/base.md", "old": "base\n", "new": "base\npreview\n"}],
        proposal_id="ci_prop_diff_preview",
    )
    proposal["payload"]["test_commands"] = ["python -c \"assert True\""]
    validation = _validation()
    validation["proposal_id"] = "ci_prop_diff_preview"

    artifact = CodeDiffPreviewAgent().generate(
        settings=settings,
        store=store,
        proposal=proposal,
        validation=validation,
    )

    assert artifact["artifact_type"] == "code_diff_preview"
    assert "diff --git a/docs/base.md b/docs/base.md" in artifact["content_text"]
    assert "+preview" in artifact["content_text"]
    assert artifact["payload"]["tests_ok"] is True
    assert artifact["payload"]["status"] == "READY_FOR_HUMAN_REVIEW"
    assert store.continuous_improvement_applied_changes(limit=10) == []
    assert (repo / "docs" / "base.md").read_text(encoding="utf-8") == "base\n"


def test_code_diff_preview_attaches_failed_tests_without_promotion(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")
    settings = _settings(tmp_path, repo)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    monkeypatch.setattr(
        GitSandbox,
        "validate",
        lambda self, **kw: {
            "ok": False,
            "steps": [{"step": "pytest", "ok": False, "returncode": 1, "output": "failed"}],
        },
    )
    proposal = _proposal(
        [{"path": "docs/base.md", "old": "base\n", "new": "base\npreview\n"}],
        proposal_id="ci_prop_diff_preview_failed_tests",
    )
    validation = _validation()
    validation["proposal_id"] = "ci_prop_diff_preview_failed_tests"

    artifact = CodeDiffPreviewAgent().generate(
        settings=settings,
        store=store,
        proposal=proposal,
        validation=validation,
    )

    assert artifact["artifact_type"] == "code_diff_preview_invalid"
    assert artifact["payload"]["tests_ok"] is False
    assert artifact["payload"]["status"] == "REJECTED_BY_TESTS"
    assert "diff --git a/docs/base.md b/docs/base.md" in artifact["content_text"]
    assert store.continuous_improvement_applied_changes(limit=10) == []
    assert (repo / "docs" / "base.md").read_text(encoding="utf-8") == "base\n"


@pytest.mark.parametrize("protected_path", [".env", "src/agente_bolsa/tools/risk.py"])
def test_code_diff_preview_blocks_kernel_floor_without_worktree(tmp_path, protected_path):
    repo = _init_repo(tmp_path / "repo")
    settings = _settings(tmp_path, repo)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    proposal = _proposal(
        [{"path": protected_path, "content": "# blocked\n"}],
        proposal_id=f"ci_prop_blocked_{protected_path.replace('/', '_').replace('.', '_')}",
    )
    proposal["payload"]["test_commands"] = ["python -c \"assert True\""]

    artifact = CodeDiffPreviewAgent().generate(
        settings=settings,
        store=store,
        proposal=proposal,
        validation=_validation(),
    )

    assert artifact["artifact_type"] == "code_diff_preview_blocked"
    assert artifact["payload"]["status"] == "BLOCKED"
    assert "bloqueado" in artifact["payload"]["error"]
    assert store.continuous_improvement_applied_changes(limit=10) == []
    sandboxes = repo / "sandboxes"
    assert not sandboxes.exists() or not any(sandboxes.iterdir())


# -- T5.8: integridad de escritura -----------------------------------------
def test_apply_rejects_null_bytes(tmp_path):
    with pytest.raises(GitSandboxError):
        apply_payload_to_worktree(
            tmp_path, file_edits=[{"path": "x.py", "content": "x=1\x00\n"}], patch_text=""
        )


def test_apply_rejects_unparseable_python(tmp_path):
    with pytest.raises(GitSandboxError):
        apply_payload_to_worktree(
            tmp_path, file_edits=[{"path": "x.py", "content": "def f(:\n"}], patch_text=""
        )
    assert not (tmp_path / "x.py").exists() or "def f(:" not in (tmp_path / "x.py").read_text()


def test_apply_normalizes_trailing_newline(tmp_path):
    apply_payload_to_worktree(tmp_path, file_edits=[{"path": "docs/n.md", "content": "hola"}], patch_text="")
    assert (tmp_path / "docs" / "n.md").read_text(encoding="utf-8") == "hola\n"


def test_legacy_apply_refuses_main_repo():
    from pathlib import Path

    from agente_bolsa.continuous_improvement import experiments

    repo_root = Path(experiments.__file__).resolve().parents[3]
    agent = AutoApplyCodeAgent()
    with pytest.raises(RuntimeError, match="repo principal"):
        agent._apply_payload(repo_root, file_edits=[{"path": "docs/x.md", "content": "x"}], patch_text="")
