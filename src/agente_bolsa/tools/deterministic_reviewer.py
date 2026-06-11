"""Deterministic review layer to reduce single-LLM monoculture."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.models import TradeRecommendation


def recommendation_input_fingerprint(
    recommendation: TradeRecommendation,
    *,
    market_snapshot: dict[str, Any] | None,
    market_state: dict[str, Any] | None,
    technical_context: dict[str, Any] | None,
    sentiment_context: dict[str, Any] | None,
    model_info: dict[str, Any] | None,
    gate_config: dict[str, Any] | None,
) -> str:
    payload = {
        "recommendation": asdict(recommendation),
        "market_snapshot": market_snapshot or {},
        "market_state": market_state or {},
        "technical_context": technical_context or {},
        "sentiment_context": sentiment_context or {},
        "model_info": model_info or {},
        "gate_config": gate_config or {},
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


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


def _sentiment_for_symbol(sentiment_context: dict[str, Any] | None, symbol: str) -> dict[str, Any]:
    symbol = str(symbol or "").upper()
    for item in list((sentiment_context or {}).get("results", []) or []):
        if str(item.get("symbol") or "").upper() == symbol:
            return item
    return {}


def _reward_risk(recommendation: TradeRecommendation) -> float | None:
    entry = _float(recommendation.entry_price)
    stop = _float(recommendation.stop_loss)
    take = _float(recommendation.take_profit)
    if entry is None or stop is None or take is None or entry <= 0 or stop >= entry or take <= entry:
        return None
    risk = entry - stop
    reward = take - entry
    if risk <= 0:
        return None
    return round(reward / risk, 4)


def review_recommendations(
    settings: Settings,
    recommendations: list[TradeRecommendation],
    technical_context: dict[str, Any] | None,
    sentiment_context: dict[str, Any] | None,
    market_state: dict[str, Any] | None,
) -> tuple[list[TradeRecommendation], list[dict[str, Any]]]:
    reviewed: list[TradeRecommendation] = []
    decisions: list[dict[str, Any]] = []
    regime = str((market_state or {}).get("market_regime") or "unknown").lower()
    quality = str(((market_state or {}).get("data_quality") or {}).get("status") or "unknown").upper()
    regime_policy = (market_state or {}).get("market_regime_policy") or {}

    for recommendation in recommendations:
        if str(recommendation.action).lower() != "buy":
            reviewed.append(recommendation)
            continue

        candidate = _candidate_for_symbol(technical_context, recommendation.symbol)
        sentiment_row = _sentiment_for_symbol(sentiment_context, recommendation.symbol)
        sentiment = sentiment_row.get("sentiment", {}) if isinstance(sentiment_row, dict) else {}
        reward_risk = _reward_risk(recommendation)
        score = int(candidate.get("score") or 0)
        duplicate_count = int(candidate.get("duplicate_count") or candidate.get("source_duplicate_count") or 0)
        sentiment_score = _float(sentiment.get("sentiment_score"))
        data_quality_notes = list(((market_state or {}).get("data_quality") or {}).get("notes") or [])
        checks = {
            "entry_stop_take_present": all(
                _float(value) is not None for value in [recommendation.entry_price, recommendation.stop_loss, recommendation.take_profit]
            ),
            "reward_risk": reward_risk,
            "score": score,
            "duplicate_count": duplicate_count,
            "market_regime": regime,
            "market_state_quality": quality,
            "market_state_quality_notes": data_quality_notes,
            "market_regime_policy": regime_policy,
            "sentiment_score": sentiment_score,
            "material_risk": bool(sentiment_row.get("material_risk")),
        }
        approved = True
        reason = "deterministic_review_aprobado"
        mutated = recommendation

        if not checks["entry_stop_take_present"]:
            approved = False
            reason = "faltan entry/stop/take"
        elif reward_risk is None or reward_risk < settings.entry_score_v2_min_reward_risk:
            approved = False
            reason = "reward_risk_insuficiente"
        elif score and score < settings.entry_quality_min_score:
            approved = False
            reason = "score_tecnico_bajo"
        elif sentiment_score is not None and sentiment_score <= -0.5:
            approved = False
            reason = "sentimiento_negativo_material"
        elif bool(sentiment_row.get("material_risk")):
            approved = False
            reason = "material_risk"
        elif quality == "INSUFFICIENT":
            approved = False
            reason = "market_state_data_quality_insufficient"
        elif regime_policy and not regime_policy.get("allow_new_buys", True):
            approved = False
            reason = str(regime_policy.get("reason") or "market_regime_policy_blocks_new_buys")
        elif (
            regime_policy.get("requires_micro_experiment")
            or regime == "bearish"
            or quality == "PARTIAL"
            or duplicate_count > 1
        ):
            if settings.trading_mode == "paper":
                mutated = replace(
                    recommendation,
                    micro_experiment=True,
                    size_multiplier=min(
                        float(recommendation.size_multiplier or 1.0),
                        float(regime_policy.get("size_multiplier") or settings.micro_experiment_size_multiplier),
                    ),
                    soft_override_reasons=[
                        *list(recommendation.soft_override_reasons or []),
                        f"deterministic_review:{regime_policy.get('profile') or ('adverse_regime' if regime == 'bearish' else 'partial_state_or_duplicate')}",
                    ],
                )
                reason = "micro_experiment_required"
            else:
                approved = False
                reason = "regimen_adverso_o_calidad_parcial"

        reviewed.append(mutated if approved else recommendation)
        decisions.append(
            {
                "symbol": recommendation.symbol,
                "action": recommendation.action,
                "approved": approved,
                "reason": reason,
                "checks": checks,
                "micro_experiment": bool(mutated.micro_experiment),
                "size_multiplier": float(mutated.size_multiplier or 1.0),
            }
        )
    return reviewed, decisions
