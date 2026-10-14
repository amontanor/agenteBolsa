"""Prospective, observation-only gate-path ledger.

The collector consumes results already produced by the cycle.  It never calls
or reimplements a gate; its only job is to seal an immutable, auditable path.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

SCHEMA_VERSION = "p-l32b.gate-evaluation.v1"
FORWARD_HORIZON = "10d"
GATE_ORDER = (
    ("deterministic_review", "eligibility"),
    ("adversarial_review", "safety"),
    ("entry_quality", "eligibility"),
    ("backtest", "eligibility"),
    ("market_state_operational", "operational"),
    ("research_operational", "operational"),
    ("kill_switch_operational", "operational"),
    ("confidence", "eligibility"),
    ("open_order", "portfolio"),
    ("already_held", "portfolio"),
    ("duplicate_symbol", "portfolio"),
    ("sizing", "eligibility"),
    ("geometry", "eligibility"),
    ("risk_eligibility", "safety"),
    ("daily_capacity", "capacity"),
    ("low_sample_quota", "capacity"),
    ("strategy_pause", "operational"),
)
_POST_FIELDS = {
    "return_1d", "return_3d", "return_5d", "return_10d", "matured_horizons",
    "mfe", "mae", "mfe_10d", "mae_10d", "first_hit", "verdict", "fill",
    "fills", "slippage", "realized_pnl", "unrealized_pnl", "execution_snapshot",
}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()[:32]


def _contains_post(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in _POST_FIELDS:
                return str(key)
            found = _contains_post(item)
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for item in value:
            found = _contains_post(item)
            if found:
                return found
    return None


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {key: getattr(value, key, None) for key in (
        "symbol", "action", "entry_price", "decision_lineage", "decision_context_snapshot",
        "strategy_name", "gate_evaluation_snapshot",
    )}


def _lineage(value: Any) -> dict[str, Any]:
    return dict(_as_dict(value).get("decision_lineage") or {})


def _action(value: Any) -> str | None:
    item = _as_dict(value)
    lineage = _lineage(value)
    raw = str(item.get("action") or item.get("side") or lineage.get("action") or "").strip().lower()
    if raw == "sell":
        return "exit"
    return raw or None


def _identity_fields(value: Any, cycle_id: str | None = None) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    item = _as_dict(value)
    lineage = _lineage(value)
    cycle = str(item.get("cycle_id") or lineage.get("cycle_id") or cycle_id or "").strip() or None
    action = _action(value)
    candidate_id = str(item.get("candidate_id") or lineage.get("candidate_id") or "").strip() or None
    capture_id = str(item.get("signal_capture_id") or lineage.get("signal_capture_id") or "").strip() or None
    signal_id = str(item.get("signal_id") or lineage.get("signal_id") or "").strip() or None
    return cycle, action, candidate_id, capture_id, signal_id


def gate_identity_key(value: Any, cycle_id: str | None = None) -> tuple[str, str, str] | None:
    """Return exact decision identity for gate snapshot association.

    Candidate and capture IDs are preferred over the shared daily signal ID.
    The action remains part of the key so BUY and EXIT cannot inherit each
    other's observational path.
    """
    cycle, action, candidate_id, capture_id, signal_id = _identity_fields(value, cycle_id)
    if cycle_id and cycle and cycle != str(cycle_id).strip():
        return None
    canonical_id = candidate_id or capture_id or signal_id
    if not cycle or not action or not canonical_id:
        return None
    return cycle, action, canonical_id


def _identity(value: Any, cycle_id: str) -> tuple[str | None, str | None, str]:
    lineage_cycle, _, candidate_id, _, signal_id = _identity_fields(value, cycle_id)
    lineage_cycle = lineage_cycle or ""
    if lineage_cycle and str(cycle_id).strip() and lineage_cycle != str(cycle_id).strip():
        return candidate_id, signal_id, "unavailable"
    status = "verified" if candidate_id else ("weak" if signal_id else "unavailable")
    return candidate_id, signal_id, status


def _row_identity(row: Mapping[str, Any], candidate: Any) -> str:
    candidate_cycle, candidate_action, candidate_id, capture_id, signal_id = _identity_fields(candidate)
    row_cycle, row_action, row_candidate_id, row_capture_id, row_signal_id = _identity_fields(row)
    if row_cycle and candidate_cycle and row_cycle != candidate_cycle:
        return "unavailable"
    if row_action and candidate_action and row_action != candidate_action:
        return "unavailable"
    if row_candidate_id:
        return "strong" if candidate_id and row_candidate_id == candidate_id else "unavailable"
    if row_capture_id:
        return "strong" if capture_id and row_capture_id == capture_id else "unavailable"
    if row_signal_id and signal_id and row_signal_id == signal_id:
        # A signal-only row cannot identify BUY versus EXIT. Keep it usable only
        # when the row carries the same explicit action; otherwise it is unsafe.
        return "weak" if row_action and candidate_action else "unavailable"
    return "unavailable"


def _gate_row(gate_name: str, category: str, row: Mapping[str, Any] | None, identity: str, order: int) -> dict[str, Any]:
    if not row:
        return {"gate_name": gate_name, "gate_version": None, "order": order, "category": category,
                "status": "unavailable", "observed_value": None, "threshold": None,
                "reason_code": None, "evaluated_at": None, "identity_link_status": "unavailable"}
    approved = row.get("approved")
    status = "passed" if approved is True else ("blocked" if approved is False else "unavailable")
    checks = row.get("checks") or row.get("metrics") or {}
    return {"gate_name": gate_name, "gate_version": row.get("gate_version"), "order": order,
            "category": category, "status": status,
            "observed_value": checks.get("observed_value") if isinstance(checks, Mapping) else None,
            "threshold": checks.get("threshold") if isinstance(checks, Mapping) else None,
            "reason_code": row.get("reason_code") or row.get("reason"),
            "evaluated_at": row.get("evaluated_at"), "identity_link_status": identity}


def _find_row(
    candidate: Any,
    rows: list[Mapping[str, Any]] | None,
    *,
    candidates: list[Any] | None = None,
) -> tuple[Mapping[str, Any] | None, str]:
    strong_matches = []
    weak_matches = []
    for row in rows or []:
        link = _row_identity(row, candidate)
        if link == "strong":
            strong_matches.append(row)
        elif link == "weak":
            if candidates is not None:
                peer_matches = [peer for peer in candidates if _row_identity(row, peer) == "weak"]
                if len(peer_matches) != 1:
                    continue
            weak_matches.append(row)
    if len(strong_matches) == 1:
        return strong_matches[0], "strong"
    if len(strong_matches) > 1:
        return None, "unavailable"
    if len(weak_matches) == 1:
        return weak_matches[0], "weak"
    return None, "unavailable"


def collect_gate_path(
    *,
    cycle_id: str,
    candidates: list[Any],
    stage_rows: Mapping[str, list[Mapping[str, Any]] | None],
    final_plans: list[Any] | None = None,
    rejected_order_plans: list[Mapping[str, Any]] | None = None,
    captured_at: str,
) -> dict[str, dict[str, Any]]:
    """Seal paths from already-produced rows; no gate is executed here."""
    result: dict[str, dict[str, Any]] = {}
    observed_rows = {name: list(rows or []) for name, rows in stage_rows.items()}
    rejection_gate = {
        "market_state_guard": "market_state_operational",
        "research_guard": "research_operational",
        "operational_kill_switch": "kill_switch_operational",
        "llm_confidence": "confidence",
        "open_order_guard": "open_order",
        "position_add_guard": "already_held",
        "duplicate_symbol_cycle_guard": "duplicate_symbol",
        "position_sizing": "sizing",
        "risk_manager": "risk_eligibility",
        "execution_sizing": "geometry",
        "cycle_order_limit": "daily_capacity",
        "daily_buy_limit": "daily_capacity",
        "low_sample_daily_quota": "low_sample_quota",
        "learning_mode_strategy_pause": "strategy_pause",
    }
    for rejection in rejected_order_plans or []:
        gate_name = rejection_gate.get(str(rejection.get("stage") or ""))
        if gate_name:
            observed_rows.setdefault(gate_name, []).append({**dict(rejection), "approved": False})
    for rows in stage_rows.values():
        for row in rows or []:
            bad = _contains_post(row)
            if bad:
                raise ValueError(f"post_decision_field:{bad}")
    final_key_counts: dict[tuple[str, str, str], int] = {}
    for plan in final_plans or []:
        rec = getattr(plan, "recommendation", None)
        key = gate_identity_key(rec, cycle_id)
        if key is not None:
            final_key_counts[key] = final_key_counts.get(key, 0) + 1
    final_keys = {key for key, count in final_key_counts.items() if count == 1}
    for candidate in candidates:
        item = _as_dict(candidate)
        candidate_id, signal_id, identity_status = _identity(candidate, cycle_id)
        identity_key = gate_identity_key(candidate, cycle_id)
        if identity_key is None:
            # Keep the public result key stable even when identity validation
            # fails; the failure must affect linkage/decision, not collection.
            key = candidate_id or signal_id or f"unavailable:{len(result)}"
        else:
            key = identity_key[2]
        path = []
        terminal = None
        for order, (gate_name, category) in enumerate(GATE_ORDER, 1):
            if terminal:
                path.append(_gate_row(gate_name, category, None, "unavailable", order) | {"status": "not_evaluated"})
                continue
            rows = observed_rows.get(gate_name)
            row, link = _find_row(candidate, rows, candidates=candidates)
            # Real order-plan rejection reasons are the authority for later gates.
            if gate_name in {"daily_capacity", "low_sample_quota", "strategy_pause"} and rejected_order_plans:
                matching = [r for r in rejected_order_plans if _row_identity(r, candidate) != "unavailable"]
                if matching:
                    row, link = matching[0], _row_identity(matching[0], candidate)
                    row = dict(row)
                    row["approved"] = False
            entry = _gate_row(gate_name, category, row, link, order)
            path.append(entry)
            if entry["status"] == "blocked":
                terminal = gate_name
        decision = "admitted" if identity_key in final_keys else ("blocked" if terminal else "unavailable")
        if decision == "admitted" and not terminal:
            for entry in path:
                if entry["status"] == "unavailable":
                    continue
        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": f"gate_{_hash({'cycle_id': cycle_id, 'candidate_id': candidate_id, 'signal_id': signal_id, 'symbol': item.get('symbol'), 'action': item.get('action')})}",
            "candidate_id": candidate_id,
            "signal_id": signal_id,
            "action": _action(candidate),
            "signal_capture_id": _lineage(candidate).get("signal_capture_id"),
            "cycle_id": cycle_id,
            "identity_status": identity_status,
            "decision_context_snapshot_id": (item.get("decision_context_snapshot") or {}).get("snapshot_id"),
            "market_state_ref_cycle_id": (item.get("decision_context_snapshot") or {}).get("market_state_ref", {}).get("cycle_id"),
            "market_state_ref_hash": (item.get("decision_context_snapshot") or {}).get("market_state_ref", {}).get("content_hash"),
            "market_state_as_of": (item.get("decision_context_snapshot") or {}).get("market_state_ref", {}).get("as_of"),
            "signal_price": item.get("entry_price"),
            "signal_timestamp": (item.get("decision_context_snapshot") or {}).get("captured_at"),
            "forward_horizon": FORWARD_HORIZON,
            "gate_path": path,
            "terminal_gate": terminal,
            "decision": decision,
            "captured_at": captured_at,
            "content_hash": "",
        }
        bad = _contains_post(snapshot)
        if bad:
            raise ValueError(f"post_decision_field:{bad}")
        snapshot["content_hash"] = _hash({k: v for k, v in snapshot.items() if k not in {"captured_at", "content_hash"}})
        result[key] = snapshot
    return result


def validate_gate_snapshot(snapshot: Mapping[str, Any]) -> tuple[bool, str | None]:
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        return False, "invalid_schema_version"
    if _contains_post(snapshot):
        return False, "post_decision_field"
    if not snapshot.get("cycle_id") or snapshot.get("forward_horizon") != FORWARD_HORIZON:
        return False, "identity_or_horizon_missing"
    ref_cycle = snapshot.get("market_state_ref_cycle_id")
    if ref_cycle and str(ref_cycle) != str(snapshot.get("cycle_id")):
        return False, "market_state_cycle_mismatch"
    as_of = snapshot.get("market_state_as_of")
    if as_of and snapshot.get("captured_at"):
        try:
            if datetime.fromisoformat(str(as_of).replace("Z", "+00:00")) > datetime.fromisoformat(str(snapshot["captured_at"]).replace("Z", "+00:00")):
                return False, "market_state_after_capture"
        except ValueError:
            return False, "invalid_market_state_timestamp"
    path = snapshot.get("gate_path")
    if not isinstance(path, list) or len(path) != len(GATE_ORDER):
        return False, "gate_path_incomplete"
    blocked = [x for x in path if x.get("status") == "blocked"]
    if len(blocked) > 1 or (blocked and snapshot.get("terminal_gate") != blocked[0].get("gate_name")):
        return False, "terminal_gate_conflict"
    if blocked:
        first = blocked[0]["order"]
        if any(x.get("status") != "not_evaluated" for x in path if x.get("order", 0) > first):
            return False, "post_block_gate_evaluated"
    return True, None


def derive_gate_outcomes(snapshots: list[Mapping[str, Any]], outcomes_by_signal: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    derived = []
    for snapshot in snapshots:
        signal = str(snapshot.get("signal_id") or "")
        outcome = outcomes_by_signal.get(signal) or {}
        matured = bool((outcome.get("matured_horizons") or {}).get("10d"))
        value = outcome.get("return_10d")
        status = "evaluable" if matured and isinstance(value, (int, float)) else ("immature" if outcome else "unavailable")
        derived.append({"snapshot_id": snapshot.get("snapshot_id"), "signal_id": signal,
                        "status": status, "return_10d": value if status == "evaluable" else None,
                        "terminal_gate": snapshot.get("terminal_gate")})
    return derived


def build_gate_effectiveness_quality(snapshots: list[Mapping[str, Any]], *, start: str | None = None, end: str | None = None, gate: str | None = None, category: str | None = None, outcomes_by_signal: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    selected = [s for s in snapshots if (not start or str(s.get("captured_at", ""))[:10] >= start) and (not end or str(s.get("captured_at", ""))[:10] <= end)]
    rows = [r for s in selected for r in s.get("gate_path", []) if not gate or r.get("gate_name") == gate if not category or r.get("category") == category]
    counts = {"candidates_reaching_gate": len(rows), "evaluated": sum(r.get("status") in {"passed", "blocked"} for r in rows),
              "passed": sum(r.get("status") == "passed" for r in rows), "blocked": sum(r.get("status") == "blocked" for r in rows),
              "not_evaluated": sum(r.get("status") == "not_evaluated" for r in rows), "unavailable": sum(r.get("status") == "unavailable" for r in rows)}
    outcomes = outcomes_by_signal or {}
    derived = derive_gate_outcomes(selected, outcomes)
    maturity = {state: sum(item.get("status") == state for item in derived) for state in ("evaluable", "immature", "unavailable")}
    if not selected:
        status = "collecting"
    elif maturity["evaluable"] == 0:
        status = "immature"
    elif maturity["evaluable"] < 30:
        status = "insufficient_sample"
    else:
        status = "evaluable"
    verified = sum(s.get("identity_status") == "verified" for s in selected)
    context = sum(bool(s.get("decision_context_snapshot_id")) for s in selected)
    categories = {name: sum(row.get("category") == name for row in rows) for name in ("eligibility", "safety", "capacity", "operational", "portfolio")}
    return {"schema_version": SCHEMA_VERSION, "status": status, "snapshots": len(selected), "identity_weak": sum(s.get("identity_status") == "weak" for s in selected), "identity_unavailable": sum(s.get("identity_status") == "unavailable" for s in selected), "identity_coverage": round(verified / len(selected), 6) if selected else None, "context_coverage": round(context / len(selected), 6) if selected else None, "conflicts": 0, "maturity": maturity, "gates": counts, "categories": categories, "warnings": [], "unavailable_by_reason": {}}
