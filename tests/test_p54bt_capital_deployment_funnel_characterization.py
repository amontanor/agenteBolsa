"""Caracterizacion aislada del embudo shadow de despliegue de capital.

El contrato vive deliberadamente en tests. No crea Store, tablas, eventos ni
wiring productivo; solo normaliza fixtures con identidad exacta para demostrar
que candidatos, recomendaciones, planes, ordenes y fills son denominadores
distintos.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import math
import time
import tracemalloc
from datetime import datetime, timezone
from typing import Any

import pytest

from agente_bolsa import cycle_runner
from agente_bolsa.tools import trade_decision

SCHEMA_VERSION = "p-l54b.capital-deployment-funnel-shadow.v1"
EVENT_PREFIX = "capital_deployment_funnel:"
DROP_REASONS = {
    "selection_unavailable",
    "gate_rejected",
    "gate_unavailable",
    "risk_rejected",
    "risk_unavailable",
    "quota_duplicate_guard",
    "not_selected",
    "capacity_exhausted",
    "sizing_zero",
    "sizing_unavailable",
    "cap_limited",
    "identity_unavailable",
    "temporal_unavailable",
    "not_generated",
    "execution_rejected_cancelled",
    "not_applicable_exit",
}
STAGE_ORDER = ("selection", "gates", "capacity", "sizing", "risk", "plans", "orders", "fills")


def _as_action(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"buy", "sell", "exit", "reduce"}:
        return "buy" if normalized == "buy" else "exit"
    return None


def _identity(row: dict[str, Any]) -> tuple[str | None, str | None]:
    cycle_id = str(row.get("cycle_id") or "").strip() or None
    action = _as_action(row.get("action"))
    signal_id = str(row.get("signal_capture_id") or row.get("signal_id") or "").strip() or None
    recommendation_id = str(row.get("recommendation_id") or "").strip() or None
    if not cycle_id or not action or not signal_id:
        return None, "identity_unavailable"
    return "|".join((cycle_id, action, signal_id, recommendation_id or "")), None


def _finite_number(value: Any, *, allow_negative: bool = False) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    if not math.isfinite(result) or (not allow_negative and result < 0):
        return None
    return result


def _parse_time(value: Any) -> tuple[datetime | None, str | None]:
    if not value:
        return None, None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None, "invalid_timestamp"
    if parsed.tzinfo is None:
        return None, "naive_timestamp"
    return parsed.astimezone(timezone.utc), None


def _stable_hash(payload: dict[str, Any]) -> str:
    content = copy.deepcopy(payload)
    content.pop("captured_at", None)
    content.pop("content_hash", None)
    encoded = json.dumps(content, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _coverage_sum(
    rows: list[dict[str, Any]],
    field: str,
    *,
    eligible: Any = None,
    currency: str = "USD",
) -> dict[str, Any]:
    eligible_rows = [row for row in rows if eligible is None or eligible(row)]
    values = [_finite_number(row.get(field)) for row in eligible_rows]
    available = [value for value in values if value is not None]
    unavailable_count = len(eligible_rows) - len(available)
    return {
        "value": round(sum(available), 2) if available else None,
        "available_count": len(available),
        "unavailable_count": unavailable_count,
        "denominator_count": len(eligible_rows),
        "currency": currency,
        "status": "complete" if available and not unavailable_count else "partial" if available else "unavailable",
    }


def _derive_stage_path(
    source: dict[str, Any],
    *,
    identity_status: str,
    temporal_status: str | None,
) -> tuple[dict[str, str], str | None]:
    """Derive a structured path from fields produced before each frontier."""

    statuses = {stage: "not_generated" for stage in STAGE_ORDER}
    action = _as_action(source.get("action"))
    if action != "buy":
        return statuses, "not_applicable_exit" if action == "exit" else "identity_unavailable"
    if identity_status != "verified":
        return statuses, "identity_unavailable"
    if temporal_status:
        statuses["selection"] = "unavailable"
        return statuses, "temporal_unavailable"
    if source.get("recommendation_generated") is not True:
        statuses["selection"] = "rejected"
        return statuses, "not_generated"

    selection_status = str(source.get("selection_status") or "").strip().lower()
    if not selection_status:
        selection_status = (
            "selected"
            if source.get("selected_for_llm") is True
            or source.get("decision_source") == "deterministic_capacity_fill"
            else "not_selected"
        )
    if selection_status in {"unavailable", "ambiguous"}:
        statuses["selection"] = "unavailable"
        return statuses, "selection_unavailable"
    if selection_status in {"not_selected", "not_generated"}:
        statuses["selection"] = "rejected" if selection_status == "not_selected" else "not_generated"
        return statuses, "not_selected" if selection_status == "not_selected" else "not_generated"
    statuses["selection"] = "passed"

    gate_status = str(source.get("gate_status") or "").strip().lower()
    if gate_status in {"unavailable", "unknown", ""}:
        statuses["gates"] = "unavailable"
        return statuses, "gate_unavailable"
    if gate_status in {"rejected", "failed"}:
        statuses["gates"] = "rejected"
        return statuses, "gate_rejected"
    statuses["gates"] = "passed"

    if source.get("capacity_exhausted") is True:
        statuses["capacity"] = "rejected"
        return statuses, "capacity_exhausted"
    statuses["capacity"] = "passed"

    sizing_status = str(source.get("sizing_status") or "").strip().lower()
    if sizing_status in {"unavailable", "unknown"}:
        statuses["sizing"] = "unavailable"
        return statuses, "sizing_unavailable"
    if sizing_status == "zero":
        statuses["sizing"] = "rejected"
        return statuses, "sizing_zero"
    if source.get("cap_limited") is True and not source.get("plan_id"):
        statuses["sizing"] = "rejected"
        return statuses, "cap_limited"
    statuses["sizing"] = "passed"

    risk_status = str(source.get("risk_status") or "").strip().lower()
    if risk_status in {"unavailable", "unknown", ""}:
        statuses["risk"] = "unavailable"
        return statuses, "risk_unavailable"
    if risk_status in {"rejected", "failed"}:
        statuses["risk"] = "rejected"
        return statuses, "risk_rejected"
    if risk_status != "approved":
        statuses["risk"] = "unavailable"
        return statuses, "risk_unavailable"
    statuses["risk"] = "passed"

    if not source.get("plan_id"):
        return statuses, "not_generated"
    statuses["plans"] = "passed"

    order = source.get("order") or {}
    if not order.get("broker_order_id"):
        return statuses, "not_generated"
    statuses["orders"] = "passed"
    order_status = str(order.get("status") or "").strip().lower()
    if order_status in {"rejected", "cancelled"}:
        statuses["fills"] = "rejected"
        return statuses, "execution_rejected_cancelled"
    if order_status in {"filled", "partially_filled"}:
        statuses["fills"] = "passed"
        return statuses, None
    if order_status == "pending":
        statuses["fills"] = "pending"
        return statuses, None
    statuses["fills"] = "unavailable"
    return statuses, "execution_unavailable"


def _normalise_row(row: dict[str, Any], *, as_of: datetime) -> dict[str, Any]:
    source = copy.deepcopy(row)
    identity_key, identity_reason = _identity(source)
    warnings: list[str] = []
    times: list[datetime] = []
    for field in ("cycle_started_at", "decision_at", "plan_at", "submitted_at", "filled_at"):
        parsed, reason = _parse_time(source.get(field))
        if reason:
            warnings.append(f"{field}:{reason}")
        if parsed is not None:
            times.append(parsed)
    if times != sorted(times):
        warnings.append("timestamps_inverted")
    if any(value > as_of for value in times):
        warnings.append("timestamp_in_future")
    temporal_status = "temporal_unavailable" if warnings else None

    normalised = {
        "identity_key": identity_key,
        "identity_status": "unavailable" if identity_reason else "verified",
        "candidate_id": source.get("candidate_id"),
        "cycle_id": source.get("cycle_id"),
        "action": _as_action(source.get("action")),
        "signal_capture_id": source.get("signal_capture_id"),
        "signal_id": source.get("signal_id"),
        "recommendation_id": source.get("recommendation_id"),
        "candidate_id_auxiliary": source.get("candidate_id"),
        "strategy": source.get("strategy"),
        "setup": source.get("setup"),
        "decision_source": source.get("decision_source"),
        "technical_eligible": source.get("technical_eligible"),
        "recommendation_generated": source.get("recommendation_generated"),
        "selection_status": source.get("selection_status"),
        "selected_for_llm": source.get("selected_for_llm"),
        "llm_considered": source.get("llm_considered"),
        "gate_status": source.get("gate_status"),
        "risk_status": source.get("risk_status"),
        "plan_id": source.get("plan_id"),
        "order": source.get("order"),
        "sizing": source.get("sizing") or {},
        "sizing_status": source.get("sizing_status"),
        "reason_codes": sorted({str(item) for item in source.get("reason_codes") or []}),
        "warnings": sorted(set(warnings)),
    }
    for field in (
        "requested_notional",
        "gate_eligible_notional",
        "risk_approved_notional",
        "sizing_approved_notional",
        "planned_notional",
        "submitted_notional",
        "filled_notional",
    ):
        value = _finite_number(source.get(field))
        normalised[field] = value
        if source.get(field) is not None and value is None:
            normalised["warnings"].append(f"{field}:invalid_numeric")
    normalised["cap_limited"] = source.get("cap_limited") is True
    normalised["capacity_exhausted"] = source.get("capacity_exhausted") is True
    normalised["not_generated"] = source.get("not_generated") is True
    stage_statuses, primary_drop_reason = _derive_stage_path(
        normalised,
        identity_status=normalised["identity_status"],
        temporal_status=temporal_status,
    )
    normalised["stage_statuses"] = stage_statuses
    normalised["primary_drop_reason"] = primary_drop_reason
    all_reasons = set(normalised["reason_codes"])
    if temporal_status:
        all_reasons.add(temporal_status)
    if identity_reason:
        all_reasons.add(identity_reason)
    normalised["secondary_reasons"] = sorted(
        reason for reason in all_reasons if reason != normalised["primary_drop_reason"]
    )
    return normalised


def _build_stage_counts(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    buy_rows = [row for row in rows if row.get("action") == "buy"]
    population_total = len(buy_rows)
    identity_unavailable = sum(row["identity_status"] != "verified" for row in buy_rows)
    output: dict[str, dict[str, int]] = {}
    for stage in STAGE_ORDER:
        statuses = [
            row["stage_statuses"][stage]
            for row in buy_rows
            if row["identity_status"] == "verified"
        ]
        reached = sum(status != "not_generated" for status in statuses)
        passed = sum(status == "passed" for status in statuses)
        rejected = sum(status == "rejected" for status in statuses)
        unavailable = sum(status == "unavailable" for status in statuses)
        pending = sum(status == "pending" for status in statuses)
        not_generated = sum(status == "not_generated" for status in statuses)
        output[stage] = {
            "population_total": population_total,
            "reached_count": reached,
            "evaluated_count": reached,
            "passed_count": passed,
            "approved_count": passed,
            "passed_or_approved_count": passed,
            "rejected_count": rejected,
            "unavailable_count": unavailable,
            "not_generated_count": not_generated,
            "identity_unavailable_count": identity_unavailable,
            "pending_count": pending,
        }
    return output


def _evaluate_invariants(result: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    stages = result["stages"]
    population_total = result["denominators"]["buy_population_total"]
    for index, stage in enumerate(STAGE_ORDER):
        counts = stages[stage]
        partition = (
            counts["passed_or_approved_count"]
            + counts["rejected_count"]
            + counts["unavailable_count"]
            + counts["pending_count"]
            + counts["not_generated_count"]
            + counts["identity_unavailable_count"]
        )
        if partition != population_total:
            errors.append(f"{stage}:partition={partition}!={population_total}")
        if index and counts["reached_count"] > stages[STAGE_ORDER[index - 1]]["passed_or_approved_count"]:
            errors.append(f"{stage}:reached_exceeds_previous_passed")

    buy_rows = [row for row in result["candidate_rows"] if row.get("action") == "buy"]
    primary_counts = {reason: 0 for reason in DROP_REASONS}
    success_count = 0
    for row in buy_rows:
        reason = row.get("primary_drop_reason")
        if reason is None:
            success_count += 1
        elif reason in primary_counts:
            primary_counts[reason] += 1
        else:
            errors.append(f"unknown_primary_reason:{reason}")
        stage_values = list(row["stage_statuses"].values())
        if sum(value == "rejected" for value in stage_values) > 1:
            errors.append(f"multiple_rejected_stages:{row['identity_key']}")
        if sum(value == "unavailable" for value in stage_values) > 1:
            errors.append(f"multiple_unavailable_stages:{row['identity_key']}")
        if (
            sum(value == "not_generated" for value in stage_values) == 0
            and reason is not None
            and reason != "execution_rejected_cancelled"
        ):
            errors.append(f"drop_without_downstream_not_generated:{row['identity_key']}")

    if success_count + sum(primary_counts.values()) != population_total:
        errors.append("terminal_partition_does_not_close_buy_population")
    denoms = result["denominators"]
    if denoms["plans_generated"] > stages["risk"]["passed_or_approved_count"]:
        errors.append("plans_exceed_risk_approved")
    if denoms["orders_submitted"] > denoms["plans_generated"]:
        errors.append("orders_exceed_plans")
    order_partition = (
        denoms["orders_filled"]
        + denoms["orders_rejected"]
        + denoms["orders_cancelled"]
        + denoms["orders_pending"]
        + denoms["orders_unavailable"]
    )
    if order_partition != denoms["orders_submitted"]:
        errors.append("orders_are_not_partitioned")
    return {
        "valid": not errors,
        "errors": errors,
        "terminal_partition": {
            "success_count": success_count,
            "primary_drop_count": sum(primary_counts.values()),
            "buy_population_total": population_total,
        },
    }


def characterize_funnel(
    rows: list[dict[str, Any]],
    *,
    cycle_id: str,
    account: dict[str, Any],
    as_of: str,
    captured_at: str = "2026-07-27T08:00:00+00:00",
    raw_count: int | None = None,
    truncated_count: int = 0,
) -> dict[str, Any]:
    as_of_dt, as_of_reason = _parse_time(as_of)
    if as_of_dt is None:
        raise ValueError(f"invalid as_of: {as_of_reason}")
    normalised = [_normalise_row(row, as_of=as_of_dt) for row in rows]
    normalised.sort(key=lambda item: item.get("identity_key") or "")
    buy_rows = [row for row in normalised if row.get("action") == "buy"]
    stage_counts = _build_stage_counts(normalised)
    denoms = {
        "raw_count": raw_count if raw_count is not None else len(rows),
        "canonical_count": len([row for row in normalised if row["identity_status"] == "verified"]),
        "identity_unavailable": len([row for row in normalised if row["identity_status"] != "verified"]),
        "buy_population_total": len(buy_rows),
        "buy_identity_unavailable": sum(row["identity_status"] != "verified" for row in buy_rows),
        "technically_eligible": sum(row.get("technical_eligible") is True for row in buy_rows),
        "recommendations_generated": sum(row.get("recommendation_generated") is True for row in buy_rows),
        "llm_selected": sum(row.get("selected_for_llm") is True for row in buy_rows),
        "llm_considered": sum(row.get("llm_considered") is True for row in buy_rows),
        "deterministic_capacity_fill": sum(row.get("decision_source") == "deterministic_capacity_fill" for row in buy_rows),
        "gates_evaluated": stage_counts["gates"]["evaluated_count"],
        "gates_passed": stage_counts["gates"]["passed_count"],
        "gates_rejected": stage_counts["gates"]["rejected_count"],
        "gates_unavailable": stage_counts["gates"]["unavailable_count"],
        "risk_approved": stage_counts["risk"]["approved_count"],
        "risk_rejected": stage_counts["risk"]["rejected_count"],
        "risk_unavailable": stage_counts["risk"]["unavailable_count"],
        "plans_generated": stage_counts["plans"]["passed_count"],
        "orders_submitted": stage_counts["orders"]["passed_count"],
        "orders_filled": stage_counts["fills"]["passed_count"],
        "orders_rejected": sum((row.get("order") or {}).get("status") == "rejected" for row in buy_rows),
        "orders_cancelled": sum((row.get("order") or {}).get("status") == "cancelled" for row in buy_rows),
        "orders_pending": sum((row.get("order") or {}).get("status") == "pending" for row in buy_rows),
        "orders_unavailable": stage_counts["fills"]["unavailable_count"],
    }
    reason_counts = {reason: 0 for reason in sorted(DROP_REASONS)}
    for row in normalised:
        if row["primary_drop_reason"] in reason_counts:
            reason_counts[row["primary_drop_reason"]] += 1
    account_fields = (
        "account_equity",
        "cash",
        "buying_power",
        "gross_exposure_pct",
        "net_exposure_pct",
        "target_account_exposure",
        "configured_min_exposure",
        "configured_max_exposure",
    )
    account_output: dict[str, Any] = {}
    for field in account_fields:
        value = _finite_number(account.get(field), allow_negative=field.endswith("exposure_pct"))
        account_output[field] = value
    warnings = sorted({warning for row in normalised for warning in row["warnings"]})
    if account_output["target_account_exposure"] is None:
        warnings.append("target_account_exposure_unavailable")
    status = "partial" if truncated_count or warnings or denoms["identity_unavailable"] else "verified"
    result = {
        "schema_version": SCHEMA_VERSION,
        "event_id": f"{EVENT_PREFIX}{cycle_id}",
        "cycle_id": cycle_id,
        "as_of": as_of,
        "captured_at": captured_at,
        "status": status,
        "coverage": {
            "raw_count": denoms["raw_count"],
            "captured_count": len(normalised),
            "truncated_count": truncated_count,
            "is_complete_universe": truncated_count == 0 and denoms["raw_count"] == len(normalised),
        },
        "denominators": denoms,
        "account": account_output,
        "stages": stage_counts,
        "notional_waterfall": {
            "requested_notional": _coverage_sum(buy_rows, "requested_notional"),
            "gate_eligible_notional": _coverage_sum(
                buy_rows,
                "gate_eligible_notional",
                eligible=lambda row: row["stage_statuses"]["gates"] == "passed",
            ),
            "risk_approved_notional": _coverage_sum(
                buy_rows,
                "risk_approved_notional",
                eligible=lambda row: row["stage_statuses"]["risk"] == "passed",
            ),
            "sizing_approved_notional": _coverage_sum(
                buy_rows,
                "sizing_approved_notional",
                eligible=lambda row: row["stage_statuses"]["sizing"] == "passed",
            ),
            "planned_notional": _coverage_sum(
                buy_rows,
                "planned_notional",
                eligible=lambda row: row["stage_statuses"]["plans"] == "passed",
            ),
            "submitted_notional": _coverage_sum(
                buy_rows,
                "submitted_notional",
                eligible=lambda row: row["stage_statuses"]["orders"] == "passed",
            ),
            "filled_notional": _coverage_sum(
                buy_rows,
                "filled_notional",
                eligible=lambda row: row["stage_statuses"]["fills"] == "passed",
            ),
        },
        "primary_drop_reason_counts": reason_counts,
        "candidate_rows": normalised,
        "warnings": sorted(set(warnings)),
        "reason_codes": sorted(set(warnings) | {"target_exposure_unavailable"} if account_output["target_account_exposure"] is None else set(warnings)),
    }
    result["invariants"] = _evaluate_invariants(result)
    result["content_hash"] = _stable_hash(result)
    return result


def append_only_result(existing: dict[str, dict[str, Any]], incoming: dict[str, Any]) -> dict[str, Any]:
    event_id = str(incoming["event_id"])
    previous = existing.get(event_id)
    if previous is None:
        existing[event_id] = copy.deepcopy(incoming)
        return {"status": "inserted", "event_id": event_id}
    if _stable_hash(previous) == _stable_hash(incoming):
        return {"status": "idempotent", "event_id": event_id}
    return {"status": "conflict", "event_id": event_id, "original_intact": True}


def _row(index: int, *, action: str = "buy", planned: bool = False) -> dict[str, Any]:
    plan_id = f"plan:{index}" if planned else None
    order_status = "filled" if planned else None
    return {
        "cycle_id": "cycle-capital",
        "session_date": "2026-07-21",
        "signal_capture_id": f"capture:cycle-capital:{action}:{index}",
        "signal_id": f"signal:cycle-capital:{action}:{index}",
        "candidate_id": f"candidate:{index}",
        "recommendation_id": f"recommendation:{index}",
        "action": action,
        "strategy": "builtin_breakout",
        "setup": "continuation",
        "decision_source": "llm" if index % 3 == 0 else "deterministic_capacity_fill",
        "technical_eligible": True,
        "recommendation_generated": True,
        "selection_status": "selected",
        "selected_for_llm": index < 15,
        "llm_considered": index < 15,
        "gate_status": "passed" if planned else "rejected",
        "risk_status": "approved" if planned else "rejected",
        "plan_id": plan_id,
        "order": {"broker_order_id": f"broker:{index}", "status": order_status} if planned else None,
        "requested_notional": 1500.0,
        "gate_eligible_notional": 1500.0,
        "risk_approved_notional": 1000.0 if planned else None,
        "sizing_approved_notional": 1000.0 if planned else None,
        "planned_notional": 1000.0 if planned else None,
        "submitted_notional": 1000.0 if planned else None,
        "filled_notional": 1000.0 if planned else None,
        "sizing": {"base_risk_size": 1000.0, "micro_experiment_multiplier": 0.5, "per_order_cap": 1000.0},
        "reason_codes": [] if planned else ["risk_rejected"],
    }


def _large_fixture() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = []
    for index in range(376):
        row = _row(index, planned=index < 15)
        if 15 <= index < 85:
            row.update({"selection_status": "not_selected", "gate_status": None, "risk_status": None, "reason_codes": ["not_selected"]})
        elif 85 <= index < 135:
            row.update({"capacity_exhausted": True, "gate_status": "passed", "risk_status": None, "reason_codes": ["quota"]})
        elif 135 <= index < 196:
            row.update({"gate_status": "unavailable", "risk_status": None, "reason_codes": ["gate_unavailable"]})
        elif 196 <= index < 296:
            row.update({"gate_status": "rejected", "risk_status": None, "reason_codes": ["gate_rejected"]})
        elif index >= 296:
            row.update({"gate_status": "passed", "risk_status": "rejected", "sizing_approved_notional": 1000.0, "reason_codes": ["risk_rejected"]})
        rows.append(row)
    account = {
        "account_equity": 100000.0,
        "cash": 89150.0,
        "buying_power": None,
        "gross_exposure_pct": 0.1085,
        "net_exposure_pct": 0.1085,
        # Intentionally absent: no structured authority in the real producer.
    }
    return rows, account


def test_376_recommendations_15_plans_15_fills_keep_denominators_and_target_null() -> None:
    rows, account = _large_fixture()
    result = characterize_funnel(
        rows,
        cycle_id="cycle-capital",
        account=account,
        as_of="2026-07-21T20:00:00+00:00",
    )
    assert result["status"] == "partial"
    assert result["denominators"]["raw_count"] == 376
    assert result["denominators"]["canonical_count"] == 376
    assert result["denominators"]["recommendations_generated"] == 376
    assert result["denominators"]["gates_evaluated"] == 306
    assert result["denominators"]["gates_passed"] == 145
    assert result["denominators"]["gates_rejected"] == 100
    assert result["denominators"]["gates_unavailable"] == 61
    assert result["denominators"]["risk_approved"] == 15
    assert result["denominators"]["risk_rejected"] == 80
    assert result["denominators"]["risk_unavailable"] == 0
    assert result["denominators"]["plans_generated"] == 15
    assert result["denominators"]["orders_submitted"] == 15
    assert result["denominators"]["orders_filled"] == 15
    assert result["account"]["gross_exposure_pct"] == 0.1085
    assert result["account"]["target_account_exposure"] is None
    assert result["notional_waterfall"]["risk_approved_notional"]["value"] == 15000.0
    assert result["notional_waterfall"]["risk_approved_notional"]["available_count"] == 15
    assert result["notional_waterfall"]["risk_approved_notional"]["denominator_count"] == 15
    assert result["notional_waterfall"]["gate_eligible_notional"]["value"] == 217500.0
    assert result["notional_waterfall"]["gate_eligible_notional"]["denominator_count"] == 145
    assert result["notional_waterfall"]["sizing_approved_notional"]["value"] == 95000.0
    assert result["notional_waterfall"]["sizing_approved_notional"]["denominator_count"] == 95
    assert result["notional_waterfall"]["filled_notional"]["value"] == 15000.0
    assert result["invariants"]["valid"] is True
    assert result["invariants"]["terminal_partition"] == {
        "success_count": 15,
        "primary_drop_count": 361,
        "buy_population_total": 376,
    }
    assert "target_account_exposure_unavailable" in result["reason_codes"]


def test_previous_p54b_snapshot_counts_are_rejected() -> None:
    previous = {
        "buy_population_total": 376,
        "gates_passed": 135,
        "risk_approved": 135,
        "risk_rejected": 80,
        "risk_unavailable": 0,
        "risk_approved_notional_available_count": 135,
        "plans_generated": 15,
    }
    with pytest.raises(AssertionError):
        assert previous["risk_approved"] + previous["risk_rejected"] + previous["risk_unavailable"] <= previous["gates_passed"]
    with pytest.raises(AssertionError):
        assert previous["risk_approved_notional_available_count"] == previous["plans_generated"]


def test_stage_transition_table_is_monotonic_and_closes_exactly() -> None:
    rows, account = _large_fixture()
    result = characterize_funnel(rows, cycle_id="cycle-capital", account=account, as_of="2026-07-21T20:00:00+00:00")
    expected = {
        "selection": (376, 306, 70, 0, 0),
        "gates": (306, 145, 100, 61, 70),
        "capacity": (145, 95, 50, 0, 231),
        "sizing": (95, 95, 0, 0, 281),
        "risk": (95, 15, 80, 0, 281),
        "plans": (15, 15, 0, 0, 361),
        "orders": (15, 15, 0, 0, 361),
        "fills": (15, 15, 0, 0, 361),
    }
    for stage, (reached, passed, rejected, unavailable, not_generated) in expected.items():
        counts = result["stages"][stage]
        assert counts["reached_count"] == reached
        assert counts["passed_or_approved_count"] == passed
        assert counts["rejected_count"] == rejected
        assert counts["unavailable_count"] == unavailable
        assert counts["not_generated_count"] == not_generated
    assert result["invariants"]["valid"] is True


@pytest.mark.parametrize("terminal", [
    "not_selected",
    "capacity_exhausted",
    "gate_rejected",
    "gate_unavailable",
    "risk_rejected",
    "risk_unavailable",
    "sizing_zero",
    "cap_limited",
    "not_generated",
    "execution_rejected_cancelled",
])
def test_structured_terminal_paths_preserve_monotonicity(terminal: str) -> None:
    row = _row(1, planned=terminal == "execution_rejected_cancelled")
    if terminal == "not_selected":
        row.update({"selection_status": "not_selected", "gate_status": None, "risk_status": None, "plan_id": None, "order": None})
    elif terminal == "capacity_exhausted":
        row.update({"capacity_exhausted": True, "gate_status": "passed", "risk_status": None, "plan_id": None, "order": None})
    elif terminal == "gate_rejected":
        row.update({"gate_status": "rejected", "risk_status": None, "plan_id": None, "order": None})
    elif terminal == "gate_unavailable":
        row.update({"gate_status": "unavailable", "risk_status": None, "plan_id": None, "order": None})
    elif terminal == "risk_rejected":
        row.update({"gate_status": "passed", "risk_status": "rejected", "plan_id": None, "order": None})
    elif terminal == "risk_unavailable":
        row.update({"gate_status": "passed", "risk_status": "unavailable", "plan_id": None, "order": None})
    elif terminal == "sizing_zero":
        row.update({"gate_status": "passed", "risk_status": "approved", "sizing_status": "zero", "plan_id": None, "order": None})
    elif terminal == "cap_limited":
        row.update({"gate_status": "passed", "risk_status": "approved", "cap_limited": True, "plan_id": None, "order": None})
    elif terminal == "not_generated":
        row.update({"recommendation_generated": False, "plan_id": None, "order": None})
    elif terminal == "execution_rejected_cancelled":
        row["order"]["status"] = "rejected"
    result = characterize_funnel([row], cycle_id="cycle-capital", account={}, as_of="2026-07-21T20:00:00+00:00")
    assert result["invariants"]["valid"] is True, result["invariants"]["errors"]
    assert result["candidate_rows"][0]["primary_drop_reason"] == terminal


def test_gate_passed_risk_unavailable_and_partial_notional_are_separate() -> None:
    row = _row(1)
    row.update({"gate_status": "passed", "risk_status": "unavailable", "plan_id": None, "order": None})
    result = characterize_funnel([row], cycle_id="cycle-capital", account={}, as_of="2026-07-21T20:00:00+00:00")
    assert result["denominators"]["gates_passed"] == 1
    assert result["denominators"]["risk_unavailable"] == 1
    assert result["denominators"]["plans_generated"] == 0
    assert result["notional_waterfall"]["risk_approved_notional"]["status"] == "unavailable"
    assert result["invariants"]["valid"] is True


def test_identity_unavailable_is_not_an_evaluable_stage() -> None:
    row = _row(1)
    row["signal_capture_id"] = None
    row["signal_id"] = None
    result = characterize_funnel([row], cycle_id="cycle-capital", account={}, as_of="2026-07-21T20:00:00+00:00")
    assert result["denominators"]["buy_identity_unavailable"] == 1
    assert result["stages"]["gates"]["identity_unavailable_count"] == 1
    assert result["stages"]["gates"]["reached_count"] == 0
    assert result["invariants"]["valid"] is True


def test_primary_reason_is_exclusive_and_secondary_reasons_do_not_double_count() -> None:
    rows = [_row(1), _row(2)]
    rows[0].update({"gate_status": "rejected", "risk_status": "rejected", "reason_codes": ["quota", "risk_rejected"]})
    rows[1].update({"gate_status": "passed", "risk_status": "approved", "capacity_exhausted": True, "reason_codes": ["quota", "not_selected"]})
    result = characterize_funnel(rows, cycle_id="cycle-capital", account={}, as_of="2026-07-21T20:00:00+00:00")
    counts = result["primary_drop_reason_counts"]
    assert counts["gate_rejected"] == 1
    assert counts["capacity_exhausted"] == 1
    assert sum(counts.values()) == 2
    assert result["candidate_rows"][0]["primary_drop_reason"] in DROP_REASONS
    assert result["candidate_rows"][0]["secondary_reasons"]


def test_buy_exit_same_signal_and_rebuys_are_distinct_without_symbol_join() -> None:
    buy = _row(1, action="buy", planned=True)
    exit_row = _row(1, action="exit", planned=False)
    rebuy = _row(2, action="buy", planned=True)
    for row in (buy, exit_row, rebuy):
        row["symbol"] = "AAA"
    rebuy["source_plan_id"] = "source-plan-rebuy"
    result = characterize_funnel(
        [buy, exit_row, rebuy],
        cycle_id="cycle-capital",
        account={},
        as_of="2026-07-21T20:00:00+00:00",
    )
    keys = [row["identity_key"] for row in result["candidate_rows"]]
    assert len(set(keys)) == 3
    assert result["denominators"]["orders_filled"] == 2
    assert all("AAA" not in key for key in keys)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1.0, True, "bad"])
def test_invalid_notionals_and_temporal_values_remain_unavailable(invalid: Any) -> None:
    row = _row(1, planned=True)
    row["requested_notional"] = invalid
    row["decision_at"] = "2026-07-21T14:00:00"
    row["filled_at"] = "2026-07-22T14:00:00+00:00"
    result = characterize_funnel(
        [row],
        cycle_id="cycle-capital",
        account={},
        as_of="2026-07-21T20:00:00+00:00",
    )
    normalised = result["candidate_rows"][0]
    assert normalised["requested_notional"] is None
    assert normalised["primary_drop_reason"] == "temporal_unavailable"
    assert result["notional_waterfall"]["requested_notional"]["status"] == "unavailable"


def test_missing_plan_order_statuses_are_separate_and_exit_not_buy_drop() -> None:
    recommendation_only = _row(1)
    recommendation_only.update({"gate_status": "passed", "risk_status": "approved", "plan_id": None, "selected_for_llm": True})
    pending = _row(2, planned=True)
    pending["order"]["status"] = "pending"
    pending["filled_notional"] = None
    rejected = _row(3, planned=True)
    rejected["order"]["status"] = "rejected"
    exit_row = _row(4, action="exit")
    exit_row.update({"gate_status": None, "risk_status": None, "reason_codes": []})
    result = characterize_funnel(
        [recommendation_only, pending, rejected, exit_row],
        cycle_id="cycle-capital",
        account={},
        as_of="2026-07-21T20:00:00+00:00",
    )
    assert result["denominators"]["plans_generated"] == 2
    assert result["denominators"]["orders_pending"] == 1
    assert result["denominators"]["orders_rejected"] == 1
    assert result["candidate_rows"][-1]["primary_drop_reason"] == "not_applicable_exit"


def test_hash_captured_at_excluded_and_conflict_preserves_original() -> None:
    rows, account = _large_fixture()
    first = characterize_funnel(rows[:2], cycle_id="cycle-capital", account=account, as_of="2026-07-21T20:00:00+00:00", captured_at="2026-07-27T08:00:00+00:00")
    repeated = copy.deepcopy(first)
    repeated["captured_at"] = "2026-07-27T08:01:00+00:00"
    assert first["content_hash"] == repeated["content_hash"]
    existing: dict[str, dict[str, Any]] = {}
    assert append_only_result(existing, first)["status"] == "inserted"
    assert append_only_result(existing, repeated)["status"] == "idempotent"
    changed = copy.deepcopy(first)
    changed["account"]["gross_exposure_pct"] = 0.2
    changed["content_hash"] = _stable_hash(changed)
    assert append_only_result(existing, changed)["status"] == "conflict"
    assert existing[first["event_id"]]["account"]["gross_exposure_pct"] == 0.1085


def test_truncation_preserves_total_and_marks_partial_not_complete() -> None:
    rows = [_row(index, planned=index < 2) for index in range(20)]
    result = characterize_funnel(
        rows,
        cycle_id="cycle-capital",
        account={},
        as_of="2026-07-21T20:00:00+00:00",
        raw_count=500,
        truncated_count=480,
    )
    assert result["status"] == "partial"
    assert result["coverage"] == {
        "raw_count": 500,
        "captured_count": 20,
        "truncated_count": 480,
        "is_complete_universe": False,
    }
    assert result["denominators"]["raw_count"] == 500
    assert result["denominators"]["canonical_count"] == 20


def test_no_mutation_and_bounded_500_candidate_fixture() -> None:
    rows = [_row(index, planned=index < 20) for index in range(500)]
    original = copy.deepcopy(rows)
    tracemalloc.start()
    started = time.perf_counter()
    result = characterize_funnel(
        rows,
        cycle_id="cycle-volume",
        account={"gross_exposure_pct": 0.1085},
        as_of="2026-07-21T20:00:00+00:00",
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    encoded_bytes = len(json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    print(
        "P-L54BT_VOLUME "
        + json.dumps(
            {"candidates": 500, "elapsed_ms": round(elapsed_ms, 3), "peak_bytes": peak_bytes, "event_bytes": encoded_bytes},
            sort_keys=True,
        )
    )
    assert rows == original
    assert result["denominators"]["raw_count"] == 500
    assert result["denominators"]["plans_generated"] == 20
    assert elapsed_ms < 5000


def test_real_producer_trace_has_exact_boundaries_and_no_target_invention() -> None:
    plans_source = inspect.getsource(trade_decision.build_buy_order_plans)
    cycle_source = inspect.getsource(cycle_runner._auto_paper_trade)
    assert "RiskManager(settings)" in plans_source
    assert "risk_manager.validate_order" in plans_source
    assert "planned_buy_symbols" in plans_source
    assert "learning_notional_cap" in plans_source
    assert "save_order_plan" in cycle_source
    assert "save_broker_order" in cycle_source
    assert "target_account_exposure" not in plans_source
    assert "target_account_exposure" not in cycle_source
    assert "symbol" in plans_source  # descriptive input exists, not an identity join.
