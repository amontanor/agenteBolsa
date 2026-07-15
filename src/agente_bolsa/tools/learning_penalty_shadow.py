"""Comparador shadow de penalización única para el prior de aprendizaje.

Este módulo no forma parte de la ruta activa de trading. Construye dos inputs
para las funciones productivas de score/prioridad: el input legacy, que llega
ya penalizado, y el input shadow, que conserva el edge histórico separado para
que el consumidor explícito aplique la penalización una sola vez.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.tools.trade_decision import (
    _candidate_rank_priority,
    _selection_score_for_candidate,
)

SCHEMA_VERSION = "p-l44b.learning-penalty-shadow.v1"


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _validate_inputs(
    candidate: Mapping[str, Any] | None,
    historical_edge_3d: Any,
    setup_edge_3d_raw: Any,
    sample_size_3d: Any,
    confidence: Any,
    operational_penalty: Any,
) -> tuple[str, list[str], dict[str, float | int] | None]:
    warnings: list[str] = []
    if not isinstance(candidate, Mapping) or not str(candidate.get("symbol") or "").strip():
        warnings.append("missing_candidate_identity")
    values: dict[str, float | int] = {}
    for name, value in (
        ("historical_edge_3d", historical_edge_3d),
        ("setup_edge_3d_raw", setup_edge_3d_raw),
        ("operational_penalty", operational_penalty),
    ):
        if value is None:
            warnings.append(f"missing_{name}")
            continue
        number = _finite_number(value)
        if number is None:
            warnings.append(f"invalid_{name}")
            continue
        if name == "operational_penalty" and number < 0:
            warnings.append("invalid_operational_penalty_negative")
            continue
        values[name] = number

    if sample_size_3d is None:
        warnings.append("missing_sample_size_3d")
    elif isinstance(sample_size_3d, bool) or not isinstance(sample_size_3d, int) or sample_size_3d < 0:
        warnings.append("invalid_sample_size_3d")
    else:
        values["sample_size_3d"] = sample_size_3d
        if sample_size_3d < 3:
            warnings.append("insufficient_sample_3d")

    if confidence is None:
        warnings.append("missing_confidence")
    else:
        confidence_number = _finite_number(confidence)
        if confidence_number is None or not 0.0 <= confidence_number <= 1.0:
            warnings.append("invalid_confidence")
        else:
            values["confidence"] = confidence_number

    if any(item.startswith("invalid_") for item in warnings):
        return "invalid", warnings, None
    if warnings:
        return "unavailable", warnings, None
    return "available", warnings, values


def _stable_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _empty_result(status: str, warnings: list[str]) -> dict[str, Any]:
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "historical_edge_3d": None,
        "setup_edge_3d_raw": None,
        "sample_size_3d": None,
        "confidence": None,
        "operational_penalty": None,
        "legacy_expected_edge_3d": None,
        "single_penalty_expected_edge_3d": None,
        "legacy_selection_score": None,
        "single_penalty_selection_score": None,
        "selection_score_delta": None,
        "legacy_rank_priority": None,
        "single_penalty_rank_priority": None,
        "rank_priority_delta": None,
        "penalty_application_count_legacy": None,
        "penalty_application_count_shadow": None,
        "would_change_relative_order": None,
        "data_quality_warnings": sorted(set(warnings)),
    }
    result["content_hash"] = _stable_hash(result)
    return result


def build_learning_penalty_shadow(
    candidate: Mapping[str, Any] | None,
    *,
    historical_edge_3d: Any,
    setup_edge_3d_raw: Any,
    sample_size_3d: Any,
    confidence: Any,
    operational_penalty: Any,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Calcula legacy y contrafactual sin conectar ninguna ruta operativa."""

    status, warnings, values = _validate_inputs(
        candidate,
        historical_edge_3d,
        setup_edge_3d_raw,
        sample_size_3d,
        confidence,
        operational_penalty,
    )
    if status != "available" or values is None:
        return _empty_result(status, warnings)

    historical = float(values["historical_edge_3d"])
    setup_edge = float(values["setup_edge_3d_raw"])
    sample = int(values["sample_size_3d"])
    confidence_value = float(values["confidence"])
    penalty = float(values["operational_penalty"])
    legacy_expected = round(historical - penalty, 4)
    single_expected = round(historical - penalty, 4)
    base_candidate = deepcopy(dict(candidate))
    base_candidate["learning_prior"] = {
        "expected_edge_3d": legacy_expected,
        "setup_edge_3d_raw": setup_edge,
        "sample_size_3d": sample,
        "setup_sample_size_3d": sample,
        "confidence_weight_3d": confidence_value,
        "operational_penalty": penalty,
    }
    shadow_candidate = deepcopy(dict(candidate))
    shadow_candidate["learning_prior"] = {
        "expected_edge_3d": historical,
        "setup_edge_3d_raw": setup_edge,
        "sample_size_3d": sample,
        "setup_sample_size_3d": sample,
        "confidence_weight_3d": confidence_value,
        "operational_penalty": penalty,
    }
    effective_settings = settings or Settings(_env_file=None)
    legacy_selection = _selection_score_for_candidate(base_candidate, {}, {}, settings=effective_settings)
    shadow_selection = _selection_score_for_candidate(shadow_candidate, {}, {}, settings=effective_settings)
    legacy_rank = _candidate_rank_priority(base_candidate, {}, {}, settings=effective_settings)
    shadow_rank = _candidate_rank_priority(shadow_candidate, {}, {}, settings=effective_settings)

    result = {
        "schema_version": SCHEMA_VERSION,
        "status": "available",
        "historical_edge_3d": historical,
        "setup_edge_3d_raw": setup_edge,
        "sample_size_3d": sample,
        "confidence": confidence_value,
        "operational_penalty": penalty,
        "legacy_expected_edge_3d": legacy_expected,
        "single_penalty_expected_edge_3d": single_expected,
        "legacy_selection_score": legacy_selection["selection_score"],
        "single_penalty_selection_score": shadow_selection["selection_score"],
        "legacy_sample_penalty": legacy_selection["selection_components"]["sample_penalty"],
        "single_penalty_sample_penalty": shadow_selection["selection_components"]["sample_penalty"],
        "selection_score_delta": round(
            shadow_selection["selection_score"] - legacy_selection["selection_score"], 4
        ),
        "legacy_rank_priority": legacy_rank["rank_priority_score"],
        "single_penalty_rank_priority": shadow_rank["rank_priority_score"],
        "rank_priority_delta": round(shadow_rank["rank_priority_score"] - legacy_rank["rank_priority_score"], 4),
        "penalty_application_count_legacy": 2,
        "penalty_application_count_shadow": 1,
        "would_change_relative_order": None,
        "data_quality_warnings": [],
    }
    result["content_hash"] = _stable_hash(result)
    return result


def compare_learning_penalty_order(
    specifications: Sequence[Mapping[str, Any]],
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Compara orden legacy/shadow con desempate estable por símbolo."""

    rows = []
    for index, specification in enumerate(specifications):
        result = build_learning_penalty_shadow(
            specification.get("candidate"),
            historical_edge_3d=specification.get("historical_edge_3d"),
            setup_edge_3d_raw=specification.get("setup_edge_3d_raw"),
            sample_size_3d=specification.get("sample_size_3d"),
            confidence=specification.get("confidence"),
            operational_penalty=specification.get("operational_penalty"),
            settings=settings,
        )
        rows.append(
            {
                "symbol": str((specification.get("candidate") or {}).get("symbol") or f"index-{index}"),
                "index": index,
                "result": result,
            }
        )
    valid = [row for row in rows if row["result"]["status"] == "available"]
    legacy_order = [row["symbol"] for row in sorted(valid, key=lambda row: (-row["result"]["legacy_rank_priority"], row["symbol"]))]
    shadow_order = [
        row["symbol"]
        for row in sorted(valid, key=lambda row: (-row["result"]["single_penalty_rank_priority"], row["symbol"]))
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "available" if len(valid) == len(rows) else "unavailable",
        "legacy_order": legacy_order,
        "shadow_order": shadow_order,
        "would_change_relative_order": legacy_order != shadow_order if valid else None,
        "results": rows,
    }
