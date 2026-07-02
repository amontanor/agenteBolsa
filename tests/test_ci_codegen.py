"""Tests del codegen manual de diffs revisables."""

import subprocess

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.codegen import (
    CodegenPatchAgent,
    CodegenPatchResponse,
)
from agente_bolsa.continuous_improvement.llm_client import LLMJsonResult
from agente_bolsa.continuous_improvement.sandbox import GitSandbox
from agente_bolsa.storage import Store


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), text=True, capture_output=True)


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    (path / "docs").mkdir(exist_ok=True)
    (path / "src" / "agente_bolsa" / "tools").mkdir(parents=True, exist_ok=True)
    (path / "src" / "agente_bolsa" / "tools" / "risk.py").write_text("# risk\n", encoding="utf-8")
    (path / "docs" / "base.md").write_text("base\n", encoding="utf-8")
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "a@b.c")
    _git(path, "config", "user.name", "t")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "init")
    return path


def _settings(tmp_path, workspace, **overrides):
    values = {
        "DATA_DIR": tmp_path / "state",
        "IMPROVEMENT_DRY_RUN": False,
        "ALLOW_AUTO_APPLY_IMPROVEMENTS": False,
        "REQUIRE_HUMAN_APPROVAL_FOR_CODE_CHANGES": True,
        "ALLOW_LIVE_TRADING": False,
        "CONTINUOUS_IMPROVEMENT_WORKSPACE_DIR": workspace,
        "CI_SANDBOX_ENABLED": True,
        "CI_SANDBOX_FULL_SUITE": False,
    }
    values.update(overrides)
    return Settings(
        _env_file=None,
        **values,
    )


def _store_ready_proposal(store, *, proposal_id="ci_prop_codegen", target_identifier="docs/generated.md"):
    cycle_id = "ci_cycle_codegen"
    payload = {
        "proposal_type": "CODE_CHANGE",
        "target_component": "docs",
        "target_identifier": target_identifier,
        "rationale": "Crear un artefacto documental de bajo riesgo.",
        "expected_impact": "Mejora trazabilidad del laboratorio.",
        "risk_level": "LOW",
        "required_validations": ["tests"],
        "rollback_plan": "Eliminar el archivo generado.",
    }
    store.upsert_continuous_improvement_proposal(
        {
            "proposal_id": proposal_id,
            "cycle_id": cycle_id,
            "fingerprint": proposal_id,
            "proposal_type": "CODE_CHANGE",
            "target_component": "docs",
            "target_identifier": target_identifier,
            "status": "READY_TO_APPLY",
            "priority": "LOW",
            "risk_level": "LOW",
            "payload": payload,
            "guard": {"status": "READY_TO_APPLY"},
        }
    )
    store.save_continuous_improvement_validation(
        {
            "validation_id": "ci_val_codegen",
            "proposal_id": proposal_id,
            "cycle_id": cycle_id,
            "status": "READY_TO_APPLY",
            "validation_type": "manual_test",
            "payload": {"objective_status": "READY_TO_APPLY"},
        }
    )
    return proposal_id


class _FakeCodegenClient:
    def __init__(self, payload):
        self.payload = payload
        self.last_kwargs = {}

    def generate_json(self, messages, schema, **kwargs):  # noqa: ANN001
        self.last_kwargs = kwargs
        return LLMJsonResult(
            ok=True,
            llm_call_id="ci_llm_codegen_test",
            provider="fake",
            model="fake-codegen",
            payload=CodegenPatchResponse(**self.payload),
        )


pytestmark = pytest.mark.skipif(
    subprocess.run(["git", "--version"], capture_output=True).returncode != 0,
    reason="git no disponible",
)


def test_codegen_preview_produces_diff_artifact_and_no_applied_change(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")
    settings = _settings(tmp_path, repo)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    proposal_id = _store_ready_proposal(store)

    def _validate(self, **kw):  # noqa: ANN001
        steps = kw["steps"]
        assert steps[0][1][1:3] == ["-c", "from pathlib import Path; assert Path('docs/generated.md').exists()"]
        return {"ok": True, "steps": [{"step": "unit", "ok": True, "returncode": 0, "output": "ok"}]}

    monkeypatch.setattr(GitSandbox, "validate", _validate)
    client = _FakeCodegenClient(
        {
            "summary": "Crea documentacion demo.",
            "file_edits": [{"path": "docs/generated.md", "old": "", "new": "demo codegen\n"}],
            "test_commands": ["cmd /c echo ok"],
        }
    )

    result = CodegenPatchAgent(client=client).generate_for_proposal(
        settings=settings,
        store=store,
        proposal_id=proposal_id,
    )

    artifact = result["artifact"]
    assert result["ok"] is True
    assert artifact["artifact_type"] == "code_diff_preview"
    assert "diff --git a/docs/generated.md b/docs/generated.md" in artifact["content_text"]
    assert "+demo codegen" in artifact["content_text"]
    assert artifact["payload"]["applied"] is False
    assert artifact["payload"]["tests_ok"] is True
    assert store.continuous_improvement_applied_changes(limit=10) == []
    assert not (repo / "docs" / "generated.md").exists()
    assert client.last_kwargs["max_tokens"] >= 16000


def test_codegen_uses_codegen_role_model_when_general_model_is_glm(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")
    settings = _settings(
        tmp_path,
        repo,
        IMPROVEMENT_LLM_MODEL="glm-5.2",
        IMPROVEMENT_LLM_ORCHESTRATOR_MODEL="kimi-k2.6",
    )
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    proposal_id = _store_ready_proposal(store)
    monkeypatch.setattr(
        GitSandbox,
        "validate",
        lambda self, **kw: {"ok": True, "steps": [{"step": "unit", "ok": True}]},
    )
    client = _FakeCodegenClient(
        {
            "summary": "Crea documentacion demo.",
            "file_edits": [{"path": "docs/generated.md", "old": "", "new": "demo codegen\n"}],
            "test_commands": ["python -c \"assert True\""],
        }
    )

    result = CodegenPatchAgent(client=client).generate_for_proposal(
        settings=settings,
        store=store,
        proposal_id=proposal_id,
    )

    assert result["ok"] is True
    assert client.last_kwargs["model"] == "kimi-k2.6"


def test_codegen_rejects_target_outside_low_risk_allowlist(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    settings = _settings(tmp_path, repo)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    proposal_id = _store_ready_proposal(store, target_identifier="src/agente_bolsa/tools/risk.py")
    client = _FakeCodegenClient(
        {
            "summary": "Intento bloqueado.",
            "file_edits": [{"path": "src/agente_bolsa/tools/risk.py", "content": "# blocked\n"}],
            "test_commands": ["python -c \"assert True\""],
        }
    )

    result = CodegenPatchAgent(client=client).generate_for_proposal(
        settings=settings,
        store=store,
        proposal_id=proposal_id,
    )

    artifact = result["artifact"]
    assert result["ok"] is False
    assert result["status"] == "BLOCKED"
    assert artifact["artifact_type"] == "code_diff_codegen_blocked"
    assert "fuera del allowlist" in artifact["payload"]["error"]
    assert store.continuous_improvement_applied_changes(limit=10) == []
    assert (repo / "src" / "agente_bolsa" / "tools" / "risk.py").read_text(encoding="utf-8") == "# risk\n"
    sandboxes = repo / "sandboxes"
    assert not sandboxes.exists() or not any(sandboxes.iterdir())
