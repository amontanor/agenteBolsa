"""Auditable classification of LLM and deterministic trade decisions.

The classifier is deliberately read-only. It explains the origin of a stored
recommendation without changing routing, ranking, gates, or broker execution.
Older rows often lack an error payload; those rows remain ``unknown`` instead
of being assigned a cause retrospectively.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agente_bolsa.storage import Store

from .reporting import write_json_report

SCHEMA_VERSION = 1
WINDOW_DAYS = 7


def _load_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def classify_fallback_error(value: Any) -> str:
    """Returns a conservative error class; absent evidence is always unknown."""

    text = str(value or "").strip().lower()
    if not text:
        return "unknown"
    if any(marker in text for marker in ("timeout", "timed out", "time out")):
        return "timeout"
    if any(
        marker in text
        for marker in (
            "connection",
            "network",
            "dns",
            "socket",
            "http error",
            "status code",
            "provider",
            "service unavailable",
        )
    ):
        return "network_or_provider"
    if any(marker in text for marker in ("json", "schema", "validation", "parse", "structured output")):
        return "invalid_response_or_schema"
    if any(marker in text for marker in ("budget", "quota", "rate limit", "circuit breaker", "circuit_breaker")):
        return "budget_or_circuit_breaker"
    return "unknown"


def classify_trade_recommendation(payload: dict[str, Any]) -> dict[str, Any]:
    """Classifies one recommendation using only fields persisted with it."""

    source = str(payload.get("source") or payload.get("decision_origin") or "").strip().lower()
    origin = str(payload.get("decision_origin") or "").strip().lower()
    capacity_reason = str(payload.get("capacity_fill_reason_code") or "").strip().lower()
    model_info = payload.get("model_info") if isinstance(payload.get("model_info"), dict) else {}
    fallback_error = model_info.get("decision_fallback_error") or payload.get("decision_fallback_error")
    model = model_info.get("llm_model") or payload.get("model")

    result: dict[str, Any] = {
        "decision_role": "trade_decision",
        "decision_source": source or "unknown",
        "decision_origin": origin or None,
        "model": model or None,
        "classification": "unknown",
        "fallback_reason": None,
        "is_fallback": False,
        "is_llm_failure": False,
    }
    if source == "llm":
        result["classification"] = "real_llm"
        return result

    deterministic = source.startswith("deterministic") or source in {"capacity_fill", "fallback"}
    if not deterministic:
        return result

    result["is_fallback"] = True
    if capacity_reason == "capacity_fill_tras_llm_ok" or origin == "deterministic_fallback_augmented":
        result.update(
            classification="deterministic_capacity_after_llm_ok",
            fallback_reason="capacity_fill_after_llm_ok",
        )
        return result

    if capacity_reason == "capacity_fill_por_fallo_llm" or origin == "deterministic_fallback_llm_failed" or fallback_error:
        result.update(
            classification="deterministic_after_llm_failure",
            fallback_reason=classify_fallback_error(fallback_error),
            is_llm_failure=True,
        )
        return result

    result.update(classification="deterministic_unclassified", fallback_reason="unknown")
    return result


def build_llm_decision_quality(
    store: Store,
    *,
    now: datetime | None = None,
    window_days: int = WINDOW_DAYS,
) -> dict[str, Any]:
    """Builds a backwards-compatible quality snapshot from recommendation rows."""

    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    window_days = max(1, int(window_days))
    cutoff = (reference - timedelta(days=window_days)).isoformat()
    with store.connect() as conn:
        rows = conn.execute(
            """
            SELECT recommendation_id, cycle_id, symbol, action, payload_json, created_at
            FROM trade_recommendations
            WHERE created_at >= ?
            ORDER BY created_at DESC
            """,
            (cutoff,),
        ).fetchall()

    classifications: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    origins: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    models: Counter[str] = Counter()
    known = real = fallback = failure_fallback = unknown = 0
    samples: list[dict[str, Any]] = []
    for row in rows:
        classification = classify_trade_recommendation(_load_payload(row["payload_json"]))
        label = str(classification["classification"])
        classifications[label] += 1
        sources[str(classification["decision_source"])] += 1
        if classification.get("decision_origin"):
            origins[str(classification["decision_origin"])] += 1
        if classification.get("model"):
            models[str(classification["model"])] += 1
        if classification.get("fallback_reason"):
            reasons[str(classification["fallback_reason"])] += 1
        if label == "real_llm":
            real += 1
            known += 1
        elif bool(classification["is_fallback"]):
            fallback += 1
            known += 1
            if bool(classification["is_llm_failure"]):
                failure_fallback += 1
        else:
            unknown += 1
        if len(samples) < 20:
            samples.append(
                {
                    "recommendation_id": row["recommendation_id"],
                    "cycle_id": row["cycle_id"],
                    "symbol": row["symbol"],
                    "action": row["action"],
                    "created_at": row["created_at"],
                    **classification,
                }
            )

    deterministic_after_llm_ok = classifications["deterministic_capacity_after_llm_ok"]
    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": reference.isoformat(),
        "window": {"days": window_days, "from": cutoff, "to": reference.isoformat()},
        "basis": "trade_recommendations",
        "summary": {
            "recommendations": len(rows),
            "known_decisions": known,
            "unknown_decisions": unknown,
            "real_decisions": real,
            "fallback_decisions": fallback,
            "llm_failure_fallback_decisions": failure_fallback,
            "deterministic_after_llm_ok_decisions": deterministic_after_llm_ok,
            "fallback_ratio": round(fallback / known, 4) if known else None,
            "real_ratio": round(real / known, 4) if known else None,
            "llm_failure_fallback_ratio": round(failure_fallback / known, 4) if known else None,
            "status": "available" if known else "unavailable",
        },
        "by_classification": dict(sorted(classifications.items())),
        "by_decision_source": dict(sorted(sources.items())),
        "by_decision_origin": dict(sorted(origins.items())),
        "by_fallback_reason": dict(sorted(reasons.items())),
        "by_model": dict(sorted(models.items())),
        "samples": samples,
    }


def write_llm_decision_quality_report(
    store: Store,
    reports_dir: Path,
    run_id: str,
    *,
    now: datetime | None = None,
    window_days: int = WINDOW_DAYS,
) -> dict[str, Any]:
    report = build_llm_decision_quality(store, now=now, window_days=window_days)
    return write_json_report(
        report,
        reports_dir,
        "llm_decision_quality",
        run_id,
        latest_filename="latest_llm_decision_quality.json",
    )
