"""Manual LLM codegen for reviewable continuous-improvement diffs."""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agente_bolsa.models import new_id

from .experiments import AutoApplyCodeAgent, CodeDiffPreviewAgent
from .llm_client import ImprovementLLMClient

if TYPE_CHECKING:  # pragma: no cover - solo anotaciones.
    from agente_bolsa.config import Settings
    from agente_bolsa.storage import Store


LOW_RISK_CODEGEN_ALLOWED_PREFIXES: tuple[str, ...] = (
    "src/agente_bolsa/continuous_improvement/",
    "src/agente_bolsa/tools/operational_",
    "tests/",
    "docs/",
)
CODEGEN_MIN_MAX_TOKENS = 16000


class CodegenPatchResponse(BaseModel):
    """Respuesta JSON esperada del LLM codegen."""

    model_config = ConfigDict(extra="ignore")

    summary: str = ""
    file_edits: list[dict[str, Any]] = Field(default_factory=list)
    patch: str = ""
    test_commands: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)

    @field_validator("file_edits", mode="before")
    @classmethod
    def _normalize_file_edits(cls, value: Any) -> list[Any]:
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list):
            return value
        return []

    @field_validator("test_commands", "risk_notes", mode="before")
    @classmethod
    def _normalize_string_list(cls, value: Any) -> list[str]:
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []


class CodegenPatchAgent:
    """Convierte propuestas CODE_CHANGE en payloads aplicables y revisables."""

    BLOCKED_ARTIFACT = "code_diff_codegen_blocked"
    FAILED_ARTIFACT = "code_diff_codegen_failed"

    def __init__(self, client: ImprovementLLMClient | None = None) -> None:
        self.client = client
        self._guard = AutoApplyCodeAgent()
        self._preview = CodeDiffPreviewAgent()

    def generate_for_proposal(
        self,
        *,
        settings: Settings,
        store: Store,
        proposal_id: str,
    ) -> dict[str, Any]:
        proposal = store.continuous_improvement_proposal(proposal_id)
        if proposal is None:
            return {"ok": False, "status": "NOT_FOUND", "error": f"Propuesta no encontrada: {proposal_id}"}
        blocked = self._proposal_blocked_reason(proposal)
        if blocked:
            artifact = self._save_artifact(
                store,
                proposal_id=proposal_id,
                artifact_type=self.BLOCKED_ARTIFACT,
                content_text=blocked,
                payload={"status": "BLOCKED", "error": blocked, "applied": False},
            )
            return {"ok": False, "status": "BLOCKED", "proposal_id": proposal_id, "artifact": artifact}

        llm_result = (self.client or ImprovementLLMClient(settings)).generate_json(
            self._messages(settings, proposal),
            CodegenPatchResponse.model_json_schema(),
            model=_codegen_model(settings),
            response_model=CodegenPatchResponse,
            normalize_response=False,
            temperature=0.0,
            max_tokens=_codegen_max_tokens(settings),
            route="agents",
        )
        if not llm_result.ok or not isinstance(llm_result.payload, CodegenPatchResponse):
            error = llm_result.error or "LLM codegen no devolvio un patch valido."
            artifact = self._save_artifact(
                store,
                proposal_id=proposal_id,
                artifact_type=self.FAILED_ARTIFACT,
                content_text=error,
                payload={
                    "status": "FAILED",
                    "error": error,
                    "llm_call_id": llm_result.llm_call_id,
                    "provider": llm_result.provider,
                    "model": llm_result.model,
                    "applied": False,
                },
            )
            return {"ok": False, "status": "FAILED", "proposal_id": proposal_id, "artifact": artifact}

        generated = llm_result.payload
        payload = self._generated_payload(proposal, generated, llm_result)
        scope_error = self._scope_error(settings.improvement_workspace_dir, payload)
        if scope_error:
            artifact = self._save_artifact(
                store,
                proposal_id=proposal_id,
                artifact_type=self.BLOCKED_ARTIFACT,
                content_text=scope_error,
                payload={
                    "status": "BLOCKED",
                    "error": scope_error,
                    "llm_call_id": llm_result.llm_call_id,
                    "provider": llm_result.provider,
                    "model": llm_result.model,
                    "generated_summary": generated.summary,
                    "applied": False,
                },
            )
            return {"ok": False, "status": "BLOCKED", "proposal_id": proposal_id, "artifact": artifact}

        preview_proposal = {**proposal, "payload": payload}
        validation = self._ready_validation(proposal)
        artifact = self._preview.generate(
            settings=settings,
            store=store,
            proposal=preview_proposal,
            validation=validation,
        )
        status = str((artifact.get("payload") or {}).get("status") or artifact.get("artifact_type") or "")
        return {
            "ok": status == "READY_FOR_HUMAN_REVIEW",
            "status": status,
            "proposal_id": proposal_id,
            "llm_call_id": llm_result.llm_call_id,
            "provider": llm_result.provider,
            "model": llm_result.model,
            "artifact": artifact,
        }

    def _proposal_blocked_reason(self, proposal: dict[str, Any]) -> str | None:
        if proposal.get("proposal_type") != "CODE_CHANGE":
            return "Solo se permite codegen para propuestas CODE_CHANGE."
        if str(proposal.get("status") or "").upper() != "READY_TO_APPLY":
            return "La propuesta debe estar READY_TO_APPLY antes de generar diff."
        if str(proposal.get("risk_level") or "").upper() == "HIGH":
            return "CODE_CHANGE HIGH requiere revision humana previa; codegen manual no lo procesa."
        return None

    def _generated_payload(
        self,
        proposal: dict[str, Any],
        generated: CodegenPatchResponse,
        llm_result: Any,
    ) -> dict[str, Any]:
        base = dict(proposal.get("payload") or {})
        file_edits = [dict(item) for item in generated.file_edits if isinstance(item, dict)]
        patch = str(generated.patch or "").strip()
        test_commands = _safe_test_commands(generated.test_commands, file_edits)
        base.update(
            {
                "file_edits": file_edits,
                "patch": patch,
                "test_commands": test_commands or ["python -m pytest tests/test_ci_sandbox.py -q"],
                "codegen": {
                    "summary": generated.summary,
                    "risk_notes": generated.risk_notes,
                    "llm_call_id": llm_result.llm_call_id,
                    "provider": llm_result.provider,
                    "model": llm_result.model,
                    "low_risk_allowlist": list(LOW_RISK_CODEGEN_ALLOWED_PREFIXES),
                },
            }
        )
        return base

    def _scope_error(self, workspace: Path, payload: dict[str, Any]) -> str | None:
        file_edits = payload.get("file_edits") or payload.get("files")
        patch_text = str(payload.get("patch") or "").strip()
        if not (file_edits or patch_text):
            return "El LLM no devolvio file_edits ni patch."
        targets = self._guard._target_paths(workspace, file_edits=file_edits, patch_text=patch_text)
        if not targets:
            return "El LLM no declaro archivos objetivo."
        workspace = workspace.resolve()
        for path in targets:
            try:
                rel = path.resolve().relative_to(workspace).as_posix()
            except ValueError:
                return f"{path} queda fuera del workspace."
            if not _is_low_risk_codegen_path(rel):
                return f"{rel} fuera del allowlist de codegen nivel 1."
        return None

    def _ready_validation(self, proposal: dict[str, Any]) -> dict[str, Any]:
        validations = proposal.get("validations") or []
        for item in validations:
            if str(item.get("status") or "").upper() == "READY_TO_APPLY":
                return item
        return {
            "validation_id": new_id("ci_val_codegen"),
            "proposal_id": proposal["proposal_id"],
            "cycle_id": proposal.get("cycle_id") or "",
            "status": "READY_TO_APPLY",
            "validation_type": "manual_codegen_entrypoint",
            "payload": {"objective_status": "READY_TO_APPLY"},
        }

    def _messages(self, settings: Settings, proposal: dict[str, Any]) -> list[dict[str, str]]:
        payload = proposal.get("payload") or {}
        context_files = self._context_files(settings.improvement_workspace_dir, proposal)
        user_payload = {
            "proposal_id": proposal.get("proposal_id"),
            "target_component": proposal.get("target_component"),
            "target_identifier": proposal.get("target_identifier"),
            "risk_level": proposal.get("risk_level"),
            "rationale": payload.get("rationale") or "",
            "proposed_value": payload.get("proposed_value") or "",
            "expected_impact": payload.get("expected_impact") or "",
            "rollback_plan": payload.get("rollback_plan") or "",
            "context_files": context_files,
        }
        return [
            {
                "role": "system",
                "content": (
                    "Eres un agente de codegen de bajo riesgo. Devuelve JSON valido con las claves "
                    "summary, file_edits, patch, test_commands y risk_notes. No escribas prosa fuera del JSON. "
                    "Debes producir un cambio pequeno, revisable y reversible. Solo puedes tocar rutas bajo: "
                    f"{', '.join(LOW_RISK_CODEGEN_ALLOWED_PREFIXES)}. "
                    "Nunca modifiques risk.py, kernel.py, broker.py, execution.py, config.py ni .env. "
                    "Prefiere file_edits con {path, old, new} o {path, content}. Incluye tests concretos."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False, indent=2),
            },
        ]

    def _context_files(self, workspace: Path, proposal: dict[str, Any]) -> list[dict[str, str]]:
        candidates = _candidate_paths_from_proposal(proposal)
        workspace = workspace.resolve()
        context: list[dict[str, str]] = []
        for rel in candidates[:4]:
            if not _is_low_risk_codegen_path(rel):
                continue
            path = (workspace / rel).resolve()
            try:
                path.relative_to(workspace)
            except ValueError:
                continue
            if not path.exists() or not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            context.append({"path": rel, "content": text[:12000]})
        return context

    def _save_artifact(
        self,
        store: Store,
        *,
        proposal_id: str,
        artifact_type: str,
        content_text: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        item = {
            "artifact_id": new_id("ci_artifact"),
            "proposal_id": proposal_id,
            "artifact_type": artifact_type,
            "content_text": content_text,
            "payload": payload,
        }
        store.save_continuous_improvement_proposal_artifact(item)
        return item


def generate_code_diff_for_proposal(
    *,
    settings: Settings,
    store: Store,
    proposal_id: str,
    client: ImprovementLLMClient | None = None,
) -> dict[str, Any]:
    return CodegenPatchAgent(client=client).generate_for_proposal(
        settings=settings,
        store=store,
        proposal_id=proposal_id,
    )


def _codegen_max_tokens(settings: Settings) -> int:
    configured = int(getattr(settings, "improvement_llm_max_tokens", CODEGEN_MIN_MAX_TOKENS) or 0)
    return max(configured, CODEGEN_MIN_MAX_TOKENS)


def _codegen_model(settings: Settings) -> str:
    override = os.environ.get("IMPROVEMENT_LLM_CODEGEN_MODEL", "").strip()
    if override:
        return override
    configured = str(getattr(settings, "improvement_llm_model", "") or "").strip()
    if configured.lower().startswith("glm-"):
        return str(getattr(settings, "improvement_llm_orchestrator_model", "") or configured)
    return configured


def create_demo_codegen_proposal(store: Store) -> str:
    proposal_id = new_id("ci_prop_codegen_demo")
    cycle_id = new_id("ci_cycle_codegen_demo")
    payload = {
        "proposal_type": "CODE_CHANGE",
        "target_component": "docs",
        "target_identifier": "docs/ci_codegen_demo.md",
        "current_value": "No existe una nota de demo para codegen manual.",
        "proposed_value": "Crear docs/ci_codegen_demo.md con una nota corta y reversible.",
        "rationale": "Demo de bajo riesgo para comprobar codegen LLM -> sandbox -> artefacto sin aplicar.",
        "expected_impact": "Permite verificar la cadena de generacion de diff sin tocar runtime de trading.",
        "risk_level": "LOW",
        "required_validations": ["tests"],
        "rollback_plan": "Eliminar docs/ci_codegen_demo.md si no se acepta el cambio.",
        "demo": True,
    }
    store.upsert_continuous_improvement_proposal(
        {
            "proposal_id": proposal_id,
            "cycle_id": cycle_id,
            "fingerprint": proposal_id,
            "proposal_type": "CODE_CHANGE",
            "target_component": "docs",
            "target_identifier": "docs/ci_codegen_demo.md",
            "status": "READY_TO_APPLY",
            "priority": "LOW",
            "risk_level": "LOW",
            "payload": payload,
            "guard": {"status": "READY_TO_APPLY", "reason": "manual_codegen_demo"},
        }
    )
    store.save_continuous_improvement_validation(
        {
            "validation_id": new_id("ci_val_codegen_demo"),
            "proposal_id": proposal_id,
            "cycle_id": cycle_id,
            "status": "READY_TO_APPLY",
            "validation_type": "manual_codegen_demo",
            "payload": {"objective_status": "READY_TO_APPLY", "demo": True},
        }
    )
    return proposal_id


def _is_low_risk_codegen_path(rel: str) -> bool:
    rel = rel.replace("\\", "/").lstrip("/")
    if rel == ".env" or ".." in rel.split("/"):
        return False
    return any(rel.startswith(prefix) for prefix in LOW_RISK_CODEGEN_ALLOWED_PREFIXES)


def _candidate_paths_from_proposal(proposal: dict[str, Any]) -> list[str]:
    payload = proposal.get("payload") or {}
    candidates: list[str] = []
    for key in ("target_identifier", "target_path", "path"):
        value = proposal.get(key) if key == "target_identifier" else payload.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip().replace("\\", "/"))
    for key in ("files", "target_files"):
        value = payload.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    candidates.append(item.strip().replace("\\", "/"))
                elif isinstance(item, dict) and item.get("path"):
                    candidates.append(str(item["path"]).strip().replace("\\", "/"))
    return list(dict.fromkeys(candidates))


def _safe_test_commands(commands: list[str], file_edits: list[dict[str, Any]]) -> list[str]:
    safe: list[str] = []
    for command in commands:
        text = str(command).strip()
        if not text:
            continue
        try:
            parts = shlex.split(text, posix=True)
        except ValueError:
            continue
        if parts and parts[0].lower() in {"python", "python.exe", "pytest", "pytest.exe", "ruff", "ruff.exe"}:
            safe.append(text)
    if safe:
        return safe
    targets = [
        str(item.get("path")).replace("\\", "/")
        for item in file_edits
        if isinstance(item, dict) and str(item.get("path") or "").strip()
    ]
    targets = list(dict.fromkeys(targets))
    if targets:
        checks = " and ".join(f"Path({target!r}).exists()" for target in targets)
        return [f'python -c "from pathlib import Path; assert {checks}"']
    return ["python -m pytest tests/test_ci_sandbox.py -q"]
