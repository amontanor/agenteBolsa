"""Persistence helpers for coarse local/compatible LLM usage counters."""

from __future__ import annotations

import sqlite3
from math import ceil
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.models import new_id
from agente_bolsa.storage import Store


def _usage_value(usage: Any, name: str) -> int:
    if usage is None:
        return 0
    if isinstance(usage, dict):
        value = usage.get(name)
    else:
        value = getattr(usage, name, None)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _text_from_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_text_from_value(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_text_from_value(item) for item in value)
    return str(value)


def _estimated_tokens(value: Any) -> int:
    text = _text_from_value(value)
    if not text:
        return 0
    return max(1, ceil(len(text) / 4))


def _response_completion_text(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    first = choices[0]
    message = getattr(first, "message", None)
    if message is None and isinstance(first, dict):
        message = first.get("message")
    if isinstance(message, dict):
        return _text_from_value(message.get("content"))
    return _text_from_value(getattr(message, "content", None))


def usage_tokens(response: Any, *, prompt: Any | None = None) -> dict[str, int]:
    tokens = usage_tokens_from_response(response)
    if tokens["prompt_tokens"] == 0 and prompt is not None:
        tokens["prompt_tokens"] = _estimated_tokens(prompt)
    if tokens["completion_tokens"] == 0:
        tokens["completion_tokens"] = _estimated_tokens(_response_completion_text(response))
    if tokens["total_tokens"] == 0:
        tokens["total_tokens"] = tokens["prompt_tokens"] + tokens["completion_tokens"]
    return tokens


def usage_tokens_from_response(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    prompt_tokens = _usage_value(usage, "prompt_tokens")
    completion_tokens = _usage_value(usage, "completion_tokens")
    total_tokens = _usage_value(usage, "total_tokens") or prompt_tokens + completion_tokens
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


# Precios por defecto en USD por millon de tokens (T5.9). Editables por settings
# LLM_PRICE_PER_MTOKEN_<MODEL> (alias en mayusculas con guiones->guion_bajo).
DEFAULT_PRICE_PER_MTOKEN: dict[str, float] = {
    "local": 0.0,
    "qwen": 0.0,
    "gemini": 0.30,
    "mimo": 0.50,
}


def price_per_mtoken(settings: Settings, model: str | None) -> float:
    """Precio USD por millon de tokens del modelo (override por settings)."""

    name = str(model or "").lower()
    override_attr = "llm_price_per_mtoken_" + name.replace("-", "_").replace(".", "_").replace("/", "_")
    override = getattr(settings, override_attr, None)
    if isinstance(override, (int, float)):
        return float(override)
    for key, price in DEFAULT_PRICE_PER_MTOKEN.items():
        if key in name:
            return price
    return 0.0


def estimate_cost(settings: Settings, model: str | None, total_tokens: int) -> float:
    return round(price_per_mtoken(settings, model) * (max(0, int(total_tokens)) / 1_000_000.0), 6)


def today_llm_spend(settings: Settings, *, role: str | None = None) -> float:
    """Gasto LLM acumulado de HOY en USD, opcionalmente filtrado por rol (T5.9)."""

    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date().isoformat()
    try:
        store = Store(settings.database_path, settings.agent_logs_dir)
        store.ensure_schema()
        rows = store.latest_llm_usage(limit=5000)
    except (OSError, sqlite3.Error):
        return 0.0
    total = 0.0
    for row in rows:
        if not str(row.get("created_at") or "").startswith(today):
            continue
        if role is not None and str(row.get("role") or "") != role:
            continue
        total += estimate_cost(settings, row.get("model"), int(row.get("total_tokens") or 0))
    return round(total, 6)


def record_llm_response(
    settings: Settings,
    source: str,
    response: Any,
    *,
    prompt: Any | None = None,
    role: str | None = None,
) -> None:
    raw_tokens = usage_tokens_from_response(response)
    tokens = usage_tokens(response, prompt=prompt)
    payload = {
        **tokens,
        "estimated": int(raw_tokens["total_tokens"] == 0 and tokens["total_tokens"] > 0),
        "role": role,
    }
    try:
        store = Store(settings.database_path, settings.agent_logs_dir)
        store.ensure_schema()
        store.record_llm_usage(
            usage_id=new_id("llm_usage"),
            source=source,
            model=getattr(response, "model", None) or settings.openai_model,
            request_count=1,
            prompt_tokens=tokens["prompt_tokens"],
            completion_tokens=tokens["completion_tokens"],
            total_tokens=tokens["total_tokens"],
            payload=payload,
            role=role,
        )
    except (OSError, sqlite3.Error):
        return
