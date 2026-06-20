"""Helpers to route OpenAI-compatible calls across primary and fallback endpoints."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from ._utils import log_swallow
from .config import Settings

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMEndpoint:
    name: str
    api_key: str
    base_url: str
    model: str
    preflight: bool = False
    reasoning_effort: str | None = None


def _provider_api_key(settings: Settings, provider: str | None) -> str:
    provider_key = str(provider or "").strip().lower()
    if provider_key in {"opencode", "opencode-go"}:
        return str(settings.opencode_api_key or "").strip()
    if provider_key == "mimo":
        return str(settings.mimo_api_key or settings.openai_api_key or "").strip()
    return str(settings.openai_api_key or "").strip()


def primary_llm_endpoint(settings: Settings) -> LLMEndpoint:
    selector = str(getattr(settings, "llm_model_selector", "custom") or "custom").strip().lower()
    if selector in {"opencode", "opencode-go"}:
        return LLMEndpoint(
            name=f"primary:{selector}",
            api_key=str(settings.opencode_api_key or "").strip(),
            base_url=settings.opencode_api_base,
            model=settings.opencode_model,
            preflight=settings.llm_primary_preflight_enabled,
        )
    if selector == "mimo":
        return LLMEndpoint(
            name="primary:mimo",
            api_key=str(settings.mimo_api_key or settings.openai_api_key or "").strip(),
            base_url=settings.mimo_api_base,
            model=settings.mimo_model,
            preflight=settings.llm_primary_preflight_enabled,
        )
    return LLMEndpoint(
        name="primary:custom",
        api_key=str(settings.openai_api_key or "").strip(),
        base_url=settings.openai_api_base,
        model=settings.openai_model,
        preflight=settings.llm_primary_preflight_enabled,
    )


def configured_llm_endpoints(settings: Settings) -> list[LLMEndpoint]:
    endpoints = [
        primary_llm_endpoint(settings),
    ]
    if settings.llm_local_fallback_enabled:
        endpoints.append(
            LLMEndpoint(
                name="local_fallback",
                api_key=str(settings.llm_local_fallback_api_key or "local-llama").strip(),
                base_url=settings.llm_local_fallback_api_base,
                model=settings.llm_local_fallback_model,
                preflight=settings.llm_local_fallback_preflight_enabled,
            )
        )
    unique: list[LLMEndpoint] = []
    seen: set[tuple[str, str, str]] = set()
    for endpoint in endpoints:
        key = (endpoint.base_url.rstrip("/"), endpoint.model, endpoint.api_key)
        if key in seen:
            continue
        seen.add(key)
        unique.append(endpoint)
    return unique


def build_openai_client(endpoint: LLMEndpoint, timeout_seconds: int):
    from openai import OpenAI

    return OpenAI(
        api_key=endpoint.api_key,
        base_url=endpoint.base_url,
        timeout=timeout_seconds,
    )


def classify_llm_client_error(exc: Exception) -> str:
    """Etiqueta fallos locales del cliente para no confundirlos con proveedor caido."""

    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return f"llm_client_import_broken: {exc}"
    return str(exc)


def is_endpoint_available(endpoint: LLMEndpoint, timeout_seconds: int) -> tuple[bool, str | None]:
    if not endpoint.preflight:
        return True, None
    try:
        client = build_openai_client(endpoint, max(3, min(timeout_seconds, 10)))
        client.models.list()
    except Exception as exc:  # noqa: BLE001 - provider/network errors are fallback triggers
        return False, classify_llm_client_error(exc)
    return True, None


def select_preferred_endpoint(settings: Settings) -> tuple[LLMEndpoint, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    endpoints = configured_llm_endpoints(settings)
    for endpoint in endpoints:
        available, error = is_endpoint_available(endpoint, settings.llm_timeout_seconds)
        attempts.append(
            {
                "name": endpoint.name,
                "base_url": endpoint.base_url,
                "model": endpoint.model,
                "stage": "preflight",
                "available": available,
                "error": error,
            }
        )
        if available:
            return endpoint, attempts
    return endpoints[0], attempts


# Perfiles de rol (T0.4). Cada rol resuelve a settings LLM_ROLE_<ROL>_* con
# fallback a la cadena por defecto (`configured_llm_endpoints`).
ROLE_PROFILES: dict[str, dict[str, Any]] = {
    "fast": {"temperature": 0.2, "max_tokens": 1200, "timeout": None},
    "sentiment": {"temperature": 0.2, "max_tokens": 4000, "timeout": None},
    "decision": {"temperature": 0.2, "max_tokens": None, "timeout": None},
    "deep": {"temperature": 0.2, "max_tokens": 16000, "timeout": 600},
}


def role_endpoints(settings: Settings, role: str) -> list[LLMEndpoint]:
    """Endpoints para un rol: el especifico (si esta configurado) + la cadena base.

    - Si hay `LLM_ROLE_<ROL>_MODEL` y `..._BASE_URL`, se antepone ese endpoint.
    - Si solo hay modelo, se reutiliza la base del endpoint primario.
    - Para `deep` sin config explicita, se usa el modelo del laboratorio
      (`IMPROVEMENT_LLM_*`) cuando existe, que es el modelo potente por defecto.
    - Siempre se anexa el endpoint primario como respaldo estandar.
    """

    role = (role or "").lower()
    model = getattr(settings, f"llm_role_{role}_model", None)
    base = getattr(settings, f"llm_role_{role}_base_url", None)
    api_key = getattr(settings, f"llm_role_{role}_api_key", None)

    endpoints: list[LLMEndpoint] = []
    if model and base:
        endpoints.append(
            LLMEndpoint(
                name=f"role:{role}",
                api_key=str(api_key or primary_llm_endpoint(settings).api_key or "").strip(),
                base_url=base,
                model=model,
                preflight=settings.llm_primary_preflight_enabled,
            )
        )
    elif model:
        primary = primary_llm_endpoint(settings)
        endpoints.append(
            LLMEndpoint(
                name=f"role:{role}",
                api_key=primary.api_key,
                base_url=primary.base_url,
                model=model,
                preflight=settings.llm_primary_preflight_enabled,
            )
        )
    elif role == "deep" and getattr(settings, "improvement_llm_model", None):
        improvement_key = str(settings.improvement_llm_api_key or "").strip() or _provider_api_key(
            settings,
            settings.improvement_llm_provider,
        )
        endpoints.append(
            LLMEndpoint(
                name="role:deep",
                api_key=improvement_key,
                base_url=settings.improvement_llm_base_url,
                model=settings.improvement_llm_model,
                preflight=False,
            )
        )

    endpoints.extend(configured_llm_endpoints(settings))
    unique: list[LLMEndpoint] = []
    seen: set[tuple[str, str, str]] = set()
    for endpoint in endpoints:
        key = (endpoint.base_url.rstrip("/"), endpoint.model, endpoint.api_key)
        if key in seen:
            continue
        seen.add(key)
        unique.append(endpoint)
    return unique


def role_max_tokens(settings: Settings, role: str) -> int | None:
    role = (role or "").lower()
    override = getattr(settings, f"llm_role_{role}_max_tokens", None)
    if override is not None:
        return override
    profile_default = ROLE_PROFILES.get(role, {}).get("max_tokens")
    if profile_default is not None:
        return profile_default
    return settings.llm_max_tokens


class LLMBudgetExhausted(RuntimeError):
    """El presupuesto economico diario del laboratorio se agoto (T5.9).

    El laboratorio lo trata como 'posponer tarea', no como fallo.
    """


def chat_for_role(
    role: str,
    *,
    settings: Settings,
    messages: list[dict[str, Any]],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> tuple[Any, LLMEndpoint, list[dict[str, Any]]]:
    """Completa un chat usando el endpoint del rol con fallback a la cadena base."""

    role_lc = (role or "").lower()
    profile = ROLE_PROFILES.get(role_lc, {})
    temp = temperature if temperature is not None else profile.get("temperature", settings.llm_temperature)
    tokens = max_tokens if max_tokens is not None else role_max_tokens(settings, role)
    timeout = profile.get("timeout") or settings.llm_timeout_seconds

    # Presupuesto economico del laboratorio (T5.9). 0 = sin limite.
    degrade_to_local = False
    try:
        from .llm_usage import today_llm_spend

        total_budget = float(getattr(settings, "llm_daily_budget_usd", 0.0) or 0.0)
        if total_budget > 0 and today_llm_spend(settings) >= total_budget:
            raise LLMBudgetExhausted("llm_budget_exhausted")
        if role_lc == "deep":
            deep_budget = float(getattr(settings, "llm_role_deep_daily_budget_usd", 0.0) or 0.0)
            if deep_budget > 0 and today_llm_spend(settings, role="deep") >= deep_budget:
                degrade_to_local = True  # degradar al endpoint local barato
    except LLMBudgetExhausted:
        raise
    except Exception as exc:  # noqa: BLE001 - sin contabilidad disponible, no bloquear.
        log_swallow(LOGGER, "consultar presupuesto LLM", exc)

    endpoints = configured_llm_endpoints(settings) if degrade_to_local else role_endpoints(settings, role)
    return _complete_with_endpoints(
        settings,
        endpoints=endpoints,
        messages=messages,
        temperature=temp,
        max_tokens=tokens,
        timeout_seconds=int(timeout),
    )


def chat_completion_with_fallback(
    settings: Settings,
    *,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int | None,
) -> tuple[Any, LLMEndpoint, list[dict[str, Any]]]:
    return _complete_with_endpoints(
        settings,
        endpoints=configured_llm_endpoints(settings),
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
    )


def _complete_with_endpoints(
    settings: Settings,
    *,
    endpoints: list[LLMEndpoint],
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int | None,
    timeout_seconds: int,
) -> tuple[Any, LLMEndpoint, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    last_error: Exception | None = None
    for endpoint in endpoints:
        available, preflight_error = is_endpoint_available(endpoint, timeout_seconds)
        attempts.append(
            {
                "name": endpoint.name,
                "base_url": endpoint.base_url,
                "model": endpoint.model,
                "stage": "preflight",
                "available": available,
                "error": preflight_error,
            }
        )
        if not available:
            continue
        retry_attempts = max(0, int(settings.llm_retry_attempts))
        for retry_index in range(retry_attempts + 1):
            try:
                client = build_openai_client(endpoint, timeout_seconds)
                request_kwargs = {
                    "model": endpoint.model,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "messages": messages,
                }
                if endpoint.reasoning_effort:
                    request_kwargs["reasoning_effort"] = endpoint.reasoning_effort
                response = client.chat.completions.create(**request_kwargs)
                attempts.append(
                    {
                        "name": endpoint.name,
                        "base_url": endpoint.base_url,
                        "model": endpoint.model,
                        "stage": "completion",
                        "available": True,
                        "retry_index": retry_index,
                        "error": None,
                    }
                )
                return response, endpoint, attempts
            except Exception as exc:  # noqa: BLE001 - fallback is intentional here
                last_error = exc
                status_code = _http_status_code(exc)
                retryable = status_code in {403, 429}
                can_retry = retryable and retry_index < retry_attempts
                delay = _retry_delay_seconds(settings, exc, retry_index) if can_retry else None
                attempts.append(
                    {
                        "name": endpoint.name,
                        "base_url": endpoint.base_url,
                        "model": endpoint.model,
                        "stage": "completion",
                        "available": False,
                        "retry_index": retry_index,
                        "status_code": status_code,
                        "retry_scheduled": can_retry,
                        "retry_after_seconds": delay,
                        "error": classify_llm_client_error(exc),
                    }
                )
                if not can_retry:
                    break
                time.sleep(delay or 0.0)
    if last_error is None:
        raise RuntimeError("No hay endpoints LLM configurados.")
    raise last_error


def _http_status_code(exc: Exception) -> int | None:
    value = getattr(exc, "status_code", None)
    if value is None:
        value = getattr(getattr(exc, "response", None), "status_code", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _retry_after_header(exc: Exception) -> str | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or getattr(exc, "headers", None)
    if headers is None:
        return None
    try:
        return headers.get("Retry-After") or headers.get("retry-after")
    except AttributeError:
        return None


def _retry_delay_seconds(settings: Settings, exc: Exception, retry_index: int) -> float:
    maximum = max(0.0, float(settings.llm_retry_max_seconds))
    header = str(_retry_after_header(exc) or "").strip()
    if header:
        try:
            return min(maximum, max(0.0, float(header)))
        except ValueError:
            try:
                target = parsedate_to_datetime(header)
                if target.tzinfo is None:
                    target = target.replace(tzinfo=timezone.utc)
                seconds = (target - datetime.now(timezone.utc)).total_seconds()
                return min(maximum, max(0.0, seconds))
            except (TypeError, ValueError, OverflowError):
                pass
    base = max(0.0, float(settings.llm_retry_base_seconds))
    return min(maximum, base * (2 ** max(0, retry_index)))
