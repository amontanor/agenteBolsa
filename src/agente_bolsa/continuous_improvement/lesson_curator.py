"""Objective lesson curator built on top of the lesson distiller."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .lesson_distiller import distill_lessons, promote_qualified_lessons, revalidate_lessons

if TYPE_CHECKING:  # pragma: no cover - typing only.
    from ..config import Settings
    from ..storage import Store


def curate_lessons(
    store: "Store",
    settings: "Settings",
    *,
    since_date: str | None = None,
) -> dict[str, Any]:
    distilled = distill_lessons(store, settings, since_date=since_date)
    promoted = promote_qualified_lessons(store, settings)
    revalidated = revalidate_lessons(store, settings, since_date=since_date)
    all_lessons = store.distilled_lessons(limit=500)
    summary = {
        "active": sum(1 for item in all_lessons if item.get("status") == "ACTIVE"),
        "hypothesis": sum(1 for item in all_lessons if item.get("status") == "HYPOTHESIS"),
        "weakened": sum(1 for item in all_lessons if item.get("status") == "WEAKENED"),
        "retired": sum(1 for item in all_lessons if item.get("status") == "RETIRED"),
    }
    return {
        "distilled": distilled,
        "promoted": promoted,
        "revalidated": revalidated,
        "summary": summary,
        "top_active": [item for item in all_lessons if item.get("status") == "ACTIVE"][:8],
        "top_hypotheses": [item for item in all_lessons if item.get("status") == "HYPOTHESIS"][:8],
    }
