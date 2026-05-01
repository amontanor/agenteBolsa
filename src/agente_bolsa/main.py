"""Command line entrypoint."""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .agent_registry import AGENTS
from .config import get_settings
from .cycle_runner import run_observable_cycle
from .eventing import PrettyLogPrinter, print_raw_tail_line
from .logging_utils import configure_logging, log_system_event
from .market_calendar import MarketCalendar
from .models import AgentEvent, Hypothesis, new_id
from .scheduler import (
    closed_market_technical_study_job,
    daily_study_job,
    market_cycle_job,
    post_market_review_job,
    portfolio_watch_job,
    run_scheduler_forever,
    scheduler_status,
)
from .storage import Store
from .tools.adaptive_tuning import adaptive_status, update_adaptive_config
from .tools.backtest import build_symbol_backtest
from .tools.broker import BrokerClientFactory
from .tools.breakout_scanner import build_breakout_scan, merge_breakout_universe
from .tools.command_catalog import available_command_catalog, command_cheatsheet
from .tools.trade_decision import (
    build_order_plans,
    filter_entry_quality,
    load_latest_sentiment,
    load_latest_technical_candidates,
    request_trade_recommendations,
)
from .tools.execution import submit_paper_order_plan
from .tools.operational_learning import build_operational_learning_review
from .tools.portfolio_optimizer import build_portfolio_rebalance_context
from .tools.post_market_review import build_post_market_review
from .tools.signal_learning import (
    build_learning_status,
    record_signal_candidates,
    update_signal_decisions,
    update_signal_outcomes,
    write_learning_report,
)
from .tools.symbol_study import build_symbol_study
from .tools.technical_study import build_closed_market_technical_study
from .tools.trade_history import DEFAULT_HISTORY_START_DATE, build_trade_history
from .tools.universe import resolve_study_universe


LOGGER = logging.getLogger(__name__)


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=True, default=str))


def _money(value: Any) -> str:
    try:
        return f"${float(value):.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "0.00%"


def _pl_item_text(item: dict[str, Any] | None) -> str:
    if not item:
        return "-"
    symbol = item.get("symbol") or "-"
    kind = item.get("kind") or "-"
    return f"{symbol} {_money(item.get('pl'))} ({_pct(item.get('plpc'))}) [{kind}]"


def _print_trade_history_summary_box(stats: dict[str, Any]) -> None:
    rows = [
        ("equity", _money(stats.get("equity"))),
        ("cash", f"{_money(stats.get('cash'))} ({_pct(stats.get('cash_pct'))})"),
        ("exposicion", f"{_money(stats.get('exposure'))} ({_pct(stats.get('exposure_pct'))})"),
        ("posiciones abiertas", str(stats.get("open_positions", 0))),
        ("comprado periodo", _money(stats.get("buy_notional"))),
        ("vendido periodo", _money(stats.get("sell_notional"))),
        ("P/L realizado", _money(stats.get("realized_pl"))),
        ("P/L abierto", _money(stats.get("unrealized_pl"))),
        ("P/L total", f"{_money(stats.get('total_pl'))} ({_pct(stats.get('total_plpc_on_equity'))} sobre equity)"),
        ("mayor ganancia", _pl_item_text(stats.get("biggest_gain"))),
        ("mayor perdida", _pl_item_text(stats.get("biggest_loss"))),
    ]
    width = max(len(label) + len(value) + 5 for label, value in rows)
    print("")
    print("+" + "-" * (width - 2) + "+")
    title = "RESUMEN GLOBAL ACTUAL"
    print("| " + title + " " * (width - len(title) - 3) + "|")
    print("+" + "-" * (width - 2) + "+")
    for label, value in rows:
        text = f"{label}: {value}"
        print("| " + text + " " * (width - len(text) - 3) + "|")
    print("+" + "-" * (width - 2) + "+")


def _post_market_review_text(report: dict[str, Any]) -> str:
    summary = report.get("summary", {}) or {}
    improvements = report.get("proposed_improvements", []) or []
    guidance = report.get("next_session_guidance", []) or []
    evaluations = report.get("trade_evaluations", []) or []
    llm_review = report.get("llm_review", {}) or {}

    lines = [
        f"REVISION POST-MERCADO {report.get('session_date', '')}",
        f"Informe: {report.get('path', '')}",
        (
            "Resumen: "
            f"trades={summary.get('trades_evaluated', 0)} | "
            f"compras={summary.get('buys', 0)} | ventas={summary.get('sells', 0)} | "
            f"posiciones abiertas={summary.get('open_positions', 0)}"
        ),
        (
            "Resultado dia: "
            f"comprado={_money(summary.get('day_buy_notional'))} | "
            f"vendido={_money(summary.get('day_sell_notional'))} | "
            f"P/L realizado={_money(summary.get('day_realized_pl'))} "
            f"({_pct(summary.get('day_realized_plpc'))}) | "
            f"P/L abierto actual={_money(summary.get('open_unrealized_pl'))}"
        ),
        "Aplicacion: no cambia codigo; actualiza memoria operativa y reglas shadow/active segun evidencia.",
    ]

    if evaluations:
        lines.append("")
        lines.append("Operaciones evaluadas:")
        interesting = [
            item
            for item in evaluations
            if item.get("side") == "sell" or item.get("issue") or item.get("verdict") != "pendiente"
        ]
        for item in (interesting or evaluations)[:8]:
            pl = item.get("realized_pl")
            if pl is None:
                pl = item.get("open_pl")
            reason = item.get("issue") or item.get("verdict") or "evaluada"
            lines.append(
                "  - "
                f"{str(item.get('side', '')).upper()} {item.get('symbol')} "
                f"{_money(item.get('notional'))} @ {item.get('price')} | "
                f"stop {item.get('stop_loss') or '-'} | take {item.get('take_profit') or '-'} | "
                f"P/L {_money(pl)} | {reason}"
            )
        if len(evaluations) > 8:
            lines.append(f"  - ... {len(evaluations) - 8} mas en el JSON.")
    else:
        lines.append("")
        lines.append("Operaciones evaluadas: ninguna compra/venta encontrada para esa fecha.")

    lines.append("")
    if improvements:
        lines.append("Mejoras propuestas:")
        for item in improvements[:6]:
            suggested = item.get("suggested_config") or item.get("candidate_filters") or {}
            lines.append(
                "  - "
                f"[{str(item.get('priority', 'info')).upper()}] {item.get('id')}: "
                f"{item.get('proposal')} "
                f"Motivo: {item.get('reason')} "
                f"Sugerencia: {suggested or 'sin cambio automatico'}."
            )
    else:
        lines.append("Mejoras propuestas: ninguna.")

    if isinstance(llm_review, dict) and llm_review:
        assessment = llm_review.get("assessment")
        if assessment:
            lines.append("")
            lines.append(f"Opinion LLM: {assessment}")
        if llm_review.get("parse_warning") or llm_review.get("error"):
            lines.append(f"Aviso LLM: {llm_review.get('parse_warning') or llm_review.get('error')}")

    operational = report.get("operational_learning", {}) or {}
    if operational:
        ops_summary = operational.get("summary", {}) or {}
        lines.append("")
        lines.append(
            "Aprendizaje operativo: "
            f"memorias={ops_summary.get('trade_memories', 0)} | "
            f"reglas active={ops_summary.get('rules_active', 0)} | "
            f"shadow={ops_summary.get('rules_shadow', 0)} | "
            f"rejected={ops_summary.get('rules_rejected', 0)}"
        )
        created = operational.get("llm_rules_created") or []
        if created:
            lines.append(f"Reglas LLM nuevas en shadow: {', '.join(created)}")

    if guidance:
        lines.append("")
        lines.append("Guia para la proxima sesion:")
        for item in guidance[:8]:
            lines.append(f"  - {item}")

    return "\n".join(lines)


def _print_post_market_review(report: dict[str, Any]) -> None:
    print(_post_market_review_text(report))


def _print_backtest_report(report: dict[str, Any]) -> None:
    metrics = report.get("metrics", {}) or {}
    strategy = report.get("strategy", {}) or {}
    print(f"BACKTEST {report.get('symbol')} | {strategy.get('name')}")
    period = report.get("period", {}) or {}
    if period:
        print(f"Periodo: {period.get('from')} -> {period.get('to')}")
    print(f"Informe: {report.get('path')}")
    print(
        "Metricas: "
        f"trades={metrics.get('trades', 0)} | "
        f"wins={metrics.get('wins', 0)} | losses={metrics.get('losses', 0)} | "
        f"hit-rate={_pct(metrics.get('hit_rate'))} | "
        f"P/L neto={_money(metrics.get('total_net_pl'))} | "
        f"retorno={_pct(metrics.get('total_return'))} | "
        f"profit-factor={metrics.get('profit_factor')} | "
        f"max-DD={_pct(metrics.get('max_drawdown'))} | "
        f"sharpe={metrics.get('sharpe')}"
    )
    trades = report.get("trades", []) or []
    if trades:
        print("Ultimas operaciones:")
        for trade in trades[-5:]:
            print(
                "  - "
                f"{trade['entry_date']} -> {trade['exit_date']} "
                f"{trade['exit_reason']} | entrada {trade['entry_price']} | "
                f"salida {trade['exit_price']} | P/L {_money(trade['net_pl'])} | "
                f"ret {_pct(trade['net_return'])}"
            )


def init_store() -> Store:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def command_init_db(_: argparse.Namespace) -> None:
    store = init_store()
    _print_json({"ok": True, "status": store.status()})


def command_status(_: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    payload = {
        "trading_mode": settings.trading_mode,
        "allow_live_trading": settings.allow_live_trading,
        "broker": {
            "name": settings.broker,
            "paper": settings.alpaca_paper,
            "endpoint": settings.alpaca_endpoint,
            "configured": bool(settings.alpaca_api_key and settings.alpaca_secret_key),
        },
        "execution": {
            "auto_paper_trading": settings.auto_paper_trading,
            "require_human_approval": settings.require_human_approval,
            "max_orders_per_cycle": settings.max_orders_per_cycle,
            "max_daily_buy_orders": settings.max_daily_buy_orders,
            "min_order_notional": settings.min_order_notional,
            "allow_position_adds": settings.allow_position_adds,
            "min_llm_confidence_to_trade": settings.min_llm_confidence_to_trade,
            "allow_short_selling": settings.allow_short_selling,
            "use_bracket_orders": settings.use_bracket_orders,
            "post_market_review_enabled": settings.post_market_review_enabled,
            "backtest_gate_enabled": settings.backtest_gate_enabled,
            "backtest_gate_min_trades": settings.backtest_gate_min_trades,
            "backtest_gate_min_hit_rate": settings.backtest_gate_min_hit_rate,
            "backtest_gate_min_profit_factor": settings.backtest_gate_min_profit_factor,
            "entry_quality_gate_enabled": settings.entry_quality_gate_enabled,
            "entry_quality_min_score": settings.entry_quality_min_score,
            "entry_quality_max_rsi": settings.entry_quality_max_rsi,
            "entry_quality_max_sma20_distance": settings.entry_quality_max_sma20_distance,
        },
        "analysis": {
            "closed_market_study_universe": settings.closed_market_study_universe,
            "closed_market_study_max_symbols": settings.closed_market_study_max_symbols,
            "intraday_technical_scan_enabled": settings.intraday_technical_scan_enabled,
            "intraday_technical_scan_universe": settings.intraday_technical_scan_universe,
            "intraday_technical_scan_max_symbols": settings.intraday_technical_scan_max_symbols,
            "breakout_extra_symbols": settings.breakout_watchlist,
            "breakout_scan": "enabled in market cycle and available via breakout-scan",
        },
        "universe": settings.universe,
        "database": store.status(),
        "runtime_dirs": {
            "data": str(settings.data_dir),
            "logs": str(settings.logs_dir),
            "agent_logs": str(settings.agent_logs_dir),
            "checkpoints": str(settings.checkpoints_dir),
        },
    }
    _print_json(payload)


def command_broker_status(_: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    try:
        account = BrokerClientFactory(settings).alpaca_account_snapshot()
    except RuntimeError as exc:
        _print_json(
            {
                "ok": False,
                "broker": settings.broker,
                "trading_mode": settings.trading_mode,
                "paper": settings.alpaca_paper,
                "endpoint": settings.alpaca_endpoint,
                "error": str(exc),
            }
        )
        raise SystemExit(1) from exc
    _print_json(
        {
            "ok": True,
            "broker": settings.broker,
            "trading_mode": settings.trading_mode,
            "paper": settings.alpaca_paper,
            "endpoint": settings.alpaca_endpoint,
            "account": account,
        }
    )


def command_portfolio_status(_: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    snapshot = BrokerClientFactory(settings).alpaca_portfolio_snapshot()
    _print_json({"ok": True, "portfolio": asdict(snapshot)})


def command_decide_once(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()

    decision_id = new_id("decide")
    portfolio = BrokerClientFactory(settings).alpaca_portfolio_snapshot()
    technical_context = load_latest_technical_candidates(
        settings.data_dir,
        per_side=args.top_per_side,
    )
    sentiment_context = load_latest_sentiment(settings.data_dir)
    rebalance_context = build_portfolio_rebalance_context(
        settings,
        portfolio,
        technical_context,
        sentiment_context,
    )
    decision = request_trade_recommendations(
        settings,
        portfolio,
        technical_context,
        sentiment_context,
        rebalance_context,
    )
    recommendations = decision["recommendations"]
    quality_recommendations, entry_quality_gate = filter_entry_quality(
        settings,
        recommendations,
        technical_context,
        sentiment_context,
    )
    plans = build_order_plans(
        settings,
        portfolio,
        quality_recommendations,
        dry_run=True,
    )
    signal_decisions_updated = update_signal_decisions(
        store,
        source_run_id=technical_context.get("run_id"),
        recommendations=recommendations,
        entry_quality_gate=entry_quality_gate,
        backtest_gate=[],
    )

    for recommendation in recommendations:
        rec_id = new_id("rec")
        store.save_trade_recommendation(
            recommendation_id=rec_id,
            cycle_id=decision_id,
            symbol=recommendation.symbol,
            action=recommendation.action,
            confidence=recommendation.confidence,
            payload=asdict(recommendation),
        )

    for plan in plans:
        plan_id = new_id("plan")
        store.save_order_plan(
            plan_id=plan_id,
            cycle_id=decision_id,
            symbol=plan.symbol,
            side=plan.side,
            notional=plan.notional,
            approved=plan.risk_decision.approved,
            dry_run=plan.dry_run,
            payload=asdict(plan),
        )

    _print_json(
        {
            "ok": True,
            "cycle_id": decision_id,
            "dry_run": True,
            "technical_report": technical_context.get("path"),
            "sentiment_report": sentiment_context.get("path"),
            "rebalance_context": rebalance_context,
            "recommendations": [asdict(item) for item in recommendations],
            "entry_quality_gate": entry_quality_gate,
            "signal_decisions_updated": signal_decisions_updated,
            "buy_order_plans": [asdict(item) for item in plans],
            "raw_response_preview": decision["raw_response_preview"],
        }
    )


def command_rebalance_status(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    portfolio = BrokerClientFactory(settings).alpaca_portfolio_snapshot()
    technical_context = load_latest_technical_candidates(
        settings.data_dir,
        per_side=args.top_per_side,
    )
    sentiment_context = load_latest_sentiment(settings.data_dir)
    rebalance_context = build_portfolio_rebalance_context(
        settings,
        portfolio,
        technical_context,
        sentiment_context,
    )
    _print_json(
        {
            "ok": True,
            "technical_report": technical_context.get("path"),
            "sentiment_report": sentiment_context.get("path"),
            "rebalance_context": rebalance_context,
        }
    )


def command_trade_history(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    payload = build_trade_history(settings, limit=args.limit, start_date=args.start, scope=args.scope)
    if args.json:
        _print_json({"ok": True, **payload})
        return

    summary = payload["summary"]
    print("HISTORICO COMPRA/VENTA")
    print(f"Filtro: desde {summary.get('start_date') or 'inicio'} | alcance={summary.get('scope')}")
    print(
        "Resumen: "
        f"fills={summary['fills']} | comprado=${summary['buy_notional']:.2f} | "
        f"vendido=${summary['sell_notional']:.2f} | P/L realizado conocido=${summary['realized_pl']:.2f} | "
        f"P/L abierto=${summary['unrealized_pl']:.2f} | posiciones={summary['open_positions']}"
    )
    if summary.get("unknown_realized_trades"):
        print(
            "Aviso: "
            f"{summary['unknown_realized_trades']} venta(s) no tienen P/L calculable porque falta "
            "la compra previa dentro de los fills leidos."
        )
    if payload["warnings"]:
        for warning in payload["warnings"]:
            print(f"Aviso: {warning}")

    print("\nPor dia:")
    if not payload["days"]:
        print("  Sin fills de Alpaca todavia.")
    for day in payload["days"]:
        open_pl = ""
        if day.get("open_unrealized_pl") is not None:
            open_pl = (
                f" | P/L abierto actual ${day['open_unrealized_pl']:.2f} "
                f"({day['open_unrealized_plpc']:.2%})"
            )
        print(
            f"\n{day['date']} | comprado ${day['buy_notional']:.2f} | vendido ${day['sell_notional']:.2f} | "
            f"P/L realizado ${day['realized_pl']:.2f} ({day['realized_plpc']:.2%}){open_pl}"
        )
        if day.get("unknown_realized_trades"):
            print(f"  Aviso: {day['unknown_realized_trades']} venta(s) sin P/L calculable.")
        for trade in day["trades"]:
            pl = ""
            if trade["realized_pl"] is not None:
                pl = f" | P/L ${trade['realized_pl']:.2f} ({trade['realized_plpc']:.2%})"
            elif trade["side"] == "sell":
                pl = " | P/L no disponible"
            risk = ""
            if trade.get("stop_loss") or trade.get("take_profit"):
                stop = float(trade.get("stop_loss") or 0)
                take = float(trade.get("take_profit") or 0)
                risk = f" | stop ${stop:.2f} | take ${take:.2f}"
            print(
                f"  {trade['time']} | {trade['side'].upper():4} | {trade['symbol']:<8} | "
                f"qty {trade['qty']} | precio ${trade['price']:.4f} | notional ${trade['notional']:.2f}"
                f"{risk}{pl}"
            )
        if day.get("open_positions"):
            print("  Posiciones abiertas actuales:")
            for position in day["open_positions"]:
                risk = ""
                if position.get("stop_loss") or position.get("take_profit"):
                    stop = float(position.get("stop_loss") or 0)
                    take = float(position.get("take_profit") or 0)
                    risk = f" | stop ${stop:.2f} | take ${take:.2f}"
                print(
                    f"    {position['symbol']:<8} | qty {position['qty']} | valor ${position['market_value']:.2f} | "
                    f"entrada ${position['avg_entry_price']:.4f} | actual ${position['current_price']:.4f} | "
                    f"P/L abierto ${position['unrealized_pl']:.2f} ({position['unrealized_plpc']:.2%}){risk}"
                )

    if payload["local_broker_orders"]:
        print("\nOrdenes enviadas registradas localmente:")
        for order in payload["local_broker_orders"][: args.limit]:
            risk = ""
            if order.get("stop_loss") or order.get("take_profit"):
                stop = float(order.get("stop_loss") or 0)
                take = float(order.get("take_profit") or 0)
                risk = f" | stop ${stop:.2f} | take ${take:.2f}"
            print(
                f"  {order['time']} | {order['side'].upper():4} | {order['symbol']:<6} | "
                f"estado {order['status']} | notional ${float(order.get('notional') or 0):.2f}{risk}"
            )

    _print_trade_history_summary_box(payload.get("current_statistics", {}))


def command_backtest(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    report = build_symbol_backtest(
        args.symbol,
        settings.data_dir / "reports",
        new_id("bt"),
        start=args.start,
        end=args.end,
        min_score=args.min_score,
        setup_quality=args.setup_quality,
        max_holding_days=args.max_holding_days,
    )
    if args.json:
        _print_json({"ok": True, **report})
        return
    _print_backtest_report(report)


def command_execute_approved(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()

    if settings.trading_mode != "paper" or not settings.alpaca_paper:
        raise SystemExit("Ejecucion bloqueada: solo se permite en Alpaca paper.")
    if not settings.auto_paper_trading and not args.confirm_paper:
        raise SystemExit(
            "Ejecucion bloqueada: usa --confirm-paper o AUTO_PAPER_TRADING=true."
        )
    calendar = MarketCalendar(settings.market_calendar, settings.local_timezone)
    market_status = calendar.status()
    if not market_status.is_open and not args.queue_closed_market:
        raise SystemExit(
            "Ejecucion bloqueada: mercado cerrado. Usa --queue-closed-market "
            "si quieres dejar ordenes en cola."
        )

    plans = store.pending_order_plans(cycle_id=args.cycle_id, limit=args.limit)
    results = []
    for plan in plans:
        client_order_id = f"agente-{plan['plan_id'][:20]}"
        order = submit_paper_order_plan(
            settings,
            plan,
            client_order_id=client_order_id,
        )
        broker_order_id = order["id"] or client_order_id
        store.save_broker_order(
            broker_order_id=broker_order_id,
            plan_id=plan["plan_id"],
            cycle_id=plan["cycle_id"],
            symbol=plan["symbol"],
            side=plan["side"],
            status=order["status"],
            payload={"plan": plan, "broker_order": order},
        )
        results.append({"plan_id": plan["plan_id"], "broker_order": order})

    _print_json(
        {
            "ok": True,
            "submitted": len(results),
            "cycle_id": args.cycle_id,
            "market": market_status.as_dict(),
            "results": results,
        }
    )


def command_scan_technical(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()

    run_id = new_id("scan")
    universe_name = args.universe or settings.closed_market_study_universe
    max_symbols = args.max_symbols or settings.closed_market_study_max_symbols
    symbols = resolve_study_universe(
        universe_name,
        settings.universe,
        max_symbols,
        settings.data_dir / "cache",
    )

    started = time.perf_counter()
    progress: dict[str, int] = {"done": 0, "total": len(symbols), "with_data": 0}

    def _progress(done: int, total: int, with_data: int) -> None:
        progress.update({"done": done, "total": total, "with_data": with_data})
        if not args.quiet:
            print(
                f"SCAN | progreso {done}/{total} | con datos {with_data}",
                flush=True,
            )

    if not args.quiet:
        print(
            f"SCAN | inicio | universo={universe_name} | simbolos={len(symbols)}",
            flush=True,
        )

    report = build_closed_market_technical_study(
        symbols,
        settings.data_dir / "reports",
        run_id,
        top_n=args.top_n,
        progress_callback=_progress,
    )
    signals_saved = record_signal_candidates(store, report, source="manual_scan")
    elapsed_seconds = round(time.perf_counter() - started, 2)
    top_longs = [item["symbol"] for item in report["top_longs"][:5]]
    top_shorts = [item["symbol"] for item in report["top_shorts"][:5]]
    payload = {
        "ok": True,
        "run_id": run_id,
        "elapsed_seconds": elapsed_seconds,
        "universe": universe_name,
        "symbols_requested": len(symbols),
        "symbols_scanned": report["symbols_scanned"],
        "symbols_with_data": report["symbols_with_data"],
        "signals_saved": signals_saved,
        "top_longs": top_longs,
        "top_shorts": top_shorts,
        "analysis_plan_counts": report["analysis_plan_counts"],
        "warnings_count": len(report["warnings"]),
        "tool_requests_count": len(report["tool_requests"]),
        "path": report["path"],
    }
    _print_json(payload)


def command_breakout_scan(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    run_id = new_id("breakout")
    universe_name = args.universe or settings.closed_market_study_universe
    max_symbols = args.max_symbols or settings.closed_market_study_max_symbols
    symbols = resolve_study_universe(
        universe_name,
        settings.universe,
        max_symbols,
        settings.data_dir / "cache",
    )
    symbols = merge_breakout_universe(symbols, settings.breakout_watchlist)

    started = time.perf_counter()
    report = build_breakout_scan(symbols, settings.data_dir / "reports", run_id)
    elapsed_seconds = round(time.perf_counter() - started, 2)
    payload = {
        "ok": True,
        "run_id": run_id,
        "elapsed_seconds": elapsed_seconds,
        "universe": universe_name,
        "symbols_requested": len(symbols),
        "symbols_scanned": report["symbols_scanned"],
        "symbols_with_data": report["symbols_with_data"],
        "confirmed": [
            {
                "symbol": item["symbol"],
                "risk": item["risk_level"],
                "tradable": item["tradable"],
                "close": item["close"],
                "resistance": item["resistance"],
                "breakout_pct": item["breakout_pct"],
                "volume_zscore_20": item["volume_zscore_20"],
                "plan": item["entry_style"],
            }
            for item in report["confirmed"][:10]
        ],
        "watch": [
            {
                "symbol": item["symbol"],
                "close": item["close"],
                "resistance": item["resistance"],
                "breakout_pct": item["breakout_pct"],
                "volume_zscore_20": item["volume_zscore_20"],
                "plan": item["entry_style"],
            }
            for item in report["watch"][:10]
        ],
        "blocked_or_failed_count": len(report["blocked_or_failed"]),
        "warnings_count": len(report["warnings"]),
        "path": report["path"],
    }
    if args.json:
        _print_json({"ok": True, **report, "elapsed_seconds": elapsed_seconds})
        return
    _print_json(payload)


def command_learning_status(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    update_result = {"updated": 0, "signals": 0, "symbols": 0, "warnings": []}
    if args.update:
        update_result = update_signal_outcomes(settings, store, since_date=args.start)
    report = build_learning_status(store, since_date=args.start, limit=args.limit)
    write_learning_report(
        {
            "as_of": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "update": update_result,
            **report,
        },
        settings.data_dir / "reports",
        new_id("learn"),
    )
    if args.json:
        _print_json({"ok": True, "update": update_result, **report})
        return

    print("APRENDIZAJE DE SENALES")
    print(
        f"Desde {report['since_date']} | senales={report['signals']} | "
        f"actualizadas={update_result.get('updated', 0)}"
    )
    print(f"Decisiones: {report['decisions']}")
    print(f"Resultados: {report['verdicts']}")
    print("\nMejores indicadores:")
    for item in report["best_indicators"][:8]:
        print(
            f"  {item['tag']:<24} | senales {item['signals']:<3} | resueltas {item['resolved']:<3} | "
            f"win-rate {_pct(item['win_rate']) if item['win_rate'] is not None else '-'} | "
            f"ret 5d {_pct(item['avg_return_5d']) if item['avg_return_5d'] is not None else '-'}"
        )
    print("\nPeores indicadores:")
    for item in report["worst_indicators"][:8]:
        print(
            f"  {item['tag']:<24} | senales {item['signals']:<3} | resueltas {item['resolved']:<3} | "
            f"win-rate {_pct(item['win_rate']) if item['win_rate'] is not None else '-'} | "
            f"ret 5d {_pct(item['avg_return_5d']) if item['avg_return_5d'] is not None else '-'}"
        )
    if update_result.get("warnings"):
        print("\nAvisos:")
        for warning in update_result["warnings"][:5]:
            print(f"  - {warning}")


def command_learning_review(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    report = build_operational_learning_review(
        settings,
        store,
        settings.data_dir / "reports",
        new_id("learnops"),
        since_date=args.start,
        use_llm=args.with_llm,
    )
    if args.json:
        _print_json({"ok": True, **report})
        return

    summary = report.get("summary", {})
    print("APRENDIZAJE OPERATIVO")
    print(f"Informe: {report.get('path')}")
    print(
        f"Desde {summary.get('since_date')} | memorias={summary.get('trade_memories', 0)} | "
        f"reglas={summary.get('rules_total', 0)} "
        f"(shadow={summary.get('rules_shadow', 0)}, active={summary.get('rules_active', 0)}, "
        f"rejected={summary.get('rules_rejected', 0)})"
    )
    print(f"Memoria actualizada: {report.get('memory_sync', {})}")
    print(f"Evaluacion shadow: {report.get('shadow_evaluation', {})}")
    print("")
    print("Reglas:")
    for rule in report.get("rules", [])[:12]:
        metrics = rule.get("metrics", {}) or {}
        print(
            f"  - [{str(rule.get('status')).upper()}] {rule.get('rule_id')} | {rule.get('name')} | "
            f"casos={metrics.get('cases', 0)} | net_shadow={_money(metrics.get('net_shadow_pl', 0))}"
        )
        print(f"    {rule.get('description')}")
    llm_review = report.get("llm_review", {}) or {}
    if llm_review:
        print("")
        print(f"Opinion LLM: {llm_review.get('assessment') or llm_review.get('error') or llm_review}")
    if report.get("llm_rules_created"):
        print(f"Reglas LLM creadas en shadow: {', '.join(report['llm_rules_created'])}")


def command_adaptive_status(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    payload = adaptive_status(settings)
    if args.json:
        _print_json({"ok": True, **payload})
        return
    print("AJUSTE ADAPTATIVO")
    print(f"Archivo: {payload['path']} | existe={payload['exists']}")
    if payload.get("active_overrides"):
        print(f"Overrides activos: {payload['active_overrides']}")
    else:
        print("Overrides activos: ninguno")
    print("")
    print("parametro                         actual      propuesto   estado")
    print("-" * 72)
    for item in payload["parameters"]:
        print(
            f"{item['name']:<33} {str(item['current']):<11} "
            f"{str(item.get('proposed') if item.get('proposed') is not None else '-'): <11} "
            f"{item['status']}"
        )
        if item.get("reason"):
            print(f"  motivo: {item['reason']}")
    if payload.get("last_tuning"):
        print("")
        print(f"Ultimo ajuste: {payload['last_tuning']}")


def command_adaptive_tune(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    result = update_adaptive_config(
        settings,
        store,
        since_date=args.start,
        min_resolved=args.min_resolved,
    )
    if args.json:
        _print_json({"ok": True, **result})
        return
    print("AJUSTE ADAPTATIVO ACTUALIZADO")
    print(f"Archivo: {result['path']}")
    print(f"Senales evaluadas: {result['generated'].get('signals', 0)}")
    print(f"Propuestas generadas: {len(result['generated'].get('proposals', []))}")
    print(f"Cambios guardados: {', '.join(result['changed']) or 'ninguno'}")
    for proposal in result["generated"].get("proposals", []):
        print(
            f"  - {proposal['name']}: {proposal['current']} -> {proposal['proposed']} "
            f"[{proposal['status']}] {proposal['reason']}"
        )


def command_study_symbol(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()

    started = time.perf_counter()
    run_id = new_id("symbol")
    report = build_symbol_study(
        args.symbol,
        settings,
        settings.data_dir / "reports",
        run_id,
        lookback_days=args.lookback_days,
        include_news=args.with_news or args.with_news_llm,
        include_news_llm=args.with_news_llm,
        news_items=args.news_items,
    )
    elapsed_seconds = round(time.perf_counter() - started, 2)
    summary = report["summary"]
    payload = {
        "ok": True,
        "elapsed_seconds": elapsed_seconds,
        "path": report["path"],
        "symbol": report["symbol"],
        "latest_bar": report["latest_bar"],
        "summary": summary,
        "benchmark": report["benchmark"],
        "fundamentals": report["fundamentals"],
        "news_count": len(report["news"].get("items", [])),
    }
    if args.full:
        payload["report"] = report
    _print_json(payload)


def command_post_market_review(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    run_id = new_id("pmr")
    report = build_post_market_review(
        settings,
        settings.data_dir / "reports",
        run_id,
        session_date=args.session_date,
        use_llm=not args.skip_llm,
    )
    if args.json:
        _print_json(
            {
                "ok": True,
                "path": report["path"],
                "session_date": report["session_date"],
                "summary": report["summary"],
                "trade_evaluations": report["trade_evaluations"],
                "proposed_improvements": report["proposed_improvements"],
                "next_session_guidance": report["next_session_guidance"],
                "llm_review": report.get("llm_review", {}),
            }
        )
        return
    _print_post_market_review(report)


def command_commands(args: argparse.Namespace) -> None:
    if args.json:
        _print_json({"commands": available_command_catalog()})
        return
    print(command_cheatsheet())


def command_agents(_: argparse.Namespace) -> None:
    rows = [
        {
            "code": info.code,
            "agent": agent,
            "title": info.title,
            "lane": info.lane,
        }
        for agent, info in sorted(AGENTS.items(), key=lambda item: item[1].code)
    ]
    _print_json({"agents": rows})


def command_seed(_: argparse.Namespace) -> None:
    settings = get_settings()
    store = init_store()
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
    store.record_agent_event(
        AgentEvent(
            agent="hypothesis_generator",
            event_type="seed_hypothesis",
            payload={"hypothesis_id": hypothesis.hypothesis_id, "name": hypothesis.name},
        )
    )
    _print_json({"ok": True, "hypothesis_id": hypothesis.hypothesis_id})


def run_cycle(use_crew: bool = True, verbose: bool = True) -> dict[str, Any]:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    return run_observable_cycle(settings, store, use_crew=use_crew, verbose=verbose)


def command_run_once(args: argparse.Namespace) -> None:
    _print_json(run_cycle(use_crew=not args.skip_crew, verbose=not args.quiet))


def command_daemon(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    LOGGER.info("Daemon iniciado con intervalo de %s segundos.", settings.run_interval_seconds)
    while True:
        try:
            payload = run_cycle(use_crew=not args.skip_crew, verbose=not args.quiet)
            LOGGER.info("Ciclo completado: %s", payload["cycle_id"])
        except Exception as exc:  # noqa: BLE001 - daemon must log and continue.
            LOGGER.exception("Ciclo fallido.")
            log_system_event(settings.logs_dir, "cycle_failed", {"error": str(exc)})
        time.sleep(settings.run_interval_seconds)


def command_schedule(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    run_scheduler_forever(settings, store, use_crew=not args.skip_crew, verbose=not args.quiet)


def command_schedule_status(_: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    _print_json(scheduler_status(settings))


def command_job_once(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    if args.job == "portfolio":
        portfolio_watch_job(settings, store, verbose=not args.quiet, force_notify=args.force)
    elif args.job == "market":
        market_cycle_job(settings, store, use_crew=not args.skip_crew, verbose=not args.quiet)
    elif args.job == "closed-study":
        closed_market_technical_study_job(
            settings,
            store,
            use_crew=not args.skip_crew,
            verbose=not args.quiet,
            force=args.force,
        )
    elif args.job == "daily":
        daily_study_job(settings, store, use_crew=not args.skip_crew, verbose=not args.quiet)
    elif args.job == "post-market-review":
        report = post_market_review_job(
            settings,
            store,
            use_llm=not args.skip_crew,
            verbose=not args.quiet,
            force=args.force,
        )
        if report and not args.quiet:
            print()
            _print_post_market_review(report)


def command_log(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    seen: set[str] = set()
    printer = PrettyLogPrinter(
        local_timezone=settings.local_timezone,
        headers=not args.no_headers,
        use_utc=args.utc,
        all_events=args.all_events,
    )

    while True:
        rows = list(reversed(store.latest_events(limit=args.lines)))
        for row in rows:
            event_id = row["event_id"]
            if event_id in seen:
                continue
            if args.agent and row["agent"] != args.agent:
                continue
            seen.add(event_id)
            if args.raw:
                print_raw_tail_line(row)
            else:
                printer.print(row)
        if not args.follow:
            break
        time.sleep(args.interval)


def command_web(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    app_path = Path(__file__).with_name("web_app.py")
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.address",
        args.host,
        "--server.port",
        str(args.port),
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]
    print(f"Abriendo panel web en http://{args.host}:{args.port}")
    print("Comando:", " ".join(cmd))
    subprocess.run(cmd, check=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Agente Bolsa multiagente.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_db = subparsers.add_parser("init-db", help="Crea la base SQLite y carpetas runtime.")
    init_db.set_defaults(func=command_init_db)

    status = subparsers.add_parser("status", help="Muestra estado basico.")
    status.set_defaults(func=command_status)

    broker_status = subparsers.add_parser(
        "broker-status",
        help="Comprueba la conexion con Alpaca y muestra estado de la cuenta paper.",
    )
    broker_status.set_defaults(func=command_broker_status)

    portfolio_status = subparsers.add_parser(
        "portfolio-status",
        help="Lee cuenta, posiciones y ordenes abiertas en Alpaca paper.",
    )
    portfolio_status.set_defaults(func=command_portfolio_status)

    web = subparsers.add_parser(
        "web",
        help="Lanza el panel web local para dashboard, cartera, aprendizaje y comandos.",
    )
    web.add_argument("--host", default="127.0.0.1", help="Host local para Streamlit.")
    web.add_argument("--port", type=int, default=8501, help="Puerto del panel web.")
    web.set_defaults(func=command_web)

    decide_once = subparsers.add_parser(
        "decide-once",
        help="Pide al LLM recomendaciones buy/sell/hold y genera planes dry-run.",
    )
    decide_once.add_argument(
        "--top-per-side",
        type=int,
        default=5,
        help="Numero de candidatos largos/cortos del ultimo estudio tecnico.",
    )
    decide_once.set_defaults(func=command_decide_once)

    rebalance_status = subparsers.add_parser(
        "rebalance-status",
        help="Muestra el contexto de rebalanceo de cartera sin llamar al LLM ni operar.",
    )
    rebalance_status.add_argument(
        "--top-per-side",
        type=int,
        default=5,
        help="Numero de candidatos largos/cortos del ultimo estudio tecnico.",
    )
    rebalance_status.set_defaults(func=command_rebalance_status)

    trade_history = subparsers.add_parser(
        "trade-history",
        help="Muestra historico de compras/ventas, fills y ganancias/perdidas.",
    )
    trade_history.add_argument("--limit", type=int, default=50, help="Numero maximo de filas.")
    trade_history.add_argument(
        "--from",
        dest="start",
        default=DEFAULT_HISTORY_START_DATE,
        help=f"Fecha inicial YYYY-MM-DD. Por defecto {DEFAULT_HISTORY_START_DATE}.",
    )
    trade_history.add_argument(
        "--scope",
        choices=["account", "agent"],
        default="account",
        help="account incluye fills de Alpaca desde la fecha; agent filtra a simbolos/ordenes del agente.",
    )
    trade_history.add_argument("--json", action="store_true", help="Devuelve el historico en JSON.")
    trade_history.set_defaults(func=command_trade_history)

    learning_status = subparsers.add_parser(
        "learning-status",
        help="Resume aprendizaje de senales, indicadores y resultados posteriores.",
    )
    learning_status.add_argument(
        "--from",
        dest="start",
        default=DEFAULT_HISTORY_START_DATE,
        help=f"Fecha inicial YYYY-MM-DD. Por defecto {DEFAULT_HISTORY_START_DATE}.",
    )
    learning_status.add_argument("--limit", type=int, default=1000, help="Numero maximo de senales.")
    learning_status.add_argument(
        "--update",
        action="store_true",
        help="Actualiza outcomes con precios posteriores antes de resumir.",
    )
    learning_status.add_argument("--json", action="store_true", help="Devuelve el informe en JSON.")
    learning_status.set_defaults(func=command_learning_status)

    learning_review = subparsers.add_parser(
        "learning-review",
        help="Construye memoria enriquecida de operaciones, evalua reglas shadow y genera aprendizaje operativo.",
    )
    learning_review.add_argument(
        "--from",
        dest="start",
        default=DEFAULT_HISTORY_START_DATE,
        help=f"Fecha inicial YYYY-MM-DD. Por defecto {DEFAULT_HISTORY_START_DATE}.",
    )
    learning_review.add_argument(
        "--with-llm",
        action="store_true",
        help="Pide al LLM nuevas reglas candidatas en shadow mode.",
    )
    learning_review.add_argument("--json", action="store_true", help="Devuelve el informe en JSON.")
    learning_review.set_defaults(func=command_learning_review)

    adaptive_status_parser = subparsers.add_parser(
        "adaptive-status",
        help="Muestra propuestas/overrides adaptativos de parametros.",
    )
    adaptive_status_parser.add_argument("--json", action="store_true", help="Devuelve el estado en JSON.")
    adaptive_status_parser.set_defaults(func=command_adaptive_status)

    adaptive_tune = subparsers.add_parser(
        "adaptive-tune",
        help="Recalcula propuestas adaptativas desde el aprendizaje de senales.",
    )
    adaptive_tune.add_argument(
        "--from",
        dest="start",
        default=DEFAULT_HISTORY_START_DATE,
        help=f"Fecha inicial YYYY-MM-DD. Por defecto {DEFAULT_HISTORY_START_DATE}.",
    )
    adaptive_tune.add_argument(
        "--min-resolved",
        type=int,
        default=10,
        help="Minimo de senales resueltas antes de proponer cambios.",
    )
    adaptive_tune.add_argument("--json", action="store_true", help="Devuelve el resultado en JSON.")
    adaptive_tune.set_defaults(func=command_adaptive_tune)

    backtest = subparsers.add_parser(
        "backtest",
        help="Simula historicamente la regla tecnica long actual con stop/take y costes.",
    )
    backtest.add_argument("--symbol", required=True, help="Ticker a simular, por ejemplo AAPL.")
    backtest.add_argument("--from", dest="start", required=True, help="Fecha inicial YYYY-MM-DD.")
    backtest.add_argument("--to", dest="end", help="Fecha final YYYY-MM-DD. Por defecto hoy.")
    backtest.add_argument("--min-score", type=int, default=7, help="Score tecnico minimo.")
    backtest.add_argument(
        "--setup-quality",
        default="strong",
        help="Calidad requerida del setup tecnico. Por defecto strong.",
    )
    backtest.add_argument(
        "--max-holding-days",
        type=int,
        default=10,
        help="Time stop maximo en sesiones.",
    )
    backtest.add_argument("--json", action="store_true", help="Devuelve el informe completo en JSON.")
    backtest.set_defaults(func=command_backtest)

    execute_approved = subparsers.add_parser(
        "execute-approved",
        help="Envia a Alpaca paper los planes aprobados pendientes.",
    )
    execute_approved.add_argument("--cycle-id", help="Ejecuta solo planes de un ciclo decide-once.")
    execute_approved.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Numero maximo de planes a enviar.",
    )
    execute_approved.add_argument(
        "--confirm-paper",
        action="store_true",
        help="Confirma explicitamente envio de ordenes a Alpaca paper.",
    )
    execute_approved.add_argument(
        "--queue-closed-market",
        action="store_true",
        help="Permite enviar ordenes aunque NYSE este cerrado y queden en cola.",
    )
    execute_approved.set_defaults(func=command_execute_approved)

    scan_technical = subparsers.add_parser(
        "scan-technical",
        help="Ejecuta ahora el analisis tecnico amplio sin depender del horario de mercado.",
    )
    scan_technical.add_argument(
        "--universe",
        help=(
            "Universo a analizar. Por defecto usa CLOSED_MARKET_STUDY_UNIVERSE. "
            "Ejemplos: sp500_top300, sp500, default, AAPL,MSFT,NVDA."
        ),
    )
    scan_technical.add_argument(
        "--max-symbols",
        type=int,
        default=0,
        help="Limite de simbolos. Por defecto usa CLOSED_MARKET_STUDY_MAX_SYMBOLS.",
    )
    scan_technical.add_argument(
        "--top-n",
        type=int,
        default=15,
        help="Numero de candidatos largos/cortos a guardar en el resumen.",
    )
    scan_technical.add_argument("--quiet", action="store_true", help="No imprime progreso.")
    scan_technical.add_argument(
        "--force",
        action="store_true",
        help="Aceptado por compatibilidad; el comando siempre ejecuta el escaneo.",
    )
    scan_technical.set_defaults(func=command_scan_technical)

    breakout_scan = subparsers.add_parser(
        "breakout-scan",
        help="Detecta rupturas o posibles rupturas de resistencia con control conservador de riesgo.",
    )
    breakout_scan.add_argument(
        "--universe",
        help=(
            "Universo a analizar. Por defecto usa CLOSED_MARKET_STUDY_UNIVERSE. "
            "Ejemplos: sp500_top300, sp500, default, RDDT,AAPL,NVDA."
        ),
    )
    breakout_scan.add_argument(
        "--max-symbols",
        type=int,
        default=0,
        help="Limite de simbolos. Por defecto usa CLOSED_MARKET_STUDY_MAX_SYMBOLS.",
    )
    breakout_scan.add_argument("--json", action="store_true", help="Devuelve el informe completo en JSON.")
    breakout_scan.set_defaults(func=command_breakout_scan)

    study_symbol = subparsers.add_parser(
        "study-symbol",
        help="Ejecuta un estudio completo de un simbolo.",
    )
    study_symbol.add_argument("symbol", help="Ticker a estudiar, por ejemplo AAPL.")
    study_symbol.add_argument(
        "--lookback-days",
        type=int,
        default=420,
        help="Dias de historico para indicadores y figuras.",
    )
    study_symbol.add_argument(
        "--with-news",
        action="store_true",
        help="Incluye noticias recientes de yfinance sin pedir validacion LLM.",
    )
    study_symbol.add_argument(
        "--with-news-llm",
        action="store_true",
        help="Incluye noticias y validacion de sentimiento con el LLM configurado.",
    )
    study_symbol.add_argument(
        "--news-items",
        type=int,
        default=5,
        help="Numero maximo de noticias a incluir si se usan noticias.",
    )
    study_symbol.add_argument(
        "--full",
        action="store_true",
        help="Imprime el informe completo ademas de guardarlo en data/reports.",
    )
    study_symbol.set_defaults(func=command_study_symbol)

    post_market_review = subparsers.add_parser(
        "post-market-review",
        help="Revisa compras/ventas tras cierre y genera aprendizaje para la siguiente sesion.",
    )
    post_market_review.add_argument(
        "--session-date",
        help="Fecha de sesion YYYY-MM-DD. Por defecto usa hoy en la zona local.",
    )
    post_market_review.add_argument(
        "--skip-llm",
        action="store_true",
        help="Genera solo el informe determinista, sin revision LLM.",
    )
    post_market_review.add_argument("--json", action="store_true", help="Devuelve el informe completo en JSON.")
    post_market_review.set_defaults(func=command_post_market_review)

    commands = subparsers.add_parser("commands", help="Resumen claro de comandos operativos frecuentes.")
    commands.add_argument("--json", action="store_true", help="Devuelve el catalogo completo en JSON.")
    commands.set_defaults(func=command_commands)

    agents = subparsers.add_parser("agents", help="Muestra leyenda de agentes y codigos.")
    agents.set_defaults(func=command_agents)

    seed = subparsers.add_parser("seed", help="Inserta una hipotesis inicial de ejemplo.")
    seed.set_defaults(func=command_seed)

    run_once = subparsers.add_parser("run-once", help="Ejecuta un ciclo observable.")
    run_once.add_argument(
        "--skip-crew",
        action="store_true",
        help="Ejecuta solo las fases, persistencia y logs, sin llamar al LLM/CrewAI.",
    )
    run_once.add_argument("--quiet", action="store_true", help="No imprime eventos en vivo.")
    run_once.set_defaults(func=command_run_once)

    daemon = subparsers.add_parser("daemon", help="Ejecuta ciclos continuamente.")
    daemon.add_argument(
        "--skip-crew",
        action="store_true",
        help="Ejecuta solo las fases, persistencia y logs, sin llamar al LLM/CrewAI.",
    )
    daemon.add_argument("--quiet", action="store_true", help="No imprime eventos en vivo.")
    daemon.set_defaults(func=command_daemon)

    schedule = subparsers.add_parser("schedule", help="Ejecuta scheduler 1m/15m/diario.")
    schedule.add_argument(
        "--skip-crew",
        action="store_true",
        help="Los ciclos programados no llaman a CrewAI, solo validan fases/logs/datos.",
    )
    schedule.add_argument("--quiet", action="store_true", help="No imprime eventos en vivo.")
    schedule.set_defaults(func=command_schedule)

    schedule_status = subparsers.add_parser("schedule-status", help="Muestra calendario y jobs.")
    schedule_status.set_defaults(func=command_schedule_status)

    job_once = subparsers.add_parser("job-once", help="Ejecuta manualmente un job del scheduler.")
    job_once.add_argument(
        "job",
        choices=["portfolio", "market", "closed-study", "daily", "post-market-review"],
    )
    job_once.add_argument(
        "--skip-crew",
        action="store_true",
        help="No llamar a CrewAI en jobs largos.",
    )
    job_once.add_argument(
        "--force",
        action="store_true",
        help="Fuerza ejecucion aunque ya se haya hecho.",
    )
    job_once.add_argument("--quiet", action="store_true", help="No imprime eventos en vivo.")
    job_once.set_defaults(func=command_job_once)

    log = subparsers.add_parser("log", help="Muestra eventos recientes y puede seguirlos en vivo.")
    log.add_argument(
        "--agent",
        help="Filtra por nombre interno de agente, por ejemplo risk_manager.",
    )
    log.add_argument("--lines", type=int, default=50, help="Numero de eventos recientes a mostrar.")
    log.add_argument("--follow", action="store_true", help="Sigue mostrando eventos nuevos.")
    log.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Segundos entre lecturas con --follow.",
    )
    log.add_argument("--raw", action="store_true", help="Muestra el formato tecnico antiguo.")
    log.add_argument(
        "--all-events",
        action="store_true",
        help="Muestra tambien eventos internos y progreso detallado.",
    )
    log.add_argument(
        "--no-headers",
        action="store_true",
        help="No imprime separadores por ciclo/job.",
    )
    log.add_argument("--utc", action="store_true", help="Muestra hora UTC en vez de hora local.")
    log.set_defaults(func=command_log)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
