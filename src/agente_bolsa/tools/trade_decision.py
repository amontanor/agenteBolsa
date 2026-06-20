"""LLM-driven trade recommendations with deterministic risk sizing."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, replace
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any

from agente_bolsa._utils import log_swallow
from agente_bolsa.config import Settings
from agente_bolsa.llm_router import chat_for_role
from agente_bolsa.llm_usage import record_llm_response
from agente_bolsa.models import OrderPlan, PortfolioSnapshot, RiskDecision, TradeRecommendation, new_id
from agente_bolsa.storage import Store
from agente_bolsa.tools.position_sizing import recommended_notional
from agente_bolsa.tools.daily_learning import load_daily_learning_context
from agente_bolsa.tools.operational_health import load_operational_block_context, load_operational_response_context
from agente_bolsa.tools.operational_learning import load_operational_learning_context
from agente_bolsa.tools.post_market_review import load_post_market_learning_context
from agente_bolsa.tools.research_evidence import (
    build_research_evidence_report,
    compact_research_context_for_prompt,
    load_research_evidence_context,
    research_block_reason,
)

LOGGER = logging.getLogger(__name__)
from agente_bolsa.tools.retention import latest_report_path
from agente_bolsa.tools.risk import OrderProposal, RiskManager
from agente_bolsa.tools.signal_learning import _indicator_tags


VALID_ACTIONS = {"buy", "sell", "hold", "reduce", "exit"}


def _buy_plan_risk_amount(plan: dict[str, Any]) -> float:
    payload = plan.get("payload", {}) or {}
    entry_price = _float(payload.get("entry_price"))
    stop_loss = _float(payload.get("stop_loss"))
    notional = _float(plan.get("notional"))
    if notional is None:
        notional = _float(payload.get("notional"))
    if notional is None or notional <= 0 or entry_price is None or entry_price <= 0 or stop_loss is None:
        return 0.0
    if stop_loss >= entry_price:
        return 0.0
    return notional * ((entry_price - stop_loss) / entry_price)


def _position_risk_amount(position: Any, source_plan: dict[str, Any] | None) -> float:
    if source_plan is None:
        return 0.0
    payload = source_plan.get("payload", {}) or {}
    stop_loss = _float(payload.get("stop_loss"))
    current_price = _float(getattr(position, "current_price", None))
    qty = _float(getattr(position, "qty", None))
    if stop_loss is None or stop_loss <= 0 or current_price is None or current_price <= 0 or qty is None or qty <= 0:
        return 0.0
    if stop_loss >= current_price:
        return 0.0
    return qty * (current_price - stop_loss)


def _portfolio_risk_context(
    settings: Settings,
    portfolio: PortfolioSnapshot,
) -> dict[str, float]:
    portfolio_value = float(portfolio.portfolio_value or 0.0)
    current_portfolio_exposure = (
        sum(
            float(position.market_value)
            for position in portfolio.positions
            if str(position.side or "long").lower() == "long" and float(position.qty or 0.0) > 0
        )
        / portfolio_value
        if portfolio_value > 0
        else 0.0
    )

    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    latest_buy_plans = store.latest_executed_buy_plans_by_symbol()
    existing_open_risk_amount = sum(
        _position_risk_amount(position, (latest_buy_plans.get(position.symbol.upper()) or {}).get("plan"))
        for position in portfolio.positions
        if str(position.side or "long").lower() == "long" and float(position.qty or 0.0) > 0
    )
    pending_buy_plans = [
        item
        for item in store.pending_order_plans(limit=max(50, settings.max_orders_per_cycle * 10))
        if str(item.get("side") or "").lower() == "buy"
    ]
    pending_portfolio_exposure = (
        sum(float(item.get("notional") or 0.0) for item in pending_buy_plans) / portfolio_value
        if portfolio_value > 0
        else 0.0
    )
    pending_open_risk_amount = sum(_buy_plan_risk_amount(item) for item in pending_buy_plans)
    return {
        "current_portfolio_exposure": current_portfolio_exposure,
        "pending_portfolio_exposure": pending_portfolio_exposure,
        "existing_open_risk_amount": existing_open_risk_amount,
        "pending_open_risk_amount": pending_open_risk_amount,
    }


def _compact_portfolio_for_prompt(portfolio: PortfolioSnapshot) -> dict[str, Any]:
    return {
        "account_id": portfolio.account_id,
        "status": portfolio.status,
        "currency": portfolio.currency,
        "cash": round(float(portfolio.cash), 2),
        "portfolio_value": round(float(portfolio.portfolio_value), 2),
        "buying_power": round(float(portfolio.buying_power), 2),
        "positions": [
            {
                "symbol": item.symbol,
                "qty": round(float(item.qty), 4),
                "market_value": round(float(item.market_value), 2),
                "avg_entry_price": round(float(item.avg_entry_price), 4),
                "current_price": round(float(item.current_price), 4),
                "unrealized_pl": round(float(item.unrealized_pl), 2),
                "unrealized_plpc": round(float(item.unrealized_plpc), 4),
                "side": item.side,
            }
            for item in portfolio.positions[:12]
        ],
        "open_orders": [
            {
                "symbol": item.symbol,
                "side": item.side,
                "qty": item.qty,
                "notional": item.notional,
                "order_type": item.order_type,
                "status": item.status,
            }
            for item in portfolio.open_orders[:12]
        ],
    }


def _compact_candidate_for_prompt(candidate: dict[str, Any]) -> dict[str, Any]:
    learning_prior = candidate.get("learning_prior", {}) or {}
    technical_state = candidate.get("technical_state", {}) or {}
    risk_plan = candidate.get("risk_plan", {}) or {}
    return {
        "symbol": candidate.get("symbol"),
        "direction": candidate.get("direction"),
        "score": candidate.get("score"),
        "setup_name": candidate.get("setup_name") or _setup_name(candidate),
        "rank_priority_score": candidate.get("rank_priority_score"),
        "rank_priority_reason": candidate.get("rank_priority_reason"),
        "selection_score": candidate.get("selection_score"),
        "selection_rank": candidate.get("selection_rank"),
        "selection_reason": candidate.get("selection_reason"),
        "blocked_auto_buy": candidate.get("blocked_auto_buy"),
        "blocked_auto_buy_reason": candidate.get("blocked_auto_buy_reason"),
        "setup_edge_3d": candidate.get("setup_edge_3d"),
        "effective_setup_edge_3d": candidate.get("effective_setup_edge_3d"),
        "setup_win_rate_3d": candidate.get("setup_win_rate_3d"),
        "setup_matured_3d": candidate.get("setup_matured_3d"),
        "operational_penalty": candidate.get("operational_penalty", 0.0),
        "operational_notes": list(candidate.get("operational_notes", []) or [])[:2],
        "reasons": list(candidate.get("reasons", []) or [])[:4],
        "learning_prior": {
            "matched_on": learning_prior.get("matched_on"),
            "expected_edge_1d": learning_prior.get("expected_edge_1d"),
            "expected_edge_3d": learning_prior.get("expected_edge_3d"),
            "sample_size_3d": learning_prior.get("sample_size_3d"),
            "setup_sample_size_3d": learning_prior.get("setup_sample_size_3d"),
            "confidence_weight_3d": learning_prior.get("confidence_weight_3d"),
        },
        "technical_state": {
            "close": technical_state.get("close"),
            "return_20d": technical_state.get("return_20d"),
            "relative_return_20d": candidate.get("relative_return_20d"),
            "rsi_14": technical_state.get("rsi_14"),
            "sma_20": technical_state.get("sma_20"),
            "sma_50": technical_state.get("sma_50"),
            "sma_200": technical_state.get("sma_200"),
            "volume_zscore_20": technical_state.get("volume_zscore_20"),
            "trend_positive": technical_state.get("trend_positive"),
            "above_long_trend": technical_state.get("above_long_trend"),
            "event_momentum_long": technical_state.get("event_momentum_long"),
            "momentum_shakeout_hold_long": technical_state.get("momentum_shakeout_hold_long"),
            "range_expansion_breakout_long": technical_state.get("range_expansion_breakout_long"),
            "orderly_breakout_long": technical_state.get("orderly_breakout_long"),
            "breakout_continuation_long": technical_state.get("breakout_continuation_long"),
            "breakout_failure_risk": technical_state.get("breakout_failure_risk"),
            "candlestick_patterns": list(technical_state.get("candlestick_patterns", []) or [])[:3],
            "chart_patterns": list(technical_state.get("chart_patterns", []) or [])[:3],
        },
        "risk_plan": {
            "entry_price": risk_plan.get("entry_price"),
            "stop_loss": risk_plan.get("stop_loss"),
            "take_profit": risk_plan.get("take_profit"),
        },
    }


def _compact_technical_context_for_prompt(
    technical_context: dict[str, Any],
    *,
    selected_limit: int = 12,
) -> dict[str, Any]:
    selected = [
        _compact_candidate_for_prompt(item)
        for item in list(technical_context.get("selected_candidates", []) or [])[: max(1, int(selected_limit))]
        if isinstance(item, dict)
    ]
    top_longs = [
        _compact_candidate_for_prompt(item)
        for item in list(technical_context.get("top_longs", []) or [])[:5]
        if isinstance(item, dict)
    ]
    top_shorts = [
        _compact_candidate_for_prompt(item)
        for item in list(technical_context.get("top_shorts", []) or [])[:3]
        if isinstance(item, dict)
    ]
    return {
        "source": technical_context.get("source"),
        "run_id": technical_context.get("run_id"),
        "as_of": technical_context.get("as_of"),
        "selected_candidates": selected,
        "top_longs": top_longs,
        "top_shorts": top_shorts,
        "selection_metadata": technical_context.get("selection_metadata", {}),
        "analysis_plan_counts": technical_context.get("analysis_plan_counts", {}),
        "breakout_confirmed": list(technical_context.get("breakout_confirmed", []) or [])[:5],
        "breakout_watch": list(technical_context.get("breakout_watch", []) or [])[:5],
        "news_supportive_symbols": list(technical_context.get("news_supportive_symbols", []) or [])[:8],
        "warnings": list(technical_context.get("warnings", []) or [])[:4],
    }


def _candidate_symbols(technical_context: dict[str, Any]) -> set[str]:
    return {
        str(item.get("symbol", "")).upper()
        for item in _candidate_items(technical_context)
        if str(item.get("symbol", "")).strip()
    }


def _can_expand_long_only_capacity(settings: Settings) -> bool:
    return (
        not settings.allow_short_selling
        and (float(settings.max_position_exposure) * 4.0) <= float(settings.max_portfolio_exposure)
    )


def _effective_long_only_capacity(settings: Settings, selected_count: int) -> int:
    if not _can_expand_long_only_capacity(settings):
        return 3
    if (
        selected_count >= 12
        and (float(settings.max_position_exposure) * 5.0) <= float(settings.max_portfolio_exposure)
    ):
        return 5
    if selected_count >= 10:
        return 4
    return 3


def _effective_trade_recommendation_limit(settings: Settings, technical_context: dict[str, Any]) -> int:
    selected = list((technical_context or {}).get("selected_candidates", []) or [])
    base_limit = max(1, int(settings.max_orders_per_cycle))
    if settings.allow_short_selling:
        return base_limit
    return max(base_limit, _effective_long_only_capacity(settings, len(selected)))


def _effective_buy_plan_limit(settings: Settings, recommendations: list[TradeRecommendation]) -> int:
    base_limit = max(1, int(settings.max_orders_per_cycle))
    buy_count = sum(1 for item in recommendations if str(item.action).lower() == "buy")
    if _can_expand_long_only_capacity(settings) and buy_count >= 5:
        return max(base_limit, 5)
    if _can_expand_long_only_capacity(settings) and buy_count >= 4:
        return max(base_limit, 4)
    return base_limit


def _effective_daily_buy_limit(settings: Settings, plans: list[Any]) -> int:
    base_limit = max(0, int(settings.max_daily_buy_orders))
    buy_count = sum(1 for item in plans if str(getattr(item, "side", "")).lower() == "buy")
    if _can_expand_long_only_capacity(settings) and buy_count >= 5:
        limit = max(base_limit, 5)
    elif _can_expand_long_only_capacity(settings) and buy_count >= 4:
        limit = max(base_limit, 4)
    else:
        limit = base_limit
    return _apply_risk_off_factor(settings, limit)


def _apply_risk_off_factor(settings: Settings, limit: int) -> int:
    """Reduce el limite de compras si la tesis de mercado es risk_off (T3.1)."""

    if not getattr(settings, "macro_thesis_enabled", True):
        return limit
    try:
        from .macro_context import load_latest_thesis, risk_off_buy_factor

        factor = risk_off_buy_factor(settings, load_latest_thesis(settings))
        if factor < 1.0:
            return max(0, int(limit * factor))
    except Exception:  # noqa: BLE001 - la tesis nunca debe romper la decision.
        return limit
    return limit


def _deterministic_selection_limit(settings: Settings) -> int:
    if settings.allow_short_selling:
        return 8
    return max(12, int(settings.news_sentiment_top_n), int(settings.trade_selection_top_n))


def _fallback_market_state_block_reason(market_state: dict[str, Any] | None) -> str | None:
    if not market_state:
        return None
    data_quality = (market_state.get("data_quality") or {}) if isinstance(market_state, dict) else {}
    quality = str(data_quality.get("status") or "").upper()
    notes = [str(item or "").lower() for item in list(data_quality.get("notes") or [])]
    vendor_quality = data_quality.get("data_vendor_quality") or {}
    vendor_quality_text = str(vendor_quality or "").lower()
    if quality == "INSUFFICIENT":
        return "market_state_data_quality_insufficient"
    if quality == "PARTIAL":
        critical_terms = (
            "macro",
            "news",
            "sentiment",
            "provider",
            "vendor",
            "stale",
            "missing",
        )
        vendor_degraded = (
            (isinstance(vendor_quality, dict) and (not bool(vendor_quality.get("formal_provider")) or str(vendor_quality.get("severity") or "").upper() in {"WARN", "BLOCK"}))
            or vendor_quality_text in {"informal", "unknown", "degraded"}
        )
        if vendor_degraded or any(
            term in note for note in notes for term in critical_terms
        ):
            return "market_state_partial_missing_macro_or_news"
    return None


def _compact_sentiment_for_prompt(sentiment_context: dict[str, Any], technical_context: dict[str, Any]) -> dict[str, Any]:
    candidate_symbols = _candidate_symbols(technical_context)
    rows = []
    for item in list(sentiment_context.get("results", []) or []):
        symbol = str(item.get("symbol", "")).upper()
        if candidate_symbols and symbol not in candidate_symbols:
            continue
        sentiment = item.get("sentiment", {}) or {}
        news_rows = []
        for news in list(item.get("news", []) or [])[:2]:
            news_rows.append(
                {
                    "title": news.get("title"),
                    "publisher": news.get("publisher"),
                    "published_at": news.get("published_at"),
                }
            )
        rows.append(
            {
                "symbol": symbol,
                "technical_direction": item.get("technical_direction"),
                "technical_score": item.get("technical_score"),
                "news_count": item.get("news_count"),
                "sentiment": {
                    "supports_technical_setup": sentiment.get("supports_technical_setup"),
                    "sentiment_score": sentiment.get("sentiment_score"),
                    "summary": sentiment.get("summary"),
                    "catalysts": list(sentiment.get("catalysts", []) or [])[:3],
                    "risks": list(sentiment.get("risks", []) or [])[:3],
                },
                "material_risk": item.get("material_risk"),
                "news": news_rows,
            }
        )
        if len(rows) >= 8:
            break
    return {
        "path": sentiment_context.get("path"),
        "run_id": sentiment_context.get("run_id"),
        "as_of": sentiment_context.get("as_of"),
        "results": rows,
    }


def _build_research_context(
    settings: Settings,
    technical_context: dict[str, Any],
    sentiment_context: dict[str, Any],
    market_state: dict[str, Any] | None,
) -> dict[str, Any]:
    if not getattr(settings, "research_evidence_enabled", True):
        return load_research_evidence_context(settings.data_dir)
    try:
        store = Store(settings.database_path, settings.agent_logs_dir)
        store.ensure_schema()
        return build_research_evidence_report(
            store,
            settings,
            settings.data_dir / "reports",
            new_id("research"),
            symbols=sorted(_candidate_symbols(technical_context))[:12],
            market_state=market_state,
            sentiment_context=sentiment_context,
        )
    except Exception:
        return load_research_evidence_context(settings.data_dir)


def _compact_daily_learning_for_prompt(digest: dict[str, Any]) -> dict[str, Any]:
    return {
        "available": digest.get("available"),
        "as_of": digest.get("as_of"),
        "summary": digest.get("summary", {}),
        "guidance": list(digest.get("guidance", []) or [])[:6],
        "setup_stats_3d": list(digest.get("setup_stats_3d", []) or [])[:8],
        "weak_buckets_3d": list(digest.get("weak_buckets_3d", []) or [])[:6],
        "strong_buckets_3d": list(digest.get("strong_buckets_3d", []) or [])[:6],
        "confidence_calibration_3d": list(digest.get("confidence_calibration_3d", []) or [])[:6],
        "prior_accuracy_3d": list(digest.get("prior_accuracy_3d", []) or [])[:6],
        "pre_earnings": digest.get("pre_earnings", {"available": False}),
    }


def _compact_operational_learning_for_prompt(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "available": context.get("available"),
        "as_of": context.get("as_of"),
        "summary": context.get("summary", {}),
        "active_rules": list(context.get("active_rules", []) or [])[:6],
        "shadow_rules": list(context.get("shadow_rules", []) or [])[:6],
        "decision_summary": list(context.get("decision_summary", []) or [])[:8],
        "learning_journal": list(context.get("learning_journal", []) or [])[:6],
        "llm_review": context.get("llm_review", {}),
    }


def _compact_post_market_learning_for_prompt(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "available": context.get("available"),
        "as_of": context.get("as_of"),
        "session_date": context.get("session_date"),
        "summary": context.get("summary", {}),
        "active_guidance": list(context.get("active_guidance", []) or [])[:6],
        "proposed_improvements": list(context.get("proposed_improvements", []) or [])[:6],
    }


def _llm_prompt_payload(
    settings: Settings,
    portfolio: PortfolioSnapshot,
    technical_context: dict[str, Any],
    sentiment_context: dict[str, Any],
    rebalance_context: dict[str, Any] | None,
    daily_learning_digest: dict[str, Any],
    decision_learning_context: dict[str, Any],
    operational_response_context: dict[str, Any],
    market_state: dict[str, Any] | None = None,
    research_context: dict[str, Any] | None = None,
    *,
    compact: bool,
) -> dict[str, Any]:
    technical_candidates = (
        _compact_technical_context_for_prompt(
            technical_context,
            selected_limit=_deterministic_selection_limit(settings),
        )
        if compact
        else technical_context
    )
    effective_recommendation_limit = _effective_trade_recommendation_limit(settings, technical_context)
    selected_count = len(list((technical_context or {}).get("selected_candidates", []) or []))
    prefer_full_long_only_capacity = effective_recommendation_limit >= 4 and selected_count >= 10
    if not settings.allow_short_selling and isinstance(technical_candidates, dict):
        technical_candidates = {
            **technical_candidates,
            "top_shorts": [],
        }
    return {
        "portfolio": _compact_portfolio_for_prompt(portfolio) if compact else asdict(portfolio),
        "technical_candidates": technical_candidates,
        "news_sentiment": _compact_sentiment_for_prompt(sentiment_context, technical_context) if compact else sentiment_context,
        "research_evidence": compact_research_context_for_prompt(research_context or {}) if compact else (research_context or {}),
        "market_state": market_state or {},
        "portfolio_rebalance": rebalance_context or {},
        "daily_learning_digest": _compact_daily_learning_for_prompt(daily_learning_digest) if compact else daily_learning_digest,
        "decision_learning_context": decision_learning_context,
        "operational_responses": list((operational_response_context.get("responses", []) if isinstance(operational_response_context, dict) else []) or [])[:8],
        "post_market_learning": _compact_post_market_learning_for_prompt(load_post_market_learning_context(settings.data_dir))
        if compact
        else load_post_market_learning_context(settings.data_dir),
        "operational_learning": _compact_operational_learning_for_prompt(load_operational_learning_context(settings.data_dir))
        if compact
        else load_operational_learning_context(settings.data_dir),
        "risk_limits": {
            "max_portfolio_exposure": settings.max_portfolio_exposure,
            "max_position_exposure": settings.max_position_exposure,
            "max_risk_per_trade": settings.max_risk_per_trade,
            "max_orders_per_cycle": settings.max_orders_per_cycle,
            "max_daily_buy_orders": settings.max_daily_buy_orders,
            "effective_max_orders_per_cycle": max(int(settings.max_orders_per_cycle), effective_recommendation_limit),
            "effective_max_daily_buy_orders": max(int(settings.max_daily_buy_orders), effective_recommendation_limit),
            "prefer_full_long_only_capacity": prefer_full_long_only_capacity,
            "min_order_notional": settings.min_order_notional,
            "allow_position_adds": settings.allow_position_adds,
            "min_confidence_to_trade": settings.min_llm_confidence_to_trade,
            "allow_short_selling": settings.allow_short_selling,
        },
        "lecciones_validadas": _lessons_block_for_prompt(settings, technical_context),
        "market_thesis": _market_thesis_for_prompt(settings),
    }


def _market_thesis_for_prompt(settings: Settings) -> dict[str, Any]:
    """Tesis de mercado compactada para el prompt (T3.1)."""

    if not getattr(settings, "macro_thesis_enabled", True):
        return {}
    try:
        from .macro_context import load_latest_thesis

        thesis = load_latest_thesis(settings)
        if not thesis:
            return {}
        payload = thesis.get("payload", {}) or {}
        return {
            "thesis_date": thesis.get("thesis_date"),
            "stance": thesis.get("stance"),
            "confidence": thesis.get("confidence"),
            "key_risks": (payload.get("key_risks") or [])[:5],
            "key_catalysts": (payload.get("key_catalysts") or [])[:5],
            "sector_bias": payload.get("sector_bias") or {},
        }
    except Exception:  # noqa: BLE001 - acceso defensivo.
        return {}


def _lessons_block_for_prompt(settings: Settings, technical_context: dict[str, Any]) -> list[dict[str, Any]]:
    """Inyecta lecciones validadas relevantes (T2.4), cap ~600 tokens."""

    if not getattr(settings, "lessons_injection_enabled", True):
        return []
    try:
        from ..continuous_improvement.lesson_distiller import relevant_lessons
        from ..continuous_improvement.context_compaction import truncate_string
        from ..storage import Store

        store = Store(settings.database_path, settings.agent_logs_dir)
        lessons = relevant_lessons(store, k=6)
        block = [
            {
                "scope": item.get("scope"),
                "statement": truncate_string(item.get("statement", ""), 240),
                "confidence": item.get("confidence"),
                # T5.4: n e intervalo de confianza para que el LLM pondere.
                "n": item.get("supporting_cases"),
                "wilson_low": (item.get("source_refs") or {}).get("wilson_low"),
            }
            for item in lessons
        ]
        return block
    except Exception:  # noqa: BLE001 - la inyeccion nunca debe romper la decision.
        return []


def _latest_report(data_dir: Path, prefix: str) -> Path | None:
    latest_name = {
        "closed_market_technical_study": "latest_closed_market_technical_study.json",
        "news_sentiment": "latest_news_sentiment.json",
    }.get(prefix)
    if latest_name:
        path = latest_report_path(data_dir, prefix, latest_name)
        if path is not None:
            return path

    reports = [
        path
        for path in (data_dir / "reports").glob(f"{prefix}_*.json")
        if not path.name.endswith(".manifest.json")
    ]
    if not reports:
        return None
    return max(reports, key=lambda path: path.stat().st_mtime)


def load_latest_technical_candidates(
    data_dir: Path,
    *,
    per_side: int = 5,
) -> dict[str, Any]:
    path = _latest_report(data_dir, "closed_market_technical_study")
    if path is None:
        return {"path": None, "top_longs": [], "top_shorts": [], "all_candidates": []}

    report = json.loads(path.read_text(encoding="utf-8"))
    all_candidates = _annotate_candidates_with_top_long_rank(
        report.get("all_candidates", []) or [],
        report.get("top_longs", []) or [],
    )
    daily_learning_digest = load_daily_learning_context(data_dir)
    operational_response_context = load_operational_response_context(data_dir)
    settings = Settings(DATA_DIR=data_dir)
    selected_candidates, selection_metadata = _select_deterministic_candidates(
        all_candidates,
        daily_learning_digest,
        operational_response_context,
        limit=max(_deterministic_selection_limit(settings), per_side),
        same_session_context=_same_session_intraday_context(data_dir, report),
        settings=settings,
    )
    return {
        "path": str(path),
        "run_id": report.get("run_id"),
        "as_of": report.get("as_of"),
        "top_longs": _annotate_candidates_with_top_long_rank(
            report.get("top_longs", [])[:per_side],
            report.get("top_longs", []) or [],
        ),
        "top_shorts": report.get("top_shorts", [])[:per_side],
        "selected_candidates": selected_candidates,
        "selection_metadata": selection_metadata,
        "all_candidates": all_candidates,
        "analysis_plan_counts": report.get("analysis_plan_counts", {}),
    }


def load_latest_sentiment(data_dir: Path) -> dict[str, Any]:
    path = _latest_report(data_dir, "news_sentiment")
    if path is None:
        return {"path": None, "results": []}
    report = json.loads(path.read_text(encoding="utf-8"))
    return {
        "path": str(path),
        "run_id": report.get("run_id"),
        "as_of": report.get("as_of"),
        "results": report.get("results", []),
    }


def _extract_json_object(text: str) -> dict[str, Any]:
    clean_text = text.strip()
    if clean_text.startswith("```"):
        clean_text = clean_text.strip("`")
        if clean_text.lower().startswith("json"):
            clean_text = clean_text[4:].strip()
    try:
        parsed = json.loads(clean_text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = clean_text.find("{")
    end = clean_text.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(clean_text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError as exc:
            raise ValueError(
                "La respuesta del LLM contiene JSON incompleto o mal formado: "
                f"{exc}. Preview: {clean_text[:240]}"
            ) from exc
    raise ValueError(f"La respuesta del LLM no contiene un objeto JSON valido. Preview: {clean_text[:240]}")


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _floor_qty(value: float, decimals: int = 9) -> float:
    quantum = Decimal("1").scaleb(-decimals)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_DOWN))


def _exposure_fraction(value: Any) -> float | None:
    exposure = _float(value)
    if exposure is None:
        return None
    if exposure > 1:
        return exposure / 100
    return exposure


def _candidate_items(technical_context: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        *technical_context.get("selected_candidates", []),
        *technical_context.get("top_longs", []),
        *technical_context.get("top_shorts", []),
        *technical_context.get("all_candidates", []),
    ]
    seen: set[str] = set()
    result = []
    for candidate in candidates:
        symbol = str(candidate.get("symbol", "")).upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        result.append(candidate)
    return result


def _candidate_for_symbol(technical_context: dict[str, Any], symbol: str) -> dict[str, Any] | None:
    symbol = symbol.upper()
    for candidate in _candidate_items(technical_context):
        if str(candidate.get("symbol", "")).upper() == symbol:
            return candidate
    return None


def _technical_value(candidate: dict[str, Any], key: str) -> Any:
    technical_state = candidate.get("technical_state", {}) or {}
    if key in technical_state:
        return technical_state.get(key)
    return candidate.get(key)


def _confirmed_bullish_patterns(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    technical_state = candidate.get("technical_state", {}) or {}
    patterns = technical_state.get("chart_patterns")
    if patterns is None:
        patterns = candidate.get("chart_patterns", [])
    return [
        pattern
        for pattern in patterns or []
        if pattern.get("bias") == "bullish" and pattern.get("status") == "confirmed"
    ]


def _session_date_from_technical_context(technical_context: dict[str, Any]) -> str | None:
    for key in ("session_date", "as_of"):
        value = technical_context.get(key)
        if value:
            return str(value)[:10]
    for candidate in _candidate_items(technical_context):
        value = candidate.get("last_date") or _technical_value(candidate, "last_date")
        if value:
            return str(value)[:10]
    return None


def _same_session_intraday_context(
    data_dir: Path | None,
    technical_context: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if data_dir is None:
        return {}
    session_date = _session_date_from_technical_context(technical_context)
    if not session_date:
        return {}
    symbols = sorted(_candidate_symbols(technical_context))
    if not symbols:
        return {}
    settings = Settings(DATA_DIR=data_dir)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store.same_session_intraday_signal_summary(session_date=session_date, symbols=symbols)


def _same_session_intraday_momentum_bonus(
    candidate: dict[str, Any],
    same_session_context: dict[str, dict[str, Any]],
    settings: Settings | None,
) -> tuple[str | None, dict[str, Any]]:
    symbol = str(candidate.get("symbol") or "").upper().strip()
    if not symbol or not same_session_context:
        return None, {}
    defaults = settings or Settings()
    if not defaults.intraday_same_session_momentum_enabled:
        return None, {}
    summary = same_session_context.get(symbol) or {}
    if not summary or summary.get("selected_for_llm"):
        return None, summary
    observations = int(summary.get("observations") or 0)
    same_session_return = _float(summary.get("same_session_return")) or 0.0
    score = _float(candidate.get("score")) or 0.0
    rsi = _float(_technical_value(candidate, "rsi_14"))
    volume_z = _float(_technical_value(candidate, "volume_zscore_20"))
    distance_sma20 = _float(_candidate_learning_features(candidate).get("distance_sma20"))
    confirmed_patterns = len(_confirmed_bullish_patterns(candidate))
    leader_qualified = (
        observations >= defaults.intraday_same_session_leader_min_observations
        and same_session_return >= defaults.intraday_same_session_leader_min_return
        and score >= defaults.intraday_same_session_leader_min_score
        and confirmed_patterns >= defaults.intraday_same_session_leader_min_bullish_patterns
        and (distance_sma20 is None or distance_sma20 <= defaults.intraday_same_session_leader_max_sma20_distance)
        and (rsi is None or rsi <= defaults.intraday_same_session_leader_max_rsi)
    )
    if observations < defaults.intraday_same_session_min_observations:
        return "same_session_intraday_leader" if leader_qualified else None, summary
    if same_session_return < defaults.intraday_same_session_min_return:
        return "same_session_intraday_leader" if leader_qualified else None, summary
    if score < defaults.intraday_same_session_min_score:
        return "same_session_intraday_leader" if leader_qualified else None, summary
    if distance_sma20 is not None and distance_sma20 > defaults.intraday_same_session_max_sma20_distance:
        return "same_session_intraday_leader" if leader_qualified else None, summary
    if rsi is not None and rsi > defaults.intraday_same_session_max_rsi:
        return "same_session_intraday_leader" if leader_qualified else None, summary
    if (
        volume_z is not None
        and volume_z >= defaults.intraday_same_session_min_volume_z
    ) or confirmed_patterns >= defaults.intraday_same_session_min_bullish_patterns:
        return "same_session_intraday_momentum", summary
    return ("same_session_intraday_leader", summary) if leader_qualified else (None, summary)


def _sentiment_for_symbol(sentiment_context: dict[str, Any] | None, symbol: str) -> dict[str, Any]:
    if not sentiment_context:
        return {}
    symbol = symbol.upper()
    for item in sentiment_context.get("results", []):
        if str(item.get("symbol", "")).upper() == symbol:
            return item.get("sentiment", {}) or {}
    return {}


def _setup_name(candidate: dict[str, Any]) -> str:
    technical_state = candidate.get("technical_state", {}) or {}
    if technical_state.get("event_momentum_long") or candidate.get("event_momentum_long"):
        return "event_momentum"
    if technical_state.get("range_expansion_breakout_long") or candidate.get("range_expansion_breakout_long"):
        return "range_expansion_breakout"
    if technical_state.get("orderly_breakout_long") or candidate.get("orderly_breakout_long"):
        return "orderly_breakout"
    if technical_state.get("momentum_shakeout_hold_long") or candidate.get("momentum_shakeout_hold_long"):
        return "momentum_shakeout"
    if technical_state.get("breakout_continuation_long") or candidate.get("breakout_continuation_long"):
        return "breakout_continuation"
    chart_patterns = technical_state.get("chart_patterns", []) or candidate.get("chart_patterns", []) or []
    if isinstance(chart_patterns, dict):
        if int(chart_patterns.get("bullish_confirmed_count") or 0) > 0:
            return "confirmed_pattern"
    elif any(item.get("bias") == "bullish" and item.get("status") == "confirmed" for item in chart_patterns):
        return "confirmed_pattern"
    volume_z = _technical_value(candidate, "volume_zscore_20")
    return_20d = _technical_value(candidate, "return_20d")
    if isinstance(volume_z, (int, float)) and isinstance(return_20d, (int, float)) and volume_z >= 1.0 and return_20d > 0:
        return "trend_volume"
    return "baseline_trend"


def _setup_stats_map(digest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = digest.get("setup_stats_3d", []) if isinstance(digest, dict) else []
    return {
        str(item.get("setup") or "").strip(): item
        for item in rows or []
        if str(item.get("setup") or "").strip()
    }


def _prior_profile_key(features: dict[str, Any]) -> str:
    feature_tags = _indicator_tags({"features": features})
    selected = []
    for prefix in ("score:", "rsi:", "sma20_dist:", "volume_z:", "chart_confirmed:"):
        for tag in feature_tags:
            if tag.startswith(prefix):
                selected.append(tag)
                break
    return "|".join([_setup_name(features), *selected])


def _candidate_learning_features(candidate: dict[str, Any]) -> dict[str, Any]:
    technical_state = candidate.get("technical_state", {}) or {}
    close = _float(technical_state.get("close"))
    sma20 = _float(technical_state.get("sma_20"))
    macd = _float(technical_state.get("macd"))
    macd_signal = _float(technical_state.get("macd_signal"))
    chart_patterns = technical_state.get("chart_patterns", []) or candidate.get("chart_patterns", []) or []
    confirmed_bullish = sum(
        1 for item in chart_patterns if item.get("bias") == "bullish" and item.get("status") == "confirmed"
    )
    return {
        "score": candidate.get("score"),
        "rsi_14": _technical_value(candidate, "rsi_14"),
        "distance_sma20": ((close - sma20) / sma20) if close and sma20 else None,
        "volume_zscore_20": _technical_value(candidate, "volume_zscore_20"),
        "macd_diff": (macd - macd_signal) if macd is not None and macd_signal is not None else None,
        "chart_patterns": {"bullish_confirmed_count": confirmed_bullish},
        "breakout_continuation_long": bool(_technical_value(candidate, "breakout_continuation_long")),
        "range_expansion_breakout_long": bool(_technical_value(candidate, "range_expansion_breakout_long")),
        "orderly_breakout_long": bool(_technical_value(candidate, "orderly_breakout_long")),
        "breakout_failure_risk": bool(_technical_value(candidate, "breakout_failure_risk")),
        "event_momentum_long": bool(_technical_value(candidate, "event_momentum_long")),
        "momentum_shakeout_hold_long": bool(_technical_value(candidate, "momentum_shakeout_hold_long")),
        "return_20d": _technical_value(candidate, "return_20d"),
    }


def _annotate_candidates_with_top_long_rank(
    candidates: list[dict[str, Any]],
    top_longs: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    top_long_ranks = {
        str(item.get("symbol") or "").upper(): idx
        for idx, item in enumerate(top_longs or [], start=1)
        if isinstance(item, dict) and str(item.get("symbol") or "").strip()
    }
    annotated: list[dict[str, Any]] = []
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        symbol = str(candidate.get("symbol") or "").upper()
        top_long_rank = top_long_ranks.get(symbol)
        if top_long_rank is None and candidate.get("top_long_rank") is None:
            annotated.append(candidate)
            continue
        annotated.append(
            {
                **candidate,
                "top_long_rank": candidate.get("top_long_rank") or top_long_rank,
            }
        )
    return annotated


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _entry_reward_risk(recommendation: TradeRecommendation) -> float | None:
    entry = _float(recommendation.entry_price)
    stop = _float(recommendation.stop_loss)
    take = _float(recommendation.take_profit)
    if entry is None or stop is None or take is None or entry <= 0 or stop <= 0 or take <= 0:
        return None
    risk = entry - stop
    reward = take - entry
    if risk <= 0 or reward <= 0:
        return None
    return reward / risk


def _entry_score_v2(
    settings: Settings,
    recommendation: TradeRecommendation,
    *,
    score: int,
    setup_quality: str,
    direction: str,
    rsi: float | None,
    sma20_distance: float | None,
    macd: float | None,
    macd_signal: float | None,
    return_20d: float | None,
    volume_z: float | None,
    relative_return_20d: float | None,
    sentiment_score: float | None,
    sentiment_confidence: float,
    sentiment_failed: bool,
    learning_prior: dict[str, Any],
) -> dict[str, Any]:
    reward_risk = _entry_reward_risk(recommendation)
    prior_edge_3d = _float(learning_prior.get("expected_edge_3d"))
    prior_sample_3d = int(learning_prior.get("sample_size_3d") or 0)
    prior_confidence = _float(learning_prior.get("confidence_weight_3d")) or 0.0

    if rsi is None:
        rsi_component = 0.55
    elif 52 <= rsi <= 76:
        rsi_component = 0.95
    elif 45 <= rsi < 52:
        rsi_component = 0.55
    elif 76 < rsi <= 84:
        rsi_component = 0.70
    else:
        rsi_component = 0.30

    if sma20_distance is None:
        sma20_component = 0.55
    elif sma20_distance < -0.04:
        sma20_component = 0.35
    elif sma20_distance <= settings.entry_quality_max_sma20_distance:
        sma20_component = 0.95
    elif sma20_distance <= settings.entry_quality_extended_sma20_distance:
        sma20_component = 0.75
    elif sma20_distance <= 0.20:
        sma20_component = 0.45
    else:
        sma20_component = 0.20

    sentiment_missing = sentiment_failed or sentiment_score is None
    if sentiment_score is None:
        sentiment_component = 0.55
    elif sentiment_confidence >= 0.5:
        sentiment_component = _clamp((sentiment_score + 1.0) / 2.0)
    else:
        sentiment_component = 0.60
    if sentiment_failed:
        sentiment_component = min(sentiment_component, 0.30)

    learning_component = 0.55
    if prior_edge_3d is not None and prior_sample_3d >= 4 and prior_confidence >= 0.35:
        learning_component = _clamp(0.55 + (prior_edge_3d * 8.0), 0.20, 0.90)

    components = {
        "score": _clamp(score / 20.0),
        "setup": 1.0 if setup_quality == "strong" and direction == "long" else 0.0,
        "momentum_20d": 0.55 if return_20d is None else _clamp(0.50 + return_20d * 3.0),
        "sma20_distance": sma20_component,
        "rsi": rsi_component,
        "volume": 0.55 if volume_z is None else _clamp(0.55 + volume_z * 0.20),
        "relative_strength": 0.50 if relative_return_20d is None else _clamp(0.55 + relative_return_20d * 5.0),
        "macd": 0.55 if macd is None or macd_signal is None else (0.90 if macd > macd_signal else 0.20),
        "reward_risk": 0.0 if reward_risk is None else _clamp(reward_risk / 3.0),
        "sentiment": sentiment_component,
        "learning_prior": learning_component,
    }
    weights = {
        "score": 0.18,
        "setup": 0.12,
        "momentum_20d": 0.10,
        "sma20_distance": 0.10,
        "rsi": 0.08,
        "volume": 0.08,
        "relative_strength": 0.07,
        "macd": 0.07,
        "reward_risk": 0.12,
        "sentiment": 0.04,
        "learning_prior": 0.04,
    }
    raw_score = sum(components[key] * weights[key] for key in weights)
    if sentiment_missing and not settings.news_sentiment_fail_closed_for_buys:
        missing_data_penalty = 0.03
    else:
        missing_data_penalty = 0.06 if sentiment_missing else 0.0
    final_score = _clamp(raw_score - missing_data_penalty)

    hard_blocks = []
    if reward_risk is None:
        hard_blocks.append("reward_risk_indisponible")
    elif reward_risk < settings.entry_score_v2_min_reward_risk:
        hard_blocks.append("reward_risk_bajo")

    reasons = []
    if sentiment_missing:
        reasons.append("sentimiento_no_validado_penalizado")
    if final_score < settings.entry_score_v2_min:
        reasons.append("score_agregado_bajo")
    if hard_blocks:
        reasons.extend(hard_blocks)

    micro_experiment = (
        not hard_blocks
        and settings.entry_score_v2_micro_min <= final_score < settings.entry_score_v2_min
    )
    return {
        "score": round(final_score, 4),
        "raw_score": round(raw_score, 4),
        "approved": not hard_blocks and final_score >= settings.entry_score_v2_min,
        "micro_experiment": micro_experiment,
        "missing_data": {"sentiment": sentiment_missing},
        "missing_data_penalty": round(missing_data_penalty, 4),
        "reward_risk": round(reward_risk, 4) if reward_risk is not None else None,
        "min_score": settings.entry_score_v2_min,
        "micro_min_score": settings.entry_score_v2_micro_min,
        "min_reward_risk": settings.entry_score_v2_min_reward_risk,
        "components": {key: round(value, 4) for key, value in components.items()},
        "hard_blocks": hard_blocks,
        "reasons": reasons,
    }


def _fallback_constructive_extension_exception(
    settings: Settings,
    candidate: dict[str, Any],
    *,
    score: int | float | None = None,
    return_20d: float | None = None,
    rsi: float | None = None,
    sma20_distance: float | None = None,
    volume_z: float | None = None,
    confirmed_patterns: int | None = None,
) -> bool:
    if not settings.entry_quality_fallback_constructive_extension_enabled:
        return False
    selection_rank = int(candidate.get("selection_rank") or 0)
    score_value = int(_float(score if score is not None else candidate.get("score")) or 0)
    return_20d_value = return_20d if return_20d is not None else _float(_technical_value(candidate, "return_20d"))
    rsi_value = rsi if rsi is not None else _float(_technical_value(candidate, "rsi_14"))
    volume_value = volume_z if volume_z is not None else _float(_technical_value(candidate, "volume_zscore_20"))
    if sma20_distance is None:
        close = _float(_technical_value(candidate, "close"))
        sma20 = _float(_technical_value(candidate, "sma_20"))
        sma20_distance = ((close - sma20) / sma20) if close and sma20 else None
    confirmed_count = confirmed_patterns if confirmed_patterns is not None else len(_confirmed_bullish_patterns(candidate))
    return bool(
        selection_rank > 0
        and selection_rank <= int(settings.entry_quality_fallback_constructive_extension_max_selection_rank)
        and score_value >= int(settings.entry_quality_fallback_constructive_extension_min_score)
        and return_20d_value is not None
        and return_20d_value >= float(settings.entry_quality_fallback_constructive_extension_min_return_20d)
        and rsi_value is not None
        and rsi_value >= float(settings.entry_quality_fallback_constructive_extension_min_rsi)
        and sma20_distance is not None
        and sma20_distance > float(settings.entry_quality_max_sma20_distance)
        and sma20_distance <= float(settings.entry_quality_fallback_constructive_extension_max_sma20_distance)
        and volume_value is not None
        and volume_value >= float(settings.entry_quality_fallback_constructive_extension_min_volume_z)
        and confirmed_count >= int(settings.entry_quality_fallback_constructive_extension_min_bullish_patterns)
    )


def _fallback_momentum_extension_exception(
    settings: Settings,
    candidate: dict[str, Any],
    *,
    score: int | float | None = None,
    return_20d: float | None = None,
    rsi: float | None = None,
    sma20_distance: float | None = None,
    volume_z: float | None = None,
    confirmed_patterns: int | None = None,
) -> bool:
    if not settings.entry_quality_fallback_momentum_extension_enabled:
        return False
    selection_rank = int(candidate.get("selection_rank") or 0)
    score_value = int(_float(score if score is not None else candidate.get("score")) or 0)
    return_20d_value = return_20d if return_20d is not None else _float(_technical_value(candidate, "return_20d"))
    rsi_value = rsi if rsi is not None else _float(_technical_value(candidate, "rsi_14"))
    volume_value = volume_z if volume_z is not None else _float(_technical_value(candidate, "volume_zscore_20"))
    if sma20_distance is None:
        close = _float(_technical_value(candidate, "close"))
        sma20 = _float(_technical_value(candidate, "sma_20"))
        sma20_distance = ((close - sma20) / sma20) if close and sma20 else None
    confirmed_count = confirmed_patterns if confirmed_patterns is not None else len(_confirmed_bullish_patterns(candidate))
    return bool(
        selection_rank > 0
        and selection_rank <= int(settings.entry_quality_fallback_momentum_extension_max_selection_rank)
        and score_value >= int(settings.entry_quality_fallback_momentum_extension_min_score)
        and return_20d_value is not None
        and return_20d_value >= float(settings.entry_quality_fallback_momentum_extension_min_return_20d)
        and rsi_value is not None
        and float(settings.entry_quality_fallback_momentum_extension_min_rsi)
        <= rsi_value
        <= float(settings.entry_quality_fallback_momentum_extension_max_rsi)
        and sma20_distance is not None
        and sma20_distance > float(settings.entry_quality_max_sma20_distance)
        and sma20_distance <= float(settings.entry_quality_fallback_momentum_extension_max_sma20_distance)
        and volume_value is not None
        and volume_value >= float(settings.entry_quality_fallback_momentum_extension_min_volume_z)
        and confirmed_count >= int(settings.entry_quality_fallback_momentum_extension_min_bullish_patterns)
    )


def _fallback_weak_volume_momentum_extension_exception(
    settings: Settings,
    candidate: dict[str, Any],
    *,
    score: int | float | None = None,
    return_20d: float | None = None,
    rsi: float | None = None,
    sma20_distance: float | None = None,
    volume_z: float | None = None,
    confirmed_patterns: int | None = None,
) -> bool:
    if not settings.entry_quality_fallback_weak_volume_momentum_extension_enabled:
        return False
    selection_reason = str(candidate.get("selection_reason") or "")
    if (
        "weak_volume_penalty" not in selection_reason
        or "confirmed_pattern" not in selection_reason
        or "leader_momentum_extension" in selection_reason
        or "same_session_intraday_momentum" in selection_reason
    ):
        return False
    selection_rank = int(candidate.get("selection_rank") or 0)
    score_value = int(_float(score if score is not None else candidate.get("score")) or 0)
    return_20d_value = return_20d if return_20d is not None else _float(_technical_value(candidate, "return_20d"))
    rsi_value = rsi if rsi is not None else _float(_technical_value(candidate, "rsi_14"))
    volume_value = volume_z if volume_z is not None else _float(_technical_value(candidate, "volume_zscore_20"))
    if sma20_distance is None:
        close = _float(_technical_value(candidate, "close"))
        sma20 = _float(_technical_value(candidate, "sma_20"))
        sma20_distance = ((close - sma20) / sma20) if close and sma20 else None
    confirmed_count = confirmed_patterns if confirmed_patterns is not None else len(_confirmed_bullish_patterns(candidate))
    return bool(
        selection_rank > 0
        and selection_rank <= int(settings.entry_quality_fallback_weak_volume_momentum_extension_max_selection_rank)
        and score_value >= int(settings.entry_quality_fallback_weak_volume_momentum_extension_min_score)
        and return_20d_value is not None
        and return_20d_value >= float(settings.entry_quality_fallback_weak_volume_momentum_extension_min_return_20d)
        and rsi_value is not None
        and float(settings.entry_quality_fallback_weak_volume_momentum_extension_min_rsi)
        <= rsi_value
        <= float(settings.entry_quality_fallback_weak_volume_momentum_extension_max_rsi)
        and sma20_distance is not None
        and float(settings.entry_quality_fallback_weak_volume_momentum_extension_min_sma20_distance)
        <= sma20_distance
        <= float(settings.entry_quality_fallback_weak_volume_momentum_extension_max_sma20_distance)
        and volume_value is not None
        and float(settings.entry_quality_fallback_weak_volume_momentum_extension_min_volume_z)
        <= volume_value
        <= float(settings.entry_quality_fallback_weak_volume_momentum_extension_max_volume_z)
        and confirmed_count
        >= int(settings.entry_quality_fallback_weak_volume_momentum_extension_min_bullish_patterns)
    )


def _fallback_relative_strength_pullback_extension_exception(
    settings: Settings,
    candidate: dict[str, Any],
    *,
    score: int | float | None = None,
    return_20d: float | None = None,
    relative_return_20d: float | None = None,
    rsi: float | None = None,
    sma20_distance: float | None = None,
    volume_z: float | None = None,
    confirmed_patterns: int | None = None,
) -> bool:
    if not settings.entry_quality_fallback_relative_strength_pullback_extension_enabled:
        return False
    selection_reason = str(candidate.get("selection_reason") or "")
    if selection_reason != "profile_edge_high_sample,weak_volume_penalty,confirmed_pattern,relative_strength":
        return False
    selection_rank = int(candidate.get("selection_rank") or 0)
    score_value = int(_float(score if score is not None else candidate.get("score")) or 0)
    return_20d_value = return_20d if return_20d is not None else _float(_technical_value(candidate, "return_20d"))
    relative_return_value = (
        relative_return_20d
        if relative_return_20d is not None
        else _float(_technical_value(candidate, "relative_return_20d"))
    )
    rsi_value = rsi if rsi is not None else _float(_technical_value(candidate, "rsi_14"))
    volume_value = volume_z if volume_z is not None else _float(_technical_value(candidate, "volume_zscore_20"))
    if sma20_distance is None:
        close = _float(_technical_value(candidate, "close"))
        sma20 = _float(_technical_value(candidate, "sma_20"))
        sma20_distance = ((close - sma20) / sma20) if close and sma20 else None
    confirmed_count = confirmed_patterns if confirmed_patterns is not None else len(_confirmed_bullish_patterns(candidate))
    return bool(
        selection_rank > 0
        and selection_rank <= int(settings.entry_quality_fallback_relative_strength_pullback_extension_max_selection_rank)
        and score_value >= int(settings.entry_quality_fallback_relative_strength_pullback_extension_min_score)
        and return_20d_value is not None
        and float(settings.entry_quality_fallback_relative_strength_pullback_extension_min_return_20d)
        <= return_20d_value
        <= float(settings.entry_quality_fallback_relative_strength_pullback_extension_max_return_20d)
        and relative_return_value is not None
        and float(settings.entry_quality_fallback_relative_strength_pullback_extension_min_relative_return_20d)
        <= relative_return_value
        <= float(settings.entry_quality_fallback_relative_strength_pullback_extension_max_relative_return_20d)
        and rsi_value is not None
        and float(settings.entry_quality_fallback_relative_strength_pullback_extension_min_rsi)
        <= rsi_value
        <= float(settings.entry_quality_fallback_relative_strength_pullback_extension_max_rsi)
        and sma20_distance is not None
        and float(settings.entry_quality_fallback_relative_strength_pullback_extension_min_sma20_distance)
        <= sma20_distance
        <= float(settings.entry_quality_fallback_relative_strength_pullback_extension_max_sma20_distance)
        and volume_value is not None
        and float(settings.entry_quality_fallback_relative_strength_pullback_extension_min_volume_z)
        <= volume_value
        <= float(settings.entry_quality_fallback_relative_strength_pullback_extension_max_volume_z)
        and confirmed_count
        >= int(settings.entry_quality_fallback_relative_strength_pullback_extension_min_bullish_patterns)
    )


def _fallback_leader_pullback_extension_exception(
    settings: Settings,
    candidate: dict[str, Any],
    *,
    score: int | float | None = None,
    return_20d: float | None = None,
    rsi: float | None = None,
    sma20_distance: float | None = None,
    volume_z: float | None = None,
    confirmed_patterns: int | None = None,
) -> bool:
    if not settings.entry_quality_fallback_leader_pullback_extension_enabled:
        return False
    selection_reason = str(candidate.get("selection_reason") or "")
    if selection_reason != (
        "profile_edge_high_sample,confirmed_pattern,leader_momentum_extension,"
        "relative_strength,weak_volume_tolerated_for_leader"
    ):
        return False
    selection_rank = int(candidate.get("selection_rank") or 0)
    score_value = int(_float(score if score is not None else candidate.get("score")) or 0)
    return_20d_value = return_20d if return_20d is not None else _float(_technical_value(candidate, "return_20d"))
    rsi_value = rsi if rsi is not None else _float(_technical_value(candidate, "rsi_14"))
    volume_value = volume_z if volume_z is not None else _float(_technical_value(candidate, "volume_zscore_20"))
    if sma20_distance is None:
        close = _float(_technical_value(candidate, "close"))
        sma20 = _float(_technical_value(candidate, "sma_20"))
        sma20_distance = ((close - sma20) / sma20) if close and sma20 else None
    confirmed_count = confirmed_patterns if confirmed_patterns is not None else len(_confirmed_bullish_patterns(candidate))
    return bool(
        selection_rank > 0
        and selection_rank <= int(settings.entry_quality_fallback_leader_pullback_extension_max_selection_rank)
        and score_value >= int(settings.entry_quality_fallback_leader_pullback_extension_min_score)
        and return_20d_value is not None
        and float(settings.entry_quality_fallback_leader_pullback_extension_min_return_20d)
        <= return_20d_value
        <= float(settings.entry_quality_fallback_leader_pullback_extension_max_return_20d)
        and rsi_value is not None
        and float(settings.entry_quality_fallback_leader_pullback_extension_min_rsi)
        <= rsi_value
        <= float(settings.entry_quality_fallback_leader_pullback_extension_max_rsi)
        and sma20_distance is not None
        and float(settings.entry_quality_fallback_leader_pullback_extension_min_sma20_distance)
        <= sma20_distance
        <= float(settings.entry_quality_fallback_leader_pullback_extension_max_sma20_distance)
        and volume_value is not None
        and float(settings.entry_quality_fallback_leader_pullback_extension_min_volume_z)
        <= volume_value
        <= float(settings.entry_quality_fallback_leader_pullback_extension_max_volume_z)
        and confirmed_count >= int(settings.entry_quality_fallback_leader_pullback_extension_min_bullish_patterns)
    )


def _fallback_top_long_follow_through_exception(
    settings: Settings,
    candidate: dict[str, Any],
    *,
    score: int | float | None = None,
    return_20d: float | None = None,
    rsi: float | None = None,
    volume_z: float | None = None,
    confirmed_patterns: int | None = None,
) -> bool:
    if not settings.entry_quality_fallback_top_long_follow_through_enabled:
        return False
    selection_reason = str(candidate.get("selection_reason") or "")
    required_tokens = {
        "profile_edge_high_sample",
        "weak_volume_penalty",
        "confirmed_pattern",
        "top_long_alignment",
    }
    if not required_tokens.issubset(set(selection_reason.split(","))):
        return False
    selection_rank = int(candidate.get("selection_rank") or 0)
    score_value = int(_float(score if score is not None else candidate.get("score")) or 0)
    return_20d_value = return_20d if return_20d is not None else _float(_technical_value(candidate, "return_20d"))
    rsi_value = rsi if rsi is not None else _float(_technical_value(candidate, "rsi_14"))
    volume_value = volume_z if volume_z is not None else _float(_technical_value(candidate, "volume_zscore_20"))
    confirmed_count = confirmed_patterns if confirmed_patterns is not None else len(_confirmed_bullish_patterns(candidate))
    return bool(
        selection_rank > 0
        and selection_rank <= int(settings.entry_quality_fallback_top_long_follow_through_max_selection_rank)
        and score_value >= int(settings.entry_quality_fallback_top_long_follow_through_min_score)
        and return_20d_value is not None
        and float(settings.entry_quality_fallback_top_long_follow_through_min_return_20d)
        <= return_20d_value
        <= float(settings.entry_quality_fallback_top_long_follow_through_max_return_20d)
        and rsi_value is not None
        and float(settings.entry_quality_fallback_top_long_follow_through_min_rsi)
        <= rsi_value
        <= float(settings.entry_quality_fallback_top_long_follow_through_max_rsi)
        and volume_value is not None
        and float(settings.entry_quality_fallback_top_long_follow_through_min_volume_z)
        <= volume_value
        <= float(settings.entry_quality_fallback_top_long_follow_through_max_volume_z)
        and confirmed_count >= int(settings.entry_quality_fallback_top_long_follow_through_min_bullish_patterns)
    )


def _prior_error_volume_confirmation_override_exception(
    settings: Settings,
    candidate: dict[str, Any],
    *,
    score: int | float | None = None,
    return_20d: float | None = None,
    rsi: float | None = None,
    volume_z: float | None = None,
    confirmed_patterns: int | None = None,
) -> bool:
    if not settings.entry_quality_prior_error_volume_confirmation_override_enabled:
        return False
    selection_reason = str(candidate.get("selection_reason") or "")
    if (
        selection_reason != "profile_edge_high_sample,volume_confirmation,confirmed_pattern"
        or "same_session_intraday_momentum" in selection_reason
    ):
        return False
    selection_rank = int(candidate.get("selection_rank") or 0)
    score_value = int(_float(score if score is not None else candidate.get("score")) or 0)
    return_20d_value = return_20d if return_20d is not None else _float(_technical_value(candidate, "return_20d"))
    rsi_value = rsi if rsi is not None else _float(_technical_value(candidate, "rsi_14"))
    volume_value = volume_z if volume_z is not None else _float(_technical_value(candidate, "volume_zscore_20"))
    confirmed_count = confirmed_patterns if confirmed_patterns is not None else len(_confirmed_bullish_patterns(candidate))
    return bool(
        selection_rank > 0
        and selection_rank <= int(settings.entry_quality_prior_error_volume_confirmation_override_max_selection_rank)
        and score_value >= int(settings.entry_quality_prior_error_volume_confirmation_override_min_score)
        and return_20d_value is not None
        and return_20d_value >= float(settings.entry_quality_prior_error_volume_confirmation_override_min_return_20d)
        and rsi_value is not None
        and float(settings.entry_quality_prior_error_volume_confirmation_override_min_rsi)
        <= rsi_value
        <= float(settings.entry_quality_prior_error_volume_confirmation_override_max_rsi)
        and volume_value is not None
        and volume_value >= float(settings.entry_quality_prior_error_volume_confirmation_override_min_volume_z)
        and confirmed_count
        >= int(settings.entry_quality_prior_error_volume_confirmation_override_min_bullish_patterns)
    )


def _low_score_volume_rebound_override_exception(
    settings: Settings,
    candidate: dict[str, Any],
    *,
    score: int | float | None = None,
    return_20d: float | None = None,
    rsi: float | None = None,
    volume_z: float | None = None,
) -> bool:
    if not settings.entry_quality_low_score_volume_rebound_override_enabled:
        return False
    selection_reason = str(candidate.get("selection_reason") or "")
    if not (
        "profile_edge_shrunk" in selection_reason
        and "volume_confirmation" in selection_reason
        and "same_session_intraday_momentum" not in selection_reason
    ):
        return False
    selection_rank = int(candidate.get("selection_rank") or 0)
    score_value = int(_float(score if score is not None else candidate.get("score")) or 0)
    return_20d_value = return_20d if return_20d is not None else _float(_technical_value(candidate, "return_20d"))
    rsi_value = rsi if rsi is not None else _float(_technical_value(candidate, "rsi_14"))
    volume_value = volume_z if volume_z is not None else _float(_technical_value(candidate, "volume_zscore_20"))
    return bool(
        selection_rank > 0
        and selection_rank <= int(settings.entry_quality_low_score_volume_rebound_max_selection_rank)
        and int(settings.entry_quality_low_score_volume_rebound_min_score)
        <= score_value
        <= int(settings.entry_quality_low_score_volume_rebound_max_score)
        and return_20d_value is not None
        and float(settings.entry_quality_low_score_volume_rebound_min_return_20d)
        <= return_20d_value
        <= float(settings.entry_quality_low_score_volume_rebound_max_return_20d)
        and rsi_value is not None
        and float(settings.entry_quality_low_score_volume_rebound_min_rsi)
        <= rsi_value
        <= float(settings.entry_quality_low_score_volume_rebound_max_rsi)
        and volume_value is not None
        and volume_value >= float(settings.entry_quality_low_score_volume_rebound_min_volume_z)
    )


def _reward_risk_follow_through_override_exception(
    settings: Settings,
    candidate: dict[str, Any],
    *,
    score: int | float | None = None,
    return_20d: float | None = None,
    rsi: float | None = None,
    sma20_distance: float | None = None,
    confirmed_patterns: int | None = None,
) -> bool:
    if not settings.entry_score_v2_reward_risk_follow_through_override_enabled:
        return False
    selection_reason = str(candidate.get("selection_reason") or "")
    allowed_selection_reason = (
        "constructive_early_pattern" in selection_reason
        or "high_conviction_confirmed_momentum" in selection_reason
        or (
            "weak_volume_penalty" in selection_reason
            and "confirmed_pattern" in selection_reason
            and "top_long_alignment" not in selection_reason
            and "same_session_intraday_momentum" not in selection_reason
        )
    )
    if not allowed_selection_reason:
        return False
    selection_rank = int(candidate.get("selection_rank") or 0)
    score_value = int(_float(score if score is not None else candidate.get("score")) or 0)
    return_20d_value = return_20d if return_20d is not None else _float(_technical_value(candidate, "return_20d"))
    rsi_value = rsi if rsi is not None else _float(_technical_value(candidate, "rsi_14"))
    if sma20_distance is None:
        close = _float(_technical_value(candidate, "close"))
        sma20 = _float(_technical_value(candidate, "sma_20"))
        sma20_distance = ((close - sma20) / sma20) if close and sma20 else None
    confirmed_count = confirmed_patterns if confirmed_patterns is not None else len(_confirmed_bullish_patterns(candidate))
    return bool(
        selection_rank > 0
        and selection_rank <= int(settings.entry_score_v2_reward_risk_follow_through_max_selection_rank)
        and score_value >= int(settings.entry_score_v2_reward_risk_follow_through_min_score)
        and return_20d_value is not None
        and return_20d_value >= float(settings.entry_score_v2_reward_risk_follow_through_min_return_20d)
        and rsi_value is not None
        and rsi_value >= float(settings.entry_score_v2_reward_risk_follow_through_min_rsi)
        and sma20_distance is not None
        and sma20_distance <= float(settings.entry_score_v2_reward_risk_follow_through_max_sma20_distance)
        and confirmed_count >= int(settings.entry_score_v2_reward_risk_follow_through_min_confirmed_patterns)
    )


def _late_constructive_follow_through_reward_risk_override_exception(
    settings: Settings,
    candidate: dict[str, Any],
    *,
    score: int | float | None = None,
    return_20d: float | None = None,
    rsi: float | None = None,
    volume_z: float | None = None,
) -> bool:
    if not settings.entry_score_v2_late_constructive_follow_through_override_enabled:
        return False
    selection_reason = str(candidate.get("selection_reason") or "")
    if not (
        "constructive_early_pattern" in selection_reason
        and "weak_volume_penalty" in selection_reason
        and "confirmed_pattern" in selection_reason
        and "top_long_alignment" not in selection_reason
        and "same_session_intraday_momentum" not in selection_reason
    ):
        return False
    selection_rank = int(candidate.get("selection_rank") or 0)
    score_value = int(_float(score if score is not None else candidate.get("score")) or 0)
    return_20d_value = return_20d if return_20d is not None else _float(_technical_value(candidate, "return_20d"))
    rsi_value = rsi if rsi is not None else _float(_technical_value(candidate, "rsi_14"))
    volume_value = volume_z if volume_z is not None else _float(_technical_value(candidate, "volume_zscore_20"))
    return bool(
        selection_rank >= int(settings.entry_score_v2_late_constructive_follow_through_min_selection_rank)
        and selection_rank <= int(settings.entry_score_v2_late_constructive_follow_through_max_selection_rank)
        and score_value >= int(settings.entry_score_v2_late_constructive_follow_through_min_score)
        and return_20d_value is not None
        and float(settings.entry_score_v2_late_constructive_follow_through_min_return_20d)
        <= return_20d_value
        <= float(settings.entry_score_v2_late_constructive_follow_through_max_return_20d)
        and rsi_value is not None
        and float(settings.entry_score_v2_late_constructive_follow_through_min_rsi)
        <= rsi_value
        <= float(settings.entry_score_v2_late_constructive_follow_through_max_rsi)
        and volume_value is not None
        and float(settings.entry_score_v2_late_constructive_follow_through_min_volume_z)
        <= volume_value
        <= float(settings.entry_score_v2_late_constructive_follow_through_max_volume_z)
    )


def _missing_relative_strength_follow_through_exception(
    settings: Settings,
    candidate: dict[str, Any],
    *,
    score: int | float | None = None,
    return_20d: float | None = None,
    rsi: float | None = None,
    sma20_distance: float | None = None,
    confirmed_patterns: int | None = None,
) -> bool:
    if not settings.entry_quality_missing_relative_strength_follow_through_enabled:
        return False
    selection_reason = str(candidate.get("selection_reason") or "")
    if "top_long_alignment" not in selection_reason:
        return False
    selection_rank = int(candidate.get("selection_rank") or 0)
    score_value = int(_float(score if score is not None else candidate.get("score")) or 0)
    return_20d_value = return_20d if return_20d is not None else _float(_technical_value(candidate, "return_20d"))
    rsi_value = rsi if rsi is not None else _float(_technical_value(candidate, "rsi_14"))
    if sma20_distance is None:
        close = _float(_technical_value(candidate, "close"))
        sma20 = _float(_technical_value(candidate, "sma_20"))
        sma20_distance = ((close - sma20) / sma20) if close and sma20 else None
    confirmed_count = confirmed_patterns if confirmed_patterns is not None else len(_confirmed_bullish_patterns(candidate))
    return bool(
        selection_rank > 0
        and selection_rank <= int(settings.entry_quality_missing_relative_strength_follow_through_max_selection_rank)
        and score_value >= int(settings.entry_quality_missing_relative_strength_follow_through_min_score)
        and return_20d_value is not None
        and return_20d_value >= float(settings.entry_quality_missing_relative_strength_follow_through_min_return_20d)
        and rsi_value is not None
        and rsi_value >= float(settings.entry_quality_missing_relative_strength_follow_through_min_rsi)
        and sma20_distance is not None
        and sma20_distance <= float(settings.entry_quality_missing_relative_strength_follow_through_max_sma20_distance)
        and confirmed_count >= int(settings.entry_quality_missing_relative_strength_follow_through_min_confirmed_patterns)
    )


def _setup_prior_maps(digest: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    priors_3d = {
        str(item.get("profile_key") or "").strip(): item
        for item in (digest.get("setup_priors_3d", []) if isinstance(digest, dict) else []) or []
        if str(item.get("profile_key") or "").strip()
    }
    priors_1d = {
        str(item.get("profile_key") or "").strip(): item
        for item in (digest.get("setup_priors_1d", []) if isinstance(digest, dict) else []) or []
        if str(item.get("profile_key") or "").strip()
    }
    setup_stats = _setup_stats_map(digest)
    return priors_1d, priors_3d, setup_stats


def _candidate_learning_prior(
    candidate: dict[str, Any],
    daily_learning_digest: dict[str, Any],
    operational_response_context: dict[str, Any],
) -> dict[str, Any]:
    features = _candidate_learning_features(candidate)
    profile_key = _prior_profile_key(features)
    priors_1d, priors_3d, setup_stats = _setup_prior_maps(daily_learning_digest)
    setup_name = _setup_name(candidate)
    profile_1d = priors_1d.get(profile_key)
    profile_3d = priors_3d.get(profile_key)
    setup_row = setup_stats.get(setup_name, {})
    setup_sample_3d = int(setup_row.get("matured") or 0)
    setup_edge_3d = _float(setup_row.get("avg_return"))
    setup_penalty = 0.0
    if isinstance(operational_response_context, dict):
        penalty_map = operational_response_context.get("setup_penalties", {}) or {}
        setup_penalty = _float(penalty_map.get(setup_name)) or 0.0
    matched_on = "profile" if profile_3d or profile_1d else "setup" if setup_row else "none"
    expected_edge_1d = _float((profile_1d or {}).get("expected_edge"))
    expected_edge_3d = _float((profile_3d or {}).get("expected_edge"))
    if expected_edge_3d is None and setup_row:
        expected_edge_3d = _float(setup_row.get("avg_return"))
    if expected_edge_3d is not None:
        expected_edge_3d = round(expected_edge_3d - setup_penalty, 4)
    return {
        "setup": setup_name,
        "profile_key": profile_key,
        "matched_on": matched_on,
        "expected_edge_1d": expected_edge_1d,
        "expected_edge_3d": expected_edge_3d,
        "win_rate_recent_3d": _float((profile_3d or setup_row).get("win_rate")),
        "sample_size_3d": int((profile_3d or setup_row).get("matured") or 0),
        "setup_sample_size_3d": setup_sample_3d,
        "setup_edge_3d_raw": setup_edge_3d,
        "confidence_weight_3d": _float((profile_3d or {}).get("confidence_weight")) if profile_3d else 0.35 if setup_row else 0.0,
        "operational_penalty": round(setup_penalty, 4),
    }


def _valid_risk_plan(candidate: dict[str, Any]) -> bool:
    risk = candidate.get("risk_plan", {}) or {}
    entry = _float(risk.get("entry_price"))
    stop = _float(risk.get("stop_loss"))
    take = _float(risk.get("take_profit"))
    return bool(entry and stop and take and 0 < stop < entry < take)


def _selection_eligible(candidate: dict[str, Any]) -> tuple[bool, str]:
    direction = str(candidate.get("direction") or "").lower()
    setup_quality = str(candidate.get("setup_quality") or "").lower()
    return_20d = _float(_technical_value(candidate, "return_20d"))
    if direction != "long":
        return False, "direction_not_long"
    if setup_quality != "strong":
        return False, "setup_not_strong"
    if return_20d is None or return_20d <= 0:
        return False, "return_20d_not_positive"
    if not _valid_risk_plan(candidate):
        return False, "invalid_risk_plan"
    return True, "eligible"


def _shrunk_selection_edge(learning_prior: dict[str, Any]) -> tuple[float, dict[str, Any], list[str]]:
    profile_edge = _float(learning_prior.get("expected_edge_3d"))
    setup_edge = _float(learning_prior.get("setup_edge_3d_raw"))
    profile_n = int(learning_prior.get("sample_size_3d") or 0)
    setup_n = int(learning_prior.get("setup_sample_size_3d") or 0)
    reasons: list[str] = []

    if profile_edge is not None and profile_n >= 30:
        edge = (0.75 * profile_edge) + (0.25 * (setup_edge or 0.0))
        sample_penalty = 0.0
        reasons.append("profile_edge_high_sample")
    elif profile_edge is not None and profile_n >= 8:
        edge = (0.45 * profile_edge) + (0.55 * (setup_edge or 0.0))
        sample_penalty = 0.006
        reasons.append("profile_edge_shrunk")
    elif setup_edge is not None and setup_n >= 30:
        edge = 0.65 * setup_edge
        sample_penalty = 0.006
        reasons.append("setup_edge_high_sample")
    elif setup_edge is not None and setup_n >= 8:
        edge = 0.35 * setup_edge
        sample_penalty = 0.012
        reasons.append("setup_edge_shrunk")
    else:
        edge = 0.0
        sample_penalty = 0.018
        reasons.append("insufficient_edge_sample")

    return edge, {
        "profile_edge_3d": profile_edge,
        "profile_sample_3d": profile_n,
        "setup_edge_3d": setup_edge,
        "setup_sample_3d": setup_n,
        "sample_penalty": sample_penalty,
    }, reasons


def _selection_score_for_candidate(
    candidate: dict[str, Any],
    daily_learning_digest: dict[str, Any],
    operational_response_context: dict[str, Any],
    same_session_context: dict[str, dict[str, Any]] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or Settings()
    learning_prior = candidate.get("learning_prior") or _candidate_learning_prior(
        candidate,
        daily_learning_digest,
        operational_response_context,
    )
    setup_name = _setup_name(candidate)
    score = _float(candidate.get("score")) or 0.0
    relative_return_20d = _float(candidate.get("relative_return_20d")) or 0.0
    volume_z = _float(_technical_value(candidate, "volume_zscore_20")) or 0.0
    rsi = _float(_technical_value(candidate, "rsi_14")) or 0.0
    distance_sma20 = _float(_candidate_learning_features(candidate).get("distance_sma20"))
    confirmed_patterns = len(_confirmed_bullish_patterns(candidate))
    breakout_failure_risk = bool(_technical_value(candidate, "breakout_failure_risk"))
    orderly_breakout = bool(_technical_value(candidate, "orderly_breakout_long"))
    breakout_continuation = bool(_technical_value(candidate, "breakout_continuation_long"))
    range_expansion = setup_name == "range_expansion_breakout"
    close_position_in_range = _float(_technical_value(candidate, "close_position_in_range"))
    return_20d = _float(_technical_value(candidate, "return_20d")) or 0.0
    return_60d = _float(_technical_value(candidate, "return_60d")) or 0.0
    bollinger_pct_b = _float(_technical_value(candidate, "bollinger_pct_b_20")) or 0.0
    top_long_rank = int(candidate.get("top_long_rank") or 0)
    top_long_rank = int(candidate.get("top_long_rank") or 0)
    high_conviction_confirmed_momentum = bool(
        score >= 16.0
        and volume_z >= 1.25
        and confirmed_patterns >= 2
        and not breakout_failure_risk
        and distance_sma20 is not None
        and 0.04 <= distance_sma20 <= 0.20
        and 65.0 <= rsi <= 82.0
    )
    leader_momentum_extension = bool(
        score >= float(settings.selection_leader_momentum_min_score)
        and relative_return_20d >= float(settings.selection_leader_momentum_min_relative_return_20d)
        and confirmed_patterns >= int(settings.selection_leader_momentum_min_bullish_patterns)
        and not breakout_failure_risk
        and distance_sma20 is not None
        and 0.08 <= distance_sma20 <= float(settings.selection_leader_momentum_max_sma20_distance)
        and 60.0 <= rsi <= float(settings.selection_leader_momentum_max_rsi)
        and (
            close_position_in_range is None
            or close_position_in_range >= float(settings.selection_leader_momentum_min_close_position_in_range)
        )
        and volume_z >= float(settings.selection_leader_momentum_min_volume_z)
    )
    emerging_leader_momentum = bool(
        float(settings.selection_emerging_leader_min_score) <= score <= float(settings.selection_emerging_leader_max_score)
        and return_20d >= float(settings.selection_emerging_leader_min_return_20d)
        and not breakout_failure_risk
        and distance_sma20 is not None
        and float(settings.selection_emerging_leader_min_sma20_distance)
        <= distance_sma20
        <= float(settings.selection_emerging_leader_max_sma20_distance)
        and float(settings.selection_emerging_leader_min_rsi) <= rsi <= float(settings.selection_emerging_leader_max_rsi)
        and (
            close_position_in_range is None
            or close_position_in_range >= float(settings.selection_emerging_leader_min_close_position_in_range)
        )
        and float(settings.selection_emerging_leader_min_volume_z)
        <= volume_z
        <= float(settings.selection_emerging_leader_max_volume_z)
    )
    parabolic_leader_momentum = bool(
        score >= float(settings.selection_parabolic_leader_min_score)
        and return_20d >= float(settings.selection_parabolic_leader_min_return_20d)
        and not breakout_failure_risk
        and distance_sma20 is not None
        and float(settings.selection_parabolic_leader_min_sma20_distance)
        <= distance_sma20
        <= float(settings.selection_parabolic_leader_max_sma20_distance)
        and float(settings.selection_parabolic_leader_min_rsi) <= rsi <= float(settings.selection_parabolic_leader_max_rsi)
        and volume_z >= float(settings.selection_parabolic_leader_min_volume_z)
    )
    top_long_alignment = bool(
        top_long_rank > 0
        and top_long_rank <= int(settings.selection_top_long_alignment_max_rank)
        and score >= float(settings.selection_top_long_alignment_min_score)
        and confirmed_patterns >= int(settings.selection_top_long_alignment_min_bullish_patterns)
        and float(settings.selection_top_long_alignment_min_return_20d)
        <= return_20d
        <= float(settings.selection_top_long_alignment_max_return_20d)
        and distance_sma20 is not None
        and float(settings.selection_top_long_alignment_min_sma20_distance)
        <= distance_sma20
        <= float(settings.selection_top_long_alignment_max_sma20_distance)
        and float(settings.selection_top_long_alignment_min_rsi) <= rsi <= float(settings.selection_top_long_alignment_max_rsi)
        and float(settings.selection_top_long_alignment_min_volume_z)
        <= volume_z
        <= float(settings.selection_top_long_alignment_max_volume_z)
        and not breakout_failure_risk
    )
    constructive_early_pattern = bool(
        float(settings.selection_constructive_early_min_score) <= score <= float(settings.selection_constructive_early_max_score)
        and float(settings.selection_constructive_early_min_return_20d)
        <= return_20d
        <= float(settings.selection_constructive_early_max_return_20d)
        and float(settings.selection_constructive_early_min_return_60d)
        <= return_60d
        <= float(settings.selection_constructive_early_max_return_60d)
        and distance_sma20 is not None
        and float(settings.selection_constructive_early_min_sma20_distance)
        <= distance_sma20
        <= float(settings.selection_constructive_early_max_sma20_distance)
        and float(settings.selection_constructive_early_min_rsi) <= rsi <= float(settings.selection_constructive_early_max_rsi)
        and float(settings.selection_constructive_early_min_volume_z)
        <= volume_z
        <= float(settings.selection_constructive_early_max_volume_z)
        and bollinger_pct_b >= float(settings.selection_constructive_early_min_bollinger_pct_b)
        and confirmed_patterns >= int(settings.selection_constructive_early_min_bullish_patterns)
        and not breakout_failure_risk
    )
    same_session_intraday_rule, same_session_summary = _same_session_intraday_momentum_bonus(
        candidate,
        same_session_context or {},
        settings,
    )

    edge, edge_components, reasons = _shrunk_selection_edge(learning_prior)
    sample_penalty = float(edge_components["sample_penalty"])
    score_component = min(0.025, max(0.0, score / 1200.0))
    relative_strength_component = min(0.020, max(-0.010, relative_return_20d * 0.20))
    volume_component = (
        0.006
        if volume_z >= 1.0
        else 0.0
        if (leader_momentum_extension or emerging_leader_momentum or parabolic_leader_momentum) and volume_z < 0
        else -0.006
        if volume_z < 0
        else 0.0
    )
    pattern_component = min(0.010, confirmed_patterns * 0.005)
    continuation_component = 0.012 if orderly_breakout else 0.008 if breakout_continuation else 0.0
    high_conviction_momentum_component = 0.018 if high_conviction_confirmed_momentum else 0.0
    leader_momentum_extension_component = (
        float(settings.selection_leader_momentum_selection_bonus) if leader_momentum_extension else 0.0
    )
    emerging_leader_momentum_component = (
        float(settings.selection_emerging_leader_selection_bonus) if emerging_leader_momentum else 0.0
    )
    parabolic_leader_momentum_component = (
        float(settings.selection_parabolic_leader_selection_bonus) if parabolic_leader_momentum else 0.0
    )
    top_long_alignment_component = (
        float(settings.selection_top_long_alignment_selection_bonus) if top_long_alignment else 0.0
    )
    constructive_early_component = (
        float(settings.selection_constructive_early_selection_bonus) if constructive_early_pattern else 0.0
    )
    if same_session_intraday_rule == "same_session_intraday_leader":
        same_session_momentum_component = float(settings.intraday_same_session_leader_selection_bonus)
    elif same_session_intraday_rule == "same_session_intraday_momentum":
        same_session_momentum_component = float(settings.intraday_same_session_selection_bonus)
    else:
        same_session_momentum_component = 0.0
    failure_penalty = 0.020 if breakout_failure_risk else 0.0
    setup_risk_penalty = 0.080 if range_expansion else 0.0
    operational_penalty = _float(learning_prior.get("operational_penalty")) or 0.0
    shadow_pocket_penalties: dict[str, float] = {}
    if setup_name == "confirmed_pattern":
        shadow_pocket_penalties["confirmed_pattern"] = float(settings.selection_negative_pocket_confirmed_pattern_penalty)
    if volume_z < 0:
        shadow_pocket_penalties["volume_z_lt0"] = float(settings.selection_negative_pocket_weak_volume_penalty)
    if distance_sma20 is not None and 0.0 <= distance_sma20 < 0.06:
        shadow_pocket_penalties["sma20_dist_0_6pct"] = float(settings.selection_negative_pocket_tight_sma20_penalty)
    if 60.0 <= rsi < 75.0:
        shadow_pocket_penalties["rsi_60_75"] = float(settings.selection_negative_pocket_mid_rsi_penalty)
    pocket_penalties = shadow_pocket_penalties if settings.selection_negative_pocket_penalty_enabled else {}
    pocket_penalty_total = sum(pocket_penalties.values())

    selection_score = (
        edge
        + score_component
        + relative_strength_component
        + volume_component
        + pattern_component
        + continuation_component
        + high_conviction_momentum_component
        + leader_momentum_extension_component
        + emerging_leader_momentum_component
        + parabolic_leader_momentum_component
        + top_long_alignment_component
        + constructive_early_component
        + same_session_momentum_component
        - sample_penalty
        - failure_penalty
        - setup_risk_penalty
        - operational_penalty
        - pocket_penalty_total
    )
    if volume_component > 0:
        reasons.append("volume_confirmation")
    elif volume_component < 0:
        reasons.append("weak_volume_penalty")
    if pattern_component > 0:
        reasons.append("confirmed_pattern")
    if orderly_breakout:
        reasons.append("orderly_breakout")
    if breakout_continuation:
        reasons.append("breakout_follow_through")
    if high_conviction_confirmed_momentum:
        reasons.append("high_conviction_confirmed_momentum")
    if leader_momentum_extension:
        reasons.append("leader_momentum_extension")
    if emerging_leader_momentum:
        reasons.append("emerging_leader_momentum")
    if parabolic_leader_momentum:
        reasons.append("parabolic_leader_momentum")
    if top_long_alignment:
        reasons.append("top_long_alignment")
    if constructive_early_pattern:
        reasons.append("constructive_early_pattern")
    if same_session_intraday_rule:
        reasons.append(same_session_intraday_rule)
    if breakout_failure_risk:
        reasons.append("breakout_failure_penalty")
    if range_expansion:
        reasons.append("range_expansion_shadow_only")
    if relative_strength_component > 0:
        reasons.append("relative_strength")
    if (leader_momentum_extension or emerging_leader_momentum or parabolic_leader_momentum) and volume_z < 0:
        reasons.append("weak_volume_tolerated_for_leader")
    for key in pocket_penalties:
        reasons.append(f"negative_pocket:{key}")
    if not settings.selection_negative_pocket_penalty_enabled:
        for key in shadow_pocket_penalties:
            reasons.append(f"negative_pocket_shadow:{key}")

    return {
        "selection_score": round(selection_score, 4),
        "selection_reason": ",".join(reasons) if reasons else "baseline",
        "negative_pocket_penalty_total": round(pocket_penalty_total, 4),
        "negative_pocket_penalties": pocket_penalties,
        "negative_pocket_shadow_penalties": shadow_pocket_penalties,
        "negative_pocket_penalty_applied": bool(settings.selection_negative_pocket_penalty_enabled),
        "selection_components": {
            **{key: round(value, 4) if isinstance(value, float) else value for key, value in edge_components.items()},
            "shrunk_edge_3d": round(edge, 4),
            "score_component": round(score_component, 4),
            "relative_strength_component": round(relative_strength_component, 4),
            "volume_component": round(volume_component, 4),
            "pattern_component": round(pattern_component, 4),
            "continuation_component": round(continuation_component, 4),
            "high_conviction_momentum_component": round(high_conviction_momentum_component, 4),
            "leader_momentum_extension_component": round(leader_momentum_extension_component, 4),
            "emerging_leader_momentum_component": round(emerging_leader_momentum_component, 4),
            "parabolic_leader_momentum_component": round(parabolic_leader_momentum_component, 4),
            "top_long_alignment_component": round(top_long_alignment_component, 4),
            "constructive_early_component": round(constructive_early_component, 4),
            "same_session_momentum_component": round(same_session_momentum_component, 4),
            "failure_penalty": round(failure_penalty, 4),
            "setup_risk_penalty": round(setup_risk_penalty, 4),
            "operational_penalty": round(operational_penalty, 4),
            "negative_pocket_penalty_total": round(pocket_penalty_total, 4),
            "same_session_observations": int(same_session_summary.get("observations") or 0),
            "same_session_return": _float(same_session_summary.get("same_session_return")),
        },
        "blocked_auto_buy": range_expansion,
        "blocked_auto_buy_reason": "range_expansion_breakout_shadow_only" if range_expansion else None,
        "learning_prior": learning_prior,
    }


def _select_deterministic_candidates(
    candidates: list[dict[str, Any]],
    daily_learning_digest: dict[str, Any],
    operational_response_context: dict[str, Any],
    *,
    limit: int = 8,
    same_session_context: dict[str, dict[str, Any]] | None = None,
    settings: Settings | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    rejected: dict[str, int] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        eligible, reason = _selection_eligible(candidate)
        if not eligible:
            rejected[reason] = rejected.get(reason, 0) + 1
            continue
        selection = _selection_score_for_candidate(
            candidate,
            daily_learning_digest,
            operational_response_context,
            same_session_context=same_session_context,
            settings=settings,
        )
        annotated.append(
            {
                **candidate,
                "setup_name": candidate.get("setup_name") or _setup_name(candidate),
                **selection,
            }
        )

    score_ranked = sorted(
        annotated,
        key=lambda item: (float(item.get("score") or 0.0), float(item.get("selection_score") or -999.0)),
        reverse=True,
    )
    score_rank_by_symbol = {
        str(item.get("symbol") or "").upper(): index
        for index, item in enumerate(score_ranked, start=1)
        if str(item.get("symbol") or "").strip()
    }
    selected = sorted(
        annotated,
        key=lambda item: (float(item.get("selection_score") or -999.0), float(item.get("score") or 0.0)),
        reverse=True,
    )
    for index, item in enumerate(selected, start=1):
        item["selection_rank"] = index
        item["score_rank"] = score_rank_by_symbol.get(str(item.get("symbol") or "").upper())

    selected = selected[:limit]
    metadata = {
        "method": "selection_score_with_shrunk_learning_prior",
        "eligible": len(annotated),
        "selected": len(selected),
        "rejected": rejected,
        "shadow_only_setups": ["range_expansion_breakout"],
        "promoted_over_score_rank": [
            {
                "symbol": item.get("symbol"),
                "selection_rank": item.get("selection_rank"),
                "score_rank": item.get("score_rank"),
                "selection_score": item.get("selection_score"),
                "selection_reason": item.get("selection_reason"),
            }
            for item in selected
            if item.get("score_rank") and item.get("selection_rank") and int(item["score_rank"]) > int(item["selection_rank"])
        ][:10],
        "top_by_score": [
            {
                "symbol": item.get("symbol"),
                "score": item.get("score"),
                "selection_score": item.get("selection_score"),
                "setup_name": item.get("setup_name"),
            }
            for item in score_ranked[: min(limit, 10)]
        ],
        "same_session_intraday_promotions": [
            {
                "symbol": item.get("symbol"),
                "selection_rank": item.get("selection_rank"),
                "selection_score": item.get("selection_score"),
                "same_session_return": (item.get("selection_components", {}) or {}).get("same_session_return"),
                "observations": (item.get("selection_components", {}) or {}).get("same_session_observations"),
            }
            for item in selected
            if "same_session_intraday_momentum" in str(item.get("selection_reason") or "")
        ][:10],
    }
    return selected, metadata


def _candidate_rank_priority(
    candidate: dict[str, Any],
    daily_learning_digest: dict[str, Any],
    operational_response_context: dict[str, Any],
    same_session_context: dict[str, dict[str, Any]] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or Settings()
    learning_prior = candidate.get("learning_prior") or _candidate_learning_prior(
        candidate,
        daily_learning_digest,
        operational_response_context,
    )
    prior_accuracy = _prior_accuracy_map(daily_learning_digest).get(str(learning_prior.get("profile_key") or "").strip(), {})
    score = _float(candidate.get("score")) or 0.0
    volume_z = _float(_technical_value(candidate, "volume_zscore_20")) or 0.0
    rsi = _float(_technical_value(candidate, "rsi_14")) or 0.0
    distance_sma20 = _float(_candidate_learning_features(candidate).get("distance_sma20"))
    relative_return_20d = _float(candidate.get("relative_return_20d")) or 0.0
    expected_edge_3d_raw = _float(learning_prior.get("expected_edge_3d"))
    expected_edge_3d = expected_edge_3d_raw or 0.0
    operational_penalty = _float(learning_prior.get("operational_penalty")) or 0.0
    matched_on = str(learning_prior.get("matched_on") or "")
    prior_avg_abs_error = _float(prior_accuracy.get("avg_abs_error")) or 0.0
    confirmed_patterns = len(_confirmed_bullish_patterns(candidate))
    breakout_continuation = bool(_technical_value(candidate, "breakout_continuation_long"))
    range_expansion_breakout = bool(_technical_value(candidate, "range_expansion_breakout_long"))
    orderly_breakout = bool(_technical_value(candidate, "orderly_breakout_long"))
    breakout_failure_risk = bool(_technical_value(candidate, "breakout_failure_risk"))
    close_position_in_range = _float(_technical_value(candidate, "close_position_in_range"))
    return_20d = _float(_technical_value(candidate, "return_20d")) or 0.0
    top_long_rank = int(candidate.get("top_long_rank") or 0)
    high_conviction_confirmed_momentum = bool(
        score >= 16.0
        and volume_z >= 1.25
        and confirmed_patterns >= 2
        and not breakout_failure_risk
        and distance_sma20 is not None
        and 0.04 <= distance_sma20 <= 0.20
        and 65.0 <= rsi <= 82.0
    )
    leader_momentum_extension = bool(
        score >= float(settings.selection_leader_momentum_min_score)
        and relative_return_20d >= float(settings.selection_leader_momentum_min_relative_return_20d)
        and confirmed_patterns >= int(settings.selection_leader_momentum_min_bullish_patterns)
        and not breakout_failure_risk
        and distance_sma20 is not None
        and 0.08 <= distance_sma20 <= float(settings.selection_leader_momentum_max_sma20_distance)
        and 60.0 <= rsi <= float(settings.selection_leader_momentum_max_rsi)
        and (
            close_position_in_range is None
            or close_position_in_range >= float(settings.selection_leader_momentum_min_close_position_in_range)
        )
        and volume_z >= float(settings.selection_leader_momentum_min_volume_z)
    )
    emerging_leader_momentum = bool(
        float(settings.selection_emerging_leader_min_score) <= score <= float(settings.selection_emerging_leader_max_score)
        and return_20d >= float(settings.selection_emerging_leader_min_return_20d)
        and not breakout_failure_risk
        and distance_sma20 is not None
        and float(settings.selection_emerging_leader_min_sma20_distance)
        <= distance_sma20
        <= float(settings.selection_emerging_leader_max_sma20_distance)
        and float(settings.selection_emerging_leader_min_rsi) <= rsi <= float(settings.selection_emerging_leader_max_rsi)
        and (
            close_position_in_range is None
            or close_position_in_range >= float(settings.selection_emerging_leader_min_close_position_in_range)
        )
        and float(settings.selection_emerging_leader_min_volume_z)
        <= volume_z
        <= float(settings.selection_emerging_leader_max_volume_z)
    )
    parabolic_leader_momentum = bool(
        score >= float(settings.selection_parabolic_leader_min_score)
        and return_20d >= float(settings.selection_parabolic_leader_min_return_20d)
        and not breakout_failure_risk
        and distance_sma20 is not None
        and float(settings.selection_parabolic_leader_min_sma20_distance)
        <= distance_sma20
        <= float(settings.selection_parabolic_leader_max_sma20_distance)
        and float(settings.selection_parabolic_leader_min_rsi) <= rsi <= float(settings.selection_parabolic_leader_max_rsi)
        and volume_z >= float(settings.selection_parabolic_leader_min_volume_z)
    )
    top_long_alignment = bool(
        top_long_rank > 0
        and top_long_rank <= int(settings.selection_top_long_alignment_max_rank)
        and score >= float(settings.selection_top_long_alignment_min_score)
        and confirmed_patterns >= int(settings.selection_top_long_alignment_min_bullish_patterns)
        and float(settings.selection_top_long_alignment_min_return_20d)
        <= return_20d
        <= float(settings.selection_top_long_alignment_max_return_20d)
        and distance_sma20 is not None
        and float(settings.selection_top_long_alignment_min_sma20_distance)
        <= distance_sma20
        <= float(settings.selection_top_long_alignment_max_sma20_distance)
        and float(settings.selection_top_long_alignment_min_rsi) <= rsi <= float(settings.selection_top_long_alignment_max_rsi)
        and float(settings.selection_top_long_alignment_min_volume_z)
        <= volume_z
        <= float(settings.selection_top_long_alignment_max_volume_z)
        and not breakout_failure_risk
    )
    return_60d = _float(_technical_value(candidate, "return_60d")) or 0.0
    bollinger_pct_b = _float(_technical_value(candidate, "bollinger_pct_b_20")) or 0.0
    constructive_early_pattern = bool(
        float(settings.selection_constructive_early_min_score) <= score <= float(settings.selection_constructive_early_max_score)
        and float(settings.selection_constructive_early_min_return_20d)
        <= return_20d
        <= float(settings.selection_constructive_early_max_return_20d)
        and float(settings.selection_constructive_early_min_return_60d)
        <= return_60d
        <= float(settings.selection_constructive_early_max_return_60d)
        and distance_sma20 is not None
        and float(settings.selection_constructive_early_min_sma20_distance)
        <= distance_sma20
        <= float(settings.selection_constructive_early_max_sma20_distance)
        and float(settings.selection_constructive_early_min_rsi) <= rsi <= float(settings.selection_constructive_early_max_rsi)
        and float(settings.selection_constructive_early_min_volume_z)
        <= volume_z
        <= float(settings.selection_constructive_early_max_volume_z)
        and bollinger_pct_b >= float(settings.selection_constructive_early_min_bollinger_pct_b)
        and confirmed_patterns >= int(settings.selection_constructive_early_min_bullish_patterns)
        and not breakout_failure_risk
    )
    same_session_intraday_rule, same_session_summary = _same_session_intraday_momentum_bonus(
        candidate,
        same_session_context or {},
        settings,
    )
    score_component = min(0.04, max(0.0, score / 1000.0))
    relative_strength_component = min(0.03, max(-0.01, relative_return_20d * 0.25))
    volume_component = (
        0.01
        if volume_z >= 1.0
        else 0.0
        if (leader_momentum_extension or emerging_leader_momentum or parabolic_leader_momentum) and volume_z < 0
        else -0.01
        if volume_z < 0
        else 0.0
    )
    pattern_component = min(0.02, confirmed_patterns * 0.01)
    continuation_component = (
        0.025
        if range_expansion_breakout
        else 0.02
        if orderly_breakout
        else 0.015
        if breakout_continuation
        else 0.0
    )
    high_conviction_momentum_component = 0.015 if high_conviction_confirmed_momentum else 0.0
    leader_momentum_extension_component = (
        float(settings.selection_leader_momentum_priority_bonus) if leader_momentum_extension else 0.0
    )
    emerging_leader_momentum_component = (
        float(settings.selection_emerging_leader_priority_bonus) if emerging_leader_momentum else 0.0
    )
    parabolic_leader_momentum_component = (
        float(settings.selection_parabolic_leader_priority_bonus) if parabolic_leader_momentum else 0.0
    )
    top_long_alignment_component = (
        float(settings.selection_top_long_alignment_priority_bonus) if top_long_alignment else 0.0
    )
    constructive_early_component = (
        float(settings.selection_constructive_early_priority_bonus) if constructive_early_pattern else 0.0
    )
    if same_session_intraday_rule == "same_session_intraday_leader":
        same_session_momentum_component = float(settings.intraday_same_session_leader_priority_bonus)
    elif same_session_intraday_rule == "same_session_intraday_momentum":
        same_session_momentum_component = float(settings.intraday_same_session_priority_bonus)
    else:
        same_session_momentum_component = 0.0
    failure_penalty = 0.02 if breakout_failure_risk else 0.0
    prior_error_penalty = min(0.06, prior_avg_abs_error * 0.5)
    priority_score = (
        expected_edge_3d
        - operational_penalty
        - prior_error_penalty
        - failure_penalty
        + score_component
        + relative_strength_component
        + volume_component
        + pattern_component
        + continuation_component
        + high_conviction_momentum_component
        + leader_momentum_extension_component
        + emerging_leader_momentum_component
        + parabolic_leader_momentum_component
        + top_long_alignment_component
        + constructive_early_component
        + same_session_momentum_component
    )
    reasons = []
    if expected_edge_3d > 0:
        reasons.append("recent_edge")
    elif matched_on == "none":
        reasons.append("no_recent_edge_history")
    if prior_avg_abs_error >= 0.04:
        reasons.append("estimation_error_penalty")
    if volume_component > 0:
        reasons.append("volume_confirmation")
    if pattern_component > 0:
        reasons.append("confirmed_pattern")
    if breakout_continuation:
        reasons.append("breakout_follow_through")
    if range_expansion_breakout:
        reasons.append("range_expansion_breakout")
    if orderly_breakout:
        reasons.append("orderly_breakout")
    if high_conviction_confirmed_momentum:
        reasons.append("high_conviction_confirmed_momentum")
    if leader_momentum_extension:
        reasons.append("leader_momentum_extension")
    if emerging_leader_momentum:
        reasons.append("emerging_leader_momentum")
    if parabolic_leader_momentum:
        reasons.append("parabolic_leader_momentum")
    if top_long_alignment:
        reasons.append("top_long_alignment")
    if constructive_early_pattern:
        reasons.append("constructive_early_pattern")
    if same_session_intraday_rule:
        reasons.append(same_session_intraday_rule)
    if breakout_failure_risk:
        reasons.append("breakout_failure_penalty")
    if relative_strength_component > 0:
        reasons.append("relative_strength")
    if (leader_momentum_extension or emerging_leader_momentum or parabolic_leader_momentum) and volume_z < 0:
        reasons.append("weak_volume_tolerated_for_leader")
    return {
        "rank_priority_score": round(priority_score, 4),
        "rank_priority_components": {
            "expected_edge_3d": round(expected_edge_3d, 4),
            "operational_penalty": round(operational_penalty, 4),
            "prior_error_penalty": round(prior_error_penalty, 4),
            "score_component": round(score_component, 4),
            "relative_strength_component": round(relative_strength_component, 4),
            "volume_component": round(volume_component, 4),
            "pattern_component": round(pattern_component, 4),
            "continuation_component": round(continuation_component, 4),
            "high_conviction_momentum_component": round(high_conviction_momentum_component, 4),
            "leader_momentum_extension_component": round(leader_momentum_extension_component, 4),
            "emerging_leader_momentum_component": round(emerging_leader_momentum_component, 4),
            "parabolic_leader_momentum_component": round(parabolic_leader_momentum_component, 4),
            "top_long_alignment_component": round(top_long_alignment_component, 4),
            "constructive_early_component": round(constructive_early_component, 4),
            "same_session_momentum_component": round(same_session_momentum_component, 4),
            "failure_penalty": round(failure_penalty, 4),
            "same_session_observations": int(same_session_summary.get("observations") or 0),
            "same_session_return": _float(same_session_summary.get("same_session_return")),
        },
        "rank_priority_reason": ",".join(reasons) if reasons else "baseline",
    }


def _annotate_technical_context_with_learning(
    technical_context: dict[str, Any],
    daily_learning_digest: dict[str, Any],
    operational_response_context: dict[str, Any],
    data_dir: Path | None = None,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    base_context = dict(technical_context)
    if isinstance(base_context.get("all_candidates"), list):
        base_context["all_candidates"] = _annotate_candidates_with_top_long_rank(
            base_context.get("all_candidates", []) or [],
            base_context.get("top_longs", []) or [],
        )
    if isinstance(base_context.get("selected_candidates"), list):
        base_context["selected_candidates"] = _annotate_candidates_with_top_long_rank(
            base_context.get("selected_candidates", []) or [],
            base_context.get("top_longs", []) or [],
        )
    if isinstance(base_context.get("top_longs"), list):
        base_context["top_longs"] = _annotate_candidates_with_top_long_rank(
            base_context.get("top_longs", []) or [],
            base_context.get("top_longs", []) or [],
        )
    effective_settings = settings
    if effective_settings is None and data_dir is not None:
        effective_settings = Settings(DATA_DIR=data_dir)
    same_session_context = _same_session_intraday_context(data_dir, base_context)
    if not base_context.get("selected_candidates") and isinstance(base_context.get("all_candidates"), list):
        selection_limit = _deterministic_selection_limit(effective_settings) if effective_settings is not None else 8
        selected, metadata = _select_deterministic_candidates(
            base_context.get("all_candidates", []) or [],
            daily_learning_digest,
            operational_response_context,
            limit=selection_limit,
            same_session_context=same_session_context,
            settings=effective_settings,
        )
        base_context["selected_candidates"] = selected
        base_context["selection_metadata"] = metadata

    notes = (
        operational_response_context.get("response_notes", {})
        if isinstance(operational_response_context, dict)
        else {}
    )

    def annotate(candidate: dict[str, Any]) -> dict[str, Any]:
        setup_name = _setup_name(candidate)
        prior = _candidate_learning_prior(candidate, daily_learning_digest, operational_response_context)
        priority = _candidate_rank_priority(
            {**candidate, "learning_prior": prior},
            daily_learning_digest,
            operational_response_context,
            same_session_context=same_session_context,
            settings=effective_settings,
        )
        setup_edge = _float(prior.get("expected_edge_3d"))
        penalty = _float(prior.get("operational_penalty")) or 0.0
        return {
            **candidate,
            "setup_name": candidate.get("setup_name") or setup_name,
            "setup_edge_3d": round(setup_edge, 4) if setup_edge is not None else None,
            "operational_penalty": round(penalty, 4),
            "effective_setup_edge_3d": round(setup_edge, 4) if setup_edge is not None else None,
            "setup_win_rate_3d": prior.get("win_rate_recent_3d"),
            "setup_matured_3d": prior.get("sample_size_3d"),
            "learning_prior": prior,
            "same_session_intraday": same_session_context.get(str(candidate.get("symbol") or "").upper(), {}),
            "operational_notes": notes.get(setup_name, []),
            "rank_priority_score": priority.get("rank_priority_score"),
            "rank_priority_components": priority.get("rank_priority_components"),
            "rank_priority_reason": priority.get("rank_priority_reason"),
        }

    annotated = dict(base_context)
    for key in ("selected_candidates", "top_longs", "top_shorts", "all_candidates"):
        rows = base_context.get(key, []) or []
        if isinstance(rows, list):
            items = [annotate(item) if isinstance(item, dict) else item for item in rows]
            if key == "selected_candidates":
                items = sorted(
                    items,
                    key=lambda item: (
                        float(item.get("selection_score") or item.get("rank_priority_score") or 0.0),
                        float(item.get("score") or 0.0),
                    ),
                    reverse=True,
                )
            elif key != "top_shorts":
                items = sorted(
                    items,
                    key=lambda item: (
                        float(item.get("rank_priority_score") or 0.0),
                        float(item.get("score") or 0.0),
                    ),
                    reverse=True,
                )
            annotated[key] = items
    return annotated


def _build_decision_learning_context(
    daily_learning_digest: dict[str, Any],
    operational_response_context: dict[str, Any],
) -> dict[str, Any]:
    setup_rows = list((daily_learning_digest or {}).get("setup_stats_3d", []) or [])
    ranked = [
        item
        for item in setup_rows
        if isinstance(item, dict) and isinstance(item.get("avg_return"), (int, float))
    ]
    ranked.sort(key=lambda item: (float(item.get("avg_return") or 0.0), float(item.get("win_rate") or 0.0)), reverse=True)
    active_responses = []
    for item in (operational_response_context.get("responses", []) if isinstance(operational_response_context, dict) else []):
        if str(item.get("status") or "") in {"guarded_active", "active"}:
            active_responses.append(
                {
                    "action": item.get("action"),
                    "scope": item.get("scope"),
                    "detail": item.get("detail"),
                    "mode": item.get("mode"),
                }
            )
    return {
        "guidance": list((daily_learning_digest or {}).get("guidance", []) or [])[:8],
        "top_setups_3d": ranked[:5],
        "weak_setups_3d": list(reversed(ranked[-5:]))[:5],
        "active_operational_responses": active_responses[:8],
        "confidence_calibration_3d": list((daily_learning_digest or {}).get("confidence_calibration_3d", []) or [])[:8],
        "prior_accuracy_3d": list((daily_learning_digest or {}).get("prior_accuracy_3d", []) or [])[:8],
        "summary": (daily_learning_digest or {}).get("summary", {}),
    }


def _confidence_bucket(value: Any) -> str:
    number = _float(value)
    if number is None:
        return "unknown"
    if number < 0.60:
        return "lt0_60"
    if number < 0.75:
        return "0_60_0_74"
    if number < 0.90:
        return "0_75_0_89"
    return "gte0_90"


def _confidence_calibration_map(digest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = digest.get("confidence_calibration_3d", []) if isinstance(digest, dict) else []
    return {
        str(item.get("bucket") or "").strip(): item
        for item in rows or []
        if str(item.get("bucket") or "").strip()
    }


def _prior_accuracy_map(digest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = digest.get("prior_accuracy_3d", []) if isinstance(digest, dict) else []
    return {
        str(item.get("profile_key") or "").strip(): item
        for item in rows or []
        if str(item.get("profile_key") or "").strip()
    }


def _sizing_adjustment_for_recommendation(
    recommendation: TradeRecommendation,
    technical_context: dict[str, Any],
    daily_learning_digest: dict[str, Any],
    operational_response_context: dict[str, Any],
) -> dict[str, Any]:
    candidate = _candidate_for_symbol(technical_context, recommendation.symbol) or {}
    learning_prior = candidate.get("learning_prior") or _candidate_learning_prior(
        candidate,
        daily_learning_digest,
        operational_response_context,
    )
    calibration = _confidence_calibration_map(daily_learning_digest).get(_confidence_bucket(recommendation.confidence), {})
    prior_accuracy = _prior_accuracy_map(daily_learning_digest).get(str(learning_prior.get("profile_key") or "").strip(), {})
    prior_edge = _float(learning_prior.get("expected_edge_3d"))
    prior_sample = int(learning_prior.get("sample_size_3d") or 0)
    prior_confidence = _float(learning_prior.get("confidence_weight_3d")) or 0.0
    calibration_edge = _float(calibration.get("avg_return"))
    calibration_win_rate = _float(calibration.get("win_rate"))
    calibration_sample = int(calibration.get("matured") or 0)
    prior_avg_abs_error = _float(prior_accuracy.get("avg_abs_error"))
    prior_accuracy_sample = int(prior_accuracy.get("matured") or 0)

    multiplier = 1.0
    reasons = []
    if prior_edge is not None and prior_sample >= 6 and prior_confidence >= 0.5:
        if prior_edge <= 0:
            multiplier *= 0.75
            reasons.append("negative_recent_prior")
        elif prior_edge >= 0.03:
            multiplier *= 1.10
            reasons.append("strong_recent_prior")
    if calibration_edge is not None and calibration_sample >= 5:
        if calibration_edge <= 0 or ((calibration_win_rate or 0.0) < 0.45):
            multiplier *= 0.85
            reasons.append("weak_confidence_calibration")
        elif calibration_edge >= 0.02 and (calibration_win_rate or 0.0) >= 0.55:
            multiplier *= 1.05
            reasons.append("strong_confidence_calibration")
    if prior_avg_abs_error is not None and prior_accuracy_sample >= 5:
        if prior_avg_abs_error >= 0.04:
            multiplier *= 0.80
            reasons.append("high_prior_estimation_error")
        elif prior_avg_abs_error <= 0.015:
            multiplier *= 1.03
            reasons.append("stable_prior_estimation")
    multiplier = min(1.15, max(0.50, multiplier))
    return {
        "size_multiplier": round(multiplier, 4),
        "reason": ",".join(reasons) if reasons else "baseline",
        "learning_prior": learning_prior,
        "confidence_bucket": _confidence_bucket(recommendation.confidence),
        "confidence_calibration": calibration,
        "prior_accuracy": prior_accuracy,
    }


def validate_entry_quality(
    settings: Settings,
    recommendation: TradeRecommendation,
    technical_context: dict[str, Any] | None,
    sentiment_context: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    if not settings.entry_quality_gate_enabled or recommendation.action != "buy":
        return True, "entry-quality desactivado o no aplica", {}

    candidate = _candidate_for_symbol(technical_context or {}, recommendation.symbol)
    if candidate is None:
        return False, "simbolo ausente del escaneo tecnico actual", {"symbol": recommendation.symbol}

    score = int(_float(candidate.get("score")) or 0)
    setup_quality = str(candidate.get("setup_quality") or "").lower()
    direction = str(candidate.get("direction") or "").lower()
    rsi = _float(_technical_value(candidate, "rsi_14"))
    close = _float(_technical_value(candidate, "close")) or recommendation.entry_price
    sma20 = _float(_technical_value(candidate, "sma_20"))
    macd = _float(_technical_value(candidate, "macd"))
    macd_signal = _float(_technical_value(candidate, "macd_signal"))
    return_20d = _float(_technical_value(candidate, "return_20d"))
    volume_z = _float(_technical_value(candidate, "volume_zscore_20"))
    gap_pct = _float(_technical_value(candidate, "gap_pct"))
    close_position = _float(_technical_value(candidate, "close_position_in_range"))
    event_momentum_long = bool(_technical_value(candidate, "event_momentum_long"))
    range_expansion_breakout_long = bool(_technical_value(candidate, "range_expansion_breakout_long"))
    orderly_breakout_long = bool(_technical_value(candidate, "orderly_breakout_long"))
    breakout_continuation_long = bool(_technical_value(candidate, "breakout_continuation_long"))
    breakout_failure_risk = bool(_technical_value(candidate, "breakout_failure_risk"))
    momentum_shakeout_hold_long = bool(_technical_value(candidate, "momentum_shakeout_hold_long"))
    relative_return_20d = _float(candidate.get("relative_return_20d"))
    confirmed_patterns = _confirmed_bullish_patterns(candidate)
    momentum_confirmation_long = (
        not event_momentum_long
        and not range_expansion_breakout_long
        and not orderly_breakout_long
        and not momentum_shakeout_hold_long
        and bool(confirmed_patterns)
        and (return_20d is not None and return_20d >= settings.entry_quality_momentum_confirmation_min_return_20d)
        and (volume_z is not None and volume_z >= settings.entry_quality_momentum_confirmation_min_volume_z)
        and (close_position is not None and close_position >= 0.75)
    )
    sentiment = _sentiment_for_symbol(sentiment_context, recommendation.symbol)
    sentiment_score = _float(sentiment.get("sentiment_score"))
    sentiment_confidence = _float(sentiment.get("confidence")) or 0.0
    sentiment_flags = [str(flag) for flag in sentiment.get("risk_flags", [])]
    daily_learning_digest = load_daily_learning_context(settings.data_dir)
    operational_response_context = load_operational_response_context(settings.data_dir)
    learning_prior = candidate.get("learning_prior") or _candidate_learning_prior(
        candidate,
        daily_learning_digest,
        operational_response_context,
    )
    prior_accuracy = _prior_accuracy_map(daily_learning_digest).get(str(learning_prior.get("profile_key") or "").strip(), {})

    checks = {
        "score": score,
        "setup_quality": setup_quality,
        "direction": direction,
        "rsi_14": rsi,
        "close": close,
        "sma_20": sma20,
        "sma20_distance": None,
        "macd": macd,
        "macd_signal": macd_signal,
        "return_20d": return_20d,
        "volume_zscore_20": volume_z,
        "gap_pct": gap_pct,
        "close_position_in_range": close_position,
        "event_momentum_long": event_momentum_long,
        "range_expansion_breakout_long": range_expansion_breakout_long,
        "orderly_breakout_long": orderly_breakout_long,
        "breakout_continuation_long": breakout_continuation_long,
        "breakout_failure_risk": breakout_failure_risk,
        "momentum_shakeout_hold_long": momentum_shakeout_hold_long,
        "momentum_confirmation_long": momentum_confirmation_long,
        "relative_return_20d": relative_return_20d,
        "confirmed_bullish_patterns": len(confirmed_patterns),
        "sentiment_score": sentiment_score,
        "sentiment_confidence": sentiment_confidence,
        "sentiment_flags": sentiment_flags,
        "learning_prior": learning_prior,
        "prior_accuracy": prior_accuracy,
    }
    if close and sma20:
        checks["sma20_distance"] = round((close - sma20) / sma20, 4)
    fallback_constructive_extension = (
        recommendation.source == "deterministic_fallback"
        and _fallback_constructive_extension_exception(
            settings,
            candidate,
            score=score,
            return_20d=return_20d,
            rsi=rsi,
            sma20_distance=checks["sma20_distance"],
            volume_z=volume_z,
            confirmed_patterns=len(confirmed_patterns),
        )
    )
    fallback_momentum_extension = (
        recommendation.source == "deterministic_fallback"
        and _fallback_momentum_extension_exception(
            settings,
            candidate,
            score=score,
            return_20d=return_20d,
            rsi=rsi,
            sma20_distance=checks["sma20_distance"],
            volume_z=volume_z,
            confirmed_patterns=len(confirmed_patterns),
        )
    )
    fallback_weak_volume_momentum_extension = (
        recommendation.source == "deterministic_fallback"
        and _fallback_weak_volume_momentum_extension_exception(
            settings,
            candidate,
            score=score,
            return_20d=return_20d,
            rsi=rsi,
            sma20_distance=checks["sma20_distance"],
            volume_z=volume_z,
            confirmed_patterns=len(confirmed_patterns),
        )
    )
    fallback_relative_strength_pullback_extension = (
        recommendation.source == "deterministic_fallback"
        and _fallback_relative_strength_pullback_extension_exception(
            settings,
            candidate,
            score=score,
            return_20d=return_20d,
            relative_return_20d=relative_return_20d,
            rsi=rsi,
            sma20_distance=checks["sma20_distance"],
            volume_z=volume_z,
            confirmed_patterns=len(confirmed_patterns),
        )
    )
    fallback_leader_pullback_extension = (
        recommendation.source == "deterministic_fallback"
        and _fallback_leader_pullback_extension_exception(
            settings,
            candidate,
            score=score,
            return_20d=return_20d,
            rsi=rsi,
            sma20_distance=checks["sma20_distance"],
            volume_z=volume_z,
            confirmed_patterns=len(confirmed_patterns),
        )
    )
    fallback_top_long_follow_through = (
        recommendation.source == "deterministic_fallback"
        and _fallback_top_long_follow_through_exception(
            settings,
            candidate,
            score=score,
            return_20d=return_20d,
            rsi=rsi,
            volume_z=volume_z,
            confirmed_patterns=len(confirmed_patterns),
        )
    )
    prior_error_volume_confirmation_override = (
        recommendation.source == "deterministic_fallback"
        and _prior_error_volume_confirmation_override_exception(
            settings,
            candidate,
            score=score,
            return_20d=return_20d,
            rsi=rsi,
            volume_z=volume_z,
            confirmed_patterns=len(confirmed_patterns),
        )
    )
    low_score_volume_rebound_override = (
        recommendation.source == "deterministic_fallback"
        and _low_score_volume_rebound_override_exception(
            settings,
            candidate,
            score=score,
            return_20d=return_20d,
            rsi=rsi,
            volume_z=volume_z,
        )
    )
    checks["fallback_constructive_extension_exception"] = {
        "eligible": fallback_constructive_extension,
        "max_selection_rank": settings.entry_quality_fallback_constructive_extension_max_selection_rank,
        "min_score": settings.entry_quality_fallback_constructive_extension_min_score,
        "min_return_20d": settings.entry_quality_fallback_constructive_extension_min_return_20d,
        "min_rsi": settings.entry_quality_fallback_constructive_extension_min_rsi,
        "max_sma20_distance": settings.entry_quality_fallback_constructive_extension_max_sma20_distance,
        "min_volume_zscore_20": settings.entry_quality_fallback_constructive_extension_min_volume_z,
        "min_bullish_patterns": settings.entry_quality_fallback_constructive_extension_min_bullish_patterns,
    }
    checks["fallback_momentum_extension_exception"] = {
        "eligible": fallback_momentum_extension,
        "max_selection_rank": settings.entry_quality_fallback_momentum_extension_max_selection_rank,
        "min_score": settings.entry_quality_fallback_momentum_extension_min_score,
        "min_return_20d": settings.entry_quality_fallback_momentum_extension_min_return_20d,
        "min_rsi": settings.entry_quality_fallback_momentum_extension_min_rsi,
        "max_rsi": settings.entry_quality_fallback_momentum_extension_max_rsi,
        "max_sma20_distance": settings.entry_quality_fallback_momentum_extension_max_sma20_distance,
        "min_volume_zscore_20": settings.entry_quality_fallback_momentum_extension_min_volume_z,
        "min_bullish_patterns": settings.entry_quality_fallback_momentum_extension_min_bullish_patterns,
    }
    checks["fallback_weak_volume_momentum_extension_exception"] = {
        "eligible": fallback_weak_volume_momentum_extension,
        "max_selection_rank": settings.entry_quality_fallback_weak_volume_momentum_extension_max_selection_rank,
        "min_score": settings.entry_quality_fallback_weak_volume_momentum_extension_min_score,
        "min_return_20d": settings.entry_quality_fallback_weak_volume_momentum_extension_min_return_20d,
        "min_rsi": settings.entry_quality_fallback_weak_volume_momentum_extension_min_rsi,
        "max_rsi": settings.entry_quality_fallback_weak_volume_momentum_extension_max_rsi,
        "min_sma20_distance": settings.entry_quality_fallback_weak_volume_momentum_extension_min_sma20_distance,
        "max_sma20_distance": settings.entry_quality_fallback_weak_volume_momentum_extension_max_sma20_distance,
        "min_volume_zscore_20": settings.entry_quality_fallback_weak_volume_momentum_extension_min_volume_z,
        "max_volume_zscore_20": settings.entry_quality_fallback_weak_volume_momentum_extension_max_volume_z,
        "min_bullish_patterns": settings.entry_quality_fallback_weak_volume_momentum_extension_min_bullish_patterns,
    }
    checks["fallback_relative_strength_pullback_extension_exception"] = {
        "eligible": fallback_relative_strength_pullback_extension,
        "max_selection_rank": settings.entry_quality_fallback_relative_strength_pullback_extension_max_selection_rank,
        "min_score": settings.entry_quality_fallback_relative_strength_pullback_extension_min_score,
        "min_return_20d": settings.entry_quality_fallback_relative_strength_pullback_extension_min_return_20d,
        "max_return_20d": settings.entry_quality_fallback_relative_strength_pullback_extension_max_return_20d,
        "min_relative_return_20d": settings.entry_quality_fallback_relative_strength_pullback_extension_min_relative_return_20d,
        "max_relative_return_20d": settings.entry_quality_fallback_relative_strength_pullback_extension_max_relative_return_20d,
        "min_rsi": settings.entry_quality_fallback_relative_strength_pullback_extension_min_rsi,
        "max_rsi": settings.entry_quality_fallback_relative_strength_pullback_extension_max_rsi,
        "min_sma20_distance": settings.entry_quality_fallback_relative_strength_pullback_extension_min_sma20_distance,
        "max_sma20_distance": settings.entry_quality_fallback_relative_strength_pullback_extension_max_sma20_distance,
        "min_volume_zscore_20": settings.entry_quality_fallback_relative_strength_pullback_extension_min_volume_z,
        "max_volume_zscore_20": settings.entry_quality_fallback_relative_strength_pullback_extension_max_volume_z,
        "min_bullish_patterns": settings.entry_quality_fallback_relative_strength_pullback_extension_min_bullish_patterns,
    }
    checks["fallback_leader_pullback_extension_exception"] = {
        "eligible": fallback_leader_pullback_extension,
        "max_selection_rank": settings.entry_quality_fallback_leader_pullback_extension_max_selection_rank,
        "min_score": settings.entry_quality_fallback_leader_pullback_extension_min_score,
        "min_return_20d": settings.entry_quality_fallback_leader_pullback_extension_min_return_20d,
        "max_return_20d": settings.entry_quality_fallback_leader_pullback_extension_max_return_20d,
        "min_rsi": settings.entry_quality_fallback_leader_pullback_extension_min_rsi,
        "max_rsi": settings.entry_quality_fallback_leader_pullback_extension_max_rsi,
        "min_sma20_distance": settings.entry_quality_fallback_leader_pullback_extension_min_sma20_distance,
        "max_sma20_distance": settings.entry_quality_fallback_leader_pullback_extension_max_sma20_distance,
        "min_volume_zscore_20": settings.entry_quality_fallback_leader_pullback_extension_min_volume_z,
        "max_volume_zscore_20": settings.entry_quality_fallback_leader_pullback_extension_max_volume_z,
        "min_bullish_patterns": settings.entry_quality_fallback_leader_pullback_extension_min_bullish_patterns,
    }
    checks["fallback_top_long_follow_through_exception"] = {
        "eligible": fallback_top_long_follow_through,
        "max_selection_rank": settings.entry_quality_fallback_top_long_follow_through_max_selection_rank,
        "min_score": settings.entry_quality_fallback_top_long_follow_through_min_score,
        "min_return_20d": settings.entry_quality_fallback_top_long_follow_through_min_return_20d,
        "max_return_20d": settings.entry_quality_fallback_top_long_follow_through_max_return_20d,
        "min_rsi": settings.entry_quality_fallback_top_long_follow_through_min_rsi,
        "max_rsi": settings.entry_quality_fallback_top_long_follow_through_max_rsi,
        "min_volume_zscore_20": settings.entry_quality_fallback_top_long_follow_through_min_volume_z,
        "max_volume_zscore_20": settings.entry_quality_fallback_top_long_follow_through_max_volume_z,
        "min_bullish_patterns": settings.entry_quality_fallback_top_long_follow_through_min_bullish_patterns,
    }
    checks["prior_error_volume_confirmation_override_exception"] = {
        "eligible": prior_error_volume_confirmation_override,
        "max_selection_rank": settings.entry_quality_prior_error_volume_confirmation_override_max_selection_rank,
        "min_score": settings.entry_quality_prior_error_volume_confirmation_override_min_score,
        "min_return_20d": settings.entry_quality_prior_error_volume_confirmation_override_min_return_20d,
        "min_rsi": settings.entry_quality_prior_error_volume_confirmation_override_min_rsi,
        "max_rsi": settings.entry_quality_prior_error_volume_confirmation_override_max_rsi,
        "min_volume_zscore_20": settings.entry_quality_prior_error_volume_confirmation_override_min_volume_z,
        "min_bullish_patterns": settings.entry_quality_prior_error_volume_confirmation_override_min_bullish_patterns,
    }
    checks["low_score_volume_rebound_override_exception"] = {
        "eligible": low_score_volume_rebound_override,
        "max_selection_rank": settings.entry_quality_low_score_volume_rebound_max_selection_rank,
        "min_score": settings.entry_quality_low_score_volume_rebound_min_score,
        "max_score": settings.entry_quality_low_score_volume_rebound_max_score,
        "min_return_20d": settings.entry_quality_low_score_volume_rebound_min_return_20d,
        "max_return_20d": settings.entry_quality_low_score_volume_rebound_max_return_20d,
        "min_rsi": settings.entry_quality_low_score_volume_rebound_min_rsi,
        "max_rsi": settings.entry_quality_low_score_volume_rebound_max_rsi,
        "min_volume_zscore_20": settings.entry_quality_low_score_volume_rebound_min_volume_z,
    }

    if direction != "long":
        return False, f"direccion tecnica no es long ({direction or 'desconocida'})", checks
    if setup_quality != "strong":
        return False, f"setup no es strong ({setup_quality or 'desconocido'})", checks
    if range_expansion_breakout_long:
        reward_risk = _entry_reward_risk(recommendation)
        confirmed_negative_sentiment = (
            sentiment_score is not None
            and sentiment_confidence >= 0.5
            and sentiment_score <= -0.5
        )
        range_expansion_eligible = (
            settings.trading_mode == "paper"
            and settings.trade_aggressiveness_profile in {"opportunistic", "aggressive"}
            and score >= 16
            and volume_z is not None
            and volume_z >= 1.25
            and close_position is not None
            and close_position >= 0.80
            and (rsi is None or rsi <= 82.0)
            and checks["sma20_distance"] is not None
            and checks["sma20_distance"] <= 0.22
            and reward_risk is not None
            and reward_risk >= 1.5
            and not confirmed_negative_sentiment
        )
        checks["range_expansion_breakout_exception"] = {
            "eligible": range_expansion_eligible,
            "profile": settings.trade_aggressiveness_profile,
            "paper_only": settings.trading_mode == "paper",
            "min_score": 16,
            "min_volume_zscore_20": 1.25,
            "min_close_position_in_range": 0.80,
            "max_rsi": 82.0,
            "max_sma20_distance": 0.22,
            "min_reward_risk": 1.5,
            "reward_risk": round(reward_risk, 4) if reward_risk is not None else None,
            "confirmed_negative_sentiment": confirmed_negative_sentiment,
        }
        if not range_expansion_eligible:
            checks["shadow_only_setup"] = "range_expansion_breakout"
            return False, "range_expansion_breakout_shadow_only", checks
    if score < settings.entry_quality_min_score and not low_score_volume_rebound_override:
        return False, f"score {score} < minimo {settings.entry_quality_min_score}", checks
    if return_20d is not None and return_20d <= 0:
        return False, f"momentum 20d no positivo ({return_20d:.2%})", checks
    if relative_return_20d is not None and relative_return_20d <= 0:
        return False, f"fuerza relativa 20d negativa vs benchmark ({relative_return_20d:.2%})", checks
    if macd is not None and macd_signal is not None and macd <= macd_signal and not low_score_volume_rebound_override:
        return False, "MACD no confirma momentum alcista", checks
    deterministic_fallback = recommendation.source == "deterministic_fallback"
    checks["deterministic_fallback"] = deterministic_fallback
    sentiment_failed = "sentiment_failed" in sentiment_flags
    checks["sentiment_data_quality"] = {
        "status": "missing_or_failed" if sentiment_failed or sentiment_score is None else "available",
        "penalized": bool(sentiment_failed or sentiment_score is None),
    }
    if (
        settings.news_sentiment_fail_closed_for_buys
        and sentiment_failed
        and not deterministic_fallback
    ):
        return False, "sentimiento no validado; compra bloqueada por fallo de noticias", checks
    if sentiment_score is not None and sentiment_confidence >= 0.5 and sentiment_score <= -0.5:
        return False, f"sentimiento negativo confirmado ({sentiment_score})", checks
    if settings.entry_score_v2_enabled:
        entry_score = _entry_score_v2(
            settings,
            recommendation,
            score=score,
            setup_quality=setup_quality,
            direction=direction,
            rsi=rsi,
            sma20_distance=checks["sma20_distance"],
            macd=macd,
            macd_signal=macd_signal,
            return_20d=return_20d,
            volume_z=volume_z,
            relative_return_20d=relative_return_20d,
            sentiment_score=sentiment_score,
            sentiment_confidence=sentiment_confidence,
            sentiment_failed=sentiment_failed,
            learning_prior=learning_prior,
        )
        reward_risk_margin_tolerance = float(settings.entry_score_v2_reward_risk_margin_tolerance)
        reward_risk = _float(entry_score.get("reward_risk"))
        selected_rank = int(candidate.get("selection_rank") or 0)
        reward_risk_hard_blocks = list(entry_score.get("hard_blocks") or [])
        high_conviction_reward_risk_override = bool(
            settings.entry_score_v2_reward_risk_margin_override_enabled
            and deterministic_fallback
            and reward_risk is not None
            and score >= int(settings.entry_score_v2_reward_risk_override_min_score)
            and selected_rank > 0
            and selected_rank <= int(settings.entry_score_v2_reward_risk_override_max_selection_rank)
            and return_20d is not None
            and return_20d >= float(settings.entry_score_v2_reward_risk_override_min_return_20d)
            and rsi is not None
            and rsi >= float(settings.entry_score_v2_reward_risk_override_min_rsi)
            and checks["sma20_distance"] is not None
            and checks["sma20_distance"] <= float(settings.entry_score_v2_reward_risk_override_max_sma20_distance)
            and reward_risk_hard_blocks == ["reward_risk_bajo"]
            and reward_risk >= float(settings.entry_score_v2_min_reward_risk) - reward_risk_margin_tolerance
        )
        follow_through_reward_risk_override = bool(
            deterministic_fallback
            and reward_risk is not None
            and reward_risk_hard_blocks == ["reward_risk_bajo"]
            and reward_risk >= float(settings.entry_score_v2_min_reward_risk) - reward_risk_margin_tolerance
            and _reward_risk_follow_through_override_exception(
                settings,
                candidate,
                score=score,
                return_20d=return_20d,
                rsi=rsi,
                sma20_distance=checks["sma20_distance"],
                confirmed_patterns=len(confirmed_patterns),
            )
        )
        late_constructive_follow_through_reward_risk_override = bool(
            deterministic_fallback
            and reward_risk is not None
            and reward_risk_hard_blocks == ["reward_risk_bajo"]
            and reward_risk >= float(settings.entry_score_v2_min_reward_risk) - reward_risk_margin_tolerance
            and _late_constructive_follow_through_reward_risk_override_exception(
                settings,
                candidate,
                score=score,
                return_20d=return_20d,
                rsi=rsi,
                volume_z=volume_z,
            )
        )
        low_score_volume_rebound_entry_score_override = bool(
            deterministic_fallback
            and low_score_volume_rebound_override
            and reward_risk_hard_blocks == ["reward_risk_bajo"]
        )
        relative_strength_pullback_entry_score_override = bool(
            deterministic_fallback
            and fallback_relative_strength_pullback_extension
            and reward_risk_hard_blocks == ["reward_risk_bajo"]
        )
        top_long_follow_through_entry_score_override = bool(
            deterministic_fallback
            and fallback_top_long_follow_through
            and reward_risk_hard_blocks == ["reward_risk_bajo"]
        )
        reward_risk_override_eligible = (
            high_conviction_reward_risk_override
            or follow_through_reward_risk_override
            or late_constructive_follow_through_reward_risk_override
            or low_score_volume_rebound_entry_score_override
            or relative_strength_pullback_entry_score_override
            or top_long_follow_through_entry_score_override
        )
        if reward_risk_override_eligible:
            entry_score["approved"] = True
            entry_score["hard_blocks"] = []
            entry_score["reasons"] = [
                reason for reason in list(entry_score.get("reasons") or []) if reason != "reward_risk_bajo"
            ]
            entry_score["reward_risk_margin_override"] = {
                "applied": True,
                "selection_rank": selected_rank,
                "reward_risk": round(reward_risk, 4),
                "min_reward_risk": float(settings.entry_score_v2_min_reward_risk),
                "tolerance": reward_risk_margin_tolerance,
                "mode": (
                    "high_conviction"
                    if high_conviction_reward_risk_override
                    else "follow_through_pattern"
                    if follow_through_reward_risk_override
                    else "late_constructive_follow_through"
                    if late_constructive_follow_through_reward_risk_override
                    else "low_score_volume_rebound"
                    if low_score_volume_rebound_entry_score_override
                    else "relative_strength_pullback_extension"
                    if relative_strength_pullback_entry_score_override
                    else "top_long_follow_through"
                ),
            }
        else:
            entry_score["reward_risk_margin_override"] = {
                "applied": False,
                "selection_rank": selected_rank,
                "reward_risk": round(reward_risk, 4) if reward_risk is not None else None,
                "min_reward_risk": float(settings.entry_score_v2_min_reward_risk),
                "tolerance": reward_risk_margin_tolerance,
                "mode": None,
            }
        checks["entry_score_v2"] = entry_score
        if not entry_score["approved"] and not entry_score["micro_experiment"]:
            return False, f"entry_score_v2 bajo ({entry_score['score']:.2f}): {', '.join(entry_score['reasons'])}", checks
    if (
        rsi is not None
        and rsi < settings.entry_quality_weak_rsi_max
        and volume_z is not None
        and volume_z < settings.entry_quality_weak_volume_max
        and not event_momentum_long
        and not range_expansion_breakout_long
        and not orderly_breakout_long
        and not momentum_shakeout_hold_long
    ):
        return False, "RSI flojo con volumen relativo debil", checks
    prior_edge_3d = _float(learning_prior.get("expected_edge_3d"))
    prior_sample_3d = int(learning_prior.get("sample_size_3d") or 0)
    prior_confidence = _float(learning_prior.get("confidence_weight_3d")) or 0.0
    prior_avg_abs_error = _float(prior_accuracy.get("avg_abs_error"))
    prior_accuracy_sample = int(prior_accuracy.get("matured") or 0)
    if prior_edge_3d is not None and prior_sample_3d >= 6 and prior_confidence >= 0.5:
        if (
            prior_edge_3d <= -0.02
            and not event_momentum_long
            and not range_expansion_breakout_long
            and not orderly_breakout_long
            and not momentum_shakeout_hold_long
            and not momentum_confirmation_long
        ):
            return False, f"setup prior reciente desfavorable ({prior_edge_3d:.2%})", checks
        if (
            prior_edge_3d < 0
            and score < settings.entry_quality_min_score + 2
            and not confirmed_patterns
            and not low_score_volume_rebound_override
            and not fallback_leader_pullback_extension
        ):
            return False, "setup prior reciente debil sin confirmacion suficiente", checks
    if (
        prior_avg_abs_error is not None
        and prior_accuracy_sample >= settings.entry_quality_prior_error_min_samples
        and prior_avg_abs_error >= settings.entry_quality_max_prior_avg_abs_error
        and (prior_edge_3d is None or prior_edge_3d < 0.02)
        and not event_momentum_long
        and not range_expansion_breakout_long
        and not orderly_breakout_long
        and not momentum_shakeout_hold_long
        and not momentum_confirmation_long
        and not fallback_weak_volume_momentum_extension
        and not prior_error_volume_confirmation_override
        and not low_score_volume_rebound_override
        and not fallback_leader_pullback_extension
    ):
        return False, "perfil reciente sobreestima el edge con demasiada frecuencia", checks

    if close and sma20:
        sma20_distance = (close - sma20) / sma20
        checks["sma20_distance"] = round(sma20_distance, 4)
        if sma20_distance > 0.35 or (rsi is not None and rsi > 90.0):
            return False, "entrada extremadamente extendida; requiere retesteo antes de comprar", checks
        if (
            sma20_distance > settings.entry_quality_max_sma20_distance
            and not event_momentum_long
            and not range_expansion_breakout_long
            and not orderly_breakout_long
            and not breakout_continuation_long
            and not momentum_shakeout_hold_long
            and not momentum_confirmation_long
            and not fallback_constructive_extension
            and not fallback_momentum_extension
            and not fallback_weak_volume_momentum_extension
            and not fallback_relative_strength_pullback_extension
            and not fallback_leader_pullback_extension
            and not fallback_top_long_follow_through
        ):
            return (
                False,
                f"precio demasiado extendido sobre SMA20 ({sma20_distance:.2%})",
                checks,
            )
        elif sma20_distance > settings.entry_quality_max_sma20_distance and fallback_momentum_extension:
            extended = False
        elif sma20_distance > settings.entry_quality_max_sma20_distance and fallback_weak_volume_momentum_extension:
            extended = False
        elif sma20_distance > settings.entry_quality_max_sma20_distance and fallback_relative_strength_pullback_extension:
            extended = False
        elif sma20_distance > settings.entry_quality_max_sma20_distance and fallback_leader_pullback_extension:
            extended = False
        elif sma20_distance > settings.entry_quality_max_sma20_distance and fallback_top_long_follow_through:
            extended = False
        elif sma20_distance > settings.entry_quality_max_sma20_distance and event_momentum_long:
            checks["event_momentum_exception"] = {
                "min_score": settings.entry_quality_extreme_rsi_min_score,
                "min_volume_zscore_20": 2.0,
                "min_close_position_in_range": 0.65,
            }
            if score < settings.entry_quality_extreme_rsi_min_score:
                return False, "repricing alcista sin score suficiente para excepcion de extension", checks
            if volume_z is None or volume_z < 2.0:
                return False, "repricing alcista sin volumen anormal suficiente", checks
            if close_position is None or close_position < 0.65:
                return False, "repricing alcista sin cierre firme en el rango diario", checks
            extended = False
        elif sma20_distance > settings.entry_quality_max_sma20_distance and range_expansion_breakout_long:
            checks["range_expansion_breakout_exception"] = {
                **(checks.get("range_expansion_breakout_exception") or {}),
                "max_sma20_distance": settings.entry_quality_range_expansion_max_sma20_distance,
                "max_rsi": settings.entry_quality_range_expansion_max_rsi,
                "min_score": settings.entry_quality_extreme_rsi_min_score,
                "min_volume_zscore_20": 1.0,
                "min_close_position_in_range": 0.75,
            }
            if sma20_distance > settings.entry_quality_range_expansion_max_sma20_distance:
                return False, "range expansion demasiado extendido sobre SMA20", checks
            if rsi is not None and rsi > settings.entry_quality_range_expansion_max_rsi:
                return False, "range expansion con RSI demasiado extremo", checks
            if score < settings.entry_quality_extreme_rsi_min_score:
                return False, "range expansion sin score suficiente", checks
            if volume_z is None or volume_z < 1.0:
                return False, "range expansion sin volumen relativo suficiente", checks
            if close_position is None or close_position < 0.75:
                return False, "range expansion sin cierre fuerte en el rango diario", checks
            extended = False
        elif sma20_distance > settings.entry_quality_max_sma20_distance and orderly_breakout_long:
            checks["orderly_breakout_exception"] = {
                "max_sma20_distance": settings.entry_quality_orderly_breakout_max_sma20_distance,
                "max_rsi": settings.entry_quality_orderly_breakout_max_rsi,
                "min_score": settings.entry_quality_orderly_breakout_min_score,
                "min_volume_zscore_20": settings.entry_quality_orderly_breakout_min_volume_z,
                "min_close_position_in_range": 0.80,
            }
            if sma20_distance > settings.entry_quality_orderly_breakout_max_sma20_distance:
                return False, "orderly breakout demasiado extendido sobre SMA20", checks
            if rsi is not None and rsi > settings.entry_quality_orderly_breakout_max_rsi:
                return False, "orderly breakout con RSI demasiado extremo", checks
            if score < settings.entry_quality_orderly_breakout_min_score:
                return False, "orderly breakout sin score suficiente", checks
            if volume_z is None or volume_z < settings.entry_quality_orderly_breakout_min_volume_z:
                return False, "orderly breakout sin volumen relativo suficiente", checks
            if close_position is None or close_position < 0.80:
                return False, "orderly breakout sin cierre muy fuerte en el rango diario", checks
            extended = False
        elif sma20_distance > settings.entry_quality_max_sma20_distance and breakout_continuation_long:
            checks["breakout_continuation_exception"] = {
                "max_sma20_distance": settings.entry_quality_breakout_continuation_max_sma20_distance,
                "max_rsi": settings.entry_quality_breakout_continuation_max_rsi,
                "min_score": settings.entry_quality_breakout_continuation_min_score,
                "min_volume_zscore_20": settings.entry_quality_breakout_continuation_min_volume_z,
                "min_relative_return_20d": settings.entry_quality_breakout_continuation_min_relative_return_20d,
                "min_close_position_in_range": 0.90,
                "confirmed_bullish_patterns": len(confirmed_patterns),
            }
            if sma20_distance > settings.entry_quality_breakout_continuation_max_sma20_distance:
                return False, "breakout continuation demasiado extendido sobre SMA20", checks
            if rsi is not None and rsi > settings.entry_quality_breakout_continuation_max_rsi:
                return False, "breakout continuation con RSI demasiado extremo", checks
            if score < settings.entry_quality_breakout_continuation_min_score:
                return False, "breakout continuation sin score suficiente", checks
            if volume_z is None or volume_z < settings.entry_quality_breakout_continuation_min_volume_z:
                return False, "breakout continuation sin volumen relativo suficiente", checks
            if relative_return_20d is None or relative_return_20d < settings.entry_quality_breakout_continuation_min_relative_return_20d:
                return False, "breakout continuation sin fuerza relativa suficiente", checks
            if close_position is None or close_position < 0.90:
                return False, "breakout continuation sin cierre excepcionalmente fuerte en el rango diario", checks
            if len(confirmed_patterns) < 2:
                return False, "breakout continuation sin confirmacion estructural suficiente", checks
            if breakout_failure_risk:
                return False, "breakout continuation con riesgo de fallo de ruptura", checks
            extended = False
        elif sma20_distance > settings.entry_quality_max_sma20_distance and momentum_shakeout_hold_long:
            checks["momentum_shakeout_exception"] = {
                "max_sma20_distance": 0.20,
                "min_score": settings.entry_quality_extreme_rsi_min_score,
                "min_volume_zscore_20": 1.5,
                "min_close_position_in_range": 0.70,
            }
            if sma20_distance > 0.20:
                return False, "shakeout alcista demasiado extendido sobre SMA20", checks
            if score < settings.entry_quality_extreme_rsi_min_score:
                return False, "shakeout alcista sin score suficiente", checks
            if volume_z is None or volume_z < 1.5:
                return False, "shakeout alcista sin volumen suficiente", checks
            if close_position is None or close_position < 0.70:
                return False, "shakeout alcista sin cierre fuerte en el rango diario", checks
            extended = False
        elif sma20_distance > settings.entry_quality_max_sma20_distance and momentum_confirmation_long:
            checks["momentum_confirmation_exception"] = {
                "max_sma20_distance": settings.entry_quality_momentum_confirmation_max_sma20_distance,
                "max_rsi": settings.entry_quality_momentum_confirmation_max_rsi,
                "min_score": settings.entry_quality_momentum_confirmation_min_score,
                "min_volume_zscore_20": settings.entry_quality_momentum_confirmation_min_volume_z,
                "min_return_20d": settings.entry_quality_momentum_confirmation_min_return_20d,
                "min_close_position_in_range": 0.75,
                "confirmed_bullish_patterns": len(confirmed_patterns),
            }
            if sma20_distance > settings.entry_quality_momentum_confirmation_max_sma20_distance:
                return False, "momentum confirmado demasiado extendido sobre SMA20", checks
            if rsi is not None and rsi > settings.entry_quality_momentum_confirmation_max_rsi:
                return False, "momentum confirmado con RSI demasiado extremo", checks
            if score < settings.entry_quality_momentum_confirmation_min_score:
                return False, "momentum confirmado sin score suficiente", checks
            extended = False
        else:
            extended = (
                sma20_distance > settings.entry_quality_extended_sma20_distance
                or (rsi is not None and rsi > settings.entry_quality_max_rsi)
            )
        if extended:
            checks["extended_entry_filter"] = {
                "sma20_distance_threshold": settings.entry_quality_extended_sma20_distance,
                "min_relative_return_20d": settings.entry_quality_extended_min_relative_return,
                "min_volume_zscore_20": settings.entry_quality_extended_min_volume_z,
            }
            follow_through_missing_relative_strength = False
            if relative_return_20d is None:
                confirmed_breakout_exception = bool(
                    (range_expansion_breakout_long or orderly_breakout_long)
                    and score >= settings.entry_quality_extreme_rsi_min_score
                    and volume_z is not None
                    and volume_z >= 1.0
                    and close_position is not None
                    and close_position >= 0.80
                    and rsi is not None
                    and rsi <= settings.entry_quality_range_expansion_max_rsi
                    and confirmed_patterns
                )
                breakout_continuation_exception = bool(
                    breakout_continuation_long
                    and score >= settings.entry_quality_breakout_continuation_min_score
                    and volume_z is not None
                    and volume_z >= settings.entry_quality_breakout_continuation_min_volume_z
                    and close_position is not None
                    and close_position >= 0.90
                    and rsi is not None
                    and rsi <= settings.entry_quality_breakout_continuation_max_rsi
                    and sma20_distance <= settings.entry_quality_breakout_continuation_max_sma20_distance
                    and return_20d is not None
                    and return_20d >= settings.entry_quality_breakout_continuation_min_relative_return_20d
                    and len(confirmed_patterns) >= 2
                    and not breakout_failure_risk
                )
                confirmed_momentum_exception = bool(
                    not (event_momentum_long or range_expansion_breakout_long or orderly_breakout_long)
                    and score >= settings.entry_quality_momentum_confirmation_min_score
                    and return_20d is not None
                    and return_20d >= settings.entry_quality_momentum_confirmation_min_return_20d
                    and volume_z is not None
                    and volume_z >= settings.entry_quality_momentum_confirmation_min_volume_z
                    and rsi is not None
                    and rsi <= settings.entry_quality_momentum_confirmation_max_rsi
                    and sma20_distance <= settings.entry_quality_momentum_confirmation_max_sma20_distance
                    and confirmed_patterns
                )
                follow_through_exception = bool(
                    deterministic_fallback
                    and _missing_relative_strength_follow_through_exception(
                        settings,
                        candidate,
                        score=score,
                        return_20d=return_20d,
                        rsi=rsi,
                        sma20_distance=sma20_distance,
                        confirmed_patterns=len(confirmed_patterns),
                    )
                )
                follow_through_missing_relative_strength = follow_through_exception or fallback_top_long_follow_through
                checks["relative_strength_missing_exception"] = {
                    "allowed": (
                        confirmed_breakout_exception
                        or breakout_continuation_exception
                        or confirmed_momentum_exception
                        or follow_through_exception
                        or fallback_constructive_extension
                        or fallback_top_long_follow_through
                    ),
                    "reason": (
                        "confirmed_breakout_with_volume_and_strong_close"
                        if confirmed_breakout_exception
                        else "breakout_continuation_with_exceptional_close"
                        if breakout_continuation_exception
                        else "confirmed_momentum_with_volume_and_pattern"
                        if confirmed_momentum_exception
                        else "follow_through_alignment_without_relative_strength"
                        if follow_through_exception
                        else "constructive_extension_fallback_exception"
                        if fallback_constructive_extension
                        else "top_long_follow_through"
                        if fallback_top_long_follow_through
                        else "missing_relative_strength_without_exception"
                    ),
                    "min_score": settings.entry_quality_extreme_rsi_min_score,
                    "min_volume_zscore_20": 1.0,
                    "min_close_position_in_range": 0.80,
                    "max_rsi": settings.entry_quality_range_expansion_max_rsi,
                    "confirmed_bullish_patterns": len(confirmed_patterns),
                    "confirmed_momentum_exception": {
                        "allowed": confirmed_momentum_exception,
                        "min_score": settings.entry_quality_momentum_confirmation_min_score,
                        "min_return_20d": settings.entry_quality_momentum_confirmation_min_return_20d,
                        "min_volume_zscore_20": settings.entry_quality_momentum_confirmation_min_volume_z,
                        "max_rsi": settings.entry_quality_momentum_confirmation_max_rsi,
                        "max_sma20_distance": settings.entry_quality_momentum_confirmation_max_sma20_distance,
                    },
                    "follow_through_exception": {
                        "allowed": follow_through_exception,
                        "max_selection_rank": settings.entry_quality_missing_relative_strength_follow_through_max_selection_rank,
                        "min_score": settings.entry_quality_missing_relative_strength_follow_through_min_score,
                        "min_return_20d": settings.entry_quality_missing_relative_strength_follow_through_min_return_20d,
                        "min_rsi": settings.entry_quality_missing_relative_strength_follow_through_min_rsi,
                        "max_sma20_distance": settings.entry_quality_missing_relative_strength_follow_through_max_sma20_distance,
                        "min_confirmed_patterns": settings.entry_quality_missing_relative_strength_follow_through_min_confirmed_patterns,
                    },
                    "breakout_continuation_exception": {
                        "allowed": breakout_continuation_exception,
                        "min_score": settings.entry_quality_breakout_continuation_min_score,
                        "min_volume_zscore_20": settings.entry_quality_breakout_continuation_min_volume_z,
                        "min_return_20d": settings.entry_quality_breakout_continuation_min_relative_return_20d,
                        "max_rsi": settings.entry_quality_breakout_continuation_max_rsi,
                        "max_sma20_distance": settings.entry_quality_breakout_continuation_max_sma20_distance,
                    },
                }
                if not (
                    confirmed_breakout_exception
                    or breakout_continuation_exception
                    or confirmed_momentum_exception
                    or follow_through_exception
                    or fallback_constructive_extension
                    or fallback_top_long_follow_through
                ):
                    return False, "entrada extendida sin fuerza relativa 20d disponible", checks
            if (
                relative_return_20d is not None
                and relative_return_20d < settings.entry_quality_extended_min_relative_return
            ):
                return (
                    False,
                    "entrada extendida sin fuerza relativa suficiente "
                    f"({relative_return_20d:.2%})",
                    checks,
                )
            if volume_z is None:
                return False, "entrada extendida sin volumen relativo disponible", checks
            if (
                volume_z < settings.entry_quality_extended_min_volume_z
                and not follow_through_missing_relative_strength
            ):
                return (
                    False,
                    f"entrada extendida sin volumen de confirmacion ({volume_z:.2f})",
                    checks,
                )
            if not confirmed_patterns:
                return False, "entrada extendida sin patron alcista confirmado", checks

    if rsi is not None and rsi >= settings.entry_quality_confirmed_pattern_rsi and not confirmed_patterns:
        return False, "RSI alto sin figura alcista confirmada", checks
    if rsi is not None and rsi > settings.entry_quality_max_rsi:
        if score < settings.entry_quality_extreme_rsi_min_score:
            return False, f"RSI extremo {rsi:.2f} sin score excepcional", checks
        if not confirmed_patterns:
            return False, f"RSI extremo {rsi:.2f} sin patron confirmado", checks
        if (
            volume_z is not None
            and volume_z < 0
            and not fallback_relative_strength_pullback_extension
            and not fallback_top_long_follow_through
        ):
            return False, f"RSI extremo {rsi:.2f} sin volumen de confirmacion", checks

    return True, "entry-quality aprobado", checks


def filter_entry_quality(
    settings: Settings,
    recommendations: list[TradeRecommendation],
    technical_context: dict[str, Any] | None,
    sentiment_context: dict[str, Any] | None = None,
) -> tuple[list[TradeRecommendation], list[dict[str, Any]]]:
    kept = []
    decisions = []
    for recommendation in recommendations:
        approved, reason, checks = validate_entry_quality(
            settings,
            recommendation,
            technical_context,
            sentiment_context,
        )
        decisions.append(
            {
                "symbol": recommendation.symbol,
                "action": recommendation.action,
                "approved": approved,
                "reason": reason,
                "checks": checks,
            }
        )
        entry_score = checks.get("entry_score_v2") or {}
        micro_experiment = bool(entry_score.get("micro_experiment"))
        soft_override_reasons = list(recommendation.soft_override_reasons or [])
        if _backtest_soft_override_eligible_from_entry_checks(settings, checks):
            soft_override_reasons.append("backtest_soft_override_eligible")
        if approved or micro_experiment:
            kept.append(
                replace(
                    recommendation,
                    aggressiveness_profile=settings.trade_aggressiveness_profile,
                    micro_experiment=bool(recommendation.micro_experiment or micro_experiment),
                    size_multiplier=(
                        min(float(recommendation.size_multiplier or 1.0), float(settings.micro_experiment_size_multiplier))
                        if micro_experiment
                        else float(recommendation.size_multiplier or 1.0)
                    ),
                    soft_override_reasons=[
                        *soft_override_reasons,
                        *(["entry_score_v2_micro_experiment"] if micro_experiment else []),
                    ],
                )
            )
    return kept, decisions


def _backtest_soft_override_eligible_from_entry_checks(settings: Settings, checks: dict[str, Any]) -> bool:
    if not settings.backtest_gate_paper_soft_override_enabled:
        return False
    if settings.trading_mode != "paper":
        return False
    if settings.trade_aggressiveness_profile not in {"opportunistic", "aggressive"}:
        return False
    entry_score = checks.get("entry_score_v2") or {}
    reward_risk = _float(entry_score.get("reward_risk"))
    sentiment_score = _float(checks.get("sentiment_score"))
    sentiment_confidence = _float(checks.get("sentiment_confidence")) or 0.0
    confirmed_negative_sentiment = (
        sentiment_score is not None
        and sentiment_confidence >= 0.5
        and sentiment_score <= -0.5
    )
    return bool(
        (_float(checks.get("score")) or 0.0) >= 16
        and (_float(checks.get("volume_zscore_20")) or 0.0) >= 1.25
        and int(checks.get("confirmed_bullish_patterns") or 0) >= 1
        and reward_risk is not None
        and reward_risk >= 1.5
        and (_float(checks.get("close_position_in_range")) or 0.0) >= 0.80
        and (_float(checks.get("sma20_distance")) is None or (_float(checks.get("sma20_distance")) or 0.0) <= 0.26)
        and (_float(checks.get("rsi_14")) is None or (_float(checks.get("rsi_14")) or 0.0) <= 88.0)
        and not confirmed_negative_sentiment
    )


def _recommendation_from_dict(item: dict[str, Any]) -> TradeRecommendation | None:
    symbol = str(item.get("symbol", "")).upper().strip()
    action = str(item.get("action", "hold")).lower().strip()
    if not symbol or action not in VALID_ACTIONS:
        return None

    confidence = _float(item.get("confidence")) or 0.0
    return TradeRecommendation(
        symbol=symbol,
        action=action,
        confidence=max(0.0, min(1.0, confidence)),
        reason=str(item.get("reason", ""))[:2000],
        entry_price=_float(item.get("entry_price")),
        stop_loss=_float(item.get("stop_loss")),
        take_profit=_float(item.get("take_profit")),
        target_exposure_pct=_exposure_fraction(item.get("target_exposure_pct")),
        time_horizon=str(item.get("time_horizon", "")) or None,
        invalidation=str(item.get("invalidation", "")) or None,
        aggressiveness_profile=str(item.get("aggressiveness_profile") or "") or None,
        micro_experiment=bool(item.get("micro_experiment")),
        size_multiplier=float(item.get("size_multiplier") or 1.0),
        backtest_soft_override=bool(item.get("backtest_soft_override")),
        soft_override_reasons=[str(value) for value in list(item.get("soft_override_reasons") or [])],
    )


def request_trade_recommendations(
    settings: Settings,
    portfolio: PortfolioSnapshot,
    technical_context: dict[str, Any],
    sentiment_context: dict[str, Any],
    rebalance_context: dict[str, Any] | None = None,
    market_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ask the configured LLM for structured trade recommendations."""

    daily_learning_digest = load_daily_learning_context(settings.data_dir)
    operational_response_context = load_operational_response_context(settings.data_dir)
    annotated_technical_context = _annotate_technical_context_with_learning(
        technical_context,
        daily_learning_digest,
        operational_response_context,
        settings.data_dir,
        settings=settings,
    )
    research_context = _build_research_context(
        settings,
        annotated_technical_context,
        sentiment_context,
        market_state,
    )
    decision_learning_context = _build_decision_learning_context(
        daily_learning_digest,
        operational_response_context,
    )
    recommendation_limit = _effective_trade_recommendation_limit(settings, annotated_technical_context)
    prompt = _llm_prompt_payload(
        settings,
        portfolio,
        annotated_technical_context,
        sentiment_context,
        rebalance_context,
        daily_learning_digest,
        decision_learning_context,
        operational_response_context,
        market_state,
        research_context,
        compact=True,
    )
    decision_max_tokens = max(settings.llm_max_tokens or 0, 3000)
    system_prompt = (
        "Eres un gestor de cartera experto. Usa solo los datos recibidos. "
        "No inventes precios ni posiciones. Devuelve solo JSON valido con "
        "la clave recommendations, una lista de objetos con: symbol, action "
        "(buy|sell|hold|reduce|exit), confidence 0-1, reason, entry_price, "
        "stop_loss, take_profit, target_exposure_pct como fraccion decimal "
        "(0.03 significa 3%), time_horizon, invalidation. "
        "Debes comparar posiciones actuales contra candidatos nuevos usando "
        "score tecnico, fuerza relativa, sentimiento, riesgo, drawdown, "
        "beneficio/perdida actual y coste estimado de rotacion. "
        "Usa research_evidence como capa de evidencia externa: si basas una compra en noticias, macro o tesis, "
        "menciona los evidence_ids relevantes dentro de la reason. "
        "Usa decision_learning_context y los campos rank_priority_score, effective_setup_edge_3d, "
        "setup_edge_3d, setup_win_rate_3d y operational_penalty para priorizar setups con evidencia reciente. "
        "Prioriza technical_candidates.selected_candidates; technical_candidates.top_longs es contexto secundario. "
        "Usa selection_score, selection_reason, setup_sample_size_3d y expected_edge_3d para comparar entradas. "
        "Trata market_state como contexto obligatorio: si data_quality.status es INSUFFICIENT, no propongas buys; "
        "si market_regime es bearish o data_quality.status es PARTIAL, solo propone buys excepcionales y explicalos. "
        "No recomiendes comprar candidatos con blocked_auto_buy=true; tratalos como shadow/watch. "
        "Si learning_prior.matched_on es 'none' o sample_size_3d es 0, trata la ausencia de historial "
        "como neutral, no como edge negativo implicito; en ese caso decide por tecnico, riesgo y contexto actual. "
        "Si effective_setup_edge_3d es negativo o existe una respuesta operativa activa de "
        "deprioritize_setup_before_llm para ese setup, evita comprarlo salvo evidencia excepcional "
        "y debes explicarlo de forma concreta. "
        "Respeta las reglas activas de operational_learning. Usa las reglas shadow "
        "solo como contexto: no son obligatorias, pero debes comentar si una decision "
        "las contradice. "
        "Regla de salida: por defecto una posicion abierta se mantiene hasta "
        "tocar stop_loss o take_profit. No recomiendes sell/exit solo porque "
        "exista otro candidato con mejor score. Solo puedes recomendar sell/exit "
        "de forma excepcional si hay noticia negativa material, riesgo extraordinario "
        "o deterioro cuantificable severo. El sistema bloqueara salidas LLM ordinarias "
        "si no hay stop/take tocado, confianza muy alta y evidencia objetiva. "
        "No recomiendes ampliar una posicion existente salvo que allow_position_adds=true. "
        "Respeta max_daily_buy_orders y max_orders_per_cycle: pocas entradas de alta calidad. "
        "Si allow_short_selling=false, ignora setups short como candidatos operables y no gastes recomendaciones en ellos. "
        "Si risk_limits.prefer_full_long_only_capacity=true y hay varios largos claros en selected_candidates, "
        "prioriza hasta llenar esa capacidad efectiva con compras distintas antes de devolver hold por exceso de conservadurismo. "
        "No compres solo porque haya cash. "
        "Si falta evidencia suficiente, action debe ser hold. "
    )
    # Prompt versionado (T2.1): si hay una version ACTIVE en prompt_versions se
    # usa; si no, cae al texto por defecto de arriba. El cierre dinamico
    # (limite de recomendaciones) se aplica SIEMPRE, sobre el prompt elegido.
    from ..prompt_store import get_prompt

    system_prompt = get_prompt(settings, "trade_decision_system", system_prompt)
    system_prompt = (
        system_prompt
        + f" Devuelve como maximo {recommendation_limit} recomendaciones. Usa razones breves. "
        + "No uses markdown. Cierra siempre el JSON."
    )

    def _create_completion(payload: dict[str, Any], max_tokens: int):
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=True)},
        ]
        response, endpoint, _attempts = chat_for_role(
            "decision",
            settings=settings,
            messages=messages,
            temperature=settings.llm_temperature,
            max_tokens=max_tokens,
        )
        return response, messages, endpoint

    try:
        response, messages, _endpoint = _create_completion(prompt, decision_max_tokens)
        record_llm_response(settings, "trade_decision", response, prompt=messages, role="decision")
    except Exception as exc:
        message = str(exc).lower()
        if "timeout" not in message and "timed out" not in message and "read operation" not in message:
            raise
        fallback_prompt = _llm_prompt_payload(
            settings,
            portfolio,
            annotated_technical_context,
            sentiment_context,
            rebalance_context,
            daily_learning_digest,
            decision_learning_context,
            operational_response_context,
            market_state,
            research_context,
            compact=True,
        )
        fallback_prompt["decision_learning_context"] = {
            "guidance": list(decision_learning_context.get("guidance", []) or [])[:4],
            "top_setups_3d": list(decision_learning_context.get("top_setups_3d", []) or [])[:3],
            "weak_setups_3d": list(decision_learning_context.get("weak_setups_3d", []) or [])[:3],
            "active_operational_responses": list(decision_learning_context.get("active_operational_responses", []) or [])[:4],
        }
        response, messages, _endpoint = _create_completion(fallback_prompt, min(decision_max_tokens, 1800))
        record_llm_response(settings, "trade_decision_fallback", response, prompt=messages, role="decision")
        prompt = fallback_prompt
    content = response.choices[0].message.content or "{}"
    parsed = _extract_json_object(content)
    recommendations = [
        recommendation
        for item in parsed.get("recommendations", [])
        if isinstance(item, dict)
        for recommendation in [_recommendation_from_dict(item)]
        if recommendation is not None
    ][:recommendation_limit]
    return {
        "raw_response_preview": content[:2000],
        "recommendations": recommendations,
        "prompt_context": prompt,
    }


def deterministic_trade_fallback_recommendations(
    settings: Settings,
    portfolio: PortfolioSnapshot,
    technical_context: dict[str, Any],
    *,
    limit: int | None = None,
    market_state: dict[str, Any] | None = None,
) -> list[TradeRecommendation]:
    """Conservative fallback for paper trading when the LLM decision layer is unavailable."""

    if _fallback_market_state_block_reason(market_state):
        return []

    existing_symbols = {
        position.symbol.upper()
        for position in portfolio.positions
        if str(position.side or "long").lower() == "long" and float(position.qty or 0.0) > 0
    }
    open_order_symbols = {order.symbol.upper() for order in portfolio.open_orders}
    recommendation_limit = max(1, int(limit or _effective_trade_recommendation_limit(settings, technical_context)))
    eligible: list[dict[str, Any]] = []
    for candidate in list((technical_context or {}).get("selected_candidates", []) or []):
        if not isinstance(candidate, dict):
            continue
        symbol = str(candidate.get("symbol") or "").upper().strip()
        if not symbol or symbol in open_order_symbols:
            continue
        if symbol in existing_symbols and not settings.allow_position_adds:
            continue
        if str(candidate.get("direction") or "").lower() != "long":
            continue
        if str(candidate.get("setup_quality") or "").lower() != "strong":
            continue
        if bool(candidate.get("blocked_auto_buy")):
            continue
        if not _valid_risk_plan(candidate):
            continue
        technical_state = candidate.get("technical_state", {}) or {}
        score = _float(candidate.get("score")) or 0.0
        close = _float(technical_state.get("close"))
        sma20 = _float(technical_state.get("sma_20"))
        if close and sma20:
            sma20_distance = (close - sma20) / sma20
            has_extension_exception = any(
                bool(technical_state.get(flag))
                for flag in (
                    "event_momentum_long",
                    "range_expansion_breakout_long",
                    "orderly_breakout_long",
                    "breakout_continuation_long",
                    "momentum_shakeout_hold_long",
                    "momentum_confirmation_long",
                )
            )
            has_extension_exception = has_extension_exception or _fallback_constructive_extension_exception(
                settings,
                candidate,
                score=score,
                volume_z=_float(technical_state.get("volume_zscore_20")),
            )
            has_extension_exception = has_extension_exception or _fallback_momentum_extension_exception(
                settings,
                candidate,
                score=score,
                volume_z=_float(technical_state.get("volume_zscore_20")),
            )
            has_extension_exception = has_extension_exception or _fallback_weak_volume_momentum_extension_exception(
                settings,
                candidate,
                score=score,
                volume_z=_float(technical_state.get("volume_zscore_20")),
            )
            has_extension_exception = has_extension_exception or _fallback_relative_strength_pullback_extension_exception(
                settings,
                candidate,
                score=score,
                return_20d=_float(technical_state.get("return_20d")),
                relative_return_20d=_float(candidate.get("relative_return_20d")),
                rsi=_float(technical_state.get("rsi_14")),
                sma20_distance=sma20_distance,
                volume_z=_float(technical_state.get("volume_zscore_20")),
            )
            has_extension_exception = has_extension_exception or _fallback_leader_pullback_extension_exception(
                settings,
                candidate,
                score=score,
                return_20d=_float(technical_state.get("return_20d")),
                rsi=_float(technical_state.get("rsi_14")),
                sma20_distance=sma20_distance,
                volume_z=_float(technical_state.get("volume_zscore_20")),
            )
            has_extension_exception = has_extension_exception or _fallback_top_long_follow_through_exception(
                settings,
                candidate,
                score=score,
                return_20d=_float(technical_state.get("return_20d")),
                rsi=_float(technical_state.get("rsi_14")),
                volume_z=_float(technical_state.get("volume_zscore_20")),
            )
            if sma20_distance > settings.entry_quality_max_sma20_distance and not has_extension_exception:
                continue
        fallback_min_score = max(
            float(settings.entry_quality_min_score),
            13.0 if _fallback_constructive_extension_exception(settings, candidate, score=score) else 14.0,
        )
        if _low_score_volume_rebound_override_exception(
            settings,
            candidate,
            score=score,
            return_20d=_float(technical_state.get("return_20d")),
            rsi=_float(technical_state.get("rsi_14")),
            volume_z=_float(technical_state.get("volume_zscore_20")),
        ):
            fallback_min_score = min(
                fallback_min_score,
                float(settings.entry_quality_low_score_volume_rebound_min_score),
            )
        if score < fallback_min_score:
            continue
        risk = candidate.get("risk_plan", {}) or {}
        candidate_recommendation = TradeRecommendation(
            symbol=symbol,
            action="buy",
            confidence=float(settings.min_llm_confidence_to_trade),
            reason="Fallback determinista: prevalidacion tecnica.",
            entry_price=_float(risk.get("entry_price")),
            stop_loss=_float(risk.get("stop_loss")),
            take_profit=_float(risk.get("take_profit")),
            target_exposure_pct=float(settings.max_position_exposure),
            source="deterministic_fallback",
        )
        entry_approved, _entry_reason, _entry_checks = validate_entry_quality(
            settings,
            candidate_recommendation,
            technical_context,
            {"results": []},
        )
        if not entry_approved:
            continue
        eligible.append(
            {
                **candidate,
                "symbol": symbol,
                "entry_price": candidate_recommendation.entry_price,
                "stop_loss": candidate_recommendation.stop_loss,
                "take_profit": candidate_recommendation.take_profit,
            }
        )

    eligible = sorted(
        eligible,
        key=lambda item: (
            float(item.get("selection_score") or item.get("rank_priority_score") or -999.0),
            float(item.get("score") or 0.0),
        ),
        reverse=True,
    )
    # T2b (opcional, flag por defecto OFF): reordenar por score de oportunidad
    # determinista (fuerza relativa / momentum / tendencia) para que el fallback
    # elija primero el mejor lider y no un nombre arbitrario. No cambia
    # elegibilidad ni riesgo; solo el orden. Envuelto para no romper el fallback.
    if getattr(settings, "opportunity_ranker_fallback_enabled", False):
        try:
            from agente_bolsa.tools.opportunity_ranker import prioritize_candidates

            _bench_ret = 0.0
            if isinstance(market_state, dict):
                _bench_ret = float(
                    (market_state.get("relative_strength") or {}).get("benchmark_return_20d")
                    or 0.0
                )
            eligible = prioritize_candidates(eligible, benchmark_return_20d=_bench_ret)
        except Exception as exc:  # noqa: BLE001 - reordenar nunca debe romper el fallback
            log_swallow(LOGGER, "priorizar fallback con opportunity ranker", exc)
    recommendations: list[TradeRecommendation] = []
    for item in eligible[:recommendation_limit]:
        selection_score = _float(item.get("selection_score"))
        confidence = max(
            float(settings.min_llm_confidence_to_trade),
            min(0.78, 0.66 + max(0.0, selection_score or 0.0)),
        )
        recommendations.append(
            TradeRecommendation(
                symbol=str(item["symbol"]),
                action="buy",
                confidence=round(confidence, 2),
                reason=(
                    "Fallback determinista por fallo del LLM: candidato strong seleccionado "
                    f"rank={item.get('selection_rank')}, score={item.get('score')}, "
                    f"selection_score={item.get('selection_score')}."
                ),
                entry_price=item.get("entry_price"),
                stop_loss=item.get("stop_loss"),
                take_profit=item.get("take_profit"),
                target_exposure_pct=float(settings.max_position_exposure),
                time_horizon="3d",
                invalidation="Stop loss o deterioro tecnico en el siguiente ciclo.",
                source="deterministic_fallback",
                aggressiveness_profile=settings.trade_aggressiveness_profile,
            )
        )
    return recommendations


def augment_recommendations_with_deterministic_fallback(
    settings: Settings,
    portfolio: PortfolioSnapshot,
    technical_context: dict[str, Any],
    recommendations: list[TradeRecommendation],
    *,
    limit: int | None = None,
    market_state: dict[str, Any] | None = None,
) -> tuple[list[TradeRecommendation], dict[str, Any]]:
    recommendation_limit = max(1, int(limit or _effective_trade_recommendation_limit(settings, technical_context)))
    block_reason = _fallback_market_state_block_reason(market_state)
    if block_reason:
        return recommendations, {
            "added": [],
            "replaced_holds": [],
            "fallback_candidates": 0,
            "blocked_reason": block_reason,
        }
    fallback_recommendations = deterministic_trade_fallback_recommendations(
        settings,
        portfolio,
        technical_context,
        limit=recommendation_limit,
        market_state=market_state,
    )
    if not fallback_recommendations:
        return recommendations, {"added": [], "replaced_holds": [], "fallback_candidates": 0}

    by_symbol: dict[str, TradeRecommendation] = {}
    hold_symbols: set[str] = set()
    buy_symbols: set[str] = set()
    non_buy_count = 0
    for recommendation in recommendations:
        symbol = recommendation.symbol.upper()
        by_symbol[symbol] = recommendation
        action = str(recommendation.action).lower()
        if action == "hold":
            hold_symbols.add(symbol)
        if action == "buy":
            buy_symbols.add(symbol)
        else:
            non_buy_count += 1

    current_buy_count = len(buy_symbols)
    remaining_capacity = max(0, recommendation_limit - current_buy_count)
    added: list[str] = []
    replaced_holds: list[str] = []
    merged = list(recommendations)

    for fallback in fallback_recommendations:
        symbol = fallback.symbol.upper()
        if symbol in buy_symbols:
            continue
        if symbol in hold_symbols:
            merged = [item for item in merged if item.symbol.upper() != symbol]
            merged.append(
                replace(
                    fallback,
                    reason=f"{fallback.reason} Override conservador sobre hold del LLM.",
                    source="deterministic_hold_override",
                )
            )
            buy_symbols.add(symbol)
            added.append(symbol)
            replaced_holds.append(symbol)
            remaining_capacity = max(0, remaining_capacity - 1)
            continue
        if remaining_capacity <= 0:
            continue
        merged.append(
            replace(
                fallback,
                reason=f"{fallback.reason} Completa capacidad buy no usada por el LLM.",
                source="deterministic_capacity_fill",
            )
        )
        buy_symbols.add(symbol)
        added.append(symbol)
        remaining_capacity -= 1

    return merged, {
        "added": added,
        "replaced_holds": replaced_holds,
        "fallback_candidates": len(fallback_recommendations),
        "original_recommendations": len(recommendations),
        "merged_recommendations": len(merged),
        "non_buy_count": non_buy_count,
        "recommendation_limit": recommendation_limit,
    }


def build_buy_order_plans(
    settings: Settings,
    portfolio: PortfolioSnapshot,
    recommendations: list[TradeRecommendation],
    *,
    dry_run: bool = True,
    rejected: list[dict[str, Any]] | None = None,
    market_state: dict[str, Any] | None = None,
) -> list[OrderPlan]:
    """Build risk-checked buy plans. Sell/reduce/exit are kept as recommendations for now."""

    plans: list[OrderPlan] = []
    buy_plan_limit = _effective_buy_plan_limit(settings, recommendations)
    risk_manager = RiskManager(settings)
    open_order_symbols = {order.symbol.upper() for order in portfolio.open_orders}
    existing_position_symbols = {
        position.symbol.upper()
        for position in portfolio.positions
        if str(position.side or "long").lower() == "long" and position.qty > 0
    }
    planned_buy_symbols: set[str] = set()
    daily_learning_digest = load_daily_learning_context(settings.data_dir)
    operational_response_context = load_operational_response_context(settings.data_dir)
    operational_block_context = load_operational_block_context(settings.data_dir)
    research_context = load_research_evidence_context(settings.data_dir)
    latest_technical_context = _annotate_technical_context_with_learning(
        load_latest_technical_candidates(settings.data_dir, per_side=50),
        daily_learning_digest,
        operational_response_context,
        settings.data_dir,
        settings=settings,
    )
    portfolio_risk_context = _portfolio_risk_context(settings, portfolio)
    planned_buy_exposure = 0.0
    planned_buy_risk_amount = 0.0
    market_state_block_reason = _fallback_market_state_block_reason(market_state)

    for recommendation in recommendations:
        if len(plans) >= buy_plan_limit:
            if rejected is not None and recommendation.action == "buy":
                rejected.append(
                    {
                        "symbol": recommendation.symbol,
                        "action": recommendation.action,
                        "stage": "cycle_order_limit",
                        "reason": "max_orders_per_cycle_reached",
                        "checks": {
                            "max_orders_per_cycle": settings.max_orders_per_cycle,
                            "effective_max_orders_per_cycle": buy_plan_limit,
                        },
                    }
                )
            break
        if recommendation.action != "buy":
            continue
        if market_state_block_reason:
            if rejected is not None:
                rejected.append(
                    {
                        "symbol": recommendation.symbol,
                        "action": recommendation.action,
                        "stage": "market_state_guard",
                        "reason": market_state_block_reason,
                        "checks": {
                            "market_state_quality": ((market_state or {}).get("data_quality") or {}).get("status"),
                            "data_quality_notes": list(((market_state or {}).get("data_quality") or {}).get("notes") or []),
                            "data_vendor_quality": ((market_state or {}).get("data_quality") or {}).get("data_vendor_quality"),
                        },
                    }
                )
            continue
        research_reason = research_block_reason(research_context, symbol=recommendation.symbol)
        if research_reason:
            if rejected is not None:
                rejected.append(
                    {
                        "symbol": recommendation.symbol,
                        "action": recommendation.action,
                        "stage": "research_guard",
                        "reason": research_reason,
                        "checks": {
                            "research_as_of": research_context.get("as_of"),
                            "research_summary": (research_context.get("summary") or {}),
                        },
                    }
                )
            continue
        if settings.operational_kill_switch_enabled and operational_block_context.get("block_new_buys"):
            if rejected is not None:
                rejected.append(
                    {
                        "symbol": recommendation.symbol,
                        "action": recommendation.action,
                        "stage": "operational_kill_switch",
                        "reason": "critical_operational_alerts_active",
                        "checks": {
                            "kill_switch_active": True,
                            "blocking_alerts": operational_block_context.get("blocking_alerts", []),
                            "reasons": operational_block_context.get("reasons", []),
                        },
                    }
                )
            continue
        if recommendation.confidence < settings.min_llm_confidence_to_trade:
            if rejected is not None:
                rejected.append(
                    {
                        "symbol": recommendation.symbol,
                        "action": recommendation.action,
                        "stage": "llm_confidence",
                        "reason": "below_min_llm_confidence_to_trade",
                        "checks": {
                            "confidence": recommendation.confidence,
                            "min_llm_confidence_to_trade": settings.min_llm_confidence_to_trade,
                        },
                    }
                )
            continue
        if recommendation.symbol in open_order_symbols:
            if rejected is not None:
                rejected.append(
                    {
                        "symbol": recommendation.symbol,
                        "action": recommendation.action,
                        "stage": "open_order_guard",
                        "reason": "symbol_has_open_order",
                        "checks": {"open_order_symbols": sorted(open_order_symbols)},
                    }
                )
            continue
        if recommendation.symbol in existing_position_symbols and not settings.allow_position_adds:
            if rejected is not None:
                rejected.append(
                    {
                        "symbol": recommendation.symbol,
                        "action": recommendation.action,
                        "stage": "position_add_guard",
                        "reason": "position_adds_disabled",
                        "checks": {
                            "allow_position_adds": settings.allow_position_adds,
                            "existing_position_symbols": sorted(existing_position_symbols),
                        },
                    }
                )
            continue
        if recommendation.symbol in planned_buy_symbols:
            if rejected is not None:
                rejected.append(
                    {
                        "symbol": recommendation.symbol,
                        "action": recommendation.action,
                        "stage": "duplicate_symbol_cycle_guard",
                        "reason": "symbol_already_has_buy_plan_in_cycle",
                        "checks": {"planned_buy_symbols": sorted(planned_buy_symbols)},
                    }
                )
            continue

        sizing_adjustment = _sizing_adjustment_for_recommendation(
            recommendation,
            latest_technical_context,
            daily_learning_digest,
            operational_response_context,
        )
        if recommendation.micro_experiment or recommendation.backtest_soft_override:
            micro_multiplier = max(
                0.0,
                min(
                    float(settings.micro_experiment_size_multiplier),
                    float(recommendation.size_multiplier or 1.0),
                    float(sizing_adjustment.get("size_multiplier") or 1.0),
                ),
            )
            sizing_adjustment = {
                **sizing_adjustment,
                "size_multiplier": micro_multiplier,
                "reason": "micro_experiment",
                "micro_experiment": bool(recommendation.micro_experiment),
                "backtest_soft_override": bool(recommendation.backtest_soft_override),
                "soft_override_reasons": list(recommendation.soft_override_reasons or []),
            }
        notional, sizing_checks = recommended_notional(
            settings,
            portfolio,
            recommendation,
            sizing_adjustment=sizing_adjustment,
        )
        if notional <= 0:
            if rejected is not None:
                rejected.append(
                    {
                        "symbol": recommendation.symbol,
                        "action": recommendation.action,
                        "stage": "position_sizing",
                        "reason": sizing_checks.get("reason") or "non_positive_notional",
                        "checks": sizing_checks,
                    }
                )
            continue

        entry = recommendation.entry_price or 0.0
        stop = recommendation.stop_loss
        take = recommendation.take_profit
        proposal = OrderProposal(
            symbol=recommendation.symbol,
            side="buy",
            notional=notional,
            portfolio_equity=portfolio.portfolio_value,
            strategy_name=(
                f"{recommendation.source}_decision"
                if recommendation.source and recommendation.source != "llm"
                else "llm_portfolio_decision"
            ),
            entry_price=entry,
            stop_loss=stop,
            take_profit=take,
            current_portfolio_exposure=portfolio_risk_context["current_portfolio_exposure"],
            pending_portfolio_exposure=portfolio_risk_context["pending_portfolio_exposure"] + planned_buy_exposure,
            existing_open_risk_amount=portfolio_risk_context["existing_open_risk_amount"],
            pending_open_risk_amount=portfolio_risk_context["pending_open_risk_amount"] + planned_buy_risk_amount,
        )
        decision = risk_manager.validate_order(proposal)
        decision.checks["position_sizing"] = sizing_checks
        decision.checks["sizing_adjustment"] = sizing_adjustment
        decision.checks["aggressiveness_profile"] = (
            recommendation.aggressiveness_profile or settings.trade_aggressiveness_profile
        )
        decision.checks["micro_experiment"] = bool(recommendation.micro_experiment)
        decision.checks["backtest_soft_override"] = bool(recommendation.backtest_soft_override)
        decision.checks["soft_override_reasons"] = list(recommendation.soft_override_reasons or [])
        if not decision.approved:
            if rejected is not None:
                rejected.append(
                    {
                        "symbol": recommendation.symbol,
                        "action": recommendation.action,
                        "stage": "risk_manager",
                        "reason": decision.reason,
                        "checks": decision.checks,
                    }
                )
            continue

        qty, execution_notional, execution_checks = _buy_qty_and_notional_for_execution(
            settings,
            notional=notional,
            entry_price=entry,
        )
        if qty is None or execution_notional < settings.min_order_notional:
            if rejected is not None:
                rejected.append(
                    {
                        "symbol": recommendation.symbol,
                        "action": recommendation.action,
                        "stage": "execution_sizing",
                        "reason": "below_min_order_notional_after_execution_sizing"
                        if execution_notional < settings.min_order_notional
                        else "invalid_execution_quantity",
                        "checks": {
                            **execution_checks,
                            "execution_notional": execution_notional,
                            "min_order_notional": settings.min_order_notional,
                        },
                    }
                )
            continue
        decision.checks["execution_sizing"] = execution_checks
        decision.checks["duplicate_symbol_cycle_guard"] = {
            "blocked_additional_same_symbol_buys": True,
            "allow_position_adds": settings.allow_position_adds,
            "blocked_existing_position_add": recommendation.symbol in existing_position_symbols and not settings.allow_position_adds,
        }
        plans.append(
            OrderPlan(
                symbol=recommendation.symbol,
                side="buy",
                notional=execution_notional,
                qty=qty,
                entry_price=entry,
                stop_loss=stop or 0.0,
                take_profit=take or 0.0,
                recommendation=recommendation,
                risk_decision=decision,
                dry_run=dry_run,
                aggressiveness_profile=recommendation.aggressiveness_profile or settings.trade_aggressiveness_profile,
                micro_experiment=bool(recommendation.micro_experiment),
                size_multiplier=float(sizing_checks.get("size_multiplier") or recommendation.size_multiplier or 1.0),
                backtest_soft_override=bool(recommendation.backtest_soft_override),
                soft_override_reasons=list(recommendation.soft_override_reasons or []),
            )
        )
        planned_buy_symbols.add(recommendation.symbol)
        if float(portfolio.portfolio_value or 0.0) > 0:
            planned_buy_exposure += execution_notional / float(portfolio.portfolio_value)
        proposed_risk_amount = decision.checks.get("proposed_trade_risk_amount")
        if isinstance(proposed_risk_amount, (int, float)):
            planned_buy_risk_amount += float(proposed_risk_amount)

    return plans


def _buy_qty_and_notional_for_execution(
    settings: Settings,
    *,
    notional: float,
    entry_price: float,
) -> tuple[float | None, float, dict[str, Any]]:
    if entry_price <= 0:
        return None, 0.0, {"execution_sizing": "invalid_entry_price"}

    if settings.use_bracket_orders:
        qty = math.floor(notional / entry_price)
        adjusted_notional = round(qty * entry_price, 2)
        return (
            float(qty) if qty > 0 else None,
            adjusted_notional,
            {
                "execution_sizing": "whole_share_bracket",
                "calculated_notional": round(notional, 2),
                "adjusted_notional": adjusted_notional,
                "whole_share_qty": qty,
            },
        )

    qty = round(notional / entry_price, 6)
    return (
        qty,
        round(notional, 2),
        {
            "execution_sizing": "fractional_simple",
            "calculated_notional": round(notional, 2),
            "fractional_qty": qty,
        },
    )


def _position_for_symbol(portfolio: PortfolioSnapshot, symbol: str):
    symbol = symbol.upper()
    for position in portfolio.positions:
        if position.symbol.upper() == symbol:
            return position
    return None


def _is_exceptional_llm_exit(
    settings: Settings,
    recommendation: TradeRecommendation,
    position,
) -> tuple[bool, str, dict[str, Any]]:
    reason = f"{recommendation.reason} {recommendation.invalidation or ''}".lower()
    checks = {
        "policy": "prefer_stop_take_exits",
        "action": recommendation.action,
        "confidence": recommendation.confidence,
        "current_price": position.current_price,
        "unrealized_plpc": position.unrealized_plpc,
        "recommendation_stop_loss": recommendation.stop_loss,
        "recommendation_take_profit": recommendation.take_profit,
        "min_exception_confidence": settings.llm_exit_exception_min_confidence,
        "min_exception_drawdown": settings.llm_exit_exception_min_drawdown,
    }
    rotation_terms = (
        "rotacion",
        "rotaci",
        "rotaciÃ³n",
        "rotación",
        "rotation",
        "candidato mejor",
        "superior",
        "liberar capital",
    )
    if any(term in reason for term in rotation_terms):
        checks["blocked_by"] = "ordinary_rotation_or_capital_release"
        return False, "Salida LLM bloqueada: rotacion/liberar capital no es motivo suficiente.", checks

    stop = recommendation.stop_loss
    take = recommendation.take_profit
    if stop is not None and stop > 0 and position.current_price <= stop:
        checks["trigger"] = "recommendation_stop_loss"
        return True, "Salida permitida: stop_loss de la recomendacion ya esta tocado.", checks
    if take is not None and take > 0 and position.current_price >= take:
        checks["trigger"] = "recommendation_take_profit"
        return True, "Salida permitida: take_profit de la recomendacion ya esta tocado.", checks

    if recommendation.confidence < settings.llm_exit_exception_min_confidence:
        checks["blocked_by"] = "low_exception_confidence"
        return (
            False,
            "Salida LLM bloqueada: no alcanza confianza excepcional para saltarse stop/take.",
            checks,
        )

    material_terms = (
        "noticia negativa material",
        "negative material",
        "material negative",
        "fraud",
        "investigation",
        "sec ",
        "regulatory",
        "lawsuit",
        "bankruptcy",
        "halt",
        "guidance cut",
        "profit warning",
        "earnings miss",
        "downgrade",
        "riesgo extraordinario",
        "extraordinary risk",
    )
    if any(term in reason for term in material_terms):
        checks["trigger"] = "material_negative_event"
        return True, "Salida excepcional permitida: evento material negativo.", checks

    deterioration_terms = (
        "stop",
        "bajista",
        "bearish",
        "deterioro",
        "deterioration",
        "soporte perdido",
        "lost support",
        "invalidacion",
        "invalidation",
    )
    severe_drawdown = position.unrealized_plpc <= -abs(settings.llm_exit_exception_min_drawdown)
    checks["severe_drawdown"] = severe_drawdown
    if severe_drawdown and any(term in reason for term in deterioration_terms):
        checks["trigger"] = "severe_drawdown_with_deterioration"
        return True, "Salida excepcional permitida: drawdown severo con deterioro objetivo.", checks

    checks["blocked_by"] = "no_objective_exception"
    return (
        False,
        "Salida LLM bloqueada: esperar stop_loss/take_profit salvo excepcion objetiva.",
        checks,
    )

def build_order_plans(
    settings: Settings,
    portfolio: PortfolioSnapshot,
    recommendations: list[TradeRecommendation],
    *,
    dry_run: bool = True,
    rejected: list[dict[str, Any]] | None = None,
    market_state: dict[str, Any] | None = None,
) -> list[OrderPlan]:
    """Build buy and long-position sell/reduce/exit plans."""

    plans = build_buy_order_plans(
        settings,
        portfolio,
        recommendations,
        dry_run=dry_run,
        rejected=rejected,
        market_state=market_state,
    )
    total_plan_limit = _effective_buy_plan_limit(settings, recommendations)
    open_order_symbols = {order.symbol.upper() for order in portfolio.open_orders}

    for recommendation in recommendations:
        if len(plans) >= total_plan_limit:
            break
        if recommendation.action not in {"sell", "reduce", "exit"}:
            continue
        if recommendation.symbol in open_order_symbols:
            continue
        if recommendation.confidence < settings.min_llm_confidence_to_trade:
            continue
        position = _position_for_symbol(portfolio, recommendation.symbol)
        if position is None or position.qty <= 0:
            continue

        exit_allowed, exit_reason, exit_checks = _is_exceptional_llm_exit(settings, recommendation, position)
        if not exit_allowed:
            continue

        if recommendation.action == "reduce":
            target_exposure = recommendation.target_exposure_pct or 0.0
            target_value = portfolio.portfolio_value * max(0.0, target_exposure)
            sell_value = max(0.0, position.market_value - target_value)
            qty = (
                min(position.qty, sell_value / position.current_price)
                if position.current_price
                else 0
            )
        else:
            qty = position.qty

        if qty <= 0:
            continue

        safe_qty = _floor_qty(qty)
        if safe_qty <= 0:
            continue

        notional = round(safe_qty * position.current_price, 2)
        decision = RiskDecision(
            approved=True,
            reason=f"Venta/reduccion aprobada: {exit_reason}",
            checks={
                "action": recommendation.action,
                "held_qty": position.qty,
                "sell_qty": safe_qty,
                "market_value": position.market_value,
                "notional": notional,
                "allow_short_selling": settings.allow_short_selling,
                "exit_policy": exit_checks,
            },
        )
        plans.append(
            OrderPlan(
                symbol=recommendation.symbol,
                side="sell",
                notional=notional,
                qty=safe_qty,
                entry_price=position.current_price,
                stop_loss=0.0,
                take_profit=0.0,
                recommendation=recommendation,
                risk_decision=decision,
                dry_run=dry_run,
            )
        )

    return plans
