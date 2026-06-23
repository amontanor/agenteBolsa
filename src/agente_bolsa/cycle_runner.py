"""Observable operational cycle for the trading agent group."""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .config import Settings
from .crew import build_crew
from .eventing import AgentPhase, EventReporter
from .llm_router import select_preferred_endpoint
from .logging_utils import log_system_event
from .market_calendar import MarketCalendar
from .models import Hypothesis, new_id
from .storage import Store
from .tools.adversarial_reviewer import review_recommendations_adversarial
from .tools.backtest import build_symbol_backtest
from .tools.broker import BrokerClientFactory
from .tools.costs import TransactionCostModel
from .tools.deterministic_reviewer import recommendation_input_fingerprint, review_recommendations
from .tools.execution import submit_paper_order_plan
from .tools.market_snapshot import build_market_snapshot, compact_snapshot_for_prompt
from .tools.market_state import build_market_state, compact_market_state_for_prompt
from .tools.operational_health import load_operational_block_context
from .tools.portfolio_optimizer import build_portfolio_rebalance_context
from .tools.signal_learning import update_signal_decisions, update_signal_execution_status
from .tools.trade_decision import (
    _compact_technical_context_for_prompt,
    _effective_buy_plan_limit,
    _effective_daily_buy_limit,
    _effective_trade_recommendation_limit,
    augment_recommendations_with_deterministic_fallback,
    build_order_plans,
    deterministic_trade_fallback_recommendations,
    filter_entry_quality,
    load_latest_sentiment,
    load_latest_technical_candidates,
    record_setup_edge_cycle_shadow,
    request_trade_recommendations,
)

PHASES = [
    AgentPhase(
        "compliance_guardian",
        "preflight",
        "Validando modo paper/live, limites de riesgo, carpetas y configuracion.",
    ),
    AgentPhase(
        "market_data_researcher",
        "data_update",
        "Preparando universo, benchmark y fuentes de datos de mercado.",
    ),
    AgentPhase(
        "technical_analyst",
        "technical_study",
        "Planificando variables tecnicas: tendencia, momentum, volatilidad, volumen y fuerza relativa.",
    ),
    AgentPhase(
        "fundamental_analyst",
        "fundamental_study",
        "Revisando calidad, valoracion, crecimiento y riesgos corporativos como filtros.",
    ),
    AgentPhase(
        "hypothesis_generator",
        "hypothesis",
        "Creando hipotesis medibles con entrada, salida, horizonte e invalidacion.",
    ),
    AgentPhase(
        "quant_backtester",
        "validation",
        "Definiendo validacion con costes, slippage, walk-forward y fuera de muestra.",
    ),
    AgentPhase(
        "risk_manager",
        "risk_review",
        "Aplicando limites de exposicion, perdida diaria, drawdown y permisos de live trading.",
    ),
    AgentPhase(
        "portfolio_manager",
        "portfolio_plan",
        "Convirtiendo senales aprobadas en prioridades y tamano de posicion.",
    ),
    AgentPhase(
        "execution_agent",
        "execution_gate",
        "Preparando ejecucion, bloqueada si no existe aprobacion de riesgo.",
    ),
    AgentPhase(
        "post_trade_analyst",
        "post_mortem",
        "Registrando aprendizaje del ciclo y preparando comparacion contra resultados futuros.",
    ),
    AgentPhase(
        "self_improvement_engineer",
        "improvement_backlog",
        "Proponiendo mejoras controladas de datos, indicadores, prompts, tests y codigo.",
    ),
]


def _payload_hash(payload: Any) -> str:
    raw = json.dumps(payload or {}, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def cycle_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _ensure_seed_hypothesis(settings: Settings, store: Store, reporter: EventReporter, run_id: str) -> str:
    hypothesis = Hypothesis(
        name="relative_strength_breakout",
        description="Rupturas de 20 dias con volumen alto y fuerza relativa positiva contra SPY.",
        symbols=settings.universe,
        entry_rule="close > high_20 and volume_zscore_20 > 1.5 and rs_vs_spy_20d > 0",
        exit_rule="atr_stop_2x or max_holding_period_10d",
        invalidation_rule="out_of_sample_sharpe < threshold or max_drawdown > limit",
        horizon="1d-10d",
    )
    store.save_hypothesis(hypothesis)
    reporter.emit(
        "hypothesis_generator",
        "hypothesis_saved",
        run_id,
        f"Hipotesis base registrada: {hypothesis.name}.",
        {"hypothesis_id": hypothesis.hypothesis_id, "symbols": hypothesis.symbols},
    )
    return hypothesis.hypothesis_id


def _record_planned_validation(store: Store, reporter: EventReporter, run_id: str, hypothesis_id: str) -> None:
    backtest_run_id = new_id("bt")
    costs = TransactionCostModel()
    metrics = {
        "status": "planned",
        "transaction_cost_model": {
            "commission_bps": costs.commission_bps,
            "slippage_bps": costs.slippage_bps,
            "round_trip_bps": costs.round_trip_bps,
        },
        "required_checks": [
            "min_trades",
            "transaction_costs",
            "slippage",
            "walk_forward",
            "out_of_sample",
            "max_drawdown",
        ],
    }
    store.save_backtest_run(
        run_id=backtest_run_id,
        hypothesis_id=hypothesis_id,
        strategy_name="relative_strength_breakout",
        metrics=metrics,
        passed=False,
    )
    reporter.emit(
        "quant_backtester",
        "backtest_planned",
        run_id,
        "Backtest pendiente registrado. No se promociona estrategia sin metricas reales.",
        {"backtest_run_id": backtest_run_id, "hypothesis_id": hypothesis_id},
    )


def _record_risk_gate(store: Store, reporter: EventReporter, run_id: str, hypothesis_id: str) -> None:
    decision_id = new_id("dec")
    checks = {
        "trading_mode": "paper",
        "live_requires_manual_enable": True,
        "requires_valid_backtest": True,
        "requires_risk_approval": True,
    }
    store.save_decision(
        decision_id=decision_id,
        hypothesis_id=hypothesis_id,
        strategy_name="relative_strength_breakout",
        decision_type="promotion_gate",
        approved=False,
        reason="Bloqueada hasta tener backtest real, paper trading y aprobacion de riesgo.",
        checks=checks,
    )
    reporter.emit(
        "risk_manager",
        "decision_saved",
        run_id,
        "Promocion bloqueada hasta validar metricas reales y limites.",
        {"decision_id": decision_id, "hypothesis_id": hypothesis_id},
    )


def _short_reason(value: Any, max_chars: int = 260) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _submitted_order_summary(item: dict[str, Any]) -> str:
    parts = [
        f"{item['symbol']} ${item['notional']:.2f} ({item['status']})",
    ]
    if item.get("confidence") is not None:
        parts.append(f"conf {float(item['confidence']):.2f}")
    if item.get("entry_price") and item.get("stop_loss") and item.get("take_profit"):
        parts.append(
            f"entrada {float(item['entry_price']):.2f}, stop {float(item['stop_loss']):.2f}, take {float(item['take_profit']):.2f}"
        )
    if item.get("reason"):
        parts.append(f"cumple: {_short_reason(item['reason'])}")
    return " | ".join(parts)


def _session_start_utc_iso(settings: Settings) -> str:
    now_local = datetime.now(ZoneInfo(settings.local_timezone))
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_local.astimezone(timezone.utc).isoformat()


def _apply_daily_buy_limit(
    settings: Settings,
    store: Store,
    reporter: EventReporter,
    run_id: str,
    plans: list[Any],
    *,
    rejected: list[dict[str, Any]] | None = None,
) -> list[Any]:
    daily_buy_limit = _effective_daily_buy_limit(settings, plans)
    if daily_buy_limit <= 0:
        return plans

    used_buys = store.count_broker_orders(
        side="buy",
        since_iso=_session_start_utc_iso(settings),
    )
    remaining_buys = max(0, daily_buy_limit - used_buys)
    kept = []
    blocked = []
    for plan in plans:
        if str(plan.side).lower() != "buy":
            kept.append(plan)
            continue
        if remaining_buys > 0:
            kept.append(plan)
            remaining_buys -= 1
        else:
            blocked.append(plan)

    if blocked:
        if rejected is not None:
            for plan in blocked:
                rejected.append(
                    {
                        "symbol": plan.symbol,
                        "action": str(getattr(plan, "side", "")).lower(),
                        "stage": "daily_buy_limit",
                        "reason": "max_daily_buy_orders_reached",
                        "checks": {
                            "used_buy_orders_today": used_buys,
                            "max_daily_buy_orders": settings.max_daily_buy_orders,
                            "effective_max_daily_buy_orders": daily_buy_limit,
                        },
                    }
                )
        reporter.emit(
            "risk_manager",
            "daily_buy_limit_applied",
            run_id,
            (
                "Compras bloqueadas por limite diario: "
                f"ya usadas {used_buys}/{daily_buy_limit}; "
                f"bloqueadas: {', '.join(plan.symbol for plan in blocked)}."
            ),
            {
                "used_buy_orders_today": used_buys,
                "max_daily_buy_orders": settings.max_daily_buy_orders,
                "effective_max_daily_buy_orders": daily_buy_limit,
                "blocked_symbols": [plan.symbol for plan in blocked],
            },
        )
    return kept


def _backtest_gate_decision(settings: Settings, report: dict[str, Any]) -> tuple[bool, str]:
    validation_gate = ((report.get("validation") or {}).get("gate")) or {}
    if validation_gate:
        return bool(validation_gate.get("approved")), str(validation_gate.get("reason") or "backtest evaluado")
    metrics = report.get("metrics", {}) or {}
    trades = int(metrics.get("trades") or 0)
    hit_rate = float(metrics.get("hit_rate") or 0)
    profit_factor = metrics.get("profit_factor")
    max_drawdown = float(metrics.get("max_drawdown") or 0)
    if trades < settings.backtest_gate_min_trades:
        return False, f"trades {trades} < minimo {settings.backtest_gate_min_trades}"
    if hit_rate < settings.backtest_gate_min_hit_rate:
        return False, f"hit-rate {hit_rate:.2%} < minimo {settings.backtest_gate_min_hit_rate:.2%}"
    if profit_factor is None or float(profit_factor) < settings.backtest_gate_min_profit_factor:
        return False, f"profit-factor {profit_factor} < minimo {settings.backtest_gate_min_profit_factor}"
    if max_drawdown < -settings.backtest_gate_max_drawdown:
        return False, f"max drawdown {max_drawdown:.2%} excede {settings.backtest_gate_max_drawdown:.2%}"
    return True, "backtest aprobado"


def _apply_backtest_gate(
    settings: Settings,
    reporter: EventReporter,
    run_id: str,
    recommendations: list[Any],
) -> tuple[list[Any], list[dict[str, Any]]]:
    if not settings.backtest_gate_enabled:
        return recommendations, []

    kept = []
    decisions = []
    start = (datetime.now(timezone.utc).date() - timedelta(days=settings.backtest_gate_lookback_days)).isoformat()
    for recommendation in recommendations:
        if recommendation.action != "buy":
            kept.append(recommendation)
            continue
        try:
            report = build_symbol_backtest(
                recommendation.symbol,
                settings.data_dir / "reports",
                new_id("btgate"),
                start=start,
                benchmark_symbol=settings.benchmark_symbol,
                provider=settings.market_data_provider,
                fmp_api_key=settings.fmp_api_key,
                gate_config={
                    "min_trades": settings.backtest_gate_min_trades,
                    "min_hit_rate": settings.backtest_gate_min_hit_rate,
                    "min_profit_factor": settings.backtest_gate_min_profit_factor,
                    "max_drawdown": settings.backtest_gate_max_drawdown,
                    "min_alpha_vs_benchmark": settings.backtest_gate_min_alpha_vs_benchmark,
                    "min_trade_window_alpha": settings.backtest_gate_min_trade_window_alpha,
                    "min_regime_trades": settings.backtest_gate_min_regime_trades,
                    "max_negative_regimes": settings.backtest_gate_max_negative_regimes,
                },
            )
            approved, reason = _backtest_gate_decision(settings, report)
            metrics = report.get("metrics", {})
            decisions.append(
                {
                    "symbol": recommendation.symbol,
                    "approved": approved,
                    "reason": reason,
                    "path": report.get("path"),
                    "metrics": metrics,
                }
            )
            if approved:
                kept.append(recommendation)
            elif (
                settings.trading_mode == "paper"
                and settings.backtest_gate_paper_soft_override_enabled
                and "backtest_soft_override_eligible" in list(getattr(recommendation, "soft_override_reasons", []) or [])
            ):
                kept.append(
                    replace(
                        recommendation,
                        micro_experiment=True,
                        size_multiplier=min(
                            float(getattr(recommendation, "size_multiplier", 1.0) or 1.0),
                            float(settings.micro_experiment_size_multiplier),
                        ),
                        backtest_soft_override=True,
                        soft_override_reasons=[
                            *list(getattr(recommendation, "soft_override_reasons", []) or []),
                            f"backtest_gate_failed:{reason}",
                        ],
                    )
                )
        except Exception as exc:  # noqa: BLE001 - missing validation should block buys, not crash cycle.
            reason = f"backtest fallido: {exc}"
            decisions.append(
                {
                    "symbol": recommendation.symbol,
                    "approved": False,
                    "reason": reason,
                    "error": repr(exc),
                }
            )
            if (
                settings.trading_mode == "paper"
                and settings.backtest_gate_paper_soft_override_enabled
                and "backtest_soft_override_eligible" in list(getattr(recommendation, "soft_override_reasons", []) or [])
            ):
                kept.append(
                    replace(
                        recommendation,
                        micro_experiment=True,
                        size_multiplier=min(
                            float(getattr(recommendation, "size_multiplier", 1.0) or 1.0),
                            float(settings.micro_experiment_size_multiplier),
                        ),
                        backtest_soft_override=True,
                        soft_override_reasons=[
                            *list(getattr(recommendation, "soft_override_reasons", []) or []),
                            f"backtest_gate_failed:{reason}",
                        ],
                    )
                )

    blocked = [item for item in decisions if not item["approved"]]
    approved_items = [item for item in decisions if item["approved"]]
    if decisions:
        reporter.emit(
            "quant_backtester",
            "backtest_gate_completed",
            run_id,
            (
                "Filtro backtest aplicado. "
                f"Aprobados: {', '.join(item['symbol'] for item in approved_items) or 'ninguno'}. "
                f"Bloqueados: {', '.join(item['symbol'] for item in blocked) or 'ninguno'}."
            ),
            {
                "start": start,
                "thresholds": {
                    "min_trades": settings.backtest_gate_min_trades,
                    "min_hit_rate": settings.backtest_gate_min_hit_rate,
                    "min_profit_factor": settings.backtest_gate_min_profit_factor,
                    "max_drawdown": settings.backtest_gate_max_drawdown,
                },
                "decisions": decisions,
            },
        )
    return kept, decisions


def _apply_entry_quality_gate(
    settings: Settings,
    reporter: EventReporter,
    run_id: str,
    recommendations: list[Any],
    technical_context: dict[str, Any] | None,
    sentiment_context: dict[str, Any] | None,
) -> tuple[list[Any], list[dict[str, Any]]]:
    kept, decisions = filter_entry_quality(
        settings,
        recommendations,
        technical_context,
        sentiment_context,
    )
    if not decisions or not settings.entry_quality_gate_enabled:
        return kept, decisions

    blocked = [item for item in decisions if item["action"] == "buy" and not item["approved"]]
    approved = [item for item in decisions if item["action"] == "buy" and item["approved"]]
    approved_text = ", ".join(item["symbol"] for item in approved) or "ninguna"
    blocked_text = ", ".join(f"{item['symbol']} ({item['reason']})" for item in blocked) or "ninguna"
    reporter.emit(
        "risk_manager",
        "entry_quality_gate_completed",
        run_id,
        (
            "Filtro calidad entrada aplicado. "
            f"Compras aprobadas: {approved_text}. "
            f"Bloqueadas: {blocked_text}."
        ),
        {"decisions": decisions},
    )
    return kept, decisions


def _record_trade_summary(
    settings: Settings,
    store: Store,
    reporter: EventReporter,
    run_id: str,
    auto_result: dict[str, Any] | None = None,
) -> None:
    auto_result = auto_result or {}
    operational_kill_switch = load_operational_block_context(settings.data_dir)
    submitted = auto_result.get("submitted", [])
    if submitted:
        buys = [item for item in submitted if str(item.get("side", "")).lower() == "buy"]
        sells = [item for item in submitted if str(item.get("side", "")).lower() == "sell"]
        buy_text = " || ".join(_submitted_order_summary(item) for item in buys) or "ninguna"
        sell_text = " || ".join(_submitted_order_summary(item) for item in sells) or "ninguna"
        reporter.emit(
            "execution_agent",
            "trade_execution_summary",
            run_id,
            f"Ordenes paper enviadas en este ciclo. compras: {buy_text}; ventas: {sell_text}.",
            {
                "auto_paper_trading": settings.auto_paper_trading,
                "require_human_approval": settings.require_human_approval,
                "operational_kill_switch": operational_kill_switch,
                "submitted": submitted,
                "failed": auto_result.get("failed", []),
                "backtest_gate": auto_result.get("backtest_gate", []),
                "entry_quality_gate": auto_result.get("entry_quality_gate", []),
            },
        )
        return
    failed = auto_result.get("failed", [])
    if failed:
        reason = "; ".join(str(item.get("error", item)) for item in failed[:3])
        reporter.emit(
            "execution_agent",
            "trade_execution_summary",
            run_id,
            f"No compra ni vende. Auto paper fallo o no pudo decidir: {reason}",
            {
                "auto_paper_trading": settings.auto_paper_trading,
                "require_human_approval": settings.require_human_approval,
                "operational_kill_switch": operational_kill_switch,
                "failed": failed,
                "backtest_gate": auto_result.get("backtest_gate", []),
                "entry_quality_gate": auto_result.get("entry_quality_gate", []),
            },
        )
        return

    if auto_result:
        recommendations = auto_result.get("recommendations", [])
        approved_buys = auto_result.get("approved_buys", [])
        rejected_order_plans = auto_result.get("rejected_order_plans", [])
        if recommendations:
            actions = ", ".join(
                f"{item.get('symbol')}:{item.get('action')}:{float(item.get('confidence', 0)):.2f}"
                for item in recommendations
            )
            message = (
                "No compra ni vende en este ciclo. "
                f"Decision automatica: {actions}. No hay plan aprobado nuevo."
            )
        else:
            message = "No compra ni vende en este ciclo. Auto paper activo, sin plan aprobado nuevo."
        if approved_buys and rejected_order_plans:
            approved_text = ", ".join(approved_buys[:5])
            rejection_text = "; ".join(
                f"{item.get('symbol')} {item.get('stage')}:{item.get('reason')}"
                for item in rejected_order_plans[:3]
            )
            message = (
                "No compra ni vende en este ciclo. "
                f"Compras aprobadas por señal: {approved_text}, "
                f"pero sin envío por restricciones posteriores: {rejection_text}."
            )
        if auto_result.get("blocked") == "operational_kill_switch":
            reasons = operational_kill_switch.get("reasons", [])
            detail = "; ".join(reasons[:2]) if reasons else "alertas criticas activas"
            message = f"No compra ni vende en este ciclo. Operational kill switch activo: {detail}."
        reporter.emit(
            "execution_agent",
            "trade_execution_summary",
            run_id,
            message,
            {
                "auto_paper_trading": settings.auto_paper_trading,
                "require_human_approval": settings.require_human_approval,
                "operational_kill_switch": operational_kill_switch,
                "recommendations": recommendations,
                "approved_buys": approved_buys,
                "submitted": [],
                "failed": [],
                "rejected_order_plans": rejected_order_plans,
                "backtest_gate": auto_result.get("backtest_gate", []),
                "entry_quality_gate": auto_result.get("entry_quality_gate", []),
            },
        )
        return

    pending_plans = store.pending_order_plans(limit=20)
    buys = [plan for plan in pending_plans if str(plan.get("side", "")).lower() == "buy"]
    sells = [plan for plan in pending_plans if str(plan.get("side", "")).lower() == "sell"]

    if not pending_plans:
        message = (
            "No compra ni vende. Este ciclo solo analiza; no hay planes aprobados pendientes "
            "para enviar a Alpaca paper."
        )
    else:
        buy_text = ", ".join(f"{plan['symbol']} ${plan['notional']:.2f}" for plan in buys) or "ninguna"
        sell_text = ", ".join(f"{plan['symbol']} ${plan['notional']:.2f}" for plan in sells) or "ninguna"
        message = (
            "No envia ordenes automaticamente. Planes paper pendientes: "
            f"compras: {buy_text}; ventas: {sell_text}. "
            "Para enviarlos usa execute-approved --confirm-paper."
        )

    reporter.emit(
        "execution_agent",
        "trade_execution_summary",
        run_id,
        message,
        {
            "auto_paper_trading": settings.auto_paper_trading,
            "require_human_approval": settings.require_human_approval,
            "operational_kill_switch": operational_kill_switch,
            "pending_plans": len(pending_plans),
            "pending_buys": [
                {"symbol": plan["symbol"], "notional": plan["notional"], "cycle_id": plan["cycle_id"]}
                for plan in buys
            ],
            "pending_sells": [
                {"symbol": plan["symbol"], "notional": plan["notional"], "cycle_id": plan["cycle_id"]}
                for plan in sells
            ],
        },
    )


def _auto_paper_trade(
    settings: Settings,
    store: Store,
    reporter: EventReporter,
    run_id: str,
    technical_context: dict[str, Any] | None,
    market_snapshot: dict[str, Any] | None,
    market_state: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not settings.auto_paper_trading:
        return None
    if settings.require_human_approval:
        reporter.emit(
            "execution_agent",
            "paper_auto_trade_blocked",
            run_id,
            "Auto paper trading bloqueado porque REQUIRE_HUMAN_APPROVAL=true.",
            {},
        )
        return {"submitted": [], "failed": [], "blocked": "REQUIRE_HUMAN_APPROVAL"}
    if settings.trading_mode != "paper" or not settings.alpaca_paper or settings.allow_live_trading:
        reporter.emit(
            "execution_agent",
            "paper_auto_trade_blocked",
            run_id,
            "Auto paper trading bloqueado: solo se permite con TRADING_MODE=paper, ALPACA_PAPER=true y live desactivado.",
            {
                "trading_mode": settings.trading_mode,
                "alpaca_paper": settings.alpaca_paper,
                "allow_live_trading": settings.allow_live_trading,
            },
        )
        return {"submitted": [], "failed": [], "blocked": "paper_safety"}
    operational_kill_switch = load_operational_block_context(settings.data_dir)
    if settings.operational_kill_switch_enabled and operational_kill_switch.get("block_buy_execution"):
        reporter.emit(
            "execution_agent",
            "paper_auto_trade_blocked",
            run_id,
            "Auto paper trading bloqueado por operational kill switch: alertas criticas activas.",
            operational_kill_switch,
        )
        return {
            "submitted": [],
            "failed": [],
            "blocked": "operational_kill_switch",
            "operational_kill_switch": operational_kill_switch,
        }

    market_status = MarketCalendar(settings.market_calendar, settings.local_timezone).status()
    if not market_status.is_open:
        reporter.emit(
            "execution_agent",
            "paper_auto_trade_blocked",
            run_id,
            "Auto paper trading bloqueado: mercado cerrado. No se envian ordenes intradia.",
            market_status.as_dict(),
        )
        return {"submitted": [], "failed": [], "blocked": "market_closed"}

    try:
        portfolio = BrokerClientFactory(settings).alpaca_portfolio_snapshot()
        decision_context = technical_context or load_latest_technical_candidates(
            settings.data_dir,
            per_side=max(1, settings.news_sentiment_top_n // 2),
        )
        effective_recommendation_limit = _effective_trade_recommendation_limit(settings, decision_context)
        sentiment_context = load_latest_sentiment(settings.data_dir)
        rebalance_context = build_portfolio_rebalance_context(
            settings,
            portfolio,
            decision_context,
            sentiment_context,
        )
        reporter.emit(
            "execution_agent",
            "paper_auto_trade_started",
            run_id,
            "Auto paper trading activo: solicitando decision LLM estructurada y planes de orden.",
            {
                "max_orders_per_cycle": settings.max_orders_per_cycle,
                "effective_max_orders_per_cycle": max(settings.max_orders_per_cycle, effective_recommendation_limit),
                "max_daily_buy_orders": settings.max_daily_buy_orders,
                "effective_max_daily_buy_orders": max(settings.max_daily_buy_orders, effective_recommendation_limit),
            },
        )
        decision = request_trade_recommendations(
            settings,
            portfolio,
            decision_context,
            sentiment_context,
            rebalance_context,
            market_state,
        )
    except Exception as exc:  # noqa: BLE001 - bad LLM JSON or broker read must not stop scheduler.
        if settings.deterministic_trade_fallback_enabled and "portfolio" in locals() and "decision_context" in locals():
            fallback_recommendations = deterministic_trade_fallback_recommendations(
                settings,
                portfolio,
                decision_context,
                limit=locals().get("effective_recommendation_limit"),
                market_state=market_state,
            )
            reporter.emit(
                "execution_agent",
                "paper_auto_trade_llm_fallback",
                run_id,
                (
                    "Decision LLM no disponible; usando fallback determinista conservador "
                    f"con {len(fallback_recommendations)} recomendacion(es)."
                ),
                {"error": str(exc), "recommendations": [asdict(item) for item in fallback_recommendations]},
            )
            decision = {
                "recommendations": fallback_recommendations,
                "raw_response_preview": "",
                "prompt_context": {},
                "fallback_error": str(exc),
            }
        else:
            reporter.emit(
                "execution_agent",
                "paper_auto_trade_failed",
                run_id,
                f"No compra ni vende. Decision automatica fallida: {exc}",
                {"error": repr(exc)},
            )
            return {"submitted": [], "failed": [{"stage": "decision", "error": str(exc)}]}

    # Medicion shadow A2 (cada ciclo, no solo en fallback): mide el funnel de
    # setup-quality y como reordenaria el sesgo de edge, sin tocar la seleccion.
    # Gobernado por SETUP_EDGE_BIAS_SHADOW_ENABLED; la funcion traga sus errores.
    try:
        _cycle_shadow = record_setup_edge_cycle_shadow(settings, decision_context, market_state)
        if _cycle_shadow.get("enabled") and not _cycle_shadow.get("error"):
            reporter.emit(
                "execution_agent",
                "setup_edge_cycle_shadow",
                run_id,
                (
                    "Shadow setup-edge por ciclo: "
                    f"{_cycle_shadow.get('candidates_total', 0)} candidatos, "
                    f"sin_patron|strong={_cycle_shadow.get('sin_patron_strong_count', 0)}, "
                    f"edge_table={_cycle_shadow.get('edge_table_rows', 0)} filas, "
                    f"cambia_top={_cycle_shadow.get('changed')}."
                ),
                _cycle_shadow,
            )
    except Exception:  # noqa: BLE001 - la medicion shadow nunca corta el ciclo
        pass

    recommendations = decision["recommendations"]
    recommendation_augmentation = {"added": [], "replaced_holds": [], "fallback_candidates": 0}
    if settings.deterministic_trade_fallback_enabled:
        recommendations, recommendation_augmentation = augment_recommendations_with_deterministic_fallback(
            settings,
            portfolio,
            decision_context,
            recommendations,
            limit=locals().get("effective_recommendation_limit"),
            market_state=market_state,
        )
        if recommendation_augmentation.get("added"):
            reporter.emit(
                "execution_agent",
                "paper_auto_trade_recommendation_augmented",
                run_id,
                (
                    "Fallback determinista completa la decision del LLM con "
                    f"{len(recommendation_augmentation['added'])} compra(s)."
                ),
                recommendation_augmentation,
            )
    reviewed_recommendations, deterministic_review = review_recommendations(
        settings,
        recommendations,
        decision_context,
        sentiment_context,
        market_state,
    )
    if deterministic_review:
        reporter.emit(
            "risk_manager",
            "deterministic_review_completed",
            run_id,
            (
                "Revision determinista completada. "
                f"Aprobadas: {', '.join(item['symbol'] for item in deterministic_review if item['approved']) or 'ninguna'}. "
                f"Bloqueadas: {', '.join(item['symbol'] for item in deterministic_review if not item['approved']) or 'ninguna'}."
            ),
            {"decisions": deterministic_review},
        )
    adversarial_review = review_recommendations_adversarial(
        reviewed_recommendations,
        technical_context=decision_context,
        market_state=market_state,
    )
    if adversarial_review:
        reporter.emit(
            "risk_manager",
            "adversarial_review_completed",
            run_id,
            (
                "Revision adversarial determinista completada. "
                f"Bloqueos: {sum(1 for item in adversarial_review if not item['approved'])}."
            ),
            {"decisions": adversarial_review},
        )

    model_info = {
        "llm_model": settings.openai_model,
        "secondary_review_llm_enabled": settings.secondary_review_llm_enabled,
        "secondary_review_llm_model": settings.secondary_review_llm_model,
        "trade_aggressiveness_profile": settings.trade_aggressiveness_profile,
        "decision_fallback_error": decision.get("fallback_error"),
    }
    gate_config = {
        "entry_quality_gate_enabled": settings.entry_quality_gate_enabled,
        "backtest_gate_enabled": settings.backtest_gate_enabled,
        "min_llm_confidence_to_trade": settings.min_llm_confidence_to_trade,
    }
    for recommendation in reviewed_recommendations:
        review_row = next(
            (item for item in deterministic_review if item["symbol"] == recommendation.symbol and item["action"] == recommendation.action),
            None,
        )
        adversarial_row = next(
            (item for item in adversarial_review if item["symbol"] == recommendation.symbol and item["action"] == recommendation.action),
            None,
        )
        fingerprint = recommendation_input_fingerprint(
            recommendation,
            market_snapshot=market_snapshot,
            market_state=market_state,
            technical_context=decision_context,
            sentiment_context=sentiment_context,
            model_info=model_info,
            gate_config=gate_config,
        )
        store.save_trade_recommendation(
            recommendation_id=new_id("rec"),
            cycle_id=run_id,
            symbol=recommendation.symbol,
            action=recommendation.action,
            confidence=recommendation.confidence,
            payload={
                **asdict(recommendation),
                "deterministic_review": review_row,
                "adversarial_review": adversarial_row,
                "decision_input_fingerprint": fingerprint,
                "market_state_quality": ((market_state or {}).get("data_quality") or {}).get("status"),
                "prompt_version": "trade_decision.v2",
                "model_config_hash": _payload_hash(model_info),
                "feature_hash": _payload_hash(decision_context),
                "data_provider_hash": _payload_hash(
                    {
                        "market_state_provider": (market_state or {}).get("provider"),
                        "market_snapshot_provider": (market_snapshot or {}).get("provider"),
                        "data_vendor_quality": ((market_state or {}).get("data_quality") or {}).get("data_vendor_quality"),
                    }
                ),
                "model_info": model_info,
            },
        )

    quality_recommendations, entry_quality_gate = _apply_entry_quality_gate(
        settings,
        reporter,
        run_id,
        reviewed_recommendations,
        decision_context,
        sentiment_context,
    )
    gated_recommendations, backtest_gate = _apply_backtest_gate(
        settings,
        reporter,
        run_id,
        quality_recommendations,
    )
    learned_decisions = update_signal_decisions(
        store,
        source_run_id=decision_context.get("run_id"),
        recommendations=reviewed_recommendations,
        entry_quality_gate=entry_quality_gate,
        backtest_gate=backtest_gate,
        settings=settings,
    )
    if learned_decisions:
        reporter.emit(
            "self_improvement_engineer",
            "signal_learning_decisions_updated",
            run_id,
            f"Aprendizaje actualizado con {learned_decisions} decision(es) de senal.",
            {"source_run_id": decision_context.get("run_id"), "updated": learned_decisions},
        )
    rejected_order_plans: list[dict[str, Any]] = []
    plans = build_order_plans(
        settings,
        portfolio,
        gated_recommendations,
        dry_run=True,
        rejected=rejected_order_plans,
        market_state=market_state,
    )
    effective_plan_limit = _effective_buy_plan_limit(settings, gated_recommendations)
    effective_daily_limit = _effective_daily_buy_limit(settings, plans)
    approved_buys = sorted({item.symbol for item in gated_recommendations if str(item.action).lower() == "buy"})
    plans = _apply_daily_buy_limit(settings, store, reporter, run_id, plans, rejected=rejected_order_plans)
    planned_symbols = [plan.symbol for plan in plans if str(plan.side).lower() == "buy"]
    for plan in plans:
        plan_id = new_id("plan")
        store.save_order_plan(
            plan_id=plan_id,
            cycle_id=run_id,
            symbol=plan.symbol,
            side=plan.side,
            notional=plan.notional,
            approved=plan.risk_decision.approved,
            dry_run=plan.dry_run,
            payload=asdict(plan),
        )

    if not plans:
        execution_updates = update_signal_execution_status(
            store,
            source_run_id=decision_context.get("run_id"),
            approved_symbols=approved_buys,
            rejected_order_plans=rejected_order_plans,
            planned_symbols=[],
            submitted=[],
            failed=[],
            effective_max_orders_per_cycle=effective_plan_limit,
            effective_max_daily_buy_orders=effective_daily_limit,
        )
        actions = ", ".join(
            f"{item.symbol}:{item.action}:{item.confidence:.2f}" for item in reviewed_recommendations
        ) or "sin recomendaciones"
        reporter.emit(
            "execution_agent",
            "paper_auto_trade_completed",
            run_id,
            f"No compra ni vende. Recomendaciones sin plan aprobado: {actions}.",
            {
                "recommendations": [asdict(item) for item in reviewed_recommendations],
                "deterministic_review": deterministic_review,
                "adversarial_review": adversarial_review,
                "entry_quality_gate": entry_quality_gate,
                "backtest_gate": backtest_gate,
                "rebalance_context": rebalance_context,
                "approved_buys": approved_buys,
                "effective_max_orders_per_cycle": effective_plan_limit,
                "effective_max_daily_buy_orders": effective_daily_limit,
                "rejected_order_plans": rejected_order_plans,
                "execution_updates": execution_updates,
                "recommendation_augmentation": recommendation_augmentation,
                "submitted": [],
            },
        )
        return {
            "submitted": [],
            "failed": [],
            "recommendations": [asdict(item) for item in reviewed_recommendations],
            "deterministic_review": deterministic_review,
            "adversarial_review": adversarial_review,
            "entry_quality_gate": entry_quality_gate,
            "backtest_gate": backtest_gate,
            "approved_buys": approved_buys,
            "effective_max_orders_per_cycle": effective_plan_limit,
            "effective_max_daily_buy_orders": effective_daily_limit,
            "rejected_order_plans": rejected_order_plans,
            "execution_updates": execution_updates,
            "recommendation_augmentation": recommendation_augmentation,
        }

    submitted = []
    failed = []
    pending_current = store.pending_order_plans(cycle_id=run_id, limit=max(len(plans), settings.max_orders_per_cycle))
    for plan in pending_current:
        client_order_id = f"agente-{plan['plan_id'][:20]}"
        try:
            order = submit_paper_order_plan(settings, plan, client_order_id=client_order_id)
            broker_order_id = order["id"] or client_order_id
            recommendation = plan.get("payload", {}).get("recommendation", {}) or {}
            risk_decision = plan.get("payload", {}).get("risk_decision", {}) or {}
            store.save_broker_order(
                broker_order_id=broker_order_id,
                plan_id=plan["plan_id"],
                cycle_id=run_id,
                symbol=plan["symbol"],
                side=plan["side"],
                status=order["status"],
                payload={"plan": plan, "broker_order": order},
            )
            submitted.append(
                {
                    "symbol": plan["symbol"],
                    "side": plan["side"],
                    "notional": plan["notional"],
                    "status": order["status"],
                    "confidence": recommendation.get("confidence"),
                    "reason": recommendation.get("reason"),
                    "entry_price": plan.get("payload", {}).get("entry_price"),
                    "stop_loss": plan.get("payload", {}).get("stop_loss"),
                    "take_profit": plan.get("payload", {}).get("take_profit"),
                    "risk_reason": risk_decision.get("reason"),
                    "risk_checks": risk_decision.get("checks", {}),
                }
            )
        except Exception as exc:  # noqa: BLE001 - one rejected order should not hide the rest.
            failed.append({"symbol": plan["symbol"], "side": plan["side"], "error": str(exc)})

    buys = [item for item in submitted if item["side"].lower() == "buy"]
    sells = [item for item in submitted if item["side"].lower() == "sell"]
    buy_text = " || ".join(_submitted_order_summary(item) for item in buys) or "ninguna"
    sell_text = " || ".join(_submitted_order_summary(item) for item in sells) or "ninguna"
    if failed:
        fail_text = "; fallos: " + ", ".join(f"{item['symbol']} {item['side']}: {item['error']}" for item in failed)
    else:
        fail_text = ""
    execution_updates = update_signal_execution_status(
        store,
        source_run_id=decision_context.get("run_id"),
        approved_symbols=approved_buys,
        rejected_order_plans=rejected_order_plans,
        planned_symbols=planned_symbols,
        submitted=submitted,
        failed=failed,
        effective_max_orders_per_cycle=effective_plan_limit,
        effective_max_daily_buy_orders=effective_daily_limit,
    )
    reporter.emit(
        "execution_agent",
        "paper_auto_trade_completed",
        run_id,
        f"Ordenes paper enviadas. compras: {buy_text}; ventas: {sell_text}.{fail_text}",
        {
            "submitted": submitted,
            "failed": failed,
            "deterministic_review": deterministic_review,
            "adversarial_review": adversarial_review,
            "entry_quality_gate": entry_quality_gate,
            "backtest_gate": backtest_gate,
            "effective_max_orders_per_cycle": effective_plan_limit,
            "effective_max_daily_buy_orders": effective_daily_limit,
            "rejected_order_plans": rejected_order_plans,
            "execution_updates": execution_updates,
            "recommendation_augmentation": recommendation_augmentation,
        },
    )
    return {
        "submitted": submitted,
        "failed": failed,
        "deterministic_review": deterministic_review,
        "adversarial_review": adversarial_review,
        "entry_quality_gate": entry_quality_gate,
        "backtest_gate": backtest_gate,
        "effective_max_orders_per_cycle": effective_plan_limit,
        "effective_max_daily_buy_orders": effective_daily_limit,
        "rejected_order_plans": rejected_order_plans,
        "execution_updates": execution_updates,
        "recommendation_augmentation": recommendation_augmentation,
    }


def run_observable_cycle(
    settings: Settings,
    store: Store,
    *,
    use_crew: bool = True,
    verbose: bool = True,
    technical_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one cycle and make every phase visible in the console and logs."""

    settings.assert_trading_safety()
    store.ensure_schema()
    run_id = cycle_id()
    reporter = EventReporter(store, verbose=verbose)

    log_system_event(settings.logs_dir, "cycle_started", {"cycle_id": run_id})
    reporter.emit(
        "orchestrator",
        "cycle_started",
        run_id,
        f"Ciclo iniciado en modo {settings.trading_mode}. Universo: {', '.join(settings.universe)}.",
        {"universe": settings.universe, "trading_mode": settings.trading_mode},
    )

    for phase in PHASES:
        reporter.emit(phase.agent, f"{phase.action}_started", run_id, phase.detail)
        reporter.emit(phase.agent, f"{phase.action}_completed", run_id, "Fase preparada y registrada.")

    hypothesis_id = _ensure_seed_hypothesis(settings, store, reporter, run_id)
    _record_planned_validation(store, reporter, run_id, hypothesis_id)
    _record_risk_gate(store, reporter, run_id, hypothesis_id)

    market_snapshot: dict[str, Any] | None = None
    market_snapshot_prompt = "{}"
    market_state: dict[str, Any] | None = None
    market_state_prompt = "{}"
    technical_context_prompt = json.dumps(
        _compact_technical_context_for_prompt(technical_context or {}) if technical_context else {},
        ensure_ascii=True,
    )
    try:
        reporter.emit(
            "market_data_researcher",
            "market_snapshot_started",
            run_id,
            "Descargando precios reales y calculando variables tecnicas basicas.",
        )
        market_snapshot = build_market_snapshot(
            settings.universe,
            settings.benchmark_symbol,
            settings.data_dir / "reports",
            run_id,
            provider=settings.market_data_provider,
            fmp_api_key=settings.fmp_api_key,
        )
        market_snapshot_prompt = compact_snapshot_for_prompt(market_snapshot, max_chars=2500)
        reporter.emit(
            "market_data_researcher",
            "market_snapshot_completed",
            run_id,
            f"Snapshot guardado con {len(market_snapshot.get('symbols', {}))} simbolos.",
            {"path": market_snapshot.get("path"), "warnings": market_snapshot.get("warnings", [])},
        )
    except Exception as exc:  # noqa: BLE001 - CrewAI can still run, but it must know data is missing.
        json_safe_error = {"error": str(exc)}
        market_snapshot_prompt = json.dumps(json_safe_error, ensure_ascii=True)
        reporter.emit(
            "market_data_researcher",
            "market_snapshot_failed",
            run_id,
            f"No se pudo crear snapshot real: {exc}",
            json_safe_error,
        )

    try:
        reporter.emit(
            "market_regime_strategist",
            "market_state_started",
            run_id,
            "Construyendo estado de mercado unificado con regimen, amplitud, sentimiento y calidad de datos.",
        )
        market_state = build_market_state(
            settings,
            settings.data_dir / "reports",
            run_id,
            market_snapshot=market_snapshot,
        )
        market_state_prompt = compact_market_state_for_prompt(market_state, max_chars=2500)
        state_quality = ((market_state.get("data_quality") or {}).get("status") or "UNKNOWN").upper()
        event_type = "market_state_completed" if state_quality == "GOOD" else "market_state_degraded"
        reporter.emit(
            "market_regime_strategist",
            event_type,
            run_id,
            f"Estado de mercado guardado con calidad {state_quality}.",
            {
                "path": market_state.get("path"),
                "market_regime": market_state.get("market_regime"),
                "volatility_regime": market_state.get("volatility_regime"),
                "data_quality": market_state.get("data_quality"),
                "warnings": market_state.get("warnings", []),
            },
        )
    except Exception as exc:  # noqa: BLE001
        market_state_prompt = json.dumps({"error": str(exc)}, ensure_ascii=True)
        reporter.emit(
            "market_regime_strategist",
            "market_state_degraded",
            run_id,
            f"No se pudo construir market_state completo: {exc}",
            {"error": str(exc)},
        )

    crew_result: str | None = None
    if use_crew:
        endpoint, _attempts = select_preferred_endpoint(settings)
        reporter.emit(
            "orchestrator",
            "crew_started",
            run_id,
            f"Lanzando CrewAI contra {endpoint.model} en {endpoint.base_url}.",
        )
        try:
            crew = build_crew(settings)
            crew_stdout_path = settings.logs_dir / f"crew_stdout_{run_id}.log"
            crew_stdout_path.parent.mkdir(parents=True, exist_ok=True)
            with crew_stdout_path.open("w", encoding="utf-8") as crew_stdout:
                logging.disable(logging.INFO)
                try:
                    with redirect_stdout(crew_stdout), redirect_stderr(crew_stdout):
                        result = crew.kickoff(
                            inputs={
                                "universe": ", ".join(settings.universe),
                                "cycle_id": run_id,
                                "current_date": datetime.now(timezone.utc).date().isoformat(),
                                "market_snapshot": market_snapshot_prompt,
                                "market_state": market_state_prompt,
                                "technical_context": technical_context_prompt,
                                "deterministic_review_summary": (
                                    "Pendiente; la revision determinista se ejecuta antes de "
                                    "convertir recomendaciones en planes de orden."
                                ),
                            }
                        )
                finally:
                    logging.disable(logging.NOTSET)
            crew_result = str(result)
            reporter.emit(
                "orchestrator",
                "crew_completed",
                run_id,
                "CrewAI completo el ciclo de razonamiento.",
                {"result_preview": crew_result[:1000], "crew_stdout_path": str(crew_stdout_path)},
            )
        except Exception as exc:
            reporter.emit(
                "orchestrator",
                "crew_failed",
                run_id,
                f"CrewAI fallo: {exc}. Se continua con decision LLM directa para no perder el ciclo.",
                {"error": str(exc), "fallback": "direct_llm_decision"},
            )
    else:
        reporter.emit(
            "orchestrator",
            "crew_skipped",
            run_id,
            "CrewAI omitido por parametro --skip-crew. Solo se valido el flujo/logging.",
        )

    auto_result = None
    if use_crew:
        auto_result = _auto_paper_trade(settings, store, reporter, run_id, technical_context, market_snapshot, market_state)
    _record_trade_summary(settings, store, reporter, run_id, auto_result)
    reporter.emit(
        "orchestrator",
        "cycle_completed",
        run_id,
        "Ciclo finalizado. Estado persistido en SQLite y JSONL por agente.",
    )
    log_system_event(settings.logs_dir, "cycle_completed", {"cycle_id": run_id})
    return {
        "cycle_id": run_id,
        "crew_result": crew_result,
        "used_crew": use_crew,
        "market_state_path": (market_state or {}).get("path"),
        "market_state_quality": ((market_state or {}).get("data_quality") or {}).get("status"),
    }
