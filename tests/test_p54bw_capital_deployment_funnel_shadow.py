"""Focal contract tests for the P-L54B-W product shadow producer."""

from __future__ import annotations

import copy
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from agente_bolsa.storage import Store
from agente_bolsa.tools.capital_deployment_funnel_shadow import (
    CapitalDeploymentFunnelObserver,
    build_capital_deployment_funnel_shadow,
    capital_deployment_funnel_digest,
    content_hash,
    persist_capital_deployment_funnel_shadow,
    read_capital_deployment_funnel_shadow,
)

CAPTURED = datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc)


def _statuses(*, selection="passed", gates="passed", capacity="passed", sizing="passed", risk="passed", plans="passed", orders="passed", fills="passed"):
    return {
        "selection": selection,
        "gates": gates,
        "capacity": capacity,
        "sizing": sizing,
        "risk": risk,
        "plans": plans,
        "orders": orders,
        "fills": fills,
    }


def _row(index: int, statuses: dict[str, str], *, action: str = "buy") -> dict:
    row = {
        "cycle_id": "cycle-capital",
        "action": action,
        "signal_capture_id": f"capture-{index}",
        "candidate_id": f"candidate-{index}",
        "recommendation_id": f"recommendation-{index}",
        "strategy": "setup-a",
        "setup": "breakout",
        "stage_statuses": statuses,
        "requested_notional": 1500.0,
        "currency": "USD",
        "as_of": "2026-07-27T09:59:00+00:00",
    }
    if statuses.get("gates") == "passed":
        row["gate_eligible_notional"] = 1500.0
    if statuses.get("sizing") == "passed":
        row["sizing_approved_notional"] = 1000.0
    if statuses.get("risk") == "passed":
        row["risk_approved_notional"] = 1000.0
    if statuses.get("plans") == "passed":
        row["plan_id"] = f"plan-{index}"
        row["planned_notional"] = 1000.0
    if statuses.get("orders") == "passed":
        row["broker_order_id"] = f"order-{index}"
        row["submitted_notional"] = 1000.0
        row["order_status"] = "filled" if statuses.get("fills") == "passed" else "pending"
    if statuses.get("fills") == "passed":
        row["filled_notional"] = 1000.0
    return row


def _closed_376() -> list[dict]:
    rows: list[dict] = []
    rows.extend(_row(i, _statuses(selection="rejected", gates="not_generated", capacity="not_generated", sizing="not_generated", risk="not_generated", plans="not_generated", orders="not_generated", fills="not_generated")) for i in range(70))
    rows.extend(_row(70 + i, _statuses(gates="rejected", capacity="not_generated", sizing="not_generated", risk="not_generated", plans="not_generated", orders="not_generated", fills="not_generated")) for i in range(100))
    rows.extend(_row(170 + i, _statuses(gates="unavailable", capacity="not_generated", sizing="not_generated", risk="not_generated", plans="not_generated", orders="not_generated", fills="not_generated")) for i in range(61))
    rows.extend(_row(231 + i, _statuses(capacity="rejected", sizing="not_generated", risk="not_generated", plans="not_generated", orders="not_generated", fills="not_generated")) for i in range(50))
    rows.extend(_row(281 + i, _statuses(risk="rejected", plans="not_generated", orders="not_generated", fills="not_generated")) for i in range(80))
    rows.extend(_row(361 + i, _statuses()) for i in range(15))
    return rows


def test_376_to_15_contract_is_sequential_and_target_is_unavailable() -> None:
    result = build_capital_deployment_funnel_shadow(
        "cycle-capital",
        _closed_376(),
        account={"equity": 100000.0, "cash": 89150.0, "gross_exposure": 0.1085},
        captured_at=CAPTURED,
    )

    assert result["status"] == "verified"
    assert result["invariants"]["valid"] is True
    assert result["denominators"]["candidates_observed"] == 376
    assert result["denominators"]["plans_generated"] == 15
    assert result["stages"]["selection"]["passed_count"] == 306
    assert result["stages"]["gates"]["passed_count"] == 145
    assert result["stages"]["capacity"]["passed_count"] == 95
    assert result["stages"]["risk"]["passed_count"] == 15
    assert result["notional_waterfall"]["requested"]["value"] == 564000.0
    assert result["notional_waterfall"]["gate_eligible"]["value"] == 217500.0
    assert result["notional_waterfall"]["sizing_approved"]["value"] == 95000.0
    assert result["notional_waterfall"]["risk_approved"]["value"] == 15000.0
    assert result["account"]["target_account_exposure"] is None
    assert result["target_exposure_status"] == "unavailable"
    assert sum(result["primary_drop_reason_counts"].values()) == 361


def test_primary_drop_is_exclusive_and_buy_exit_identities_do_not_collide() -> None:
    rows = [_row(1, _statuses(), action="buy"), _row(1, _statuses(), action="exit")]
    result = build_capital_deployment_funnel_shadow("cycle-capital", rows, captured_at=CAPTURED)
    assert result["detail_total"] == 2
    assert result["denominators"]["buy_population_total"] == 1
    assert result["primary_drop_reason_counts"] == {}
    assert {item["action"] for item in result["details"]} == {"buy", "exit"}


def test_missing_identity_and_invalid_numbers_remain_unavailable() -> None:
    row = _row(1, _statuses())
    row["signal_capture_id"] = None
    row["signal_id"] = None
    row["requested_notional"] = float("nan")
    result = build_capital_deployment_funnel_shadow("cycle-capital", [row], captured_at=CAPTURED)
    assert result["denominators"]["canonical_count"] == 0
    assert result["denominators"]["identity_unavailable"] == 1
    assert result["notional_waterfall"]["requested"]["value"] is None


def test_missing_and_conflicting_attachments_count_without_crashing() -> None:
    row = _row(1, _statuses())
    result = build_capital_deployment_funnel_shadow(
        "cycle-capital",
        [row],
        recommendations=[{"cycle_id": "cycle-capital", "action": "buy"}],
        gated_recommendations=[{"cycle_id": "cycle-capital", "action": "buy"}],
        captured_at=CAPTURED,
    )

    assert result["status"] == "partial"
    assert result["attachment_coverage"]["recommendation_attachment_unavailable"] == 1
    assert result["attachment_coverage"]["gate_attachment_unavailable"] == 1
    assert "recommendation_identity_unavailable" in result["warnings"]
    assert "gate_identity_unavailable" in result["warnings"]


def test_conflicting_recommendation_attachment_is_ambiguous_without_crashing() -> None:
    row = _row(1, _statuses())
    row["identity_ambiguous"] = True
    result = build_capital_deployment_funnel_shadow(
        "cycle-capital",
        [row],
        recommendations=[row],
        captured_at=CAPTURED,
    )

    assert result["status"] == "partial"
    assert result["attachment_coverage"]["recommendation_attachment_ambiguous"] == 1
    assert "recommendation_identity_conflict" in result["warnings"]


def test_truncation_preserves_denominators_and_is_compact() -> None:
    rows = [_row(i, _statuses()) for i in range(500)]
    start = time.perf_counter()
    result = build_capital_deployment_funnel_shadow("cycle-capital", rows, captured_at=CAPTURED, detail_limit=500)
    elapsed_ms = (time.perf_counter() - start) * 1000
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert result["detail_total"] == 500
    assert result["detail_persisted"] == 500
    assert result["detail_omitted"] == 0
    assert len(encoded.encode("utf-8")) <= 350000
    assert elapsed_ms < 250

    partial = build_capital_deployment_funnel_shadow("cycle-capital-2", rows, captured_at=CAPTURED, detail_limit=20)
    assert partial["status"] == "partial"
    assert partial["detail_total"] == 500
    assert partial["detail_omitted"] == 480
    assert partial["truncated"] is True


def test_hash_excludes_capture_time_and_persistence_is_append_only(tmp_path) -> None:
    rows = [{**row, "cycle_id": "cycle-persist"} for row in _closed_376()[:2]]
    first = build_capital_deployment_funnel_shadow("cycle-persist", rows, captured_at=CAPTURED)
    second = build_capital_deployment_funnel_shadow(
        "cycle-persist", rows, captured_at=CAPTURED.replace(hour=11)
    )
    assert first["content_hash"] == second["content_hash"]
    assert content_hash(first) == first["content_hash"]

    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    assert persist_capital_deployment_funnel_shadow(store, first)["status"] == "inserted"
    assert persist_capital_deployment_funnel_shadow(store, second)["status"] == "idempotent"
    conflict = copy.deepcopy(second)
    conflict["status"] = "partial"
    conflict["content_hash"] = content_hash(conflict)
    assert persist_capital_deployment_funnel_shadow(store, conflict)["status"] == "conflict"
    read = read_capital_deployment_funnel_shadow(store, "cycle-persist")
    assert read["content_hash"] == first["content_hash"]
    assert capital_deployment_funnel_digest(store, "cycle-persist")["conflict_events"] == 1


def test_observer_is_fail_open_and_does_not_mutate_active_row() -> None:
    row = _row(1, _statuses())
    original = copy.deepcopy(row)
    observer = CapitalDeploymentFunnelObserver("cycle-observer")
    observer.observe(row)
    result = observer.finalize([row], captured_at=CAPTURED)
    assert result["status"] in {"partial", "verified"}
    assert row == original


def test_concurrent_same_event_is_inserted_once_without_lock_error(tmp_path) -> None:
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    payload = build_capital_deployment_funnel_shadow("cycle-concurrent", [_row(1, _statuses())], captured_at=CAPTURED)

    def persist() -> str:
        return persist_capital_deployment_funnel_shadow(store, payload)["status"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(lambda _: persist(), range(2)))
    assert statuses == ["idempotent", "inserted"]
    assert len(store.agent_events(event_type_prefix="capital_deployment_funnel_shadow")) == 1
