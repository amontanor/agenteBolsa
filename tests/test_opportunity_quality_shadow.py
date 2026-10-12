from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agente_bolsa.tools.opportunity_quality_shadow import (
    CURRENT_SCORE_HORIZON,
    MIN_MATURE_CURRENT_SCORE_OUTCOMES,
    MIN_MATURE_LLM_OUTCOMES,
    build_opportunity_quality_carrier,
    calibrate_current_selection_score,
    calibrate_empirical_llm_reliability,
)

DECISION_AT = datetime(2026, 10, 12, 11, 0, tzinfo=timezone.utc)


def _news(*, canonical_hash: str = "fact-1", published_at: datetime = DECISION_AT - timedelta(hours=1)) -> dict:
    return {
        "news_id": f"news-{canonical_hash}",
        "symbol": "ABC",
        "source": "wire-a",
        "canonical_hash": canonical_hash,
        "published_at": published_at.isoformat().replace("+00:00", "Z"),
        "available_at": (published_at + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        "materiality": 0.9,
        "novelty": 0.7,
        "economic_relevance": 0.8,
        "sentiment": 0.9,
        "priced_in": 0.2,
    }


def _payload() -> dict:
    identity = {
        "candidate_id": "candidate-1",
        "signal_capture_id": "capture-1",
        "signal_id": "signal-1",
        "recommendation_id": "recommendation-1",
        "cycle_id": "cycle-1",
        "symbol": "ABC",
    }
    return {
        "identity": identity,
        "horizon_sessions": 5,
        "currency": "USD",
        "technical": 0.9,
        "setup": 0.8,
        "model_id": "model-a",
        "model_version": "2026-10",
        "prompt_version": "score-p1",
        "llm_calibration": {
            "status": "available",
            "value": 0.9,
            "mature_count": MIN_MATURE_LLM_OUTCOMES,
            "min_mature_outcomes": MIN_MATURE_LLM_OUTCOMES,
            "model_id": "model-a",
            "model_version": "2026-10",
            "prompt_version": "score-p1",
            "horizon_sessions": 5,
            "as_of": "2026-10-12T10:00:00Z",
            "evidence_ids": [f"outcome-{index}" for index in range(MIN_MATURE_LLM_OUTCOMES)],
            "coverage": {
                "eligible_rows": MIN_MATURE_LLM_OUTCOMES,
                "deduplicated_rows": MIN_MATURE_LLM_OUTCOMES,
            },
            "receipt_id": "calibration-receipt-1",
            "binding": {
                "identity": {
                    "candidate_id": "candidate-1",
                    "signal_capture_id": "capture-1",
                    "recommendation_id": "recommendation-1",
                },
                "model_id": "model-a",
                "model_version": "2026-10",
                "prompt_version": "score-p1",
                "horizon_sessions": 5,
            },
        },
        "news_evidence": [_news()],
    }


def _calibration_outcome(outcome_id: str, *, success: bool = True) -> dict:
    return {
        "outcome_id": outcome_id,
        "identity": {
            "candidate_id": "candidate-1",
            "signal_capture_id": "capture-1",
            "recommendation_id": "recommendation-1",
        },
        "model_id": "model-a",
        "model_version": "2026-10",
        "prompt_version": "score-p1",
        "horizon_sessions": 5,
        "decision_at": "2026-10-12T08:00:00Z",
        "outcome_matured_at": "2026-10-12T10:00:00Z",
        "outcome_success": success,
    }


def _current_outcome(outcome_id: str, *, score: float = 25.0, net_return: float = 0.01) -> dict:
    return {
        "outcome_id": outcome_id,
        "identity": {
            "candidate_id": "candidate-1",
            "signal_capture_id": "capture-1",
            "recommendation_id": "recommendation-1",
        },
        "current_selection_score": score,
        "net_return_after_costs": net_return,
        "costs_included": True,
        "currency": "USD",
        "horizon_sessions": CURRENT_SCORE_HORIZON,
        "decision_at": "2026-10-12T08:00:00Z",
        "outcome_matured_at": "2026-10-12T10:00:00Z",
    }


def _current_prior_receipt(policy_hash: str = "policy-hash-1") -> dict:
    return {
        "status": "available",
        "bins_frozen": True,
        "policy_hash": policy_hash,
        "frozen_bins": [
            {"label": "low", "lower": 0.0, "upper": 50.0},
            {"label": "high", "lower": 50.0, "upper": 100.0},
        ],
    }


def test_duplicate_syndicated_fact_scored_once_and_dimensions_remain_separate():
    payload = _payload()
    duplicate = _news(canonical_hash="fact-1")
    duplicate["news_id"] = "news-syndicated-copy"
    payload["news_evidence"] = [_news(), duplicate]

    carrier = build_opportunity_quality_carrier(payload, decision_at=DECISION_AT)

    assert carrier["status"] == "available"
    assert carrier["score"] == 87.0
    assert carrier["news"]["valid_count"] == 2
    assert carrier["news"]["deduplicated_count"] == 1
    assert carrier["news"]["dimensions"]["materiality"] == 0.9
    assert carrier["news"]["dimensions"]["sentiment"] == 0.9
    assert "news_duplicate_canonical_fact_deduped" in carrier["reason_codes"]


def test_future_news_becomes_unavailable_without_positive_score():
    payload = _payload()
    payload["news_evidence"] = [_news(published_at=DECISION_AT + timedelta(minutes=1))]

    carrier = build_opportunity_quality_carrier(payload, decision_at=DECISION_AT)

    assert carrier["score"] is None
    assert "news" in carrier["coverage"]["missing_components"]
    assert "news_future_unavailable" in carrier["reason_codes"]


def test_missing_component_does_not_redistribute_weights():
    payload = _payload()
    payload.pop("news_evidence")
    carrier = build_opportunity_quality_carrier(payload, decision_at=DECISION_AT)

    assert carrier["score"] is None
    assert carrier["coverage"]["ratio"] == 0.75
    assert carrier["coverage"]["weights_redistributed"] is False
    assert carrier["components"]["news"] is None


def test_nan_component_is_invalid_and_cannot_make_score_available():
    payload = _payload()
    payload["technical"] = float("nan")

    carrier = build_opportunity_quality_carrier(payload, decision_at=DECISION_AT)

    assert carrier["score"] is None
    assert carrier["components"]["technical"] is None
    assert "component_technical_invalid" in carrier["reason_codes"]


def test_llm_self_confidence_is_not_empirical_reliability():
    payload = _payload()
    payload.pop("llm_calibration")
    payload["llm"] = {"confidence": 0.99, "model_id": "model-a"}

    carrier = build_opportunity_quality_carrier(payload, decision_at=DECISION_AT)

    assert carrier["components"]["empirical_llm_reliability"] is None
    assert carrier["score"] is None
    assert "llm_self_confidence_ignored" in carrier["reason_codes"]


def test_llm_fallback_is_unavailable_even_when_numeric_value_is_present():
    payload = _payload()
    payload.pop("llm_calibration")
    payload["empirical_llm_reliability"] = 0.9
    payload["llm"] = {"fallback": True}

    carrier = build_opportunity_quality_carrier(payload, decision_at=DECISION_AT)

    assert carrier["components"]["empirical_llm_reliability"] is None
    assert carrier["score"] is None
    assert "llm_fallback_unavailable" in carrier["reason_codes"]


def test_shadow_carrier_has_no_size_or_order_authority():
    carrier = build_opportunity_quality_carrier(_payload(), decision_at=DECISION_AT)

    assert carrier["authority"]["shadow_only"] is True
    assert carrier["authority"]["can_authorize_size"] is False
    assert carrier["authority"]["size_authorized"] is False
    assert carrier["authority"]["can_change_orders"] is False
    assert carrier["authority"]["can_select_candidate"] is False
    assert carrier["high_tier"]["eligible"] is False


def test_high_tier_requires_score_expectancy_evidence_binding_and_all_hard_gates():
    payload = _payload()
    payload["higher_tier_evidence"] = {
        "approved": True,
        "approval_token": "approval-1",
        "binding": {
            "candidate_id": "candidate-1",
            "signal_capture_id": "capture-1",
            "recommendation_id": "recommendation-1",
        },
    }
    payload["validated_net_expectancy"] = {
        "validated": True,
        "value": 0.01,
        "horizon_sessions": 5,
        "evidence_id": "expectancy-1",
        "as_of": "2026-10-12T10:00:00Z",
        "costs_included": True,
        "policy_version": "score-shadow.v1",
    }
    payload["hard_gates"] = {
        "identity": True,
        "risk": True,
        "data": True,
        "costs": True,
        "policy": True,
    }

    carrier = build_opportunity_quality_carrier(payload, decision_at=DECISION_AT)

    assert carrier["score"] == 87.0
    assert carrier["high_tier"]["eligible"] is True
    assert carrier["high_tier"]["hard_gates_passed"] is True


def test_calibration_uses_only_mature_real_exact_model_and_horizon_rows():
    outcomes = [
        {
            "outcome_id": f"outcome-{index}",
            "identity": {
                "candidate_id": "candidate-1",
                "signal_capture_id": "capture-1",
                "recommendation_id": "recommendation-1",
            },
            "model_id": "model-a",
            "model_version": "2026-10",
            "prompt_version": "score-p1",
            "horizon_sessions": 5,
            "decision_at": "2026-10-12T08:00:00Z",
            "outcome_matured_at": "2026-10-12T10:00:00Z",
            "outcome_success": True,
        }
        for index in range(MIN_MATURE_LLM_OUTCOMES)
    ]
    outcomes.extend(
        [
        {
            "outcome_id": "future-outcome",
            "identity": {"candidate_id": "candidate-1"},
            "model_id": "model-a",
            "model_version": "2026-10",
            "prompt_version": "score-p1",
            "horizon_sessions": 5,
            "decision_at": "2026-10-12T08:00:00Z",
            "outcome_matured_at": "2026-10-12T12:00:00Z",
            "outcome_success": False,
        },
        {
            "outcome_id": "shadow-outcome",
            "identity": {"candidate_id": "candidate-1"},
            "model_id": "model-a",
            "model_version": "2026-10",
            "prompt_version": "score-p1",
            "horizon_sessions": 5,
            "decision_at": "2026-10-12T08:00:00Z",
            "outcome_matured_at": "2026-10-12T09:00:00Z",
            "outcome_success": False,
            "is_shadow": True,
        },
        {
            "outcome_id": "wrong-model-outcome",
            "identity": {"candidate_id": "candidate-1"},
            "model_id": "model-other",
            "model_version": "2026-10",
            "prompt_version": "score-p1",
            "horizon_sessions": 5,
            "decision_at": "2026-10-12T08:00:00Z",
            "outcome_matured_at": "2026-10-12T09:00:00Z",
            "outcome_success": False,
        },
        ]
    )

    result = calibrate_empirical_llm_reliability(
        outcomes,
        as_of=DECISION_AT,
        model_id="model-a",
        model_version="2026-10",
        prompt_version="score-p1",
        horizon_sessions=5,
        identity={
            "candidate_id": "candidate-1",
            "signal_capture_id": "capture-1",
            "recommendation_id": "recommendation-1",
        },
    )

    assert result["status"] == "available"
    assert result["mature_count"] == MIN_MATURE_LLM_OUTCOMES
    assert result["value"] == 1.0
    assert len(result["evidence_ids"]) == MIN_MATURE_LLM_OUTCOMES
    assert result["coverage"]["deduplicated_rows"] == MIN_MATURE_LLM_OUTCOMES + 3
    assert "llm_shadow_or_fallback_outcome_excluded" in result["reason_codes"]


def test_invalid_news_identity_stays_unavailable():
    payload = _payload()
    invalid = _news()
    invalid.pop("source")
    payload["news_evidence"] = [invalid]

    carrier = build_opportunity_quality_carrier(payload, decision_at=DECISION_AT)

    assert carrier["components"]["news"] is None
    assert carrier["score"] is None
    assert "news_identity_incomplete" in carrier["reason_codes"]


def test_numeric_news_cannot_override_invalid_supplied_evidence():
    payload = _payload()
    payload["news"] = 1.0
    future = _news(published_at=DECISION_AT + timedelta(minutes=1))
    payload["news_evidence"] = [future]

    carrier = build_opportunity_quality_carrier(payload, decision_at=DECISION_AT)

    assert carrier["components"]["news"] is None
    assert carrier["score"] is None
    assert "component_news_invalid_evidence" in carrier["reason_codes"]


def test_raw_numeric_news_without_proof_is_unavailable():
    payload = _payload()
    payload.pop("news_evidence")
    payload["news"] = 1.0

    carrier = build_opportunity_quality_carrier(payload, decision_at=DECISION_AT)

    assert carrier["components"]["news"] is None
    assert carrier["score"] is None
    assert "news_evidence_unavailable" in carrier["reason_codes"]


def test_raw_numeric_llm_without_calibration_receipt_is_unavailable():
    payload = _payload()
    payload.pop("llm_calibration")
    payload["empirical_llm_reliability"] = 1.0

    carrier = build_opportunity_quality_carrier(payload, decision_at=DECISION_AT)

    assert carrier["components"]["empirical_llm_reliability"] is None
    assert carrier["score"] is None
    assert "llm_calibration_receipt_unavailable" in carrier["reason_codes"]


def test_calibration_deduplicates_identical_outcome_and_rejects_conflict():
    outcomes = [_calibration_outcome(f"outcome-{index}") for index in range(MIN_MATURE_LLM_OUTCOMES)]
    outcomes.append(dict(outcomes[0]))
    conflict = dict(outcomes[0])
    conflict["outcome_success"] = False
    outcomes.append(conflict)

    result = calibrate_empirical_llm_reliability(
        outcomes,
        as_of=DECISION_AT,
        model_id="model-a",
        model_version="2026-10",
        prompt_version="score-p1",
        horizon_sessions=5,
        identity={
            "candidate_id": "candidate-1",
            "signal_capture_id": "capture-1",
            "recommendation_id": "recommendation-1",
        },
    )

    assert result["status"] == "unavailable"
    assert "llm_outcome_duplicate_deduped" in result["reason_codes"]
    assert "llm_outcome_identity_conflict" in result["reason_codes"]
    assert result["coverage"]["deduplicated_rows"] == MIN_MATURE_LLM_OUTCOMES


def test_calibration_excludes_fallback_outcomes_from_real_learning():
    outcomes = [_calibration_outcome(f"outcome-{index}") for index in range(MIN_MATURE_LLM_OUTCOMES)]
    fallback = _calibration_outcome("fallback-outcome", success=False)
    fallback["fallback_reason"] = "provider_timeout"
    outcomes.append(fallback)

    result = calibrate_empirical_llm_reliability(
        outcomes,
        as_of=DECISION_AT,
        model_id="model-a",
        model_version="2026-10",
        prompt_version="score-p1",
        horizon_sessions=5,
        identity={
            "candidate_id": "candidate-1",
            "signal_capture_id": "capture-1",
            "recommendation_id": "recommendation-1",
        },
    )

    assert result["status"] == "available"
    assert result["mature_count"] == MIN_MATURE_LLM_OUTCOMES
    assert "llm_shadow_or_fallback_outcome_excluded" in result["reason_codes"]


def test_calibration_rejects_future_as_of_and_missing_canonical_ids():
    outcomes = [_calibration_outcome(f"outcome-{index}") for index in range(MIN_MATURE_LLM_OUTCOMES)]
    calibrated = calibrate_empirical_llm_reliability(
        outcomes,
        as_of=DECISION_AT,
        model_id="model-a",
        model_version="2026-10",
        prompt_version="score-p1",
        horizon_sessions=5,
        identity={
            "candidate_id": "candidate-1",
            "signal_capture_id": "capture-1",
            "recommendation_id": "recommendation-1",
        },
    )
    future_outcomes = outcomes[:-1]
    future_outcome = _calibration_outcome("future-matured")
    future_outcome["outcome_matured_at"] = "2026-10-12T12:00:00Z"
    future_outcomes.append(future_outcome)
    future_outcome_result = calibrate_empirical_llm_reliability(
        future_outcomes,
        as_of=DECISION_AT,
        model_id="model-a",
        model_version="2026-10",
        prompt_version="score-p1",
        horizon_sessions=5,
        identity={
            "candidate_id": "candidate-1",
            "signal_capture_id": "capture-1",
            "recommendation_id": "recommendation-1",
        },
    )
    future_receipt_payload = _payload()
    future_receipt_payload["llm_calibration"] = dict(future_receipt_payload["llm_calibration"])
    future_receipt_payload["llm_calibration"]["as_of"] = "2026-10-12T12:00:00Z"
    future_receipt = build_opportunity_quality_carrier(future_receipt_payload, decision_at=DECISION_AT)
    missing_ids = calibrate_empirical_llm_reliability(
        outcomes,
        as_of=DECISION_AT,
        model_id="model-a",
        model_version="2026-10",
        prompt_version="score-p1",
        horizon_sessions=5,
        identity={"candidate_id": "candidate-1"},
    )

    assert calibrated["status"] == "available"
    assert future_outcome_result["status"] == "unavailable"
    assert future_outcome_result["mature_count"] == MIN_MATURE_LLM_OUTCOMES - 1
    assert "llm_outcome_not_matured" in future_outcome_result["reason_codes"]
    assert future_receipt["components"]["empirical_llm_reliability"] is None
    assert "llm_calibration_as_of_after_decision" in future_receipt["reason_codes"]
    assert missing_ids["status"] == "unavailable"
    assert "llm_calibration_identity_required" in missing_ids["reason_codes"]


def test_high_tier_rejects_identity_horizon_threshold_and_gate_laundering():
    identity_missing = _payload()
    identity_missing["identity"].pop("recommendation_id")
    identity_result = build_opportunity_quality_carrier(identity_missing, decision_at=DECISION_AT)

    invalid_horizon = _payload()
    invalid_horizon["horizon_sessions"] = 7
    horizon_result = build_opportunity_quality_carrier(invalid_horizon, decision_at=DECISION_AT)

    low_score = _payload()
    low_score["technical"] = 0.8
    low_score["setup"] = 0.7
    low_score["higher_tier_evidence"] = {
        "approved": True,
        "approval_token": "approval-1",
        "binding": {
            "candidate_id": "candidate-1",
            "signal_capture_id": "capture-1",
            "recommendation_id": "recommendation-1",
        },
    }
    low_score["validated_net_expectancy"] = {
        "validated": True,
        "value": 0.01,
        "horizon_sessions": 5,
        "evidence_id": "expectancy-1",
        "as_of": "2026-10-12T10:00:00Z",
        "costs_included": True,
        "policy_version": "score-shadow.v1",
    }
    low_score["hard_gates"] = {"anything": True}
    threshold_result = build_opportunity_quality_carrier(
        low_score,
        decision_at=DECISION_AT,
        policy={"high_tier_score": 1},
    )

    assert identity_result["high_tier"]["eligible"] is False
    assert "high_tier_canonical_identity_incomplete" in identity_result["reason_codes"]
    assert horizon_result["horizon_sessions"] is None
    assert horizon_result["high_tier"]["eligible"] is False
    assert "high_tier_horizon_invalid" in horizon_result["reason_codes"]
    assert threshold_result["high_tier"]["score_threshold"] == 85.0
    assert threshold_result["high_tier"]["eligible"] is False
    assert threshold_result["high_tier"]["hard_gates_passed"] is False
    assert "high_tier_threshold_floor_applied" in threshold_result["reason_codes"]


def test_current_score_calibration_uses_frozen_bins_and_separate_value_kinds():
    outcomes = [
        _current_outcome(
            f"current-outcome-{index}",
            net_return=0.02 if index % 2 == 0 else -0.01,
        )
        for index in range(MIN_MATURE_CURRENT_SCORE_OUTCOMES)
    ]
    shadow_outcome = _current_outcome("shadow-current-outcome")
    shadow_outcome["is_shadow"] = True
    outcomes.append(shadow_outcome)
    receipt = calibrate_current_selection_score(
        outcomes,
        as_of=DECISION_AT,
        policy_hash="policy-hash-1",
        prior_receipt=_current_prior_receipt(),
        identity={
            "candidate_id": "candidate-1",
            "signal_capture_id": "capture-1",
            "recommendation_id": "recommendation-1",
        },
    )
    payload = _payload()
    payload.update(
        {
            "current_selection_score": 25.0,
            "current_selection_components": {"raw_edge": 0.057},
            "policy_hash": "policy-hash-1",
            "champion_calibration": receipt,
        }
    )

    carrier = build_opportunity_quality_carrier(payload, decision_at=DECISION_AT)

    assert receipt["status"] == "available"
    assert "current_score_shadow_or_fallback_outcome_excluded" in receipt["reason_codes"]
    assert carrier["current_selection_score"] == 25.0
    assert carrier["current_selection_components"] == {"raw_edge": 0.057}
    assert carrier["champion_calibration"]["status"] == "available"
    assert carrier["champion_calibration"]["bin_label"] == "low"
    assert carrier["champion_calibration"]["empirical_positive_net_return_probability"] == 0.5
    assert carrier["champion_calibration"]["score_kind"] == "calibrated_score_0_100"
    assert carrier["champion_calibration"]["probability_kind"] != "calibrated_score_0_100"
    assert carrier["champion_calibration"]["value_kind"] == "empirical_net_return_after_costs"


def test_current_score_calibration_requires_frozen_receipt_and_rejects_raw_scale():
    outcomes = [_current_outcome(f"current-outcome-{index}", score=0.057) for index in range(MIN_MATURE_CURRENT_SCORE_OUTCOMES)]
    missing_receipt = calibrate_current_selection_score(
        outcomes,
        as_of=DECISION_AT,
        policy_hash="policy-hash-1",
        prior_receipt=None,
        identity={
            "candidate_id": "candidate-1",
            "signal_capture_id": "capture-1",
            "recommendation_id": "recommendation-1",
        },
    )
    receipt = calibrate_current_selection_score(
        outcomes,
        as_of=DECISION_AT,
        policy_hash="policy-hash-2",
        prior_receipt=_current_prior_receipt("policy-hash-2"),
        identity={
            "candidate_id": "candidate-1",
            "signal_capture_id": "capture-1",
            "recommendation_id": "recommendation-1",
        },
    )
    payload = _payload()
    payload.update(
        {
            "current_selection_score": 0.057,
            "policy_hash": "policy-hash-2",
            "champion_calibration": receipt,
        }
    )
    carrier = build_opportunity_quality_carrier(payload, decision_at=DECISION_AT)

    assert missing_receipt["status"] == "unavailable"
    assert "current_score_prior_receipt_unavailable" in missing_receipt["reason_codes"]
    assert carrier["current_selection_score"] == 0.057
    assert carrier["champion_calibration"]["status"] == "available"
    assert carrier["champion_calibration"]["empirical_net_return_after_costs"] == 0.01
    assert carrier["champion_calibration"]["empirical_positive_net_return_probability"] == 1.0


def test_current_score_calibration_rejects_future_as_of_missing_costs_and_ids():
    outcomes = [_current_outcome(f"current-outcome-{index}") for index in range(MIN_MATURE_CURRENT_SCORE_OUTCOMES)]
    future_as_of = calibrate_current_selection_score(
        outcomes,
        as_of=DECISION_AT,
        policy_hash="policy-hash-1",
        prior_receipt={
            **_current_prior_receipt(),
            "calibration_as_of": "2026-10-12T12:00:00Z",
        },
        identity={
            "candidate_id": "candidate-1",
            "signal_capture_id": "capture-1",
            "recommendation_id": "recommendation-1",
        },
    )
    missing_costs = list(outcomes[:-1])
    missing_cost = _current_outcome("missing-cost", net_return=0.01)
    missing_cost["costs_included"] = False
    missing_costs.append(missing_cost)
    missing_costs_result = calibrate_current_selection_score(
        missing_costs,
        as_of=DECISION_AT,
        policy_hash="policy-hash-1",
        prior_receipt=_current_prior_receipt(),
        identity={
            "candidate_id": "candidate-1",
            "signal_capture_id": "capture-1",
            "recommendation_id": "recommendation-1",
        },
    )
    missing_ids = list(outcomes[:-1])
    missing_id = _current_outcome("missing-ids")
    missing_id["identity"].pop("recommendation_id")
    missing_ids.append(missing_id)
    missing_ids_result = calibrate_current_selection_score(
        missing_ids,
        as_of=DECISION_AT,
        policy_hash="policy-hash-1",
        prior_receipt=_current_prior_receipt(),
        identity={
            "candidate_id": "candidate-1",
            "signal_capture_id": "capture-1",
            "recommendation_id": "recommendation-1",
        },
    )

    assert future_as_of["status"] == "unavailable"
    assert "current_score_prior_receipt_as_of_after_calibration" in future_as_of["reason_codes"]
    assert missing_costs_result["status"] == "unavailable"
    assert "current_score_costs_missing" in missing_costs_result["reason_codes"]
    assert missing_ids_result["status"] == "unavailable"
    assert "current_score_outcome_identity_mismatch" in missing_ids_result["reason_codes"]


def test_current_score_calibration_deduplicates_duplicate_ids_and_rejects_conflicts():
    outcomes = [_current_outcome(f"current-outcome-{index}") for index in range(MIN_MATURE_CURRENT_SCORE_OUTCOMES)]
    outcomes.append(dict(outcomes[0]))
    conflict = dict(outcomes[0])
    conflict["net_return_after_costs"] = -0.5
    outcomes.append(conflict)

    result = calibrate_current_selection_score(
        outcomes,
        as_of=DECISION_AT,
        policy_hash="policy-hash-1",
        prior_receipt=_current_prior_receipt(),
        identity={
            "candidate_id": "candidate-1",
            "signal_capture_id": "capture-1",
            "recommendation_id": "recommendation-1",
        },
    )

    assert result["status"] == "unavailable"
    assert "current_score_outcome_duplicate_deduped" in result["reason_codes"]
    assert "current_score_outcome_identity_conflict" in result["reason_codes"]


def test_current_score_calibration_carrier_keeps_shadow_without_authority():
    payload = _payload()
    payload["current_selection_score"] = 25.0

    carrier = build_opportunity_quality_carrier(payload, decision_at=DECISION_AT)

    assert carrier["champion_calibration"]["status"] == "unavailable"
    assert carrier["authority"]["shadow_only"] is True
    assert carrier["authority"]["can_authorize_size"] is False
    assert carrier["authority"]["can_change_orders"] is False
