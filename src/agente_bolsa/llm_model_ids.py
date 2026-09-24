"""Canonical external LLM model IDs and exact legacy-ID migration."""

from __future__ import annotations

DEPRECATED_DEEPSEEK_V4_FLASH_FREE_ID = "deepseek-v4-flash-free"
DEEPSEEK_V4_1_FLASH_MODEL_ID = "deepseek-v4.1-flash"


def normalize_model_id(model: str | None) -> str | None:
    """Replace only the retired exact ID; preserve every other override."""

    if model == DEPRECATED_DEEPSEEK_V4_FLASH_FREE_ID:
        return DEEPSEEK_V4_1_FLASH_MODEL_ID
    return model
