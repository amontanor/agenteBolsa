"""Pure, observational SCORE opportunity-quality shadow.

This module consumes already captured, point-in-time payloads.  It never fetches
news, calls an LLM, authorizes size, selects a candidate, or changes an order.
Missing and invalid evidence stays unavailable; component weights are never
redistributed.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

SCORE_SHADOW_SCHEMA_VERSION = "p-lscore.opportunity-quality-shadow.v1"
SCORE_POLICY_VERSION = "score-shadow.v1"
SCORE_COMPONENTS = (
    "technical",
    "news",
    "empirical_llm_reliability",
    "setup",
)
SCORE_WEIGHTS = {
    "technical": 0.55,
    "news": 0.20,
    "empirical_llm_reliability": 0.15,
    "setup": 0.10,
}
SUPPORTED_HORIZONS = (3, 5, 10)
PRIMARY_HORIZON = 5
HIGH_TIER_SCORE = 85.0
MIN_MATURE_LLM_OUTCOMES = 30
REQUIRED_CANONICAL_IDENTITY = ("candidate_id", "signal_capture_id", "recommendation_id", "symbol")
REQUIRED_HIGH_TIER_GATES = ("identity", "data", "risk", "costs", "policy")
MIN_MATURE_CURRENT_SCORE_OUTCOMES = 30
CURRENT_SCORE_HORIZON = 5


class OpportunityQualityShadowError(ValueError):
    """Raised for malformed required inputs, never for unavailable evidence."""


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _normalised_unit(value: Any) -> float | None:
    number = _finite(value)
    if number is None or not 0.0 <= number <= 1.0:
        return None
    return number


def _utc(value: Any, field: str, *, required: bool = True) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise OpportunityQualityShadowError(f"{field}_invalid") from exc
    elif value is None and not required:
        return None
    else:
        raise OpportunityQualityShadowError(f"{field}_required")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OpportunityQualityShadowError(f"{field}_timezone_required")
    return parsed.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _decision_time(value: Any) -> datetime:
    return _utc(value, "decision_at")  # type: ignore[return-value]


def _append_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _identity_value(payload: Mapping[str, Any], identity: Mapping[str, Any], key: str) -> str | None:
    nested = _text(identity.get(key)) if key in identity else None
    root = _text(payload.get(key)) if key in payload else None
    if nested is not None and root is not None and nested != root:
        return None
    return nested if nested is not None else root


def _identity(payload: Mapping[str, Any], reasons: list[str]) -> dict[str, str]:
    raw = payload.get("identity")
    identity = raw if isinstance(raw, Mapping) else {}
    if raw is not None and not isinstance(raw, Mapping):
        _append_reason(reasons, "identity_invalid")
    result: dict[str, str] = {}
    for key in (
        "candidate_id",
        "signal_capture_id",
        "signal_id",
        "recommendation_id",
        "cycle_id",
        "symbol",
    ):
        value = _identity_value(payload, identity, key)
        if value is not None:
            result[key] = value
        elif key in payload or key in identity:
            _append_reason(reasons, f"identity_{key}_invalid")
    if "symbol" in result:
        result["symbol"] = result["symbol"].upper()
    if "candidate_id" not in result:
        _append_reason(reasons, "candidate_identity_unavailable")
    if "signal_capture_id" not in result:
        _append_reason(reasons, "capture_identity_unavailable")
    if "recommendation_id" not in result:
        _append_reason(reasons, "recommendation_identity_unavailable")
    return result


def _horizon(payload: Mapping[str, Any], reasons: list[str]) -> tuple[int | None, bool]:
    raw = payload.get("horizon_sessions", payload.get("horizon"))
    if raw is None:
        return PRIMARY_HORIZON, True
    try:
        value = int(raw)
    except (TypeError, ValueError):
        _append_reason(reasons, "horizon_invalid")
        return None, False
    if value not in SUPPORTED_HORIZONS:
        _append_reason(reasons, "horizon_unsupported")
        return None, False
    return value, True


def _component_value(
    payload: Mapping[str, Any],
    name: str,
    reasons: list[str],
) -> float | None:
    components = payload.get("components")
    nested = components if isinstance(components, Mapping) else {}
    aliases = (name, "llm_reliability") if name == "empirical_llm_reliability" else (name,)
    present = False
    raw: Any = None
    for key in aliases:
        if key in nested:
            raw = nested.get(key)
            present = True
            break
        if key in payload:
            raw = payload.get(key)
            present = True
            break
    if not present:
        _append_reason(reasons, f"component_{name}_unavailable")
        return None
    value = _normalised_unit(raw)
    if value is None:
        _append_reason(reasons, f"component_{name}_invalid")
        return None
    return value


def _model_provenance(payload: Mapping[str, Any], reasons: list[str]) -> dict[str, str | None]:
    model = payload.get("model")
    model_mapping = model if isinstance(model, Mapping) else {}
    result = {
        "model_id": _text(payload.get("model_id", model_mapping.get("model_id"))),
        "model_version": _text(payload.get("model_version", model_mapping.get("model_version"))),
        "prompt_version": _text(payload.get("prompt_version", model_mapping.get("prompt_version"))),
    }
    if any(value is not None for value in result.values()) and not all(result.values()):
        _append_reason(reasons, "llm_provenance_incomplete")
    return result


def _news_ids(payload: Mapping[str, Any], reasons: list[str]) -> list[str]:
    raw = payload.get("news_ids")
    if raw is None:
        identity = payload.get("identity")
        if isinstance(identity, Mapping):
            raw = identity.get("news_ids")
    if raw is None:
        return []
    if isinstance(raw, (str, bytes, Mapping)):
        _append_reason(reasons, "news_ids_invalid")
        return []
    result: list[str] = []
    try:
        values = list(raw)
    except TypeError:
        _append_reason(reasons, "news_ids_invalid")
        return []
    for value in values:
        text = _text(value)
        if text is None:
            _append_reason(reasons, "news_id_invalid")
            continue
        if text not in result:
            result.append(text)
    return result


def _news_items(payload: Mapping[str, Any]) -> tuple[Any, bool]:
    for key in ("news_evidence", "news_items", "news"):
        if key in payload:
            # Root ``news`` may be the explicit normalized component.  Lists
            # and mappings are reserved for evidence so a numeric component is
            # never misclassified as malformed news.
            if key == "news" and not isinstance(payload.get(key), (list, tuple, Mapping)):
                return None, False
            return payload.get(key), True
    return None, False


def validate_news_evidence(
    news: Iterable[Mapping[str, Any]],
    *,
    symbol: str | None,
    decision_at: datetime,
) -> dict[str, Any]:
    """Validate point-in-time news and dedupe syndicated facts.

    Every item needs exact ID, symbol, source, published timestamp and available
    timestamp.  Invalid/future items do not receive a positive score.
    """

    if decision_at.tzinfo is None or decision_at.utcoffset() is None:
        raise OpportunityQualityShadowError("decision_at_timezone_required")
    decision_utc = decision_at.astimezone(timezone.utc)
    expected_symbol = _text(symbol)
    expected_symbol = expected_symbol.upper() if expected_symbol else None
    reasons: list[str] = []
    valid: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_facts: set[str] = set()
    duplicate_count = 0
    invalid_count = 0
    try:
        items = list(news)
    except TypeError:
        return {
            "status": "unavailable",
            "items": [],
            "unique_items": [],
            "valid_count": 0,
            "deduplicated_count": 0,
            "duplicate_count": 0,
            "invalid_count": 1,
            "reason_codes": ["news_items_invalid"],
        }
    for raw in items:
        if not isinstance(raw, Mapping):
            invalid_count += 1
            _append_reason(reasons, "news_item_invalid")
            continue
        news_id = _text(raw.get("news_id", raw.get("id")))
        item_symbol = _text(raw.get("symbol"))
        source = _text(raw.get("source", raw.get("publisher")))
        canonical_hash = _text(raw.get("canonical_hash", raw.get("content_hash")))
        if not news_id or not item_symbol or not source or not canonical_hash:
            invalid_count += 1
            _append_reason(reasons, "news_identity_incomplete")
            continue
        if expected_symbol is None or item_symbol.upper() != expected_symbol:
            invalid_count += 1
            _append_reason(reasons, "news_symbol_mismatch")
            continue
        try:
            published = _utc(raw.get("published_at"), "news_published_at")
            available = _utc(raw.get("available_at"), "news_available_at")
        except OpportunityQualityShadowError:
            invalid_count += 1
            _append_reason(reasons, "news_timestamp_invalid")
            continue
        if published > decision_utc or available > decision_utc:
            invalid_count += 1
            _append_reason(reasons, "news_future_unavailable")
            continue
        if news_id in seen_ids:
            duplicate_count += 1
            _append_reason(reasons, "news_duplicate_id_deduped")
            continue
        seen_ids.add(news_id)
        normalised = dict(raw)
        normalised.update(
            {
                "news_id": news_id,
                "symbol": item_symbol.upper(),
                "source": source,
                "canonical_hash": canonical_hash,
                "published_at": _utc_text(published),
                "available_at": _utc_text(available),
            }
        )
        valid.append(normalised)
    unique: list[dict[str, Any]] = []
    for item in valid:
        fact = item["canonical_hash"]
        if fact in seen_facts:
            duplicate_count += 1
            _append_reason(reasons, "news_duplicate_canonical_fact_deduped")
            continue
        seen_facts.add(fact)
        unique.append(item)
    if not unique:
        _append_reason(reasons, "news_evidence_unavailable")
    return {
        "status": "available" if unique else "unavailable",
        "items": valid,
        "unique_items": unique,
        "valid_count": len(valid),
        "deduplicated_count": len(unique),
        "duplicate_count": duplicate_count,
        "invalid_count": invalid_count,
        "reason_codes": reasons,
    }


def _news_dimensions(items: list[Mapping[str, Any]], reasons: list[str]) -> dict[str, float | None]:
    dimensions: dict[str, float | None] = {}
    for name in ("materiality", "novelty", "economic_relevance"):
        values = [_normalised_unit(item.get(name)) for item in items]
        if not values or any(value is None for value in values):
            dimensions[name] = None
            _append_reason(reasons, f"news_{name}_unavailable")
        else:
            dimensions[name] = sum(value for value in values if value is not None) / len(values)
    optional_sentiment = [_normalised_unit(item.get("sentiment")) for item in items]
    dimensions["sentiment"] = (
        sum(value for value in optional_sentiment if value is not None) / len(optional_sentiment)
        if optional_sentiment and all(value is not None for value in optional_sentiment)
        else None
    )
    priced = [_normalised_unit(item.get("priced_in")) for item in items]
    dimensions["priced_in"] = (
        sum(value for value in priced if value is not None) / len(priced)
        if priced and all(value is not None for value in priced)
        else None
    )
    return dimensions


def _news_component(
    payload: Mapping[str, Any],
    *,
    identity: Mapping[str, str],
    decision_at: datetime,
    reasons: list[str],
) -> tuple[float | None, dict[str, Any]]:
    raw_news, supplied = _news_items(payload)
    declared_ids = _news_ids(payload, reasons)
    if not supplied:
        _append_reason(reasons, "news_evidence_unavailable")
        return None, {
            "status": "unavailable",
            "ids": declared_ids,
            "items": [],
            "unique_items": [],
            "dimensions": {},
        }
    if isinstance(raw_news, (str, bytes, Mapping)) or raw_news is None:
        validation = validate_news_evidence([], symbol=identity.get("symbol"), decision_at=decision_at)
        _append_reason(reasons, "news_items_invalid")
        return None, validation
    validation = validate_news_evidence(raw_news, symbol=identity.get("symbol"), decision_at=decision_at)
    for reason in validation["reason_codes"]:
        _append_reason(reasons, reason)
    unique = validation["unique_items"]
    actual_ids = [item["news_id"] for item in unique]
    if declared_ids and set(declared_ids) != set(actual_ids):
        _append_reason(reasons, "news_declared_id_not_validated")
        _append_reason(reasons, "component_news_invalid_evidence")
        return None, validation
    dimensions = _news_dimensions(unique, reasons) if unique else {}
    validation["dimensions"] = dimensions
    direct = _component_value(payload, "news", reasons) if "news" in payload else None
    # Any invalid or future item invalidates declared news quality.  A numeric
    # value cannot override temporal or identity failures in supplied evidence.
    if validation["invalid_count"] and direct is not None:
        _append_reason(reasons, "component_news_invalid_evidence")
        return None, validation
    if direct is not None and unique:
        return direct, validation
    required = [dimensions.get(name) for name in ("materiality", "novelty", "economic_relevance")]
    if unique and all(value is not None for value in required):
        return sum(value for value in required if value is not None) / len(required), validation
    _append_reason(reasons, "component_news_unavailable")
    return None, validation


def calibrate_empirical_llm_reliability(
    outcomes: Iterable[Mapping[str, Any]],
    *,
    as_of: datetime,
    model_id: str,
    model_version: str,
    prompt_version: str,
    horizon_sessions: int = PRIMARY_HORIZON,
    identity: Mapping[str, Any] | None = None,
    min_mature_outcomes: int = MIN_MATURE_LLM_OUTCOMES,
) -> dict[str, Any]:
    """Calibrate LLM reliability from mature real outcomes only.

    Rows require exact recommendation/capture identity, model/version/prompt,
    horizon, and decision/maturity timestamps.  Duplicate outcome IDs are
    idempotent; conflicting content is rejected.  Shadow/fallback rows never
    enter real learning.
    """

    as_of_utc = _decision_time(as_of)
    expected_identity = {key: _text(value) for key, value in (identity or {}).items() if _text(value)}
    expected_model = (_text(model_id), _text(model_version), _text(prompt_version))
    reasons: list[str] = []
    base_result = {
        "value": None,
        "mature_count": 0,
        "min_mature_outcomes": MIN_MATURE_LLM_OUTCOMES,
        "reason_codes": reasons,
        "as_of": _utc_text(as_of_utc),
        "model_id": expected_model[0],
        "model_version": expected_model[1],
        "prompt_version": expected_model[2],
        "horizon_sessions": horizon_sessions,
        "evidence_ids": [],
        "coverage": {
            "raw_rows": 0,
            "deduplicated_rows": 0,
            "eligible_rows": 0,
            "required_minimum": MIN_MATURE_LLM_OUTCOMES,
        },
        "binding": {
            "identity": expected_identity,
            "model_id": expected_model[0],
            "model_version": expected_model[1],
            "prompt_version": expected_model[2],
            "horizon_sessions": horizon_sessions,
        },
        "receipt_id": None,
    }
    if not all(expected_model):
        _append_reason(reasons, "llm_provenance_incomplete")
        return {"status": "unavailable", **base_result}
    if not all(expected_identity.get(key) for key in ("recommendation_id", "signal_capture_id")):
        _append_reason(reasons, "llm_calibration_identity_required")
        return {"status": "unavailable", **base_result}
    if horizon_sessions not in SUPPORTED_HORIZONS:
        _append_reason(reasons, "horizon_unsupported")
        return {"status": "unavailable", **base_result}
    values: list[float] = []
    evidence_ids: list[str] = []
    seen_outcomes: dict[str, str] = {}
    conflict = False
    try:
        rows = list(outcomes)
    except TypeError:
        rows = []
        _append_reason(reasons, "llm_outcomes_invalid")
    base_result["coverage"]["raw_rows"] = len(rows)
    for row in rows:
        if not isinstance(row, Mapping):
            _append_reason(reasons, "llm_outcome_invalid")
            continue
        outcome_id = _text(row.get("outcome_id", row.get("evidence_id")))
        if outcome_id is None:
            _append_reason(reasons, "llm_outcome_identity_missing")
            continue
        fingerprint_payload = {key: value for key, value in row.items() if key not in {"captured_at", "observed_at", "recorded_at"}}
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        previous = seen_outcomes.get(outcome_id)
        if previous is not None:
            if previous != fingerprint:
                conflict = True
                _append_reason(reasons, "llm_outcome_identity_conflict")
            else:
                _append_reason(reasons, "llm_outcome_duplicate_deduped")
            continue
        seen_outcomes[outcome_id] = fingerprint
        outcome_source = str(row.get("source") or row.get("learning_source") or "").lower()
        if (
            bool(row.get("is_shadow"))
            or bool(row.get("fallback"))
            or bool(row.get("is_fallback"))
            or bool(row.get("fallback_reason"))
            or "fallback" in str(row.get("decision_origin") or "").lower()
            or outcome_source in {
            "shadow",
            "score_shadow",
            "opportunity_quality_shadow",
            "fallback",
            "llm_fallback",
            }
        ):
            _append_reason(reasons, "llm_shadow_or_fallback_outcome_excluded")
            continue
        if any(
            _text(row.get(field)) != expected
            for field, expected in (
                ("model_id", expected_model[0]),
                ("model_version", expected_model[1]),
                ("prompt_version", expected_model[2]),
            )
        ):
            continue
        try:
            row_horizon = int(row.get("horizon_sessions"))
        except (TypeError, ValueError):
            continue
        if row_horizon != horizon_sessions:
            continue
        row_identity = row.get("identity") if isinstance(row.get("identity"), Mapping) else row
        if any(_text(row_identity.get(key)) != expected for key, expected in expected_identity.items()):
            _append_reason(reasons, "llm_outcome_identity_mismatch")
            continue
        maturity_raw = row.get("outcome_matured_at", row.get("matured_at"))
        try:
            matured = _utc(maturity_raw, "outcome_matured_at")
        except OpportunityQualityShadowError:
            continue
        decision_raw = row.get("decision_at")
        try:
            decision = _utc(decision_raw, "outcome_decision_at")
        except OpportunityQualityShadowError:
            _append_reason(reasons, "llm_outcome_decision_time_missing")
            continue
        if not decision < matured:
            _append_reason(reasons, "llm_outcome_maturity_order_invalid")
            continue
        if matured > as_of_utc or row.get("mature") is False:
            _append_reason(reasons, "llm_outcome_not_matured")
            continue
        value = _normalised_unit(row.get("reliability"))
        if value is None:
            success = row.get("outcome_success")
            if type(success) is bool:
                value = 1.0 if success else 0.0
            else:
                net = _finite(row.get("net_expectancy", row.get("net_return")))
                if net is not None:
                    value = 1.0 if net > 0 else 0.0
        if value is None:
            _append_reason(reasons, "llm_outcome_value_invalid")
            continue
        values.append(value)
        evidence_ids.append(outcome_id)
    base_result["coverage"]["deduplicated_rows"] = len(seen_outcomes)
    base_result["coverage"]["eligible_rows"] = len(values)
    base_result["mature_count"] = len(values)
    base_result["evidence_ids"] = evidence_ids
    min_count = max(MIN_MATURE_LLM_OUTCOMES, int(min_mature_outcomes))
    base_result["min_mature_outcomes"] = min_count
    base_result["coverage"]["required_minimum"] = min_count
    if conflict:
        _append_reason(reasons, "llm_outcome_identity_conflict")
    if conflict or len(values) < min_count:
        _append_reason(reasons, "llm_calibration_insufficient_mature_outcomes")
        return {"status": "unavailable", **base_result}
    base_result["value"] = round(sum(values) / len(values), 8)
    receipt_material = {
        "binding": base_result["binding"],
        "as_of": base_result["as_of"],
        "evidence_ids": evidence_ids,
        "coverage": base_result["coverage"],
        "value": base_result["value"],
    }
    base_result["receipt_id"] = hashlib.sha256(
        json.dumps(receipt_material, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "status": "available",
        **base_result,
    }


build_empirical_llm_reliability = calibrate_empirical_llm_reliability


def _frozen_bins(
    prior_receipt: Mapping[str, Any] | None,
    *,
    policy_hash: str,
    as_of: datetime | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    reasons: list[str] = []
    if not isinstance(prior_receipt, Mapping):
        return [], ["current_score_prior_receipt_unavailable"]
    if prior_receipt.get("status") not in {None, "available"}:
        reasons.append("current_score_prior_receipt_unavailable")
    if prior_receipt.get("bins_frozen") is not True and prior_receipt.get("frozen") is not True:
        reasons.append("current_score_bins_not_frozen")
    if _text(prior_receipt.get("policy_hash")) != policy_hash:
        reasons.append("current_score_policy_hash_mismatch")
    if as_of is not None and prior_receipt.get("calibration_as_of", prior_receipt.get("as_of")) is not None:
        try:
            prior_as_of = _utc(
                prior_receipt.get("calibration_as_of", prior_receipt.get("as_of")),
                "current_score_prior_receipt_as_of",
            )
            if prior_as_of > as_of.astimezone(timezone.utc):
                reasons.append("current_score_prior_receipt_as_of_after_calibration")
        except OpportunityQualityShadowError:
            reasons.append("current_score_prior_receipt_as_of_invalid")
    raw_bins = prior_receipt.get("frozen_bins", prior_receipt.get("bins"))
    if isinstance(raw_bins, (str, bytes, Mapping)) or raw_bins is None:
        return [], reasons + ["current_score_bins_invalid"]
    try:
        items = list(raw_bins)
    except TypeError:
        return [], reasons + ["current_score_bins_invalid"]
    result: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, Mapping):
            reasons.append("current_score_bin_invalid")
            continue
        label = _text(raw.get("label"))
        lower = _finite(raw.get("lower", raw.get("min")))
        upper = _finite(raw.get("upper", raw.get("max")))
        if label is None or lower is None or upper is None or lower >= upper:
            reasons.append("current_score_bin_invalid")
            continue
        result.append({"label": label, "lower": lower, "upper": upper})
    result.sort(key=lambda item: (item["lower"], item["upper"], item["label"]))
    previous_upper: float | None = None
    for item in result:
        if previous_upper is not None and item["lower"] < previous_upper:
            reasons.append("current_score_bins_overlap")
        previous_upper = item["upper"]
    if not result:
        reasons.append("current_score_bins_invalid")
    return result, list(dict.fromkeys(reasons))


def _score_bin(score: float, bins: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    for index, item in enumerate(bins):
        lower = float(item["lower"])
        upper = float(item["upper"])
        if lower <= score < upper or (index == len(bins) - 1 and score == upper):
            return item
    return None


def calibrate_current_selection_score(
    outcomes: Iterable[Mapping[str, Any]],
    *,
    as_of: datetime,
    policy_hash: str,
    prior_receipt: Mapping[str, Any] | None,
    currency: str = "USD",
    horizon_sessions: int = CURRENT_SCORE_HORIZON,
    identity: Mapping[str, Any] | None = None,
    min_mature_outcomes: int = MIN_MATURE_CURRENT_SCORE_OUTCOMES,
) -> dict[str, Any]:
    """Calibrate raw selection scores using frozen bins and mature net returns.

    Bins come only from an explicit prior receipt.  The helper reports empirical
    net return after costs and empirical positive probability separately from
    the optional 0-100 calibrated score.
    """

    as_of_utc = _decision_time(as_of)
    expected_policy_hash = _text(policy_hash)
    expected_currency = _text(currency)
    expected_identity = {key: _text(value) for key, value in (identity or {}).items() if _text(value)}
    reasons: list[str] = []
    bins, bin_reasons = _frozen_bins(prior_receipt, policy_hash=expected_policy_hash or "", as_of=as_of_utc)
    for reason in bin_reasons:
        _append_reason(reasons, reason)
    base = {
        "value": None,
        "status": "unavailable",
        "policy_hash": expected_policy_hash,
        "calibration_as_of": _utc_text(as_of_utc),
        "as_of": _utc_text(as_of_utc),
        "currency": expected_currency,
        "horizon_sessions": horizon_sessions,
        "bins_frozen": bool(bins) and not bin_reasons,
        "frozen_bins": bins,
        "bins": [],
        "mature_count": 0,
        "min_mature_outcomes": MIN_MATURE_CURRENT_SCORE_OUTCOMES,
        "evidence_ids": [],
        "coverage": {
            "raw_rows": 0,
            "deduplicated_rows": 0,
            "eligible_rows": 0,
            "required_minimum": MIN_MATURE_CURRENT_SCORE_OUTCOMES,
        },
        "binding": {
            "identity": expected_identity,
            "policy_hash": expected_policy_hash,
            "currency": expected_currency,
            "horizon_sessions": horizon_sessions,
        },
        "receipt_id": None,
        "reason_codes": reasons,
        "value_kind": "empirical_net_return_after_costs",
        "probability_kind": "empirical_positive_net_return_probability",
        "score_kind": "calibrated_score_0_100",
    }
    if not expected_policy_hash:
        _append_reason(reasons, "current_score_policy_hash_missing")
    if not expected_currency:
        _append_reason(reasons, "current_score_currency_missing")
    if horizon_sessions != CURRENT_SCORE_HORIZON:
        _append_reason(reasons, "current_score_horizon_unsupported")
    if not expected_identity or not all(expected_identity.get(key) for key in ("recommendation_id", "signal_capture_id")):
        _append_reason(reasons, "current_score_identity_required")
    try:
        rows = list(outcomes)
    except TypeError:
        rows = []
        _append_reason(reasons, "current_score_outcomes_invalid")
    base["coverage"]["raw_rows"] = len(rows)
    if reasons:
        return base
    seen: dict[str, str] = {}
    accepted: list[tuple[str, float, float]] = []
    conflict = False
    for row in rows:
        if not isinstance(row, Mapping):
            _append_reason(reasons, "current_score_outcome_invalid")
            continue
        outcome_id = _text(row.get("outcome_id", row.get("evidence_id")))
        if outcome_id is None:
            _append_reason(reasons, "current_score_outcome_identity_missing")
            continue
        fingerprint_payload = {
            key: value for key, value in row.items() if key not in {"captured_at", "observed_at", "recorded_at"}
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        if outcome_id in seen:
            if seen[outcome_id] != fingerprint:
                conflict = True
                _append_reason(reasons, "current_score_outcome_identity_conflict")
            else:
                _append_reason(reasons, "current_score_outcome_duplicate_deduped")
            continue
        seen[outcome_id] = fingerprint
        outcome_source = str(row.get("source") or row.get("learning_source") or "").lower()
        if (
            bool(row.get("is_shadow"))
            or bool(row.get("fallback"))
            or bool(row.get("is_fallback"))
            or bool(row.get("fallback_reason"))
            or "fallback" in str(row.get("decision_origin") or "").lower()
            or outcome_source in {"shadow", "score_shadow", "opportunity_quality_shadow", "fallback", "llm_fallback"}
        ):
            _append_reason(reasons, "current_score_shadow_or_fallback_outcome_excluded")
            continue
        row_identity = row.get("identity") if isinstance(row.get("identity"), Mapping) else row
        if any(_text(row_identity.get(key)) != expected for key, expected in expected_identity.items()):
            _append_reason(reasons, "current_score_outcome_identity_mismatch")
            continue
        if _text(row.get("currency")) != expected_currency:
            _append_reason(reasons, "current_score_currency_mismatch")
            continue
        try:
            if int(row.get("horizon_sessions")) != CURRENT_SCORE_HORIZON:
                _append_reason(reasons, "current_score_horizon_mismatch")
                continue
        except (TypeError, ValueError):
            _append_reason(reasons, "current_score_horizon_mismatch")
            continue
        if row.get("costs_included") is not True:
            _append_reason(reasons, "current_score_costs_missing")
            continue
        score = _finite(row.get("current_selection_score"))
        net_return = _finite(row.get("net_return_after_costs", row.get("net_5_session_after_costs")))
        if score is None or net_return is None:
            _append_reason(reasons, "current_score_outcome_value_invalid")
            continue
        try:
            decision = _utc(row.get("decision_at"), "current_score_decision_at")
            matured = _utc(row.get("outcome_matured_at", row.get("matured_at")), "current_score_matured_at")
        except OpportunityQualityShadowError:
            _append_reason(reasons, "current_score_outcome_time_invalid")
            continue
        if not decision < matured or matured > as_of_utc:
            _append_reason(reasons, "current_score_outcome_not_matured")
            continue
        if _score_bin(score, bins) is None:
            _append_reason(reasons, "current_score_outcome_outside_frozen_bins")
            continue
        accepted.append((outcome_id, score, net_return))
    base["coverage"]["deduplicated_rows"] = len(seen)
    base["coverage"]["eligible_rows"] = len(accepted)
    base["mature_count"] = len(accepted)
    base["evidence_ids"] = [item[0] for item in accepted]
    min_count = max(MIN_MATURE_CURRENT_SCORE_OUTCOMES, int(min_mature_outcomes))
    base["min_mature_outcomes"] = min_count
    base["coverage"]["required_minimum"] = min_count
    if conflict or len(accepted) < min_count:
        _append_reason(reasons, "current_score_calibration_insufficient_mature_outcomes")
        return base
    for frozen_bin in bins:
        members = [item for item in accepted if _score_bin(item[1], [frozen_bin]) is not None]
        net_returns = [item[2] for item in members]
        probability = sum(value > 0 for value in net_returns) / len(net_returns) if net_returns else None
        bin_result = {
            **frozen_bin,
            "sample_count": len(members),
            "empirical_net_return_after_costs": round(sum(net_returns) / len(net_returns), 8) if net_returns else None,
            "empirical_positive_net_return_probability": round(probability, 8) if probability is not None else None,
            "calibrated_score_0_100": round(probability * 100.0, 8) if probability is not None else None,
        }
        base["bins"].append(bin_result)
    receipt_material = {
        "binding": base["binding"],
        "calibration_as_of": base["calibration_as_of"],
        "evidence_ids": base["evidence_ids"],
        "bins": base["bins"],
        "coverage": base["coverage"],
    }
    base["receipt_id"] = hashlib.sha256(
        json.dumps(receipt_material, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    base["status"] = "available"
    return base


def _current_score_calibration(
    payload: Mapping[str, Any],
    *,
    raw_score: float | None,
    identity: Mapping[str, str],
    horizon: int | None,
    horizon_valid: bool,
    decision_at: datetime,
    policy_hash: str | None,
    reasons: list[str],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "unavailable",
        "raw_selection_score": raw_score,
        "calibrated_score_0_100": None,
        "empirical_net_return_after_costs": None,
        "empirical_positive_net_return_probability": None,
        "value_kind": "empirical_net_return_after_costs",
        "probability_kind": "empirical_positive_net_return_probability",
        "score_kind": "calibrated_score_0_100",
        "receipt_id": None,
        "reason_codes": [],
    }
    receipt = None
    for key in ("champion_calibration", "current_score_calibration"):
        if isinstance(payload.get(key), Mapping):
            receipt = payload[key]
            break
    if raw_score is None:
        _append_reason(result["reason_codes"], "current_selection_score_unavailable")
    if receipt is None:
        _append_reason(result["reason_codes"], "current_score_calibration_receipt_unavailable")
        for reason in result["reason_codes"]:
            _append_reason(reasons, reason)
        return result
    if receipt.get("status") != "available":
        _append_reason(result["reason_codes"], "current_score_calibration_unavailable")
    if receipt.get("bins_frozen") is not True:
        _append_reason(result["reason_codes"], "current_score_bins_not_frozen")
    if not policy_hash or _text(receipt.get("policy_hash")) != policy_hash:
        _append_reason(result["reason_codes"], "current_score_policy_hash_mismatch")
    if not horizon_valid or horizon != CURRENT_SCORE_HORIZON or receipt.get("horizon_sessions") != CURRENT_SCORE_HORIZON:
        _append_reason(result["reason_codes"], "current_score_horizon_invalid")
    if _text(receipt.get("currency")) is None:
        _append_reason(result["reason_codes"], "current_score_currency_missing")
    payload_currency = _text(payload.get("currency"))
    if payload_currency is None:
        _append_reason(result["reason_codes"], "current_score_currency_unavailable")
    elif _text(receipt.get("currency")) != payload_currency:
        _append_reason(result["reason_codes"], "current_score_currency_mismatch")
    try:
        calibration_as_of = _utc(receipt.get("calibration_as_of", receipt.get("as_of")), "current_score_calibration_as_of")
    except OpportunityQualityShadowError:
        calibration_as_of = None
        _append_reason(result["reason_codes"], "current_score_calibration_as_of_invalid")
    if calibration_as_of is not None and calibration_as_of > decision_at.astimezone(timezone.utc):
        _append_reason(result["reason_codes"], "current_score_calibration_as_of_after_decision")
    try:
        mature_count = int(receipt.get("mature_count"))
        min_count = int(receipt.get("min_mature_outcomes", MIN_MATURE_CURRENT_SCORE_OUTCOMES))
    except (TypeError, ValueError):
        mature_count = min_count = 0
    if mature_count < MIN_MATURE_CURRENT_SCORE_OUTCOMES or min_count < MIN_MATURE_CURRENT_SCORE_OUTCOMES or mature_count < min_count:
        _append_reason(result["reason_codes"], "current_score_calibration_insufficient_mature_outcomes")
    evidence_ids = receipt.get("evidence_ids")
    if (
        isinstance(evidence_ids, (str, bytes, Mapping))
        or not evidence_ids
        or len(evidence_ids) != mature_count
    ):
        _append_reason(result["reason_codes"], "current_score_evidence_ids_invalid")
    else:
        try:
            if any(_text(value) is None for value in evidence_ids) or len(evidence_ids) != len(set(evidence_ids)):
                _append_reason(result["reason_codes"], "current_score_evidence_ids_invalid")
        except TypeError:
            _append_reason(result["reason_codes"], "current_score_evidence_ids_invalid")
    binding = receipt.get("binding")
    if not isinstance(binding, Mapping) or _text(receipt.get("receipt_id")) is None:
        _append_reason(result["reason_codes"], "current_score_binding_invalid")
    else:
        binding_identity = binding.get("identity")
        if isinstance(binding_identity, Mapping):
            for key in ("candidate_id", "signal_capture_id", "recommendation_id"):
                if _text(binding_identity.get(key)) != identity.get(key):
                    _append_reason(result["reason_codes"], "current_score_binding_mismatch")
        if (
            _text(binding.get("policy_hash")) != policy_hash
            or binding.get("horizon_sessions") != horizon
            or _text(binding.get("currency")) != _text(receipt.get("currency"))
        ):
            _append_reason(result["reason_codes"], "current_score_binding_mismatch")
    coverage = receipt.get("coverage")
    if not isinstance(coverage, Mapping):
        _append_reason(result["reason_codes"], "current_score_coverage_invalid")
    else:
        try:
            if int(coverage.get("eligible_rows")) != mature_count or int(coverage.get("deduplicated_rows")) < mature_count:
                _append_reason(result["reason_codes"], "current_score_coverage_invalid")
        except (TypeError, ValueError):
            _append_reason(result["reason_codes"], "current_score_coverage_invalid")
    rows = receipt.get("bins")
    selected = _score_bin(raw_score, rows) if raw_score is not None and isinstance(rows, list) else None
    if selected is None:
        _append_reason(result["reason_codes"], "current_score_bin_unavailable")
    else:
        result.update(
            {
                "status": "available" if not result["reason_codes"] else "unavailable",
                "bin_label": selected.get("label"),
                "bin_sample_count": selected.get("sample_count"),
                "calibrated_score_0_100": selected.get("calibrated_score_0_100"),
                "empirical_net_return_after_costs": selected.get("empirical_net_return_after_costs"),
                "empirical_positive_net_return_probability": selected.get(
                    "empirical_positive_net_return_probability"
                ),
                "receipt_id": receipt.get("receipt_id"),
            }
        )
    for reason in result["reason_codes"]:
        _append_reason(reasons, reason)
    return result


def _llm_component(
    payload: Mapping[str, Any],
    *,
    reasons: list[str],
    identity: Mapping[str, str],
    horizon: int | None,
    horizon_valid: bool,
    decision_at: datetime,
) -> float | None:
    llm = payload.get("llm")
    llm_mapping = llm if isinstance(llm, Mapping) else {}
    if bool(llm_mapping.get("fallback")) or bool(llm_mapping.get("is_fallback")) or bool(payload.get("llm_fallback")):
        _append_reason(reasons, "llm_fallback_unavailable")
        return None
    if "self_confidence" in llm_mapping or "confidence" in llm_mapping:
        _append_reason(reasons, "llm_self_confidence_ignored")
    receipt = None
    for key in ("llm_calibration", "empirical_llm_calibration", "calibration_receipt"):
        if isinstance(payload.get(key), Mapping):
            receipt = payload[key]
            break
    if receipt is None:
        _append_reason(reasons, "llm_calibration_receipt_unavailable")
        return None
    if receipt.get("status") != "available":
        _append_reason(reasons, "llm_calibration_unavailable")
        return None
    try:
        mature_count = int(receipt.get("mature_count"))
        declared_minimum = int(receipt.get("min_mature_outcomes", MIN_MATURE_LLM_OUTCOMES))
    except (TypeError, ValueError):
        _append_reason(reasons, "llm_calibration_coverage_invalid")
        return None
    if mature_count < MIN_MATURE_LLM_OUTCOMES or declared_minimum < MIN_MATURE_LLM_OUTCOMES or mature_count < declared_minimum:
        _append_reason(reasons, "llm_calibration_insufficient_mature_outcomes")
        return None
    if not horizon_valid or horizon is None:
        _append_reason(reasons, "llm_calibration_horizon_invalid")
        return None
    provenance = _model_provenance(payload, reasons)
    receipt_provenance = {
        "model_id": _text(receipt.get("model_id")),
        "model_version": _text(receipt.get("model_version")),
        "prompt_version": _text(receipt.get("prompt_version")),
    }
    if not all(provenance.values()) or provenance != receipt_provenance:
        _append_reason(reasons, "llm_provenance_unavailable")
        return None
    try:
        receipt_horizon = int(receipt.get("horizon_sessions"))
    except (TypeError, ValueError):
        _append_reason(reasons, "llm_calibration_horizon_invalid")
        return None
    if receipt_horizon != horizon:
        _append_reason(reasons, "llm_calibration_horizon_mismatch")
        return None
    try:
        receipt_as_of = _utc(receipt.get("as_of"), "llm_calibration_as_of")
    except OpportunityQualityShadowError:
        _append_reason(reasons, "llm_calibration_as_of_invalid")
        return None
    if receipt_as_of > decision_at.astimezone(timezone.utc):
        _append_reason(reasons, "llm_calibration_as_of_after_decision")
        return None
    evidence_ids = receipt.get("evidence_ids")
    if isinstance(evidence_ids, (str, bytes, Mapping)) or not evidence_ids:
        _append_reason(reasons, "llm_calibration_evidence_ids_invalid")
        return None
    try:
        evidence_ids = [_text(value) for value in list(evidence_ids)]
    except TypeError:
        _append_reason(reasons, "llm_calibration_evidence_ids_invalid")
        return None
    if any(value is None for value in evidence_ids) or len(evidence_ids) != len(set(evidence_ids)):
        _append_reason(reasons, "llm_calibration_evidence_ids_invalid")
        return None
    coverage = receipt.get("coverage")
    if not isinstance(coverage, Mapping):
        _append_reason(reasons, "llm_calibration_coverage_invalid")
        return None
    try:
        coverage_eligible = int(coverage.get("eligible_rows"))
        coverage_deduplicated = int(coverage.get("deduplicated_rows"))
    except (TypeError, ValueError):
        _append_reason(reasons, "llm_calibration_coverage_invalid")
        return None
    if coverage_eligible != mature_count or coverage_deduplicated < mature_count or len(evidence_ids) != mature_count:
        _append_reason(reasons, "llm_calibration_coverage_invalid")
        return None
    binding = receipt.get("binding")
    binding_identity = binding.get("identity") if isinstance(binding, Mapping) else None
    if not isinstance(binding, Mapping) or not isinstance(binding_identity, Mapping) or _text(receipt.get("receipt_id")) is None:
        _append_reason(reasons, "llm_calibration_binding_invalid")
        return None
    if (
        _text(binding.get("model_id")) != provenance["model_id"]
        or _text(binding.get("model_version")) != provenance["model_version"]
        or _text(binding.get("prompt_version")) != provenance["prompt_version"]
        or binding.get("horizon_sessions") != horizon
    ):
        _append_reason(reasons, "llm_calibration_binding_mismatch")
        return None
    for key in ("candidate_id", "signal_capture_id", "recommendation_id"):
        if _text(binding_identity.get(key)) != identity.get(key):
            _append_reason(reasons, "llm_calibration_binding_mismatch")
            return None
    value = _normalised_unit(receipt.get("value"))
    if value is None:
        _append_reason(reasons, "llm_calibration_value_invalid")
        return None
    return value


def _validated_expectancy(
    payload: Mapping[str, Any],
    horizon: int | None,
    horizon_valid: bool,
    reasons: list[str],
    *,
    decision_at: datetime,
    policy_version: str,
) -> dict[str, Any]:
    raw = payload.get("validated_net_expectancy")
    if raw is None:
        raw = payload.get("net_expectancy_evidence")
    if not isinstance(raw, Mapping):
        _append_reason(reasons, "validated_net_expectancy_unavailable")
        return {"validated": False, "value": None, "horizon_sessions": horizon}
    evidence_id = _text(raw.get("evidence_id"))
    evidence_time_raw = raw.get("as_of", raw.get("validated_at"))
    costs_included = raw.get("costs_included") is True
    bound_policy = _text(raw.get("policy_version"))
    evidence_horizon = raw.get("horizon_sessions", horizon)
    try:
        evidence_horizon = int(evidence_horizon)
    except (TypeError, ValueError):
        _append_reason(reasons, "validated_net_expectancy_horizon_invalid")
        return {"validated": False, "value": None, "horizon_sessions": horizon}
    value = _finite(raw.get("value", raw.get("net_expectancy")))
    validated = raw.get("validated") is True
    try:
        evidence_time = _utc(evidence_time_raw, "validated_net_expectancy_as_of")
    except OpportunityQualityShadowError:
        evidence_time = None
    if (
        not horizon_valid
        or evidence_horizon != horizon
        or value is None
        or value <= 0
        or not validated
        or evidence_id is None
        or evidence_time is None
        or evidence_time > decision_at.astimezone(timezone.utc)
        or not costs_included
        or bound_policy != policy_version
    ):
        _append_reason(reasons, "validated_net_expectancy_gate_failed")
        return {
            "validated": False,
            "value": value,
            "horizon_sessions": evidence_horizon,
            "evidence_id": evidence_id,
            "as_of": _utc_text(evidence_time) if evidence_time else None,
            "costs_included": costs_included,
            "policy_version": bound_policy,
        }
    return {
        "validated": True,
        "value": value,
        "horizon_sessions": evidence_horizon,
        "evidence_id": evidence_id,
        "as_of": _utc_text(evidence_time),
        "costs_included": True,
        "policy_version": bound_policy,
    }


def _higher_tier_evidence(
    payload: Mapping[str, Any],
    identity: Mapping[str, str],
    reasons: list[str],
) -> dict[str, Any]:
    raw = payload.get("higher_tier_evidence")
    if not isinstance(raw, Mapping):
        _append_reason(reasons, "higher_tier_evidence_unavailable")
        return {"approved": False, "token": None, "binding": {}}
    approved = raw.get("approved") is True
    token = _text(raw.get("approval_token", raw.get("token")))
    binding = raw.get("binding")
    binding = dict(binding) if isinstance(binding, Mapping) else {}
    if not approved or token is None:
        _append_reason(reasons, "higher_tier_evidence_not_approved")
    if not binding or not identity:
        _append_reason(reasons, "higher_tier_evidence_binding_unavailable")
    for key, expected in identity.items():
        if key in binding and _text(binding[key]) != expected:
            _append_reason(reasons, "higher_tier_evidence_binding_mismatch")
        elif key in {"candidate_id", "signal_capture_id", "recommendation_id"} and key not in binding:
            _append_reason(reasons, "higher_tier_evidence_binding_incomplete")
    return {"approved": approved, "token": token, "binding": binding}


def _high_tier(
    *,
    score: float | None,
    components: Mapping[str, float | None],
    payload: Mapping[str, Any],
    identity: Mapping[str, str],
    horizon: int | None,
    horizon_valid: bool,
    reasons: list[str],
    policy: Mapping[str, Any],
    policy_version: str,
    decision_at: datetime,
) -> dict[str, Any]:
    high_reasons: list[str] = []
    requested_threshold = _finite(policy.get("high_tier_score"))
    threshold = max(HIGH_TIER_SCORE, requested_threshold) if requested_threshold is not None else HIGH_TIER_SCORE
    if requested_threshold is not None and requested_threshold < HIGH_TIER_SCORE:
        _append_reason(high_reasons, "high_tier_threshold_floor_applied")
    identity_complete = all(_text(identity.get(key)) for key in REQUIRED_CANONICAL_IDENTITY)
    if not identity_complete:
        _append_reason(high_reasons, "high_tier_canonical_identity_incomplete")
    if not horizon_valid or horizon is None:
        _append_reason(high_reasons, "high_tier_horizon_invalid")
    expectancy_reasons: list[str] = []
    expectancy = _validated_expectancy(
        payload,
        horizon,
        horizon_valid,
        expectancy_reasons,
        decision_at=decision_at,
        policy_version=policy_version,
    )
    evidence_reasons: list[str] = []
    evidence = _higher_tier_evidence(payload, identity, evidence_reasons)
    hard_gates = payload.get("hard_gates")
    gates = dict(hard_gates) if isinstance(hard_gates, Mapping) else {}
    gates_pass = all(key in gates and gates[key] is True for key in REQUIRED_HIGH_TIER_GATES) and all(
        value is True for value in gates.values()
    )
    if not gates_pass:
        _append_reason(high_reasons, "high_tier_hard_gates_failed")
    complete = all(components.get(name) is not None for name in SCORE_COMPONENTS)
    if not complete:
        _append_reason(high_reasons, "high_tier_components_incomplete")
    if score is None or score < threshold:
        _append_reason(high_reasons, "high_tier_score_threshold_failed")
    for reason in expectancy_reasons + evidence_reasons + high_reasons:
        _append_reason(reasons, reason)
    eligible = bool(
        score is not None
        and score >= threshold
        and complete
        and identity_complete
        and horizon_valid
        and expectancy["validated"]
        and evidence["approved"]
        and evidence["token"]
        and not evidence_reasons
        and gates_pass
    )
    return {
        "eligible": eligible,
        "score_threshold": threshold,
        "components_complete": complete,
        "canonical_identity_complete": identity_complete,
        "horizon_valid": horizon_valid,
        "validated_net_expectancy": expectancy,
        "evidence": evidence,
        "hard_gates": gates,
        "required_hard_gates": list(REQUIRED_HIGH_TIER_GATES),
        "hard_gates_passed": gates_pass,
        "reason_codes": expectancy_reasons + evidence_reasons + high_reasons,
    }


def build_opportunity_quality_carrier(
    payload: Mapping[str, Any],
    *,
    decision_at: datetime,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build SCORE shadow carrier from explicit, prevalidated numeric inputs."""

    if not isinstance(payload, Mapping):
        raise OpportunityQualityShadowError("payload_mapping_required")
    decision_utc = _decision_time(decision_at)
    reasons: list[str] = []
    policy_mapping = policy if isinstance(policy, Mapping) else {}
    identity = _identity(payload, reasons)
    horizon, horizon_valid = _horizon(payload, reasons)
    effective_policy_version = _text(policy_mapping.get("policy_version")) or SCORE_POLICY_VERSION
    effective_policy_hash = _text(payload.get("policy_hash")) or _text(policy_mapping.get("policy_hash"))
    raw_current_selection_score = _finite(payload.get("current_selection_score"))
    current_selection_components = payload.get("current_selection_components")
    if current_selection_components is None:
        current_selection_components = payload.get("selection_components")
    champion_calibration = _current_score_calibration(
        payload,
        raw_score=raw_current_selection_score,
        identity=identity,
        horizon=horizon,
        horizon_valid=horizon_valid,
        decision_at=decision_utc,
        policy_hash=effective_policy_hash,
        reasons=reasons,
    )
    components: dict[str, float | None] = {}
    components["technical"] = _component_value(payload, "technical", reasons)
    components["news"], news = _news_component(
        payload,
        identity=identity,
        decision_at=decision_utc,
        reasons=reasons,
    )
    components["empirical_llm_reliability"] = _llm_component(
        payload,
        reasons=reasons,
        identity=identity,
        horizon=horizon,
        horizon_valid=horizon_valid,
        decision_at=decision_utc,
    )
    components["setup"] = _component_value(payload, "setup", reasons)
    complete = all(value is not None for value in components.values())
    score = (
        round(sum(SCORE_WEIGHTS[name] * float(components[name]) for name in SCORE_COMPONENTS) * 100.0, 8)
        if complete
        else None
    )
    model = _model_provenance(payload, reasons)
    news_ids = [item["news_id"] for item in news.get("unique_items", [])] or _news_ids(payload, reasons)
    high_tier = _high_tier(
        score=score,
        components=components,
        payload=payload,
        identity=identity,
        horizon=horizon,
        horizon_valid=horizon_valid,
        reasons=reasons,
        policy=policy_mapping,
        policy_version=effective_policy_version,
        decision_at=decision_utc,
    )
    # A carrier can report a high-tier failure without making its failure reason
    # appear as a component reason twice.
    reason_codes = list(reasons)
    for reason in high_tier["reason_codes"]:
        _append_reason(reason_codes, reason)
    coverage = {
        "available_components": [name for name in SCORE_COMPONENTS if components[name] is not None],
        "missing_components": [name for name in SCORE_COMPONENTS if components[name] is None],
        "component_count": sum(value is not None for value in components.values()),
        "component_total": len(SCORE_COMPONENTS),
        "ratio": round(sum(value is not None for value in components.values()) / len(SCORE_COMPONENTS), 8),
        "weights_redistributed": False,
    }
    carrier_identity = dict(identity)
    carrier = {
        "schema_version": SCORE_SHADOW_SCHEMA_VERSION,
        "policy_version": effective_policy_version,
        "status": "available" if score is not None else "unavailable",
        "score": score,
        "combined_score": score,
        "challenger_score": score,
        "score_type": "calibrated_challenger",
        "components": components,
        "weights": dict(SCORE_WEIGHTS),
        "current_selection_score": raw_current_selection_score,
        "current_selection_components": current_selection_components,
        "policy_hash": effective_policy_hash,
        "champion_calibration": champion_calibration,
        "coverage": coverage,
        "identity": carrier_identity,
        "carrier_identity": carrier_identity,
        "candidate_id": identity.get("candidate_id"),
        "signal_capture_id": identity.get("signal_capture_id"),
        "signal_id": identity.get("signal_id"),
        "recommendation_id": identity.get("recommendation_id"),
        "cycle_id": identity.get("cycle_id"),
        "symbol": identity.get("symbol"),
        "horizon_sessions": horizon,
        "supported_horizons": list(SUPPORTED_HORIZONS),
        "primary_horizon_sessions": PRIMARY_HORIZON,
        "decision_at": _utc_text(decision_utc),
        "model_id": model["model_id"],
        "model_version": model["model_version"],
        "prompt_version": model["prompt_version"],
        "model": model,
        "news_ids": news_ids,
        "news": news,
        "high_tier": high_tier,
        "reason_codes": reason_codes,
        "authority": {
            "mode": "shadow",
            "shadow_only": True,
            "can_authorize_size": False,
            "size_authorized": False,
            "can_change_orders": False,
            "can_select_candidate": False,
            "can_promote_policy": False,
        },
    }
    return carrier


__all__ = [
    "HIGH_TIER_SCORE",
    "CURRENT_SCORE_HORIZON",
    "MIN_MATURE_CURRENT_SCORE_OUTCOMES",
    "MIN_MATURE_LLM_OUTCOMES",
    "PRIMARY_HORIZON",
    "REQUIRED_CANONICAL_IDENTITY",
    "REQUIRED_HIGH_TIER_GATES",
    "SCORE_COMPONENTS",
    "SCORE_POLICY_VERSION",
    "SCORE_SHADOW_SCHEMA_VERSION",
    "SCORE_WEIGHTS",
    "SUPPORTED_HORIZONS",
    "OpportunityQualityShadowError",
    "build_empirical_llm_reliability",
    "build_opportunity_quality_carrier",
    "calibrate_current_selection_score",
    "calibrate_empirical_llm_reliability",
    "validate_news_evidence",
]
