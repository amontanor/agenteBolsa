"""Adversarial deterministic checks for trade recommendations."""

from __future__ import annotations

from typing import Any

from agente_bolsa.models import TradeRecommendation


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _candidate_for_symbol(technical_context: dict[str, Any] | None, symbol: str) -> dict[str, Any]:
    symbol = str(symbol or "").upper()
    for bucket in ("selected_candidates", "top_longs", "all_candidates"):
        for item in list((technical_context or {}).get(bucket, []) or []):
            if str(item.get("symbol") or "").upper() == symbol:
                return item
    return {}


def review_recommendation_adversarial(
    recommendation: TradeRecommendation,
    *,
    technical_context: dict[str, Any] | None,
    market_state: dict[str, Any] | None,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    entry = _float(recommendation.entry_price)
    stop = _float(recommendation.stop_loss)
    take = _float(recommendation.take_profit)
    candidate = _candidate_for_symbol(technical_context, recommendation.symbol)
    policy = (market_state or {}).get("market_regime_policy") or {}
    quality = ((market_state or {}).get("data_quality") or {}).get("status")

    if str(recommendation.action).lower() == "buy":
        if entry is None or stop is None or take is None or stop >= entry or take <= entry:
            issues.append({"kind": "contradictory_entry_stop_take", "severity": "BLOCK"})
        if quality == "INSUFFICIENT":
            issues.append({"kind": "insufficient_market_state", "severity": "BLOCK"})
        if policy and not policy.get("allow_new_buys", True):
            issues.append({"kind": "regime_policy_blocks_new_buys", "severity": "BLOCK"})
        if policy.get("requires_micro_experiment") and not recommendation.micro_experiment:
            issues.append({"kind": "regime_requires_micro_experiment", "severity": "WARN"})
        if int(candidate.get("duplicate_count") or candidate.get("source_duplicate_count") or 0) > 1:
            issues.append({"kind": "duplicate_signal_sources", "severity": "WARN"})
        if candidate.get("lookahead_warning") or candidate.get("future_data_used"):
            issues.append({"kind": "potential_lookahead_bias", "severity": "BLOCK"})
        if candidate.get("overfit_warning") or candidate.get("parameter_tuning_count", 0) > 2:
            issues.append({"kind": "overfit_or_repeated_tuning", "severity": "WARN"})

    block = any(item["severity"] == "BLOCK" for item in issues)
    return {
        "symbol": recommendation.symbol,
        "action": recommendation.action,
        "approved": not block,
        "issues": issues,
        "reason": "adversarial_review_blocked" if block else "adversarial_review_passed",
    }


def review_recommendations_adversarial(
    recommendations: list[TradeRecommendation],
    *,
    technical_context: dict[str, Any] | None,
    market_state: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    return [
        review_recommendation_adversarial(
            recommendation,
            technical_context=technical_context,
            market_state=market_state,
        )
        for recommendation in recommendations
    ]
