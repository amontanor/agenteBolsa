"""LLM-driven trade recommendations with deterministic risk sizing."""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.llm_usage import record_llm_response
from agente_bolsa.models import OrderPlan, PortfolioSnapshot, RiskDecision, TradeRecommendation
from agente_bolsa.storage import Store
from agente_bolsa.tools.position_sizing import recommended_notional
from agente_bolsa.tools.daily_learning import load_daily_learning_context
from agente_bolsa.tools.operational_health import load_operational_block_context, load_operational_response_context
from agente_bolsa.tools.operational_learning import load_operational_learning_context
from agente_bolsa.tools.post_market_review import load_post_market_learning_context
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
    return _effective_long_only_capacity(settings, len(selected))


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
        return max(base_limit, 5)
    if _can_expand_long_only_capacity(settings) and buy_count >= 4:
        return max(base_limit, 4)
    return base_limit


def _deterministic_selection_limit(settings: Settings) -> int:
    if settings.allow_short_selling:
        return 8
    return max(12, int(settings.news_sentiment_top_n), int(settings.trade_selection_top_n))


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
    }


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
    all_candidates = report.get("all_candidates", []) or []
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
        "top_longs": report.get("top_longs", [])[:per_side],
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
    high_conviction_confirmed_momentum = bool(
        score >= 17.0
        and volume_z >= 1.25
        and confirmed_patterns >= 2
        and not breakout_failure_risk
        and distance_sma20 is not None
        and 0.04 <= distance_sma20 <= 0.20
        and 65.0 <= rsi <= 82.0
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
    volume_component = 0.006 if volume_z >= 1.0 else -0.006 if volume_z < 0 else 0.0
    pattern_component = min(0.010, confirmed_patterns * 0.005)
    continuation_component = 0.012 if orderly_breakout else 0.008 if breakout_continuation else 0.0
    high_conviction_momentum_component = 0.018 if high_conviction_confirmed_momentum else 0.0
    if same_session_intraday_rule == "same_session_intraday_leader":
        same_session_momentum_component = float((settings or Settings()).intraday_same_session_leader_selection_bonus)
    elif same_session_intraday_rule == "same_session_intraday_momentum":
        same_session_momentum_component = float((settings or Settings()).intraday_same_session_selection_bonus)
    else:
        same_session_momentum_component = 0.0
    failure_penalty = 0.020 if breakout_failure_risk else 0.0
    setup_risk_penalty = 0.080 if range_expansion else 0.0
    operational_penalty = _float(learning_prior.get("operational_penalty")) or 0.0

    selection_score = (
        edge
        + score_component
        + relative_strength_component
        + volume_component
        + pattern_component
        + continuation_component
        + high_conviction_momentum_component
        + same_session_momentum_component
        - sample_penalty
        - failure_penalty
        - setup_risk_penalty
        - operational_penalty
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
    if same_session_intraday_rule:
        reasons.append(same_session_intraday_rule)
    if breakout_failure_risk:
        reasons.append("breakout_failure_penalty")
    if range_expansion:
        reasons.append("range_expansion_shadow_only")
    if relative_strength_component > 0:
        reasons.append("relative_strength")

    return {
        "selection_score": round(selection_score, 4),
        "selection_reason": ",".join(reasons) if reasons else "baseline",
        "selection_components": {
            **{key: round(value, 4) if isinstance(value, float) else value for key, value in edge_components.items()},
            "shrunk_edge_3d": round(edge, 4),
            "score_component": round(score_component, 4),
            "relative_strength_component": round(relative_strength_component, 4),
            "volume_component": round(volume_component, 4),
            "pattern_component": round(pattern_component, 4),
            "continuation_component": round(continuation_component, 4),
            "high_conviction_momentum_component": round(high_conviction_momentum_component, 4),
            "same_session_momentum_component": round(same_session_momentum_component, 4),
            "failure_penalty": round(failure_penalty, 4),
            "setup_risk_penalty": round(setup_risk_penalty, 4),
            "operational_penalty": round(operational_penalty, 4),
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
    high_conviction_confirmed_momentum = bool(
        score >= 17.0
        and volume_z >= 1.25
        and confirmed_patterns >= 2
        and not breakout_failure_risk
        and distance_sma20 is not None
        and 0.04 <= distance_sma20 <= 0.20
        and 65.0 <= rsi <= 82.0
    )
    same_session_intraday_rule, same_session_summary = _same_session_intraday_momentum_bonus(
        candidate,
        same_session_context or {},
        settings,
    )
    score_component = min(0.04, max(0.0, score / 1000.0))
    relative_strength_component = min(0.03, max(-0.01, relative_return_20d * 0.25))
    volume_component = 0.01 if volume_z >= 1.0 else -0.01 if volume_z < 0 else 0.0
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
    if same_session_intraday_rule == "same_session_intraday_leader":
        same_session_momentum_component = float((settings or Settings()).intraday_same_session_leader_priority_bonus)
    elif same_session_intraday_rule == "same_session_intraday_momentum":
        same_session_momentum_component = float((settings or Settings()).intraday_same_session_priority_bonus)
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
    if same_session_intraday_rule:
        reasons.append(same_session_intraday_rule)
    if breakout_failure_risk:
        reasons.append("breakout_failure_penalty")
    if relative_strength_component > 0:
        reasons.append("relative_strength")
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
) -> dict[str, Any]:
    base_context = dict(technical_context)
    settings = Settings(DATA_DIR=data_dir) if data_dir is not None else None
    same_session_context = _same_session_intraday_context(data_dir, base_context)
    if not base_context.get("selected_candidates") and isinstance(base_context.get("all_candidates"), list):
        selection_limit = _deterministic_selection_limit(settings) if settings is not None else 8
        selected, metadata = _select_deterministic_candidates(
            base_context.get("all_candidates", []) or [],
            daily_learning_digest,
            operational_response_context,
            limit=selection_limit,
            same_session_context=same_session_context,
            settings=settings,
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
            settings=settings,
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

    if direction != "long":
        return False, f"direccion tecnica no es long ({direction or 'desconocida'})", checks
    if setup_quality != "strong":
        return False, f"setup no es strong ({setup_quality or 'desconocido'})", checks
    if range_expansion_breakout_long:
        checks["shadow_only_setup"] = "range_expansion_breakout"
        return False, "range_expansion_breakout_shadow_only", checks
    if score < settings.entry_quality_min_score:
        return False, f"score {score} < minimo {settings.entry_quality_min_score}", checks
    if return_20d is not None and return_20d <= 0:
        return False, f"momentum 20d no positivo ({return_20d:.2%})", checks
    if relative_return_20d is not None and relative_return_20d <= 0:
        return False, f"fuerza relativa 20d negativa vs benchmark ({relative_return_20d:.2%})", checks
    if macd is not None and macd_signal is not None and macd <= macd_signal:
        return False, "MACD no confirma momentum alcista", checks
    deterministic_fallback = recommendation.source == "deterministic_fallback"
    checks["deterministic_fallback"] = deterministic_fallback
    if (
        settings.news_sentiment_fail_closed_for_buys
        and "sentiment_failed" in sentiment_flags
        and not deterministic_fallback
    ):
        return False, "sentimiento no validado; compra bloqueada por fallo de noticias", checks
    if sentiment_score is not None and sentiment_confidence >= 0.5 and sentiment_score <= -0.5:
        return False, f"sentimiento negativo confirmado ({sentiment_score})", checks
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
        if prior_edge_3d < 0 and score < settings.entry_quality_min_score + 2 and not confirmed_patterns:
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
    ):
        return False, "perfil reciente sobreestima el edge con demasiada frecuencia", checks

    if close and sma20:
        sma20_distance = (close - sma20) / sma20
        checks["sma20_distance"] = round(sma20_distance, 4)
        if (
            sma20_distance > settings.entry_quality_max_sma20_distance
            and not event_momentum_long
            and not range_expansion_breakout_long
            and not orderly_breakout_long
            and not momentum_shakeout_hold_long
            and not momentum_confirmation_long
        ):
            return (
                False,
                f"precio demasiado extendido sobre SMA20 ({sma20_distance:.2%})",
                checks,
            )
        if sma20_distance > settings.entry_quality_max_sma20_distance and event_momentum_long:
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
                checks["relative_strength_missing_exception"] = {
                    "allowed": confirmed_breakout_exception or confirmed_momentum_exception,
                    "reason": (
                        "confirmed_breakout_with_volume_and_strong_close"
                        if confirmed_breakout_exception
                        else "confirmed_momentum_with_volume_and_pattern"
                        if confirmed_momentum_exception
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
                }
                if not (confirmed_breakout_exception or confirmed_momentum_exception):
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
            if volume_z < settings.entry_quality_extended_min_volume_z:
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
        if volume_z is not None and volume_z < 0:
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
        if approved:
            kept.append(recommendation)
    return kept, decisions


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
    )


def request_trade_recommendations(
    settings: Settings,
    portfolio: PortfolioSnapshot,
    technical_context: dict[str, Any],
    sentiment_context: dict[str, Any],
    rebalance_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ask the configured LLM for structured trade recommendations."""

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Instala openai con `pip install -r requirements.txt`.") from exc

    daily_learning_digest = load_daily_learning_context(settings.data_dir)
    operational_response_context = load_operational_response_context(settings.data_dir)
    annotated_technical_context = _annotate_technical_context_with_learning(
        technical_context,
        daily_learning_digest,
        operational_response_context,
        settings.data_dir,
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
        compact=True,
    )
    client = OpenAI(
        api_key=settings.openai_api_key or "local-llama",
        base_url=settings.openai_api_base,
        timeout=settings.llm_timeout_seconds,
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
        "Usa decision_learning_context y los campos rank_priority_score, effective_setup_edge_3d, "
        "setup_edge_3d, setup_win_rate_3d y operational_penalty para priorizar setups con evidencia reciente. "
        "Prioriza technical_candidates.selected_candidates; technical_candidates.top_longs es contexto secundario. "
        "Usa selection_score, selection_reason, setup_sample_size_3d y expected_edge_3d para comparar entradas. "
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
        f"Devuelve como maximo {recommendation_limit} recomendaciones. Usa razones breves. "
        "No uses markdown. Cierra siempre el JSON."
    )

    def _create_completion(payload: dict[str, Any], max_tokens: int):
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=True)},
        ]
        return client.chat.completions.create(
            model=settings.openai_model,
            temperature=settings.llm_temperature,
            max_tokens=max_tokens,
            messages=messages,
        ), messages

    try:
        response, messages = _create_completion(prompt, decision_max_tokens)
        record_llm_response(settings, "trade_decision", response, prompt=messages)
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
            compact=True,
        )
        fallback_prompt["decision_learning_context"] = {
            "guidance": list(decision_learning_context.get("guidance", []) or [])[:4],
            "top_setups_3d": list(decision_learning_context.get("top_setups_3d", []) or [])[:3],
            "weak_setups_3d": list(decision_learning_context.get("weak_setups_3d", []) or [])[:3],
            "active_operational_responses": list(decision_learning_context.get("active_operational_responses", []) or [])[:4],
        }
        response, messages = _create_completion(fallback_prompt, min(decision_max_tokens, 1800))
        record_llm_response(settings, "trade_decision_fallback", response, prompt=messages)
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
) -> list[TradeRecommendation]:
    """Conservative fallback for paper trading when the LLM decision layer is unavailable."""

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
        score = _float(candidate.get("score")) or 0.0
        if score < max(float(settings.entry_quality_min_score), 14.0):
            continue
        risk = candidate.get("risk_plan", {}) or {}
        eligible.append(
            {
                **candidate,
                "symbol": symbol,
                "entry_price": _float(risk.get("entry_price")),
                "stop_loss": _float(risk.get("stop_loss")),
                "take_profit": _float(risk.get("take_profit")),
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
            )
        )
    return recommendations


def build_buy_order_plans(
    settings: Settings,
    portfolio: PortfolioSnapshot,
    recommendations: list[TradeRecommendation],
    *,
    dry_run: bool = True,
    rejected: list[dict[str, Any]] | None = None,
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
    latest_technical_context = _annotate_technical_context_with_learning(
        load_latest_technical_candidates(settings.data_dir, per_side=50),
        daily_learning_digest,
        operational_response_context,
        settings.data_dir,
    )
    portfolio_risk_context = _portfolio_risk_context(settings, portfolio)
    planned_buy_exposure = 0.0
    planned_buy_risk_amount = 0.0

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
    exceptional_terms = (
        "stop",
        "take profit",
        "take_profit",
        "bajista",
        "bearish",
        "deterioro",
        "deterioration",
        "soporte perdido",
        "lost support",
        "noticia negativa",
        "negative news",
        "drawdown",
        "riesgo extraordinario",
        "fraud",
        "guidance",
        "earnings",
    )
    rotation_terms = ("rotacion", "rotación", "rotation", "candidato mejor", "superior")
    return any(term in reason for term in exceptional_terms) and not any(
        term in reason for term in rotation_terms
    )


def build_order_plans(
    settings: Settings,
    portfolio: PortfolioSnapshot,
    recommendations: list[TradeRecommendation],
    *,
    dry_run: bool = True,
    rejected: list[dict[str, Any]] | None = None,
) -> list[OrderPlan]:
    """Build buy and long-position sell/reduce/exit plans."""

    plans = build_buy_order_plans(settings, portfolio, recommendations, dry_run=dry_run, rejected=rejected)
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
