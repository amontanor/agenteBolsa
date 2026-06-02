"""Helpers to route OpenAI-compatible calls across primary and fallback endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import Settings


@dataclass(frozen=True)
class LLMEndpoint:
    name: str
    api_key: str
    base_url: str
    model: str
    preflight: bool = False
    reasoning_effort: str | None = None


def configured_llm_endpoints(settings: Settings) -> list[LLMEndpoint]:
    endpoints = [
        LLMEndpoint(
            name="primary",
            api_key=settings.openai_api_key or "local-llama",
            base_url=settings.openai_api_base,
            model=settings.openai_model,
            preflight=settings.llm_primary_preflight_enabled,
        )
    ]
    if settings.llm_fallback_enabled:
        endpoints.append(
            LLMEndpoint(
                name="fallback",
                api_key=settings.llm_fallback_api_key or settings.openai_api_key or "local-llama",
                base_url=settings.llm_fallback_api_base,
                model=settings.llm_fallback_model,
                preflight=False,
                reasoning_effort=settings.llm_fallback_reasoning_effort,
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


def is_endpoint_available(endpoint: LLMEndpoint, timeout_seconds: int) -> tuple[bool, str | None]:
    if not endpoint.preflight:
        return True, None
    try:
        client = build_openai_client(endpoint, max(3, min(timeout_seconds, 10)))
        client.models.list()
    except Exception as exc:  # noqa: BLE001 - provider/network errors are fallback triggers
        return False, str(exc)
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


def chat_completion_with_fallback(
    settings: Settings,
    *,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int | None,
) -> tuple[Any, LLMEndpoint, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    last_error: Exception | None = None
    for endpoint in configured_llm_endpoints(settings):
        available, preflight_error = is_endpoint_available(endpoint, settings.llm_timeout_seconds)
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
        try:
            client = build_openai_client(endpoint, settings.llm_timeout_seconds)
            request_kwargs = {
                "model": endpoint.model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "messages": messages,
            }
            if endpoint.reasoning_effort:
                request_kwargs["reasoning_effort"] = endpoint.reasoning_effort
            response = client.chat.completions.create(
                **request_kwargs,
            )
            attempts.append(
                {
                    "name": endpoint.name,
                    "base_url": endpoint.base_url,
                    "model": endpoint.model,
                    "stage": "completion",
                    "available": True,
                    "error": None,
                }
            )
            return response, endpoint, attempts
        except Exception as exc:  # noqa: BLE001 - fallback is intentional here
            last_error = exc
            attempts.append(
                {
                    "name": endpoint.name,
                    "base_url": endpoint.base_url,
                    "model": endpoint.model,
                    "stage": "completion",
                    "available": False,
                    "error": str(exc),
                }
            )
    if last_error is None:
        raise RuntimeError("No hay endpoints LLM configurados.")
    raise last_error
