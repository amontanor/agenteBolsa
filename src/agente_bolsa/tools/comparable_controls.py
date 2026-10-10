"""Prospective same-cycle comparable-control capture.

This module only builds immutable JSON blocks from decisions already made by the
cycle.  It never reruns ranking or gates and never reads a latest report to
reconstruct a cycle.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "p-l31b.comparable-control.v2"
LEGACY_SCHEMA_VERSION = "p-l31b.comparable-control.v1"
FORWARD_HORIZON = "10d"
CONTROL_LIMIT = 3
CONTROL_STATUSES = frozenset({"verified", "partially_comparable", "unavailable"})
GATE_STATUSES = frozenset({"passed", "blocked", "not_evaluated", "unavailable"})
GATE_ELIGIBILITY = frozenset({"verified", "partial", "unavailable"})
PRIMARY_REASONS = frozenset({"lower_rank", "capacity_limit"})
NON_EXECUTION_REASONS = frozenset(
    {
        "lower_rank",
        "capacity_limit",
        "daily_order_limit",
        "low_sample_quota",
        "gate_blocked",
        "risk_blocked",
        "strategy_paused",
        "invalid_geometry",
        "duplicate_symbol",
        "already_held",
        "unknown",
    }
)
_EXPLICIT_REASON_CODES = {
    "max_orders_per_cycle_reached": "capacity_limit",
    "max_daily_buy_orders_reached": "daily_order_limit",
    "low_sample_daily_quota_exhausted": "low_sample_quota",
    "strategy_paused_shadow_active": "strategy_paused",
    "symbol_already_has_buy_plan_in_cycle": "duplicate_symbol",
    "position_adds_disabled": "already_held",
    "symbol_has_open_order": "already_held",
    "critical_operational_alerts_active": "unknown",
    "below_min_order_notional_after_execution_sizing": "invalid_geometry",
    "invalid_execution_quantity": "invalid_geometry",
}
BLOCKED_REASONS = frozenset(NON_EXECUTION_REASONS - PRIMARY_REASONS - {"unknown"})


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any, *, exclude: set[str] | None = None) -> str:
    excluded = exclude or set()
    payload = {key: item for key, item in value.items() if key not in excluded} if isinstance(value, Mapping) else value
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()[:32]


_POST_DECISION_FIELDS = frozenset(
    {
        "return_1d",
        "return_3d",
        "return_5d",
        "return_10d",
        "matured_horizons",
        "mfe",
        "mae",
        "first_hit",
        "verdict",
        "fill",
        "fills",
        "realized_pnl",
        "unrealized_pnl",
        "execution_snapshot",
        "slippage",
        "exit_status",
    })


def _contains_post_decision(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in _POST_DECISION_FIELDS:
                return str(key)
            found = _contains_post_decision(item)
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for item in value:
            found = _contains_post_decision(item)
            if found:
                return found
    return None


def candidate_id_for(cycle_id: Any, signal_id: Any, source_run_id: Any = None) -> str | None:
    """Return a stable candidate identity, or None when identity is insufficient."""

    cycle = str(cycle_id or "").strip()
    signal = str(signal_id or "").strip()
    if not cycle or not signal:
        return None
    source = str(source_run_id or "").strip()
    return f"cand_{_hash({'cycle_id': cycle, 'signal_id': signal, 'source_run_id': source})[:24]}"


def normalize_non_execution_reason(value: Any, *, stage: str | None = None) -> str:
    text = str(value or "").strip().lower()
    if text in NON_EXECUTION_REASONS:
        return text
    return _EXPLICIT_REASON_CODES.get(text, "unknown")


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {
        key: getattr(value, key, None)
        for key in ("symbol", "action", "entry_price", "decision_lineage", "decision_context_snapshot", "plan_id")
    }


def _recommendation_key(value: Any) -> tuple[str, str]:
    item = _as_dict(value)
    return str(item.get("symbol") or "").upper(), str(item.get("action") or "").lower()


def _lineage(value: Any) -> dict[str, Any]:
    return dict(_as_dict(value).get("decision_lineage") or {})


def _snapshot(value: Any) -> dict[str, Any]:
    return dict(_as_dict(value).get("decision_context_snapshot") or {})


def _market_hash(value: Any) -> str | None:
    snapshot = _snapshot(value)
    ref = snapshot.get("market_state_ref") or {}
    if ref.get("status") != "available":
        return None
    return str(ref.get("content_hash") or "").strip() or None


def _rank(value: Any) -> float | None:
    raw = _lineage(value).get("candidate_rank")
    if raw is None:
        raw = _as_dict(value).get("candidate_rank")
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _signal_timestamp(value: Any) -> str | None:
    snapshot = _snapshot(value)
    captured = snapshot.get("captured_at")
    return str(captured) if captured else None


def _signal_price(value: Any) -> float | None:
    item = _as_dict(value)
    raw = item.get("entry_price")
    try:
        return float(raw) if raw is not None and float(raw) > 0 else None
    except (TypeError, ValueError):
        return None


def _gate_row(
    row: Mapping[str, Any] | None,
    *,
    gate_name: str,
    stage: str,
    gate_link_status: str = "unavailable",
) -> dict[str, Any]:
    item = dict(row or {})
    approved = item.get("approved")
    checks = item.get("checks") or item.get("metrics") or {}
    if approved is True:
        status = "passed"
    elif approved is False:
        status = "blocked"
    elif row:
        status = "unavailable"
    else:
        status = "not_evaluated"
    reason = item.get("reason")
    return {
        "gate_name": gate_name,
        "gate_version": item.get("gate_version"),
        "stage": stage,
        "gate_link_status": gate_link_status if row else "unavailable",
        "status": status,
        "observed_value": checks.get("observed_value") if isinstance(checks, Mapping) else None,
        "threshold": checks.get("threshold") if isinstance(checks, Mapping) else None,
        "reason_code": normalize_non_execution_reason(reason) if reason else None,
        "evaluated_at": item.get("evaluated_at"),
    }


def _gate_row_for(
    candidate: Any,
    rows: list[Mapping[str, Any]] | None,
    *,
    gate_name: str,
    stage: str,
) -> dict[str, Any]:
    lineage = _lineage(candidate)
    candidate_id = str(lineage.get("candidate_id") or "").strip()
    signal_id = str(lineage.get("signal_id") or "").strip()
    symbol, action = _recommendation_key(candidate)
    fallback: Mapping[str, Any] | None = None
    fallback_status = "unavailable"
    for row in rows or []:
        row_candidate = str(row.get("candidate_id") or "").strip()
        row_signal = str(row.get("signal_id") or "").strip()
        if candidate_id and row_candidate and row_candidate == candidate_id:
            return _gate_row(row, gate_name=gate_name, stage=stage, gate_link_status="strong")
        if signal_id and row_signal and row_signal == signal_id:
            return _gate_row(row, gate_name=gate_name, stage=stage, gate_link_status="strong")
        row_key = (str(row.get("symbol") or "").upper(), str(row.get("action") or "").lower())
        if row_key == (symbol, action) and fallback is None:
            fallback = row
            fallback_status = "weak"
    return _gate_row(fallback, gate_name=gate_name, stage=stage, gate_link_status=fallback_status)


def _gate_ledger(
    candidate: Any,
    *,
    deterministic: list[Mapping[str, Any]] | None,
    adversarial: list[Mapping[str, Any]] | None,
    entry_quality: list[Mapping[str, Any]] | None,
    backtest: list[Mapping[str, Any]] | None,
    strategy_pause: list[Mapping[str, Any]] | None,
    geometry: list[Mapping[str, Any]] | None,
    risk_eligibility: list[Mapping[str, Any]] | None,
    duplicate_symbol: list[Mapping[str, Any]] | None,
    already_held: list[Mapping[str, Any]] | None,
    low_sample: list[Mapping[str, Any]] | None,
    daily_capacity: list[Mapping[str, Any]] | None,
    capacity_reason: str | None = None,
    capacity_link_status: str = "weak",
) -> list[dict[str, Any]]:
    ledger = [
        _gate_row_for(candidate, deterministic, gate_name="deterministic_review", stage="pre_rank"),
        _gate_row_for(candidate, adversarial, gate_name="adversarial_review", stage="post_rank"),
        _gate_row_for(candidate, entry_quality, gate_name="entry_quality", stage="post_rank"),
        _gate_row_for(candidate, backtest, gate_name="backtest", stage="post_rank"),
        _gate_row_for(candidate, strategy_pause, gate_name="strategy_pause", stage="post_rank"),
        _gate_row_for(candidate, geometry, gate_name="geometry", stage="post_rank"),
        _gate_row_for(candidate, risk_eligibility, gate_name="risk_eligibility", stage="post_rank"),
        _gate_row_for(candidate, duplicate_symbol, gate_name="duplicate_symbol", stage="post_rank"),
        _gate_row_for(candidate, already_held, gate_name="already_held", stage="post_rank"),
        _gate_row_for(candidate, low_sample, gate_name="low_sample", stage="post_rank"),
    ]
    if capacity_reason:
        ledger.append(
            {
                "gate_name": "daily_capacity",
                "gate_version": None,
                "stage": "capacity",
                "gate_link_status": capacity_link_status,
                "status": "blocked",
                "observed_value": None,
                "threshold": None,
                "reason_code": normalize_non_execution_reason(capacity_reason, stage="capacity"),
                "evaluated_at": None,
            }
        )
    else:
        ledger.append(_gate_row_for(candidate, daily_capacity, gate_name="daily_capacity", stage="capacity"))
    return ledger


def _identity(value: Any, *, cycle_id: str) -> dict[str, Any]:
    item = _as_dict(value)
    lineage = _lineage(value)
    signal_id = str(lineage.get("signal_id") or "").strip() or None
    signal_capture_id = str(lineage.get("signal_capture_id") or "").strip() or None
    source_run_id = lineage.get("source_run_id") or item.get("source_run_id")
    candidate_id = str(lineage.get("candidate_id") or "").strip() or candidate_id_for(cycle_id, signal_id, source_run_id)
    return {
        "signal_id": signal_id,
        "signal_capture_id": signal_capture_id,
        "candidate_id": candidate_id,
        "rank": _rank(value),
        "signal_price": _signal_price(value),
        "signal_timestamp": _signal_timestamp(value),
        "decision_context_snapshot_id": _snapshot(value).get("snapshot_id"),
        "plan_id": _as_dict(value).get("plan_id"),
        "strategy_name": item.get("strategy_name") or lineage.get("strategy_name"),
        "strategy_version": lineage.get("strategy_version"),
    }


def _blocked_candidate(value: Any, *, reason: str, gate_name: str | None = None, ledger: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    identity = _identity(value, cycle_id=str(_lineage(value).get("cycle_id") or ""))
    return {
        "signal_id": identity["signal_id"],
        "candidate_id": identity["candidate_id"],
        "rank": identity["rank"],
        "blocked_reason": normalize_non_execution_reason(reason),
        "gate_name": gate_name,
        "gate_ledger": ledger or [],
        "gate_ledger_hash": _hash(ledger or []),
    }


def build_comparable_control_sets(
    *,
    cycle_id: str,
    recommendations: list[Any],
    plans: list[Any] | None = None,
    rejected_order_plans: list[Mapping[str, Any]] | None = None,
    all_recommendations: list[Any] | None = None,
    deterministic_review: list[Mapping[str, Any]] | None = None,
    adversarial_review: list[Mapping[str, Any]] | None = None,
    entry_quality_gate: list[Mapping[str, Any]] | None = None,
    backtest_gate: list[Mapping[str, Any]] | None = None,
    strategy_pause_gate: list[Mapping[str, Any]] | None = None,
    geometry_gate: list[Mapping[str, Any]] | None = None,
    risk_eligibility_gate: list[Mapping[str, Any]] | None = None,
    duplicate_symbol_gate: list[Mapping[str, Any]] | None = None,
    already_held_gate: list[Mapping[str, Any]] | None = None,
    low_sample_gate: list[Mapping[str, Any]] | None = None,
    daily_capacity_gate: list[Mapping[str, Any]] | None = None,
    captured_at: datetime | None = None,
    forward_horizon: str = FORWARD_HORIZON,
) -> dict[str, dict[str, Any]]:
    """Build one immutable set per selected buy treatment.

    ``plans`` are the final in-memory plans after every real filter. Persistence
    and order submission happen later. The function never calls a gate or
    ranking rule and never fabricates a rejection reason.
    """

    if forward_horizon != FORWARD_HORIZON:
        raise ValueError("comparable_control_horizon_invalid")
    captured = (captured_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    cycle = str(cycle_id or "").strip()
    all_items = list(all_recommendations or recommendations)
    plan_by_key: dict[tuple[str, str], Any] = {}
    plan_id_by_key: dict[tuple[str, str], Any] = {}
    for plan in plans or []:
        candidate = getattr(plan, "recommendation", None) or (plan.get("recommendation") if isinstance(plan, Mapping) else None)
        if candidate is not None:
            all_items.append(candidate)
            plan_by_key[_recommendation_key(candidate)] = candidate
            plan_id_by_key[_recommendation_key(candidate)] = _as_dict(plan).get("plan_id")
        else:
            side = str(getattr(plan, "side", plan.get("side") if isinstance(plan, Mapping) else "")).lower()
            symbol = str(getattr(plan, "symbol", plan.get("symbol") if isinstance(plan, Mapping) else "")).upper()
            if symbol and side:
                plan_by_key[(symbol, side)] = None
                plan_id_by_key[(symbol, side)] = _as_dict(plan).get("plan_id")
    rec_by_key = {_recommendation_key(item): item for item in all_items}
    gated_by_key = {_recommendation_key(item): item for item in recommendations}
    treatment_keys = {
        _recommendation_key(getattr(plan, "recommendation", None) or (plan.get("recommendation") if isinstance(plan, Mapping) else None))
        for plan in (plans or [])
        if str(getattr(plan, "side", plan.get("side") if isinstance(plan, Mapping) else "")).lower() == "buy"
        and (getattr(plan, "recommendation", None) or (plan.get("recommendation") if isinstance(plan, Mapping) else None)) is not None
    }
    for plan in plans or []:
        side = str(getattr(plan, "side", plan.get("side") if isinstance(plan, Mapping) else "")).lower()
        if side == "buy" and not (getattr(plan, "recommendation", None) or (plan.get("recommendation") if isinstance(plan, Mapping) else None)):
            symbol = str(getattr(plan, "symbol", plan.get("symbol") if isinstance(plan, Mapping) else "")).upper()
            if symbol:
                treatment_keys.add((symbol, side))
    rejection_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for rejected in rejected_order_plans or []:
        symbol = str(rejected.get("symbol") or "").upper()
        if symbol:
            rejection_by_symbol.setdefault(symbol, []).append(dict(rejected))
    deterministic = deterministic_review or []
    adversarial = adversarial_review or []
    entry_quality = entry_quality_gate or []
    backtest = backtest_gate or []
    strategy_pause = strategy_pause_gate or []
    geometry = geometry_gate or []
    risk_eligibility = risk_eligibility_gate or []
    duplicate_symbol = duplicate_symbol_gate or []
    already_held = already_held_gate or []
    low_sample = low_sample_gate or []
    daily_capacity = daily_capacity_gate or []
    result: dict[str, dict[str, Any]] = {}

    used_control_signals: set[str] = set()
    for treatment_key in sorted(treatment_keys):
        treatment = rec_by_key.get(treatment_key, plan_by_key.get(treatment_key))
        treatment_identity = _identity(treatment, cycle_id=cycle)
        if treatment_identity.get("plan_id") is None:
            treatment_identity["plan_id"] = plan_id_by_key.get(treatment_key)
        market_hash = _market_hash(treatment)
        control_set_id = (
            f"cset_{_hash({'cycle_id': cycle, 'treatment_signal_id': treatment_identity['signal_id'], 'horizon': forward_horizon})[:24]}"
            if cycle and treatment_identity["signal_id"]
            else None
        )
        base: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "selection_source": "actual_final_plans",
            "control_set_id": control_set_id,
            "status": "unavailable",
            "cycle_id": cycle or None,
            "forward_horizon": forward_horizon,
            "market_state_ref_hash": market_hash,
            "cycle_link_status": "verified",
            "treatment": treatment_identity,
            "controls": [],
            "blocked_candidates": [],
            "ineligible_candidates": [],
            "eligible_controls_omitted": 0,
            "unavailable_reason": None,
            "captured_at": captured,
        }
        if not cycle:
            base["cycle_link_status"] = "unavailable"
            base["unavailable_reason"] = "cycle_id_unavailable"
        elif treatment is None:
            base["unavailable_reason"] = "treatment_identity_unavailable"
        elif str(_lineage(treatment).get("cycle_id") or "").strip() != cycle:
            base["cycle_link_status"] = "broken"
            base["unavailable_reason"] = "treatment_cycle_mismatch"
        elif not treatment_identity["signal_id"] or not treatment_identity["candidate_id"]:
            base["unavailable_reason"] = "treatment_identity_unavailable"
        elif treatment_identity["signal_price"] is None:
            base["unavailable_reason"] = "treatment_signal_price_unavailable"
        elif not treatment_identity["decision_context_snapshot_id"]:
            base["unavailable_reason"] = "treatment_snapshot_required"
        elif not market_hash:
            base["unavailable_reason"] = "market_state_ref_unavailable"

        if base["unavailable_reason"] is not None:
            base["content_hash"] = _hash(base, exclude={"captured_at", "content_hash"})
            result[treatment_identity["signal_id"] or f"{treatment_key[0]}|{treatment_key[1]}"] = base
            continue

        candidate_rows: list[tuple[float, Any, str, str]] = []
        for key, candidate in gated_by_key.items():
            if key in treatment_keys or str(key[1]).lower() != "buy":
                continue
            candidate_cycle = str(_lineage(candidate).get("cycle_id") or "").strip()
            if candidate_cycle != cycle:
                continue
            symbol = key[0]
            reasons = rejection_by_symbol.get(symbol, [])
            reason = None
            reason_link_status = "unavailable"
            for rejected in reasons:
                rejection_candidate = str(rejected.get("candidate_id") or "").strip()
                rejection_signal = str(rejected.get("signal_id") or "").strip()
                candidate_lineage = _lineage(candidate)
                if rejection_candidate and rejection_candidate == str(candidate_lineage.get("candidate_id") or "").strip():
                    reason_link_status = "strong"
                elif rejection_signal and rejection_signal == str(candidate_lineage.get("signal_id") or "").strip():
                    reason_link_status = "strong"
                elif str(rejected.get("symbol") or "").upper() == symbol:
                    reason_link_status = "weak"
                normalized = normalize_non_execution_reason(rejected.get("reason"), stage=rejected.get("stage"))
                if normalized in NON_EXECUTION_REASONS:
                    reason = normalized
                    break
            if reason is None:
                continue
            candidate_rank = _rank(candidate)
            treatment_rank = treatment_identity["rank"]
            if reason in PRIMARY_REASONS and treatment_rank is not None and candidate_rank is not None and candidate_rank <= treatment_rank:
                continue
            candidate_rows.append((candidate_rank if candidate_rank is not None else float("inf"), candidate, reason, reason_link_status))
        candidate_rows.sort(key=lambda item: (item[0], str(_identity(item[1], cycle_id=cycle).get("signal_id") or "")))

        eligible_count = 0
        for _rank_value, candidate, reason, reason_link_status in candidate_rows:
            identity = _identity(candidate, cycle_id=cycle)
            ledger = _gate_ledger(
                candidate,
                deterministic=deterministic,
                adversarial=adversarial,
                entry_quality=entry_quality,
                backtest=backtest,
                strategy_pause=strategy_pause,
                geometry=geometry,
                risk_eligibility=risk_eligibility,
                duplicate_symbol=duplicate_symbol,
                already_held=already_held,
                low_sample=low_sample,
                daily_capacity=daily_capacity,
                capacity_reason=reason,
                capacity_link_status=(
                    "strong"
                    if any(
                        (str(row.get("candidate_id") or "").strip() and str(row.get("candidate_id") or "").strip() == str(_lineage(candidate).get("candidate_id") or "").strip())
                        or (str(row.get("signal_id") or "").strip() and str(row.get("signal_id") or "").strip() == str(_lineage(candidate).get("signal_id") or "").strip())
                        for row in rejection_by_symbol.get(_recommendation_key(candidate)[0], [])
                    )
                    else "weak"
                ),
            )
            if reason in PRIMARY_REASONS:
                if any(row["status"] == "blocked" for row in ledger[:-1]):
                    base["blocked_candidates"].append(
                        _blocked_candidate(candidate, reason="gate_blocked", ledger=ledger)
                    )
                    continue
                control_snapshot_hash = _market_hash(candidate)
                same_market = bool(control_snapshot_hash and control_snapshot_hash == market_hash)
                if market_hash and control_snapshot_hash and not same_market:
                    continue
                if not control_snapshot_hash:
                    continue
                eligible_count += 1
                if len(base["controls"]) >= CONTROL_LIMIT or str(identity.get("signal_id") or "") in used_control_signals:
                    continue
                # A primary control is verified only when every applicable
                # pre/post-rank gate has an explicit passed result.  Missing
                # gate rows remain auditable but make the control partial.
                gate_required = bool(ledger[:-1]) and all(
                    item["status"] == "passed" and item.get("gate_link_status") == "strong"
                    for item in ledger[:-1]
                )
                gate_eligibility = "verified" if same_market and gate_required and reason_link_status == "strong" and identity["signal_id"] and identity["candidate_id"] and identity["signal_price"] is not None else "partial"
                if identity["signal_timestamp"] is None:
                    gate_eligibility = "partial"
                base["controls"].append(
                    {
                        **{key: identity.get(key) for key in ("signal_id", "candidate_id", "rank", "signal_price", "signal_timestamp")},
                        "non_execution_reason": reason,
                        "reason_link_status": reason_link_status,
                        "gate_eligibility": gate_eligibility,
                        "gate_ledger": ledger,
                        "gate_ledger_hash": _hash(ledger),
                        "market_state_ref_hash": control_snapshot_hash or market_hash,
                    }
                )
                used_control_signals.add(str(identity.get("signal_id") or ""))
            elif reason in BLOCKED_REASONS:
                base["blocked_candidates"].append(_blocked_candidate(candidate, reason=reason, ledger=ledger))
            else:
                identity = _identity(candidate, cycle_id=cycle)
                base["ineligible_candidates"].append(
                    {
                        "signal_id": identity["signal_id"],
                        "candidate_id": identity["candidate_id"],
                        "rank": identity["rank"],
                        "reason": reason,
                        "gate_ledger_hash": _hash(ledger),
                    }
                )
        base["eligible_controls_omitted"] = max(0, eligible_count - len(base["controls"]))
        valid_controls = [item for item in base["controls"] if item["gate_eligibility"] == "verified"]
        partial_controls = [item for item in base["controls"] if item["gate_eligibility"] == "partial"]
        if base["unavailable_reason"] is None:
            if valid_controls:
                base["status"] = "verified"
            elif partial_controls:
                base["status"] = "partially_comparable"
                base["unavailable_reason"] = "control_gate_or_context_partial"
            else:
                base["unavailable_reason"] = "no_eligible_alternatives"
        base["content_hash"] = _hash(base, exclude={"captured_at", "content_hash"})
        result[treatment_identity["signal_id"] or f"{treatment_key[0]}|{treatment_key[1]}"] = base
    return result


def build_unavailable_control_set(
    *,
    cycle_id: str | None,
    treatment: Any = None,
    reason: str = "treatment_identity_unavailable",
) -> dict[str, Any]:
    """Create the explicit unavailable record required for a final plan."""

    identity = _identity(treatment, cycle_id=str(cycle_id or ""))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "selection_source": "actual_final_plans",
        "control_set_id": None,
        "status": "unavailable",
        "cycle_id": str(cycle_id or "") or None,
        "forward_horizon": FORWARD_HORIZON,
        "market_state_ref_hash": _market_hash(treatment),
        "cycle_link_status": "verified" if cycle_id else "unavailable",
        "treatment": identity,
        "controls": [],
        "blocked_candidates": [],
        "ineligible_candidates": [],
        "eligible_controls_omitted": 0,
        "unavailable_reason": reason,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    payload["content_hash"] = _hash(payload, exclude={"captured_at", "content_hash"})
    return payload


def validate_comparable_control_set(control_set: Mapping[str, Any]) -> None:
    if not isinstance(control_set, Mapping):
        raise ValueError("comparable_control_set_not_object")
    if control_set.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("comparable_control_schema_version_invalid")
    if control_set.get("status") not in CONTROL_STATUSES:
        raise ValueError("comparable_control_status_invalid")
    if control_set.get("forward_horizon") != FORWARD_HORIZON:
        raise ValueError("comparable_control_horizon_invalid")
    unavailable = control_set.get("status") == "unavailable"
    if control_set.get("selection_source") != "actual_final_plans":
        raise ValueError("comparable_control_selection_source_invalid")
    if not control_set.get("cycle_id") and not unavailable:
        raise ValueError("comparable_control_cycle_missing")
    treatment = control_set.get("treatment") or {}
    if (not treatment.get("signal_id") or not treatment.get("candidate_id")) and not unavailable:
        raise ValueError("comparable_control_treatment_identity_missing")
    if not unavailable and (treatment.get("signal_price") is None or not treatment.get("decision_context_snapshot_id")):
        raise ValueError("comparable_control_treatment_context_missing")
    post_decision = _contains_post_decision(control_set)
    if post_decision:
        raise ValueError(f"comparable_control_post_decision_field:{post_decision}")
    controls = control_set.get("controls") or []
    if len(controls) > CONTROL_LIMIT:
        raise ValueError("comparable_control_limit_exceeded")
    seen: set[str] = set()
    treatment_signal = str(treatment.get("signal_id"))
    for control in controls:
        if control.get("signal_id") in seen or control.get("signal_id") == treatment_signal:
            raise ValueError("comparable_control_duplicate_signal")
        seen.add(str(control.get("signal_id")))
        if control.get("non_execution_reason") not in PRIMARY_REASONS:
            raise ValueError("comparable_control_reason_invalid")
        if control.get("gate_eligibility") not in GATE_ELIGIBILITY:
            raise ValueError("comparable_control_gate_eligibility_invalid")
        if control.get("reason_link_status") not in {"strong", "weak", "unavailable"}:
            raise ValueError("comparable_control_reason_link_invalid")
        if control.get("signal_price") is None:
            raise ValueError("comparable_control_signal_price_missing")
    expected = _hash(control_set, exclude={"captured_at", "content_hash"})
    if control_set.get("content_hash") != expected:
        raise ValueError("comparable_control_content_hash_invalid")


def copy_comparable_control_set(control_set: Mapping[str, Any]) -> dict[str, Any]:
    validate_comparable_control_set(control_set)
    return copy.deepcopy(dict(control_set))


def merge_comparable_control_set(existing: Mapping[str, Any] | None, incoming: Mapping[str, Any]) -> str:
    """Return attached/idempotent/conflict without mutating either payload."""

    validate_comparable_control_set(incoming)
    if not existing:
        return "attached"
    validate_comparable_control_set(existing)
    if existing.get("control_set_id") == incoming.get("control_set_id") and existing.get("content_hash") == incoming.get("content_hash"):
        return "idempotent"
    return "conflict"


def derive_comparable_control_outcomes(store: Any, control_set: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve a read-only outcome view by exact signal IDs.

    The captured control set is never mutated.  A missing or immature outcome
    remains explicit and cannot be interpreted as a comparison.
    """

    validate_comparable_control_set(control_set)
    rows = {
        str(item.get("signal_id") or ""): item
        for item in store.signal_outcomes(limit=200000, include_lab_book=True, include_learning_experiment=True)
        if item.get("signal_id")
    }

    def resolve(identity: Mapping[str, Any]) -> dict[str, Any]:
        signal_id = str(identity.get("signal_id") or "")
        row = rows.get(signal_id)
        if not row:
            return {"signal_id": signal_id or None, "status": "unavailable", "outcome_source": None}
        outcome = row.get("outcome") or {}
        matured = bool((outcome.get("matured_horizons") or {}).get(FORWARD_HORIZON))
        return {
            "signal_id": signal_id,
            "status": "evaluable" if matured and outcome.get("return_10d") is not None else "immature",
            "outcome_source": "signal_outcomes",
            "return_10d": outcome.get("return_10d") if matured else None,
            "matured_10d": matured,
        }

    return {
        "control_set_id": control_set.get("control_set_id"),
        "forward_horizon": FORWARD_HORIZON,
        "treatment": resolve(control_set.get("treatment") or {}),
        "controls": [resolve(item) for item in control_set.get("controls") or []],
    }


def comparable_control_evaluation_status(
    control_set: Mapping[str, Any],
    outcome_view: Mapping[str, Any],
    *,
    min_sample: int = 30,
) -> str:
    """Return a non-causal maturity/sample state for a captured set."""

    validate_comparable_control_set(control_set)
    if control_set.get("status") == "unavailable":
        return "unavailable"
    rows = [outcome_view.get("treatment") or {}, *(outcome_view.get("controls") or [])]
    if not rows:
        return "collecting"
    evaluable = sum(row.get("status") == "evaluable" for row in rows)
    if evaluable == 0:
        return "immature"
    if evaluable < max(1, int(min_sample)):
        return "insufficient_sample"
    return "evaluable"


def _iso_date(value: Any) -> str:
    return str(value or "")[:10]


def build_comparable_control_quality(
    store: Any,
    *,
    start: str | None = None,
    end: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Read-only digest for newly captured control sets."""

    legacy = 0
    legacy_v1 = 0
    invalid_schema = 0

    # Keep only aggregate state and identities needed to join the later outcome
    # stream.  The old reader retained up to 50k full recommendation payloads
    # and 200k full outcome payloads at once.
    counts: Counter[str] = Counter()
    denominator = 0
    primary_controls = 0
    blocked_candidates = 0
    eligible_controls_omitted = 0
    control_denominator = 0
    same_cycle_count = 0
    signal_price_count = 0
    market_state_ref_count = 0
    gate_ledger_count = 0
    non_execution_reason_count = 0
    unavailable_by_reason: Counter[str] = Counter()
    selection_source_count = 0
    maturity = {"treatment": 0, "controls": 0, "total": 0}
    tracked_signal_ids: set[str] = set()
    maturity_probe_by_signal_id: dict[str, tuple[str, bool | str]] = {}
    treatment_signal_ids: Counter[str] = Counter()
    control_signal_ids: Counter[str] = Counter()
    arm_signal_order: list[tuple[str, tuple[str, str]]] = []
    metric_errors: dict[str, Exception] = {}

    def signal_probe(identity: Any, *, arm: str, treatment: bool = False) -> tuple[str, str]:
        normalized = identity or {} if treatment else identity
        if not isinstance(normalized, Mapping):
            return "invalid", type(normalized).__name__
        signal_id = str(normalized.get("signal_id") or "")
        tracked_signal_ids.add(signal_id)
        (treatment_signal_ids if arm == "treatment" else control_signal_ids)[signal_id] += 1
        return "signal", signal_id

    def remember_metric_error(name: str, error: Exception) -> None:
        metric_errors.setdefault(name, error)

    def consume_control_set(item: Any) -> None:
        nonlocal denominator
        nonlocal primary_controls, blocked_candidates, eligible_controls_omitted
        nonlocal control_denominator, same_cycle_count, signal_price_count
        nonlocal market_state_ref_count, gate_ledger_count, non_execution_reason_count
        nonlocal selection_source_count

        counts[str(item.get("status") or "unavailable")] += 1
        denominator += 1
        is_verified = item.get("status") == "verified"
        controls_for_item = item.get("controls") or []
        # The base builds its verified-control list before reading outcomes.
        # Validate iteration now, while deferring per-control field reads.
        for _control in controls_for_item:
            pass
        if is_verified:
            primary_controls += len(controls_for_item)
        arm_signal_order.append(
            ("treatment", signal_probe(item.get("treatment"), arm="treatment", treatment=True))
        )
        for control in controls_for_item:
            arm_signal_order.append(("controls", signal_probe(control, arm="controls")))
        control_denominator += len(controls_for_item)

        try:
            blocked_candidates += len(item.get("blocked_candidates") or [])
        except Exception as exc:
            remember_metric_error("blocked_candidates", exc)
        try:
            eligible_controls_omitted += int(item.get("eligible_controls_omitted") or 0)
        except Exception as exc:
            remember_metric_error("eligible_controls_omitted", exc)
        same_cycle_count += bool(item.get("cycle_id"))
        try:
            signal_price_count += bool((item.get("treatment") or {}).get("signal_price"))
        except Exception as exc:
            remember_metric_error("signal_price", exc)
        market_state_ref_count += bool(item.get("market_state_ref_hash"))
        try:
            gate_ledger_count += sum(bool(control.get("gate_ledger")) for control in controls_for_item)
        except Exception as exc:
            remember_metric_error("gate_ledger", exc)
        try:
            non_execution_reason_count += sum(
                control.get("non_execution_reason") in PRIMARY_REASONS for control in controls_for_item
            )
        except Exception as exc:
            remember_metric_error("non_execution_reason", exc)
        if item.get("unavailable_reason"):
            unavailable_by_reason[str(item.get("unavailable_reason") or "")] += 1
        selection_source_count += item.get("selection_source") == "actual_final_plans"

    def consume_recommendation(record: Mapping[str, Any]) -> None:
        nonlocal legacy, legacy_v1, invalid_schema
        created = _iso_date(record.get("created_at"))
        if start and created and created < start:
            return
        if end and created and created > end:
            return
        payload = record.get("payload") or {}
        control_set = payload.get("comparable_control_set")
        if not control_set:
            legacy += 1
            return
        if control_set.get("schema_version") == LEGACY_SCHEMA_VERSION:
            legacy_v1 += 1
            return
        if control_set.get("schema_version") != SCHEMA_VERSION:
            invalid_schema += 1
            return
        if status and str(control_set.get("status") or "") != status:
            return
        consume_control_set(control_set)

    def consume_outcome(record: Mapping[str, Any]) -> None:
        signal_id = str(record.get("signal_id") or "")
        if signal_id not in tracked_signal_ids:
            return
        outcome = record.get("outcome") or {}
        # Keep a compact probe only. Assignment on every row preserves legacy
        # last-wins behavior; shape errors are raised only for the final row.
        if not isinstance(outcome, Mapping):
            maturity_probe_by_signal_id[signal_id] = ("invalid_outcome", type(outcome).__name__)
            return
        matured_horizons = outcome.get("matured_horizons")
        if not matured_horizons:
            maturity_probe_by_signal_id[signal_id] = ("value", False)
        elif not isinstance(matured_horizons, Mapping):
            maturity_probe_by_signal_id[signal_id] = ("invalid_horizons", type(matured_horizons).__name__)
        else:
            maturity_probe_by_signal_id[signal_id] = ("value", bool(matured_horizons.get("10d")))

    stream_factory = getattr(store, "comparable_control_quality_record_stream", None)
    if callable(stream_factory):
        with stream_factory(batch_size=512) as stream:
            for kind, record in stream:
                if kind == "recommendation":
                    consume_recommendation(record)
                elif kind == "outcome":
                    consume_outcome(record)
                else:
                    raise ValueError(f"comparable_control_quality_record_kind_invalid:{kind}")
    else:
        # Fakes and older Store implementations keep their list-based contract.
        for record in store.trade_recommendations(limit=50000):
            consume_recommendation(record)
        for record in store.signal_outcomes(
            limit=200000,
            include_lab_book=True,
            include_learning_experiment=True,
        ):
            consume_outcome(record)

    # Re-evaluate maturity after all duplicate outcome rows have been seen.
    # This second pass uses IDs only; no outcome payload is retained.
    for arm, probe in arm_signal_order:
        probe_kind, probe_value = probe
        if probe_kind != "signal":
            raise AttributeError(f"'{probe_value}' object has no attribute 'get'")
        signal_id = probe_value
        probe = maturity_probe_by_signal_id.get(signal_id)
        if probe:
            probe_kind, probe_value = probe
            if probe_kind != "value":
                raise AttributeError(f"'{probe_value}' object has no attribute 'get'")
            if probe_value:
                maturity[arm] += 1
    for metric_name in (
        "blocked_candidates",
        "eligible_controls_omitted",
        "signal_price",
        "gate_ledger",
        "non_execution_reason",
    ):
        error = metric_errors.get(metric_name)
        if error is not None:
            raise error
    mature_total = maturity["treatment"] + maturity["controls"]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "collecting" if not denominator or not mature_total else "evaluable",
        "window": {"from": start, "to": end, "status_filter": status},
        "treatments_total_new": denominator,
        "treatments_with_control_set": denominator,
        "verified_control_sets": counts.get("verified", 0),
        "partially_comparable_sets": counts.get("partially_comparable", 0),
        "unavailable_sets": counts.get("unavailable", 0),
        "primary_controls": primary_controls,
        "blocked_candidates": blocked_candidates,
        "eligible_controls_omitted": eligible_controls_omitted,
        "treatment_control_pairs": primary_controls,
        "average_controls_per_treatment": primary_controls / denominator if denominator else None,
        "same_cycle_coverage": same_cycle_count / denominator if denominator else None,
        "signal_price_coverage": signal_price_count / denominator if denominator else None,
        "market_state_ref_coverage": market_state_ref_count / denominator if denominator else None,
        "gate_ledger_coverage": gate_ledger_count / control_denominator if control_denominator else None,
        "non_execution_reason_coverage": non_execution_reason_count / control_denominator if control_denominator else None,
        "outcome_maturity_by_arm": maturity,
        "outcome_maturity_coverage": mature_total / (denominator + control_denominator) if denominator + control_denominator else None,
        "conflicts": None,
        "conflicts_status": "unavailable",
        "unavailable_by_reason": dict(unavailable_by_reason),
        "legacy_without_control_set": legacy,
        "legacy_v1_prospective_selection": legacy_v1,
        "invalid_schema_count": invalid_schema,
        "selection_source_coverage": selection_source_count / denominator if denominator else None,
    }
