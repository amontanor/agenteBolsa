"""Observable operational cycle for the trading agent group."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .config import Settings
from .crew import build_crew
from .eventing import AgentPhase, EventReporter
from .logging_utils import log_system_event
from .market_calendar import MarketCalendar
from .models import Hypothesis, new_id
from .storage import Store
from .tools.backtest import build_symbol_backtest
from .tools.broker import BrokerClientFactory
from .tools.costs import TransactionCostModel
from .tools.execution import submit_paper_order_plan
from .tools.market_snapshot import build_market_snapshot, compact_snapshot_for_prompt
from .tools.portfolio_optimizer import build_portfolio_rebalance_context
from .tools.signal_learning import update_signal_decisions
from .tools.trade_decision import (
    build_order_plans,
    filter_entry_quality,
    load_latest_sentiment,
    load_latest_technical_candidates,
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
) -> list[Any]:
    if settings.max_daily_buy_orders <= 0:
        return plans

    used_buys = store.count_broker_orders(
        side="buy",
        since_iso=_session_start_utc_iso(settings),
    )
    remaining_buys = max(0, settings.max_daily_buy_orders - used_buys)
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
        reporter.emit(
            "risk_manager",
            "daily_buy_limit_applied",
            run_id,
            (
                "Compras bloqueadas por limite diario: "
                f"ya usadas {used_buys}/{settings.max_daily_buy_orders}; "
                f"bloqueadas: {', '.join(plan.symbol for plan in blocked)}."
            ),
            {
                "used_buy_orders_today": used_buys,
                "max_daily_buy_orders": settings.max_daily_buy_orders,
                "blocked_symbols": [plan.symbol for plan in blocked],
            },
        )
    return kept


def _backtest_gate_decision(settings: Settings, report: dict[str, Any]) -> tuple[bool, str]:
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
        except Exception as exc:  # noqa: BLE001 - missing validation should block buys, not crash cycle.
            decisions.append(
                {
                    "symbol": recommendation.symbol,
                    "approved": False,
                    "reason": f"backtest fallido: {exc}",
                    "error": repr(exc),
                }
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
                "failed": failed,
                "backtest_gate": auto_result.get("backtest_gate", []),
                "entry_quality_gate": auto_result.get("entry_quality_gate", []),
            },
        )
        return

    if auto_result:
        recommendations = auto_result.get("recommendations", [])
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
        reporter.emit(
            "execution_agent",
            "trade_execution_summary",
            run_id,
            message,
            {
                "auto_paper_trading": settings.auto_paper_trading,
                "require_human_approval": settings.require_human_approval,
                "recommendations": recommendations,
                "submitted": [],
                "failed": [],
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

    reporter.emit(
        "execution_agent",
        "paper_auto_trade_started",
        run_id,
        "Auto paper trading activo: solicitando decision LLM estructurada y planes de orden.",
        {"max_orders_per_cycle": settings.max_orders_per_cycle},
    )

    try:
        portfolio = BrokerClientFactory(settings).alpaca_portfolio_snapshot()
        decision_context = technical_context or load_latest_technical_candidates(
            settings.data_dir,
            per_side=max(1, settings.news_sentiment_top_n // 2),
        )
        sentiment_context = load_latest_sentiment(settings.data_dir)
        rebalance_context = build_portfolio_rebalance_context(
            settings,
            portfolio,
            decision_context,
            sentiment_context,
        )
        decision = request_trade_recommendations(
            settings,
            portfolio,
            decision_context,
            sentiment_context,
            rebalance_context,
        )
    except Exception as exc:  # noqa: BLE001 - bad LLM JSON or broker read must not stop scheduler.
        reporter.emit(
            "execution_agent",
            "paper_auto_trade_failed",
            run_id,
            f"No compra ni vende. Decision automatica fallida: {exc}",
            {"error": repr(exc)},
        )
        return {"submitted": [], "failed": [{"stage": "decision", "error": str(exc)}]}

    recommendations = decision["recommendations"]
    for recommendation in recommendations:
        store.save_trade_recommendation(
            recommendation_id=new_id("rec"),
            cycle_id=run_id,
            symbol=recommendation.symbol,
            action=recommendation.action,
            confidence=recommendation.confidence,
            payload=asdict(recommendation),
        )

    quality_recommendations, entry_quality_gate = _apply_entry_quality_gate(
        settings,
        reporter,
        run_id,
        recommendations,
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
        recommendations=recommendations,
        entry_quality_gate=entry_quality_gate,
        backtest_gate=backtest_gate,
    )
    if learned_decisions:
        reporter.emit(
            "self_improvement_engineer",
            "signal_learning_decisions_updated",
            run_id,
            f"Aprendizaje actualizado con {learned_decisions} decision(es) de senal.",
            {"source_run_id": decision_context.get("run_id"), "updated": learned_decisions},
        )
    plans = build_order_plans(settings, portfolio, gated_recommendations, dry_run=True)
    plans = _apply_daily_buy_limit(settings, store, reporter, run_id, plans)
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
        actions = ", ".join(
            f"{item.symbol}:{item.action}:{item.confidence:.2f}" for item in recommendations
        ) or "sin recomendaciones"
        reporter.emit(
            "execution_agent",
            "paper_auto_trade_completed",
            run_id,
            f"No compra ni vende. Recomendaciones sin plan aprobado: {actions}.",
            {
                "recommendations": [asdict(item) for item in recommendations],
                "entry_quality_gate": entry_quality_gate,
                "backtest_gate": backtest_gate,
                "rebalance_context": rebalance_context,
                "submitted": [],
            },
        )
        return {
            "submitted": [],
            "failed": [],
            "recommendations": [asdict(item) for item in recommendations],
            "entry_quality_gate": entry_quality_gate,
            "backtest_gate": backtest_gate,
        }

    submitted = []
    failed = []
    pending_current = store.pending_order_plans(cycle_id=run_id, limit=settings.max_orders_per_cycle)
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
    reporter.emit(
        "execution_agent",
        "paper_auto_trade_completed",
        run_id,
        f"Ordenes paper enviadas. compras: {buy_text}; ventas: {sell_text}.{fail_text}",
        {
            "submitted": submitted,
            "failed": failed,
            "entry_quality_gate": entry_quality_gate,
            "backtest_gate": backtest_gate,
        },
    )
    return {
        "submitted": submitted,
        "failed": failed,
        "entry_quality_gate": entry_quality_gate,
        "backtest_gate": backtest_gate,
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
    technical_context_prompt = json.dumps(technical_context or {}, ensure_ascii=True)
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
        )
        market_snapshot_prompt = compact_snapshot_for_prompt(market_snapshot)
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

    crew_result: str | None = None
    if use_crew:
        reporter.emit(
            "orchestrator",
            "crew_started",
            run_id,
            f"Lanzando CrewAI contra {settings.openai_model} en {settings.openai_api_base}.",
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
                            "technical_context": technical_context_prompt,
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
                f"CrewAI fallo: {exc}",
                {"error": str(exc)},
            )
            raise
    else:
        reporter.emit(
            "orchestrator",
            "crew_skipped",
            run_id,
            "CrewAI omitido por parametro --skip-crew. Solo se valido el flujo/logging.",
        )

    auto_result = None
    if use_crew:
        auto_result = _auto_paper_trade(settings, store, reporter, run_id, technical_context)
    _record_trade_summary(settings, store, reporter, run_id, auto_result)
    reporter.emit(
        "orchestrator",
        "cycle_completed",
        run_id,
        "Ciclo finalizado. Estado persistido en SQLite y JSONL por agente.",
    )
    log_system_event(settings.logs_dir, "cycle_completed", {"cycle_id": run_id})
    return {"cycle_id": run_id, "crew_result": crew_result, "used_crew": use_crew}
