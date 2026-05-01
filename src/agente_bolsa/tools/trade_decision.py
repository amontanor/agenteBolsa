"""LLM-driven trade recommendations with deterministic risk sizing."""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.models import OrderPlan, PortfolioSnapshot, RiskDecision, TradeRecommendation
from agente_bolsa.tools.position_sizing import recommended_notional
from agente_bolsa.tools.operational_learning import load_operational_learning_context
from agente_bolsa.tools.post_market_review import load_post_market_learning_context
from agente_bolsa.tools.risk import OrderProposal, RiskManager


VALID_ACTIONS = {"buy", "sell", "hold", "reduce", "exit"}


def _latest_report(data_dir: Path, prefix: str) -> Path | None:
    reports = list((data_dir / "reports").glob(f"{prefix}_*.json"))
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
    return {
        "path": str(path),
        "run_id": report.get("run_id"),
        "as_of": report.get("as_of"),
        "top_longs": report.get("top_longs", [])[:per_side],
        "top_shorts": report.get("top_shorts", [])[:per_side],
        "all_candidates": report.get("all_candidates", []),
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


def _sentiment_for_symbol(sentiment_context: dict[str, Any] | None, symbol: str) -> dict[str, Any]:
    if not sentiment_context:
        return {}
    symbol = symbol.upper()
    for item in sentiment_context.get("results", []):
        if str(item.get("symbol", "")).upper() == symbol:
            return item.get("sentiment", {}) or {}
    return {}


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
    relative_return_20d = _float(candidate.get("relative_return_20d"))
    confirmed_patterns = _confirmed_bullish_patterns(candidate)
    sentiment = _sentiment_for_symbol(sentiment_context, recommendation.symbol)
    sentiment_score = _float(sentiment.get("sentiment_score"))
    sentiment_confidence = _float(sentiment.get("confidence")) or 0.0

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
        "relative_return_20d": relative_return_20d,
        "confirmed_bullish_patterns": len(confirmed_patterns),
        "sentiment_score": sentiment_score,
        "sentiment_confidence": sentiment_confidence,
    }

    if direction != "long":
        return False, f"direccion tecnica no es long ({direction or 'desconocida'})", checks
    if setup_quality != "strong":
        return False, f"setup no es strong ({setup_quality or 'desconocido'})", checks
    if score < settings.entry_quality_min_score:
        return False, f"score {score} < minimo {settings.entry_quality_min_score}", checks
    if return_20d is not None and return_20d <= 0:
        return False, f"momentum 20d no positivo ({return_20d:.2%})", checks
    if relative_return_20d is not None and relative_return_20d <= 0:
        return False, f"fuerza relativa 20d negativa vs benchmark ({relative_return_20d:.2%})", checks
    if macd is not None and macd_signal is not None and macd <= macd_signal:
        return False, "MACD no confirma momentum alcista", checks
    if sentiment_score is not None and sentiment_confidence >= 0.5 and sentiment_score <= -0.5:
        return False, f"sentimiento negativo confirmado ({sentiment_score})", checks

    if close and sma20:
        sma20_distance = (close - sma20) / sma20
        checks["sma20_distance"] = round(sma20_distance, 4)
        if sma20_distance > settings.entry_quality_max_sma20_distance:
            return (
                False,
                f"precio demasiado extendido sobre SMA20 ({sma20_distance:.2%})",
                checks,
            )
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
                return False, "entrada extendida sin fuerza relativa 20d disponible", checks
            if relative_return_20d < settings.entry_quality_extended_min_relative_return:
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

    prompt = {
        "portfolio": asdict(portfolio),
        "technical_candidates": technical_context,
        "news_sentiment": sentiment_context,
        "portfolio_rebalance": rebalance_context or {},
        "post_market_learning": load_post_market_learning_context(settings.data_dir),
        "operational_learning": load_operational_learning_context(settings.data_dir),
        "risk_limits": {
            "max_portfolio_exposure": settings.max_portfolio_exposure,
            "max_position_exposure": settings.max_position_exposure,
            "max_risk_per_trade": settings.max_risk_per_trade,
            "max_orders_per_cycle": settings.max_orders_per_cycle,
            "max_daily_buy_orders": settings.max_daily_buy_orders,
            "min_order_notional": settings.min_order_notional,
            "allow_position_adds": settings.allow_position_adds,
            "min_confidence_to_trade": settings.min_llm_confidence_to_trade,
            "allow_short_selling": settings.allow_short_selling,
        },
    }
    client = OpenAI(
        api_key=settings.openai_api_key or "local-llama",
        base_url=settings.openai_api_base,
        timeout=settings.llm_timeout_seconds,
    )
    decision_max_tokens = max(settings.llm_max_tokens or 0, 3000)
    response = client.chat.completions.create(
        model=settings.openai_model,
        temperature=settings.llm_temperature,
        max_tokens=decision_max_tokens,
        messages=[
            {
                "role": "system",
                "content": (
                    "Eres un gestor de cartera experto. Usa solo los datos recibidos. "
                    "No inventes precios ni posiciones. Devuelve solo JSON valido con "
                    "la clave recommendations, una lista de objetos con: symbol, action "
                    "(buy|sell|hold|reduce|exit), confidence 0-1, reason, entry_price, "
                    "stop_loss, take_profit, target_exposure_pct como fraccion decimal "
                    "(0.03 significa 3%), time_horizon, invalidation. "
                    "Debes comparar posiciones actuales contra candidatos nuevos usando "
                    "score tecnico, fuerza relativa, sentimiento, riesgo, drawdown, "
                    "beneficio/perdida actual y coste estimado de rotacion. "
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
                    "No compres solo porque haya cash. "
                    "Si falta evidencia suficiente, action debe ser hold. "
                    "Devuelve como maximo 3 recomendaciones. Usa razones breves. "
                    "No uses markdown. Cierra siempre el JSON."
                ),
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=True)},
        ],
    )
    content = response.choices[0].message.content or "{}"
    parsed = _extract_json_object(content)
    recommendations = [
        recommendation
        for item in parsed.get("recommendations", [])
        if isinstance(item, dict)
        for recommendation in [_recommendation_from_dict(item)]
        if recommendation is not None
    ]
    return {
        "raw_response_preview": content[:2000],
        "recommendations": recommendations,
        "prompt_context": prompt,
    }


def build_buy_order_plans(
    settings: Settings,
    portfolio: PortfolioSnapshot,
    recommendations: list[TradeRecommendation],
    *,
    dry_run: bool = True,
) -> list[OrderPlan]:
    """Build risk-checked buy plans. Sell/reduce/exit are kept as recommendations for now."""

    plans: list[OrderPlan] = []
    risk_manager = RiskManager(settings)
    open_order_symbols = {order.symbol.upper() for order in portfolio.open_orders}

    for recommendation in recommendations:
        if len(plans) >= settings.max_orders_per_cycle:
            break
        if recommendation.action != "buy":
            continue
        if recommendation.confidence < settings.min_llm_confidence_to_trade:
            continue
        if recommendation.symbol in open_order_symbols:
            continue

        notional, sizing_checks = recommended_notional(settings, portfolio, recommendation)
        if notional <= 0:
            continue

        entry = recommendation.entry_price or 0.0
        stop = recommendation.stop_loss
        take = recommendation.take_profit
        proposal = OrderProposal(
            symbol=recommendation.symbol,
            side="buy",
            notional=notional,
            portfolio_equity=portfolio.portfolio_value,
            strategy_name="llm_portfolio_decision",
            entry_price=entry,
            stop_loss=stop,
            take_profit=take,
        )
        decision = risk_manager.validate_order(proposal)
        decision.checks["position_sizing"] = sizing_checks
        if not decision.approved:
            continue

        qty, execution_notional, execution_checks = _buy_qty_and_notional_for_execution(
            settings,
            notional=notional,
            entry_price=entry,
        )
        if qty is None or execution_notional < settings.min_order_notional:
            continue
        decision.checks["execution_sizing"] = execution_checks
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
) -> list[OrderPlan]:
    """Build buy and long-position sell/reduce/exit plans."""

    plans = build_buy_order_plans(settings, portfolio, recommendations, dry_run=dry_run)
    open_order_symbols = {order.symbol.upper() for order in portfolio.open_orders}

    for recommendation in recommendations:
        if len(plans) >= settings.max_orders_per_cycle:
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
