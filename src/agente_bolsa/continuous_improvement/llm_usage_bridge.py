"""Bridge ImprovementLLMClient results into the shared LLM usage ledger."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agente_bolsa.models import new_id

if TYPE_CHECKING:  # pragma: no cover - typing only.
    from agente_bolsa.config import Settings
    from agente_bolsa.storage import Store

    from .schemas import LLMJsonResult


def _estimated_completion_tokens(raw_response: str | None) -> int:
    text = str(raw_response or "").strip()
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def record_improvement_llm_usage(
    store: "Store",
    settings: "Settings",
    *,
    source: str,
    result: "LLMJsonResult",
    role: str = "continuous_improvement",
) -> dict[str, int | bool | str | None]:
    """Persist estimated usage for ImprovementLLMClient calls.

    The provider wrapper returns prompt estimates but not provider usage. Recording
    successful calls here makes the dashboard/CLI heartbeat reflect real CI LLM
    activity instead of only trade-decision/chat_for_role calls.
    """

    prompt_tokens = int(result.prompt_tokens_estimate or 0)
    completion_tokens = _estimated_completion_tokens(result.raw_response)
    total_tokens = prompt_tokens + completion_tokens
    recorded = bool(total_tokens > 0 and settings.improvement_llm_enabled)
    if recorded:
        store.record_llm_usage(
            usage_id=new_id("llm_usage"),
            source=source,
            model=result.model or settings.improvement_llm_model,
            request_count=1,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            payload={
                "estimated": 1,
                "role": role,
                "llm_call_id": result.llm_call_id,
                "provider": result.provider,
                "ok": result.ok,
                "error": result.error,
                "fallback_used": result.fallback_used,
                "context_compacted": result.context_compacted,
                "source": source,
            },
            role=role,
        )
    return {
        "recorded": recorded,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "llm_call_id": result.llm_call_id,
    }
