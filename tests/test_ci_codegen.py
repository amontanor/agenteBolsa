"""Tests del codegen manual de diffs revisables."""

import json
import sqlite3
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


class _SequenceCodegenClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def generate_json(self, messages, schema, **kwargs):  # noqa: ANN001
        self.calls.append({"messages": messages, "kwargs": kwargs})
        payload = self.payloads.pop(0)
        return LLMJsonResult(
            ok=True,
            llm_call_id=f"ci_llm_codegen_test_{len(self.calls)}",
            provider="fake",
            model="fake-codegen",
            payload=CodegenPatchResponse(**payload),
        )


pytestmark = pytest.mark.skipif(
    subprocess.run(["git", "--version"], capture_output=True).returncode != 0,
    reason="git no disponible",
)


def _proposal_artifacts(store):
    with sqlite3.connect(store.database_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT artifact_type, content_text, payload_json
            FROM continuous_improvement_proposal_artifacts
            ORDER BY created_at
            """
        ).fetchall()
    return [
        {
            "artifact_type": row["artifact_type"],
            "content_text": row["content_text"],
            "payload": json.loads(row["payload_json"] or "{}"),
        }
        for row in rows
    ]


def test_codegen_response_accepts_null_patch():
    response = CodegenPatchResponse(summary="ok", file_edits=[], patch=None)

    assert response.patch == ""


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
    assert client.last_kwargs["max_tokens"] >= 32000


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


def test_codegen_self_corrects_after_invalid_old_block(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")
    settings = _settings(tmp_path, repo)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    proposal_id = _store_ready_proposal(store, target_identifier="docs/base.md")
    monkeypatch.setattr(
        GitSandbox,
        "validate",
        lambda self, **kw: {"ok": True, "steps": [{"step": "unit", "ok": True}]},
    )
    client = _SequenceCodegenClient(
        [
            {
                "summary": "Intento con old invalido.",
                "file_edits": [{"path": "docs/base.md", "old": "missing\n", "new": "fixed\n"}],
                "test_commands": ["python -c \"assert True\""],
            },
            {
                "summary": "Correccion con old exacto.",
                "file_edits": [{"path": "docs/base.md", "old": "base\n", "new": "base\nfixed\n"}],
                "test_commands": ["python -c \"assert True\""],
            },
        ]
    )

    result = CodegenPatchAgent(client=client).generate_for_proposal(
        settings=settings,
        store=store,
        proposal_id=proposal_id,
    )

    artifacts = _proposal_artifacts(store)
    attempts = [item for item in artifacts if item["artifact_type"] == "code_diff_attempt"]
    assert result["ok"] is True
    assert result["correction_round"] == 1
    assert len(client.calls) == 2
    assert len(attempts) == 2
    assert "No se encontro bloque old" in client.calls[1]["messages"][-1]["content"]
    assert "base\\n" in client.calls[1]["messages"][-1]["content"]


def test_codegen_exhausts_two_failed_corrections_and_records_attempts(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    settings = _settings(tmp_path, repo)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    proposal_id = _store_ready_proposal(store, target_identifier="docs/base.md")
    client = _SequenceCodegenClient(
        [
            {
                "summary": "Intento invalido.",
                "file_edits": [{"path": "docs/base.md", "old": f"missing-{idx}\n", "new": "fixed\n"}],
                "test_commands": ["python -c \"assert True\""],
            }
            for idx in range(3)
        ]
    )

    result = CodegenPatchAgent(client=client).generate_for_proposal(
        settings=settings,
        store=store,
        proposal_id=proposal_id,
    )

    artifacts = _proposal_artifacts(store)
    attempts = [item for item in artifacts if item["artifact_type"] == "code_diff_attempt"]
    invalid = [item for item in artifacts if item["artifact_type"] == "code_diff_preview_invalid"]
    assert result["ok"] is False
    assert result["status"] == "REJECTED_BY_TESTS"
    assert len(client.calls) == 3
    assert [item["payload"]["correction_round"] for item in attempts] == [0, 1, 2]
    assert len(invalid) == 3


def test_codegen_accepts_full_content_for_new_file(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")
    settings = _settings(tmp_path, repo)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    proposal_id = _store_ready_proposal(store, target_identifier="docs/new_full_file.md")
    monkeypatch.setattr(
        GitSandbox,
        "validate",
        lambda self, **kw: {"ok": True, "steps": [{"step": "unit", "ok": True}]},
    )
    client = _SequenceCodegenClient(
        [
            {
                "summary": "Crea fichero nuevo completo.",
                "file_edits": [{"path": "docs/new_full_file.md", "content": "nuevo\ncompleto\n"}],
                "test_commands": ["python -c \"assert True\""],
            }
        ]
    )

    result = CodegenPatchAgent(client=client).generate_for_proposal(
        settings=settings,
        store=store,
        proposal_id=proposal_id,
    )

    assert result["ok"] is True
    assert "new_full_file.md" in result["artifact"]["content_text"]


def test_codegen_prompt_includes_full_current_target_context(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    settings = _settings(tmp_path, repo)
    long_text = "".join(f"line {idx:03d} - {'x' * 48}\n" for idx in range(500))
    (repo / "docs" / "long.md").write_text(long_text, encoding="utf-8")
    proposal = {
        "proposal_id": "ci_prop_context",
        "proposal_type": "CODE_CHANGE",
        "target_component": "docs",
        "target_identifier": "docs/long.md",
        "risk_level": "LOW",
        "payload": {"target_identifier": "docs/long.md", "rationale": "test"},
    }

    messages = CodegenPatchAgent()._messages(settings, proposal)
    user_payload = json.loads(messages[1]["content"])
    context_file = user_payload["context_files"][0]

    assert context_file["path"] == "docs/long.md"
    assert context_file["content"] == long_text
    assert context_file["truncated"] is False
    assert context_file["lines"] == 500


def test_codegen_prompt_includes_real_data_file_sample(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    settings = _settings(tmp_path, repo)
    log_dir = repo / "data" / "research" / "core_sleeve"
    log_dir.mkdir(parents=True)
    real_line = (
        '{"created_at": "2026-07-02T11:12:06+00:00", "status": "would_submit", '
        '"symbol": "SPY", "data_date": "2026-07-01", "exposure": 0.656465, '
        '"decision": {"order": {"side": "buy", "notional": 13914.44}, "reason": "buy_to_target"}}'
    )
    (log_dir / "core_sleeve_log.jsonl").write_text(real_line + "\n", encoding="utf-8")
    proposal = {
        "proposal_id": "ci_prop_context_data",
        "proposal_type": "CODE_CHANGE",
        "target_component": "continuous_improvement",
        "target_identifier": "docs/base.md",
        "risk_level": "LOW",
        "payload": {
            "target_identifier": "docs/base.md",
            "proposed_value": "Leer data/research/core_sleeve/core_sleeve_log.jsonl y mostrar exposure + decision.order.",
            "rationale": "test",
        },
    }

    messages = CodegenPatchAgent()._messages(settings, proposal)
    user_payload = json.loads(messages[1]["content"])
    sample = user_payload["data_samples"][0]

    assert sample["path"] == "data/research/core_sleeve/core_sleeve_log.jsonl"
    assert sample["head"] == [real_line]
    assert "decision" in sample["head"][0]
    assert "target_exposure" not in sample["head"][0]


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
