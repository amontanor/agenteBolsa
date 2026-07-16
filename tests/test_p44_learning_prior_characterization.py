"""Caracterización de prior de aprendizaje y penalización operativa.

Estas pruebas describen el comportamiento de 0.4.172 sin modificar el
productor. Todos los datos son sintéticos y las funciones invocadas son las
reales de producción.
"""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.models import TradeRecommendation
from agente_bolsa.tools.daily_learning import _setup_priors
from agente_bolsa.tools.operational_health import load_operational_response_context
from agente_bolsa.tools.trade_decision import (
    _candidate_learning_features,
    _candidate_learning_prior,
    _candidate_rank_priority,
    _prior_profile_key,
    _selection_score_for_candidate,
    _sizing_adjustment_for_recommendation,
    filter_entry_quality,
    validate_entry_quality,
)


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(DATA_DIR=tmp_path, _env_file=None, **overrides)


def _candidate() -> dict:
    return {
        "symbol": "AAPL",
        "direction": "long",
        "setup_quality": "strong",
        "score": 14,
        "relative_return_20d": 0.08,
        "top_long_rank": 1,
        "technical_state": {
            "close": 100.0,
            "return_20d": 0.08,
            "return_60d": 0.12,
            "sma_20": 95.0,
            "rsi_14": 72.0,
            "macd": 2.0,
            "macd_signal": 1.0,
            "volume_zscore_20": 0.5,
            "close_position_in_range": 0.85,
            "chart_patterns": [{"bias": "bullish", "status": "confirmed", "label": "breakout"}],
        },
    }


def _prior_digest(candidate: dict, raw_edge: float, *, sample: int = 8) -> dict:
    profile_key = _prior_profile_key(_candidate_learning_features(candidate))
    return {
        "setup_stats_3d": [
            {"setup": "confirmed_pattern", "avg_return": raw_edge, "win_rate": 0.5, "matured": sample}
        ],
        "setup_priors_3d": [
            {
                "profile_key": profile_key,
                "setup": "confirmed_pattern",
                "expected_edge": raw_edge,
                "win_rate": 0.5,
                "matured": sample,
                "confidence_weight": 1.0 if sample >= 8 else 0.5,
            }
        ],
    }


def _observation(features: dict, value: float, index: int) -> dict:
    return {
        "observation_id": f"obs-{index}",
        "symbol": f"SYM{index}",
        "signal_date": "2026-07-01",
        "features": features,
        "outcome": {"matured_horizons": {"3d": True}, "return_3d": value},
    }


def _recommendation() -> TradeRecommendation:
    return TradeRecommendation(
        symbol="AAPL",
        action="buy",
        confidence=0.90,
        reason="synthetic",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=115.0,
        target_exposure_pct=0.05,
    )


def test_setup_priors_uses_profile_setup_shrinkage_before_operational_penalty():
    target_features = {
        "score": 14,
        "rsi_14": 72.0,
        "distance_sma20": 0.05,
        "volume_zscore_20": 0.5,
        "chart_patterns": {"bullish_confirmed_count": 1},
    }
    other_features = {**target_features, "score": 18}
    observations = [
        *[_observation(target_features, 0.02, i) for i in range(4)],
        *[_observation(other_features, 0.01, i + 4) for i in range(4)],
    ]

    rows = _setup_priors(observations, 3, min_samples=3)

    target_key = _prior_profile_key(target_features)
    target = next(row for row in rows if row["profile_key"] == target_key)
    assert target["avg_return"] == 0.02
    assert target["setup_avg_return"] == 0.015
    assert target["confidence_weight"] == 0.5
    assert target["expected_edge"] == 0.0175


@pytest.mark.parametrize("raw_edge", [0.02, 0.01, 0.0, -0.01])
@pytest.mark.parametrize("penalty", [0.0, 0.01, 0.05])
def test_prior_matrix_publishes_raw_edge_minus_penalty(raw_edge: float, penalty: float):
    candidate = _candidate()
    prior = _candidate_learning_prior(
        candidate,
        _prior_digest(candidate, raw_edge),
        {"setup_penalties": {"confirmed_pattern": penalty}},
    )

    assert prior["expected_edge_3d"] == round(raw_edge - penalty, 4)
    assert prior["setup_edge_3d_raw"] == raw_edge
    assert prior["operational_penalty"] == penalty


def test_raw_plus_one_percent_and_five_percent_penalty_is_minus_four_percent():
    candidate = _candidate()
    prior = _candidate_learning_prior(
        candidate,
        _prior_digest(candidate, 0.01),
        {"setup_penalties": {"confirmed_pattern": 0.05}},
    )

    assert prior["expected_edge_3d"] == -0.04
    assert prior["setup_edge_3d_raw"] == 0.01
    assert prior["operational_penalty"] == 0.05


@pytest.mark.parametrize(
    ("context", "expected"),
    [
        ({}, 0.0),
        ({"setup_penalties": {"confirmed_pattern": None}}, 0.0),
        ({"setup_penalties": {"confirmed_pattern": "0.05"}}, 0.05),
        ({"setup_penalties": {"confirmed_pattern": "invalid"}}, 0.0),
        ({"setup_penalties": {"confirmed_pattern": object()}}, 0.0),
    ],
)
def test_prior_invalid_penalty_inputs_are_characterized_without_normalization(context: dict, expected: float):
    candidate = _candidate()
    prior = _candidate_learning_prior(candidate, _prior_digest(candidate, 0.01), context)

    assert prior["operational_penalty"] == expected
    assert prior["expected_edge_3d"] == round(0.01 - expected, 4)


def test_operational_health_loader_accepts_only_numeric_penalties(tmp_path: Path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "latest_operational_health.json").write_text(
        json.dumps(
            {
                "responses": [
                    {
                        "action": "deprioritize_setup_before_llm",
                        "status": "guarded_active",
                        "scope": "confirmed_pattern",
                        "candidate_priority_penalty": 0.05,
                    },
                    {
                        "action": "deprioritize_setup_before_llm",
                        "status": "guarded_active",
                        "scope": "string_penalty",
                        "candidate_priority_penalty": "0.05",
                    },
                    {
                        "action": "deprioritize_setup_before_llm",
                        "status": "guarded_active",
                        "scope": "null_penalty",
                        "candidate_priority_penalty": None,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    context = load_operational_response_context(tmp_path)

    assert context["setup_penalties"] == {"confirmed_pattern": 0.05}


def test_insufficient_profile_samples_fall_back_to_setup_and_selection_marks_sample_penalty(tmp_path: Path):
    candidate = _candidate()
    profile_key = _prior_profile_key(_candidate_learning_features(candidate))
    digest = {
        "setup_stats_3d": [{"setup": "confirmed_pattern", "avg_return": 0.02, "win_rate": 0.5, "matured": 2}],
        "setup_priors_3d": [],
    }
    prior = _candidate_learning_prior(candidate, digest, {})
    candidate["learning_prior"] = prior
    selection = _selection_score_for_candidate(candidate, digest, {}, settings=_settings(tmp_path))

    assert prior["profile_key"] == profile_key
    assert prior["matched_on"] == "setup"
    assert prior["sample_size_3d"] == 2
    assert prior["expected_edge_3d"] == 0.02
    assert selection["selection_components"]["sample_penalty"] == 0.018
    assert selection["selection_components"]["shrunk_edge_3d"] == 0.0


def _prior_for_stage(edge: float, penalty: float) -> dict:
    return {
        "profile_key": "confirmed_pattern|score:12_14",
        "expected_edge_3d": edge,
        "setup_edge_3d_raw": 0.01,
        "sample_size_3d": 8,
        "setup_sample_size_3d": 12,
        "confidence_weight_3d": 1.0,
        "operational_penalty": penalty,
    }


def test_same_candidate_is_deterministic_and_penalty_is_applied_again_in_ranking_dimensions(tmp_path: Path):
    candidate_without = _candidate()
    candidate_without["learning_prior"] = _prior_for_stage(0.01, 0.0)
    candidate_with = deepcopy(candidate_without)
    candidate_with["learning_prior"] = _prior_for_stage(-0.04, 0.05)
    settings = _settings(tmp_path)

    selection_without = _selection_score_for_candidate(candidate_without, {}, {}, settings=settings)
    selection_with = _selection_score_for_candidate(candidate_with, {}, {}, settings=settings)
    rank_without = _candidate_rank_priority(candidate_without, {}, {}, settings=settings)
    rank_with = _candidate_rank_priority(candidate_with, {}, {}, settings=settings)

    assert selection_without == _selection_score_for_candidate(candidate_without, {}, {}, settings=settings)
    assert rank_without == _candidate_rank_priority(candidate_without, {}, {}, settings=settings)
    assert rank_without["rank_priority_score"] - rank_with["rank_priority_score"] == pytest.approx(0.10)
    assert selection_without["selection_score"] - selection_with["selection_score"] == pytest.approx(0.0725)
    assert selection_with["selection_components"]["shrunk_edge_3d"] == -0.0125
    assert rank_with["rank_priority_components"]["expected_edge_3d"] == -0.04
    assert rank_with["rank_priority_components"]["operational_penalty"] == 0.05


def test_sizing_separates_negative_prior_and_confidence_calibration(tmp_path: Path):
    recommendation = _recommendation()
    candidate = _candidate()
    candidate["learning_prior"] = {
        "expected_edge_3d": -0.01,
        "sample_size_3d": 8,
        "confidence_weight_3d": 1.0,
        "profile_key": "confirmed_pattern|score:12_14",
    }
    technical_context = {"top_longs": [candidate], "top_shorts": []}

    prior_only = _sizing_adjustment_for_recommendation(recommendation, technical_context, {}, {})
    calibration_only_candidate = deepcopy(candidate)
    calibration_only_candidate["learning_prior"] = {
        **candidate["learning_prior"],
        "expected_edge_3d": 0.01,
    }
    calibration_only = _sizing_adjustment_for_recommendation(
        recommendation,
        {"top_longs": [calibration_only_candidate], "top_shorts": []},
        {
            "confidence_calibration_3d": [
                {"bucket": "gte0_90", "avg_return": -0.01, "win_rate": 0.40, "matured": 9}
            ]
        },
        {},
    )
    combined = _sizing_adjustment_for_recommendation(
        recommendation,
        technical_context,
        {
            "confidence_calibration_3d": [
                {"bucket": "gte0_90", "avg_return": -0.01, "win_rate": 0.40, "matured": 9}
            ]
        },
        {},
    )

    assert prior_only["size_multiplier"] == 0.75
    assert prior_only["reason"] == "negative_recent_prior"
    assert calibration_only["size_multiplier"] == 0.85
    assert calibration_only["reason"] == "weak_confidence_calibration"
    assert combined["size_multiplier"] == 0.6375
    assert combined["reason"] == "negative_recent_prior,weak_confidence_calibration"


def test_strong_prior_and_calibration_are_a_distinct_sizing_dimension(tmp_path: Path):
    candidate = _candidate()
    candidate["learning_prior"] = {
        "expected_edge_3d": 0.04,
        "sample_size_3d": 8,
        "confidence_weight_3d": 1.0,
        "profile_key": "confirmed_pattern|score:12_14",
    }
    adjustment = _sizing_adjustment_for_recommendation(
        _recommendation(),
        {"top_longs": [candidate], "top_shorts": []},
        {
            "confidence_calibration_3d": [
                {"bucket": "gte0_90", "avg_return": 0.03, "win_rate": 0.60, "matured": 9}
            ]
        },
        {},
    )

    assert adjustment["size_multiplier"] == 1.15
    assert adjustment["reason"] == "strong_recent_prior,strong_confidence_calibration"


def test_normal_candidate_has_no_micro_experiment_and_keeps_baseline_size(tmp_path: Path):
    candidate = _candidate()
    candidate["learning_prior"] = {
        "expected_edge_3d": 0.01,
        "sample_size_3d": 2,
        "confidence_weight_3d": 0.2,
        "profile_key": "confirmed_pattern|score:12_14",
    }

    kept, decisions = filter_entry_quality(
        _settings(tmp_path),
        [_recommendation()],
        {"top_longs": [candidate], "top_shorts": []},
        {"results": []},
        daily_learning_digest={},
        operational_response_context={},
    )

    assert len(kept) == 1
    assert kept[0].micro_experiment is False
    assert kept[0].size_multiplier == 1.0
    assert decisions[0]["checks"]["entry_score_v2"]["micro_experiment"] is False


def test_negative_prior_blocks_when_sample_and_confidence_are_sufficient(tmp_path: Path):
    candidate = _candidate()
    candidate["learning_prior"] = {
        "expected_edge_3d": -0.04,
        "sample_size_3d": 8,
        "confidence_weight_3d": 1.0,
        "profile_key": "confirmed_pattern|score:12_14",
    }
    approved, reason, checks = validate_entry_quality(
        _settings(tmp_path),
        _recommendation(),
        {"top_longs": [candidate], "top_shorts": []},
        {"results": []},
        daily_learning_digest={},
        operational_response_context={},
    )

    assert approved is False
    assert "prior reciente desfavorable" in reason
    assert checks["learning_prior"]["expected_edge_3d"] == -0.04


def test_negative_prior_can_pass_as_micro_experiment_with_half_size(tmp_path: Path):
    candidate = _candidate()
    candidate.update(
        {
            "score": 10,
            "learning_prior": {
                "expected_edge_3d": -0.01,
                "sample_size_3d": 2,
                "confidence_weight_3d": 0.2,
                "profile_key": "confirmed_pattern|score:9_11",
            },
        }
    )
    candidate["technical_state"].update(
        {
            "return_20d": 0.03,
            "sma_20": 98.0,
            "volume_zscore_20": 0.0,
            "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
        }
    )
    recommendation = TradeRecommendation(
        symbol="AAPL",
        action="buy",
        confidence=0.90,
        reason="synthetic",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=107.5,
        target_exposure_pct=0.05,
    )

    kept, decisions = filter_entry_quality(
        _settings(tmp_path, ENTRY_QUALITY_MIN_SCORE=10, ENTRY_SCORE_V2_MIN=0.70),
        [recommendation],
        {"top_longs": [candidate], "top_shorts": []},
        {"results": [{"symbol": "AAPL", "sentiment": {"risk_flags": ["sentiment_failed"]}}]},
        daily_learning_digest={},
        operational_response_context={},
    )

    assert len(kept) == 1
    assert kept[0].micro_experiment is True
    assert kept[0].size_multiplier == 0.5
    assert decisions[0]["checks"]["entry_score_v2"]["micro_experiment"] is True
