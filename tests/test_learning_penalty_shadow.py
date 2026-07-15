"""Pruebas del candidato shadow P-L44B-W1."""

import copy
from pathlib import Path

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.tools.learning_penalty_shadow import (
    SCHEMA_VERSION,
    build_learning_penalty_shadow,
    compare_learning_penalty_order,
)
from agente_bolsa.tools.trade_decision import (
    _candidate_rank_priority,
    _selection_score_for_candidate,
)


def _candidate(symbol: str = "AAPL", score: int = 14) -> dict:
    return {
        "symbol": symbol,
        "direction": "long",
        "setup_quality": "strong",
        "score": score,
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
            "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
        },
    }


def _settings(tmp_path: Path) -> Settings:
    return Settings(DATA_DIR=tmp_path, _env_file=None)


def _spec(symbol: str, edge: float, penalty: float, *, score: int = 14) -> dict:
    return {
        "candidate": _candidate(symbol, score),
        "historical_edge_3d": edge,
        "setup_edge_3d_raw": 0.01,
        "sample_size_3d": 8,
        "confidence": 1.0,
        "operational_penalty": penalty,
    }


@pytest.mark.parametrize("edge", [0.02, 0.01, 0.0, -0.01])
@pytest.mark.parametrize("penalty", [0.0, 0.01, 0.05])
def test_shadow_matrix_keeps_historical_edge_separate(edge: float, penalty: float, tmp_path: Path):
    result = build_learning_penalty_shadow(
        _candidate(),
        historical_edge_3d=edge,
        setup_edge_3d_raw=0.01,
        sample_size_3d=8,
        confidence=1.0,
        operational_penalty=penalty,
        settings=_settings(tmp_path),
    )

    assert result["schema_version"] == SCHEMA_VERSION
    assert result["status"] == "available"
    assert result["historical_edge_3d"] == edge
    assert result["legacy_expected_edge_3d"] == round(edge - penalty, 4)
    assert result["single_penalty_expected_edge_3d"] == round(edge - penalty, 4)
    assert result["penalty_application_count_legacy"] == 2
    assert result["penalty_application_count_shadow"] == 1


def test_raw_one_percent_penalty_five_percent_removes_only_duplicate_consumer_application(tmp_path: Path):
    result = build_learning_penalty_shadow(
        _candidate(),
        historical_edge_3d=0.01,
        setup_edge_3d_raw=0.01,
        sample_size_3d=8,
        confidence=1.0,
        operational_penalty=0.05,
        settings=_settings(tmp_path),
    )

    assert result["legacy_expected_edge_3d"] == -0.04
    assert result["single_penalty_expected_edge_3d"] == -0.04
    assert result["selection_score_delta"] == pytest.approx(0.0225)
    assert result["rank_priority_delta"] == pytest.approx(0.05)


def test_zero_penalty_is_exact_parity(tmp_path: Path):
    result = build_learning_penalty_shadow(
        _candidate(),
        historical_edge_3d=0.01,
        setup_edge_3d_raw=0.01,
        sample_size_3d=8,
        confidence=1.0,
        operational_penalty=0.0,
        settings=_settings(tmp_path),
    )

    assert result["legacy_expected_edge_3d"] == result["single_penalty_expected_edge_3d"]
    assert result["legacy_selection_score"] == result["single_penalty_selection_score"]
    assert result["legacy_rank_priority"] == result["single_penalty_rank_priority"]
    assert result["selection_score_delta"] == 0.0
    assert result["rank_priority_delta"] == 0.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("historical_edge_3d", None),
        ("setup_edge_3d_raw", None),
        ("sample_size_3d", None),
        ("confidence", None),
        ("operational_penalty", None),
    ],
)
def test_missing_values_are_unavailable_not_zero(field: str, value: object, tmp_path: Path):
    values = {
        "historical_edge_3d": 0.01,
        "setup_edge_3d_raw": 0.01,
        "sample_size_3d": 8,
        "confidence": 1.0,
        "operational_penalty": 0.05,
    }
    values[field] = value
    result = build_learning_penalty_shadow(_candidate(), settings=_settings(tmp_path), **values)

    assert result["status"] == "unavailable"
    assert result["content_hash"]
    assert result["legacy_selection_score"] is None


@pytest.mark.parametrize("penalty", ["0.05", float("nan"), float("inf"), -0.01])
def test_invalid_penalty_values_are_invalid(penalty: object, tmp_path: Path):
    result = build_learning_penalty_shadow(
        _candidate(),
        historical_edge_3d=0.01,
        setup_edge_3d_raw=0.01,
        sample_size_3d=8,
        confidence=1.0,
        operational_penalty=penalty,
        settings=_settings(tmp_path),
    )

    assert result["status"] == "invalid"
    assert any(item.startswith("invalid_operational_penalty") for item in result["data_quality_warnings"])


def test_insufficient_sample_is_unavailable_without_invented_edge(tmp_path: Path):
    result = build_learning_penalty_shadow(
        _candidate(),
        historical_edge_3d=0.01,
        setup_edge_3d_raw=0.01,
        sample_size_3d=2,
        confidence=0.2,
        operational_penalty=0.05,
        settings=_settings(tmp_path),
    )

    assert result["status"] == "unavailable"
    assert result["sample_size_3d"] is None
    assert result["historical_edge_3d"] is None
    assert result["legacy_selection_score"] is None
    assert "insufficient_sample_3d" in result["data_quality_warnings"]


def test_setup_edge_can_differ_from_profile_edge_and_is_not_rewritten(tmp_path: Path):
    result = build_learning_penalty_shadow(
        _candidate(),
        historical_edge_3d=0.02,
        setup_edge_3d_raw=-0.01,
        sample_size_3d=8,
        confidence=0.5,
        operational_penalty=0.01,
        settings=_settings(tmp_path),
    )

    assert result["historical_edge_3d"] == 0.02
    assert result["setup_edge_3d_raw"] == -0.01
    assert result["single_penalty_expected_edge_3d"] == 0.01


def test_order_comparison_can_exchange_positions_and_ties_are_deterministic(tmp_path: Path):
    specifications = [
        _spec("AAPL", 0.07, 0.05),
        _spec("MSFT", 0.01, 0.0),
    ]
    first = compare_learning_penalty_order(specifications, settings=_settings(tmp_path))
    second = compare_learning_penalty_order(specifications, settings=_settings(tmp_path))

    assert first == second
    assert first["would_change_relative_order"] is True
    assert first["legacy_order"] == ["MSFT", "AAPL"]
    assert first["shadow_order"] == ["AAPL", "MSFT"]

    tied = compare_learning_penalty_order(
        [_spec("ZZZ", 0.01, 0.0), _spec("AAA", 0.01, 0.0)],
        settings=_settings(tmp_path),
    )
    assert tied["legacy_order"] == ["AAA", "ZZZ"]
    assert tied["shadow_order"] == ["AAA", "ZZZ"]


def test_hash_is_independent_of_input_key_order_and_repeat_is_idempotent(tmp_path: Path):
    candidate = _candidate()
    reordered = {key: candidate[key] for key in reversed(list(candidate))}
    kwargs = {
        "historical_edge_3d": 0.01,
        "setup_edge_3d_raw": 0.01,
        "sample_size_3d": 8,
        "confidence": 1.0,
        "operational_penalty": 0.05,
        "settings": _settings(tmp_path),
    }
    first = build_learning_penalty_shadow(candidate, **kwargs)
    repeat = build_learning_penalty_shadow(candidate, **kwargs)
    reordered_result = build_learning_penalty_shadow(reordered, **kwargs)

    assert first == repeat
    assert first["content_hash"] == reordered_result["content_hash"]


def test_missing_identity_is_unavailable_and_does_not_create_unknown(tmp_path: Path):
    result = build_learning_penalty_shadow(
        {"score": 14},
        historical_edge_3d=0.01,
        setup_edge_3d_raw=0.01,
        sample_size_3d=8,
        confidence=1.0,
        operational_penalty=0.05,
        settings=_settings(tmp_path),
    )

    assert result["status"] == "unavailable"
    assert "missing_candidate_identity" in result["data_quality_warnings"]
    assert "UNKNOWN" not in json_text(result)


def json_text(value: object) -> str:
    return str(value)


def test_shadow_import_and_execution_do_not_mutate_active_decision_functions(tmp_path: Path):
    candidate = _candidate()
    before = copy.deepcopy(candidate)
    settings = _settings(tmp_path)
    active_before = _selection_score_for_candidate(
        candidate,
        {},
        {},
        settings=settings,
    )
    active_rank_before = _candidate_rank_priority(candidate, {}, {}, settings=settings)

    shadow = build_learning_penalty_shadow(
        candidate,
        historical_edge_3d=0.01,
        setup_edge_3d_raw=0.01,
        sample_size_3d=8,
        confidence=1.0,
        operational_penalty=0.05,
        settings=settings,
    )
    active_after = _selection_score_for_candidate(candidate, {}, {}, settings=settings)
    active_rank_after = _candidate_rank_priority(candidate, {}, {}, settings=settings)

    assert candidate == before
    assert active_before == active_after
    assert active_rank_before == active_rank_after
    assert shadow["status"] == "available"
