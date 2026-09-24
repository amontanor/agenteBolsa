"""Structured, append-only evidence emitted by advisory agents.

The group can discuss freely inside CrewAI, but only this small contract is
allowed to cross into the evidence layer.  It deliberately carries no order
authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from .agent_run import safe_refs

SCHEMA_VERSION = "agent_contribution.v1"
EVENT_TYPE = "agent_contribution"
_STANCES = frozenset({"support", "oppose", "neutral", "abstain", "unavailable"})
_DATA_QUALITIES = frozenset({"good", "partial", "poor", "unavailable"})
_STANCE_ALIASES = {
    "buy": "support",
    "bullish": "support",
    "long": "support",
    "sell": "oppose",
    "bearish": "oppose",
    "short": "oppose",
}
_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.IGNORECASE | re.DOTALL)


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _content_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _normalise_as_of(value: Any) -> str:
    if value is None or value == "":
        parsed = datetime.now(timezone.utc)
    elif isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("agent_contribution_as_of_invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("agent_contribution_as_of_requires_timezone")
    parsed = parsed.astimezone(timezone.utc)
    if parsed > datetime.now(timezone.utc) + timedelta(seconds=5):
        raise ValueError("agent_contribution_as_of_in_future")
    return parsed.isoformat()


def _text(value: Any, *, field: str, required: bool = True, limit: int = 300) -> str | None:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"agent_contribution_{field}_missing")
    if len(text) > limit:
        raise ValueError(f"agent_contribution_{field}_too_long")
    return text or None


def _bounded_confidence(value: Any, stance: str) -> float:
    if value is None or value == "":
        return 0.0 if stance in {"abstain", "unavailable", "neutral"} else math.nan
    try:
        confidence = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("agent_contribution_confidence_invalid") from exc
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise ValueError("agent_contribution_confidence_out_of_range")
    return round(confidence, 6)


def _codes(value: Any, *, field: str, limit: int) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        raise ValueError(f"agent_contribution_{field}_invalid")
    result: list[str] = []
    for item in values[:limit]:
        text = str(item or "").strip()
        if text and len(text) <= 120:
            result.append(text)
    return list(dict.fromkeys(result))


def build_agent_contribution(
    contribution: Mapping[str, Any],
    *,
    cycle_id: str,
    agent_run_id: str,
    agent_name: str,
    as_of: Any = None,
) -> dict[str, Any]:
    """Validate and hash one contribution using runtime-owned identity."""

    if not isinstance(contribution, Mapping):
        raise ValueError("agent_contribution_mapping_required")
    canonical_cycle = _text(cycle_id, field="cycle_id")
    run_id = _text(agent_run_id, field="agent_run_id")
    runtime_agent = _text(agent_name, field="agent_name")
    supplied_cycle = _text(contribution.get("cycle_id"), field="cycle_id", required=False)
    if supplied_cycle and supplied_cycle != canonical_cycle:
        raise ValueError("agent_contribution_cycle_mismatch")
    signal_id = _text(contribution.get("signal_id"), field="signal_id")
    candidate_id = _text(contribution.get("candidate_id"), field="candidate_id")
    raw_stance = str(contribution.get("stance") or "").strip().lower()
    stance = _STANCE_ALIASES.get(raw_stance, raw_stance)
    if stance not in _STANCES:
        raise ValueError("agent_contribution_stance_invalid")
    confidence = _bounded_confidence(contribution.get("confidence"), stance)
    if math.isnan(confidence):
        raise ValueError("agent_contribution_confidence_missing")
    quality = str(contribution.get("data_quality") or "unavailable").strip().lower()
    if quality not in _DATA_QUALITIES:
        raise ValueError("agent_contribution_data_quality_invalid")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "cycle_id": canonical_cycle,
        "agent_run_id": run_id,
        "agent_name": runtime_agent,
        "signal_id": signal_id,
        "candidate_id": candidate_id,
        "stance": stance,
        "confidence": confidence,
        "reason_codes": _codes(contribution.get("reason_codes"), field="reason_codes", limit=12),
        "evidence_refs": safe_refs(_codes(contribution.get("evidence_refs"), field="evidence_refs", limit=20)),
        "data_quality": quality,
        "as_of": _normalise_as_of(contribution.get("as_of", as_of)),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def contribution_event_id(payload: Mapping[str, Any]) -> str:
    """Return a stable event ID for one run/agent/signal/candidate tuple."""

    identity = ":".join(
        str(payload.get(key) or "").strip()
        for key in ("agent_run_id", "agent_name", "signal_id", "candidate_id")
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"agent_contribution:{digest}"


def persist_agent_contribution(store: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Persist with the conflict-safe Store boundary."""

    event_id = contribution_event_id(payload)
    result = store.record_append_only_event(
        event_id=event_id,
        event_type=EVENT_TYPE,
        cycle_id=str(payload.get("cycle_id") or "") or None,
        payload=dict(payload),
    )
    return {"event_id": event_id, "payload": dict(payload), "persistence": result}


def extract_structured_contributions(raw: Any) -> list[dict[str, Any]]:
    """Extract only exact JSON objects; prose is never treated as evidence."""

    if raw is None:
        return []
    if hasattr(raw, "json_dict"):
        raw = raw.json_dict
    if hasattr(raw, "raw"):
        raw = raw.raw
    if hasattr(raw, "output") and not isinstance(raw, (str, bytes, Mapping, list, tuple)):
        raw = raw.output
    if isinstance(raw, Mapping):
        if isinstance(raw.get("contributions"), list):
            return [dict(item) for item in raw["contributions"][:100] if isinstance(item, Mapping)]
        required = {"signal_id", "candidate_id", "stance"}
        return [dict(raw)] if required.issubset(raw) else []
    if isinstance(raw, (list, tuple)):
        return [dict(item) for item in raw[:100] if isinstance(item, Mapping)]
    if not isinstance(raw, str):
        return []
    text = raw.strip()
    match = _FENCE_RE.match(text)
    if match:
        text = match.group(1).strip()
    if not text or text[0] not in "[{":
        return []
    try:
        decoded = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return []
    return extract_structured_contributions(decoded)


def _outcome_for(payload: Mapping[str, Any], outcomes: Any) -> Mapping[str, Any] | None:
    if outcomes is None:
        return None
    signal_id = str(payload.get("signal_id") or "")
    candidate_id = str(payload.get("candidate_id") or "")
    if isinstance(outcomes, Mapping):
        for key in ((signal_id, candidate_id), signal_id, candidate_id):
            item = outcomes.get(key)
            if isinstance(item, Mapping):
                return item
        return None
    for item in outcomes if isinstance(outcomes, (list, tuple)) else []:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("signal_id") or "") == signal_id and str(item.get("candidate_id") or "") == candidate_id:
            return item
    return None


def _binary_label(outcome: Mapping[str, Any]) -> bool | None:
    for key in ("positive", "is_winner"):
        if isinstance(outcome.get(key), bool):
            return outcome[key]
    label = str(outcome.get("label") or "").strip().lower()
    if label in {"positive", "winner", "win", "success", "profitable"}:
        return True
    if label in {"negative", "loser", "loss", "failure", "unprofitable"}:
        return False
    for key in ("net_return_5d", "return_5d", "net_return", "return"):
        value = outcome.get(key)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return float(value) > 0.0
    return None


def summarize_agent_contributions(
    contributions: list[Mapping[str, Any]],
    *,
    run_payloads: list[Mapping[str, Any]] | None = None,
    outcomes: Any = None,
    candidate_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Produce operational and predictive metrics without creating authority."""

    runs_by_id = {
        str(item.get("agent_run_id") or ""): item
        for item in run_payloads or []
        if str(item.get("agent_run_id") or "")
    }
    by_agent: dict[str, dict[str, Any]] = {}
    predictions: dict[str, list[tuple[bool, bool, float]]] = {}
    for contribution in contributions:
        agent = str(contribution.get("agent_name") or "unavailable")
        bucket = by_agent.setdefault(
            agent,
            {
                "agent_name": agent,
                "contributions": 0,
                "unique_candidates": set(),
                "evidence_refs": set(),
                "confidence_sum": 0.0,
                "latency_seconds": [],
                "estimated_cost": [],
            },
        )
        bucket["contributions"] += 1
        candidate = str(contribution.get("candidate_id") or "")
        if candidate:
            bucket["unique_candidates"].add(candidate)
        bucket["evidence_refs"].update(contribution.get("evidence_refs") or [])
        confidence = contribution.get("confidence")
        if isinstance(confidence, (int, float)):
            bucket["confidence_sum"] += float(confidence)
        run = runs_by_id.get(str(contribution.get("agent_run_id") or ""), {})
        duration = run.get("duration_seconds")
        cost = run.get("estimated_cost")
        if isinstance(duration, (int, float)):
            bucket["latency_seconds"].append(float(duration))
        if isinstance(cost, (int, float)):
            bucket["estimated_cost"].append(float(cost))
        outcome = _outcome_for(contribution, outcomes)
        label = _binary_label(outcome) if outcome else None
        stance = str(contribution.get("stance") or "")
        if label is not None and stance in {"support", "oppose"}:
            predictions.setdefault(agent, []).append((stance == "support", label, float(confidence or 0.0)))

    formatted: dict[str, dict[str, Any]] = {}
    for agent, bucket in by_agent.items():
        rows = predictions.get(agent, [])
        tp = sum(pred and actual for pred, actual, _ in rows)
        fp = sum(pred and not actual for pred, actual, _ in rows)
        fn = sum((not pred) and actual for pred, actual, _ in rows)
        formatted[agent] = {
            "agent_name": agent,
            "contributions": bucket["contributions"],
            "unique_candidates": len(bucket["unique_candidates"]),
            "coverage": (
                round(len(bucket["unique_candidates"]) / len(candidate_ids), 4)
                if candidate_ids
                else None
            ),
            "evidence_refs": len(bucket["evidence_refs"]),
            "average_confidence": round(bucket["confidence_sum"] / bucket["contributions"], 4),
            "average_latency_seconds": (
                round(sum(bucket["latency_seconds"]) / len(bucket["latency_seconds"]), 4)
                if bucket["latency_seconds"]
                else None
            ),
            "estimated_cost": round(sum(bucket["estimated_cost"]), 8) if bucket["estimated_cost"] else None,
            "labeled_predictions": len(rows),
            "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "false_positive_rate": round(fp / (fp + tn), 4) if (tn := sum(not pred and not actual for pred, actual, _ in rows)) + fp else None,
            "false_negative_rate": round(fn / (fn + tp), 4) if fn + tp else None,
            "calibration_error": (
                round(
                    sum(abs(confidence - (1.0 if actual else 0.0)) for _, actual, confidence in rows) / len(rows),
                    4,
                )
                if rows
                else None
            ),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "agents": formatted,
        "contributions": len(contributions),
        "unique_candidates": len({str(item.get("candidate_id") or "") for item in contributions if item.get("candidate_id")}),
        "labeled_predictions": sum(len(rows) for rows in predictions.values()),
    }
