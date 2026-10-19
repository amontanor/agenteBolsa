"""Observable operational cycle for the trading agent group."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from collections.abc import Mapping
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from . import __version__
from .agent_run import AgentRunTracker
from .config import Settings
from .crew import build_crew, build_crew_task_manifest
from .crew_observer import CrewTaskObserver
from .crewai_context import crew_execution_context
from .eventing import AgentPhase, EventReporter
from .llm_router import (
    build_llm_identity,
    configured_llm_endpoints,
    select_preferred_endpoint,
    unavailable_llm_identity,
)
from .logging_utils import log_system_event
from .market_calendar import MarketCalendar
from .models import Hypothesis, new_id
from .storage import Store
from .tools.adversarial_reviewer import review_recommendations_adversarial
from .tools.backtest import build_symbol_backtest
from .tools.broker import BrokerClientFactory
from .tools.canonical_selection_ledger import (
    build_canonical_selection_ledger,
    persist_canonical_selection_ledger,
)
from .tools.capital_allocation_policy import load_capital_allocation_policy
from .tools.capital_allocation_shadow import (
    build_capital_allocation_shadow,
    persist_capital_allocation_shadow,
)
from .tools.capital_deployment_funnel_shadow import (
    account_projection_from_portfolio_snapshot,
    build_capital_deployment_funnel_shadow,
    persist_capital_deployment_funnel_shadow,
    unavailable_capital_deployment_funnel,
)
from .tools.comparable_controls import (
    build_comparable_control_sets,
    build_unavailable_control_set,
    copy_comparable_control_set,
)
from .tools.costs import TransactionCostModel
from .tools.data_quality_decision_shadow import (
    capture_data_quality_phase_a,
    finalize_data_quality_phase_b,
    persist_data_quality_decision_shadow,
)
from .tools.decision_context import build_decision_context_snapshot, copy_snapshot
from .tools.decision_lineage import build_decision_lineage
from .tools.deterministic_reviewer import recommendation_input_fingerprint, review_recommendations
from .tools.execution import submit_paper_order_plan
from .tools.gate_evaluation import collect_gate_path, gate_identity_key
from .tools.h_capture import build_prediction_capture, persist_h_capture_event
from .tools.learning_mode import (
    LEARNING_EXPERIMENT_SOURCE,
    LOW_SAMPLE_EXPLORATION_TAG,
    active_learning_mode,
    is_strategy_shadow_paused,
)
from .tools.learning_penalty_cycle_shadow import (
    finalize_learning_penalty_cycle_shadow,
    persist_learning_penalty_cycle_shadow,
)
from .tools.market_cycle_timing import MarketCycleTiming, optional_measure
from .tools.market_snapshot import build_market_snapshot, compact_snapshot_for_prompt
from .tools.market_state import build_market_state, compact_market_state_for_prompt
from .tools.operational_health import load_operational_block_context
from .tools.portfolio_optimizer import build_portfolio_rebalance_context
from .tools.signal_identity import resolve_signal_capture
from .tools.signal_learning import (
    attach_comparable_control_sets,
    attach_gate_evaluation_snapshots,
    update_signal_decisions,
    update_signal_execution_status,
)
from .tools.trade_decision import (
    _compact_technical_context_for_prompt,
    _construct_min_reward_risk,
    _effective_buy_plan_limit,
    _effective_daily_buy_limit,
    _effective_trade_recommendation_limit,
    augment_recommendations_with_deterministic_fallback,
    build_order_plans,
    deterministic_trade_fallback_recommendations,
    filter_entry_quality,
    load_daily_learning_context,
    load_latest_sentiment,
    load_latest_technical_candidates,
    load_operational_response_context,
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


def _market_session_date(settings: Settings, now: datetime | None = None) -> str:
    reference = now or datetime.now(timezone.utc)
    return reference.astimezone(ZoneInfo(settings.local_timezone)).date().isoformat()


def _low_sample_runtime_key(session_date: str) -> str:
    return f"learning_mode_low_sample_usage:{session_date}"


def _low_sample_usage_payload(store: Store, settings: Settings, *, now: datetime | None = None) -> dict[str, Any]:
    learning_mode = active_learning_mode(settings) or {}
    session_date = _market_session_date(settings, now=now)
    quota = max(0, int(learning_mode.get("low_sample_daily_quota") or 0))
    payload = store.get_runtime_value(_low_sample_runtime_key(session_date)) or {}
    orders = list(payload.get("orders") or []) if isinstance(payload, dict) else []
    used = len(orders)
    return {
        "session_date": session_date,
        "quota": quota,
        "used": used,
        "remaining": max(0, quota - used),
        "enabled": quota > 0,
        "orders": orders,
    }


def _register_low_sample_order(
    store: Store,
    settings: Settings,
    *,
    run_id: str,
    plan_id: str,
    symbol: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    usage = _low_sample_usage_payload(store, settings, now=now)
    order_entry = {
        "run_id": run_id,
        "plan_id": plan_id,
        "symbol": str(symbol).upper(),
        "recorded_at": (now or datetime.now(timezone.utc)).isoformat(),
    }
    updated_orders = [*list(usage.get("orders") or []), order_entry]
    payload = {
        "session_date": usage["session_date"],
        "quota": usage["quota"],
        "orders": updated_orders,
    }
    store.set_runtime_value(_low_sample_runtime_key(usage["session_date"]), payload)
    return {
        **usage,
        "used": len(updated_orders),
        "remaining": max(0, int(usage["quota"]) - len(updated_orders)),
        "orders": updated_orders,
    }


def _rejection_payload_for_plan(plan: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Attach exact recommendation lineage to a post-plan rejection."""

    row = dict(payload)
    recommendation = getattr(plan, "recommendation", None)
    lineage = dict(getattr(recommendation, "decision_lineage", {}) or {})
    for key in ("candidate_id", "signal_id", "cycle_id"):
        value = str(lineage.get(key) or "").strip()
        if value:
            row[key] = value
    return row


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
        # Preserve legacy zero-budget behavior except a fail-closed allocation
        # policy: already materialized BUY plans must not bypass its block.
        if load_capital_allocation_policy(settings.data_dir, settings).get("status") != "blocked":
            return plans
        used_buys = 0
    else:
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
                    _rejection_payload_for_plan(plan, {
                        "symbol": plan.symbol,
                        "action": str(getattr(plan, "side", "")).lower(),
                        "stage": "daily_buy_limit",
                        "reason": "max_daily_buy_orders_reached",
                        "checks": {
                            "used_buy_orders_today": used_buys,
                            "max_daily_buy_orders": settings.max_daily_buy_orders,
                            "effective_max_daily_buy_orders": daily_buy_limit,
                        },
                    })
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


def _learning_mode_backtest_near_miss(settings: Settings, report: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    learning_mode = active_learning_mode(settings)
    if not learning_mode:
        return False, {}
    metrics = report.get("metrics", {}) or {}
    benchmark = ((report.get("benchmark") or {}).get("metrics")) or {}
    trades = int(metrics.get("trades") or 0)
    hit_rate = float(metrics.get("hit_rate") or 0.0)
    profit_factor = metrics.get("profit_factor")
    profit_factor_value = None if profit_factor is None else float(profit_factor)
    trade_window_alpha = benchmark.get("trade_window_alpha")
    alpha_vs_benchmark = benchmark.get("alpha_vs_benchmark")
    alpha_value = trade_window_alpha if trade_window_alpha is not None else alpha_vs_benchmark
    negative_regimes = 0
    for bucket in (report.get("regime_summary") or {}).values():
        bucket_trades = int(bucket.get("trades") or 0)
        bucket_avg = bucket.get("avg_return")
        if (
            bucket_trades >= int(settings.backtest_gate_min_regime_trades or 0)
            and bucket_avg is not None
            and float(bucket_avg) < 0
        ):
            negative_regimes += 1
    if trades < 8:
        return False, {"clear_reject": "trades_lt_8"}
    if profit_factor_value is None or profit_factor_value < 0.90:
        return False, {"clear_reject": "profit_factor_lt_0_90"}
    if alpha_value is not None and float(alpha_value) < -0.01:
        return False, {"clear_reject": "alpha_very_negative"}
    approved = (
        hit_rate >= (float(settings.backtest_gate_min_hit_rate) - 0.03)
        and (profit_factor_value is not None and profit_factor_value >= 0.95)
        and negative_regimes <= 2
        and (alpha_value is None or float(alpha_value) >= -0.005)
    )
    return approved, {
        "mode": "learning_near_miss",
        "trades": trades,
        "hit_rate": hit_rate,
        "profit_factor": profit_factor_value,
        "alpha_value": alpha_value,
        "negative_regimes": negative_regimes,
    }


def _learning_mode_backtest_low_sample(
    settings: Settings,
    store: Store,
    report: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    learning_mode = active_learning_mode(settings)
    if not learning_mode:
        return False, {}
    quota = max(0, int(learning_mode.get("low_sample_daily_quota") or 0))
    if quota <= 0:
        return False, {
            "clear_reject": "low_sample_daily_quota_disabled",
            "reason": "low_sample desactivado: quota diaria = 0",
        }

    metrics = report.get("metrics", {}) or {}
    benchmark = ((report.get("benchmark") or {}).get("metrics")) or {}
    trades = int(metrics.get("trades") or 0)
    hit_rate = float(metrics.get("hit_rate") or 0.0)
    profit_factor = metrics.get("profit_factor")
    profit_factor_value = None if profit_factor is None else float(profit_factor)
    trade_window_alpha = benchmark.get("trade_window_alpha")
    alpha_vs_benchmark = benchmark.get("alpha_vs_benchmark")
    alpha_value = trade_window_alpha if trade_window_alpha is not None else alpha_vs_benchmark
    negative_regimes = 0
    for bucket in (report.get("regime_summary") or {}).values():
        bucket_trades = int(bucket.get("trades") or 0)
        bucket_avg = bucket.get("avg_return")
        if (
            bucket_trades >= int(settings.backtest_gate_min_regime_trades or 0)
            and bucket_avg is not None
            and float(bucket_avg) < 0
        ):
            negative_regimes += 1
    if trades >= settings.backtest_gate_min_trades:
        return False, {"clear_reject": "trades_not_low_sample", "reason": "no es caso low-sample"}
    if hit_rate < (float(settings.backtest_gate_min_hit_rate) - 0.03):
        return False, {
            "clear_reject": "hit_rate_outside_near_miss",
            "reason": (
                f"hit-rate {hit_rate:.2%} fuera de near-miss "
                f"({float(settings.backtest_gate_min_hit_rate) - 0.03:.2%})"
            ),
        }
    if profit_factor_value is None or profit_factor_value < 0.95:
        return False, {
            "clear_reject": "profit_factor_outside_near_miss",
            "reason": f"profit-factor {profit_factor_value} fuera de near-miss 0.95",
        }
    if alpha_value is not None and float(alpha_value) < -0.005:
        return False, {
            "clear_reject": "alpha_outside_near_miss",
            "reason": f"alpha {float(alpha_value):.2%} fuera de near-miss -0.50%",
        }
    if negative_regimes > 2:
        return False, {
            "clear_reject": "negative_regimes_outside_near_miss",
            "reason": f"regimenes negativos {negative_regimes} > maximo near-miss 2",
        }

    usage = _low_sample_usage_payload(store, settings)
    if int(usage["used"]) >= quota:
        return False, {
            "clear_reject": "low_sample_daily_quota_exhausted",
            "reason": f"low_sample agotado hoy: {int(usage['used'])}/{quota} usado(s)",
            "low_sample_usage": usage,
        }
    return True, {
        "mode": "learning_low_sample_exception",
        "trades": trades,
        "min_trades": int(settings.backtest_gate_min_trades),
        "hit_rate": hit_rate,
        "profit_factor": profit_factor_value,
        "alpha_value": alpha_value,
        "negative_regimes": negative_regimes,
        "low_sample_usage": usage,
        "message": (
            "aprobada por excepcion low-sample (cupo 1/dia): "
            f"trades {trades} < {int(settings.backtest_gate_min_trades)}, "
            "resto de metricas dentro de near-miss/umbral"
        ),
    }


def _strategy_name_from_recommendation(recommendation: Any) -> str | None:
    explicit = str(getattr(recommendation, "strategy_name", "") or "").strip()
    if explicit:
        return explicit
    for tag in list(getattr(recommendation, "tags", []) or []):
        text = str(tag or "")
        if text.startswith("strategy:"):
            value = text.removeprefix("strategy:").strip()
            return value or None
    return None


def _annotate_recommendations_with_strategy(
    recommendations: list[Any],
    technical_context: dict[str, Any],
) -> list[Any]:
    """Conserva la estrategia seleccionada hasta el plan y la orden.

    El LLM decide por simbolo; el tag inmutable evita que la atribucion de una
    estrategia pausada dependa de reconstruir el contexto despues del ciclo.
    """
    by_symbol: dict[str, str] = {}
    for bucket in ("selected_candidates", "top_longs", "all_candidates"):
        for candidate in list((technical_context or {}).get(bucket) or []):
            if not isinstance(candidate, dict):
                continue
            symbol = str(candidate.get("symbol") or "").upper().strip()
            strategy = str(candidate.get("strategy_name") or "").strip()
            if symbol and strategy and symbol not in by_symbol:
                by_symbol[symbol] = strategy

    tagged: list[Any] = []
    for recommendation in recommendations:
        strategy = by_symbol.get(str(getattr(recommendation, "symbol", "") or "").upper().strip())
        if not strategy or _strategy_name_from_recommendation(recommendation):
            tagged.append(recommendation)
            continue
        tags = [*list(getattr(recommendation, "tags", []) or []), f"strategy:{strategy}"]
        tagged.append(replace(recommendation, strategy_name=strategy, tags=tags))
    return tagged


def _annotate_recommendations_with_lineage(
    recommendations: list[Any],
    technical_context: dict[str, Any],
    *,
    cycle_id: str,
    default_cohort: str | None,
) -> list[Any]:
    policy_version = f"agente_bolsa:{__version__}:trade_decision.v2"
    return [
        replace(
            recommendation,
            decision_lineage=build_decision_lineage(
                recommendation,
                technical_context,
                cycle_id=cycle_id,
                policy_version=policy_version,
                default_cohort=default_cohort,
                source_run_id=(technical_context or {}).get("run_id"),
            ),
        )
        for recommendation in recommendations
    ]


def _decision_context_snapshot_for_recommendation(
    store: Store,
    recommendation: Any,
    *,
    cycle_id: str,
    source_run_id: str | None,
    market_state: dict[str, Any] | None,
    agent_run_id: str | None,
    fallback_error: Any = None,
    llm_model: str | None = None,
    llm_identity: dict[str, Any] | None = None,
    identity_key: str | None = None,
) -> dict[str, Any]:
    identity = dict(llm_identity or {})
    lineage = dict(getattr(recommendation, "decision_lineage", {}) or {})
    signal_id = str(lineage.get("signal_id") or "").strip() or None
    signal_capture_id = str(lineage.get("signal_capture_id") or "").strip() or None
    signal_link_status = "unavailable"
    if signal_id:
        signal_source_run_id = str(lineage.get("signal_source_run_id") or "").strip() or None
        if signal_capture_id:
            resolved = resolve_signal_capture(store, signal_capture_id, signal_id=signal_id)
            if (
                resolved.get("status") == "exact_match"
                and resolved.get("signal_id") == signal_id
                and resolved.get("signal_source_run_id") == signal_source_run_id
            ):
                signal_link_status = "verified"
            else:
                signal_link_status = "broken"
        else:
            signal = store.signal_outcome_by_id(signal_id)
            # Legacy rows retain the previous exact signal/source check.
            if signal and signal_source_run_id and signal.get("source_run_id") == signal_source_run_id:
                signal_link_status = "verified"
            else:
                signal_link_status = "broken"
    raw = str(getattr(recommendation, "source", "") or "")
    origin = str(getattr(recommendation, "decision_origin", "") or "")
    capacity_code = str(getattr(recommendation, "capacity_fill_reason_code", "") or "").lower()
    raw_lower = f"{raw} {origin}".lower()
    llm_considered = None
    llm_status = None
    if raw_lower.strip() == "llm" or raw_lower.startswith("llm "):
        llm_considered, llm_status = True, "ok"
    elif "capacity_fill" in raw_lower:
        if "llm_ok" in capacity_code or "tras_llm" in capacity_code:
            llm_considered, llm_status = True, "ok"
        elif "fallo_llm" in capacity_code:
            llm_considered, llm_status = True, "failed"
        else:
            llm_status = "unavailable"
    elif "fallback" in raw_lower:
        llm_considered = True
        llm_status = "failed" if fallback_error or "fallo_llm" in raw_lower else "ok"
    elif "hold_override" in raw_lower:
        llm_status = "unavailable"
    elif "deterministic" in raw_lower:
        llm_considered, llm_status = False, "unavailable"
    llm_selected = getattr(recommendation, "llm_selected", None)
    snapshot = build_decision_context_snapshot(
        recommendation,
        cycle_id=cycle_id,
        source_run_id=source_run_id,
        market_state=market_state,
        agent_run_id=agent_run_id,
        signal_id=signal_id,
        signal_capture_id=signal_capture_id,
        signal_link_status=signal_link_status,
        llm_considered=llm_considered,
        llm_selected=llm_selected,
        llm_response_status=llm_status,
        llm_model=identity.get("effective_model") or llm_model,
        llm_provider=identity.get("provider"),
        llm_requested_model=identity.get("requested_model"),
        llm_effective_model=identity.get("effective_model") or llm_model,
        llm_fallback_used=identity.get("fallback_used"),
        fallback_reason=fallback_error,
        identity_key=identity_key,
    )
    if signal_id and signal_link_status == "verified":
        store.attach_decision_context_snapshot(signal_id, snapshot)
    return copy_snapshot(snapshot)


def _explicit_recommendation_prediction(recommendation: Any, snapshot: dict[str, Any]) -> dict[str, Any] | None:
    value = getattr(recommendation, "prospective_prediction", None)
    if isinstance(value, dict):
        return dict(value)
    value = snapshot.get("prospective_prediction") if isinstance(snapshot, dict) else None
    return dict(value) if isinstance(value, dict) else None


def _candidate_id_for_recommendation(
    technical_context: dict[str, Any] | None,
    *,
    lineage: Mapping[str, Any],
) -> str | None:
    expected_signal_id = str(lineage.get("signal_id") or "").strip()
    expected_capture_id = str(lineage.get("signal_capture_id") or "").strip()
    expected_source_run_id = str(lineage.get("signal_source_run_id") or "").strip()
    expected_candidate_id = str(lineage.get("candidate_id") or "").strip()
    if not expected_signal_id or not expected_capture_id or not expected_source_run_id:
        return None

    candidate_records: set[tuple[str, str, str, str]] = set()
    candidates_by_id: dict[str, set[tuple[str, str, str]]] = {}
    for bucket in ("selected_candidates", "top_longs", "top_shorts", "all_candidates"):
        for candidate in list((technical_context or {}).get(bucket) or []):
            if not isinstance(candidate, dict):
                continue
            candidate_id = str(candidate.get("candidate_id") or "").strip()
            identity = (
                str(candidate.get("signal_id") or "").strip(),
                str(candidate.get("signal_capture_id") or "").strip(),
                str(candidate.get("signal_source_run_id") or "").strip(),
            )
            candidate_records.add((candidate_id, *identity))
            if candidate_id:
                candidates_by_id.setdefault(candidate_id, set()).add(identity)

    expected_identity = (expected_signal_id, expected_capture_id, expected_source_run_id)
    if expected_candidate_id:
        identities = candidates_by_id.get(expected_candidate_id, set())
        if len(identities) != 1 or next(iter(identities)) != expected_identity:
            return None
        return expected_candidate_id

    matching_records = [
        record for record in candidate_records
        if record[1:] == expected_identity
    ]
    if any(len(candidates_by_id.get(record[0], set())) != 1 for record in matching_records if record[0]):
        return None
    return matching_records[0][0] if len(matching_records) == 1 and matching_records[0][0] else None


def _persist_decision_prediction_capture(
    store: Store,
    *,
    recommendation: Any,
    snapshot: dict[str, Any],
    technical_context: dict[str, Any] | None,
    cycle_id: str,
    agent_run_id: str | None,
) -> None:
    try:
        lineage = dict(getattr(recommendation, "decision_lineage", {}) or {})
        prediction = _explicit_recommendation_prediction(recommendation, snapshot)
        payload = build_prediction_capture(
            lineage={
                "cycle_id": cycle_id,
                "agent_run_id": agent_run_id,
                "agent_name": "trade_decision_agent" if agent_run_id else None,
                "signal_id": lineage.get("signal_id"),
                "signal_capture_id": lineage.get("signal_capture_id"),
                "signal_source_run_id": lineage.get("signal_source_run_id"),
                "candidate_id": _candidate_id_for_recommendation(
                    technical_context,
                    lineage=lineage,
                ),
                "source_event_id": prediction.get("source_event_id") if prediction else None,
                "source_event_content_hash": (
                    prediction.get("source_event_content_hash") or prediction.get("source_content_hash")
                    if prediction
                    else None
                ),
            },
            prediction=prediction,
            capture_observed_at=snapshot.get("captured_at"),
            producer_stage="decision",
            calendar_name="XNYS",
        )
        persist_h_capture_event(store, payload)
    except Exception:  # noqa: BLE001 - shadow observation cannot change execution.
        logging.getLogger(__name__).exception("No se pudo persistir captura prospectiva de decisión")


def _separate_strategy_paused_plans(
    learning_mode: dict[str, Any] | None,
    plans: list[Any],
) -> tuple[list[Any], list[tuple[Any, str]]]:
    """Separa planes pausados antes de persistirlos o enviarlos al broker."""
    executable: list[Any] = []
    shadow: list[tuple[Any, str]] = []
    for plan in plans:
        strategy = _strategy_name_from_recommendation(getattr(plan, "recommendation", None))
        if is_strategy_shadow_paused(learning_mode, strategy):
            shadow.append((plan, str(strategy)))
        else:
            executable.append(plan)
    return executable, shadow


def _write_json_atomic(path: Any, payload: dict[str, Any]) -> None:
    target = path
    temporary = target.with_name(f".{target.name}.{new_id('tmp')}")
    try:
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def _write_learning_mode_shadow_report(
    settings: Settings,
    *,
    run_id: str,
    recommendations: list[Any],
    plans: list[Any],
    rejected: list[dict[str, Any]],
    paused_strategies: list[str] | None = None,
    operational_kill_switch: dict[str, Any] | None = None,
) -> str:
    local_day = datetime.now(ZoneInfo(settings.local_timezone)).date().isoformat()
    reports_dir = settings.data_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"learning_mode_shadow_{local_day}.json"
    gate_by_symbol = {
        str(item.get("symbol") or "").upper(): item
        for item in rejected
        if str(item.get("symbol") or "").strip()
    }
    paused = {str(item).strip().lower() for item in paused_strategies or [] if str(item).strip()}

    def _would_buy(plan: Any) -> dict[str, Any]:
        strategy_name = _strategy_name_from_recommendation(plan.recommendation) or (
            ((gate_by_symbol.get(plan.symbol) or {}).get("checks") or {}).get("strategy_name")
        )
        strategy_paused = str(strategy_name or "").strip().lower() in paused
        return {
            "symbol": plan.symbol,
            "notional": plan.notional,
            "entry_price": plan.entry_price,
            "stop_loss": plan.stop_loss,
            "take_profit": plan.take_profit,
            "reason": plan.recommendation.reason,
            "source": plan.recommendation.source,
            "strategy_name": strategy_name,
            "shadow_reason": "strategy_paused" if strategy_paused else "shadow_first",
            "backtest_soft_override": bool(plan.backtest_soft_override),
            "micro_experiment": bool(plan.micro_experiment),
        }

    payload = {
        "run_id": run_id,
        "session_date": local_day,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "strategy_pause" if paused else "shadow_first",
        "cohort": LEARNING_EXPERIMENT_SOURCE,
        "paused_strategies": sorted(paused),
        "operational_kill_switch": operational_kill_switch or {},
        "would_buy": [_would_buy(plan) for plan in plans if str(plan.side).lower() == "buy"],
        "rejected": rejected,
        "recommendations": [asdict(item) for item in recommendations],
    }
    _write_json_atomic(path, payload)
    latest_path = reports_dir / "latest_learning_mode_shadow.json"
    _write_json_atomic(latest_path, payload)
    return str(path)


def _apply_backtest_gate(
    settings: Settings,
    store: Store,
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
            else:
                low_sample_ok, low_sample_checks = _learning_mode_backtest_low_sample(settings, store, report)
                if low_sample_ok:
                    decisions[-1] = {
                        "symbol": recommendation.symbol,
                        "approved": True,
                        "reason": str(low_sample_checks.get("message") or LOW_SAMPLE_EXPLORATION_TAG),
                        "path": report.get("path"),
                        "metrics": metrics,
                        "checks": low_sample_checks,
                    }
                    kept.append(
                        replace(
                            recommendation,
                            micro_experiment=True,
                            backtest_soft_override=True,
                            soft_override_reasons=[
                                *list(getattr(recommendation, "soft_override_reasons", []) or []),
                                LOW_SAMPLE_EXPLORATION_TAG,
                            ],
                            cohort=LEARNING_EXPERIMENT_SOURCE,
                            tags=[
                                *list(getattr(recommendation, "tags", []) or []),
                                LOW_SAMPLE_EXPLORATION_TAG,
                            ],
                        )
                    )
                    continue
                if low_sample_checks.get("reason"):
                    decisions[-1]["reason"] = str(low_sample_checks["reason"])
                    decisions[-1]["checks"] = low_sample_checks
            near_miss_ok, near_miss_checks = _learning_mode_backtest_near_miss(settings, report)
            if near_miss_ok:
                decisions[-1] = {
                    "symbol": recommendation.symbol,
                    "approved": True,
                    "reason": "learning_near_miss",
                    "path": report.get("path"),
                    "metrics": metrics,
                    "checks": near_miss_checks,
                }
                kept.append(
                    replace(
                        recommendation,
                        micro_experiment=True,
                        backtest_soft_override=True,
                        soft_override_reasons=[
                            *list(getattr(recommendation, "soft_override_reasons", []) or []),
                            "learning_near_miss",
                        ],
                        cohort=LEARNING_EXPERIMENT_SOURCE,
                    )
                )
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


def _apply_low_sample_daily_quota(
    settings: Settings,
    store: Store,
    reporter: EventReporter,
    run_id: str,
    plans: list[Any],
    *,
    rejected: list[dict[str, Any]] | None = None,
) -> list[Any]:
    usage = _low_sample_usage_payload(store, settings)
    remaining = int(usage.get("remaining") or 0)
    if not plans:
        return plans
    kept = []
    blocked = []
    for plan in plans:
        recommendation_tags = list(getattr(getattr(plan, "recommendation", None), "tags", []) or [])
        is_low_sample = LOW_SAMPLE_EXPLORATION_TAG in recommendation_tags
        if not is_low_sample or str(getattr(plan, "side", "")).lower() != "buy":
            kept.append(plan)
            continue
        if remaining > 0:
            kept.append(plan)
            remaining -= 1
        else:
            blocked.append(plan)
    if blocked:
        for plan in blocked:
            if rejected is not None:
                rejected.append(
                    _rejection_payload_for_plan(plan, {
                        "symbol": plan.symbol,
                        "action": str(getattr(plan, "side", "")).lower(),
                        "stage": "low_sample_daily_quota",
                        "reason": "low_sample_daily_quota_exhausted",
                        "checks": {
                            "used_low_sample_orders_today": usage.get("used"),
                            "low_sample_daily_quota": usage.get("quota"),
                        },
                    })
                )
        reporter.emit(
            "risk_manager",
            "low_sample_daily_quota_applied",
            run_id,
            (
                "Excepcion low-sample agotada hoy: "
                f"{usage.get('used')}/{usage.get('quota')} ya usadas; "
                f"bloqueadas: {', '.join(plan.symbol for plan in blocked)}."
            ),
            {
                "usage": usage,
                "blocked_symbols": [plan.symbol for plan in blocked],
            },
        )
    return kept


def _apply_entry_quality_gate(
    settings: Settings,
    reporter: EventReporter,
    run_id: str,
    recommendations: list[Any],
    technical_context: dict[str, Any] | None,
    sentiment_context: dict[str, Any] | None,
    *,
    learning_mode_config: dict[str, Any] | None = None,
    daily_learning_digest: dict[str, Any] | None = None,
    operational_response_context: dict[str, Any] | None = None,
) -> tuple[list[Any], list[dict[str, Any]]]:
    kept, decisions = filter_entry_quality(
        settings,
        recommendations,
        technical_context,
        sentiment_context,
        learning_mode_config=learning_mode_config,
        daily_learning_digest=daily_learning_digest,
        operational_response_context=operational_response_context,
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


def _persist_learning_penalty_cycle_shadow_final(
    *,
    store: Store,
    reporter: EventReporter,
    phase_a: dict[str, Any] | None,
    run_id: str,
    recommendations: list[Any],
    plans: list[Any],
    comparable_control_sets: dict[str, dict[str, Any]],
    rejected_order_plans: list[dict[str, Any]],
    gate_snapshots: dict[str, dict[str, Any]] | None = None,
    phase_b_available: bool = True,
) -> dict[str, Any] | None:
    """Finalize and persist exactly one post-selection event, fail-open."""
    if not isinstance(phase_a, dict):
        return None

    try:
        final = finalize_learning_penalty_cycle_shadow(
            phase_a,
            recommendations=recommendations,
            plans=plans,
            comparable_control_sets=comparable_control_sets,
            rejected_order_plans=rejected_order_plans,
            gate_snapshots=gate_snapshots,
            cycle_id=run_id,
            phase_b_available=phase_b_available,
        )
        persisted = persist_learning_penalty_cycle_shadow(store, final)
        reporter.emit(
            "self_improvement_engineer",
            "learning_penalty_cycle_shadow",
            run_id,
            "Shadow de penalizacion final capturado tras selecciones, planes y controles reales.",
            {
                "status": final.get("status"),
                "candidate_counts": final.get("candidate_counts"),
                "persist_status": persisted.get("status"),
                "policy_mode": "shadow_only",
                "phase": final.get("phase"),
            },
        )
        return final
    except Exception as exc:  # noqa: BLE001 - observabilidad fail-open.
        reporter.emit(
            "self_improvement_engineer",
            "learning_penalty_cycle_shadow_failed",
            run_id,
            "No se pudo persistir el shadow final; el ciclo activo continua sin cambios.",
            {"error": repr(exc), "policy_mode": "shadow_only", "phase": "post_selection"},
        )
        return None


def _capture_data_quality_decision_shadow(
    *,
    run_id: str,
    market_snapshot: dict[str, Any] | None,
    market_state: dict[str, Any] | None,
    technical_context: dict[str, Any] | None,
    reporter: EventReporter,
) -> dict[str, Any] | None:
    """Capture Phase A without becoming an argument to active decisions."""

    try:
        phase_a = capture_data_quality_phase_a(
            cycle_id=run_id,
            market_snapshot=market_snapshot,
            market_state=market_state,
            technical_context=technical_context,
            candidates=(technical_context or {}).get("all_candidates") if isinstance(technical_context, dict) else None,
        )
        reporter.emit(
            "market_data_researcher",
            "data_quality_decision_shadow_phase_a",
            run_id,
            "Captura shadow de calidad realizada en memoria antes de la decision activa.",
            {
                "status": phase_a.get("status"),
                "denominators": phase_a.get("denominators"),
                "details_included": phase_a.get("details_included"),
                "details_omitted": phase_a.get("details_omitted"),
                "policy_mode": "shadow_only",
            },
        )
        return phase_a
    except Exception as exc:  # noqa: BLE001 - quality telemetry is fail-open.
        reporter.emit(
            "market_data_researcher",
            "data_quality_decision_shadow_unavailable",
            run_id,
            "No se pudo capturar el shadow de calidad; el ciclo activo continua.",
            {"error": repr(exc), "policy_mode": "shadow_only"},
        )
        return None


def _persist_data_quality_decision_shadow_final(
    *,
    store: Store,
    reporter: EventReporter,
    phase_a: dict[str, Any] | None,
    run_id: str,
    recommendations: list[Any] | None = None,
    plans: list[Any] | None = None,
    rejected_order_plans: list[dict[str, Any]] | None = None,
    orders: list[dict[str, Any]] | None = None,
    phase_b_available: bool = True,
) -> dict[str, Any] | None:
    """Seal/persist Phase B without retrying any active stage."""

    if not isinstance(phase_a, dict):
        return None
    try:
        final = finalize_data_quality_phase_b(
            phase_a,
            recommendations=recommendations or [],
            plans=plans or [],
            rejected_order_plans=rejected_order_plans or [],
            orders=orders or [],
            cycle_id=run_id,
            phase_b_available=phase_b_available,
        )
        persisted = persist_data_quality_decision_shadow(store, final)
        reporter.emit(
            "market_data_researcher",
            "data_quality_decision_shadow_final",
            run_id,
            "Shadow de calidad finalizado tras la ruta activa; sin autoridad sobre trading.",
            {
                "status": final.get("status"),
                "denominators": final.get("denominators"),
                "persist_status": persisted.get("status"),
                "policy_mode": "shadow_only",
            },
        )
        return final
    except Exception as exc:  # noqa: BLE001 - observability must not block the cycle.
        reporter.emit(
            "market_data_researcher",
            "data_quality_decision_shadow_failed",
            run_id,
            "No se pudo persistir el shadow final; el ciclo activo continua sin cambios.",
            {"error": repr(exc), "policy_mode": "shadow_only"},
        )
        return None


def _persist_selection_ledger_shadow(
    *,
    store: Store,
    reporter: EventReporter,
    phase_a: dict[str, Any] | None,
    run_id: str,
    recommendations: list[Any] | None = None,
    plans: list[Any] | None = None,
    plan_records: list[dict[str, Any]] | None = None,
    rejected_order_plans: list[dict[str, Any]] | None = None,
    ordered_records: list[dict[str, Any]] | None = None,
    failed_records: list[dict[str, Any]] | None = None,
    gate_snapshots: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Capture the exact cycle funnel once, without authority over trading."""

    tracker = AgentRunTracker(
        store,
        role="self_improvement_engineer",
        agent_name="self_improvement_engineer",
        task_name="canonical_selection_ledger_shadow",
        cycle_id=run_id,
        execution_kind="deterministic",
        input_refs=[run_id],
    )
    try:
        payload = build_canonical_selection_ledger(
            run_id,
            phase_a,
            recommendations=recommendations,
            plans=plans,
            plan_records=plan_records,
            rejected_order_plans=rejected_order_plans,
            ordered_records=ordered_records,
            failed_records=failed_records,
            gate_snapshots=gate_snapshots,
        )
        persisted = persist_canonical_selection_ledger(store, payload)
        reporter.emit(
            "self_improvement_engineer",
            "canonical_selection_ledger",
            run_id,
            "Ledger shadow de seleccion capturado despues de la ruta activa.",
            {
                "status": payload.get("status"),
                "persist_status": persisted.get("status"),
                "denominators": payload.get("denominators"),
                "policy_mode": "shadow_only",
            },
        )
        tracker.add_outputs(output_refs=[payload.get("event_id") or run_id])
        if payload.get("status") == "unavailable" or persisted.get("status") == "failed":
            tracker.fail(reason="canonical_selection_ledger_unavailable", error_code="shadow_unavailable")
        else:
            tracker.succeed()
        return {
            "status": payload.get("status"),
            "persist_status": persisted.get("status"),
            "event_id": payload.get("event_id"),
            "content_hash": payload.get("content_hash"),
            "denominators": payload.get("denominators"),
        }
    except Exception as exc:  # noqa: BLE001 - telemetry is fail-open by contract.
        tracker.fail(reason=exc, error_code="canonical_selection_ledger_failed")
        reporter.emit(
            "self_improvement_engineer",
            "canonical_selection_ledger_failed",
            run_id,
            "No se pudo capturar el ledger shadow; la ruta activa continua sin cambios.",
            {"error": repr(exc), "policy_mode": "shadow_only"},
        )
        return {
            "status": "unavailable",
            "persist_status": "failed",
            "event_id": f"canonical_selection_ledger:{run_id}",
            "error": repr(exc),
        }


def _persist_capital_deployment_funnel_shadow(
    *,
    store: Store,
    reporter: EventReporter,
    phase_a: dict[str, Any] | None,
    run_id: str,
    recommendations: list[Any] | None = None,
    gated_recommendations: list[Any] | None = None,
    plans: list[Any] | None = None,
    rejected_order_plans: list[dict[str, Any]] | None = None,
    submitted: list[dict[str, Any]] | None = None,
    account: dict[str, Any] | None = None,
    portfolio_snapshot: Any = None,
    allocation_settings: Settings | None = None,
    allocation_observations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Persist P-L54B after the active route; every failure is fail-open."""

    tracker = AgentRunTracker(
        store,
        role="risk_manager",
        agent_name="risk_manager",
        task_name="capital_deployment_funnel_shadow",
        cycle_id=run_id,
        execution_kind="deterministic",
        input_refs=[run_id],
    )
    try:
        if not str(run_id or "").strip():
            tracker.skip(reason="cycle_id_unavailable")
            return {
                "status": "unavailable",
                "persist_status": "skipped",
                "event_id": None,
                "error": "cycle_id_unavailable",
            }
        candidates = None
        if isinstance(phase_a, dict):
            candidates = phase_a.get("all_candidates", phase_a.get("ranked_candidates"))
        payload = build_capital_deployment_funnel_shadow(
            run_id,
            candidates,
            recommendations=recommendations,
            gated_recommendations=gated_recommendations,
            plans=plans,
            rejected_order_plans=rejected_order_plans,
            submitted=submitted,
            account=account,
        )
        persisted = persist_capital_deployment_funnel_shadow(store, payload)
        allocation_result = None
        # Separate event: never changes legacy funnel hashes, rows or authority.
        if allocation_settings is not None:
            try:
                policy = load_capital_allocation_policy(allocation_settings.data_dir, allocation_settings)
                allocation_shadow = build_capital_allocation_shadow(
                    cycle_id=run_id, policy=policy, portfolio=portfolio_snapshot,
                    recommendations=recommendations, plans=plans, funnel=payload,
                    allocation_observations=allocation_observations,
                )
                for row in allocation_shadow["details"]:
                    row["daily_risk_budget"] = {
                        "configured_pct": allocation_settings.risk_budget_max_new_risk_per_day_pct,
                        "enforcement": "enabled" if allocation_settings.risk_budget_enabled else "disabled",
                    }
                from .tools.capital_allocation_shadow import shadow_content_hash
                allocation_shadow["content_hash"] = shadow_content_hash(allocation_shadow)
                allocation_persisted = persist_capital_allocation_shadow(store, allocation_shadow)
                allocation_result = {"status": allocation_persisted.get("status"),
                                     "event_id": allocation_shadow["event_id"],
                                     "content_hash": allocation_shadow["content_hash"]}
            except Exception as shadow_exc:  # noqa: BLE001 - no shadow failure changes the active result.
                allocation_result = {"status": "unavailable", "error_type": type(shadow_exc).__name__}
                logging.getLogger(__name__).warning("capital_allocation_shadow unavailable: %s", type(shadow_exc).__name__)
        reporter.emit(
            "risk_manager",
            "capital_deployment_funnel_shadow",
            run_id,
            "Embudo de capital shadow capturado tras la ruta activa; sin autoridad sobre trading.",
            {
                "status": payload.get("status"),
                "persist_status": persisted.get("status"),
                "denominators": payload.get("denominators"),
                "policy_mode": "shadow_only",
            },
        )
        tracker.add_outputs(output_refs=[payload.get("event_id") or run_id])
        if payload.get("status") == "unavailable" or persisted.get("status") == "failed":
            tracker.fail(reason="capital_deployment_funnel_unavailable", error_code="shadow_unavailable")
        else:
            tracker.succeed()
        return {
            "status": payload.get("status"),
            "persist_status": persisted.get("status"),
            "event_id": payload.get("event_id"),
            "content_hash": payload.get("content_hash"),
            "denominators": payload.get("denominators"),
            "detail_total": payload.get("detail_total"),
            "detail_persisted": payload.get("detail_persisted"),
            "detail_omitted": payload.get("detail_omitted"),
            **({"allocation_shadow": allocation_result} if allocation_settings is not None else {}),
        }
    except Exception as exc:  # noqa: BLE001 - shadow telemetry cannot alter trading.
        tracker.fail(reason=exc, error_code="capital_deployment_funnel_failed")
        reporter.emit(
            "risk_manager",
            "capital_deployment_funnel_shadow_failed",
            run_id,
            "No se pudo persistir el embudo shadow; la ruta activa continua sin cambios.",
            {"error": repr(exc), "policy_mode": "shadow_only"},
        )
        unavailable = unavailable_capital_deployment_funnel(run_id, reason="persist_failed")
        return {
            "status": unavailable.get("status"),
            "persist_status": "failed",
            "event_id": unavailable.get("event_id"),
            "error": repr(exc),
        }


def _auto_paper_trade(
    settings: Settings,
    store: Store,
    reporter: EventReporter,
    run_id: str,
    technical_context: dict[str, Any] | None,
    market_snapshot: dict[str, Any] | None,
    market_state: dict[str, Any] | None,
    learning_penalty_shadow: dict[str, Any] | None = None,
    data_quality_shadow: dict[str, Any] | None = None,
    agent_run_id: str | None = None,
    timing: MarketCycleTiming | None = None,
    selection_ledger_phase_a: dict[str, Any] | None = None,
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
        return {
            "submitted": [],
            "failed": [],
            "blocked": "REQUIRE_HUMAN_APPROVAL",
            "selection_ledger": _persist_selection_ledger_shadow(
                store=store, reporter=reporter, phase_a=selection_ledger_phase_a, run_id=run_id
            ),
        }
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
        return {
            "submitted": [],
            "failed": [],
            "blocked": "paper_safety",
            "selection_ledger": _persist_selection_ledger_shadow(
                store=store, reporter=reporter, phase_a=selection_ledger_phase_a, run_id=run_id
            ),
        }
    learning_mode = active_learning_mode(settings)
    daily_learning_digest = load_daily_learning_context(settings.data_dir)
    operational_response_context = load_operational_response_context(settings.data_dir)
    learning_shadow_only = bool(learning_mode and learning_mode.get("shadow_first"))
    operational_kill_switch = load_operational_block_context(settings.data_dir)
    if (
        settings.operational_kill_switch_enabled
        and operational_kill_switch.get("block_buy_execution")
        and not learning_shadow_only
    ):
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
            "selection_ledger": _persist_selection_ledger_shadow(
                store=store, reporter=reporter, phase_a=selection_ledger_phase_a, run_id=run_id
            ),
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
        return {
            "submitted": [],
            "failed": [],
            "blocked": "market_closed",
            "selection_ledger": _persist_selection_ledger_shadow(
                store=store, reporter=reporter, phase_a=selection_ledger_phase_a, run_id=run_id
            ),
        }

    capital_account = None
    decision_run: AgentRunTracker | None = None
    decision_agent_run_id = agent_run_id
    decision_capture_agent_run_id: str | None = None
    try:
        portfolio = BrokerClientFactory(settings).alpaca_portfolio_snapshot()
        capital_account = account_projection_from_portfolio_snapshot(portfolio)
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
        decision_run = AgentRunTracker(
            store,
            role="trade_decision_agent",
            agent_name="trade_decision_agent",
            task_name="structured_trade_recommendations",
            cycle_id=run_id,
            execution_kind="llm",
            parent_run_id=agent_run_id,
            input_refs=[run_id, decision_context.get("run_id")],
        )
        try:
            with optional_measure(timing, "llm_decision", "structured_recommendations"):
                decision = request_trade_recommendations(
                    settings,
                    portfolio,
                    decision_context,
                    sentiment_context,
                    rebalance_context,
                    market_state,
                )
        except TimeoutError as exc:
            decision_run.timeout(reason=exc, error_code="structured_trade_recommendations_timeout")
            raise
        except Exception as exc:
            decision_run.fail(reason=exc, error_code="structured_trade_recommendations_failed")
            raise
        llm_identity = decision.get("llm_identity") or unavailable_llm_identity("identity_unavailable")
        decision_run.set_effective_identity(
            provider=llm_identity.get("provider"),
            model=llm_identity.get("effective_model") or llm_identity.get("requested_model"),
        )
        decision_run.add_outputs(
            output_refs=[run_id],
            llm_calls=1 if llm_identity.get("status") == "ok" else 0,
        )
        decision_run.succeed()
        decision_capture_agent_run_id = decision_run.agent_run_id
        if agent_run_id is not None:
            decision_agent_run_id = decision_run.agent_run_id
    except Exception as exc:  # noqa: BLE001 - bad LLM JSON or broker read must not stop scheduler.
        if settings.deterministic_trade_fallback_enabled and "portfolio" in locals() and "decision_context" in locals():
            fallback_recommendations = deterministic_trade_fallback_recommendations(
                settings,
                portfolio,
                decision_context,
                limit=locals().get("effective_recommendation_limit"),
                market_state=market_state,
                llm_failed=True,
                learning_mode_config=learning_mode,
                daily_learning_digest=daily_learning_digest,
                operational_response_context=operational_response_context,
            )
            fallback_run = AgentRunTracker(
                store,
                role="trade_decision_agent",
                agent_name="trade_decision_agent",
                task_name="deterministic_trade_fallback",
                cycle_id=run_id,
                execution_kind="fallback",
                parent_run_id=decision_run.agent_run_id if decision_run is not None else agent_run_id,
                retry_of=decision_run.agent_run_id if decision_run is not None else agent_run_id,
                input_refs=[run_id, decision_context.get("run_id")],
                fallback_reason=f"structured_trade_recommendations_failed:{type(exc).__name__}",
            )
            fallback_run.add_outputs(output_refs=[run_id])
            fallback_run.succeed()
            if agent_run_id is not None:
                decision_agent_run_id = fallback_run.agent_run_id
            decision_capture_agent_run_id = fallback_run.agent_run_id
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
                "llm_identity": unavailable_llm_identity("deterministic_trade_fallback"),
            }
        else:
            reporter.emit(
                "execution_agent",
                "paper_auto_trade_failed",
                run_id,
                f"No compra ni vende. Decision automatica fallida: {exc}",
                {"error": repr(exc)},
            )
            return {
                "submitted": [],
                "failed": [{"stage": "decision", "error": str(exc)}],
                "selection_ledger": _persist_selection_ledger_shadow(
                    store=store,
                    reporter=reporter,
                    phase_a=selection_ledger_phase_a,
                    run_id=run_id,
                ),
            }

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
                    f"{_cycle_shadow.get('candidates_total', 0)} finalistas / "
                    f"{_cycle_shadow.get('all_candidates_total', 0)} totales, "
                    f"setups con edge+ fuera del corte={_cycle_shadow.get('positive_edge_found', 0)}, "
                    f"edge_table={_cycle_shadow.get('edge_table_rows', 0)} filas, "
                    f"cambia_top={_cycle_shadow.get('changed')}."
                ),
                _cycle_shadow,
            )
    except Exception:  # noqa: BLE001 - la medicion shadow nunca corta el ciclo
        pass

    recommendations = decision["recommendations"]
    learning_mode = active_learning_mode(settings)
    # §1 (experimento paper): construir objetivo a R:R minimo en compras de buen setup
    # cuyo take del LLM era demasiado conservador. Solo sube el take; nunca empeora.
    if str(getattr(settings, "trading_mode", "")).lower() == "paper":
        recommendations = [
            _construct_min_reward_risk(item, settings) if str(item.action).lower() == "buy" else item
            for item in recommendations
        ]
    recommendation_augmentation = {"added": [], "replaced_holds": [], "fallback_candidates": 0}
    if settings.deterministic_trade_fallback_enabled:
        recommendations, recommendation_augmentation = augment_recommendations_with_deterministic_fallback(
            settings,
            portfolio,
            decision_context,
            recommendations,
            limit=locals().get("effective_recommendation_limit"),
            market_state=market_state,
            llm_failed=bool(decision.get("fallback_error")),
            learning_mode_config=learning_mode,
            daily_learning_digest=daily_learning_digest,
            operational_response_context=operational_response_context,
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
    with optional_measure(timing, "deterministic_gates", "deterministic_review"):
        reviewed_recommendations, deterministic_review = review_recommendations(settings, recommendations, decision_context, sentiment_context, market_state)
    if learning_mode:
        reviewed_recommendations = [
            replace(
                item,
                cohort=LEARNING_EXPERIMENT_SOURCE if str(item.action).lower() == "buy" else item.cohort,
            )
            for item in reviewed_recommendations
        ]
    reviewed_recommendations = _annotate_recommendations_with_strategy(
        reviewed_recommendations,
        decision_context,
    )
    reviewed_recommendations = _annotate_recommendations_with_lineage(
        reviewed_recommendations,
        decision_context,
        cycle_id=run_id,
        default_cohort=LEARNING_EXPERIMENT_SOURCE if learning_mode else None,
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
    with optional_measure(timing, "deterministic_gates", "adversarial_review"):
        adversarial_review = review_recommendations_adversarial(reviewed_recommendations, technical_context=decision_context, market_state=market_state)
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

    llm_identity = decision.get("llm_identity") or unavailable_llm_identity("identity_unavailable")
    model_info = {
        "llm_identity": llm_identity,
        "llm_provider": llm_identity.get("provider"),
        "llm_model": llm_identity.get("effective_model"),
        "llm_requested_model": llm_identity.get("requested_model"),
        "llm_effective_model": llm_identity.get("effective_model"),
        "llm_fallback_used": llm_identity.get("fallback_used"),
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
    snapshotted_recommendations = []
    recommendation_records: list[tuple[str, Any, dict[str, Any]]] = []
    decision_capture_requests: list[tuple[Any, dict[str, Any]]] = []
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
        snapshot = _decision_context_snapshot_for_recommendation(
            store,
            recommendation,
            cycle_id=run_id,
            source_run_id=decision_context.get("run_id"),
            market_state=market_state,
            agent_run_id=decision_agent_run_id,
            fallback_error=decision.get("fallback_error"),
            llm_identity=llm_identity,
            identity_key=f"{run_id}|{recommendation.symbol}|{recommendation.action}|{fingerprint}",
        )
        decision_capture_requests.append((recommendation, snapshot))
        recommendation_id = new_id("rec")
        recommendation = replace(
            recommendation,
            decision_context_snapshot=snapshot,
            recommendation_id=recommendation_id,
        )
        snapshotted_recommendations.append(recommendation)
        recommendation_records.append(
            (
                recommendation_id,
                recommendation,
                {
                    "deterministic_review": review_row,
                    "adversarial_review": adversarial_row,
                    "decision_input_fingerprint": fingerprint,
                },
            )
        )
    reviewed_recommendations = snapshotted_recommendations

    def _flush_decision_prediction_captures() -> None:
        for recommendation, snapshot in decision_capture_requests:
            _persist_decision_prediction_capture(
                store,
                recommendation=recommendation,
                snapshot=snapshot,
                technical_context=decision_context,
                cycle_id=run_id,
                agent_run_id=decision_capture_agent_run_id,
            )

    with optional_measure(timing, "deterministic_gates", "entry_quality_gate"):
        quality_recommendations, entry_quality_gate = _apply_entry_quality_gate(
        settings,
        reporter,
        run_id,
        reviewed_recommendations,
        decision_context,
        sentiment_context,
        learning_mode_config=learning_mode,
        daily_learning_digest=daily_learning_digest,
        operational_response_context=operational_response_context,
        )
    with optional_measure(timing, "deterministic_gates", "backtest_gate"):
        gated_recommendations, backtest_gate = _apply_backtest_gate(
        settings,
        store,
        reporter,
        run_id,
        quality_recommendations,
        )
    gated_recommendations = _annotate_recommendations_with_lineage(
        gated_recommendations,
        decision_context,
        cycle_id=run_id,
        default_cohort=LEARNING_EXPERIMENT_SOURCE if learning_mode else None,
    )
    with optional_measure(timing, "persistence", "signal_decision_updates"):
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
    exit_rejections: list[dict[str, Any]] = []
    plan_records: list[dict[str, Any]] = []
    ordered_records: list[dict[str, Any]] = []
    failed_records: list[dict[str, Any]] = []

    def _recommendation_identity(item: Any) -> tuple[str, str, str]:
        lineage = dict(getattr(item, "decision_lineage", {}) or {})
        return (
            str(getattr(item, "symbol", "") or "").upper(),
            str(getattr(item, "action", "") or "").lower(),
            str(lineage.get("signal_id") or ""),
        )

    def _recommendation_signal_id(item: Any) -> str | None:
        lineage = dict(getattr(item, "decision_lineage", {}) or {})
        signal_id = str(lineage.get("signal_id") or "").strip()
        return signal_id or None

    with optional_measure(timing, "deterministic_gates", "order_plan_build"):
        allocation_observations: list[dict[str, Any]] = []
        plans = build_order_plans(
            settings,
            portfolio,
            gated_recommendations,
            dry_run=True,
            rejected=rejected_order_plans,
            exit_rejections=exit_rejections,
            market_state=market_state,
            ignore_operational_kill_switch=learning_shadow_only,
            allocation_observations=allocation_observations,
        )
    if exit_rejections:
        try:
            reporter.emit(
                "risk_manager",
                "exit_plan_rejections",
                run_id,
                "Motivos de salidas descartadas registrados sin modificar los planes.",
                {"cycle_id": run_id, "rejections": exit_rejections},
            )
        except Exception as exc:  # noqa: BLE001 - observational evidence is fail-open.
            logging.getLogger(__name__).debug("Exit rejection audit unavailable: %s", exc)
    effective_plan_limit = _effective_buy_plan_limit(settings, gated_recommendations)
    effective_daily_limit = _effective_daily_buy_limit(settings, plans)
    approved_buys = sorted({item.symbol for item in gated_recommendations if str(item.action).lower() == "buy"})
    approved_recommendations = [
        item for item in gated_recommendations if str(getattr(item, "action", "")).lower() == "buy"
    ]
    with optional_measure(timing, "deterministic_gates", "daily_buy_limit"):
        plans = _apply_daily_buy_limit(settings, store, reporter, run_id, plans, rejected=rejected_order_plans)
    with optional_measure(timing, "deterministic_gates", "low_sample_quota"):
        plans = _apply_low_sample_daily_quota(settings, store, reporter, run_id, plans, rejected=rejected_order_plans)
    with optional_measure(timing, "deterministic_gates", "strategy_pause_filter"):
        plans, paused_plans = _separate_strategy_paused_plans(learning_mode, plans)
    planned_signal_ids = [
        signal_id
        for plan in plans
        if str(getattr(plan, "side", "")).lower() == "buy"
        for signal_id in [_recommendation_signal_id(getattr(plan, "recommendation", None))]
        if signal_id
    ]
    if paused_plans:
        for plan, strategy_name in paused_plans:
            rejected_order_plans.append(
                _rejection_payload_for_plan(plan, {
                    "symbol": plan.symbol,
                    "action": str(getattr(plan, "side", "")).lower(),
                    "stage": "learning_mode_strategy_pause",
                    "reason": "strategy_paused_shadow_active",
                    "checks": {
                        "strategy_name": strategy_name,
                        "shadow_active": True,
                        "execution_blocked": True,
                    },
                })
            )
        reporter.emit(
            "execution_agent",
            "learning_mode_strategy_paused_shadow_logged",
            run_id,
            (
                "Estrategia(s) pausada(s): no se enviaran ordenes y se conservara "
                "el would_buy en sombra. "
                f"Planes: {', '.join(f'{plan.symbol}:{strategy}' for plan, strategy in paused_plans)}."
            ),
            {
                "paused_strategies": sorted({strategy for _, strategy in paused_plans}),
                "symbols": [plan.symbol for plan, _ in paused_plans],
            },
        )

    # P-L32B: observe the real path already produced by the cycle.  This call
    # does not run a gate or apply a threshold; it only seals immutable JSON.
    gate_snapshots = collect_gate_path(
        cycle_id=run_id,
        candidates=reviewed_recommendations,
        stage_rows={
            "deterministic_review": deterministic_review,
            "adversarial_review": adversarial_review,
            "entry_quality": entry_quality_gate,
            "backtest": backtest_gate,
        },
        final_plans=plans,
        rejected_order_plans=rejected_order_plans,
        captured_at=datetime.now(timezone.utc).isoformat(),
    )
    gate_by_identity: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    ambiguous_gate_identities: set[tuple[str, str, str, str, str]] = set()
    for snapshot in gate_snapshots.values():
        identity_key = gate_identity_key(snapshot, run_id)
        if identity_key is None:
            continue
        if identity_key in gate_by_identity:
            ambiguous_gate_identities.add(identity_key)
            continue
        gate_by_identity[identity_key] = snapshot

    def _attach_gate_snapshot(item: Any) -> Any:
        identity_key = gate_identity_key(item, run_id)
        snapshot = (
            {}
            if identity_key is None or identity_key in ambiguous_gate_identities
            else gate_by_identity.get(identity_key, {})
        )
        return replace(item, gate_evaluation_snapshot=copy.deepcopy(snapshot))

    reviewed_recommendations = [_attach_gate_snapshot(item) for item in reviewed_recommendations]
    gated_recommendations = [_attach_gate_snapshot(item) for item in gated_recommendations]
    attach_gate_evaluation_snapshots(store, snapshots=list(gate_snapshots.values()))
    if gate_snapshots:
        reporter.emit(
            "self_improvement_engineer",
            "gate_evaluation_snapshots_captured",
            run_id,
            f"Gate paths prospectivos capturados: {len(gate_snapshots)}.",
            {"snapshots": len(gate_snapshots), "verified": sum(x.get("identity_status") == "verified" for x in gate_snapshots.values())},
        )

    # P-L31BR: seal control sets only from the final in-memory plans and the
    # rejection rows emitted by the real flow. No ranking, capacity or gate is
    # rerun and no synthetic rejection is introduced here.
    comparable_control_sets = build_comparable_control_sets(
        cycle_id=run_id,
        recommendations=gated_recommendations,
        plans=plans,
        rejected_order_plans=rejected_order_plans,
        all_recommendations=reviewed_recommendations,
        deterministic_review=deterministic_review,
        adversarial_review=adversarial_review,
        entry_quality_gate=entry_quality_gate,
        backtest_gate=backtest_gate,
    )

    def _control_set_for_recommendation(item: Any) -> dict[str, Any]:
        lineage = dict(getattr(item, "decision_lineage", {}) or {})
        key = str(lineage.get("signal_id") or "")
        if not key:
            key = f"{str(getattr(item, 'symbol', '') or '').upper()}|{str(getattr(item, 'action', '') or '').lower()}"
        return comparable_control_sets.get(key) or build_unavailable_control_set(
            cycle_id=run_id,
            treatment=item,
            reason="treatment_identity_unavailable",
        )

    # The plan list is the treatment authority. Attach one set to every final
    # buy plan, including an explicit unavailable block when identity is absent.
    final_plan_symbols = {str(plan.symbol).upper() for plan in plans if str(plan.side).lower() == "buy"}
    treatment_symbols = set()
    attached_plans = []
    for plan in plans:
        if str(plan.side).lower() != "buy":
            attached_plans.append(plan)
            continue
        recommendation = getattr(plan, "recommendation", None)
        control_set = _control_set_for_recommendation(recommendation)
        treatment_symbols.add(str(plan.symbol).upper())
        copied_control_set = copy_comparable_control_set(control_set)
        if recommendation is None:
            attached_plans.append(plan)
        else:
            attached_recommendation = replace(recommendation, comparable_control_set=copied_control_set)
            attached_plans.append(replace(plan, recommendation=attached_recommendation))
        comparable_control_sets.setdefault(
            str((getattr(recommendation, "decision_lineage", {}) or {}).get("signal_id") or f"{str(plan.symbol).upper()}|buy"),
            control_set,
        )
    plans = attached_plans
    if treatment_symbols != final_plan_symbols:
        raise RuntimeError("comparable_control_treatment_plan_mismatch")

    def _attach_to_recommendation(item: Any) -> Any:
        lineage = dict(getattr(item, "decision_lineage", {}) or {})
        key = str(lineage.get("signal_id") or "")
        if not key:
            key = f"{str(getattr(item, 'symbol', '') or '').upper()}|{str(getattr(item, 'action', '') or '').lower()}"
        control_set = comparable_control_sets.get(key)
        return replace(item, comparable_control_set=copy_comparable_control_set(control_set)) if control_set else item

    reviewed_recommendations = [_attach_to_recommendation(item) for item in reviewed_recommendations]
    gated_recommendations = [_attach_to_recommendation(item) for item in gated_recommendations]
    attach_comparable_control_sets(store, recommendations=reviewed_recommendations)
    updated_reviewed_by_identity = {_recommendation_identity(item): item for item in reviewed_recommendations}
    with optional_measure(timing, "persistence", "recommendation_records"):
        for recommendation_id, original_recommendation, metadata in recommendation_records:
            recommendation = updated_reviewed_by_identity.get(_recommendation_identity(original_recommendation), original_recommendation)
            store.save_trade_recommendation(
                recommendation_id=recommendation_id,
                cycle_id=run_id,
                symbol=recommendation.symbol,
                action=recommendation.action,
                confidence=recommendation.confidence,
                payload={
                    **asdict(recommendation),
                    **metadata,
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
    if comparable_control_sets:
        reporter.emit(
            "self_improvement_engineer",
            "comparable_controls_captured",
            run_id,
            f"Control sets contemporaneos capturados desde planes finales: {len(comparable_control_sets)}.",
            {
                "sets": len(comparable_control_sets),
                "treatments": len(treatment_symbols),
                "verified": sum(item.get("status") == "verified" for item in comparable_control_sets.values()),
                "partially_comparable": sum(item.get("status") == "partially_comparable" for item in comparable_control_sets.values()),
                "unavailable": sum(item.get("status") == "unavailable" for item in comparable_control_sets.values()),
            },
        )

    # P-L49B Phase B is sealed before P-L50/P-L44 Phase B and before any
    # order-plan row or broker payload is registered. Both shadows observe the
    # active results but are never passed into ranking, gates, sizing, plans,
    # or execution.
    _data_quality_shadow_final = _persist_data_quality_decision_shadow_final(
        store=store,
        reporter=reporter,
        phase_a=data_quality_shadow,
        run_id=run_id,
        recommendations=reviewed_recommendations,
        plans=plans,
        rejected_order_plans=rejected_order_plans,
        phase_b_available=True,
    )
    learning_penalty_shadow_final = _persist_learning_penalty_cycle_shadow_final(
        store=store,
        reporter=reporter,
        phase_a=learning_penalty_shadow,
        run_id=run_id,
        recommendations=reviewed_recommendations,
        plans=plans,
        comparable_control_sets=comparable_control_sets,
        rejected_order_plans=rejected_order_plans,
        gate_snapshots=gate_snapshots,
    )

    if learning_mode and (bool(learning_mode.get("shadow_first")) or paused_plans):
        low_sample_usage = _low_sample_usage_payload(store, settings)
        shadow_plans = [*plans, *(plan for plan, _ in paused_plans)] if bool(learning_mode.get("shadow_first")) else [
            plan for plan, _ in paused_plans
        ]
        with optional_measure(timing, "report_generation", "learning_shadow_report"):
            shadow_path = _write_learning_mode_shadow_report(
                settings,
                run_id=run_id,
                recommendations=reviewed_recommendations,
                plans=shadow_plans,
                rejected=rejected_order_plans,
                paused_strategies=list(learning_mode.get("shadow_strategies") or []),
                operational_kill_switch=operational_kill_switch,
            )
        reporter.emit(
            "execution_agent",
            "learning_mode_shadow_logged",
            run_id,
            "Learning mode: se registro lo que habria comprado sin enviar las ordenes pausadas.",
            {"path": shadow_path, "buys": [plan.symbol for plan in shadow_plans if str(plan.side).lower() == "buy"]},
        )
        if settings.operational_kill_switch_enabled and operational_kill_switch.get("block_buy_execution"):
            reporter.emit(
                "risk_manager",
                "auto_paper_trading_blocked_shadow_only",
                run_id,
                "Operational kill switch activo: learning_mode shadow sigue registrando, pero no enviaria ordenes reales.",
                operational_kill_switch,
            )
        if bool(learning_mode.get("shadow_first")):
            with optional_measure(timing, "persistence", "execution_status_updates"):
                execution_updates = update_signal_execution_status(
                    store,
                    source_run_id=decision_context.get("run_id"),
                    approved_symbols=approved_buys,
                    approved_recommendations=approved_recommendations,
                    rejected_order_plans=rejected_order_plans,
                    planned_symbols=[],
                    planned_signal_ids=[],
                    submitted=[],
                    failed=[],
                    effective_max_orders_per_cycle=effective_plan_limit,
                    effective_max_daily_buy_orders=effective_daily_limit,
                    cycle_id=run_id,
                )
            _flush_decision_prediction_captures()
            return {
                "submitted": [],
                "failed": [],
                "shadow_only": True,
                "shadow_report_path": shadow_path,
                "operational_kill_switch": operational_kill_switch,
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
                "low_sample_usage": low_sample_usage,
                "recommendation_augmentation": recommendation_augmentation,
                "learning_penalty_shadow": learning_penalty_shadow_final,
                "data_quality_decision_shadow": _persist_data_quality_decision_shadow_final(
                    store=store,
                    reporter=reporter,
                    phase_a=data_quality_shadow,
                    run_id=run_id,
                    recommendations=reviewed_recommendations,
                    plans=plans,
                    rejected_order_plans=rejected_order_plans,
                    phase_b_available=True,
                ),
                "selection_ledger": _persist_selection_ledger_shadow(
                    store=store,
                    reporter=reporter,
                    phase_a=selection_ledger_phase_a,
                    run_id=run_id,
                    recommendations=reviewed_recommendations,
                    plans=plans,
                    plan_records=plan_records,
                    rejected_order_plans=rejected_order_plans,
                    gate_snapshots=gate_snapshots,
                ),
            }
    planned_symbols = [plan.symbol for plan in plans if str(plan.side).lower() == "buy"]
    for plan in plans:
        plan_id = new_id("plan")
        plan_payload = asdict(plan)
        plan_records.append(
            {
                "cycle_id": run_id,
                "action": str(plan.side).lower(),
                "plan_id": plan_id,
                "payload": plan_payload,
                "decision_lineage": copy.deepcopy(plan_payload.get("decision_lineage") or {}),
            }
        )
        with optional_measure(timing, "persistence", "order_plan_records"):
            store.save_order_plan(
                plan_id=plan_id, cycle_id=run_id, symbol=plan.symbol, side=plan.side,
                notional=plan.notional, approved=plan.risk_decision.approved, dry_run=plan.dry_run, payload=plan_payload,
            )
            recommendation_tags = list(getattr(getattr(plan, "recommendation", None), "tags", []) or [])
            if LOW_SAMPLE_EXPLORATION_TAG in recommendation_tags and str(plan.side).lower() == "buy":
                _register_low_sample_order(store, settings, run_id=run_id, plan_id=plan_id, symbol=plan.symbol)
    low_sample_usage = _low_sample_usage_payload(store, settings)

    if not plans:
        with optional_measure(timing, "persistence", "execution_status_updates"):
            execution_updates = update_signal_execution_status(
                store,
                source_run_id=decision_context.get("run_id"),
                approved_symbols=approved_buys,
                approved_recommendations=approved_recommendations,
                rejected_order_plans=rejected_order_plans,
                planned_symbols=[],
                planned_signal_ids=[],
                submitted=[],
                failed=[],
                effective_max_orders_per_cycle=effective_plan_limit,
                effective_max_daily_buy_orders=effective_daily_limit,
                cycle_id=run_id,
            )
        _flush_decision_prediction_captures()
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
                "low_sample_usage": low_sample_usage,
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
            "low_sample_usage": low_sample_usage,
            "recommendation_augmentation": recommendation_augmentation,
            "learning_penalty_shadow": learning_penalty_shadow_final,
            "data_quality_decision_shadow": _data_quality_shadow_final,
            "selection_ledger": _persist_selection_ledger_shadow(
                store=store,
                reporter=reporter,
                phase_a=selection_ledger_phase_a,
                run_id=run_id,
                recommendations=reviewed_recommendations,
                plans=plans,
                plan_records=plan_records,
                rejected_order_plans=rejected_order_plans,
                gate_snapshots=gate_snapshots,
            ),
            "capital_funnel": _persist_capital_deployment_funnel_shadow(
                store=store,
                reporter=reporter,
                phase_a=selection_ledger_phase_a,
                run_id=run_id,
                recommendations=reviewed_recommendations,
                gated_recommendations=gated_recommendations,
                plans=plan_records or plans,
                rejected_order_plans=rejected_order_plans,
                submitted=[],
                account=capital_account,
                portfolio_snapshot=portfolio,
                allocation_settings=settings,
                allocation_observations=allocation_observations,
            ),
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
            ordered_records.append(
                {
                    "cycle_id": run_id,
                    "action": str(plan.get("side") or "").lower(),
                    "plan_id": plan.get("plan_id"),
                    "broker_order_id": broker_order_id,
                    "order_status": order.get("status"),
                    "submitted_notional": plan.get("notional"),
                    "submitted_at": order.get("submitted_at"),
                    "decision_lineage": copy.deepcopy(
                        plan.get("payload", {}).get("decision_lineage")
                        or recommendation.get("decision_lineage", {})
                    ),
                }
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
                    "tags": list((recommendation or {}).get("tags") or []),
                    "low_sample_exploration": LOW_SAMPLE_EXPLORATION_TAG in list((recommendation or {}).get("tags") or []),
                    "decision_lineage": plan.get("payload", {}).get("decision_lineage")
                    or (recommendation or {}).get("decision_lineage", {}),
                    "signal_id": (
                        plan.get("payload", {}).get("decision_lineage", {}) or {}
                    ).get("signal_id")
                    or (recommendation or {}).get("decision_lineage", {}).get("signal_id"),
                }
            )
        except Exception as exc:  # noqa: BLE001 - one rejected order should not hide the rest.
            failed.append(
                {
                    "symbol": plan["symbol"],
                    "side": plan["side"],
                    "error": str(exc),
                    "signal_id": (plan.get("payload", {}).get("decision_lineage", {}) or {}).get("signal_id"),
                    "decision_lineage": copy.deepcopy(plan.get("payload", {}).get("decision_lineage") or {}),
                }
            )
            failed_records.append(
                {
                    "cycle_id": run_id,
                    "action": str(plan.get("side") or "").lower(),
                    "plan_id": plan.get("plan_id"),
                    "decision_lineage": copy.deepcopy(plan.get("payload", {}).get("decision_lineage") or {}),
                    "reason": str(exc),
                }
            )

    _flush_decision_prediction_captures()
    buys = [item for item in submitted if item["side"].lower() == "buy"]
    sells = [item for item in submitted if item["side"].lower() == "sell"]
    buy_text = " || ".join(_submitted_order_summary(item) for item in buys) or "ninguna"
    sell_text = " || ".join(_submitted_order_summary(item) for item in sells) or "ninguna"
    if failed:
        fail_text = "; fallos: " + ", ".join(f"{item['symbol']} {item['side']}: {item['error']}" for item in failed)
    else:
        fail_text = ""
    with optional_measure(timing, "persistence", "execution_status_updates"):
        execution_updates = update_signal_execution_status(
            store,
            source_run_id=decision_context.get("run_id"),
            approved_symbols=approved_buys,
            approved_recommendations=approved_recommendations,
            rejected_order_plans=rejected_order_plans,
            planned_symbols=planned_symbols,
            planned_signal_ids=planned_signal_ids,
            submitted=submitted,
            failed=failed,
            effective_max_orders_per_cycle=effective_plan_limit,
            effective_max_daily_buy_orders=effective_daily_limit,
            cycle_id=run_id,
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
            "low_sample_usage": low_sample_usage,
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
        "low_sample_usage": low_sample_usage,
        "recommendation_augmentation": recommendation_augmentation,
        "learning_penalty_shadow": learning_penalty_shadow_final,
        "data_quality_decision_shadow": _data_quality_shadow_final,
        "selection_ledger": _persist_selection_ledger_shadow(
            store=store,
            reporter=reporter,
            phase_a=selection_ledger_phase_a,
            run_id=run_id,
            recommendations=reviewed_recommendations,
            plans=plans,
            plan_records=plan_records,
            rejected_order_plans=rejected_order_plans,
            ordered_records=ordered_records,
            failed_records=failed_records,
            gate_snapshots=gate_snapshots,
        ),
        "capital_funnel": _persist_capital_deployment_funnel_shadow(
            store=store,
            reporter=reporter,
            phase_a=selection_ledger_phase_a,
            run_id=run_id,
            recommendations=reviewed_recommendations,
            gated_recommendations=gated_recommendations,
            plans=plan_records or plans,
            rejected_order_plans=rejected_order_plans,
            submitted=ordered_records,
            account=capital_account,
            portfolio_snapshot=portfolio,
            allocation_settings=settings,
            allocation_observations=allocation_observations,
        ),
    }


def _same_llm_endpoint(left: Any, right: Any) -> bool:
    return (
        str(getattr(left, "base_url", "")).rstrip("/"),
        str(getattr(left, "model", "")),
        str(getattr(left, "api_key", "")),
    ) == (
        str(getattr(right, "base_url", "")).rstrip("/"),
        str(getattr(right, "model", "")),
        str(getattr(right, "api_key", "")),
    )


def _crew_provider_failure_retryable(exc: Exception) -> bool:
    """Retry CrewAI only for bounded provider-availability failures."""

    try:
        status_code = int(getattr(exc, "status_code", 0) or 0)
    except (TypeError, ValueError):
        status_code = 0
    response = getattr(exc, "response", None)
    try:
        response_status = int(getattr(response, "status_code", 0) or 0)
    except (TypeError, ValueError):
        response_status = 0
    # HTTP 401/402 cannot be repaired by retrying the same Crew request. CrewAI
    # wraps these errors with text such as "Upstream request failed", which used
    # to match the transient-provider marker below and launch a slow CrewAI
    # fallback before the existing direct decision fallback.  Preserve the
    # fallback route, but classify authentication/account failures as terminal.
    if status_code in {401, 402} or response_status in {401, 402}:
        return False
    if status_code in {408, 429, 500, 502, 503, 504} and response is not None:
        return True
    if response_status in {408, 429, 500, 502, 503, 504}:
        return True
    message = str(exc).lower()
    if any(
        marker in message
        for marker in (
            "error code: 401",
            "error code 401",
            "http 401",
            "status code: 401",
            "status code 401",
            "status_code=401",
            "api_key_expired",
            "error code: 402",
            "error code 402",
            "http 402",
            "status code: 402",
            "status code 402",
            "status_code=402",
        )
    ):
        return False
    # Do not retry arbitrary task/configuration errors merely because their
    # prose contains words such as "rate limit".  The model-unavailable form
    # is the provider error observed on Jetson; the remaining markers are
    # explicit transport/provider responses.
    return any(
        marker in message
        for marker in (
            "model is unavailable",
            "model unavailable",
            "upstream request failed",
            "too many requests",
            "rate_limit",
            "rate limit exceeded",
            "rate limit reached",
            "error code: 408",
            "error code: 429",
            "error code: 500",
            "error code: 502",
            "error code: 503",
            "error code: 504",
            "http 408",
            "http 429",
            "http 500",
            "http 502",
            "http 503",
            "http 504",
            "503 service unavailable",
            "502 bad gateway",
        )
    )


def _crew_endpoints(
    settings: Settings,
    preferred: Any,
    preflight_attempts: list[dict[str, Any]] | None = None,
) -> list[Any]:
    """Return preferred endpoint followed by configured, distinct fallbacks."""

    unavailable_names = {
        str(item.get("name") or "")
        for item in preflight_attempts or []
        if item.get("available") is False
    }
    endpoints = [] if preferred.name in unavailable_names else [preferred]
    for endpoint in configured_llm_endpoints(settings):
        if endpoint.name in unavailable_names:
            continue
        if not any(_same_llm_endpoint(endpoint, existing) for existing in endpoints):
            endpoints.append(endpoint)
    return endpoints


def run_observable_cycle(
    settings: Settings,
    store: Store,
    *,
    use_crew: bool = True,
    verbose: bool = True,
    technical_context: dict[str, Any] | None = None,
    run_id: str | None = None,
    timing: MarketCycleTiming | None = None,
    learning_penalty_shadow: dict[str, Any] | None = None,
    selection_ledger_phase_a: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one cycle and make every phase visible in the console and logs."""

    settings.assert_trading_safety()
    store.ensure_schema()
    run_id = run_id or cycle_id()
    timing = timing or MarketCycleTiming(settings.data_dir / "reports", run_id)
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
    snapshot_run = AgentRunTracker(
        store,
        role="market_data_researcher",
        agent_name="market_data_researcher",
        task_name="market_snapshot",
        cycle_id=run_id,
        execution_kind="system",
        input_refs=[run_id],
    )
    try:
        reporter.emit(
            "market_data_researcher",
            "market_snapshot_started",
            run_id,
            "Descargando precios reales y calculando variables tecnicas basicas.",
        )
        with timing.measure("data_loading", "market_snapshot"):
            market_snapshot = build_market_snapshot(
                settings.universe, settings.benchmark_symbol, settings.data_dir / "reports", run_id,
                provider=settings.market_data_provider, fmp_api_key=settings.fmp_api_key,
            )
        market_snapshot_prompt = compact_snapshot_for_prompt(market_snapshot, max_chars=2500)
        snapshot_run.add_outputs(output_refs=[run_id])
        snapshot_run.succeed()
        reporter.emit(
            "market_data_researcher",
            "market_snapshot_completed",
            run_id,
            f"Snapshot guardado con {len(market_snapshot.get('symbols', {}))} simbolos.",
            {"path": market_snapshot.get("path"), "warnings": market_snapshot.get("warnings", [])},
        )
    except Exception as exc:  # noqa: BLE001 - CrewAI can still run, but it must know data is missing.
        snapshot_run.fail(reason=exc, error_code="market_snapshot_failed")
        json_safe_error = {"error": str(exc)}
        market_snapshot_prompt = json.dumps(json_safe_error, ensure_ascii=True)
        reporter.emit(
            "market_data_researcher",
            "market_snapshot_failed",
            run_id,
            f"No se pudo crear snapshot real: {exc}",
            json_safe_error,
        )

    state_run = AgentRunTracker(
        store,
        role="market_regime_strategist",
        agent_name="market_regime_strategist",
        task_name="market_state",
        cycle_id=run_id,
        execution_kind="deterministic",
        input_refs=[run_id],
    )
    try:
        reporter.emit(
            "market_regime_strategist",
            "market_state_started",
            run_id,
            "Construyendo estado de mercado unificado con regimen, amplitud, sentimiento y calidad de datos.",
        )
        with timing.measure("report_generation", "market_state_report"):
            market_state = build_market_state(settings, settings.data_dir / "reports", run_id, market_snapshot=market_snapshot)
        market_state_prompt = compact_market_state_for_prompt(market_state, max_chars=2500)
        state_run.add_outputs(output_refs=[run_id])
        state_run.succeed()
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
        state_run.fail(reason=exc, error_code="market_state_failed")
        market_state_prompt = json.dumps({"error": str(exc)}, ensure_ascii=True)
        reporter.emit(
            "market_regime_strategist",
            "market_state_degraded",
            run_id,
            f"No se pudo construir market_state completo: {exc}",
            {"error": str(exc)},
        )

    # P-L49B Phase A is strictly in-memory and receives only the market
    # objects already constructed for this cycle.  It is not supplied to any
    # active decision function.
    data_quality_run = AgentRunTracker(
        store,
        role="market_data_researcher",
        agent_name="market_data_researcher",
        task_name="data_quality_decision_shadow",
        cycle_id=run_id,
        execution_kind="deterministic",
        input_refs=[run_id],
    )
    data_quality_shadow = _capture_data_quality_decision_shadow(
        run_id=run_id,
        market_snapshot=market_snapshot,
        market_state=market_state,
        technical_context=technical_context,
        reporter=reporter,
    )
    if data_quality_shadow is None:
        data_quality_run.fail(reason="data_quality_shadow_unavailable", error_code="shadow_unavailable")
    else:
        data_quality_run.add_outputs(output_refs=[run_id])
        data_quality_run.succeed()

    crew_result: str | None = None
    crew_execution_parent_id: str | None = None
    crew_observability: dict[str, Any] | None = None
    if use_crew:
        endpoint, _attempts = select_preferred_endpoint(settings)
        crew_run = AgentRunTracker(
            store,
            role="crew_orchestrator",
            agent_name="orchestrator",
            task_name="crew_cycle",
            cycle_id=run_id,
            execution_kind="llm",
            provider=endpoint.provider,
            model=endpoint.model,
            input_refs=[run_id],
        )
        crew_execution_parent_id = crew_run.agent_run_id
        reporter.emit(
            "orchestrator",
            "crew_started",
            run_id,
            f"Lanzando CrewAI contra {endpoint.model} en {endpoint.base_url}.",
            {"llm_identity": build_llm_identity(endpoint)},
        )
        crew_endpoints = _crew_endpoints(settings, endpoint, _attempts)
        attempted_endpoints: list[dict[str, Any]] = []
        last_exc: Exception | None = None
        previous_attempt_run = crew_run
        if not crew_endpoints:
            crew_run.fail(
                reason="all_crew_endpoints_unavailable",
                error_code="crew_provider_unavailable",
            )
            crew_run.fallback_started(reason="direct_llm_decision")
            reporter.emit(
                "orchestrator",
                "crew_failed",
                run_id,
                "CrewAI omitido: todos los endpoints quedaron no disponibles en preflight; se continua con decision LLM directa.",
                {
                    "error": "all_crew_endpoints_unavailable",
                    "fallback": "direct_llm_decision",
                    "attempted_endpoints": attempted_endpoints,
                    "crew_observability": crew_observability,
                },
            )
        for attempt_index, attempt_endpoint in enumerate(crew_endpoints, start=1):
            attempt_run = crew_run
            if attempt_index > 1:
                fallback_reason = (
                    "crew_provider_failure:"
                    f"{type(last_exc).__name__ if last_exc is not None else 'unknown'}"
                )
                previous_attempt_run.fallback_started(reason=fallback_reason)
                attempt_run = AgentRunTracker(
                    store,
                    role="crew_orchestrator",
                    agent_name="orchestrator",
                    task_name="crew_cycle_fallback",
                    cycle_id=run_id,
                    execution_kind="fallback",
                    parent_run_id=previous_attempt_run.agent_run_id,
                    retry_of=previous_attempt_run.agent_run_id,
                    provider=attempt_endpoint.provider,
                    model=attempt_endpoint.model,
                    input_refs=[run_id],
                    fallback_reason=fallback_reason,
                )
                reporter.emit(
                    "orchestrator",
                    "crew_fallback_started",
                    run_id,
                    f"Reintentando CrewAI contra {attempt_endpoint.model} en {attempt_endpoint.base_url}.",
                    {
                        "retry_of": previous_attempt_run.agent_run_id,
                        "attempt": attempt_index,
                        "llm_identity": build_llm_identity(attempt_endpoint, status="fallback"),
                    },
                )
            log_suffix = "" if attempt_index == 1 else f"_attempt{attempt_index}"
            crew_stdout_path = settings.logs_dir / f"crew_stdout_{run_id}{log_suffix}.log"
            task_observer = CrewTaskObserver(
                store,
                cycle_id=run_id,
                parent_run_id=attempt_run.agent_run_id,
                model=attempt_endpoint.model,
                candidate_ids={
                    str(item["candidate_id"])
                    for item in ((technical_context or {}).get("all_candidates") or [])
                    if isinstance(item, dict) and item.get("candidate_id")
                },
            )
            try:
                with crew_execution_context(
                    cycle_id=run_id, crew_agent_run_id=attempt_run.agent_run_id,
                    attempt=attempt_index, fallback=attempt_index > 1,
                    task_observer=task_observer,
                ):
                    crew = build_crew(settings, endpoint=attempt_endpoint)
                try:
                    reporter.emit(
                        "orchestrator",
                        "crew_participant_manifest",
                        run_id,
                        "Manifiesto de participantes CrewAI registrado.",
                        {
                            "cycle_id": run_id,
                            "agent_run_id": attempt_run.agent_run_id,
                            "crew_agent_run_id": attempt_run.agent_run_id,
                            "attempt": attempt_index,
                            "fallback": attempt_index > 1,
                            "manifest": build_crew_task_manifest(),
                            "crew_result_consumed_by": [],
                            "active_decision_route": "structured_trade_recommendations",
                        },
                    )
                except Exception as exc:  # noqa: BLE001 - telemetry is fail-open.
                    logging.getLogger(__name__).debug(
                        "Crew participant manifest telemetry skipped: %s", exc
                    )
                crew_stdout_path.parent.mkdir(parents=True, exist_ok=True)
                with crew_execution_context(
                    cycle_id=run_id,
                    crew_agent_run_id=attempt_run.agent_run_id,
                    attempt=attempt_index,
                    fallback=attempt_index > 1,
                    task_observer=task_observer,
                ):
                    with timing.measure("llm_decision", f"crew_reasoning_attempt_{attempt_index}"):
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
                crew_observability = task_observer.finalize()
                attempt_run.add_outputs(output_refs=[f"data/logs/{crew_stdout_path.name}"])
                attempt_run.succeed()
                crew_execution_parent_id = attempt_run.agent_run_id
                reporter.emit(
                    "orchestrator",
                    "crew_completed",
                    run_id,
                    "CrewAI completo el ciclo de razonamiento.",
                    {
                        "result_preview": crew_result[:1000],
                        "crew_stdout_path": str(crew_stdout_path),
                        "attempt": attempt_index,
                        "fallback": attempt_index > 1,
                        "llm_identity": build_llm_identity(attempt_endpoint),
                        "crew_observability": crew_observability,
                    },
                )
                break
            except Exception as exc:
                crew_observability = task_observer.finalize(failed=True, reason="crew_failed")
                last_exc = exc
                attempted_endpoints.append(
                    build_llm_identity(attempt_endpoint, status="failed", reason="crew_failed")
                )
                attempt_run.fail(reason=exc, error_code="crew_failed")
                next_endpoint_available = attempt_index < len(crew_endpoints)
                if next_endpoint_available and _crew_provider_failure_retryable(exc):
                    previous_attempt_run = attempt_run
                    continue
                attempt_run.fallback_started(reason="direct_llm_decision")
                reporter.emit(
                    "orchestrator",
                    "crew_failed",
                    run_id,
                    f"CrewAI fallo: {exc}. Se continua con decision LLM directa para no perder el ciclo.",
                    {
                        "error": str(exc),
                        "fallback": "direct_llm_decision",
                        "attempted_endpoints": attempted_endpoints,
                        "llm_identity": build_llm_identity(endpoint, status="failed", reason="crew_failed"),
                    },
                )
                break
    else:
        crew_run = AgentRunTracker(
            store,
            role="crew_orchestrator",
            agent_name="orchestrator",
            task_name="crew_cycle",
            cycle_id=run_id,
            execution_kind="llm",
            input_refs=[run_id],
        )
        crew_run.skip(reason="skip_crew_parameter")
        timing.skip_segment("llm_decision", "crew_reasoning", "CrewAI omitido por parametro --skip-crew")
        reporter.emit(
            "orchestrator",
            "crew_skipped",
            run_id,
            "CrewAI omitido por parametro --skip-crew. Solo se valido el flujo/logging.",
        )

    auto_result = None
    if use_crew:
        execution_run = AgentRunTracker(
            store,
            role="execution_agent",
            agent_name="execution_agent",
            task_name="paper_auto_trade",
            cycle_id=run_id,
            execution_kind="system",
            parent_run_id=crew_execution_parent_id,
            input_refs=[run_id],
        )
        try:
            auto_result = _auto_paper_trade(
                settings,
                store,
                reporter,
                run_id,
                technical_context,
                market_snapshot,
                market_state,
                learning_penalty_shadow=learning_penalty_shadow,
                data_quality_shadow=data_quality_shadow,
                agent_run_id=execution_run.agent_run_id,
                timing=timing,
                selection_ledger_phase_a=selection_ledger_phase_a,
            )
            if auto_result is None:
                execution_run.skip(reason="auto_paper_trading_disabled")
            else:
                execution_run.add_outputs(
                    output_refs=[
                        run_id,
                        *[
                            item.get("broker_order_id")
                            for item in auto_result.get("submitted", [])
                            if isinstance(item, dict)
                        ],
                    ]
                )
                if auto_result.get("blocked"):
                    execution_run.block(reason=auto_result["blocked"])
                elif auto_result.get("failed"):
                    execution_run.fail(
                        reason="paper_order_submission_failed",
                        error_code="paper_order_submission_failed",
                    )
                else:
                    execution_run.succeed()
        except Exception as exc:
            execution_run.fail(reason=exc, error_code="paper_auto_trade_failed")
            timing.finalize("failed", error=exc)
            raise
        if learning_penalty_shadow is not None and (
            not isinstance(auto_result, dict) or auto_result.get("learning_penalty_shadow") is None
        ):
            try:
                existing = [
                    item
                    for item in store.learning_penalty_cycle_shadow_events(limit=50000)
                    if str(item.get("cycle_id") or "") == str(run_id)
                ]
            except Exception:
                existing = []
            if not existing:
                _persist_learning_penalty_cycle_shadow_final(
                    store=store,
                    reporter=reporter,
                    phase_a=learning_penalty_shadow,
                    run_id=run_id,
                    recommendations=[],
                    plans=[],
                    comparable_control_sets={},
                    rejected_order_plans=[],
                    phase_b_available=False,
                )
    else:
        timing.skip("deterministic_gates", "sin decision LLM al omitir CrewAI")
        if learning_penalty_shadow is not None:
            partial_shadow = finalize_learning_penalty_cycle_shadow(
                learning_penalty_shadow,
                cycle_id=run_id,
                phase_b_available=False,
            )
            try:
                persist_learning_penalty_cycle_shadow(store, partial_shadow)
            except Exception as exc:  # noqa: BLE001 - fail-open observability.
                reporter.emit(
                    "self_improvement_engineer",
                    "learning_penalty_cycle_shadow_failed",
                    run_id,
                    "No se pudo persistir el shadow partial; el ciclo continua.",
                    {"error": repr(exc), "policy_mode": "shadow_only"},
                )
    # Blocked/skip paths may not enter the active plan boundary.  Persist one
    # partial snapshot only when Phase B was not already sealed; this never
    # retries market data, reconciliation, outcomes, ranking, or execution.
    if data_quality_shadow is not None:
        try:
            existing_quality_event = store.data_quality_decision_shadow_event(run_id)
        except Exception:
            existing_quality_event = None
        if existing_quality_event is None:
            _persist_data_quality_decision_shadow_final(
                store=store,
                reporter=reporter,
                phase_a=data_quality_shadow,
                run_id=run_id,
                recommendations=(auto_result or {}).get("recommendations", []) if isinstance(auto_result, dict) else [],
                plans=[],
                rejected_order_plans=(auto_result or {}).get("rejected_order_plans", []) if isinstance(auto_result, dict) else [],
                phase_b_available=False,
            )
    if not isinstance(auto_result, dict) or "selection_ledger" not in auto_result:
        _persist_selection_ledger_shadow(
            store=store,
            reporter=reporter,
            phase_a=selection_ledger_phase_a,
            run_id=run_id,
            recommendations=(auto_result or {}).get("recommendations") if isinstance(auto_result, dict) else None,
            plans=(auto_result or {}).get("plans") if isinstance(auto_result, dict) else None,
            rejected_order_plans=(auto_result or {}).get("rejected_order_plans") if isinstance(auto_result, dict) else None,
        )
    if not isinstance(auto_result, dict) or "capital_funnel" not in auto_result:
        _persist_capital_deployment_funnel_shadow(
            store=store,
            reporter=reporter,
            phase_a=selection_ledger_phase_a,
            run_id=run_id,
            recommendations=(auto_result or {}).get("recommendations") if isinstance(auto_result, dict) else None,
            plans=(auto_result or {}).get("plans") if isinstance(auto_result, dict) else None,
            rejected_order_plans=(auto_result or {}).get("rejected_order_plans") if isinstance(auto_result, dict) else None,
            submitted=(auto_result or {}).get("submitted") if isinstance(auto_result, dict) else None,
            allocation_settings=settings,
        )
    with timing.measure("persistence", "trade_summary"):
        _record_trade_summary(settings, store, reporter, run_id, auto_result)
    if not timing.is_running("technical_analysis"):
        timing.skip("technical_analysis", "sin escaneo tecnico intradia instrumentado")
    reporter.emit(
        "orchestrator",
        "cycle_completed",
        run_id,
        "Ciclo finalizado. Estado persistido en SQLite y JSONL por agente.",
    )
    log_system_event(settings.logs_dir, "cycle_completed", {"cycle_id": run_id})
    timing.finalize("completed")
    return {
        "cycle_id": run_id,
        "crew_result": crew_result,
        "crew_observability": crew_observability,
        "used_crew": use_crew,
        "market_state_path": (market_state or {}).get("path"),
        "market_state_quality": ((market_state or {}).get("data_quality") or {}).get("status"),
    }
