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
    """Return the stable display/link identity used by phase B.

    The raw shadow admission decision is made by :func:`_identity_evidence`
    below.  Keeping this compatibility order (candidate then signal) lets
    already persisted phase-B lineage continue to link without changing its
    identifiers, while the capture/signal authority is recorded separately.
    """
    candidate_id = str(candidate.get("candidate_id") or "").strip()
    signal_id = str(candidate.get("signal_id") or "").strip()
    return candidate_id or signal_id or None


def _identity_evidence(candidate: Mapping[str, Any]) -> tuple[str | None, str | None, str | None]:
    """Return ``(canonical_key, status, source)`` for raw shadow admission.

    ``signal_capture_id`` is the strongest available identity, followed by
    the canonical ``signal_id``.  A candidate id alone is intentionally not
    sufficient: it may be minted after the raw capture and cannot be used to
    reconstruct identity by symbol/date.
    """

    capture_id = str(candidate.get("signal_capture_id") or "").strip()
    signal_id = str(candidate.get("signal_id") or "").strip()
    if capture_id:
        return capture_id, "identity_verified", "signal_capture_id"
    if signal_id:
        return signal_id, "identity_verified", "signal_id"
    return None, "identity_unavailable", None


def _candidate_cycle_id(candidate: Mapping[str, Any]) -> str | None:
    direct = str(candidate.get("cycle_id") or "").strip()
    if direct:
        return direct
    lineage = candidate.get("decision_lineage")
    if isinstance(lineage, Mapping):
        value = str(lineage.get("cycle_id") or "").strip()
        if value:
            return value
    return None


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
    selected: bool = False,
    identity_status: str | None = None,
    identity_source: str | None = None,
    identity_key: str | None = None,
) -> dict[str, Any]:
    prior = candidate.get("learning_prior") if isinstance(candidate.get("learning_prior"), Mapping) else {}
    return {
        "candidate_id": candidate.get("candidate_id"),
        "signal_id": candidate.get("signal_id"),
        "signal_capture_id": candidate.get("signal_capture_id"),
        "identity_status": identity_status or result.get("identity_status"),
        "identity_source": identity_source or result.get("identity_source"),
        "identity_key": identity_key or result.get("identity_key"),
        "symbol": candidate.get("symbol"),
        "strategy_name": candidate.get("strategy_name"),
        "strategy_version": candidate.get("strategy_version"),
        "decision_source": candidate.get("decision_source"),
        "decision_source_status": "available" if candidate.get("decision_source") else "unavailable",
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
        "selected_by_decision": selected,
        "planned_by_active_path": False,
        "comparable_control": False,
        "blocked_candidate": False,
        "final_non_execution_reason": None,
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
    active_candidates: Iterable[Mapping[str, Any]] | None = None,
    configured_capacity: int | None = None,
    settings: Settings | None = None,
    captured_at: str | None = None,
    input_wiring: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the phase-A snapshot without influencing the active path.

    ``active_candidates`` is the exact ordered list delivered to the active
    cycle.  It is deliberately retained as the legacy ordering authority; no
    second ranking is performed here.  Persistence is intentionally deferred
    to :func:`finalize_learning_penalty_cycle_shadow`.
    """

    context = technical_context if isinstance(technical_context, Mapping) else {}
    source = list(context.get("all_candidates") or context.get("ranked_candidates") or active_candidates or [])
    candidates = [item for item in source if isinstance(item, Mapping) and str(item.get("direction") or "long").lower() in {"long", "buy"}]
    ranked_total = len(candidates)
    selected_ids = {_identity(item) for item in (selected_candidates or []) if isinstance(item, Mapping)}
    control_ids = {_identity(item) for item in (control_candidates or []) if isinstance(item, Mapping)}
    settings = settings or Settings(_env_file=None)

    canonical_groups: dict[str, list[Mapping[str, Any]]] = {}
    signal_groups: dict[str, list[Mapping[str, Any]]] = {}
    candidate_meta: list[dict[str, Any]] = []
    for item in candidates:
        canonical_key, identity_status, identity_source = _identity_evidence(item)
        internal_cycle = _candidate_cycle_id(item)
        cycle_warning = bool(internal_cycle and internal_cycle != str(cycle_id))
        if cycle_warning:
            identity_status = "identity_ambiguous"
            canonical_key = canonical_key or _identity(item)
        if canonical_key and not cycle_warning:
            canonical_groups.setdefault(canonical_key, []).append(item)
        signal_id = str(item.get("signal_id") or "").strip()
        if signal_id:
            signal_groups.setdefault(signal_id, []).append(item)
        candidate_meta.append(
            {
                "candidate": item,
                "identity": _identity(item) or canonical_key,
                "identity_key": canonical_key,
                "identity_status": identity_status,
                "identity_source": identity_source,
                "cycle_warning": cycle_warning,
            }
        )
    duplicate_keys = {key for key, values in canonical_groups.items() if len(values) > 1}
    duplicate_signals = {key for key, values in signal_groups.items() if len(values) > 1}

    rows: list[dict[str, Any]] = []
    invalid = 0
    shadow_inputs_unavailable = 0
    shadow_inputs_invalid = 0
    identity_unavailable = 0
    identity_ambiguous = 0
    for meta in candidate_meta:
        item = meta["candidate"]
        identity = meta["identity"]
        identity_key = meta["identity_key"]
        identity_status = meta["identity_status"]
        identity_source = meta["identity_source"]
        warnings: list[str] = []
        if meta["cycle_warning"]:
            warnings.append("cycle_id_mismatch")
        signal_id = str(item.get("signal_id") or "").strip()
        if identity_key in duplicate_keys or signal_id in duplicate_signals:
            identity_status = "identity_ambiguous"
            warnings.append("duplicate_identity_ambiguous")
        if identity_status == "identity_unavailable":
            identity_unavailable += 1
            rows.append(
                {
                    "candidate": item,
                    "identity": identity,
                    "identity_key": identity_key,
                    "identity_status": identity_status,
                    "identity_source": identity_source,
                    "result": {
                        "status": "unavailable",
                        "identity_status": identity_status,
                        "identity_source": identity_source,
                        "identity_key": identity_key,
                        "data_quality_warnings": ["identity_unavailable"],
                    },
                }
            )
            continue
        if identity_status == "identity_ambiguous":
            identity_ambiguous += 1
            rows.append(
                {
                    "candidate": item,
                    "identity": identity,
                    "identity_key": identity_key,
                    "identity_status": identity_status,
                    "identity_source": identity_source,
                    "result": {
                        "status": "unavailable",
                        "identity_status": identity_status,
                        "identity_source": identity_source,
                        "identity_key": identity_key,
                        "data_quality_warnings": sorted(set(warnings + ["identity_ambiguous"])),
                    },
                }
            )
            continue
        has_prior_mapping = isinstance(item.get("learning_prior"), Mapping)
        if not has_prior_mapping:
            shadow_inputs_unavailable += 1
            rows.append(
                {
                    "candidate": item,
                    "identity": identity,
                    "identity_key": identity_key,
                    "identity_status": identity_status,
                    "identity_source": identity_source,
                    "result": {
                        "status": "unavailable",
                        "identity_status": identity_status,
                        "identity_source": identity_source,
                        "identity_key": identity_key,
                        "data_quality_warnings": ["shadow_inputs_unavailable"],
                    },
                }
            )
            continue
        inputs, input_warnings = _prior_inputs(item)
        if inputs is None:
            invalid += 1
            shadow_inputs_invalid += 1
            rows.append(
                {
                    "candidate": item,
                    "identity": identity,
                    "identity_key": identity_key,
                    "identity_status": identity_status,
                    "identity_source": identity_source,
                    "result": {
                        "status": "unavailable",
                        "identity_status": identity_status,
                        "identity_source": identity_source,
                        "identity_key": identity_key,
                        "data_quality_warnings": sorted(set(input_warnings + warnings)),
                    },
                }
            )
            continue
        result = build_learning_penalty_shadow(item, settings=settings, **inputs)
        if result.get("status") != "available":
            invalid += 1
            shadow_inputs_invalid += 1
        result = dict(result)
        result.update(
            {
                "identity_status": identity_status,
                "identity_source": identity_source,
                "identity_key": identity_key,
                "data_quality_warnings": sorted(set((result.get("data_quality_warnings") or []) + warnings)),
            }
        )
        rows.append(
            {
                "candidate": item,
                "identity": identity,
                "identity_key": identity_key,
                "identity_status": identity_status,
                "identity_source": identity_source,
                "result": result,
            }
        )

    valid = [row for row in rows if row["result"].get("status") == "available"]
    def _sort_key(row: Mapping[str, Any], field: str) -> tuple[float, str]:
        value = _finite(row["result"].get(field))
        return (-(value if value is not None else float("-inf")), str(row.get("identity") or ""))

    # The active list is already ranked by production.  Preserve that order
    # exactly for legacy_rank.  Shadow order uses the same deterministic
    # tie-break (the active position), never an invented alphabetical order.
    active_source = list(active_candidates or source)
    active_position = {
        str(_identity(item)): index
        for index, item in enumerate(active_source)
        if isinstance(item, Mapping) and _identity(item)
    }
    next_position = len(active_position)
    for row in rows:
        identity = str(row["identity"] or row.get("identity_key") or "")
        if not identity:
            continue
        if identity not in active_position:
            active_position[identity] = next_position
            next_position += 1
    legacy_order = sorted(valid, key=lambda row: active_position.get(str(row["identity"]), 10**9))
    def _shadow_key(row: Mapping[str, Any]) -> tuple[float, int]:
        # ``0.0`` is a valid rank.  Do not treat it as a missing value via
        # ``value or -inf`` because that would move a zero-ranked candidate
        # behind every finite candidate.
        value = _finite(row["result"].get("single_penalty_rank_priority"))
        return (
            -(value if value is not None else float("-inf")),
            active_position.get(str(row["identity"]), 10**9),
        )

    shadow_order = sorted(valid, key=_shadow_key)
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
                selected=False,
                identity_status=row.get("identity_status"),
                identity_source=row.get("identity_source"),
                identity_key=row.get("identity_key"),
            )
        )
        for row in rows
        if row.get("identity") in detail_ids
    ]
    pool_details = {
        str(row["identity"]): _safe_detail(
            _candidate_detail(
                row["candidate"],
                row["result"],
                legacy_rank=legacy_rank.get(str(row["identity"]), 0),
                shadow_rank=shadow_rank.get(str(row["identity"]), 0),
                selected=False,
                identity_status=row.get("identity_status"),
                identity_source=row.get("identity_source"),
                identity_key=row.get("identity_key"),
            )
        )
        for row in rows
        if row.get("identity")
    }
    rank_deltas = [abs(shadow_rank[key] - legacy_rank[key]) for key in legacy_rank if key in shadow_rank]
    legacy_top5 = set(legacy_ids[:5])
    shadow_top5 = set(shadow_ids[:5])
    capacity = int(configured_capacity) if configured_capacity is not None and int(configured_capacity) > 0 else None
    capacity_changed = None
    if capacity is not None:
        capacity_changed = set(legacy_ids[:capacity]) != set(shadow_ids[:capacity])
    identity_verified = sum(1 for row in rows if row.get("identity_status") == "identity_verified")
    status = "unavailable" if not candidates else "available" if len(valid) == len(candidates) else "partial"
    if identity_unavailable == ranked_total or identity_ambiguous == ranked_total:
        status = "unavailable"
    elif identity_unavailable or identity_ambiguous or shadow_inputs_unavailable or shadow_inputs_invalid:
        status = "partial"
    counts = {
        "ranked_buy_total": ranked_total,
        "shadow_available": len(valid),
        "shadow_invalid": invalid,
        "identity_verified": identity_verified,
        "identity_unavailable": identity_unavailable,
        "identity_ambiguous": identity_ambiguous,
        "shadow_inputs_available": len(valid),
        "shadow_inputs_unavailable": shadow_inputs_unavailable,
        "shadow_inputs_invalid": shadow_inputs_invalid,
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
        "phase": "pre_decision",
        "selected_candidates": [],
        "planned_candidates": [],
        "comparable_control_candidates": [],
        "bounded_candidates": bounded,
        "_candidate_pool": pool_details,
        "input_wiring": dict(input_wiring or {}),
        "warnings": sorted(
            set(
                (["duplicate_identity_ambiguous"] if duplicate_keys or duplicate_signals else [])
                + (["cycle_id_mismatch"] if any(meta["cycle_warning"] for meta in candidate_meta) else [])
                + (["identity_contract_gap"] if identity_unavailable or identity_ambiguous else [])
            )
        ),
    }
    snapshot["content_hash"] = _canonical_hash(snapshot)
    return snapshot


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        from dataclasses import asdict

        return asdict(value)
    except (TypeError, ValueError):
        return {
            key: getattr(value, key, None)
            for key in ("symbol", "action", "side", "decision_lineage", "source", "decision_source")
        }


def _identity_parts(value: Any) -> tuple[str | None, str | None]:
    item = _as_mapping(value)
    lineage = item.get("decision_lineage") if isinstance(item.get("decision_lineage"), Mapping) else {}
    candidate_id = str(item.get("candidate_id") or lineage.get("candidate_id") or "").strip() or None
    signal_id = str(item.get("signal_id") or lineage.get("signal_id") or "").strip() or None
    if not candidate_id and not signal_id and isinstance(item.get("recommendation"), Mapping):
        nested = item["recommendation"]
        nested_lineage = nested.get("decision_lineage") if isinstance(nested.get("decision_lineage"), Mapping) else {}
        candidate_id = str(nested.get("candidate_id") or nested_lineage.get("candidate_id") or "").strip() or None
        signal_id = str(nested.get("signal_id") or nested_lineage.get("signal_id") or "").strip() or None
    return candidate_id, signal_id


def _cycle_id(value: Any) -> str | None:
    """Read a cycle id from the value or its embedded recommendation/lineage."""

    item = _as_mapping(value)
    direct = str(item.get("cycle_id") or "").strip()
    if direct:
        return direct
    lineage = item.get("decision_lineage") if isinstance(item.get("decision_lineage"), Mapping) else {}
    lineage_cycle = str(lineage.get("cycle_id") or "").strip()
    if lineage_cycle:
        return lineage_cycle
    nested = item.get("recommendation")
    if isinstance(nested, Mapping):
        return _cycle_id(nested)
    return None


def _cycle_matches(value: Any, cycle_id: str | None) -> bool:
    expected = str(cycle_id or "").strip()
    return bool(expected and _cycle_id(value) == expected)


def _identity_matches(left: Any, right: Any) -> bool:
    left_candidate, left_signal = _identity_parts(left)
    right_candidate, right_signal = _identity_parts(right)
    shared = False
    if left_candidate and right_candidate:
        if left_candidate != right_candidate:
            return False
        shared = True
    if left_signal and right_signal:
        if left_signal != right_signal:
            return False
        shared = True
    return shared


def _buy(value: Any) -> bool:
    item = _as_mapping(value)
    side = str(item.get("action") or item.get("side") or "").lower()
    return side == "buy"


def _matched_detail(detail: Mapping[str, Any], values: Iterable[Any], *, cycle_id: str | None) -> bool:
    return any(
        _cycle_matches(value, cycle_id) and _identity_matches(detail, value)
        for value in values
    )


def _gate_block_reason(value: Any, *, cycle_id: str | None) -> str | None:
    """Return a blocked gate reason only when the snapshot links exactly."""

    if not _cycle_matches(value, cycle_id):
        return None
    item = _as_mapping(value)
    if item.get("identity_status") not in {"verified", "strong"}:
        return None
    path = item.get("gate_path") or []
    for gate in path:
        if not isinstance(gate, Mapping) or gate.get("status") != "blocked":
            continue
        if gate.get("identity_link_status") not in {"verified", "strong"}:
            return None
        return str(gate.get("reason_code") or gate.get("gate_name") or "gate_blocked")
    return "gate_blocked" if item.get("decision") == "blocked" else None


def finalize_learning_penalty_cycle_shadow(
    phase_a: Mapping[str, Any],
    *,
    recommendations: Iterable[Any] | None = None,
    plans: Iterable[Any] | None = None,
    comparable_control_sets: Mapping[str, Mapping[str, Any]] | None = None,
    rejected_order_plans: Iterable[Mapping[str, Any]] | None = None,
    gate_snapshots: Mapping[str, Mapping[str, Any]] | None = None,
    cycle_id: str | None = None,
    captured_at: str | None = None,
    phase_b_available: bool = True,
) -> dict[str, Any]:
    """Attach only real post-selection facts to the phase-A snapshot.

    Scores, ranks and shadow calculations are never recomputed.  Missing
    identity is left unavailable rather than joined by symbol/date.
    """

    snapshot = json.loads(json.dumps(dict(phase_a), ensure_ascii=False, default=str))
    candidate_pool = snapshot.pop("_candidate_pool", {})
    cycle_mismatch = False
    if cycle_id and str(snapshot.get("cycle_id") or "") != str(cycle_id):
        cycle_mismatch = True
        snapshot["status"] = "unavailable"
        snapshot.setdefault("warnings", []).append("cycle_id_mismatch")
        phase_b_available = False

    raw_recs = [value for value in (recommendations or []) if _buy(value)]
    raw_plans = [value for value in (plans or []) if str(_as_mapping(value).get("side") or "").lower() == "buy"]
    recs = [value for value in raw_recs if _cycle_matches(value, cycle_id)]
    final_plans = [value for value in raw_plans if _cycle_matches(value, cycle_id)]
    rejected = [dict(value) for value in (rejected_order_plans or []) if isinstance(value, Mapping)]
    controls = comparable_control_sets or {}
    control_rows: list[Mapping[str, Any]] = []
    for control_set in controls.values():
        if not isinstance(control_set, Mapping):
            continue
        control_rows.extend(item for item in (control_set.get("controls") or []) if isinstance(item, Mapping))

    rejected_exact: list[Mapping[str, Any]] = []
    for row in rejected:
        if _cycle_matches(row, cycle_id) and (_identity_parts(row)[0] or _identity_parts(row)[1]):
            rejected_exact.append(row)

    identity_issues = any(
        not _cycle_matches(value, cycle_id) or not any(_identity_parts(value))
        for value in [*raw_recs, *raw_plans]
    )
    gate_rows = [
        value
        for value in (gate_snapshots or {}).values()
        if isinstance(value, Mapping) and _cycle_matches(value, cycle_id)
    ]

    # A final plan/control may sit outside the bounded top-20 detail.  Add
    # only those exact identities from the phase-A pool; never reconstruct by
    # symbol/date and never persist the full pool.
    required_values = [*recs, *final_plans, *control_rows, *rejected_exact]
    existing_ids = {_identity(item) for item in snapshot.get("bounded_candidates") or []}
    for identity, detail in (candidate_pool.items() if isinstance(candidate_pool, Mapping) else []):
        if identity in existing_ids:
            continue
        if any(
            _cycle_matches(value, cycle_id) and _identity_matches(detail, value)
            for value in required_values
        ):
            snapshot.setdefault("bounded_candidates", []).append(dict(detail))
            existing_ids.add(identity)

    selected_ids: list[str] = []
    planned_ids: list[str] = []
    control_ids: list[str] = []
    for detail in snapshot.get("bounded_candidates") or []:
        if not isinstance(detail, dict):
            continue
        selected = _matched_detail(detail, recs, cycle_id=cycle_id)
        planned = _matched_detail(detail, final_plans, cycle_id=cycle_id)
        comparable = _matched_detail(detail, control_rows, cycle_id=cycle_id)
        rejection = next((row for row in rejected_exact if _identity_matches(detail, row)), None)
        gate_reason = next(
            (
                reason
                for gate in gate_rows
                if _identity_matches(detail, gate)
                for reason in [_gate_block_reason(gate, cycle_id=cycle_id)]
                if reason
            ),
            None,
        )
        decision_source = None
        source_status = "unavailable"
        matched_recommendation = next((value for value in recs if _identity_matches(detail, value)), None)
        if matched_recommendation is not None:
            item = _as_mapping(matched_recommendation)
            lineage = item.get("decision_lineage") if isinstance(item.get("decision_lineage"), Mapping) else {}
            decision_source = (
                item.get("decision_source")
                or lineage.get("decision_source")
                or item.get("source")
                or item.get("decision_origin")
            )
            source_status = "available" if decision_source else "unavailable"
        detail["selected_by_decision"] = selected
        detail["planned_by_active_path"] = planned
        blocked = bool(rejection or gate_reason)
        # A blocked treatment is not a primary comparable control, even if a
        # malformed/legacy control payload happens to mention the same id.
        detail["comparable_control"] = comparable and not blocked
        detail["blocked_candidate"] = blocked
        detail["final_non_execution_reason"] = (
            (rejection or {}).get("reason") or gate_reason
            if blocked
            else None
        )
        detail["decision_source"] = decision_source
        detail["decision_source_status"] = source_status
        # Compatibility alias is derived only from the final plan path.
        detail.pop("selected_by_active_path", None)
        identity = _identity(detail)
        if selected and identity:
            selected_ids.append(identity)
        if planned and identity:
            planned_ids.append(identity)
        if comparable and identity:
            control_ids.append(identity)

    snapshot["phase"] = "post_selection"
    snapshot["selected_candidates"] = sorted(set(selected_ids))
    snapshot["planned_candidates"] = sorted(set(planned_ids))
    snapshot["comparable_control_candidates"] = sorted(set(control_ids))
    snapshot.setdefault("candidate_counts", {})["selected_by_decision"] = len(set(selected_ids))
    snapshot["candidate_counts"]["planned_by_active_path"] = len(set(planned_ids))
    snapshot["candidate_counts"]["comparable_control"] = len(set(control_ids))
    snapshot["candidate_counts"]["blocked_candidate"] = sum(bool(item.get("blocked_candidate")) for item in snapshot.get("bounded_candidates") or [])
    snapshot["candidate_counts"]["detail_persisted"] = len(snapshot.get("bounded_candidates") or [])
    snapshot["candidate_counts"]["detail_omitted"] = max(
        0,
        int(snapshot["candidate_counts"].get("shadow_available") or 0)
        - int(snapshot["candidate_counts"].get("detail_persisted") or 0),
    )
    if identity_issues:
        snapshot.setdefault("warnings", []).append("phase_b_identity_unavailable")
    if cycle_mismatch:
        snapshot["status"] = "unavailable"
    elif not phase_b_available:
        snapshot["status"] = "partial"
        snapshot.setdefault("warnings", []).append("phase_b_unavailable")
    elif identity_issues:
        snapshot["status"] = "partial"
    elif snapshot.get("status") not in {"partial", "unavailable"}:
        snapshot["status"] = "available"
    snapshot["captured_at"] = _captured_at(captured_at)
    snapshot["content_hash"] = _canonical_hash(snapshot)
    return snapshot


def persist_learning_penalty_cycle_shadow(store: Any, snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Persist one cycle snapshot through the conflict-safe Store boundary."""

    cycle_id = str(snapshot.get("cycle_id") or "").strip()
    if not cycle_id:
        return {"status": "unavailable", "reason": "missing_cycle_id"}
    event_id = f"learning_penalty_cycle_shadow:{cycle_id}"
    return store.record_learning_penalty_cycle_shadow(dict(snapshot), event_id=event_id, cycle_id=cycle_id)


def learning_penalty_shadow_digest(
    store: Any,
    *,
    limit: int = 50000,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Publish one denominator set per canonical cycle.

    ``now`` is injectable for deterministic health tests.  It is used only to
    describe freshness and never participates in the snapshot content hash.
    """

    try:
        readout = store.learning_penalty_cycle_shadow_read(limit=limit)
        events = list(readout.get("events") or [])
    except AttributeError:
        events = store.learning_penalty_cycle_shadow_events(limit=limit)
        readout = {
            "events": events,
            "canonical_cycles": len({str(item.get("cycle_id") or "") for item in events}),
            "canonical_events": len(events),
            "generic_reporter_rows_ignored": 0,
            "conflicts": len(store.agent_events(event_type_prefix="learning_penalty_cycle_shadow_conflict", limit=limit)),
        }
    except Exception as exc:  # pragma: no cover - defensive observability path
        if "no such table" in str(exc).lower():
            return {
                "status": "collecting",
                "shadow_only": True,
                "observations": None,
                "cycles": None,
                "candidate_counts": None,
                "canonical_cycles": None,
                "canonical_events": None,
                "generic_reporter_rows_ignored": None,
                "invalid_canonical_rows": None,
                "idempotent_duplicates": None,
                "conflicts": None,
                "freshness": {"status": "unavailable", "latest_event_created_at": None},
                "legacy_unavailable": True,
            }
        return {"status": "degraded_observability", "shadow_only": True, "error": str(exc), "observations": None}

    canonical_cycles = int(readout.get("canonical_cycles") or 0)
    generic_ignored = int(readout.get("generic_reporter_rows_ignored") or 0)
    conflicts = int(readout.get("conflicts") or 0)
    if not events:
        return {
            "status": "collecting",
            "shadow_only": True,
            "observations": None,
            "cycles": None,
            "canonical_cycles": None,
            "canonical_events": None,
            "generic_reporter_rows_ignored": generic_ignored,
            "invalid_canonical_rows": int(readout.get("invalid_canonical_rows") or 0),
            "idempotent_duplicates": int(readout.get("idempotent_duplicates") or 0),
            "candidate_counts": None,
            "conflicts": None if not conflicts else conflicts,
            "freshness": {"status": "unavailable", "latest_event_created_at": None, "latest_captured_at": None},
        }

    count_keys = (
        "ranked_buy_total",
        "shadow_available",
        "shadow_invalid",
        "identity_verified",
        "identity_unavailable",
        "identity_ambiguous",
        "shadow_inputs_available",
        "shadow_inputs_unavailable",
        "shadow_inputs_invalid",
        "detail_persisted",
        "detail_omitted",
        "selected_by_decision",
        "planned_by_active_path",
        "comparable_control",
        "blocked_candidate",
    )
    totals = {key: 0 for key in count_keys}
    for event in events:
        for key in count_keys:
            value = (event.get("candidate_counts") or {}).get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                totals[key] += value
    event_statuses = {str(item.get("status") or "unavailable") for item in events}
    digest_status = "available"
    if event_statuses == {"unavailable"}:
        digest_status = "unavailable"
    elif event_statuses & {"partial", "unavailable"}:
        digest_status = "partial"
    latest = events[-1]
    latest_created = latest.get("created_at")
    latest_captured = latest.get("captured_at")
    freshness_status = "unknown"
    age_seconds: float | None = None
    try:
        created_dt = datetime.fromisoformat(str(latest_created).replace("Z", "+00:00"))
        reference = now or datetime.now(timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        age_seconds = max(0.0, (reference - created_dt).total_seconds())
        freshness_status = "fresh" if age_seconds <= 24 * 60 * 60 else "stale"
    except (TypeError, ValueError):
        freshness_status = "unavailable"
    return {
        "status": digest_status,
        "shadow_only": True,
        "observations": len(events),
        "cycles": canonical_cycles,
        "canonical_cycles": canonical_cycles,
        "canonical_events": int(readout.get("canonical_events") or len(events)),
        "generic_reporter_rows_ignored": generic_ignored,
        "invalid_canonical_rows": int(readout.get("invalid_canonical_rows") or 0),
        "idempotent_duplicates": int(readout.get("idempotent_duplicates") or 0),
        "candidate_counts": totals,
        "identity_coverage": {
            "verified": totals["identity_verified"],
            "unavailable": totals["identity_unavailable"],
            "ambiguous": totals["identity_ambiguous"],
        },
        "shadow_input_coverage": {
            "available": totals["shadow_inputs_available"],
            "unavailable": totals["shadow_inputs_unavailable"],
            "invalid": totals["shadow_inputs_invalid"],
        },
        "decision_coverage": {
            "selected": totals["selected_by_decision"],
            "planned": totals["planned_by_active_path"],
            "control": totals["comparable_control"],
        },
        "latest_cycle_id": latest.get("cycle_id"),
        "latest_captured_at": latest_captured,
        "conflicts": conflicts,
        "freshness": {
            "status": freshness_status,
            "latest_event_created_at": latest_created,
            "latest_captured_at": latest_captured,
            "age_seconds": age_seconds,
        },
    }


def read_learning_penalty_shadow_events(store: Any, *, limit: int = 50000) -> list[dict[str, Any]]:
    return store.learning_penalty_cycle_shadow_events(limit=limit)
