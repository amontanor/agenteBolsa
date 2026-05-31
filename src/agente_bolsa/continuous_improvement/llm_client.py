"""Configurable external LLM client for improvement cycles."""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib import error, request

from pydantic import BaseModel
from pydantic import ValidationError

from agente_bolsa.config import Settings
from agente_bolsa.logging_utils import log_system_event
from agente_bolsa.models import new_id

from .schemas import LLMImprovementResponse, LLMJsonResult


LOGGER = logging.getLogger(__name__)


class ImprovementLLMClient:
    """OpenAI-compatible JSON client with disabled/mock mode for tests and safety."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate_json(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_model: type[BaseModel] = LLMImprovementResponse,
    ) -> LLMJsonResult:
        llm_call_id = new_id("ci_llm")
        provider = self.settings.improvement_llm_provider
        model_name = model or self.settings.improvement_llm_model
        request_preview = {
            "provider": provider,
            "base_url": self.settings.improvement_llm_base_url,
            "model": model_name,
            "messages": len(messages),
            "schema": schema.get("title") or schema.get("$defs", {}).keys(),
            "temperature": temperature if temperature is not None else self.settings.improvement_llm_temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.settings.improvement_llm_max_tokens,
        }
        if not self.settings.improvement_llm_enabled or provider.lower() in {"disabled", "mock"}:
            payload = LLMImprovementResponse(
                diagnosis={
                    "summary": "LLM externo de mejora continua desactivado; ciclo ejecutado en modo seguro.",
                    "confidence": "LOW",
                    "data_quality": "PARTIAL",
                },
                detected_issues=[],
                proposals=[
                    {
                        "proposal_type": "MONITORING_CHANGE",
                        "target_component": "continuous_improvement",
                        "target_identifier": "llm_configuration",
                        "current_value": "IMPROVEMENT_LLM_ENABLED=false",
                        "proposed_value": "Configurar IMPROVEMENT_LLM_* y ejecutar un ciclo manual.",
                        "rationale": "Sin LLM externo solo se pueden generar diagnósticos deterministas.",
                        "expected_impact": "Permitir propuestas razonadas por un modelo externo.",
                        "risk_level": "LOW",
                        "required_validations": ["configuration_review"],
                        "rollback_plan": "Volver a IMPROVEMENT_LLM_ENABLED=false.",
                    }
                ],
                recommended_next_actions=["Configurar proveedor LLM externo y repetir ciclo en dry-run."],
            )
            return LLMJsonResult(
                ok=True,
                llm_call_id=llm_call_id,
                payload=payload,
                provider=provider,
                model=model_name,
                request_preview=request_preview,
            )

        config_error = self._configuration_error(provider)
        if config_error:
            log_system_event(
                self.settings.logs_dir,
                "continuous_improvement_llm_config_error",
                {"llm_call_id": llm_call_id, "provider": provider, "model": model_name, "error": config_error},
            )
            return LLMJsonResult(
                ok=False,
                llm_call_id=llm_call_id,
                raw_response=None,
                error=config_error,
                provider=provider,
                model=model_name,
                request_preview=request_preview,
            )

        endpoint = self.settings.improvement_llm_base_url.rstrip("/") + "/chat/completions"
        body = self._request_body(
            provider=provider,
            model=model_name,
            messages=messages,
            temperature=temperature if temperature is not None else self.settings.improvement_llm_temperature,
            max_tokens=max_tokens if max_tokens is not None else self.settings.improvement_llm_max_tokens,
        )
        headers = self._request_headers(provider)

        last_error = ""
        for attempt in range(max(1, self.settings.improvement_llm_retries + 1)):
            try:
                raw = self._post_json(endpoint, body, headers)
                content = self._extract_content(raw)
                parsed = self._parse_json_content(content)
                payload = response_model.model_validate(parsed)
                log_system_event(
                    self.settings.logs_dir,
                    "continuous_improvement_llm_success",
                    {"llm_call_id": llm_call_id, "provider": provider, "model": model_name, "attempt": attempt + 1},
                )
                return LLMJsonResult(
                    ok=True,
                    llm_call_id=llm_call_id,
                    payload=payload,
                    raw_response=content,
                    provider=provider,
                    model=model_name,
                    request_preview=request_preview,
                )
            except (OSError, ValueError, ValidationError) as exc:
                last_error = str(exc)
                LOGGER.warning("Improvement LLM call failed on attempt %s: %s", attempt + 1, exc)
                if attempt < self.settings.improvement_llm_retries:
                    time.sleep(min(2**attempt, 8))

        log_system_event(
            self.settings.logs_dir,
            "continuous_improvement_llm_failed",
            {"llm_call_id": llm_call_id, "provider": provider, "model": model_name, "error": last_error},
        )
        return LLMJsonResult(
            ok=False,
            llm_call_id=llm_call_id,
            raw_response=None,
            error=last_error,
            provider=provider,
            model=model_name,
            request_preview=request_preview,
        )

    def _configuration_error(self, provider: str) -> str | None:
        provider_key = provider.strip().lower()
        if provider_key != "mimo":
            return None
        api_key = str(self.settings.improvement_llm_api_key or "").strip()
        base_url = self.settings.improvement_llm_base_url.rstrip("/")
        if api_key.startswith("tp-") and "api.xiaomimimo.com" in base_url:
            return (
                "MiMo Token Plan keys starting with tp- must use a token-plan base URL, "
                "for example https://token-plan-ams.xiaomimimo.com/v1 in Europe. "
                "Pay-as-you-go sk- keys use https://api.xiaomimimo.com/v1."
            )
        if api_key.startswith("sk-") and "token-plan-" in base_url:
            return (
                "MiMo pay-as-you-go keys starting with sk- must use https://api.xiaomimimo.com/v1. "
                "Token Plan tp- keys use token-plan regional base URLs."
            )
        return None

    def _request_body(
        self,
        *,
        provider: str,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        provider_key = provider.strip().lower()
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if provider_key == "mimo":
            body["max_completion_tokens"] = max_tokens
            body["thinking"] = {"type": "disabled"}
        else:
            body["max_tokens"] = max_tokens
            body["response_format"] = {"type": "json_object"}
        return body

    def _request_headers(self, provider: str) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if not self.settings.improvement_llm_api_key:
            return headers
        provider_key = provider.strip().lower()
        if provider_key == "mimo":
            headers["api-key"] = self.settings.improvement_llm_api_key
        else:
            headers["Authorization"] = f"Bearer {self.settings.improvement_llm_api_key}"
        return headers

    def _post_json(self, endpoint: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        payload = json.dumps(body, ensure_ascii=True).encode("utf-8")
        req = request.Request(endpoint, data=payload, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=self.settings.improvement_llm_timeout_seconds) as response:
                response_body = response.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise OSError(f"HTTP {exc.code}: {detail}") from exc
        return json.loads(response_body)

    def _extract_content(self, response_payload: dict[str, Any]) -> str:
        choices = response_payload.get("choices") or []
        if not choices:
            raise ValueError("LLM response without choices")
        message = (choices[0] or {}).get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("LLM response without text content")
        return content

    def _parse_json_content(self, content: str) -> dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON from LLM: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError("LLM JSON root must be an object")
        return self._normalize_response_shape(value)

    def _normalize_response_shape(self, value: dict[str, Any]) -> dict[str, Any]:
        if "diagnosis" in value and "proposals" in value:
            return value

        diagnosis_summary = str(value.get("summary") or value.get("message") or "").strip()
        metrics_snapshot = value.get("metrics_snapshot") if isinstance(value.get("metrics_snapshot"), dict) else {}
        safety_status = value.get("safety_status") if isinstance(value.get("safety_status"), dict) else {}

        normalized: dict[str, Any] = {
            "diagnosis": {
                "summary": diagnosis_summary or "Respuesta LLM normalizada desde un formato alternativo.",
                "confidence": "MEDIUM",
                "data_quality": "PARTIAL",
            },
            "detected_issues": [],
            "proposals": [],
            "recommended_next_actions": [],
        }

        if metrics_snapshot:
            outcomes = metrics_snapshot.get("outcomes_available")
            normalized["diagnosis"]["confidence"] = "LOW" if not outcomes else "MEDIUM"
            normalized["diagnosis"]["data_quality"] = "GOOD" if outcomes else "PARTIAL"

        key_findings = value.get("key_findings")
        if isinstance(key_findings, list):
            for idx, item in enumerate(key_findings, start=1):
                if not isinstance(item, dict):
                    continue
                evidence = item.get("evidence")
                if isinstance(evidence, str):
                    evidence_list = [evidence]
                elif isinstance(evidence, list):
                    evidence_list = [str(part) for part in evidence]
                else:
                    evidence_list = []
                normalized["detected_issues"].append(
                    {
                        "issue_id": str(item.get("issue_id") or f"finding_{idx}"),
                        "component": str(item.get("component") or item.get("category") or "continuous_improvement"),
                        "description": str(item.get("description") or item.get("finding") or item.get("summary") or ""),
                        "evidence": evidence_list,
                        "severity": str(item.get("severity") or item.get("risk_level") or "MEDIUM").upper(),
                    }
                )

        proposals = value.get("proposals")
        if isinstance(proposals, list):
            for item in proposals:
                if not isinstance(item, dict):
                    continue
                normalized["proposals"].append(self._normalize_proposal(item))

        next_actions = value.get("next_actions") or value.get("recommended_next_actions")
        if isinstance(next_actions, list):
            for item in next_actions:
                if isinstance(item, str):
                    normalized["recommended_next_actions"].append(item)
                elif isinstance(item, dict):
                    text = item.get("action") or item.get("title") or item.get("description")
                    if text:
                        normalized["recommended_next_actions"].append(str(text))

        if safety_status.get("dry_run_mode_active") is False:
            normalized["recommended_next_actions"].append("Revisar por que dry-run esta desactivado antes de continuar.")

        return normalized

    def _normalize_proposal(self, item: dict[str, Any]) -> dict[str, Any]:
        proposal_type = str(item.get("proposal_type") or "").upper()
        target_component = str(item.get("target_component") or item.get("component") or item.get("category") or "").strip()
        target_identifier = str(item.get("target_identifier") or item.get("proposal_id") or item.get("title") or "").strip()
        rationale = str(item.get("rationale") or item.get("reason") or item.get("description") or item.get("summary") or "").strip()
        proposed_value = str(item.get("proposed_value") or item.get("action") or item.get("change") or item.get("recommendation") or rationale).strip()
        current_value = str(item.get("current_value") or item.get("current_state") or item.get("baseline") or "").strip()
        expected_impact = str(item.get("expected_impact") or item.get("impact") or item.get("expected_result") or "").strip()
        rollback_plan = str(item.get("rollback_plan") or item.get("fallback") or "Revertir el cambio propuesto si la validacion falla.").strip()

        if proposal_type not in {
            "PARAMETER_CHANGE",
            "PROMPT_CHANGE",
            "STRATEGY_RULE_CHANGE",
            "RISK_RULE_CHANGE",
            "CODE_CHANGE",
            "DATA_QUALITY_CHANGE",
            "MONITORING_CHANGE",
        }:
            proposal_type = self._infer_proposal_type(item, target_component, rationale, proposed_value)

        if not target_component:
            target_component = self._infer_target_component(item, proposal_type)

        required_validations = item.get("required_validations")
        if isinstance(required_validations, list):
            validations = [str(part) for part in required_validations]
        else:
            validations = self._infer_validations(proposal_type, target_component)

        risk_level = str(item.get("risk_level") or item.get("severity") or "MEDIUM").upper()
        if risk_level not in {"LOW", "MEDIUM", "HIGH"}:
            risk_level = "MEDIUM"

        return {
            "proposal_type": proposal_type,
            "target_component": target_component,
            "target_identifier": target_identifier,
            "current_value": current_value,
            "proposed_value": proposed_value,
            "rationale": rationale,
            "expected_impact": expected_impact,
            "risk_level": risk_level,
            "required_validations": validations,
            "rollback_plan": rollback_plan,
        }

    def _infer_proposal_type(self, item: dict[str, Any], target_component: str, rationale: str, proposed_value: str) -> str:
        haystack = " ".join(
            [
                target_component,
                str(item.get("category") or ""),
                str(item.get("title") or ""),
                rationale,
                proposed_value,
            ]
        ).lower()
        if any(term in haystack for term in {"code", "software", "runtime", "bug", "test", "logging", "observability"}):
            return "CODE_CHANGE"
        if any(term in haystack for term in {"data", "coverage", "quality"}):
            return "DATA_QUALITY_CHANGE"
        if any(term in haystack for term in {"risk", "drawdown", "exposure"}):
            return "RISK_RULE_CHANGE"
        if any(term in haystack for term in {"prompt", "llm"}):
            return "PROMPT_CHANGE"
        if any(term in haystack for term in {"parameter", "threshold", "filter", "entry", "exit"}):
            return "PARAMETER_CHANGE"
        return "MONITORING_CHANGE"

    def _infer_target_component(self, item: dict[str, Any], proposal_type: str) -> str:
        category = str(item.get("category") or "").lower()
        if category:
            return category
        mapping = {
            "CODE_CHANGE": "software_runtime",
            "DATA_QUALITY_CHANGE": "market_data_pipeline",
            "RISK_RULE_CHANGE": "risk_manager",
            "PROMPT_CHANGE": "llm_prompts",
            "PARAMETER_CHANGE": "strategy_parameters",
            "MONITORING_CHANGE": "continuous_improvement",
        }
        return mapping.get(proposal_type, "continuous_improvement")

    def _infer_validations(self, proposal_type: str, target_component: str) -> list[str]:
        if proposal_type == "CODE_CHANGE":
            return ["tests"]
        if proposal_type in {"PARAMETER_CHANGE", "STRATEGY_RULE_CHANGE", "RISK_RULE_CHANGE"}:
            return ["backtest", "baseline_compare"]
        if proposal_type == "DATA_QUALITY_CHANGE":
            return ["tests", "data_quality_review"]
        if target_component == "continuous_improvement":
            return ["configuration_review"]
        return ["tests"]
