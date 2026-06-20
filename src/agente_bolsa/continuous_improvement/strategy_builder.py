"""ProgrammerAgent end-to-end: de hipotesis a estrategia SHADOW (T1.4).

Toma una especificacion (derivada de una hipotesis), pide al modelo `deep` que
genere los archivos completos de una estrategia + su test, los valida en el
sandbox git (T0.3), y si pasan abre una ventana de promocion SHADOW (T1.3). Si
el sandbox rechaza por tests, reintenta devolviendo el log de pytest al modelo
hasta `PROGRAMMER_MAX_REPAIR_ATTEMPTS`; agotados, archiva `FAILED_BUILD`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .._utils import log_swallow
from ..models import new_id
from .repo_context import OUTPUT_CONTRACT, build_repo_context

if TYPE_CHECKING:  # pragma: no cover - solo anotaciones.
    from ..config import Settings
    from ..storage import Store


SYSTEM_PROMPT = (
    "Eres un ProgrammerAgent que escribe estrategias de trading completas para este "
    "repositorio. Cumples el contrato de salida al pie de la letra y SIEMPRE incluyes "
    "un archivo de test nuevo. No tocas codigo del kernel ni de ejecucion/broker.\n\n"
    + OUTPUT_CONTRACT
)

LOGGER = logging.getLogger(__name__)


def _extract_json(raw: str) -> dict[str, Any] | None:
    if not raw:
        return None
    text = raw.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def _has_test_file(file_edits: Any) -> bool:
    if not isinstance(file_edits, list):
        return False
    return any(
        isinstance(item, dict) and str(item.get("path", "")).startswith("tests/") and str(item.get("path", "")).endswith(".py")
        for item in file_edits
    )


class StrategyBuilder:
    def __init__(
        self,
        store: Store,
        settings: Settings,
        *,
        applier: Any = None,
        llm: Callable[[list[dict[str, str]]], str] | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.llm = llm
        if applier is None:
            from .experiments import AutoApplyCodeAgent

            applier = AutoApplyCodeAgent()
        self.applier = applier
        self.max_repair = int(getattr(settings, "programmer_max_repair_attempts", 2))

    def _generate(self, messages: list[dict[str, str]]) -> str:
        if self.llm is not None:
            return self.llm(messages)
        from ..llm_router import chat_for_role

        response, _endpoint, _attempts = chat_for_role("deep", settings=self.settings, messages=messages)
        try:
            return response.choices[0].message.content or ""
        except Exception:  # noqa: BLE001
            return ""

    def build(self, spec: dict[str, Any]) -> dict[str, Any]:
        context = build_repo_context(self.settings, targets=spec.get("targets"))
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"{context}\n\n== ESPECIFICACION ==\n{json.dumps(spec, ensure_ascii=True)}"},
        ]
        proposal_id = str(spec.get("proposal_id") or new_id("ci_build"))
        last_error = ""
        attempts: list[dict[str, Any]] = []

        for attempt in range(self.max_repair + 1):
            raw = self._generate(messages)
            payload = _extract_json(raw)
            if not payload or not payload.get("file_edits"):
                last_error = "respuesta sin file_edits parseable"
                messages.append({"role": "user", "content": f"Error: {last_error}. Devuelve JSON valido segun el contrato."})
                attempts.append({"attempt": attempt, "error": last_error})
                continue
            if not _has_test_file(payload["file_edits"]):
                last_error = "falta archivo de test obligatorio bajo tests/"
                messages.append({"role": "user", "content": f"Error: {last_error}. Anade un test nuevo."})
                attempts.append({"attempt": attempt, "error": last_error})
                continue

            proposal = {
                "proposal_id": proposal_id,
                "cycle_id": spec.get("cycle_id"),
                "proposal_type": "CODE_CHANGE",
                "status": "READY_TO_APPLY",
                "risk_level": "LOW",
                "target_component": "strategies",
                "payload": {
                    "proposal_type": "CODE_CHANGE",
                    "build_kind": "strategy",
                    "strategy_name": payload.get("strategy_name"),
                    "strategy_version": payload.get("strategy_version", "1"),
                    "rollback_plan": "git revert del commit del sandbox",
                    "file_edits": payload["file_edits"],
                    "test_commands": payload.get("test_commands") or [],
                    "rationale": payload.get("rationale"),
                    "expected_metric_impact": payload.get("expected_metric_impact"),
                },
            }
            applied = self.applier.try_apply(
                settings=self.settings,
                store=self.store,
                initiative=None,
                proposal=proposal,
                validation={"validation_id": new_id("ci_val"), "status": "READY_TO_APPLY", "payload": {}},
            )
            status = applied.get("status")
            attempts.append({"attempt": attempt, "status": status, "error": applied.get("error")})

            if status == "APPLIED":
                strategy_name = payload.get("strategy_name")
                window = None
                if strategy_name:
                    from .promotion import PromotionManager

                    window = PromotionManager(self.store, self.settings).start_shadow(
                        str(strategy_name), str(payload.get("strategy_version", "1"))
                    )
                return {
                    "ok": True,
                    "status": "APPLIED",
                    "strategy_name": strategy_name,
                    "applied_change_id": applied.get("applied_change_id"),
                    "promotion_window": (window or {}).get("window_id"),
                    "attempts": attempts,
                }
            if status == "REJECTED_BY_TESTS":
                last_error = applied.get("error") or "tests fallaron en el sandbox"
                messages.append(
                    {"role": "user", "content": f"El sandbox rechazo el cambio por tests. Log:\n{str(last_error)[:3000]}\nCorrige y reintenta."}
                )
                continue
            # BLOCKED / FAILED: no tiene sentido reintentar.
            return {"ok": False, "status": status, "error": applied.get("error"), "attempts": attempts}

        # Agotados los reintentos: archivar FAILED_BUILD.
        try:
            self.store.save_continuous_improvement_proposal_artifact(
                {
                    "artifact_id": new_id("ci_artifact"),
                    "proposal_id": proposal_id,
                    "artifact_type": "failed_build",
                    "content_text": str(last_error)[:6000],
                    "payload": {"attempts": attempts},
                }
            )
        except Exception as exc:  # noqa: BLE001 - el archivo no debe romper el flujo.
            log_swallow(LOGGER, "archivar fallo de build de estrategia", exc)
        return {"ok": False, "status": "FAILED_BUILD", "error": last_error, "attempts": attempts}


def build_strategy_from_spec(
    store: Store,
    settings: Settings,
    spec: dict[str, Any],
    *,
    applier: Any = None,
    llm: Callable[[list[dict[str, str]]], str] | None = None,
) -> dict[str, Any]:
    if not getattr(settings, "ci_build_strategy_enabled", False):
        return {"ok": False, "status": "DISABLED", "reason": "CI_BUILD_STRATEGY_ENABLED=false"}
    return StrategyBuilder(store, settings, applier=applier, llm=llm).build(spec)
