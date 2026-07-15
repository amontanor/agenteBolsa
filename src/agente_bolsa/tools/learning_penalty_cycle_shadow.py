"""Ciclo shadow P-L44B para medir una penalización operativa única.

La ruta es observacional: calcula un contrafactual en memoria a partir de los
candidatos ya rankeados por el ciclo y nunca devuelve decisiones operativas.
La persistencia se hace en el ledger append-only de ``agent_events`` mediante
el método específico de :class:`Store`.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from agente_bolsa.config import Settings

from .learning_penalty_shadow import build_learning_penalty_shadow

SCHEMA_VERSION = "p-l44b.learning-penalty-cycle-shadow.v1"
EVENT_TYPE = "learning_penalty_cycle_shadow"

_POST_DECISION_FIELDS = {
    "pnl",
    "profit",
    "realized_pl",
    "unrealized_pl",
    "fill",
    "fills",
    "slippage",
    "return_1d",
    "return_3d",
    "return_5d",
    "return_10d",
    "mfe",
    "mae",
    "first_hit",
    "outcome",
    "verdict",
    "prompt",
    "response",
}


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _identity(candidate: Mapping[str, Any]) -> str | None:
    candidate_id = str(candidate.get("candidate_id") or "").strip()
    signal_id = str(candidate.get("signal_id") or "").strip()
    return candidate_id or signal_id or None


def _identity_kind(candidate: Mapping[str, Any]) -> str | None:
    if str(candidate.get("candidate_id") or "").strip():
        return "candidate_id"
    if str(candidate.get("signal_id") or "").strip():
        return "signal_id"
    return None


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key not in {"captured_at", "content_hash"}}
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _captured_at(value: str | None) -> str:
    if value:
        return value
    return datetime.now(timezone.utc).isoformat()


def _prior_inputs(candidate: Mapping[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    prior = candidate.get("learning_prior") or {}
    if not isinstance(prior, Mapping):
        return None, ["learning_prior_invalid"]
    expected = _finite(prior.get("expected_edge_3d"))
    penalty = _finite(prior.get("operational_penalty"))
    setup_edge = _finite(prior.get("setup_edge_3d_raw"))
    sample = prior.get("sample_size_3d")
    confidence = prior.get("confidence_weight_3d")
    warnings: list[str] = []
    if expected is None:
        warnings.append("historical_edge_unavailable")
    if penalty is None or penalty < 0:
        warnings.append("operational_penalty_invalid")
    if setup_edge is None:
        warnings.append("setup_edge_unavailable")
    if isinstance(sample, bool) or not isinstance(sample, int) or sample < 0:
        warnings.append("sample_size_invalid")
    if _finite(confidence) is None or not 0.0 <= float(confidence) <= 1.0:
        warnings.append("confidence_invalid")
    if warnings:
        return None, warnings
    # The active producer publishes expected_edge_3d after its one producer-side
    # subtraction. Re-adding that explicit penalty only reconstructs the
    # unpenalized historical edge for observation; no active value is changed.
    historical = round(float(expected) + float(penalty), 4)
    return {
        "historical_edge_3d": historical,
        "setup_edge_3d_raw": float(setup_edge),
        "sample_size_3d": int(sample),
        "confidence": float(confidence),
        "operational_penalty": float(penalty),
    }, ["historical_edge_reconstructed_from_legacy"]


def _candidate_detail(
    candidate: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    legacy_rank: int,
    shadow_rank: int,
    selected: bool,
) -> dict[str, Any]:
    prior = candidate.get("learning_prior") if isinstance(candidate.get("learning_prior"), Mapping) else {}
    return {
        "candidate_id": candidate.get("candidate_id"),
        "signal_id": candidate.get("signal_id"),
        "symbol": candidate.get("symbol"),
        "strategy_name": candidate.get("strategy_name"),
        "strategy_version": candidate.get("strategy_version"),
        "decision_source": candidate.get("decision_source"),
        "historical_edge_3d": result.get("historical_edge_3d"),
        "operational_penalty": result.get("operational_penalty"),
        "legacy_expected_edge_3d": result.get("legacy_expected_edge_3d"),
        "single_penalty_expected_edge_3d": result.get("single_penalty_expected_edge_3d"),
        "legacy_selection_score": result.get("legacy_selection_score"),
        "single_penalty_selection_score": result.get("single_penalty_selection_score"),
        "selection_score_delta": result.get("selection_score_delta"),
        "legacy_rank_priority": result.get("legacy_rank_priority"),
        "single_penalty_rank_priority": result.get("single_penalty_rank_priority"),
        "legacy_rank": legacy_rank,
        "shadow_rank": shadow_rank,
        "rank_delta": shadow_rank - legacy_rank,
        "legacy_top_5": legacy_rank <= 5,
        "shadow_top_5": shadow_rank <= 5,
        "selected_by_active_path": selected,
        "availability_status": result.get("status"),
        "warnings": sorted(set(result.get("data_quality_warnings", []) or [])),
        "sample_size_3d": prior.get("sample_size_3d"),
        "confidence": prior.get("confidence_weight_3d"),
    }


def _safe_detail(detail: Mapping[str, Any]) -> dict[str, Any]:
    # Keep only pre-decision telemetry, even when a caller passes a rich
    # candidate object containing later execution fields.
    return {
        key: value
        for key, value in detail.items()
        if str(key).lower() not in _POST_DECISION_FIELDS
    }


def build_learning_penalty_cycle_shadow(
    cycle_id: str,
    technical_context: Mapping[str, Any] | None,
    *,
    selected_candidates: Iterable[Mapping[str, Any]] | None = None,
    control_candidates: Iterable[Mapping[str, Any]] | None = None,
    configured_capacity: int | None = None,
    settings: Settings | None = None,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Build a bounded cycle snapshot without influencing the active path."""

    context = technical_context if isinstance(technical_context, Mapping) else {}
    source = context.get("all_candidates") or context.get("ranked_candidates") or []
    candidates = [item for item in source if isinstance(item, Mapping) and str(item.get("direction") or "long").lower() in {"long", "buy"}]
    by_identity: dict[str, Mapping[str, Any]] = {}
    duplicate_ids: set[str] = set()
    for item in candidates:
        if _finite(item.get("rank_priority_score")) is None and not isinstance(item.get("learning_prior"), Mapping):
            continue
        identity = _identity(item)
        if identity is None:
            continue
        if identity in by_identity:
            duplicate_ids.add(identity)
        else:
            by_identity[identity] = item
    unique_candidates = [item for identity, item in by_identity.items() if identity not in duplicate_ids]
    ranked_total = len(candidates)
    selected_ids = {_identity(item) for item in (selected_candidates or []) if isinstance(item, Mapping)}
    control_ids = {_identity(item) for item in (control_candidates or []) if isinstance(item, Mapping)}
    settings = settings or Settings(_env_file=None)

    rows: list[dict[str, Any]] = []
    unavailable_identity = max(0, ranked_total - len(by_identity))
    invalid = 0
    for item in unique_candidates:
        inputs, input_warnings = _prior_inputs(item)
        if inputs is None:
            invalid += 1
            rows.append({"candidate": item, "identity": _identity(item), "result": {"status": "unavailable", "data_quality_warnings": input_warnings}})
            continue
        result = build_learning_penalty_shadow(item, settings=settings, **inputs)
        if result.get("status") != "available":
            invalid += 1
        rows.append({"candidate": item, "identity": _identity(item), "result": result})

    valid = [row for row in rows if row["result"].get("status") == "available"]
    def _sort_key(row: Mapping[str, Any], field: str) -> tuple[float, str]:
        value = _finite(row["result"].get(field))
        return (-(value if value is not None else float("-inf")), str(row.get("identity") or ""))

    legacy_order = sorted(valid, key=lambda row: _sort_key(row, "legacy_rank_priority"))
    shadow_order = sorted(valid, key=lambda row: _sort_key(row, "single_penalty_rank_priority"))
    legacy_rank = {str(row["identity"]): index for index, row in enumerate(legacy_order, start=1)}
    shadow_rank = {str(row["identity"]): index for index, row in enumerate(shadow_order, start=1)}
    legacy_ids = [str(row["identity"]) for row in legacy_order[:20]]
    shadow_ids = [str(row["identity"]) for row in shadow_order[:20]]
    detail_ids = set(legacy_ids) | set(shadow_ids) | {item for item in selected_ids | control_ids if item}
    bounded = [
        _safe_detail(
            _candidate_detail(
                row["candidate"],
                row["result"],
                legacy_rank=legacy_rank.get(str(row["identity"]), None) or 0,
                shadow_rank=shadow_rank.get(str(row["identity"]), None) or 0,
                selected=str(row["identity"]) in selected_ids,
            )
        )
        for row in rows
        if row.get("identity") in detail_ids
    ]
    rank_deltas = [abs(shadow_rank[key] - legacy_rank[key]) for key in legacy_rank if key in shadow_rank]
    legacy_top5 = set(legacy_ids[:5])
    shadow_top5 = set(shadow_ids[:5])
    capacity = int(configured_capacity) if configured_capacity is not None and int(configured_capacity) > 0 else None
    capacity_changed = None
    if capacity is not None:
        capacity_changed = set(legacy_ids[:capacity]) != set(shadow_ids[:capacity])
    status = "unavailable" if not candidates else "available" if len(valid) == len(candidates) else "partial"
    if duplicate_ids:
        status = "partial"
    counts = {
        "ranked_buy_total": ranked_total,
        "shadow_available": len(valid),
        "shadow_invalid": invalid,
        "identity_unavailable": unavailable_identity + len(duplicate_ids),
        "detail_persisted": len(bounded),
        "detail_omitted": max(0, len(valid) - len(bounded)),
    }
    snapshot: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "cycle_id": str(cycle_id),
        "status": status,
        "policy_mode": "shadow_only",
        "active_policy": "legacy_double_application",
        "shadow_policy": "single_application",
        "captured_at": _captured_at(captured_at),
        "candidate_counts": counts,
        "configured_capacity": capacity,
        "legacy_top_ids": legacy_ids,
        "shadow_top_ids": shadow_ids,
        "top_5_membership_changed": legacy_top5 != shadow_top5 if valid else None,
        "configured_capacity_membership_changed": capacity_changed,
        "rank_changed_count": sum(1 for key in legacy_rank if key in shadow_rank and legacy_rank[key] != shadow_rank[key]) if valid else None,
        "max_absolute_rank_delta": max(rank_deltas) if rank_deltas else None,
        "mean_absolute_rank_delta": round(sum(rank_deltas) / len(rank_deltas), 4) if rank_deltas else None,
        "selected_candidates": sorted(item for item in selected_ids if item),
        "bounded_candidates": bounded,
        "warnings": sorted({"duplicate_identity_ambiguous"} if duplicate_ids else set()),
    }
    snapshot["content_hash"] = _canonical_hash(snapshot)
    return snapshot


def persist_learning_penalty_cycle_shadow(store: Any, snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Persist one cycle snapshot through the conflict-safe Store boundary."""

    cycle_id = str(snapshot.get("cycle_id") or "").strip()
    if not cycle_id:
        return {"status": "unavailable", "reason": "missing_cycle_id"}
    event_id = f"learning_penalty_cycle_shadow:{cycle_id}"
    return store.record_learning_penalty_cycle_shadow(dict(snapshot), event_id=event_id, cycle_id=cycle_id)


def learning_penalty_shadow_digest(store: Any, *, limit: int = 50000) -> dict[str, Any]:
    """Read valid cycle events; conflicts are visible but never counted valid."""

    try:
        events = store.learning_penalty_cycle_shadow_events(limit=limit)
        conflict_events = store.agent_events(event_type_prefix="learning_penalty_cycle_shadow_conflict", limit=limit)
    except Exception as exc:  # pragma: no cover - defensive observability path
        if "no such table" in str(exc).lower():
            return {
                "status": "collecting",
                "shadow_only": True,
                "observations": None,
                "cycles": None,
                "candidate_counts": None,
                "conflicts": len(conflict_events),
                "legacy_unavailable": True,
            }
        return {"status": "degraded_observability", "shadow_only": True, "error": str(exc), "observations": None}
    if not events:
        return {
            "status": "degraded_observability" if conflict_events else "collecting",
            "shadow_only": True,
            "observations": None,
            "cycles": None,
            "candidate_counts": None,
            "conflicts": len(conflict_events) if conflict_events else None,
        }
    totals = {key: 0 for key in ("ranked_buy_total", "shadow_available", "shadow_invalid", "identity_unavailable", "detail_persisted", "detail_omitted")}
    for event in events:
        for key, value in (event.get("candidate_counts") or {}).items():
            if key in totals and isinstance(value, int):
                totals[key] += value
    return {
        "status": "available",
        "shadow_only": True,
        "observations": len(events),
        "cycles": len({str(item.get("cycle_id") or "") for item in events}),
        "candidate_counts": totals,
        "latest_cycle_id": events[-1].get("cycle_id"),
        "latest_captured_at": events[-1].get("captured_at"),
        "conflicts": len(conflict_events),
    }


def read_learning_penalty_shadow_events(store: Any, *, limit: int = 50000) -> list[dict[str, Any]]:
    return store.learning_penalty_cycle_shadow_events(limit=limit)
