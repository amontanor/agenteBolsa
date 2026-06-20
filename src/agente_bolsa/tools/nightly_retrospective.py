"""Retrospectiva generativa nocturna: perdidas -> hipotesis (T2.3).

Cada perdida, oportunidad perdida y acierto raro se convierte en hipotesis
falsable que alimenta el pipeline de construccion (T1.4). Exige evidencia: una
hipotesis que no cite >= N casos concretos se descarta (gate anti-fabulacion).
La llamada al modelo es inyectable para tests.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ..models import new_id

if TYPE_CHECKING:  # pragma: no cover - solo anotaciones.
    from ..config import Settings
    from ..storage import Store


DEFAULT_RETROSPECTIVE_PROMPT = (
    "Eres un analista cuantitativo. A partir de la evidencia del dia (perdidas, "
    "oportunidades perdidas y ganadores no comprados), propone hipotesis falsables. "
    "Devuelve SOLO JSON con la clave 'hypotheses', una lista de objetos con: "
    "pattern_description, entry_rule (medible), exit_rule, invalidation, "
    "expected_improvement, evidence_refs (lista de ids de senales concretas). "
    "Cada hipotesis DEBE citar al menos 3 casos en evidence_refs. No inventes casos."
)


def _verdict(signal: dict[str, Any]) -> str:
    return str((signal.get("outcome") or {}).get("verdict", "") or "")


def _decision(signal: dict[str, Any]) -> str:
    return str(signal.get("decision") or "").lower()


def collect_evidence(store: Store, settings: Settings, session_date: str) -> dict[str, Any]:
    """Empaqueta perdidas, misses y ganadores no comprados del dia."""

    rows = [item for item in store.signal_outcomes(limit=5000, since_date=session_date) if item["signal_date"] == session_date]
    losses = [
        {"signal_id": item["signal_id"], "symbol": item["symbol"], "verdict": _verdict(item), "features": item.get("features", {})}
        for item in rows
        if _verdict(item).startswith("loser") and _decision(item) in {"buy", "long", "enter"}
    ]
    misses = [
        {"signal_id": item["signal_id"], "symbol": item["symbol"], "verdict": _verdict(item), "features": item.get("features", {})}
        for item in rows
        if _verdict(item).startswith("winner") and _decision(item) in {"hold", "skip", "", "watch"}
    ]
    winners_not_bought = list(misses)  # alias semantico
    return {
        "session_date": session_date,
        "losses": losses,
        "misses": misses,
        "winners_not_bought": winners_not_bought,
        "counts": {"losses": len(losses), "misses": len(misses)},
    }


def generate_hypotheses(
    evidence: dict[str, Any],
    settings: Settings,
    *,
    llm: Callable[[list[dict[str, str]]], str] | None = None,
) -> list[dict[str, Any]]:
    """Llama al modelo (rol deep) y filtra hipotesis sin evidencia suficiente."""

    if not evidence.get("losses") and not evidence.get("misses"):
        return []
    min_evidence = int(getattr(settings, "nightly_retrospective_min_evidence", 3))
    from ..prompt_store import get_prompt

    system = get_prompt(settings, "nightly_retrospective", DEFAULT_RETROSPECTIVE_PROMPT)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(evidence, ensure_ascii=True, default=str)},
    ]
    raw = llm(messages) if llm is not None else _default_llm(settings, messages)
    parsed = _extract_obj(raw)
    hypotheses = parsed.get("hypotheses", []) if isinstance(parsed, dict) else []
    valid: list[dict[str, Any]] = []
    for item in hypotheses:
        if not isinstance(item, dict):
            continue
        refs = item.get("evidence_refs") or []
        if not isinstance(refs, list) or len(refs) < min_evidence:
            continue
        if not str(item.get("pattern_description") or "").strip():
            continue
        valid.append(item)
    return valid


def persist_hypotheses(store: Store, hypotheses: list[dict[str, Any]], session_date: str) -> list[str]:
    """Inserta hipotesis (dedup por fingerprint) con prioridad por nº de casos."""

    inserted: list[str] = []
    for item in hypotheses:
        pattern = str(item.get("pattern_description") or "")
        fingerprint = hashlib.sha256(pattern.encode("utf-8")).hexdigest()[:24]
        refs = item.get("evidence_refs") or []
        confidence = "HIGH" if len(refs) >= 6 else "MEDIUM" if len(refs) >= 4 else "LOW"
        hypothesis_id, created = store.upsert_continuous_improvement_hypothesis(
            {
                "hypothesis_id": new_id("hyp"),
                "event_id": new_id("nightly"),
                "domain": "strategy",
                "subject": pattern[:200],
                "status": "OPEN",
                "confidence": confidence,
                "fingerprint": fingerprint,
                "summary_text": json.dumps(
                    {
                        "entry_rule": item.get("entry_rule"),
                        "exit_rule": item.get("exit_rule"),
                        "invalidation": item.get("invalidation"),
                        "expected_improvement": item.get("expected_improvement"),
                    },
                    ensure_ascii=True,
                ),
                "evidence": refs,
            }
        )
        if created:
            inserted.append(hypothesis_id)
    return inserted


def run_nightly_retrospective(
    store: Store,
    settings: Settings,
    session_date: str,
    *,
    llm: Callable[[list[dict[str, str]]], str] | None = None,
) -> dict[str, Any]:
    evidence = collect_evidence(store, settings, session_date)
    hypotheses = generate_hypotheses(evidence, settings, llm=llm)
    inserted = persist_hypotheses(store, hypotheses, session_date)
    return {
        "session_date": session_date,
        "evidence_counts": evidence["counts"],
        "hypotheses_generated": len(hypotheses),
        "hypotheses_inserted": len(inserted),
        "hypothesis_ids": inserted,
    }


def _extract_obj(raw: str) -> dict[str, Any]:
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


def _default_llm(settings: Settings, messages: list[dict[str, str]]) -> str:
    try:
        from ..llm_router import chat_for_role

        response, _endpoint, _attempts = chat_for_role("deep", settings=settings, messages=messages)
        return response.choices[0].message.content or ""
    except Exception:  # noqa: BLE001
        return ""
