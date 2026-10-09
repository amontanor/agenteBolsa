"""Prospective, pre-decision context snapshots.

The snapshot is deliberately kept inside existing JSON payloads.  Its hash and
validation rules make the nested block immutable by contract while preserving
backward-compatible readers for records that predate P-L30B.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "p-l30b.decision-context.v1"
AGENT_CONTRACT_SCHEMA = "p-l84b.agent-contract.v1"
DECISION_SOURCES = frozenset(
    {"llm", "fallback", "capacity_fill", "hold_override", "deterministic", "unknown"}
)
SIGNAL_LINK_STATUSES = frozenset({"verified", "broken", "unavailable"})
LLM_STATUSES = frozenset({"ok", "failed", "skipped", "unavailable"})
PROHIBITED_KEYS = frozenset(
    {
        "return_1d",
        "return_3d",
        "return_5d",
        "return_10d",
        "matured_horizons",
        "mfe",
        "mfe_10d",
        "mae",
        "mae_10d",
        "first_hit",
        "verdict",
        "fill",
        "filled_at",
        "filled_avg_price",
        "filled_qty",
        "realized_pnl",
        "unrealized_pnl",
        "execution_snapshot",
        "slippage",
        "exit_status",
    })


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {
        key: getattr(value, key, None)
        for key in (
            "symbol",
            "action",
            "source",
            "strategy_name",
            "decision_origin",
        "capacity_fill_reason_code",
        "decision_lineage",
        "tags",
        "soft_override_reasons",
        "direction",
        "probability",
        "evidence_refs",
        "latency_seconds",
        "confidence",
        "time_horizon",
        )
    }


def _parse_utc(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("decision_context_timestamp_invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


def _hash_payload(value: Mapping[str, Any], *, exclude: set[str] | None = None) -> str:
    excluded = exclude or set()
    payload = {key: item for key, item in value.items() if key not in excluded}
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()[:32]


def _snapshot_content_hash(snapshot: Mapping[str, Any]) -> str:
    body = dict(snapshot)
    contract = body.get("agent_contract")
    if isinstance(contract, Mapping):
        body["agent_contract"] = {**contract, "as_of": None}
    return _hash_payload(body, exclude={"captured_at", "content_hash"})


def _contains_prohibited(value: Any, path: str = "snapshot") -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in PROHIBITED_KEYS:
                return f"{path}.{key}"
            nested = _contains_prohibited(item, f"{path}.{key}")
            if nested:
                return nested
    elif isinstance(value, list):
        for index, item in enumerate(value):
            nested = _contains_prohibited(item, f"{path}[{index}]")
            if nested:
                return nested
    return None


def stable_reason_code(value: Any) -> str | None:
    text = str(value or "").lower()
    if not text:
        return None
    if "quota" in text:
        return "llm_quota"
    if "timeout" in text:
        return "llm_timeout"
    if "unavailable" in text or "capacity" in text:
        return "llm_unavailable"
    if "skip" in text or "omit" in text:
        return "llm_skipped"
    return "llm_failed"


def normalize_decision_source(raw: Any, decision_origin: Any = None) -> str:
    text = f"{str(raw or '').lower()} {str(decision_origin or '').lower()}"
    if "capacity_fill" in text:
        return "capacity_fill"
    if "fallback" in text:
        return "fallback"
    if "hold_override" in text:
        return "hold_override"
    if str(raw or "").lower() == "llm" or " llm" in text:
        return "llm"
    if "deterministic" in text:
        return "deterministic"
    return "unknown"


def _market_state_ref(
    market_state: Mapping[str, Any] | None,
    *,
    cycle_id: str,
    captured_at: datetime,
) -> dict[str, Any]:
    if not market_state:
        return {
            "status": "unavailable",
            "cycle_id": cycle_id,
            "run_id": None,
            "as_of": None,
            "prompt_version": None,
            "market_regime": None,
            "volatility_regime": None,
            "risk_posture": None,
            "data_quality_status": None,
            "content_hash": None,
        }
    state_cycle = str(market_state.get("cycle_id") or market_state.get("run_id") or "")
    if state_cycle != str(cycle_id):
        raise ValueError("market_state_cycle_mismatch")
    as_of = _parse_utc(market_state.get("as_of"))
    if as_of > captured_at:
        raise ValueError("market_state_after_capture")
    quality = market_state.get("data_quality") or {}
    ref = {
        "status": "available",
        "run_id": market_state.get("run_id"),
        "cycle_id": cycle_id,
        "as_of": as_of.isoformat(),
        "prompt_version": market_state.get("prompt_version") or "market_state.v2",
        "market_regime": market_state.get("market_regime"),
        "volatility_regime": market_state.get("volatility_regime"),
        "risk_posture": market_state.get("risk_posture"),
        "data_quality_status": quality.get("status"),
    }
    ref["content_hash"] = _hash_payload(ref)
    return ref


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


def _build_agent_contract(
    recommendation: Mapping[str, Any],
    *,
    cycle_id: str,
    agent_run_id: str | None,
    captured_at: datetime,
    decision_source: str,
    llm_response_status: str,
    llm_provider: str | None,
    llm_requested_model: str | None,
    llm_effective_model: str | None,
    llm_fallback_used: bool | None,
    fallback_reason: str | None,
) -> dict[str, Any]:
    """Build the prospective agent carrier without inventing unavailable fields."""

    raw_source = f"{recommendation.get('source') or ''} {recommendation.get('decision_origin') or ''}".lower()
    deterministic = "deterministic" in raw_source and not llm_provider
    effective_provider = llm_provider or ("deterministic" if deterministic else None)
    effective_model = llm_effective_model or ("deterministic-rules" if deterministic else None)
    requested_provider = llm_provider if not llm_fallback_used else None
    requested_model = llm_requested_model
    fields = {
        "direction": recommendation.get("direction"),
        "probability": recommendation.get("probability"),
        "evidence_refs": recommendation.get("evidence_refs"),
        "latency_seconds": recommendation.get("latency_seconds"),
    }
    return {
        "schema_version": AGENT_CONTRACT_SCHEMA,
        "agent_name": "trade_decision",
        "agent_run_id": agent_run_id,
        "cycle_id": cycle_id,
        "as_of": captured_at.isoformat(),
        "decision_source": decision_source,
        "horizon": recommendation.get("time_horizon"),
        "decision": recommendation.get("action"),
        "confidence": recommendation.get("confidence"),
        "fields": fields,
        "field_status": {
            key: "available" if value is not None else "unavailable"
            for key, value in fields.items()
        },
        "status": llm_response_status,
        "requested_identity": {"provider": requested_provider, "model": requested_model},
        "effective_identity": {"provider": effective_provider, "model": effective_model},
        "fallback": {
            "used": llm_fallback_used,
            "reason": fallback_reason,
        },
    }


def build_decision_context_snapshot(
    recommendation: Any,
    *,
    cycle_id: str,
    source_run_id: str | None,
    market_state: Mapping[str, Any] | None,
    agent_run_id: str | None = None,
    signal_id: str | None = None,
    signal_capture_id: str | None = None,
    signal_link_status: str = "unavailable",
    captured_at: datetime | None = None,
    llm_considered: bool | None = None,
    llm_selected: bool | None = None,
    llm_response_status: str | None = None,
    llm_model: str | None = None,
    llm_provider: str | None = None,
    llm_requested_model: str | None = None,
    llm_effective_model: str | None = None,
    llm_fallback_used: bool | None = None,
    fallback_reason: Any = None,
    identity_key: str | None = None,
) -> dict[str, Any]:
    captured = (captured_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if signal_link_status not in SIGNAL_LINK_STATUSES:
        raise ValueError("signal_link_status_invalid")
    rec = _as_dict(recommendation)
    raw = str(rec.get("source") or "").strip() or str(rec.get("decision_origin") or "").strip() or "unknown"
    origin = rec.get("decision_origin")
    normalized = normalize_decision_source(raw, origin)
    reason = stable_reason_code(fallback_reason)
    if normalized == "fallback" and not reason:
        raise ValueError("fallback_reason_required")
    if llm_response_status is None:
        if normalized == "llm":
            llm_response_status = "ok"
        elif normalized == "fallback":
            llm_response_status = "failed"
        elif normalized == "capacity_fill" and "por_fallo_llm" in raw:
            llm_response_status = "failed"
        else:
            llm_response_status = "unavailable"
    if llm_response_status not in LLM_STATUSES:
        raise ValueError("llm_response_status_invalid")
    identity = identity_key or "|".join(
        (
            str(cycle_id),
            str(signal_id or ""),
            str(signal_capture_id or ""),
            str(rec.get("symbol") or ""),
            str(rec.get("action") or ""),
            raw,
        )
    )
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_id": f"dctx_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}",
        "cycle_id": cycle_id,
        "source_run_id": source_run_id,
        "agent_run_id": agent_run_id,
        "signal_id": signal_id,
        "signal_capture_id": signal_capture_id,
        "signal_link_status": signal_link_status,
        "strategy_name": rec.get("strategy_name") or (rec.get("decision_lineage") or {}).get("strategy_name"),
        "strategy_version": (rec.get("decision_lineage") or {}).get("strategy_version"),
        "setup_name": None,
        "setup_quality": None,
        "market_state_ref": _market_state_ref(market_state, cycle_id=cycle_id, captured_at=captured),
        "decision_source": normalized,
        "decision_source_raw": raw,
        "decision_origin": origin,
        "llm_considered": llm_considered,
        "llm_selected": normalize_llm_selected(llm_selected),
        "llm_response_status": llm_response_status,
        "llm_provider": llm_provider,
        "llm_model": llm_effective_model or llm_model,
        "llm_requested_model": llm_requested_model or llm_model,
        "llm_effective_model": llm_effective_model or llm_model,
        "llm_fallback_used": llm_fallback_used,
        "fallback_reason": reason,
        "candidate_rank": (rec.get("decision_lineage") or {}).get("candidate_rank"),
        "score_rank": (rec.get("decision_lineage") or {}).get("score_rank"),
        "captured_at": captured.isoformat(),
        "pre_decision_only": True,
    }
    snapshot["agent_contract"] = _build_agent_contract(
        rec,
        cycle_id=cycle_id,
        agent_run_id=agent_run_id,
        captured_at=captured,
        decision_source=normalized,
        llm_response_status=llm_response_status,
        llm_provider=llm_provider,
        llm_requested_model=llm_requested_model or llm_model,
        llm_effective_model=llm_effective_model or llm_model,
        llm_fallback_used=llm_fallback_used,
        fallback_reason=reason,
    )
    snapshot["content_hash"] = _snapshot_content_hash(snapshot)
    validate_decision_context_snapshot(snapshot)
    return snapshot


def validate_decision_context_snapshot(snapshot: Mapping[str, Any]) -> None:
    if not isinstance(snapshot, Mapping):
        raise ValueError("decision_context_snapshot_not_object")
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("decision_context_schema_version_invalid")
    if not snapshot.get("snapshot_id") or not snapshot.get("cycle_id"):
        raise ValueError("decision_context_identity_missing")
    if snapshot.get("pre_decision_only") is not True:
        raise ValueError("decision_context_not_pre_decision")
    if snapshot.get("decision_source") not in DECISION_SOURCES:
        raise ValueError("decision_source_invalid")
    if snapshot.get("signal_link_status") not in SIGNAL_LINK_STATUSES:
        raise ValueError("signal_link_status_invalid")
    if snapshot.get("llm_response_status") not in LLM_STATUSES:
        raise ValueError("llm_response_status_invalid")
    if snapshot.get("decision_source") == "fallback" and not snapshot.get("fallback_reason"):
        raise ValueError("fallback_reason_required")
    contract = snapshot.get("agent_contract") or {}
    if not isinstance(contract, Mapping):
        raise ValueError("agent_contract_invalid")
    if contract:
        if contract.get("schema_version") != AGENT_CONTRACT_SCHEMA:
            raise ValueError("agent_contract_schema_version_invalid")
        if contract.get("cycle_id") != snapshot.get("cycle_id"):
            raise ValueError("agent_contract_cycle_mismatch")
        if _parse_utc(contract.get("as_of")) != _parse_utc(snapshot.get("captured_at")):
            raise ValueError("agent_contract_as_of_mismatch")
        if contract.get("decision_source") != snapshot.get("decision_source"):
            raise ValueError("agent_contract_source_mismatch")
    _parse_utc(snapshot.get("captured_at"))
    market_ref = snapshot.get("market_state_ref") or {}
    if market_ref.get("status") == "available":
        if market_ref.get("cycle_id") != snapshot.get("cycle_id"):
            raise ValueError("market_state_cycle_mismatch")
        if _parse_utc(market_ref.get("as_of")) > _parse_utc(snapshot.get("captured_at")):
            raise ValueError("market_state_after_capture")
    prohibited = _contains_prohibited(snapshot)
    if prohibited:
        raise ValueError(f"decision_context_post_decision_field:{prohibited}")
    expected = _snapshot_content_hash(snapshot)
    if snapshot.get("content_hash") != expected:
        raise ValueError("decision_context_content_hash_invalid")


def copy_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Return a detached validated copy for embedding in an existing JSON payload."""

    validate_decision_context_snapshot(snapshot)
    return copy.deepcopy(dict(snapshot))


def _snapshot_from_record(record: Mapping[str, Any]) -> Mapping[str, Any] | None:
    payload = record.get("payload") or {}
    snapshot = payload.get("decision_context_snapshot")
    if snapshot:
        return snapshot
    recommendation = payload.get("recommendation") or {}
    return recommendation.get("decision_context_snapshot") or (record.get("features") or {}).get(
        "decision_context_snapshot"
    )


def build_decision_context_quality(
    store: Any,
    *,
    now: datetime | None = None,
    days: int = 1,
) -> dict[str, Any]:
    """Read-only coverage diagnostics for newly captured snapshots."""

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = current.timestamp() - max(1, int(days)) * 86400

    def recent(record: Mapping[str, Any]) -> bool:
        try:
            return _parse_utc(record.get("created_at")).timestamp() >= cutoff
        except ValueError:
            return False

    total = 0
    captured = 0
    verified = 0
    broken = 0
    unavailable = 0
    plans_with_snapshot = 0
    observations_with_snapshot = 0
    outcomes_with_snapshot = 0
    snapshot_count = 0
    agent_run_linked = 0
    same_cycle = 0
    contamination = 0
    fallback_count = 0
    fallback_reason_count = 0
    decision_source_non_unknown = 0
    source_counts: dict[str, int] = {}
    first_hash_by_id: dict[str, str] = {}
    conflicted_ids: set[str] = set()

    def consume(kind: str, item: Mapping[str, Any]) -> None:
        nonlocal agent_run_linked
        nonlocal broken, captured, contamination, fallback_count, fallback_reason_count
        nonlocal decision_source_non_unknown, observations_with_snapshot, outcomes_with_snapshot, plans_with_snapshot
        nonlocal same_cycle, snapshot_count, total, unavailable, verified
        if not recent(item):
            return
        snapshot = _snapshot_from_record(item)
        if kind == "recommendation":
            total += 1
            if snapshot:
                captured += 1
                source = str(snapshot.get("decision_source") or "unknown")
                source_counts[source] = source_counts.get(source, 0) + 1
                decision_source_non_unknown += snapshot.get("decision_source") != "unknown"
                signal_link_status = snapshot.get("signal_link_status")
                verified += signal_link_status == "verified"
                broken += signal_link_status == "broken"
                unavailable += signal_link_status == "unavailable"
                if snapshot.get("decision_source") == "fallback":
                    fallback_count += 1
                    fallback_reason_count += bool(snapshot.get("fallback_reason"))
        elif kind == "plan":
            plans_with_snapshot += bool(snapshot)
        elif kind == "observation":
            observations_with_snapshot += bool(snapshot)
        elif kind == "outcome":
            outcomes_with_snapshot += bool(snapshot)
        else:
            raise ValueError(f"decision_context_quality_record_kind_invalid:{kind}")
        if not snapshot:
            return
        snapshot_count += 1
        agent_run_linked += bool(snapshot.get("agent_run_id"))
        market_state_ref = snapshot.get("market_state_ref") or {}
        same_cycle += market_state_ref.get("status") == "unavailable" or market_state_ref.get("cycle_id") == snapshot.get("cycle_id")
        snapshot_id = str(snapshot.get("snapshot_id"))
        content_hash = str(snapshot.get("content_hash"))
        previous_hash = first_hash_by_id.setdefault(snapshot_id, content_hash)
        if previous_hash != content_hash:
            conflicted_ids.add(snapshot_id)
        contamination += _contains_prohibited(snapshot) is not None

    stream_factory = getattr(store, "decision_context_quality_record_stream", None)
    if callable(stream_factory):
        with stream_factory(batch_size=512) as records:
            for kind, item in records:
                consume(kind, item)
    else:
        for item in store.trade_recommendations(limit=50000):
            consume("recommendation", item)
        for item in store.order_plans(limit=50000):
            consume("plan", item)
        for item in store.learning_observations(limit=200000):
            consume("observation", item)
        for item in store.signal_outcomes(limit=200000, include_lab_book=True, include_learning_experiment=True):
            consume("outcome", item)

    conflict_count = len(conflicted_ids)
    return {
        "schema_version": SCHEMA_VERSION,
        "window_days": max(1, int(days)),
        "status": "collecting" if not total or not captured else "evaluable",
        "recommendations_total_new": total,
        "recommendations_with_snapshot": captured,
        "recommendation_snapshot_coverage": captured / total if total else None,
        "verified_signal_links": verified,
        "broken_signal_links": broken,
        "unavailable_signal_links": unavailable,
        "signal_snapshot_coverage_verified_links": verified / total if total else None,
        "plans_with_snapshot": plans_with_snapshot,
        "observations_with_snapshot": observations_with_snapshot,
        "outcomes_with_snapshot": outcomes_with_snapshot,
        "agent_run_link_coverage": agent_run_linked / snapshot_count
        if snapshot_count
        else None,
        "market_state_same_cycle_coverage": same_cycle / snapshot_count if snapshot_count else None,
        "decision_source_coverage": decision_source_non_unknown / total
        if total
        else None,
        "fallback_reason_coverage": fallback_reason_count / fallback_count
        if fallback_count
        else None,
        "post_decision_contamination_count": contamination,
        "snapshot_conflict_count": conflict_count,
        "sources": source_counts,
        "legacy_without_snapshot": total - captured,
    }
