"""Shadow ledger for exact pre-decision selection evidence.

The producer receives the in-memory ranked universe and the objects already
produced by the active decision path.  It never ranks, selects, runs a gate,
calls the LLM, queries a broker, or reconstructs identities by symbol/date.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from ..storage import Store


SCHEMA_VERSION = "p-l53b.canonical-selection-ledger.v1"
EVENT_TYPE = "canonical_selection_ledger"
EVENT_ID_PREFIX = "canonical_selection_ledger:"
VALID_ACTIONS = {"buy", "exit"}
_DECISION_SOURCES = {
    "llm": "llm",
    "capacity_fill": "deterministic_capacity_fill",
    "deterministic_capacity_fill": "deterministic_capacity_fill",
    "fallback": "fallback",
    "deterministic_fallback": "fallback",
    "hold_override": "hold_override",
    "deterministic": "deterministic",
}
_FORBIDDEN_FIELDS = {
    "return_1d",
    "return_3d",
    "return_5d",
    "return_10d",
    "matured_horizons",
    "fill",
    "fill_price",
    "filled_at",
    "filled_qty",
    "realized_pnl",
    "unrealized_pnl",
    "mfe",
    "mae",
    "first_hit",
    "slippage",
    "exit_status",
}


def _safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def stable_content_hash(payload: Mapping[str, Any]) -> str:
    body = copy.deepcopy(dict(payload))
    body.pop("captured_at", None)
    body.pop("content_hash", None)
    encoded = json.dumps(
        _safe(body),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def normalize_llm_selected(value: Any) -> bool | None:
    """Normalize llm_selected to bool or None only. Fail-open.

    Only literal Python bool values (True/False) are accepted as structured
    authority.  Any other type -- int (0, 1), str ('true', 'false'), list,
    dict, float -- is degraded silently to None (unavailable/legacy).

    This function must never raise; it is a fail-open telemetry guard.
    """
    if value is None:
        return None
    if type(value) is bool:
        return value
    return None


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    return {}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _action(value: Any) -> str | None:
    row = _mapping(value)
    lineage = _mapping(row.get("decision_lineage"))
    raw = _text(row.get("action") or lineage.get("action"))
    if raw is None:
        direction = str(row.get("direction") or "").lower()
        if direction in {"long", "buy", "entry"}:
            raw = "buy"
        elif direction in {"short", "sell", "exit", "reduce"}:
            raw = "exit"
    raw = raw.lower() if raw else None
    return "exit" if raw == "sell" else raw if raw in VALID_ACTIONS else None


def _identity(value: Any, cycle_id: str) -> tuple[str, str, str] | None:
    row = _mapping(value)
    lineage = _mapping(row.get("decision_lineage"))
    cycle = _text(row.get("cycle_id") or lineage.get("cycle_id")) or cycle_id
    action = _action(row)
    capture_id = _text(row.get("signal_capture_id") or lineage.get("signal_capture_id"))
    signal_id = _text(row.get("signal_id") or lineage.get("signal_id"))
    # ``signal_capture_id`` is the primary capture identity; ``signal_id`` is
    # only its explicit canonical fallback.  Never prefer a later/derived
    # signal ID over the exact capture ID.
    canonical_id = capture_id or signal_id
    if not cycle or not action or not canonical_id:
        return None
    return cycle, action, canonical_id


def _identity_text(key: tuple[str, str, str] | None) -> str | None:
    if key is None:
        return None
    return "|".join(key)


def _parse_timestamp(value: Any, captured_at: datetime, warnings: list[str], field: str) -> str | None:
    raw = _text(value)
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        warnings.append(f"invalid_timestamp:{field}")
        return None
    if parsed.tzinfo is None:
        warnings.append(f"naive_timestamp:{field}")
        return None
    parsed = parsed.astimezone(timezone.utc)
    if parsed > captured_at:
        warnings.append(f"future_timestamp:{field}")
        return None
    return parsed.isoformat()


def _normalize_source(value: Any, decision_origin: Any = None) -> str | None:
    if value is None and decision_origin is None:
        return None
    text = f"{str(value or '').lower()} {str(decision_origin or '').lower()}"
    for source, normalized in _DECISION_SOURCES.items():
        if source in text:
            return normalized
    return "other"


def _states(row: Mapping[str, Any]) -> list[str]:
    states: list[str] = []
    identity_status = row.get("identity_status")
    states.append("identified" if identity_status == "verified" else str(identity_status or "unavailable"))
    eligible = row.get("eligible_at_selection")
    if eligible is True:
        states.append("eligible")
    elif eligible is False:
        states.append("ineligible")
    else:
        states.append("shadow_inputs_unavailable")
    selected = row.get("selected_for_llm")
    if selected is True:
        states.append("selected")
    elif selected is False:
        states.append("not_selected")
    else:
        states.append("unavailable")
    for field, positive, negative in (
        ("recommended", "recommended", "not_recommended"),
        ("planned", "planned", "not_planned"),
        ("ordered", "ordered", "not_ordered"),
        ("rejected", "rejected", "not_rejected"),
    ):
        value = row.get(field)
        if value is True:
            states.append(positive)
        elif value is False:
            states.append(negative)
        else:
            states.append("unavailable")
    if row.get("gated_out") is True:
        states.append("gated_out")
    if row.get("not_generated") is True:
        states.append("not_generated")
    return list(dict.fromkeys(states))


def _candidate_projection(
    candidate: Mapping[str, Any],
    *,
    cycle_id: str,
    captured_at: datetime,
    selected_ids: set[tuple[str, str, str]] | None,
) -> dict[str, Any]:
    raw = dict(candidate)
    forbidden = sorted(_FORBIDDEN_FIELDS.intersection(raw))
    if forbidden:
        raise ValueError(f"predecision_forbidden_field:{forbidden[0]}")
    key = _identity(raw, cycle_id)
    lineage = _mapping(raw.get("decision_lineage"))
    warnings: list[str] = []
    signal_at = _parse_timestamp(raw.get("signal_at"), captured_at, warnings, "signal_at")
    decision_at = _parse_timestamp(raw.get("decision_at"), captured_at, warnings, "decision_at")
    if signal_at and decision_at and decision_at < signal_at:
        warnings.append("inverted_timestamp:decision_at")
    selected = (
        raw.get("selected_for_llm")
        if selected_ids is None
        else key in selected_ids if key is not None else None
    )
    row = {
        "schema_version": SCHEMA_VERSION,
        "source_stage": "predecision",
        "cycle_id": key[0] if key else _text(raw.get("cycle_id")) or cycle_id,
        "session_date": raw.get("session_date") or raw.get("signal_date") or raw.get("last_date"),
        "signal_capture_id": _text(raw.get("signal_capture_id") or lineage.get("signal_capture_id")),
        "signal_id": _text(raw.get("signal_id") or lineage.get("signal_id")),
        "candidate_id": _text(raw.get("candidate_id") or lineage.get("candidate_id")),
        "recommendation_id": None,
        "plan_id": None,
        "broker_order_id": None,
        "source_run_id": _text(raw.get("source_run_id") or raw.get("signal_source_run_id")),
        "symbol": _text(raw.get("symbol")),
        "action": _action(raw),
        "strategy": raw.get("strategy") or raw.get("strategy_name") or raw.get("signal_strategy_name"),
        "setup": raw.get("setup") or raw.get("setup_name"),
        "score_universe": raw.get("score_universe") or raw.get("score_domain"),
        "score": raw.get("score"),
        "selection_score": (
            raw.get("selection_score")
            if raw.get("selection_score") is not None
            else raw.get("rank_priority_score")
        ),
        "learning_prior": copy.deepcopy(raw.get("learning_prior")),
        "score_rank": raw.get("score_rank"),
        "selection_rank": raw.get("selection_rank"),
        "rank_direction": {
            "score": "descending_raw_higher_better",
            "selection": "descending_selection_score_higher_better",
        },
        "data_quality": copy.deepcopy(raw.get("data_quality")),
        "freshness": copy.deepcopy(raw.get("freshness")),
        "price_basis": raw.get("price_basis"),
        "signal_at": signal_at,
        "decision_at": decision_at,
        "timestamp_status": "verified" if not warnings else "unavailable",
        "timestamp_warnings": sorted(set(warnings)),
        "eligible_at_selection": raw.get("eligible_at_selection", raw.get("eligible")),
        "gate_frontier": raw.get("gate_frontier") or raw.get("selection_frontier"),
        "selected_for_llm": selected,
        "llm_considered": None,
        "llm_selected": None,
        "decision_source": None,
        "recommended": None,
        "planned": None,
        "ordered": None,
        "rejected": None,
        "gated_out": None,
        "not_generated": None,
        "exclusion_reason": None,
        "identity_status": "verified" if key else "identity_unavailable",
        "identity_key": _identity_text(key),
        "captured_at": captured_at.isoformat(),
    }
    if raw.get("identity_status") == "ambiguous" or raw.get("identity_ambiguous") is True:
        row["identity_status"] = "identity_ambiguous"
    row["states"] = _states(row)
    return row


def _phase_a_rows(
    phase_a: Mapping[str, Any] | None,
    *,
    cycle_id: str,
    captured_at: datetime,
    warnings: list[str],
) -> tuple[list[dict[str, Any]] | None, int, set[tuple[str, str, str]] | None]:
    if not isinstance(phase_a, Mapping):
        warnings.append("phase_a_unavailable")
        return None, 0, None
    if "all_candidates" in phase_a:
        raw = phase_a.get("all_candidates")
    elif "ranked_candidates" in phase_a:
        raw = phase_a.get("ranked_candidates")
    else:
        warnings.append("phase_a_universe_unavailable")
        return None, 0, None
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        warnings.append("phase_a_universe_invalid")
        return None, 0, None
    selected_raw = phase_a.get("selected_candidates")
    selected_ids: set[tuple[str, str, str]] | None = None
    if isinstance(selected_raw, Sequence) and not isinstance(selected_raw, (str, bytes)):
        selected_ids = set()
        for item in selected_raw:
            key = _identity(item, cycle_id)
            if key is None:
                warnings.append("selected_identity_unavailable")
            else:
                selected_ids.add(key)
    rows: list[dict[str, Any]] = []
    conflicts = 0
    seen: dict[tuple[str, str, str], str] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            warnings.append("generic_reporter_row_ignored")
            continue
        row = _candidate_projection(item, cycle_id=cycle_id, captured_at=captured_at, selected_ids=selected_ids)
        key = _identity(row, cycle_id)
        if key is not None:
            previous_hash = seen.get(key)
            current_hash = stable_content_hash(row)
            if previous_hash is not None:
                if previous_hash != current_hash:
                    conflicts += 1
                    row["identity_status"] = "conflict"
                    warnings.append("candidate_identity_conflict")
                    continue
                warnings.append("candidate_idempotent_duplicate")
                continue
            seen[key] = current_hash
        rows.append(row)
    return rows, conflicts, selected_ids


def _decision_projection(value: Any, cycle_id: str) -> tuple[tuple[str, str, str] | None, dict[str, Any]]:
    row = _mapping(value)
    key = _identity(row, cycle_id)
    lineage = _mapping(row.get("decision_lineage"))
    return key, {
        "row": row,
        "lineage": lineage,
        "decision_source": _normalize_source(row.get("source"), row.get("decision_origin")),
    }


def _attach_phase_b(
    rows: list[dict[str, Any]],
    *,
    cycle_id: str,
    recommendations: Sequence[Any] | None,
    plans: Sequence[Any] | None,
    plan_records: Sequence[Mapping[str, Any]] | None,
    rejected_order_plans: Sequence[Mapping[str, Any]] | None,
    ordered_records: Sequence[Mapping[str, Any]] | None,
    failed_records: Sequence[Mapping[str, Any]] | None,
    gate_snapshots: Mapping[str, Any] | Sequence[Any] | None,
    warnings: list[str],
) -> None:
    by_key = {_identity(row, cycle_id): row for row in rows if _identity(row, cycle_id) is not None}
    if recommendations is not None:
        for row in rows:
            if row["identity_status"] == "verified":
                row["recommended"] = False
                row["rejected"] = False
        for recommendation in recommendations:
            key, info = _decision_projection(recommendation, cycle_id)
            if key is None:
                warnings.append("recommendation_identity_unavailable")
                continue
            target = by_key.get(key)
            if target is None:
                warnings.append("recommendation_without_phase_a_candidate")
                continue
            raw = info["row"]
            snapshot = _mapping(raw.get("decision_context_snapshot"))
            source = info["decision_source"]
            # P-L59C: llm_selected is now a structured authority set by the producer
            # (True=LLM selected, False=not selected, None=legacy/unavailable).
            # Consumed directly from decision_context_snapshot; never inferred from source.
            # P-L59C-R1: normalize_llm_selected enforces bool|None; non-bool degrades to None.
            snapshot_llm_selected = normalize_llm_selected(snapshot.get("llm_selected"))
            target.update(
                {
                    "recommended": True,
                    "recommendation_id": _text(raw.get("recommendation_id")),
                    "llm_considered": snapshot.get("llm_considered"),
                    "llm_selected": snapshot_llm_selected,
                    "decision_source": source,
                    "gate_frontier": target.get("gate_frontier") or snapshot.get("gate_frontier"),
                    "source_stage": "decision",
                }
            )

    effective_plans = list(plan_records) if plan_records is not None else []
    if plan_records is None and plans is not None:
        effective_plans = [{"payload": _mapping(plan)} for plan in plans]
    if plans is not None or plan_records is not None:
        for row in rows:
            if row["identity_status"] == "verified":
                row["planned"] = False
        for plan in effective_plans:
            payload = _mapping(plan.get("payload")) if isinstance(plan, Mapping) else _mapping(plan)
            key = _identity(plan, cycle_id) or _identity(payload, cycle_id)
            if key is None:
                warnings.append("plan_identity_unavailable")
                continue
            target = by_key.get(key)
            if target is not None:
                target["planned"] = True
                target["plan_id"] = _text(plan.get("plan_id")) if isinstance(plan, Mapping) else None
                target["source_stage"] = "plan"

    if rejected_order_plans is not None:
        for rejection in rejected_order_plans:
            key = _identity(rejection, cycle_id)
            if key is None:
                warnings.append("rejection_identity_unavailable")
                continue
            target = by_key.get(key)
            if target is None:
                warnings.append("rejection_without_phase_a_candidate")
                continue
            reason = _text(rejection.get("reason") or rejection.get("reason_code"))
            target.update(
                {
                    "rejected": True,
                    "gated_out": True,
                    "planned": False,
                    "exclusion_reason": reason,
                    "source_stage": "rejection",
                }
            )

    if ordered_records is not None:
        for row in rows:
            if row["identity_status"] == "verified":
                row["ordered"] = False
        for record in ordered_records:
            key = _identity(record, cycle_id)
            if key is None:
                warnings.append("ordered_identity_unavailable")
                continue
            target = by_key.get(key)
            if target is not None:
                target.update(
                    {
                        "ordered": True,
                        "broker_order_id": _text(record.get("broker_order_id")),
                        "source_stage": "ordered",
                    }
                )
    if failed_records is not None:
        for record in failed_records:
            key = _identity(record, cycle_id)
            if key is None:
                warnings.append("failed_order_identity_unavailable")
                continue
            target = by_key.get(key)
            if target is not None:
                target["ordered"] = False
                target["exclusion_reason"] = _text(record.get("reason")) or "order_submission_failed"

    if gate_snapshots is not None:
        snapshots = gate_snapshots.values() if isinstance(gate_snapshots, Mapping) else gate_snapshots
        for snapshot in snapshots:
            if not isinstance(snapshot, Mapping):
                continue
            key = _identity(snapshot, cycle_id)
            if key is None:
                continue
            target = by_key.get(key)
            if target is not None and snapshot.get("gate_frontier"):
                target["gate_frontier"] = snapshot["gate_frontier"]

    for row in rows:
        row["states"] = _states(row)


def _denominators(
    rows: list[dict[str, Any]] | None,
    *,
    raw_count: int | None,
    conflicts: int,
    truncated_count: int | None,
) -> dict[str, Any]:
    if rows is None or raw_count is None:
        nulls = {
            key: None
            for key in (
                "raw_count",
                "canonical_count",
                "eligible_count",
                "selected_count",
                "recommended_count",
                "planned_count",
                "ordered_count",
                "identity_unavailable",
                "identity_ambiguous",
                "shadow_inputs_unavailable",
                "conflict_count",
                "truncated_count",
            )
        }
        return nulls
    verified = [row for row in rows if row.get("identity_status") == "verified"]
    return {
        "raw_count": raw_count,
        "canonical_count": len(verified),
        "eligible_count": sum(row.get("eligible_at_selection") is True for row in rows),
        "selected_count": sum(row.get("selected_for_llm") is True for row in rows),
        "recommended_count": sum(row.get("recommended") is True for row in rows),
        "planned_count": sum(row.get("planned") is True for row in rows),
        "ordered_count": sum(row.get("ordered") is True for row in rows),
        "identity_unavailable": sum(row.get("identity_status") == "identity_unavailable" for row in rows),
        "identity_ambiguous": sum(row.get("identity_status") == "identity_ambiguous" for row in rows),
        "shadow_inputs_unavailable": sum(row.get("eligible_at_selection") is None for row in rows),
        "conflict_count": conflicts,
        "truncated_count": truncated_count or 0,
    }


def _coverage(denominators: Mapping[str, Any]) -> dict[str, float | None]:
    raw = denominators.get("raw_count")
    canonical = denominators.get("canonical_count")
    if not isinstance(raw, int) or raw <= 0:
        return {"identity": None, "eligibility": None, "selection": None, "decision": None}
    return {
        "identity": round(canonical / raw, 6) if isinstance(canonical, int) else None,
        "eligibility": round(denominators["eligible_count"] / raw, 6),
        "selection": round(denominators["selected_count"] / raw, 6),
        "decision": round(denominators["recommended_count"] / raw, 6),
    }


def build_canonical_selection_ledger(
    cycle_id: str,
    phase_a: Mapping[str, Any] | None,
    *,
    recommendations: Sequence[Any] | None = None,
    plans: Sequence[Any] | None = None,
    plan_records: Sequence[Mapping[str, Any]] | None = None,
    rejected_order_plans: Sequence[Mapping[str, Any]] | None = None,
    ordered_records: Sequence[Mapping[str, Any]] | None = None,
    failed_records: Sequence[Mapping[str, Any]] | None = None,
    gate_snapshots: Mapping[str, Any] | Sequence[Any] | None = None,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    """Build one immutable, pre-decision-only selection ledger event."""

    if not _text(cycle_id):
        raise ValueError("cycle_id_required")
    capture = captured_at or datetime.now(timezone.utc)
    if capture.tzinfo is None:
        capture = capture.replace(tzinfo=timezone.utc)
    capture = capture.astimezone(timezone.utc)
    warnings: list[str] = []
    rows, conflicts, _selected_ids = _phase_a_rows(
        phase_a,
        cycle_id=cycle_id,
        captured_at=capture,
        warnings=warnings,
    )
    raw_count = None if rows is None else len(rows)
    if isinstance(phase_a, Mapping) and rows is not None:
        raw_value = phase_a.get("all_candidates", phase_a.get("ranked_candidates"))
        raw_count = len(raw_value) if isinstance(raw_value, Sequence) and not isinstance(raw_value, (str, bytes)) else len(rows)
    truncated = phase_a.get("truncated_count") if isinstance(phase_a, Mapping) else None
    if truncated is not None:
        try:
            truncated = max(0, int(truncated))
        except (TypeError, ValueError):
            truncated = None
    _attach_phase_b(
        rows or [],
        cycle_id=cycle_id,
        recommendations=recommendations,
        plans=plans,
        plan_records=plan_records,
        rejected_order_plans=rejected_order_plans,
        ordered_records=ordered_records,
        failed_records=failed_records,
        gate_snapshots=gate_snapshots,
        warnings=warnings,
    )
    denominators = _denominators(rows, raw_count=raw_count, conflicts=conflicts, truncated_count=truncated)
    if rows is None:
        status = "collecting"
    elif truncated:
        status = "partial"
        warnings.append("universe_truncated")
    elif conflicts or any(row.get("identity_status") != "verified" for row in rows) or warnings:
        status = "partial"
    else:
        status = "verified"
    session_dates = sorted({str(row.get("session_date")) for row in rows or [] if row.get("session_date")})
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "revision": 1,
        "event_id": f"{EVENT_ID_PREFIX}{cycle_id}",
        "event_type": EVENT_TYPE,
        "cycle_id": cycle_id,
        "session_date": session_dates[0] if len(session_dates) == 1 else None,
        "status": status,
        "captured_at": capture.isoformat(),
        "candidate_rows": sorted(rows or [], key=lambda row: str(row.get("identity_key") or "")),
        "denominators": denominators,
        "coverage": _coverage(denominators),
        "truncated_count": truncated,
        "warnings": sorted(set(warnings)),
        "conflicts": conflicts,
        "outcomes": None,
    }
    payload["content_hash"] = stable_content_hash(payload)
    return _safe(payload)


def persist_canonical_selection_ledger(store: Store, payload: Mapping[str, Any]) -> dict[str, Any]:
    event_id = _text(payload.get("event_id"))
    if not event_id:
        raise ValueError("selection_ledger_event_id_required")
    return store.record_canonical_selection_ledger(dict(payload), event_id=event_id)


def _empty_read(cycle_id: str | None, *, warning: str) -> dict[str, Any]:
    return {
        "status": "collecting",
        "schema_version": SCHEMA_VERSION,
        "event_id": f"{EVENT_ID_PREFIX}{cycle_id}" if cycle_id else None,
        "cycle_id": cycle_id,
        "denominators": {key: None for key in (
            "raw_count",
            "canonical_count",
            "eligible_count",
            "selected_count",
            "recommended_count",
            "planned_count",
            "ordered_count",
            "identity_unavailable",
            "identity_ambiguous",
            "shadow_inputs_unavailable",
            "conflict_count",
            "truncated_count",
        )},
        "coverage": None,
        "candidate_rows": [],
        "warnings": [warning],
        "conflicts": [],
    }


def read_canonical_selection_ledger(store: Store, cycle_id: str | None = None) -> dict[str, Any]:
    event = store.canonical_selection_ledger_event(cycle_id) if cycle_id else store.latest_canonical_selection_ledger_event()
    if event is None:
        return _empty_read(cycle_id, warning="no_canonical_selection_ledger")
    payload = dict(event.get("payload") or {})
    expected_id = f"{EVENT_ID_PREFIX}{payload.get('cycle_id')}"
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("event_id") != expected_id:
        return _empty_read(cycle_id, warning="invalid_canonical_selection_ledger") | {"status": "unavailable"}
    if stable_content_hash(payload) != payload.get("content_hash"):
        return _empty_read(cycle_id, warning="content_hash_mismatch") | {"status": "unavailable"}
    return payload


def canonical_selection_ledger_digest(store: Store, cycle_id: str | None = None) -> dict[str, Any]:
    payload = read_canonical_selection_ledger(store, cycle_id)
    conflicts = store.canonical_selection_ledger_conflicts(cycle_id=payload.get("cycle_id"))
    payload["conflict_events"] = len(conflicts)
    if conflicts and payload.get("status") == "verified":
        payload["status"] = "partial"
    return payload


def _matching_timestamp_delta_seconds(left: Any, right: Any) -> float | None:
    try:
        left_dt = datetime.fromisoformat(str(left).replace("Z", "+00:00"))
        right_dt = datetime.fromisoformat(str(right).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if left_dt.tzinfo is None or right_dt.tzinfo is None:
        return None
    return abs((left_dt.astimezone(timezone.utc) - right_dt.astimezone(timezone.utc)).total_seconds())


def match_same_cycle_controls(
    treatment: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    *,
    max_signal_delta_seconds: int = 60,
) -> dict[str, Any]:
    """Match only pre-decision controls from the same eligible frontier.

    This is a read-only projection helper.  It does not add outcomes to the
    ledger and it never treats a recommended-but-blocked row as a control.
    """

    treatment_row = _mapping(treatment)
    treatment_key = _identity(treatment_row, _text(treatment_row.get("cycle_id")) or "")
    if treatment_key is None or treatment_key[1] != "buy":
        return {
            "status": "unavailable",
            "reason": "treatment_identity_or_action_unavailable",
            "controls": [],
            "excluded": [],
        }
    if treatment_row.get("eligible_at_selection") is not True:
        return {
            "status": "unavailable",
            "reason": "treatment_not_eligible",
            "controls": [],
            "excluded": [],
        }
    controls: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for candidate in candidates:
        row = _mapping(candidate)
        key = _identity(row, treatment_key[0])
        reason: str | None = None
        if key is None:
            reason = "identity_unavailable"
        elif key == treatment_key:
            reason = "same_treatment"
        elif key[1] != "buy":
            reason = "action_mismatch"
        elif key[0] != treatment_key[0]:
            reason = "cycle_mismatch"
        elif row.get("session_date") != treatment_row.get("session_date"):
            reason = "session_mismatch"
        elif row.get("strategy") != treatment_row.get("strategy") or row.get("setup") != treatment_row.get("setup"):
            reason = "strategy_setup_mismatch"
        elif row.get("eligible_at_selection") is not True:
            reason = "ineligible_at_frontier"
        elif row.get("gate_frontier") != treatment_row.get("gate_frontier"):
            reason = "gate_frontier_mismatch_or_unavailable"
        elif row.get("data_quality") != treatment_row.get("data_quality"):
            reason = "data_quality_mismatch_or_unavailable"
        elif row.get("freshness") != treatment_row.get("freshness"):
            reason = "freshness_mismatch_or_unavailable"
        elif row.get("timestamp_status") != "verified":
            reason = "predecision_timestamp_unavailable"
        else:
            delta = _matching_timestamp_delta_seconds(row.get("signal_at"), treatment_row.get("signal_at"))
            if delta is None:
                reason = "predecision_timestamp_unavailable"
            elif delta > max_signal_delta_seconds:
                reason = "predecision_timestamp_incompatible"
        if reason is None and row.get("recommended") is not False:
            reason = "postdecision_recommended_not_control"
        if reason is None and row.get("selected_for_llm") is not False:
            reason = "selection_state_unavailable_or_selected"
        if reason is None:
            controls.append(copy.deepcopy(row))
        else:
            excluded.append({"identity_key": _identity_text(key), "reason": reason})
    return {
        "status": "verified" if controls else "unavailable",
        "reason": None if controls else "no_eligible_alternatives",
        "controls": controls,
        "excluded": excluded,
    }


def match_mature_forward_outcome(
    row: Mapping[str, Any],
    outcome: Mapping[str, Any],
    *,
    completed_sessions: Sequence[str],
) -> dict[str, Any]:
    """Join a future outcome after capture using canonical identity only."""

    ledger_row = _mapping(row)
    outcome_row = _mapping(outcome)
    row_key = _identity(ledger_row, _text(ledger_row.get("cycle_id")) or "")
    outcome_key = _identity(outcome_row, _text(outcome_row.get("cycle_id")) or "")
    if row_key is None or outcome_key != row_key:
        return {"status": "unavailable", "reason": "decision_identity_mismatch"}
    horizon = _text(outcome_row.get("horizon"))
    required_sessions = {"3d": 3, "5d": 5, "10d": 10}.get(horizon or "")
    if required_sessions is None:
        return {"status": "unavailable", "reason": "horizon_invalid"}
    if not ledger_row.get("price_basis") or outcome_row.get("price_basis") != ledger_row.get("price_basis"):
        return {"status": "unavailable", "reason": "price_basis_unavailable_or_mismatch"}
    if outcome_row.get("matured") is not True:
        return {"status": "unavailable", "reason": "outcome_immature"}
    try:
        signal_index = list(completed_sessions).index(str(ledger_row["session_date"]))
        maturity_index = list(completed_sessions).index(str(outcome_row["maturity_session_date"]))
    except (KeyError, ValueError):
        return {"status": "unavailable", "reason": "session_not_completed"}
    if maturity_index - signal_index < required_sessions:
        return {"status": "unavailable", "reason": "maturity_sessions_insufficient"}
    return {
        "status": "matured",
        "horizon": horizon,
        "forward_return": outcome_row.get("forward_return"),
        "net_profit": None,
        "warning": "forward_return_is_not_net_profit",
    }
