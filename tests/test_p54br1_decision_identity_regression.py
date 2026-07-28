"""Regression characterization for P-L54B decision identity."""

from __future__ import annotations

from datetime import datetime, timezone

from agente_bolsa.tools.capital_deployment_funnel_shadow import (
    build_capital_deployment_funnel_shadow,
)

CAPTURED = datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc)


def _row(
    *,
    recommendation_id: str | None = "rec-a",
    action: str = "buy",
    cycle_id: str = "cycle-identity",
    signal_capture_id: str | None = "capture-1",
    candidate_id: str | None = "candidate-1",
    plan_id: str | None = "plan-1",
    requested_notional: float = 1000.0,
) -> dict[str, object]:
    return {
        "cycle_id": cycle_id,
        "action": action,
        "signal_capture_id": signal_capture_id,
        "candidate_id": candidate_id,
        "recommendation_id": recommendation_id,
        "plan_id": plan_id,
        "broker_order_id": f"order-{recommendation_id or candidate_id}",
        "order_status": "filled",
        "stage_statuses": {
            "selection": "passed",
            "gates": "passed",
            "capacity": "passed",
            "sizing": "passed",
            "risk": "passed",
            "plans": "passed",
            "orders": "passed",
            "fills": "passed",
        },
        "requested_notional": requested_notional,
        "gate_eligible_notional": requested_notional,
        "sizing_approved_notional": requested_notional,
        "risk_approved_notional": requested_notional,
        "planned_notional": requested_notional,
        "submitted_notional": requested_notional,
        "filled_notional": requested_notional,
        "as_of": "2026-07-27T09:59:00+00:00",
    }


def test_distinct_recommendations_same_signal_are_distinct_decisions() -> None:
    first = _row(recommendation_id="rec-a", plan_id="plan-a")
    second = _row(recommendation_id="rec-b", plan_id="plan-b")

    result = build_capital_deployment_funnel_shadow("cycle-identity", [first, second], captured_at=CAPTURED)

    assert result["detail_total"] == 2
    assert result["denominators"]["decision_identity_verified"] == 2
    assert {item["recommendation_id"] for item in result["details"]} == {"rec-a", "rec-b"}


def test_same_recommendation_incompatible_content_is_a_conflict() -> None:
    first = _row(recommendation_id="rec-a", plan_id="plan-a", requested_notional=1000.0)
    second = _row(recommendation_id="rec-a", plan_id="plan-b", requested_notional=900.0)

    result = build_capital_deployment_funnel_shadow("cycle-identity", [first, second], captured_at=CAPTURED)

    assert result["denominators"]["decision_identity_ambiguous"] == 2
    assert result["denominators"]["conflict_count"] == 1
    assert result["invariants"]["excluded_identity_count"] == 2
    assert result["notional_waterfall"]["planned"]["value"] is None


def test_same_recommendation_identical_content_is_idempotent() -> None:
    row = _row(recommendation_id="rec-a", plan_id="plan-a")

    result = build_capital_deployment_funnel_shadow("cycle-identity", [row, dict(row)], captured_at=CAPTURED)

    assert result["detail_total"] == 1
    assert result["denominators"]["decision_identity_verified"] == 1
    assert result["denominators"]["conflict_count"] == 0


def test_candidate_id_does_not_create_a_second_decision() -> None:
    first = _row(recommendation_id="rec-a", candidate_id="candidate-a")
    second = _row(recommendation_id="rec-a", candidate_id="candidate-b")

    result = build_capital_deployment_funnel_shadow("cycle-identity", [first, second], captured_at=CAPTURED)

    assert result["denominators"]["decision_identity_ambiguous"] == 2
    assert result["detail_total"] == 2


def test_missing_recommendation_is_partial_and_repeated_partial_is_ambiguous() -> None:
    single = _row(recommendation_id=None, candidate_id="candidate-single", plan_id=None)
    result = build_capital_deployment_funnel_shadow("cycle-identity", [single], captured_at=CAPTURED)
    assert result["denominators"]["decision_identity_partial"] == 1
    assert result["denominators"]["recommendation_id_unavailable"] == 1

    first = _row(recommendation_id=None, candidate_id="candidate-a", plan_id=None)
    second = _row(recommendation_id=None, candidate_id="candidate-b", plan_id=None)
    ambiguous = build_capital_deployment_funnel_shadow("cycle-identity", [first, second], captured_at=CAPTURED)
    assert ambiguous["denominators"]["decision_identity_ambiguous"] == 2


def test_plan_without_recommendation_is_not_attached_by_signal() -> None:
    candidate = _row(recommendation_id="rec-a", plan_id=None)
    candidate["stage_statuses"] = {
        **candidate["stage_statuses"],
        "plans": "not_generated",
        "orders": "not_generated",
        "fills": "not_generated",
    }
    plan_without_recommendation = {
        "cycle_id": "cycle-identity",
        "action": "buy",
        "signal_capture_id": "capture-1",
        "plan_id": "plan-without-decision-id",
        "planned_notional": 1000.0,
    }

    result = build_capital_deployment_funnel_shadow(
        "cycle-identity",
        [candidate],
        plans=[plan_without_recommendation],
        captured_at=CAPTURED,
    )

    assert result["denominators"]["plans_generated"] == 0
    assert result["denominators"]["plan_attachment_verified"] == 0
    assert result["denominators"]["plan_attachment_unavailable"] == 1


def test_action_and_candidate_do_not_replace_decision_identity() -> None:
    buy = _row(recommendation_id="rec-a", action="buy", candidate_id="candidate-a", plan_id="plan-a")
    exit_row = _row(recommendation_id="rec-a", action="exit", candidate_id="candidate-b", plan_id="plan-exit")
    result = build_capital_deployment_funnel_shadow("cycle-identity", [buy, exit_row], captured_at=CAPTURED)

    assert result["detail_total"] == 2
    assert result["denominators"]["buy_population_total"] == 1
    assert {item["action"] for item in result["details"]} == {"buy", "exit"}


def test_cycle_mismatch_is_unavailable_not_rekeyed_to_embedded_cycle() -> None:
    row = _row(cycle_id="cycle-internal")

    result = build_capital_deployment_funnel_shadow("cycle-external", [row], captured_at=CAPTURED)

    assert result["denominators"]["cycle_mismatch_count"] == 1
    assert result["denominators"]["decision_identity_unavailable"] == 1
    assert result["denominators"]["buy_population_total"] == 1
    assert result["denominators"]["buy_population_identity_verified"] == 0
