"""Memoria de largo plazo destilada (T2.4).

Las lecciones acumuladas (que funciona en que regimen/setup) se comprimen a un
conjunto pequeno de lecciones validadas y se inyectan en el prompt de decision.
Cada leccion debe ser verificable contra los numeros agregados que se le pasaron
(se guardan en source_refs). Las lecciones mueren si los datos dejan de
apoyarlas: confidence baja -> WEAKENED -> RETIRED.

Nucleo stdlib; la llamada al modelo es inyectable para tests.
"""

from __future__ import annotations

import statistics
from typing import TYPE_CHECKING, Any, Callable

from ..models import new_id

if TYPE_CHECKING:  # pragma: no cover - solo anotaciones.
    from ..config import Settings
    from ..storage import Store


DEFAULT_DISTILLER_PROMPT = (
    "Eres un analista que destila lecciones de trading verificables. A partir de los "
    "agregados por setup/regimen, devuelve SOLO JSON con la clave 'lessons', una lista "
    "de objetos con: scope (setup|regime|symbol|sector|process), statement, setup (la "
    "clave del agregado que la respalda). No inventes: cada leccion debe apoyarse en un "
    "agregado presente en la entrada."
)

WEAK_CONFIDENCE = 0.45
RETIRE_CONFIDENCE = 0.35


def _verdict(signal: dict[str, Any]) -> str:
    return str((signal.get("outcome") or {}).get("verdict", "") or "")


def _setup_of(signal: dict[str, Any]) -> str:
    features = signal.get("features") or {}
    return str(features.get("setup") or features.get("setup_quality") or "unknown")


def _is_matured(signal: dict[str, Any]) -> bool:
    return _verdict(signal) not in {"", "pending"}


def aggregate_by_setup(outcomes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Agrega outcomes madurados por setup: n, win_rate, expectancy."""

    buckets: dict[str, list[dict[str, Any]]] = {}
    for signal in outcomes:
        if not _is_matured(signal):
            continue
        buckets.setdefault(_setup_of(signal), []).append(signal)
    aggregates: dict[str, dict[str, Any]] = {}
    for setup, items in buckets.items():
        decided = [it for it in items if _verdict(it).startswith(("winner", "loser"))]
        winners = sum(1 for it in decided if _verdict(it).startswith("winner"))
        returns = [
            float((it.get("outcome") or {}).get("return_pct"))
            for it in items
            if isinstance((it.get("outcome") or {}).get("return_pct"), (int, float))
        ]
        aggregates[setup] = {
            "n": len(items),
            "win_rate": round(winners / len(decided), 4) if decided else None,
            "expectancy": round(statistics.fmean(returns), 6) if returns else None,
            "winners": winners,
            "decided": len(decided),
        }
    return aggregates


def distill_lessons(
    store: "Store",
    settings: "Settings",
    *,
    since_date: str | None = None,
    llm: Callable[[list[dict[str, str]]], str] | None = None,
) -> dict[str, Any]:
    """Destila lecciones desde los agregados recientes (con validacion)."""

    outcomes = store.signal_outcomes(limit=8000, since_date=since_date)
    aggregates = aggregate_by_setup(outcomes)
    if not aggregates:
        return {"distilled": 0, "lessons": []}

    max_lessons = int(getattr(settings, "max_active_lessons", 40))
    import json

    from ..prompt_store import get_prompt

    system = get_prompt(settings, "lesson_distiller", DEFAULT_DISTILLER_PROMPT)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps({"aggregates": aggregates}, ensure_ascii=True, default=str)},
    ]
    raw = llm(messages) if llm is not None else _default_llm(settings, messages)
    parsed = _extract_obj(raw)
    proposed = parsed.get("lessons", []) if isinstance(parsed, dict) else []

    inserted: list[str] = []
    for item in proposed[:max_lessons]:
        if not isinstance(item, dict):
            continue
        statement = str(item.get("statement") or "").strip()
        setup = str(item.get("setup") or "")
        agg = aggregates.get(setup)
        # Validacion determinista: la leccion debe apoyarse en un agregado real.
        if not statement or agg is None:
            continue
        winners = int(agg.get("winners") or 0)
        contradicting = int(agg.get("decided") or 0) - winners
        confidence = round(winners / agg["decided"], 4) if agg.get("decided") else 0.0
        lesson_id = new_id("lesson")
        store.upsert_distilled_lesson(
            {
                "lesson_id": lesson_id,
                "scope": str(item.get("scope") or "setup"),
                "statement": statement,
                "supporting_cases": winners,
                "contradicting_cases": max(0, contradicting),
                "confidence": confidence,
                "status": "ACTIVE",
                "source_refs": {"setup": setup, "aggregate": agg},
            }
        )
        inserted.append(lesson_id)
    return {"distilled": len(inserted), "lessons": inserted}


def revalidate_lessons(
    store: "Store",
    settings: "Settings",
    *,
    since_date: str | None = None,
) -> dict[str, Any]:
    """Recalcula soporte de lecciones ACTIVE/WEAKENED; baja confianza -> retiro."""

    outcomes = store.signal_outcomes(limit=8000, since_date=since_date)
    aggregates = aggregate_by_setup(outcomes)
    transitions: list[dict[str, Any]] = []
    for lesson in store.distilled_lessons(limit=500):
        if lesson["status"] == "RETIRED":
            continue
        setup = str((lesson.get("source_refs") or {}).get("setup") or "")
        agg = aggregates.get(setup)
        if agg is None or not agg.get("decided"):
            continue
        winners = int(agg.get("winners") or 0)
        decided = int(agg.get("decided") or 0)
        confidence = round(winners / decided, 4) if decided else 0.0
        new_status = lesson["status"]
        if confidence < RETIRE_CONFIDENCE:
            new_status = "RETIRED" if lesson["status"] == "WEAKENED" else "WEAKENED"
        elif confidence < WEAK_CONFIDENCE:
            new_status = "WEAKENED"
        else:
            new_status = "ACTIVE"
        store.upsert_distilled_lesson(
            {
                "lesson_id": lesson["lesson_id"],
                "scope": lesson["scope"],
                "statement": lesson["statement"],
                "supporting_cases": winners,
                "contradicting_cases": max(0, decided - winners),
                "confidence": confidence,
                "status": new_status,
                "source_refs": {"setup": setup, "aggregate": agg},
            }
        )
        if new_status != lesson["status"]:
            transitions.append({"lesson_id": lesson["lesson_id"], "from": lesson["status"], "to": new_status})
    return {"revalidated": True, "transitions": transitions}


def relevant_lessons(store: "Store", *, setup: str | None = None, k: int = 5) -> list[dict[str, Any]]:
    """Top-K lecciones ACTIVE, opcionalmente filtradas por setup."""

    lessons = store.distilled_lessons(status="ACTIVE", limit=200)
    if setup:
        matched = [item for item in lessons if str((item.get("source_refs") or {}).get("setup") or "") == setup]
        if matched:
            lessons = matched
    return lessons[:k]


def _extract_obj(raw: str) -> dict[str, Any]:
    import json

    if not raw:
        return {}
    text = str(raw)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}


def _default_llm(settings: "Settings", messages: list[dict[str, str]]) -> str:
    try:
        from ..llm_router import chat_for_role

        response, _endpoint, _attempts = chat_for_role("deep", settings=settings, messages=messages)
        return response.choices[0].message.content or ""
    except Exception:  # noqa: BLE001
        return ""
