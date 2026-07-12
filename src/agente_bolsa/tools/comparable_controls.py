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

SCHEMA_VERSION = "p-l31b.comparable-control.v1"
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
    if "max_orders_per_cycle" in text or "capacity" in text or "cycle_order_limit" in text:
        return "capacity_limit"
    if "daily_buy" in text or "daily_order" in text:
        return "daily_order_limit"
    if "low_sample" in text:
        return "low_sample_quota"
    if "strategy_pause" in text or "paused" in text:
        return "strategy_paused"
    if "duplicate" in text:
        return "duplicate_symbol"
    if "already_held" in text or "position" in text:
        return "already_held"
    if "risk" in text or "exposure" in text:
        return "risk_blocked"
    if "geometry" in text or "stop" in text or "take" in text:
        return "invalid_geometry"
    if "gate" in text or "entry_quality" in text or "backtest" in text:
        return "gate_blocked"
    if stage == "capacity":
        return "capacity_limit"
    return "unknown"


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {key: getattr(value, key, None) for key in ("symbol", "action", "entry_price", "decision_lineage", "decision_context_snapshot")}


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


def _gate_row(row: Mapping[str, Any] | None, *, gate_name: str, stage: str) -> dict[str, Any]:
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
        "status": status,
        "observed_value": checks.get("observed_value") if isinstance(checks, Mapping) else None,
        "threshold": checks.get("threshold") if isinstance(checks, Mapping) else None,
        "reason_code": normalize_non_execution_reason(reason) if reason else None,
        "evaluated_at": item.get("evaluated_at"),
    }


def _rows_by_symbol(rows: list[Mapping[str, Any]] | None) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows or []:
        key = (str(row.get("symbol") or "").upper(), str(row.get("action") or "").lower())
        if key[0]:
            result[key] = dict(row)
    return result


def _gate_ledger(
    candidate: Any,
    *,
    deterministic: Mapping[tuple[str, str], dict[str, Any]],
    adversarial: Mapping[tuple[str, str], dict[str, Any]],
    entry_quality: Mapping[tuple[str, str], dict[str, Any]],
    backtest: Mapping[tuple[str, str], dict[str, Any]],
    strategy_pause: Mapping[tuple[str, str], dict[str, Any]],
    geometry: Mapping[tuple[str, str], dict[str, Any]],
    risk_eligibility: Mapping[tuple[str, str], dict[str, Any]],
    duplicate_symbol: Mapping[tuple[str, str], dict[str, Any]],
    already_held: Mapping[tuple[str, str], dict[str, Any]],
    low_sample: Mapping[tuple[str, str], dict[str, Any]],
    daily_capacity: Mapping[tuple[str, str], dict[str, Any]],
    capacity_reason: str | None = None,
) -> list[dict[str, Any]]:
    key = _recommendation_key(candidate)
    ledger = [
        _gate_row(deterministic.get(key), gate_name="deterministic_review", stage="pre_rank"),
        _gate_row(adversarial.get(key), gate_name="adversarial_review", stage="post_rank"),
        _gate_row(entry_quality.get(key), gate_name="entry_quality", stage="post_rank"),
        _gate_row(backtest.get(key), gate_name="backtest", stage="post_rank"),
        _gate_row(strategy_pause.get(key), gate_name="strategy_pause", stage="post_rank"),
        _gate_row(geometry.get(key), gate_name="geometry", stage="post_rank"),
        _gate_row(risk_eligibility.get(key), gate_name="risk_eligibility", stage="post_rank"),
        _gate_row(duplicate_symbol.get(key), gate_name="duplicate_symbol", stage="post_rank"),
        _gate_row(already_held.get(key), gate_name="already_held", stage="post_rank"),
        _gate_row(low_sample.get(key), gate_name="low_sample", stage="post_rank"),
    ]
    if capacity_reason:
        ledger.append(
            {
                "gate_name": "daily_capacity",
                "gate_version": None,
                "stage": "capacity",
                "status": "blocked",
                "observed_value": None,
                "threshold": None,
                "reason_code": normalize_non_execution_reason(capacity_reason, stage="capacity"),
                "evaluated_at": None,
            }
        )
    else:
        ledger.append(_gate_row(daily_capacity.get(key), gate_name="daily_capacity", stage="capacity"))
    return ledger


def _identity(value: Any, *, cycle_id: str) -> dict[str, Any]:
    item = _as_dict(value)
    lineage = _lineage(value)
    signal_id = str(lineage.get("signal_id") or "").strip() or None
    source_run_id = lineage.get("source_run_id") or item.get("source_run_id")
    candidate_id = str(lineage.get("candidate_id") or "").strip() or candidate_id_for(cycle_id, signal_id, source_run_id)
    return {
        "signal_id": signal_id,
        "candidate_id": candidate_id,
        "rank": _rank(value),
        "signal_price": _signal_price(value),
        "signal_timestamp": _signal_timestamp(value),
        "decision_context_snapshot_id": _snapshot(value).get("snapshot_id"),
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
    selected_recommendations: list[Any] | None = None,
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

    ``plans`` are already-created in-memory plans; persistence and order
    submission happen later.  The function never calls a gate or ranking rule.
    """

    if forward_horizon != FORWARD_HORIZON:
        raise ValueError("comparable_control_horizon_invalid")
    captured = (captured_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    cycle = str(cycle_id or "").strip()
    all_items = list(all_recommendations or recommendations)
    for plan in plans or []:
        candidate = getattr(plan, "recommendation", None) or (plan.get("recommendation") if isinstance(plan, Mapping) else None)
        if candidate is not None:
            all_items.append(candidate)
    all_items.extend(selected_recommendations or [])
    rec_by_key = {_recommendation_key(item): item for item in all_items}
    gated_by_key = {_recommendation_key(item): item for item in recommendations}
    treatment_keys = {
        _recommendation_key(getattr(plan, "recommendation", None) or (plan.get("recommendation") if isinstance(plan, Mapping) else None))
        for plan in (plans or [])
        if str(getattr(plan, "side", plan.get("side") if isinstance(plan, Mapping) else "")).lower() == "buy"
    }
    treatment_keys.update(_recommendation_key(item) for item in (selected_recommendations or []))
    rejection_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for rejected in rejected_order_plans or []:
        symbol = str(rejected.get("symbol") or "").upper()
        if symbol:
            rejection_by_symbol.setdefault(symbol, []).append(dict(rejected))
    deterministic = _rows_by_symbol(deterministic_review)
    adversarial = _rows_by_symbol(adversarial_review)
    entry_quality = _rows_by_symbol(entry_quality_gate)
    backtest = _rows_by_symbol(backtest_gate)
    strategy_pause = _rows_by_symbol(strategy_pause_gate)
    geometry = _rows_by_symbol(geometry_gate)
    risk_eligibility = _rows_by_symbol(risk_eligibility_gate)
    duplicate_symbol = _rows_by_symbol(duplicate_symbol_gate)
    already_held = _rows_by_symbol(already_held_gate)
    low_sample = _rows_by_symbol(low_sample_gate)
    daily_capacity = _rows_by_symbol(daily_capacity_gate)
    result: dict[str, dict[str, Any]] = {}

    used_control_signals: set[str] = set()
    for treatment_key in sorted(treatment_keys):
        treatment = rec_by_key.get(treatment_key)
        if treatment is None:
            continue
        treatment_identity = _identity(treatment, cycle_id=cycle)
        market_hash = _market_hash(treatment)
        control_set_id = (
            f"cset_{_hash({'cycle_id': cycle, 'treatment_signal_id': treatment_identity['signal_id'], 'horizon': forward_horizon})[:24]}"
            if cycle and treatment_identity["signal_id"]
            else None
        )
        base: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "control_set_id": control_set_id,
            "status": "unavailable",
            "cycle_id": cycle or None,
            "forward_horizon": forward_horizon,
            "market_state_ref_hash": market_hash,
            "cycle_link_status": "verified",
            "treatment": treatment_identity,
            "controls": [],
            "blocked_candidates": [],
            "eligible_controls_omitted": 0,
            "unavailable_reason": None,
            "captured_at": captured,
        }
        if not cycle:
            base["cycle_link_status"] = "unavailable"
            base["unavailable_reason"] = "cycle_id_unavailable"
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

        candidate_rows: list[tuple[float, Any, str]] = []
        for key, candidate in gated_by_key.items():
            if key in treatment_keys or str(key[1]).lower() != "buy":
                continue
            candidate_cycle = str(_lineage(candidate).get("cycle_id") or "").strip()
            if candidate_cycle != cycle:
                continue
            symbol = key[0]
            reasons = rejection_by_symbol.get(symbol, [])
            reason = None
            for rejected in reasons:
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
            candidate_rows.append((candidate_rank if candidate_rank is not None else float("inf"), candidate, reason))
        candidate_rows.sort(key=lambda item: (item[0], str(_identity(item[1], cycle_id=cycle).get("signal_id") or "")))

        eligible_count = 0
        for _rank_value, candidate, reason in candidate_rows:
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
            )
            if reason in PRIMARY_REASONS:
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
                gate_required = bool(ledger[:-1]) and all(item["status"] == "passed" for item in ledger[:-1])
                gate_eligibility = "verified" if same_market and gate_required and identity["signal_id"] and identity["candidate_id"] and identity["signal_price"] is not None else "partial"
                if identity["signal_timestamp"] is None:
                    gate_eligibility = "partial"
                base["controls"].append(
                    {
                        **{key: identity.get(key) for key in ("signal_id", "candidate_id", "rank", "signal_price", "signal_timestamp")},
                        "non_execution_reason": reason,
                        "gate_eligibility": gate_eligibility,
                        "gate_ledger": ledger,
                        "gate_ledger_hash": _hash(ledger),
                        "market_state_ref_hash": control_snapshot_hash or market_hash,
                    }
                )
                used_control_signals.add(str(identity.get("signal_id") or ""))
            elif reason not in PRIMARY_REASONS:
                base["blocked_candidates"].append(_blocked_candidate(candidate, reason=reason, ledger=ledger))
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

    records = []
    legacy = 0
    for record in store.trade_recommendations(limit=50000):
        created = _iso_date(record.get("created_at"))
        if start and created and created < start:
            continue
        if end and created and created > end:
            continue
        payload = record.get("payload") or {}
        control_set = payload.get("comparable_control_set")
        if not control_set:
            legacy += 1
            continue
        if status and str(control_set.get("status") or "") != status:
            continue
        records.append(control_set)
    counts = Counter(str(item.get("status") or "unavailable") for item in records)
    verified = [item for item in records if item.get("status") == "verified"]
    controls = [control for item in verified for control in item.get("controls") or []]
    outcomes_by_id = {}
    for item in store.signal_outcomes(limit=200000, include_lab_book=True, include_learning_experiment=True):
        outcomes_by_id[str(item.get("signal_id") or "")] = item.get("outcome") or {}
    maturity = {"treatment": 0, "controls": 0, "total": 0}
    for item in records:
        treatment_signal = str((item.get("treatment") or {}).get("signal_id") or "")
        outcome = outcomes_by_id.get(treatment_signal) or {}
        if (outcome.get("matured_horizons") or {}).get("10d"):
            maturity["treatment"] += 1
        for control in item.get("controls") or []:
            outcome = outcomes_by_id.get(str(control.get("signal_id") or "")) or {}
            if (outcome.get("matured_horizons") or {}).get("10d"):
                maturity["controls"] += 1
    denominator = len(records)
    control_denominator = sum(len(item.get("controls") or []) for item in records)
    mature_total = maturity["treatment"] + maturity["controls"]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "collecting" if not records or not mature_total else "evaluable",
        "window": {"from": start, "to": end, "status_filter": status},
        "treatments_total_new": denominator,
        "treatments_with_control_set": denominator,
        "verified_control_sets": counts.get("verified", 0),
        "partially_comparable_sets": counts.get("partially_comparable", 0),
        "unavailable_sets": counts.get("unavailable", 0),
        "primary_controls": len(controls),
        "blocked_candidates": sum(len(item.get("blocked_candidates") or []) for item in records),
        "eligible_controls_omitted": sum(int(item.get("eligible_controls_omitted") or 0) for item in records),
        "treatment_control_pairs": len(controls),
        "average_controls_per_treatment": len(controls) / denominator if denominator else None,
        "same_cycle_coverage": sum(bool(item.get("cycle_id")) for item in records) / denominator if denominator else None,
        "signal_price_coverage": sum(bool((item.get("treatment") or {}).get("signal_price")) for item in records) / denominator if denominator else None,
        "market_state_ref_coverage": sum(bool(item.get("market_state_ref_hash")) for item in records) / denominator if denominator else None,
        "gate_ledger_coverage": sum(
            bool(control.get("gate_ledger"))
            for item in records
            for control in item.get("controls") or []
        ) / control_denominator if control_denominator else None,
        "non_execution_reason_coverage": sum(
            control.get("non_execution_reason") in PRIMARY_REASONS
            for item in records
            for control in item.get("controls") or []
        ) / control_denominator if control_denominator else None,
        "outcome_maturity_by_arm": maturity,
        "outcome_maturity_coverage": mature_total / (denominator + control_denominator) if denominator + control_denominator else None,
        "conflicts": None,
        "conflicts_status": "unavailable",
        "unavailable_by_reason": dict(Counter(str(item.get("unavailable_reason") or "") for item in records if item.get("unavailable_reason"))),
        "legacy_without_control_set": legacy,
    }
