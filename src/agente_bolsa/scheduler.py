"""APScheduler runtime jobs for the autonomous trading system."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
except ModuleNotFoundError:  # pragma: no cover - exercised by import-only test environments.
    BackgroundScheduler = None  # type: ignore[assignment]
    CronTrigger = None  # type: ignore[assignment]
    IntervalTrigger = None  # type: ignore[assignment]

from .config import Settings
from .cycle_runner import run_observable_cycle
from .eventing import EventReporter
from .logging_utils import log_system_event
from .market_calendar import MarketCalendar
from .models import new_id
from .storage import Store
from .tools.broker import BrokerClientFactory
from .tools.breakout_scanner import build_breakout_scan, merge_breakout_universe
from .tools.execution import submit_paper_order_plan
from .tools.daily_learning import build_learning_digest_report, load_daily_learning_context
from .tools.news_sentiment import analyze_news_sentiment_for_candidates
from .tools.operational_health import load_operational_response_context
from .tools.pre_earnings import (
    backfill_pending_pre_earnings_estimates,
    build_pre_earnings_learning_digest,
    build_pre_earnings_report,
    build_pre_earnings_trade_operation,
    build_pre_earnings_trade_recommendations,
    enrich_report_with_local_analyst_revisions,
    enrich_report_with_pre_earnings_score_v2,
    record_pre_earnings_analyst_snapshots,
    record_pre_earnings_predictions,
    update_pre_earnings_outcomes,
)
from .tools.post_market_review import build_post_market_review
from .tools.retention import cleanup_runtime_data
from .tools.signal_learning import record_signal_candidates
from .tools.technical_study import build_closed_market_technical_study
from .tools.trade_decision import _annotate_technical_context_with_learning
from .tools.universe import resolve_study_universe


LOGGER = logging.getLogger(__name__)


def _scheduler_lock_path(settings: Settings) -> Any:
    return settings.state_dir / "scheduler.lock"


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _acquire_scheduler_lock(settings: Settings) -> tuple[bool, str]:
    lock_path = _scheduler_lock_path(settings)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    current_pid = os.getpid()
    if lock_path.exists():
        raw = lock_path.read_text(encoding="utf-8").strip()
        try:
            existing_pid = int(raw)
        except ValueError:
            existing_pid = 0
        if existing_pid and existing_pid != current_pid and _pid_is_running(existing_pid):
            return False, f"Scheduler ya activo en PID {existing_pid}"
        try:
            lock_path.unlink()
        except OSError:
            return False, "No se pudo limpiar un lock antiguo del scheduler"
    lock_path.write_text(str(current_pid), encoding="utf-8")
    return True, ""


def _release_scheduler_lock(settings: Settings) -> None:
    lock_path = _scheduler_lock_path(settings)
    try:
        if lock_path.exists() and lock_path.read_text(encoding="utf-8").strip() == str(os.getpid()):
            lock_path.unlink()
    except OSError:
        LOGGER.warning("No se pudo liberar scheduler.lock")


def _reporter(settings: Settings, store: Store, verbose: bool) -> EventReporter:
    return EventReporter(store, verbose=verbose)


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

    used_buys = store.count_broker_orders(side="buy", since_iso=_session_start_utc_iso(settings))
    remaining_buys = max(0, settings.max_daily_buy_orders - used_buys)
    kept = []
    blocked = []
    for plan in plans:
        if str(getattr(plan, "side", "")).lower() != "buy":
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
                "Compras pre-earnings bloqueadas por limite diario: "
                f"ya usadas {used_buys}/{settings.max_daily_buy_orders}; "
                f"bloqueadas: {', '.join(plan.symbol for plan in blocked)}."
            ),
            {
                "used_buy_orders_today": used_buys,
                "max_daily_buy_orders": settings.max_daily_buy_orders,
                "blocked_symbols": [plan.symbol for plan in blocked],
                "source": "pre_earnings",
            },
        )
    return kept


def _run_pre_earnings_trade_operation(
    settings: Settings,
    store: Store,
    reporter: EventReporter,
    run_id: str,
    report: dict[str, Any],
) -> dict[str, Any]:
    recommendations = build_pre_earnings_trade_recommendations(settings, report)
    result: dict[str, Any] = {
        "enabled": settings.pre_earnings_trade_enabled,
        "recommendations": [asdict(item) for item in recommendations],
        "buy_order_plans": [],
        "submitted": [],
        "failed": [],
        "blocked": None,
        "blocked_pending_symbols": [],
    }
    if not settings.pre_earnings_trade_enabled:
        result["blocked"] = "pre_earnings_trade_disabled"
        return result
    if not recommendations:
        return result

    for recommendation in recommendations:
        store.save_trade_recommendation(
            recommendation_id=new_id("rec"),
            cycle_id=run_id,
            symbol=recommendation.symbol,
            action=recommendation.action,
            confidence=recommendation.confidence,
            payload=asdict(recommendation),
        )

    try:
        portfolio = BrokerClientFactory(settings).alpaca_portfolio_snapshot()
    except Exception as exc:  # noqa: BLE001 - diagnostics should continue even if broker is unavailable.
        result["blocked"] = "portfolio_unavailable"
        result["failed"].append({"stage": "portfolio_snapshot", "error": str(exc)})
        return result
    operation = build_pre_earnings_trade_operation(
        settings,
        portfolio,
        report,
        dry_run=True,
    )
    plans = list(operation.get("plans", []) or [])
    pending_symbols = {
        str(item.get("symbol") or "").upper()
        for item in store.pending_order_plans(limit=max(20, settings.max_orders_per_cycle * 5))
        if str(item.get("side") or "").lower() == "buy"
    }
    if pending_symbols:
        blocked_pending = [plan.symbol for plan in plans if plan.symbol.upper() in pending_symbols]
        if blocked_pending:
            result["blocked_pending_symbols"] = blocked_pending
            plans = [plan for plan in plans if plan.symbol.upper() not in pending_symbols]
    plans = _apply_daily_buy_limit(settings, store, reporter, run_id, plans)
    for plan in plans:
        store.save_order_plan(
            plan_id=new_id("plan"),
            cycle_id=run_id,
            symbol=plan.symbol,
            side=plan.side,
            notional=plan.notional,
            approved=plan.risk_decision.approved,
            dry_run=plan.dry_run,
            payload=asdict(plan),
        )
    result["buy_order_plans"] = [asdict(plan) for plan in plans]
    if not plans:
        return result

    if not settings.auto_paper_trading:
        result["blocked"] = "auto_paper_trading_disabled"
        return result
    if settings.require_human_approval:
        result["blocked"] = "REQUIRE_HUMAN_APPROVAL"
        return result
    if settings.trading_mode != "paper" or not settings.alpaca_paper or settings.allow_live_trading:
        result["blocked"] = "paper_safety"
        return result

    pending_current = store.pending_order_plans(cycle_id=run_id, limit=settings.max_orders_per_cycle)
    for plan in pending_current:
        client_order_id = f"agente-{plan['plan_id'][:20]}"
        try:
            order = submit_paper_order_plan(settings, plan, client_order_id=client_order_id)
            broker_order_id = order["id"] or client_order_id
            store.save_broker_order(
                broker_order_id=broker_order_id,
                plan_id=plan["plan_id"],
                cycle_id=run_id,
                symbol=plan["symbol"],
                side=plan["side"],
                status=order["status"],
                payload={"plan": plan, "broker_order": order},
            )
            result["submitted"].append(
                {
                    "symbol": plan["symbol"],
                    "side": plan["side"],
                    "notional": plan["notional"],
                    "status": order["status"],
                }
            )
        except Exception as exc:  # noqa: BLE001 - one failed order should not hide the rest.
            result["failed"].append({"symbol": plan["symbol"], "side": plan["side"], "error": str(exc)})
    return result


def _candidate_limit_per_side(settings: Settings) -> int:
    return max(1, settings.news_sentiment_top_n // 2)


def _setup_name(candidate: dict[str, Any]) -> str:
    technical_state = candidate.get("technical_state", {}) or {}
    if technical_state.get("event_momentum_long"):
        return "event_momentum"
    if technical_state.get("momentum_shakeout_hold_long"):
        return "momentum_shakeout"
    chart_patterns = technical_state.get("chart_patterns", []) or []
    if any(item.get("bias") == "bullish" and item.get("status") == "confirmed" for item in chart_patterns):
        return "confirmed_pattern"
    volume_z = technical_state.get("volume_zscore_20")
    return_20d = technical_state.get("return_20d")
    if isinstance(volume_z, (int, float)) and isinstance(return_20d, (int, float)) and volume_z >= 1.0 and return_20d > 0:
        return "trend_volume"
    return "baseline_trend"


def _selected_candidates(report: dict[str, Any], settings: Settings) -> tuple[list[dict[str, Any]], list[str]]:
    candidate_limit_per_side = _candidate_limit_per_side(settings)
    daily_learning_digest = load_daily_learning_context(settings.data_dir)
    operational_context = load_operational_response_context(settings.data_dir)
    ranked_report = _annotate_technical_context_with_learning(
        report,
        daily_learning_digest,
        operational_context,
    )
    top_longs = list(ranked_report.get("top_longs", []) or [])
    top_shorts = list(ranked_report.get("top_shorts", []) or [])
    candidates = [
        *top_longs[:candidate_limit_per_side],
        *top_shorts[:candidate_limit_per_side],
    ]
    symbols = sorted({str(item["symbol"]).upper() for item in candidates if item.get("symbol")})
    return candidates, symbols


def _compact_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    technical_state = candidate.get("technical_state", {}) or {}
    chart_patterns = []
    for pattern in (technical_state.get("chart_patterns", []) or [])[:5]:
        chart_patterns.append(
            {
                "pattern": pattern.get("pattern"),
                "label": pattern.get("label"),
                "bias": pattern.get("bias"),
                "status": pattern.get("status"),
                "confidence": pattern.get("confidence"),
            }
        )
    return {
        "symbol": candidate.get("symbol"),
        "direction": candidate.get("direction"),
        "score": candidate.get("score"),
        "setup_name": _setup_name(candidate),
        "setup_edge_3d": candidate.get("setup_edge_3d"),
        "rank_priority_score": candidate.get("rank_priority_score"),
        "rank_priority_reason": candidate.get("rank_priority_reason"),
        "operational_penalty": candidate.get("operational_penalty", 0.0),
        "operational_notes": candidate.get("operational_notes", [])[:2],
        "setup_quality": candidate.get("setup_quality"),
        "reasons": candidate.get("reasons", [])[:5],
        "close": technical_state.get("close"),
        "return_20d": technical_state.get("return_20d"),
        "sma_20": technical_state.get("sma_20"),
        "sma_50": technical_state.get("sma_50"),
        "sma_200": technical_state.get("sma_200"),
        "rsi_14": technical_state.get("rsi_14"),
        "macd": technical_state.get("macd"),
        "macd_signal": technical_state.get("macd_signal"),
        "atr_14": technical_state.get("atr_14"),
        "volume_zscore_20": technical_state.get("volume_zscore_20"),
        "trend_positive": technical_state.get("trend_positive"),
        "above_long_trend": technical_state.get("above_long_trend"),
        "candlestick_patterns": technical_state.get("candlestick_patterns", [])[:5],
        "chart_patterns": chart_patterns,
        "risk_plan": candidate.get("risk_plan", {}),
    }


def _compact_scan_context(report: dict[str, Any], selected_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "source": "intraday_technical_scan",
        "run_id": report.get("run_id"),
        "path": report.get("path"),
        "symbols_scanned": report.get("symbols_scanned"),
        "symbols_with_data": report.get("symbols_with_data"),
        "selected_candidates": [_compact_candidate(item) for item in selected_candidates],
        "top_longs": [_compact_candidate(item) for item in report.get("top_longs", [])[:5]],
        "top_shorts": [_compact_candidate(item) for item in report.get("top_shorts", [])[:5]],
        "analysis_plan_counts": report.get("analysis_plan_counts", {}),
        "warnings": report.get("warnings", [])[:5],
    }


def _job_state_key(job_name: str) -> str:
    return f"scheduler_job_status:{job_name}"


def _set_job_status(
    store: Store,
    job_name: str,
    *,
    status: str,
    run_id: str,
    started_at: datetime,
    detail: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    finished_at = datetime.now(timezone.utc)
    payload = {
        "job": job_name,
        "status": status,
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
        "detail": detail,
        "extra": extra or {},
    }
    store.set_runtime_value(_job_state_key(job_name), payload)


def _risk_exit_plan(
    *,
    symbol: str,
    notional: float,
    qty: float,
    current_price: float,
    trigger: str,
    level: float,
    source_plan: dict[str, Any],
) -> dict[str, Any]:
    return {
        "plan_id": new_id("risk_exit"),
        "cycle_id": new_id("watch_exit"),
        "symbol": symbol,
        "side": "sell",
        "notional": round(notional, 2),
        "approved": True,
        "dry_run": True,
        "payload": {
            "qty": qty,
            "entry_price": current_price,
            "stop_loss": source_plan.get("payload", {}).get("stop_loss", 0.0),
            "take_profit": source_plan.get("payload", {}).get("take_profit", 0.0),
            "recommendation": {
                "symbol": symbol,
                "action": "exit",
                "confidence": 1.0,
                "reason": f"Salida automatica por {trigger}: precio {current_price:.4f} vs nivel {level:.4f}.",
                "entry_price": current_price,
                "stop_loss": source_plan.get("payload", {}).get("stop_loss", 0.0),
                "take_profit": source_plan.get("payload", {}).get("take_profit", 0.0),
                "target_exposure_pct": 0.0,
                "time_horizon": "inmediato",
                "invalidation": f"{trigger} tocado",
                "source": "risk_monitor",
            },
            "risk_decision": {
                "approved": True,
                "reason": f"Salida automatica aprobada por {trigger}.",
                "checks": {
                    "action": "exit",
                    "trigger": trigger,
                    "trigger_level": level,
                    "current_price": current_price,
                    "held_qty": qty,
                    "notional": round(notional, 2),
                    "source_plan_id": source_plan.get("plan_id"),
                },
            },
            "dry_run": True,
        },
        "created_at": "",
    }


def _execute_stop_take_exits(
    settings: Settings,
    store: Store,
    reporter: EventReporter,
    run_id: str,
    portfolio: Any,
) -> list[dict[str, Any]]:
    if not settings.auto_paper_trading or settings.require_human_approval:
        return []
    if settings.trading_mode != "paper" or not settings.alpaca_paper or settings.allow_live_trading:
        return []

    open_order_symbols = {order.symbol.upper() for order in portfolio.open_orders}
    buy_plans = store.latest_executed_buy_plans_by_symbol()
    exits = []
    for position in portfolio.positions:
        symbol = position.symbol.upper()
        if symbol in open_order_symbols:
            continue
        source = buy_plans.get(symbol)
        if not source:
            continue
        source_plan = source.get("plan", {}) or {}
        payload = source_plan.get("payload", {}) or {}
        stop_loss = float(payload.get("stop_loss") or 0)
        take_profit = float(payload.get("take_profit") or 0)
        trigger = None
        level = 0.0
        if stop_loss > 0 and position.current_price <= stop_loss:
            trigger = "stop_loss"
            level = stop_loss
        elif take_profit > 0 and position.current_price >= take_profit:
            trigger = "take_profit"
            level = take_profit
        if not trigger:
            continue

        plan = _risk_exit_plan(
            symbol=symbol,
            notional=position.market_value,
            qty=position.qty,
            current_price=position.current_price,
            trigger=trigger,
            level=level,
            source_plan=source_plan,
        )
        try:
            order = submit_paper_order_plan(
                settings,
                plan,
                client_order_id=f"agente-{plan['plan_id'][:20]}",
            )
            store.save_broker_order(
                broker_order_id=order["id"] or plan["plan_id"],
                plan_id=plan["plan_id"],
                cycle_id=run_id,
                symbol=symbol,
                side="sell",
                status=order["status"],
                payload={"plan": plan, "broker_order": order},
            )
            exits.append(
                {
                    "symbol": symbol,
                    "trigger": trigger,
                    "level": level,
                    "current_price": position.current_price,
                    "status": order["status"],
                }
            )
        except Exception as exc:  # noqa: BLE001 - watch must stay alive.
            exits.append(
                {
                    "symbol": symbol,
                    "trigger": trigger,
                    "level": level,
                    "current_price": position.current_price,
                    "error": str(exc),
                }
            )

    if exits:
        ok = [item for item in exits if "error" not in item]
        failed = [item for item in exits if "error" in item]
        ok_text = ", ".join(
            f"{item['symbol']} por {item['trigger']} ({item['status']})" for item in ok
        ) or "ninguna"
        fail_text = "; fallos: " + ", ".join(
            f"{item['symbol']} {item['trigger']}: {item['error']}" for item in failed
        ) if failed else ""
        reporter.emit(
            "risk_manager",
            "stop_take_exit_executed",
            run_id,
            f"Salidas automaticas stop/take: {ok_text}{fail_text}.",
            {"exits": exits},
        )
    return exits


def _position_news_candidates(portfolio: Any) -> list[dict[str, Any]]:
    candidates = []
    for position in portfolio.positions:
        candidates.append(
            {
                "symbol": position.symbol.upper(),
                "direction": "long" if position.side == "long" else position.side,
                "score": None,
                "reasons": [
                    "posicion abierta",
                    f"unrealized_plpc={position.unrealized_plpc:.4f}",
                ],
                "technical_state": {
                    "close": position.current_price,
                    "unrealized_pl": position.unrealized_pl,
                    "unrealized_plpc": position.unrealized_plpc,
                    "avg_entry_price": position.avg_entry_price,
                },
            }
        )
    return candidates


def _open_position_news_guard_due(settings: Settings, store: Store, symbols: list[str]) -> bool:
    if settings.open_position_news_guard_interval_minutes <= 0:
        return True
    key = "open_position_news_guard_last_run"
    last = store.get_runtime_value(key)
    fingerprint = ",".join(sorted(symbols))
    if isinstance(last, dict) and last.get("symbols") == fingerprint:
        try:
            last_run = datetime.fromisoformat(str(last.get("at")))
            if datetime.now(timezone.utc) - last_run < timedelta(
                minutes=settings.open_position_news_guard_interval_minutes
            ):
                return False
        except ValueError:
            pass
    store.set_runtime_value(
        key,
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "symbols": fingerprint,
        },
    )
    return True


def _run_open_position_news_guard(
    settings: Settings,
    store: Store,
    reporter: EventReporter,
    run_id: str,
    portfolio: Any,
) -> dict[str, Any] | None:
    if not (
        settings.news_sentiment_enabled
        and settings.open_position_news_guard_enabled
        and portfolio.positions
    ):
        return None

    candidates = _position_news_candidates(portfolio)
    symbols = [item["symbol"] for item in candidates]
    if not _open_position_news_guard_due(settings, store, symbols):
        reporter.emit(
            "macro_news_researcher",
            "open_position_news_guard_blocked",
            run_id,
            (
                "Guardia de noticias de posiciones omitida por intervalo. "
                f"Simbolos: {', '.join(symbols)}."
            ),
            {
                "symbols": symbols,
                "interval_minutes": settings.open_position_news_guard_interval_minutes,
            },
        )
        return None

    reporter.emit(
        "macro_news_researcher",
        "open_position_news_guard_started",
        run_id,
        f"Validando noticias para posiciones abiertas: {', '.join(symbols)}.",
        {
            "symbols": symbols,
            "news_items_per_symbol": settings.news_items_per_symbol,
        },
    )
    try:
        report = analyze_news_sentiment_for_candidates(
            settings,
            candidates,
            settings.data_dir / "reports",
            run_id,
            max_news_items=settings.news_items_per_symbol,
        )
    except Exception as exc:  # noqa: BLE001 - portfolio watch must keep running.
        reporter.emit(
            "macro_news_researcher",
            "open_position_news_guard_failed",
            run_id,
            f"Guardia de noticias de posiciones fallida: {exc}",
            {"symbols": symbols, "error": repr(exc)},
        )
        return None
    material = [
        item["symbol"]
        for item in report.get("results", [])
        if item.get("material_risk", {}).get("material")
    ]
    unknown = [
        item["symbol"]
        for item in report.get("results", [])
        if item.get("material_risk", {}).get("unknown")
    ]
    reporter.emit(
        "macro_news_researcher",
        "open_position_news_guard_completed",
        run_id,
        (
            "Noticias de posiciones revisadas. "
            f"Riesgo material: {', '.join(material) or 'ninguno'}. "
            f"Riesgo desconocido: {', '.join(unknown) or 'ninguno'}."
        ),
        {
            "path": report.get("path"),
            "symbols_analyzed": report.get("symbols_analyzed"),
            "material_risk_symbols": material,
            "unknown_risk_symbols": unknown,
            "warnings": report.get("warnings", [])[:10],
        },
    )
    return report


def portfolio_watch_job(
    settings: Settings,
    store: Store,
    verbose: bool = True,
    *,
    force_notify: bool = False,
) -> None:
    run_id = new_id("watch")
    started_at = datetime.now(timezone.utc)
    calendar = MarketCalendar(settings.market_calendar, settings.local_timezone)
    status = calendar.status()
    reporter = _reporter(settings, store, verbose)

    if not status.is_open:
        closed_key = status.next_open or status.reason
        state_key = "portfolio_watch_last_closed_notification"
        if not force_notify and store.get_runtime_value(state_key) == closed_key:
            _set_job_status(store, "portfolio_watch", status="skipped", run_id=run_id, started_at=started_at, detail="mercado cerrado; notificacion ya emitida")
            return
        store.set_runtime_value(state_key, closed_key)
        reporter.emit(
            "portfolio_manager",
            "portfolio_watch_sleeping",
            run_id,
            f"Mercado cerrado. Monitor intradia en espera hasta la proxima apertura: {status.next_open}.",
            status.as_dict(),
        )
        _set_job_status(store, "portfolio_watch", status="completed", run_id=run_id, started_at=started_at, detail="mercado cerrado; monitor en espera", extra={"market_open": False})
        return

    portfolio = None
    watch_message = f"Revisando cartera. Mercado abierto: {status.is_open}."
    watch_payload: dict[str, Any] = status.as_dict()
    has_activity = False
    try:
        portfolio = BrokerClientFactory(settings).alpaca_portfolio_snapshot()
        has_activity = bool(portfolio.positions or portfolio.open_orders)
        watch_payload.update(
            {
                "cash": portfolio.cash,
                "portfolio_value": portfolio.portfolio_value,
                "positions_count": len(portfolio.positions),
                "open_orders_count": len(portfolio.open_orders),
            }
        )
        if has_activity:
            symbols = sorted(
                {
                    *(position.symbol for position in portfolio.positions),
                    *(order.symbol for order in portfolio.open_orders),
                }
            )
            watch_message = (
                "Cartera con actividad: "
                f"{len(portfolio.positions)} posiciones, {len(portfolio.open_orders)} ordenes abiertas. "
                f"Simbolos: {', '.join(symbols)}."
            )
    except Exception as exc:  # noqa: BLE001 - watch must keep scheduler alive.
        has_activity = True
        watch_message = f"No se pudo leer cartera Alpaca: {exc}"
        watch_payload.update({"error": repr(exc)})

    store.set_runtime_value("portfolio_watch_last_closed_notification", "")
    event_type = "portfolio_watch_started" if has_activity else "portfolio_watch_heartbeat"
    reporter.emit(
        "portfolio_manager",
        event_type,
        run_id,
        watch_message,
        watch_payload,
    )

    risk_message = "Mercado abierto: cartera sin posiciones ni ordenes; sin accion intradia."
    if has_activity:
        risk_message = "Mercado abierto: se revisan posiciones, PnL, ordenes abiertas y limites."
    reporter.emit(
        "risk_manager",
        "intraday_risk_check" if has_activity else "intraday_risk_heartbeat",
        run_id,
        risk_message,
        {
            **status.as_dict(),
            "broker": settings.broker,
            "configured": bool(settings.alpaca_api_key and settings.alpaca_secret_key),
            "paper": settings.alpaca_paper,
            "endpoint": settings.alpaca_endpoint,
            "positions_count": len(portfolio.positions) if portfolio else 0,
            "open_orders_count": len(portfolio.open_orders) if portfolio else 0,
        },
    )
    if portfolio and portfolio.positions:
        _run_open_position_news_guard(settings, store, reporter, run_id, portfolio)
        _execute_stop_take_exits(settings, store, reporter, run_id, portfolio)

    reporter.emit(
        "portfolio_manager",
        "portfolio_watch_completed" if has_activity else "portfolio_watch_heartbeat_completed",
        run_id,
        "Monitor de cartera finalizado.",
        status.as_dict(),
    )
    _set_job_status(
        store,
        "portfolio_watch",
        status="completed",
        run_id=run_id,
        started_at=started_at,
        detail="monitor de cartera finalizado",
        extra={"market_open": True, "has_activity": has_activity},
    )


def market_cycle_job(
    settings: Settings,
    store: Store,
    *,
    use_crew: bool,
    verbose: bool = True,
) -> None:
    run_id = new_id("mkt")
    started_at = datetime.now(timezone.utc)
    calendar = MarketCalendar(settings.market_calendar, settings.local_timezone)
    status = calendar.status()
    reporter = _reporter(settings, store, verbose)

    reporter.emit(
        "orchestrator",
        "scheduled_market_cycle_check",
        run_id,
        f"Comprobando ciclo de 15 minutos. Mercado abierto: {status.is_open}.",
        status.as_dict(),
    )
    if not status.is_open:
        reporter.emit(
            "orchestrator",
            "scheduled_market_cycle_skipped",
            run_id,
            f"Ciclo intradia omitido porque el mercado esta cerrado. {status.reason}",
            status.as_dict(),
        )
        _set_job_status(store, "market_cycle", status="skipped", run_id=run_id, started_at=started_at, detail="mercado cerrado")
        return

    cycle_settings = settings
    technical_context: dict[str, Any] | None = None
    if settings.intraday_technical_scan_enabled:
        universe_name = settings.intraday_technical_scan_universe or settings.closed_market_study_universe
        max_symbols = settings.intraday_technical_scan_max_symbols or settings.closed_market_study_max_symbols
        reporter.emit(
            "technical_analyst",
            "intraday_technical_scan_started",
            run_id,
            f"Escaneo tecnico intradia iniciado: {universe_name}, max {max_symbols} simbolos.",
            {"universe": universe_name, "max_symbols": max_symbols},
        )
        symbols = resolve_study_universe(
            universe_name,
            settings.universe,
            max_symbols,
            settings.data_dir / "cache",
        )
        report = build_closed_market_technical_study(
            symbols,
            settings.data_dir / "reports",
            run_id,
            benchmark_symbol=settings.benchmark_symbol,
        )
        signals_saved = record_signal_candidates(store, report, source="intraday_scan")
        selected_candidates, selected_symbols = _selected_candidates(report, settings)
        top_longs = ", ".join(item["symbol"] for item in report["top_longs"][:5]) or "sin candidatos"
        top_shorts = ", ".join(item["symbol"] for item in report["top_shorts"][:5]) or "sin candidatos"
        reporter.emit(
            "technical_analyst",
            "intraday_technical_scan_completed",
            run_id,
            f"Escaneo tecnico listo. Largos: {top_longs}. Cortos: {top_shorts}.",
            {
                "path": report["path"],
                "symbols_scanned": report["symbols_scanned"],
                "symbols_with_data": report["symbols_with_data"],
                "signals_saved": signals_saved,
                "selected_symbols": selected_symbols,
                "analysis_plan_counts": report["analysis_plan_counts"],
            },
        )
        technical_context = _compact_scan_context(report, selected_candidates)

        try:
            breakout_symbols = merge_breakout_universe(symbols, settings.breakout_watchlist)
            breakout_report = build_breakout_scan(
                breakout_symbols,
                settings.data_dir / "reports",
                run_id,
            )
            confirmed = breakout_report.get("confirmed", [])
            tradable = [item for item in confirmed if item.get("tradable")]
            watch = breakout_report.get("watch", [])
            blocked = breakout_report.get("blocked_or_failed", [])
            confirmed_text = ", ".join(
                f"{item['symbol']} ({item['risk_level']})" for item in confirmed[:5]
            ) or "ninguna"
            watch_text = ", ".join(item["symbol"] for item in watch[:5]) or "ninguna"
            reporter.emit(
                "technical_analyst",
                "intraday_breakout_scan_completed",
                run_id,
                (
                    "Rupturas revisadas. "
                    f"Confirmadas: {confirmed_text}. Vigilancia: {watch_text}. "
                    f"Operables conservadoras: {len(tradable)}; bloqueadas/fallidas: {len(blocked)}."
                ),
                {
                    "path": breakout_report["path"],
                    "symbols_scanned": breakout_report["symbols_scanned"],
                    "confirmed": confirmed[:10],
                    "watch": watch[:10],
                    "tradable_symbols": [item["symbol"] for item in tradable[:10]],
                    "blocked_or_failed_count": len(blocked),
                    "warnings": breakout_report["warnings"][:10],
                },
            )
            if technical_context is not None:
                technical_context["breakout_scan_path"] = breakout_report["path"]
                technical_context["breakout_confirmed"] = confirmed[:5]
                technical_context["breakout_watch"] = watch[:5]
        except Exception as exc:  # noqa: BLE001 - breakout scan must not block the cycle.
            reporter.emit(
                "technical_analyst",
                "intraday_breakout_scan_failed",
                run_id,
                f"Escaneo de rupturas fallido: {exc}",
                {"error": repr(exc)},
            )

        if settings.news_sentiment_enabled and settings.intraday_news_sentiment_enabled and use_crew and selected_candidates:
            reporter.emit(
                "macro_news_researcher",
                "intraday_news_sentiment_started",
                run_id,
                f"Validando noticias intradia para {len(selected_candidates)} candidatos tecnicos.",
                {
                    "symbols": [item["symbol"] for item in selected_candidates],
                    "news_items_per_symbol": settings.news_items_per_symbol,
                },
            )
            sentiment_report = analyze_news_sentiment_for_candidates(
                settings,
                selected_candidates,
                settings.data_dir / "reports",
                run_id,
                max_news_items=settings.news_items_per_symbol,
            )
            supportive = [
                item["symbol"]
                for item in sentiment_report["results"]
                if item.get("sentiment", {}).get("supports_technical_setup")
            ]
            reporter.emit(
                "macro_news_researcher",
                "intraday_news_sentiment_completed",
                run_id,
                f"Noticias intradia listas. Apoyan tesis: {', '.join(supportive) or 'sin apoyos claros'}.",
                {
                    "path": sentiment_report["path"],
                    "symbols_analyzed": sentiment_report["symbols_analyzed"],
                    "supportive": supportive,
                    "warnings": sentiment_report["warnings"][:10],
                },
            )
            if technical_context is not None:
                technical_context["news_sentiment_path"] = sentiment_report["path"]
                technical_context["news_supportive_symbols"] = supportive

        if selected_symbols:
            cycle_settings = settings.model_copy(update={"default_universe": ",".join(selected_symbols)})
            reporter.emit(
                "orchestrator",
                "intraday_candidate_universe_selected",
                run_id,
                f"Ciclo LLM usara candidatos tecnicos: {', '.join(selected_symbols)}.",
                {"selected_symbols": selected_symbols},
            )

    try:
        run_observable_cycle(
            cycle_settings,
            store,
            use_crew=use_crew,
            verbose=verbose,
            technical_context=technical_context,
        )
        _set_job_status(
            store,
            "market_cycle",
            status="completed",
            run_id=run_id,
            started_at=started_at,
            detail="ciclo de mercado ejecutado",
            extra={
                "selected_symbols": [item.get("symbol") for item in (technical_context.get("selected_candidates", []) if technical_context else [])],
                "technical_report": technical_context.get("path") if technical_context else None,
            },
        )
    except Exception as exc:
        _set_job_status(
            store,
            "market_cycle",
            status="failed",
            run_id=run_id,
            started_at=started_at,
            detail=str(exc),
            extra={"error_type": type(exc).__name__},
        )
        raise


def closed_market_technical_study_job(
    settings: Settings,
    store: Store,
    *,
    use_crew: bool,
    verbose: bool = True,
    force: bool = False,
) -> None:
    run_id = new_id("closed")
    started_at = datetime.now(timezone.utc)
    calendar = MarketCalendar(settings.market_calendar, settings.local_timezone)
    status = calendar.status()
    if status.is_open:
        _set_job_status(store, "closed_market_technical_study", status="skipped", run_id=run_id, started_at=started_at, detail="mercado abierto")
        return

    study_key = "|".join(
        [
            status.next_open or status.now_market[:10],
            settings.closed_market_study_universe,
            str(settings.closed_market_study_max_symbols),
            f"crew={use_crew}",
        ]
    )
    state_key = "closed_market_technical_study_last_run"
    if not force and store.get_runtime_value(state_key) == study_key:
        _set_job_status(store, "closed_market_technical_study", status="skipped", run_id=run_id, started_at=started_at, detail="estudio ya ejecutado para la sesion objetivo")
        return

    reporter = _reporter(settings, store, verbose)
    reporter.emit(
        "technical_analyst",
        "closed_market_study_started",
        run_id,
        "Mercado cerrado: lanzando estudio tecnico amplio para preparar posibles largos/cortos.",
        status.as_dict(),
    )

    reporter.emit(
        "market_data_researcher",
        "closed_market_universe_loading",
        run_id,
        f"Cargando universo {settings.closed_market_study_universe}. Si es top por capitalizacion puede tardar.",
        {
            "universe": settings.closed_market_study_universe,
            "max_symbols": settings.closed_market_study_max_symbols,
        },
    )
    symbols = resolve_study_universe(
        settings.closed_market_study_universe,
        settings.universe,
        settings.closed_market_study_max_symbols,
        settings.data_dir / "cache",
    )
    reporter.emit(
        "market_data_researcher",
        "closed_market_universe_loaded",
        run_id,
        f"Universo de estudio cargado: {len(symbols)} simbolos.",
        {"universe": settings.closed_market_study_universe, "symbols_count": len(symbols)},
    )
    reporter.emit(
        "market_data_researcher",
        "closed_market_download_started",
        run_id,
        "Descargando historico y preparando validacion tecnica profunda por simbolo.",
        {"symbols_count": len(symbols)},
    )

    def _progress(done: int, total: int, with_data: int) -> None:
        reporter.emit(
            "technical_analyst",
            "closed_market_study_progress",
            run_id,
            f"Analizados {done}/{total} simbolos. Con datos validos: {with_data}.",
            {"done": done, "total": total, "with_data": with_data},
        )

    report = build_closed_market_technical_study(
        symbols,
        settings.data_dir / "reports",
        run_id,
        progress_callback=_progress,
        benchmark_symbol=settings.benchmark_symbol,
    )
    signals_saved = record_signal_candidates(store, report, source="closed_market_study")
    top_longs = ", ".join(item["symbol"] for item in report["top_longs"][:5]) or "sin candidatos"
    top_shorts = ", ".join(item["symbol"] for item in report["top_shorts"][:5]) or "sin candidatos"
    reporter.emit(
        "technical_analyst",
        "closed_market_study_completed",
        run_id,
        f"Estudio tecnico guardado. Largos: {top_longs}. Cortos: {top_shorts}.",
        {
            "path": report["path"],
            "symbols_scanned": report["symbols_scanned"],
            "symbols_with_data": report["symbols_with_data"],
            "signals_saved": signals_saved,
            "top_longs": report["top_longs"][:5],
            "top_shorts": report["top_shorts"][:5],
            "analysis_plan_counts": report["analysis_plan_counts"],
            "warnings": report["warnings"][:10],
            "tool_requests": report["tool_requests"][:10],
        },
    )
    if report.get("tool_requests"):
        reporter.emit(
            "self_improvement_engineer",
            "technical_tool_requests_created",
            run_id,
            f"El analista tecnico solicito {len(report['tool_requests'])} mejoras/herramientas.",
            {"tool_requests": report["tool_requests"][:10]},
        )

    candidate_limit_per_side = max(1, settings.news_sentiment_top_n // 2)
    selected_symbols = sorted(
        {
            item["symbol"]
            for item in [
                *report["top_longs"][:candidate_limit_per_side],
                *report["top_shorts"][:candidate_limit_per_side],
            ]
        }
    )
    selected_candidates = [
        *report["top_longs"][:candidate_limit_per_side],
        *report["top_shorts"][:candidate_limit_per_side],
    ]

    if settings.news_sentiment_enabled and use_crew and selected_candidates:
        reporter.emit(
            "macro_news_researcher",
            "news_sentiment_started",
            run_id,
            (
                "Descargando ultimas noticias y validando sentimiento con LLM "
                f"para {len(selected_candidates)} candidatos tecnicos."
            ),
            {
                "symbols": [item["symbol"] for item in selected_candidates],
                "news_items_per_symbol": settings.news_items_per_symbol,
            },
        )

        def _sentiment_progress(done: int, total: int, symbol: str) -> None:
            reporter.emit(
                "macro_news_researcher",
                "news_sentiment_progress",
                run_id,
                f"Sentimiento validado {done}/{total}: {symbol}.",
                {"done": done, "total": total, "symbol": symbol},
            )

        sentiment_report = analyze_news_sentiment_for_candidates(
            settings,
            selected_candidates,
            settings.data_dir / "reports",
            run_id,
            max_news_items=settings.news_items_per_symbol,
            progress_callback=_sentiment_progress,
        )
        supportive = [
            item["symbol"]
            for item in sentiment_report["results"]
            if item.get("sentiment", {}).get("supports_technical_setup")
        ]
        reporter.emit(
            "macro_news_researcher",
            "news_sentiment_completed",
            run_id,
            (
                "Sentimiento guardado. "
                f"Apoyan tesis tecnica: {', '.join(supportive) or 'sin apoyos claros'}."
            ),
            {
                "path": sentiment_report["path"],
                "symbols_analyzed": sentiment_report["symbols_analyzed"],
                "supportive": supportive,
                "warnings": sentiment_report["warnings"][:10],
            },
        )

    if use_crew and selected_symbols:
        reporter.emit(
            "orchestrator",
            "closed_market_crew_started",
            run_id,
            f"Lanzando CrewAI sobre candidatos filtrados: {', '.join(selected_symbols)}.",
            {"selected_symbols": selected_symbols},
        )
        study_settings = settings.model_copy(
            update={"default_universe": ",".join(selected_symbols)}
        )
        try:
            run_observable_cycle(study_settings, store, use_crew=True, verbose=verbose)
        except Exception as exc:  # noqa: BLE001 - scheduler must keep running after LLM failures.
            reporter.emit(
                "orchestrator",
                "closed_market_crew_failed",
                run_id,
                f"CrewAI/LLM fallo durante el estudio cerrado: {exc}",
                {"selected_symbols": selected_symbols, "error": repr(exc)},
            )

    store.set_runtime_value(state_key, study_key)
    _set_job_status(
        store,
        "closed_market_technical_study",
        status="completed",
        run_id=run_id,
        started_at=started_at,
        detail="estudio tecnico cerrado completado",
        extra={"report_path": report.get("path"), "signals_saved": signals_saved},
    )


def daily_study_job(
    settings: Settings,
    store: Store,
    *,
    use_crew: bool,
    verbose: bool = True,
) -> None:
    run_id = new_id("daily")
    started_at = datetime.now(timezone.utc)
    calendar = MarketCalendar(settings.market_calendar, settings.local_timezone)
    should_run, status = calendar.should_run_daily_study()
    reporter = _reporter(settings, store, verbose)
    reporter.emit(
        "self_improvement_engineer",
        "daily_study_check",
        run_id,
        f"Comprobando estudio diario. Debe ejecutarse: {should_run}.",
        status.as_dict(),
    )
    if not should_run:
        reporter.emit(
            "self_improvement_engineer",
            "daily_study_skipped",
            run_id,
            "Estudio diario omitido: no es dia de sesion cerrada o todavia esta abierto.",
            status.as_dict(),
        )
        _set_job_status(store, "daily_study", status="skipped", run_id=run_id, started_at=started_at, detail="no corresponde ejecutar estudio diario")
        return

    reporter.emit(
        "self_improvement_engineer",
        "daily_study_started",
        run_id,
        "Ejecutando estudio diario: revisar hipotesis, resultados, mejoras y backlog.",
        status.as_dict(),
    )
    try:
        run_observable_cycle(settings, store, use_crew=use_crew, verbose=verbose)
    except Exception as exc:
        _set_job_status(store, "daily_study", status="failed", run_id=run_id, started_at=started_at, detail=str(exc), extra={"error_type": type(exc).__name__})
        raise
    reporter.emit(
        "self_improvement_engineer",
        "daily_study_completed",
        run_id,
        "Estudio diario finalizado.",
        status.as_dict(),
    )
    _set_job_status(store, "daily_study", status="completed", run_id=run_id, started_at=started_at, detail="estudio diario finalizado")


def post_market_review_job(
    settings: Settings,
    store: Store,
    *,
    use_llm: bool,
    verbose: bool = True,
    force: bool = False,
) -> dict[str, Any] | None:
    if not settings.post_market_review_enabled and not force:
        return None

    run_id = new_id("pmr")
    started_at = datetime.now(timezone.utc)
    calendar = MarketCalendar(settings.market_calendar, settings.local_timezone)
    should_run, status = calendar.should_run_daily_study()
    reporter = _reporter(settings, store, verbose)
    if not should_run and not force:
        _set_job_status(store, "post_market_review", status="skipped", run_id=run_id, started_at=started_at, detail="mercado aun no apto para review")
        return None

    session_date = datetime.fromisoformat(status.now_market).date().isoformat()
    state_key = "post_market_review_last_session"
    if not force and store.get_runtime_value(state_key) == session_date:
        _set_job_status(store, "post_market_review", status="skipped", run_id=run_id, started_at=started_at, detail="review ya ejecutado para la sesion")
        return None

    reporter.emit(
        "post_market_review_agent",
        "post_market_review_started",
        run_id,
        f"Revision post-mercado iniciada para {session_date}: operaciones, aciertos, errores y mejoras minimas.",
        status.as_dict(),
    )
    try:
        report = build_post_market_review(
            settings,
            settings.data_dir / "reports",
            run_id,
            session_date=session_date,
            use_llm=use_llm and settings.post_market_review_use_llm,
        )
        store.set_runtime_value(state_key, session_date)
        improvements = report.get("proposed_improvements", [])
        reporter.emit(
            "post_market_review_agent",
            "post_market_review_completed",
            run_id,
            (
                f"Revision post-mercado guardada. Trades evaluados: "
                f"{report['summary']['trades_evaluated']}. Mejoras propuestas: {len(improvements)}."
            ),
            {
                "path": report["path"],
                "session_date": session_date,
                "summary": report["summary"],
                "proposed_improvements": improvements[:5],
                "next_session_guidance": report.get("next_session_guidance", [])[:8],
            },
        )
        _set_job_status(store, "post_market_review", status="completed", run_id=run_id, started_at=started_at, detail="review post-mercado completado", extra={"report_path": report.get("path")})
        return report
    except Exception as exc:  # noqa: BLE001 - scheduler must keep running.
        reporter.emit(
            "post_market_review_agent",
            "post_market_review_failed",
            run_id,
            f"Revision post-mercado fallida: {exc}",
            {"error": repr(exc), "session_date": session_date},
        )
        _set_job_status(store, "post_market_review", status="failed", run_id=run_id, started_at=started_at, detail=str(exc), extra={"error_type": type(exc).__name__})
        return None


def _daily_hour_minute(value: str) -> tuple[int, int]:
    hour_text, minute_text = value.split(":", maxsplit=1)
    return int(hour_text), int(minute_text)


def _pre_earnings_run_time_reached(settings: Settings, status: Any) -> bool:
    now_utc_raw = getattr(status, "now_utc", None)
    close_raw = getattr(status, "market_close", None) or getattr(status, "next_close", None)
    if now_utc_raw and close_raw and settings.pre_earnings_before_close_minutes >= 0:
        try:
            now_utc = datetime.fromisoformat(str(now_utc_raw)).astimezone(timezone.utc)
            market_close = datetime.fromisoformat(str(close_raw)).astimezone(timezone.utc)
            return now_utc >= market_close - timedelta(minutes=settings.pre_earnings_before_close_minutes)
        except ValueError:
            pass

    now_market = datetime.fromisoformat(status.now_market)
    run_hour, run_minute = _daily_hour_minute(settings.pre_earnings_time_market)
    run_time = now_market.replace(hour=run_hour, minute=run_minute, second=0, microsecond=0)
    return now_market >= run_time


def pre_earnings_job(
    settings: Settings,
    store: Store,
    *,
    verbose: bool = True,
    force: bool = False,
) -> dict[str, Any] | None:
    if not settings.pre_earnings_enabled and not force:
        return None

    run_id = new_id("preearn")
    started_at = datetime.now(timezone.utc)
    calendar = MarketCalendar(settings.market_calendar, settings.local_timezone)
    status = calendar.status()
    reporter = _reporter(settings, store, verbose)

    if not status.is_open and not force:
        _set_job_status(store, "pre_earnings", status="skipped", run_id=run_id, started_at=started_at, detail="mercado cerrado")
        return None

    if not _pre_earnings_run_time_reached(settings, status) and not force:
        _set_job_status(store, "pre_earnings", status="skipped", run_id=run_id, started_at=started_at, detail="ventana temporal aun no alcanzada")
        return None

    now_market = datetime.fromisoformat(status.now_market)
    session_date = status.session_date or now_market.date().isoformat()
    universe_name = settings.pre_earnings_universe or settings.closed_market_study_universe
    max_symbols = settings.pre_earnings_max_symbols or settings.closed_market_study_max_symbols
    state_key = "pre_earnings_last_session"
    study_key = "|".join([session_date, universe_name, str(max_symbols), str(settings.pre_earnings_days)])
    if not force and store.get_runtime_value(state_key) == study_key:
        _set_job_status(store, "pre_earnings", status="skipped", run_id=run_id, started_at=started_at, detail="estudio pre-earnings ya ejecutado para la sesion")
        return None

    reporter.emit(
        "market_data_researcher",
        "pre_earnings_started",
        run_id,
        (
            "Estudio pre-earnings informativo iniciado antes del cierre. "
            f"Universo {universe_name}, max {max_symbols}, dias {settings.pre_earnings_days}. "
            f"Disparo: {settings.pre_earnings_before_close_minutes} min antes del cierre."
        ),
        {**status.as_dict(), "universe": universe_name, "max_symbols": max_symbols},
    )
    try:
        symbols = resolve_study_universe(
            universe_name,
            settings.universe,
            max_symbols,
            settings.data_dir / "cache",
        )
        report = build_pre_earnings_report(
            symbols=symbols,
            output_dir=settings.data_dir / "reports",
            run_id=run_id,
            calendar_name=settings.market_calendar,
            local_timezone=settings.local_timezone,
            session_count=settings.pre_earnings_days,
            cache_dir=settings.data_dir / "cache",
            fmp_api_key=settings.fmp_api_key,
        )
        tracking_update = update_pre_earnings_outcomes(store)
        local_analyst_revisions = enrich_report_with_local_analyst_revisions(store, report)
        score_v2_items_updated = enrich_report_with_pre_earnings_score_v2(store, report)
        predictions_saved = record_pre_earnings_predictions(store, report)
        analyst_snapshots_saved = record_pre_earnings_analyst_snapshots(store, report)
        estimates_backfill = backfill_pending_pre_earnings_estimates(
            store,
            settings.data_dir / "reports",
            f"{run_id}_backfill",
            api_key=settings.fmp_api_key,
        )
        learning_digest = build_pre_earnings_learning_digest(
            store,
            settings.data_dir / "reports",
            f"{run_id}_digest",
            since_date="2026-04-01",
        )
        build_learning_digest_report(
            store,
            settings.data_dir / "reports",
            new_id("learn_digest_refresh"),
        )
        trading_operation = _run_pre_earnings_trade_operation(
            settings,
            store,
            reporter,
            run_id,
            report,
        )
        store.set_runtime_value(state_key, study_key)
        summary = report.get("summary", {}) or {}
        success = summary.get("success_rate")
        success_text = "sin datos" if success is None else f"{success:.2%}"
        report["mode"] = (
            "operativo_pre_earnings" if settings.pre_earnings_trade_enabled else "informativo_no_operativo"
        )
        report["operation_allowed"] = settings.pre_earnings_trade_enabled
        report["trading_operation"] = trading_operation
        reporter.emit(
            "market_data_researcher",
            "pre_earnings_completed",
            run_id,
            (
                "Estudio pre-earnings guardado. "
                f"Eventos: {summary.get('total_events', 0)}; pendientes: {summary.get('pending_count', 0)}; "
                f"exito historico visible: {success_text}; "
                f"senales operativas: {len(trading_operation.get('recommendations', []))}; "
                f"planes buy: {len(trading_operation.get('buy_order_plans', []))}."
            ),
            {
                "path": report["path"],
                "session_date": report.get("session_date"),
                "session_count": report.get("session_count"),
                "summary": summary,
                "operation_allowed": report.get("operation_allowed"),
                "predictions_saved": predictions_saved,
                "analyst_snapshots_saved": analyst_snapshots_saved,
                "local_analyst_revisions": local_analyst_revisions,
                "score_v2_items_updated": score_v2_items_updated,
                "estimates_backfill": estimates_backfill,
                "tracking_update": tracking_update,
                "learning_digest_path": learning_digest.get("path"),
                "trading_operation": trading_operation,
            },
        )
        report["tracking_update"] = tracking_update
        report["local_analyst_revisions"] = local_analyst_revisions
        report["score_v2_items_updated"] = score_v2_items_updated
        report["predictions_saved"] = predictions_saved
        report["analyst_snapshots_saved"] = analyst_snapshots_saved
        report["estimates_backfill"] = estimates_backfill
        report["learning_digest"] = learning_digest
        _set_job_status(store, "pre_earnings", status="completed", run_id=run_id, started_at=started_at, detail="estudio pre-earnings completado", extra={"report_path": report.get("path")})
        return report
    except Exception as exc:  # noqa: BLE001 - scheduler must keep running.
        reporter.emit(
            "market_data_researcher",
            "pre_earnings_failed",
            run_id,
            f"Estudio pre-earnings fallido: {exc}",
            {"error": repr(exc), **status.as_dict()},
        )
        _set_job_status(store, "pre_earnings", status="failed", run_id=run_id, started_at=started_at, detail=str(exc), extra={"error_type": type(exc).__name__})
        return None


def build_scheduler(settings: Settings, store: Store, *, use_crew: bool, verbose: bool) -> Any:
    if BackgroundScheduler is None or CronTrigger is None or IntervalTrigger is None:
        raise RuntimeError("APScheduler no esta instalado. Instala las dependencias del proyecto para usar schedule.")
    local_tz = ZoneInfo(settings.local_timezone)
    scheduler = BackgroundScheduler(timezone=local_tz)
    daily_hour, daily_minute = _daily_hour_minute(settings.daily_study_time_local)

    scheduler.add_job(
        portfolio_watch_job,
        trigger=IntervalTrigger(seconds=settings.portfolio_watch_interval_seconds),
        args=[settings, store, verbose],
        id="portfolio_watch_1m",
        name="Portfolio watch every minute",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_job(
        market_cycle_job,
        trigger=IntervalTrigger(minutes=settings.market_cycle_interval_minutes),
        args=[settings, store],
        kwargs={"use_crew": use_crew, "verbose": verbose},
        id="market_cycle_15m",
        name="Market cycle every 15 minutes",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_job(
        closed_market_technical_study_job,
        trigger=IntervalTrigger(minutes=settings.closed_market_study_interval_minutes),
        args=[settings, store],
        kwargs={"use_crew": use_crew, "verbose": verbose},
        id="closed_market_technical_study",
        name="Closed-market technical study",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_job(
        daily_study_job,
        trigger=CronTrigger(hour=daily_hour, minute=daily_minute, timezone=local_tz),
        args=[settings, store],
        kwargs={"use_crew": use_crew, "verbose": verbose},
        id="daily_study",
        name="Daily study after US market close",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_job(
        post_market_review_job,
        trigger=IntervalTrigger(minutes=settings.closed_market_study_interval_minutes),
        args=[settings, store],
        kwargs={"use_llm": use_crew, "verbose": verbose},
        id="post_market_review",
        name="Post-market trade review once per closed session",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_job(
        pre_earnings_job,
        trigger=IntervalTrigger(minutes=settings.closed_market_study_interval_minutes),
        args=[settings, store],
        kwargs={"verbose": verbose},
        id="pre_earnings_daily",
        name="Pre-earnings informative study before US close",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    return scheduler


def run_scheduler_forever(settings: Settings, store: Store, *, use_crew: bool, verbose: bool) -> None:
    store.ensure_schema()
    cleanup_runtime_data(settings)
    acquired, reason = _acquire_scheduler_lock(settings)
    if not acquired:
        EventReporter(store, verbose=verbose).emit(
            "orchestrator",
            "scheduler_already_running",
            new_id("sched"),
            reason,
            {"lock_path": str(_scheduler_lock_path(settings))},
        )
        return
    scheduler = build_scheduler(settings, store, use_crew=use_crew, verbose=verbose)
    scheduler.start()
    jobs = [{"id": job.id, "name": job.name, "next_run_time": str(job.next_run_time)} for job in scheduler.get_jobs()]
    log_system_event(settings.logs_dir, "scheduler_started", {"jobs": jobs})
    EventReporter(store, verbose=verbose).emit(
        "orchestrator",
        "scheduler_started",
        new_id("sched"),
        "Scheduler iniciado: vigilancia intradia, pre-earnings, ciclos de mercado y estudios con mercado cerrado.",
        {"jobs": jobs},
    )
    portfolio_watch_job(settings, store, verbose=verbose, force_notify=True)
    bootstrap_status = MarketCalendar(settings.market_calendar, settings.local_timezone).status()
    try:
        if bootstrap_status.is_open:
            pre_earnings_job(settings, store, verbose=verbose)
            market_cycle_job(settings, store, use_crew=use_crew, verbose=verbose)
        else:
            closed_market_technical_study_job(settings, store, use_crew=use_crew, verbose=verbose)
            post_market_review_job(settings, store, use_llm=use_crew, verbose=verbose)
    except Exception as exc:  # noqa: BLE001 - keep scheduler alive and visible.
        EventReporter(store, verbose=verbose).emit(
            "orchestrator",
            "scheduler_bootstrap_failed",
            new_id("sched"),
            f"El trabajo inicial fallo, pero el scheduler sigue vivo: {exc}",
            {"error": repr(exc)},
        )
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        LOGGER.info("Deteniendo scheduler.")
        scheduler.shutdown(wait=False)
        log_system_event(settings.logs_dir, "scheduler_stopped", {})
    finally:
        _release_scheduler_lock(settings)


def scheduler_status(settings: Settings) -> dict[str, object]:
    calendar = MarketCalendar(settings.market_calendar, settings.local_timezone)
    market_status = calendar.status()
    daily_hour, daily_minute = _daily_hour_minute(settings.daily_study_time_local)
    now_local = datetime.now(ZoneInfo(settings.local_timezone))
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    job_runtime = {
        job_name: store.get_runtime_value(_job_state_key(job_name))
        for job_name in [
            "portfolio_watch",
            "market_cycle",
            "closed_market_technical_study",
            "daily_study",
            "post_market_review",
            "pre_earnings",
        ]
    }
    return {
        "market": market_status.as_dict(),
        "jobs": [
            {
                "id": "portfolio_watch_1m",
                "cadence": f"cada {settings.portfolio_watch_interval_seconds} segundos",
                "market_behavior": "solo informa una vez si esta cerrado; cada minuto solo actua de verdad si NYSE esta abierto",
            },
            {
                "id": "market_cycle_15m",
                "cadence": f"cada {settings.market_cycle_interval_minutes} minutos",
                "market_behavior": "solo ejecuta ciclo de mercado si NYSE esta abierto; incluye scan tecnico, rupturas y LLM",
            },
            {
                "id": "closed_market_technical_study",
                "cadence": f"cada {settings.closed_market_study_interval_minutes} minutos como comprobador",
                "market_behavior": (
                    "si NYSE esta cerrado, ejecuta un estudio tecnico amplio una sola vez por "
                    "proxima apertura; incluye velas y sentimiento LLM sobre finalistas"
                ),
            },
            {
                "id": "daily_study",
                "cadence": f"cada dia a las {daily_hour:02d}:{daily_minute:02d} {settings.local_timezone}",
                "market_behavior": "solo ejecuta si fue dia de mercado y la sesion ya cerro",
            },
            {
                "id": "post_market_review",
                "cadence": f"cada {settings.closed_market_study_interval_minutes} minutos como comprobador",
                "market_behavior": "tras cierre, una vez por sesion, revisa compras/ventas y genera aprendizaje",
            },
            {
                "id": "pre_earnings_daily",
                "cadence": f"cada {settings.closed_market_study_interval_minutes} minutos como comprobador",
                "market_behavior": (
                    "si NYSE esta abierto y faltan "
                    f"{settings.pre_earnings_before_close_minutes} minutos o menos para el cierre, "
                    "ejecuta una vez por sesion el estudio pre-earnings informativo"
                ),
            },
        ],
        "now_local": now_local.isoformat(),
        "job_runtime": job_runtime,
    }
