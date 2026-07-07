"""Manual LLM codegen for reviewable continuous-improvement diffs."""

from __future__ import annotations

import json
import os
import re
import shlex
from ast import Import, ImportFrom, parse
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agente_bolsa.models import new_id

from .experiments import AutoApplyCodeAgent, CodeDiffPreviewAgent
from .llm_client import ImprovementLLMClient
from .versioning import VERSION_FILE

if TYPE_CHECKING:  # pragma: no cover - solo anotaciones.
    from agente_bolsa.config import Settings
    from agente_bolsa.storage import Store


LOW_RISK_CODEGEN_ALLOWED_PREFIXES: tuple[str, ...] = (
    "src/agente_bolsa/__init__.py",
    "src/agente_bolsa/continuous_improvement/",
    "src/agente_bolsa/tools/operational_",
    "tests/",
    "docs/",
)
CODEGEN_MIN_MAX_TOKENS = 32000
CODEGEN_SELF_CORRECTION_ROUNDS = 2
CODEGEN_FULL_CONTEXT_MAX_LINES = 900
CODEGEN_FULL_CONTENT_MAX_LINES = 900
CODEGEN_DATA_SAMPLE_LINES = 5
DATA_PATH_RE = re.compile(r"\bdata/[A-Za-z0-9_./-]+\.(?:jsonl|json|csv|tsv)\b")
CODEGEN_CONTEXT_ALLOWED_PREFIXES: tuple[str, ...] = (*LOW_RISK_CODEGEN_ALLOWED_PREFIXES, "scripts/")


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

    @field_validator("patch", mode="before")
    @classmethod
    def _normalize_patch(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value)


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

        messages = self._messages(settings, proposal)
        last_preview: dict[str, Any] | None = None
        for correction_round in range(CODEGEN_SELF_CORRECTION_ROUNDS + 1):
            llm_result = (self.client or ImprovementLLMClient(settings)).generate_json(
                messages,
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
                        "correction_round": correction_round,
                        "applied": False,
                    },
                )
                return {"ok": False, "status": "FAILED", "proposal_id": proposal_id, "artifact": artifact}

            generated = llm_result.payload
            self._save_attempt_artifact(
                store,
                proposal_id=proposal_id,
                generated=generated,
                llm_result=llm_result,
                correction_round=correction_round,
            )
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
                        "correction_round": correction_round,
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
            last_preview = artifact
            status = str((artifact.get("payload") or {}).get("status") or artifact.get("artifact_type") or "")
            if status == "READY_FOR_HUMAN_REVIEW" or not self._is_correctable_preview_error(artifact):
                return {
                    "ok": status == "READY_FOR_HUMAN_REVIEW",
                    "status": status,
                    "proposal_id": proposal_id,
                    "llm_call_id": llm_result.llm_call_id,
                    "provider": llm_result.provider,
                    "model": llm_result.model,
                    "artifact": artifact,
                    "correction_round": correction_round,
                }
            if correction_round >= CODEGEN_SELF_CORRECTION_ROUNDS:
                break
            messages = self._correction_messages(
                settings=settings,
                proposal=proposal,
                previous_messages=messages,
                generated=generated,
                artifact=artifact,
                correction_round=correction_round + 1,
            )

        artifact = last_preview or {}
        status = str((artifact.get("payload") or {}).get("status") or artifact.get("artifact_type") or "FAILED")
        return {
            "ok": False,
            "status": status,
            "proposal_id": proposal_id,
            "artifact": artifact,
            "correction_round": CODEGEN_SELF_CORRECTION_ROUNDS,
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

    def _save_attempt_artifact(
        self,
        store: Store,
        *,
        proposal_id: str,
        generated: CodegenPatchResponse,
        llm_result: Any,
        correction_round: int,
    ) -> dict[str, Any]:
        raw_payload = generated.model_dump(mode="json")
        return self._save_artifact(
            store,
            proposal_id=proposal_id,
            artifact_type="code_diff_attempt",
            content_text=json.dumps(raw_payload, ensure_ascii=False, indent=2)[-200000:],
            payload={
                "status": "GENERATED",
                "correction_round": correction_round,
                "llm_call_id": llm_result.llm_call_id,
                "provider": llm_result.provider,
                "model": llm_result.model,
                "file_edit_count": len(generated.file_edits),
                "has_patch": bool(str(generated.patch or "").strip()),
                "test_commands": generated.test_commands,
            },
        )

    def _is_correctable_preview_error(self, artifact: dict[str, Any]) -> bool:
        payload = artifact.get("payload") or {}
        validation = payload.get("validation") or {}
        steps = validation.get("steps") or []
        if steps and str((steps[0] or {}).get("step") or "") == "apply_patch" and not (steps[0] or {}).get("ok"):
            return True
        if payload.get("status") == "REJECTED_BY_TESTS" and validation.get("ok") is False:
            return True
        error = self._artifact_error_text(artifact)
        return any(term in error for term in ("No se encontro bloque old", "git apply fallo", "Falta patch", "file_edits invalido"))

    def _artifact_error_text(self, artifact: dict[str, Any]) -> str:
        payload = artifact.get("payload") or {}
        error = str(payload.get("error") or "")
        validation = payload.get("validation") or {}
        failed_steps = [
            f"{step.get('step')}: {step.get('output')}"
            for step in validation.get("steps", []) or []
            if isinstance(step, dict) and not step.get("ok")
        ]
        if failed_steps:
            return "\n".join([error, *failed_steps]).strip()
        return error or str(artifact.get("content_text") or "")

    def _correction_messages(
        self,
        *,
        settings: Settings,
        proposal: dict[str, Any],
        previous_messages: list[dict[str, str]],
        generated: CodegenPatchResponse,
        artifact: dict[str, Any],
        correction_round: int,
    ) -> list[dict[str, str]]:
        error = self._artifact_error_text(artifact)
        correction_payload = {
            "correction_round": correction_round,
            "application_error": error,
            "previous_response": generated.model_dump(mode="json"),
            "real_target_context": self._real_target_context(settings.improvement_workspace_dir, proposal, generated),
            "data_samples": self._data_samples(settings.improvement_workspace_dir, proposal),
            "instruction": (
                "Regenera el JSON completo. Copia cada bloque old VERBATIM del contexto real adjunto, "
                "sin normalizar espacios ni cambiar saltos de linea. Usa bloques old cortos y unicos. "
                "Si el archivo es nuevo o un archivo existente con "
                f"{CODEGEN_FULL_CONTENT_MAX_LINES} lineas o menos, puedes usar {{path, content}}."
            ),
        }
        return [
            *previous_messages,
            {"role": "assistant", "content": json.dumps(generated.model_dump(mode="json"), ensure_ascii=False)},
            {"role": "user", "content": json.dumps(correction_payload, ensure_ascii=False, indent=2)},
        ]

    def _real_target_context(
        self,
        workspace: Path,
        proposal: dict[str, Any],
        generated: CodegenPatchResponse,
    ) -> list[dict[str, Any]]:
        candidates = _candidate_paths_from_proposal(proposal)
        for item in generated.file_edits:
            if isinstance(item, dict) and item.get("path"):
                candidates.append(str(item["path"]).strip().replace("\\", "/"))
        candidates = list(dict.fromkeys(candidates))
        workspace = workspace.resolve()
        context: list[dict[str, Any]] = []
        for rel in candidates[:6]:
            if not _is_context_allowed_path(rel):
                continue
            path = (workspace / rel).resolve()
            try:
                path.relative_to(workspace)
            except ValueError:
                continue
            if not path.exists():
                context.append({"path": rel, "exists": False, "content": "", "lines": 0, "truncated": False})
                continue
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                context.append({"path": rel, "exists": True, "error": str(exc), "truncated": True})
                continue
            lines = text.splitlines()
            if len(lines) <= CODEGEN_FULL_CONTEXT_MAX_LINES:
                context.append(
                    {
                        "path": rel,
                        "exists": True,
                        "content": text,
                        "chars": len(text),
                        "lines": len(lines),
                        "truncated": False,
                        "content_mode_allowed": len(lines) <= CODEGEN_FULL_CONTENT_MAX_LINES,
                    }
                )
            else:
                excerpt = "\n".join([*lines[:120], "... <TRUNCATED> ...", *lines[-120:]])
                context.append(
                    {
                        "path": rel,
                        "exists": True,
                        "content": excerpt,
                        "chars": len(text),
                        "lines": len(lines),
                        "truncated": True,
                        "content_mode_allowed": False,
                    }
                )
        return context

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
        data_samples = self._data_samples(settings.improvement_workspace_dir, proposal)
        target_identifier = str(proposal.get("target_identifier") or payload.get("target_identifier") or "")
        target_rule = (
            "Debes modificar el target_identifier de la propuesta cuando sea una ruta de codigo existente; "
            "generar solo tests o documentacion no satisface la propuesta. "
            if not target_identifier.replace("\\", "/").startswith("tests/")
            else "El target_identifier es un test existente; en este caso un cambio solo en tests SI satisface la propuesta. "
        )
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
            "data_samples": data_samples,
        }
        return [
            {
                "role": "system",
                "content": (
                    "Eres un agente de codegen de bajo riesgo. Devuelve JSON valido con las claves "
                    "summary, file_edits, patch, test_commands y risk_notes. No escribas prosa fuera del JSON. "
                    "Responde de forma directa y compacta; no expliques razonamiento ni repitas contexto. "
                    "Debes producir un cambio pequeno, revisable y reversible. Solo puedes tocar rutas bajo: "
                    f"{', '.join(LOW_RISK_CODEGEN_ALLOWED_PREFIXES)}. "
                    f"{target_rule}"
                    "Nunca modifiques risk.py, kernel.py, broker.py, execution.py, config.py ni .env. "
                    f"Nunca modifiques {VERSION_FILE}; el pipeline la bumpea de forma determinista despues de aplicar tu cambio. "
                    "Para archivos existentes grandes usa file_edits {path, old, new}; el bloque old debe copiarse "
                    "VERBATIM del contexto proporcionado, sin reformatear ni normalizar espacios, y debe ser corto y unico. "
                    "Para archivos nuevos o existentes con "
                    f"{CODEGEN_FULL_CONTENT_MAX_LINES} lineas o menos puedes usar {{path, content}} "
                    "con el contenido completo. "
                    "Si hay data_samples, respeta ese esquema real y crea al menos un test con una linea real copiada literalmente. "
                    "Los tests deben cubrir valores null y claves ausentes de campos anidados que aparezcan en esas muestras, "
                    "por ejemplo objetos internos opcionales como decision.order."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False, indent=2),
            },
        ]

    def _context_files(self, workspace: Path, proposal: dict[str, Any]) -> list[dict[str, Any]]:
        candidates = _context_candidate_paths(workspace, proposal)
        workspace = workspace.resolve()
        context: list[dict[str, Any]] = []
        for rel in candidates[:4]:
            if not _is_context_allowed_path(rel):
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
            lines = text.splitlines()
            if len(lines) <= CODEGEN_FULL_CONTEXT_MAX_LINES:
                context.append(
                    {
                        "path": rel,
                        "content": text,
                        "chars": len(text),
                        "lines": len(lines),
                        "truncated": False,
                        "content_mode_allowed": len(lines) <= CODEGEN_FULL_CONTENT_MAX_LINES,
                    }
                )
            else:
                excerpt = "\n".join([*lines[:120], "... <TRUNCATED> ...", *lines[-120:]])
                context.append(
                    {
                        "path": rel,
                        "content": excerpt,
                        "chars": len(text),
                        "lines": len(lines),
                        "truncated": True,
                        "content_mode_allowed": False,
                    }
                )
        return context

    def _data_samples(self, workspace: Path, proposal: dict[str, Any]) -> list[dict[str, Any]]:
        paths = _data_paths_from_proposal(proposal)
        workspace = workspace.resolve()
        samples: list[dict[str, Any]] = []
        for rel in paths[:6]:
            path = (workspace / rel).resolve()
            try:
                path.relative_to(workspace)
            except ValueError:
                continue
            if not path.exists() or not path.is_file():
                continue
            try:
                lines = path.read_text(encoding="utf-8-sig").splitlines()
            except OSError as exc:
                samples.append({"path": rel, "exists": True, "error": str(exc)})
                continue
            head = lines[:CODEGEN_DATA_SAMPLE_LINES]
            tail = lines[-CODEGEN_DATA_SAMPLE_LINES:] if len(lines) > CODEGEN_DATA_SAMPLE_LINES else []
            samples.append(
                {
                    "path": rel,
                    "exists": True,
                    "line_count": len(lines),
                    "head": head,
                    "tail": tail,
                    "truncated": len(lines) > CODEGEN_DATA_SAMPLE_LINES * 2,
                    "instruction": "Usa esta muestra para inferir el esquema real; no inventes nombres de campos.",
                }
            )
        return samples

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


def _is_context_allowed_path(rel: str) -> bool:
    rel = rel.replace("\\", "/").lstrip("/")
    if rel == ".env" or ".." in rel.split("/"):
        return False
    return any(rel.startswith(prefix) for prefix in CODEGEN_CONTEXT_ALLOWED_PREFIXES)


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


def _context_candidate_paths(workspace: Path, proposal: dict[str, Any]) -> list[str]:
    candidates = _candidate_paths_from_proposal(proposal)
    if not candidates:
        return candidates
    if not all(path.startswith("tests/") for path in candidates):
        return candidates
    payload = proposal.get("payload") or {}
    modules = list(dict.fromkeys([*_modules_under_test_from_payload(payload), *_modules_under_test_from_tests(workspace, candidates)]))
    return list(dict.fromkeys([*candidates, *modules]))


def _modules_under_test_from_payload(payload: dict[str, Any]) -> list[str]:
    value = payload.get("modules_under_test")
    if isinstance(value, str) and value.strip():
        return [_module_name_to_repo_path(value.strip())]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                result.append(_module_name_to_repo_path(item.strip()))
        return result
    return []


def _modules_under_test_from_tests(workspace: Path, test_paths: list[str]) -> list[str]:
    result: list[str] = []
    workspace = workspace.resolve()
    for rel in test_paths:
        path = (workspace / rel).resolve()
        try:
            path.relative_to(workspace)
        except ValueError:
            continue
        if not path.exists() or not path.is_file():
            continue
        try:
            tree = parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            if isinstance(node, Import):
                for alias in node.names:
                    target = _module_name_to_repo_path(alias.name)
                    if target:
                        result.append(target)
            elif isinstance(node, ImportFrom):
                module_name = str(node.module or "")
                if not module_name.startswith("agente_bolsa."):
                    continue
                imported_names = [str(alias.name or "").strip() for alias in node.names if str(alias.name or "").strip()]
                target = _import_from_to_repo_path(workspace, module_name, imported_names)
                if target:
                    result.append(target)
    return list(dict.fromkeys(result))


def _import_from_to_repo_path(workspace: Path, module_name: str, imported_names: list[str]) -> str | None:
    module_target = _module_name_to_repo_path(module_name)
    if module_target and (workspace / module_target).exists():
        return module_target
    package_target = _module_name_to_package_init(module_name)
    package_path = workspace / package_target
    if not package_path.exists():
        return module_target if module_target and (workspace / module_target).exists() else None
    for imported_name in imported_names:
        candidate = package_path.parent / f"{imported_name}.py"
        if candidate.exists():
            try:
                return candidate.resolve().relative_to(workspace.resolve()).as_posix()
            except ValueError:
                return None
    return package_target


def _module_name_to_repo_path(module_name: str) -> str | None:
    normalized = str(module_name or "").strip().replace("\\", "/")
    if not normalized:
        return None
    if normalized.endswith(".py") and "/" in normalized:
        return normalized.lstrip("/")
    if normalized == "agente_bolsa":
        return VERSION_FILE
    if normalized.startswith("agente_bolsa."):
        suffix = normalized.removeprefix("agente_bolsa.").replace(".", "/")
        return f"src/agente_bolsa/{suffix}.py"
    if normalized.startswith("src/") or normalized.startswith("tests/") or normalized.startswith("docs/") or normalized.startswith("scripts/"):
        return normalized.lstrip("/")
    return None


def _module_name_to_package_init(module_name: str) -> str:
    suffix = str(module_name or "").strip().removeprefix("agente_bolsa.").replace(".", "/")
    return f"src/agente_bolsa/{suffix}/__init__.py"


def _data_paths_from_proposal(proposal: dict[str, Any]) -> list[str]:
    payload = proposal.get("payload") or {}
    haystack = json.dumps(
        {
            "proposal": {
                key: proposal.get(key)
                for key in ("target_component", "target_identifier", "proposal_type", "risk_level")
            },
            "payload": payload,
        },
        ensure_ascii=False,
        default=str,
    )
    candidates = [match.group(0).strip().replace("\\", "/") for match in DATA_PATH_RE.finditer(haystack)]
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
