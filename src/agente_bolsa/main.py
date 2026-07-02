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

from .agent_config import load_agent_config, load_task_config, validate_agent_task_config
from .agent_registry import AGENTS
from .config import get_settings
from .continuous_improvement.api import run_api_server
from .continuous_improvement.digest import build_lab_digest, format_lab_digest_text
from .continuous_improvement.experiments import AutoApplyCodeAgent
from .continuous_improvement.orchestrator import ContinuousImprovementOrchestrator
from .continuous_improvement.runtime import ContinuousImprovementLabRuntime
from .cycle_runner import run_observable_cycle
from .eventing import EventReporter, PrettyLogPrinter, print_raw_tail_line
from .logging_utils import configure_logging, log_system_event
from .market_calendar import MarketCalendar
from .models import AgentEvent, Hypothesis, new_id
from .research.telegram_radar.cli import build_report as telegram_radar_build_report
from .research.telegram_radar.cli import list_records as telegram_radar_list_records
from .research.telegram_radar.cli import run_ingest as telegram_radar_run_ingest
from .research.telegram_radar.cli import (
    write_markdown_report as telegram_radar_write_markdown_report,
)
from .scheduler import (
    _run_pre_earnings_trade_operation,
    broker_reconciliation_job,
    closed_market_technical_study_job,
    continuous_improvement_job,
    daily_study_job,
    market_cycle_job,
    opportunity_snapshot_job,
    overnight_learning_heartbeat_job,
    portfolio_watch_job,
    post_market_review_job,
    pre_earnings_job,
    run_scheduler_forever,
    scheduler_status,
)
from .storage import Store
from .tools.adaptive_tuning import adaptive_status, update_adaptive_config
from .tools.backtest import build_symbol_backtest
from .tools.breakout_scanner import build_breakout_scan, merge_breakout_universe
from .tools.broker import BrokerClientFactory
from .tools.command_catalog import available_command_catalog, command_cheatsheet
from .tools.counterfactual_analysis import (
    DEFAULT_RETROSPECTIVE_SESSIONS,
    build_decision_compare_report,
    build_fallback_blocker_report,
    build_missed_opportunities_report,
    build_selector_replay_report,
    build_session_retrospective_report,
    build_signal_postmortem_report,
    build_walk_forward_validation_report,
    build_winner_coverage_report,
)
from .tools.daily_learning import (
    DEFAULT_DAILY_LEARNING_START,
    build_learning_daily_run,
    build_learning_digest_report,
    build_learning_health_report,
    build_learning_promotions_report,
    build_policy_candidates_report,
    load_daily_learning_context,
)
from .tools.execution import submit_paper_order_plan
from .tools.live_readiness import build_live_readiness_report
from .tools.market_state import build_market_state, load_latest_market_state
from .tools.operational_health import (
    build_operational_health_report,
    build_production_health_report,
    load_operational_response_context,
)
from .tools.operational_learning import build_operational_learning_review
from .tools.opportunities import parse_opportunity_snapshot_times
from .tools.ops_reports import (
    backup_database,
    build_market_data_quality_report,
    build_market_data_reconciliation_report,
    build_selection_bandwidth_review,
    build_weekly_trading_review,
)
from .tools.portfolio_optimizer import build_portfolio_rebalance_context
from .tools.post_market_review import build_post_market_review
from .tools.pre_earnings import (
    backfill_pending_pre_earnings_estimates,
    build_pre_earnings_event_study,
    build_pre_earnings_learning_digest,
    build_pre_earnings_report,
    build_pre_earnings_score_study,
    enrich_report_with_local_analyst_revisions,
    enrich_report_with_pre_earnings_score_v2,
    record_pre_earnings_analyst_snapshots,
    record_pre_earnings_predictions,
    update_pre_earnings_outcomes,
)
from .tools.retention import cleanup_runtime_data
from .tools.signal_learning import (
    backfill_signal_candidates_from_reports,
    build_learning_status,
    record_signal_candidates,
    update_signal_decisions,
    update_signal_outcomes,
    write_learning_report,
)
from .tools.symbol_study import build_symbol_study
from .tools.technical_study import build_closed_market_technical_study
from .tools.trade_decision import (
    _annotate_technical_context_with_learning,
    build_order_plans,
    filter_entry_quality,
    load_latest_sentiment,
    load_latest_technical_candidates,
    request_trade_recommendations,
)
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
        f"sharpe={metrics.get('sharpe')} | "
        f"sortino={metrics.get('sortino')} | "
        f"calmar={metrics.get('calmar')}"
    )
    print(
        "Riesgo/actividad: "
        f"expectancy={_money(metrics.get('expectancy_per_trade'))} por trade | "
        f"turnover={_pct(metrics.get('turnover'))} | "
        f"exposure-time={_pct(metrics.get('exposure_time_pct'))}"
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


def _print_counterfactual_summary(title: str, report: dict[str, Any]) -> None:
    print(title)
    print(f"Informe: {report.get('path')}")
    period = report.get("period", {}) or {}
    if period:
        print(f"Periodo: {period.get('from')} -> {period.get('to')}")
    summary = report.get("summary", {}) or {}
    if "cohorts" in summary:
        print(
            f"Senales={summary.get('signals', 0)} | maduras={summary.get('matured', 0)} | "
            f"missed={summary.get('missed_opportunities', 0)} | duplicados ejecutados={summary.get('executed_duplicates', 0)}"
        )
        print(f"Cohortes: {summary.get('cohorts', {})}")
        print(f"Flags: {summary.get('flags', {})}")
        rank_shadow = summary.get("rank_shadow", {}) or {}
        if rank_shadow:
            print(
                "Ranking shadow: "
                f"reemplazos={rank_shadow.get('candidate_replacements', 0)} | "
                f"delta={rank_shadow.get('delta_net_opportunity')}"
            )
        return
    if "current" in summary and "proposed" in summary:
        print(
            f"Actual ejecutadas={summary.get('current', {}).get('executed', 0)} | "
            f"Propuesta ejecutadas={summary.get('proposed', {}).get('executed', 0)} | "
            f"bloqueadas={summary.get('blocked_by_policy', 0)} | "
            f"delta neto={summary.get('delta_net_opportunity')}"
        )
        rank_shadow = summary.get("rank_shadow", {}) or {}
        if rank_shadow:
            print(
                "Ranking shadow: "
                f"reemplazos={rank_shadow.get('candidate_replacements', 0)} | "
                f"delta={rank_shadow.get('delta_net_opportunity')}"
            )
        return
    if "sessions" in summary:
        print(
            f"Sesiones={summary.get('sessions', 0)} | "
            f"delta agregado={summary.get('aggregate_delta_net_opportunity')} | "
            f"duplicados bloqueados={summary.get('aggregate_blocked_duplicates', 0)} | "
            f"ranking shadow delta={summary.get('aggregate_rank_shadow_delta')}"
        )
        best = summary.get("best_day") or {}
        worst = summary.get("worst_day") or {}
        if best:
            print(f"Mejor dia: {best.get('session_date')} delta={best.get('delta_net_opportunity')}")
        if worst:
            print(f"Peor dia: {worst.get('session_date')} delta={worst.get('delta_net_opportunity')}")
        return
    if "windows" in report:
        print(
            f"Ventanas={summary.get('windows', 0)} | "
            f"ventanas estables={summary.get('stable_windows', 0)}"
        )
        return
    if "winners_considered" in summary:
        print(
            f"Ganadoras={summary.get('winners_considered', 0)} | "
            f"seleccionadas_any={summary.get('selected_any', 0)} | "
            f"seleccionadas_mayoria={summary.get('selected_majority', 0)} | "
            f"fallback_any={summary.get('fallback_buy_any', 0)} | "
            f"fallback_mayoria={summary.get('fallback_buy_majority', 0)}"
        )
        buckets = summary.get("coverage_buckets", {}) or {}
        if buckets:
            print(f"Cobertura: {buckets}")
        blockers = summary.get("fallback_blocker_summary", []) or []
        if blockers:
            print("Bloqueadores principales:")
            for item in blockers[:5]:
                print(f"  - {item.get('reason')}: {item.get('sessions')} sesiones")
        misses = summary.get("selection_miss_summary", []) or []
        if misses:
            print("Misses de seleccion principales:")
            for item in misses[:5]:
                print(f"  - {item.get('reason')}: {item.get('sessions')} sesiones")
        top_rows = report.get("top_winner_coverage", []) or []
        if top_rows:
            print("Top ganadoras:")
            for item in top_rows[:10]:
                print(
                    "  - "
                    f"{item.get('symbol')} {item.get('signal_date')} ret5d={_pct(item.get('return_5d'))} | "
                    f"bucket={item.get('coverage_bucket')} | "
                    f"selected={item.get('selected_sessions')}/{item.get('reports_on_date')} | "
                    f"fallback={item.get('fallback_buy_sessions')}/{item.get('reports_on_date')} | "
                    f"best_rank={item.get('best_selection_rank')}"
                )
        return


def _print_pre_earnings_report(report: dict[str, Any]) -> None:
    summary = report.get("summary", {}) or {}
    success_rate = summary.get("success_rate")
    success_text = "sin datos" if success_rate is None else _pct(success_rate)
    trading_operation = report.get("trading_operation", {}) or {}
    operation_allowed = bool(report.get("operation_allowed"))
    print("PRE-EARNINGS")
    if operation_allowed:
        print("Modo: operativo conservador; genera recomendaciones buy y planes de orden para oportunidades actionable.")
    else:
        print("Modo: solo informativo; no genera compras ni planes de orden.")
    print(f"Informe: {report.get('path')}")
    print(
        "Resumen: "
        f"exito={success_text} | "
        f"aciertos={summary.get('bullish_hits', 0)} | "
        f"fallos={summary.get('bullish_misses', 0)} | "
        f"resueltos={summary.get('resolved_count', 0)} | "
        f"pendientes={summary.get('pending_count', 0)} | "
        f"eventos={summary.get('total_events', report.get('events_found', 0))} | "
        f"universo={report.get('universe_size', 0)}"
    )
    quality = report.get("data_quality", {}) or {}
    if quality:
        print(
            "Datos: "
            f"fuente={quality.get('calendar_source')} | "
            f"cache={quality.get('cache_hits', 0)} | "
            f"consultas={quality.get('yfinance_calls', 0)} | "
            f"errores={quality.get('calendar_errors', 0)}"
        )
    if "predictions_saved" in report or "tracking_update" in report:
        tracking = report.get("tracking_update", {}) or {}
        print(
            "Seguimiento: "
            f"hipotesis guardadas={report.get('predictions_saved', 0)} | "
            f"resultados actualizados={tracking.get('updated', 0)}"
        )
    if operation_allowed:
        print(
            "Operacion: "
            f"recomendaciones={len(trading_operation.get('recommendations', []))} | "
            f"planes buy={len(trading_operation.get('buy_order_plans', []))} | "
            f"enviadas={len(trading_operation.get('submitted', []))}"
        )
        if trading_operation.get("blocked"):
            print(f"Bloqueo ejecucion: {trading_operation.get('blocked')}")
    sessions = report.get("sessions") or [{"session_date": report.get("session_date"), "items": report.get("items", [])}]
    for session in sessions:
        items = session.get("items", []) or []
        print("")
        print(f"Sesion AMC {session.get('session_date')} | eventos={len(items)}")
        if not items:
            print("  sin earnings AMC detectados")
            continue
        for item in items:
            outcome = item.get("outcome", {}) or {}
            ret = outcome.get("return_pct")
            ret_text = "pendiente" if ret is None else _pct(ret)
            print(
                "  - "
                f"{item.get('symbol')} | {item.get('earnings_datetime')} | "
                f"hipotesis={item.get('hypothesis')} score={item.get('score')}/{item.get('max_score')} | "
                f"v2={item.get('score_v2_label', 'sin_datos')} {item.get('pre_earnings_score_v2', '-')}/100 | "
                f"resultado={ret_text} ({outcome.get('status')})"
            )
            reason = item.get("reason")
            if reason:
                print(f"    {reason}")


def _print_pre_earnings_event_study(report: dict[str, Any]) -> None:
    metrics = report.get("metrics", {}) or {}
    success_rate = metrics.get("success_rate")
    success_text = "sin datos" if success_rate is None else _pct(success_rate)
    print("PRE-EARNINGS EVENT-STUDY INFORMATIVO")
    print("Modo: solo analisis historico; no genera compras ni planes de orden.")
    print(f"Periodo: {report.get('period', {}).get('from')} -> {report.get('period', {}).get('to')}")
    print(f"Informe: {report.get('path')}")
    print(
        "Metricas: "
        f"eventos={metrics.get('events', 0)} | "
        f"resueltos={metrics.get('resolved', 0)} | "
        f"alcistas={metrics.get('bullish_predictions', 0)} | "
        f"aciertos={metrics.get('bullish_hits', 0)} | "
        f"fallos={metrics.get('bullish_misses', 0)} | "
        f"exito={success_text} | "
        f"ret medio={_pct(metrics.get('avg_return')) if metrics.get('avg_return') is not None else 'sin datos'} | "
        f"ret medio alcista={_pct(metrics.get('bullish_avg_return')) if metrics.get('bullish_avg_return') is not None else 'sin datos'}"
    )
    by_hypothesis = metrics.get("by_hypothesis", {}) or {}
    if by_hypothesis:
        print("")
        print("Por hipotesis:")
        for name, item in by_hypothesis.items():
            rate = item.get("positive_rate")
            avg = item.get("avg_return")
            print(
                "  - "
                f"{name}: eventos={item.get('events', 0)} | resueltos={item.get('resolved', 0)} | "
                f"positivos={_pct(rate) if rate is not None else 'sin datos'} | "
                f"ret medio={_pct(avg) if avg is not None else 'sin datos'}"
            )


def _print_pre_earnings_score_study(report: dict[str, Any]) -> None:
    metrics = report.get("metrics", {}) or {}
    print("PRE-EARNINGS SCORE V2 STUDY")
    print("Modo: estudio informativo; no genera compras ni planes de orden.")
    print(f"Informe: {report.get('path')}")
    print(
        "Metricas: "
        f"predicciones={metrics.get('predictions', 0)} | "
        f"eventos={metrics.get('events', 0)} | "
        f"resueltos={metrics.get('resolved_events', 0)} | "
        f"subidas>5={metrics.get('big_winners_gt_5', 0)} | "
        f"captura antigua={_pct(metrics.get('legacy_big_winner_capture_rate')) if metrics.get('legacy_big_winner_capture_rate') is not None else 'sin datos'} | "
        f"captura v2={_pct(metrics.get('v2_big_winner_capture_rate')) if metrics.get('v2_big_winner_capture_rate') is not None else 'sin datos'} | "
        f"captura alta conviccion={_pct(metrics.get('v2_high_conviction_capture_rate')) if metrics.get('v2_high_conviction_capture_rate') is not None else 'sin datos'} | "
        f"FP antigua={_pct(metrics.get('legacy_false_positive_rate')) if metrics.get('legacy_false_positive_rate') is not None else 'sin datos'} | "
        f"FP v2={_pct(metrics.get('v2_false_positive_rate')) if metrics.get('v2_false_positive_rate') is not None else 'sin datos'} | "
        f"FP alta conviccion={_pct(metrics.get('v2_high_conviction_false_positive_rate')) if metrics.get('v2_high_conviction_false_positive_rate') is not None else 'sin datos'}"
    )
    big_winners = report.get("big_winners", []) or []
    if big_winners:
        print("")
        print("Subidas >5%:")
        for item in big_winners[:20]:
            print(
                "  - "
                f"{item.get('symbol')} {item.get('earnings_date')} | "
                f"ret={_pct(item.get('return_pct'))} | "
                f"antes={item.get('legacy_hypothesis')} {item.get('legacy_score')}/{item.get('legacy_max_score')} | "
                f"v2={item.get('final_label_v2')} {item.get('final_score_v2')}/100"
            )
            print(f"    {item.get('failure_analysis')}")
    blocked = report.get("blocked_big_winners", []) or []
    if blocked:
        print("")
        print("Ganadores fuertes vetados por la capa actionable:")
        for item in blocked[:20]:
            print(
                "  - "
                f"{item.get('symbol')} {item.get('earnings_date')} | "
                f"ret={_pct(item.get('return_pct'))} | "
                f"v2={item.get('final_label_v2')} {item.get('final_score_v2')}/100 | "
                f"motivo={item.get('actionable_pre_earnings_reason')}"
            )


def init_store() -> Store:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    cleanup_runtime_data(settings)
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
            "pre_earnings_enabled": settings.pre_earnings_enabled,
            "pre_earnings_days": settings.pre_earnings_days,
            "pre_earnings_time_market": settings.pre_earnings_time_market,
            "pre_earnings_universe": settings.pre_earnings_universe or settings.closed_market_study_universe,
            "pre_earnings_max_symbols": settings.pre_earnings_max_symbols or settings.closed_market_study_max_symbols,
        },
        "universe": settings.universe,
        "database": store.status(),
        "runtime_dirs": {
            "data": str(settings.data_dir),
            "logs": str(settings.logs_dir),
            "agent_logs": str(settings.agent_logs_dir),
            "checkpoints": str(settings.checkpoints_dir),
        },
        "retention": {
            "enabled": settings.retention_enabled,
            "report_retention_days": settings.report_retention_days,
            "log_retention_days": settings.log_retention_days,
            "cache_retention_days": settings.cache_retention_days,
            "disabled_report_prefixes": settings.disabled_report_prefix_list,
        },
    }
    _print_json(payload)


def command_retention_cleanup(_: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    summary = cleanup_runtime_data(settings)
    _print_json(
        {
            "ok": True,
            "retention": {
                "enabled": settings.retention_enabled,
                "report_retention_days": settings.report_retention_days,
                "log_retention_days": settings.log_retention_days,
                "cache_retention_days": settings.cache_retention_days,
                "disabled_report_prefixes": settings.disabled_report_prefix_list,
            },
            "summary": summary.as_dict(),
        }
    )


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
        settings=settings,
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
        benchmark_symbol=settings.benchmark_symbol,
        provider=settings.market_data_provider,
        fmp_api_key=settings.fmp_api_key,
        allowed_setup_names={args.setup_name} if args.setup_name else None,
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
    if args.json:
        _print_json({"ok": True, **report})
        return
    _print_backtest_report(report)


def command_backtest_baseline(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    baseline_reports = []
    for setup_name in (
        "trend_volume",
        "orderly_breakout",
        "event_momentum",
        "momentum_confirmation",
        "momentum_shakeout_hold",
        "range_expansion_breakout",
    ):
        report = build_symbol_backtest(
            args.symbol,
            settings.data_dir / "reports",
            new_id(f"bt_{setup_name}"),
            start=args.start,
            end=args.end,
            min_score=args.min_score,
            setup_quality=args.setup_quality,
            max_holding_days=args.max_holding_days,
            benchmark_symbol=settings.benchmark_symbol,
            provider=settings.market_data_provider,
            fmp_api_key=settings.fmp_api_key,
            allowed_setup_names={setup_name},
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
        baseline_reports.append(
            {
                "setup_name": setup_name,
                "path": report.get("path"),
                "metrics": report.get("metrics", {}),
                "validation": ((report.get("validation") or {}).get("gate")) or {},
            }
        )
    payload = {"ok": True, "symbol": args.symbol.upper(), "baseline_reports": baseline_reports}
    if args.json:
        _print_json(payload)
        return
    print(f"BASELINE BACKTESTS {payload['symbol']}")
    for item in baseline_reports:
        metrics = item["metrics"]
        gate = item["validation"]
        print(
            f"- {item['setup_name']}: "
            f"trades={metrics.get('trades', 0)} | "
            f"retorno={_pct(metrics.get('total_return'))} | "
            f"sharpe={metrics.get('sharpe')} | "
            f"sortino={metrics.get('sortino')} | "
            f"aprobado={gate.get('approved')}"
        )


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
        benchmark_symbol=settings.benchmark_symbol,
    )
    annotated_report = _annotate_technical_context_with_learning(
        report,
        load_daily_learning_context(settings.data_dir),
        load_operational_response_context(settings.data_dir),
        settings.data_dir,
        settings=settings,
    )
    report["selected_candidates"] = annotated_report.get("selected_candidates", [])
    report["selection_metadata"] = annotated_report.get("selection_metadata", {})
    market_state = load_latest_market_state(settings.data_dir / "reports")
    if market_state:
        report["market_state"] = market_state
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


def command_opportunity_snapshot(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    slot_time = parse_opportunity_snapshot_times(args.slot)[0]
    snapshot = opportunity_snapshot_job(
        settings,
        store,
        slot_time=slot_time,
        verbose=not args.quiet,
        force=args.force,
    )
    _print_json(
        {
            "ok": True,
            "session_date": snapshot.get("session_date"),
            "slot_time": snapshot.get("slot_time"),
            "run_id": snapshot.get("run_id"),
            "report_path": snapshot.get("report_path"),
            "summary": snapshot.get("summary", {}),
        }
    )


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


def command_pre_earnings(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    universe_name = args.universe or settings.pre_earnings_universe or settings.closed_market_study_universe
    max_symbols = args.max_symbols or settings.pre_earnings_max_symbols or settings.closed_market_study_max_symbols
    symbols = resolve_study_universe(
        universe_name,
        settings.universe,
        max_symbols,
        settings.data_dir / "cache",
    )
    report = build_pre_earnings_report(
        symbols=symbols,
        output_dir=settings.data_dir / "reports",
        run_id=new_id("preearn"),
        calendar_name=settings.market_calendar,
        local_timezone=settings.local_timezone,
        session_count=args.days or settings.pre_earnings_days,
        cache_dir=settings.data_dir / "cache",
        fmp_api_key=settings.fmp_api_key,
    )
    report["tracking_update"] = update_pre_earnings_outcomes(store)
    report["local_analyst_revisions"] = enrich_report_with_local_analyst_revisions(store, report)
    report["score_v2_items_updated"] = enrich_report_with_pre_earnings_score_v2(store, report)
    report["predictions_saved"] = record_pre_earnings_predictions(store, report)
    report["analyst_snapshots_saved"] = record_pre_earnings_analyst_snapshots(store, report)
    report["estimates_backfill"] = backfill_pending_pre_earnings_estimates(
        store,
        settings.data_dir / "reports",
        f"{report['run_id']}_backfill",
        api_key=settings.fmp_api_key,
    )
    report["learning_digest"] = build_pre_earnings_learning_digest(
        store,
        settings.data_dir / "reports",
        f"{report['run_id']}_digest",
    )
    build_learning_digest_report(store, settings.data_dir / "reports", new_id("learn_digest_refresh"))
    report["mode"] = (
        "operativo_pre_earnings" if settings.pre_earnings_trade_enabled else "informativo_no_operativo"
    )
    report["operation_allowed"] = settings.pre_earnings_trade_enabled
    report["trading_operation"] = _run_pre_earnings_trade_operation(
        settings,
        store,
        EventReporter(store, verbose=False),
        report["run_id"],
        report,
    )
    if args.json:
        _print_json({"ok": True, **report})
        return
    _print_pre_earnings_report(report)


def command_pre_earnings_backtest(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    universe_name = args.universe or settings.pre_earnings_universe or settings.closed_market_study_universe
    max_symbols = args.max_symbols or settings.pre_earnings_max_symbols or settings.closed_market_study_max_symbols
    symbols = resolve_study_universe(
        universe_name,
        settings.universe,
        max_symbols,
        settings.data_dir / "cache",
    )
    report = build_pre_earnings_event_study(
        symbols=symbols,
        output_dir=settings.data_dir / "reports",
        run_id=new_id("preearn_bt"),
        start=args.start,
        end=args.end,
        calendar_name=settings.market_calendar,
        local_timezone=settings.local_timezone,
        cache_dir=settings.data_dir / "cache",
        fmp_api_key=settings.fmp_api_key,
    )
    if args.json:
        _print_json({"ok": True, **report})
        return
    _print_pre_earnings_event_study(report)


def command_pre_earnings_score_study(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    update_result = update_pre_earnings_outcomes(store)
    report = build_pre_earnings_score_study(
        store,
        settings.data_dir / "reports",
        new_id("preearn_score"),
        since_date=args.since,
        limit=args.limit,
    )
    report["tracking_update"] = update_result
    if args.json:
        _print_json({"ok": True, **report})
        return
    _print_pre_earnings_score_study(report)


def command_pre_earnings_learning_digest(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    report = build_pre_earnings_learning_digest(
        store,
        settings.data_dir / "reports",
        new_id("preearn_learn"),
        since_date=args.since,
        limit=args.limit,
    )
    build_learning_digest_report(
        store,
        settings.data_dir / "reports",
        new_id("learn_digest_refresh"),
        since_date=args.since or DEFAULT_DAILY_LEARNING_START,
    )
    if args.json:
        _print_json({"ok": True, **report})
        return
    print("PRE-EARNINGS LEARNING DIGEST")
    print(f"Informe: {report.get('path')}")
    print(f"Metricas: {report.get('metrics', {})}")
    print("Guidance:")
    for item in (report.get("digest", {}) or {}).get("guidance", []):
        print(f"  - {item}")


def command_pre_earnings_backfill_estimates(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    backfill = backfill_pending_pre_earnings_estimates(
        store,
        settings.data_dir / "reports",
        new_id("preearn_backfill"),
        limit=args.limit,
        api_key=settings.fmp_api_key,
    )
    digest = build_pre_earnings_learning_digest(
        store,
        settings.data_dir / "reports",
        new_id("preearn_learn"),
        since_date=args.since,
        limit=max(args.limit, 10000),
    )
    build_learning_digest_report(
        store,
        settings.data_dir / "reports",
        new_id("learn_digest_refresh"),
        since_date=args.since or DEFAULT_DAILY_LEARNING_START,
    )
    payload = {"backfill": backfill, "learning_digest": digest}
    if args.json:
        _print_json({"ok": True, **payload})
        return
    print("PRE-EARNINGS BACKFILL")
    print(f"Backfill: {backfill.get('path')}")
    print(
        f"actualizadas={backfill.get('updated_predictions', 0)} | "
        f"elegibles={backfill.get('eligible_predictions', 0)} | "
        f"omitidas_por_seguridad={backfill.get('skipped_temporal_safety', 0)}"
    )


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


def command_backfill_signal_candidates(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    result = backfill_signal_candidates_from_reports(
        settings,
        store,
        settings.data_dir / "reports",
        since_date=args.start,
        end_date=args.end,
        infer_selected=not args.no_infer_selected,
    )
    if args.json:
        _print_json({"ok": True, **result})
        return
    print("BACKFILL SIGNAL CANDIDATES")
    print(
        f"reports_saved={result.get('reports_saved', 0)} / {result.get('reports_scanned', 0)} | "
        f"signals_saved={result.get('signals_saved', 0)} | "
        f"inferred_reports={result.get('inferred_reports', 0)} | "
        f"skipped_reports={result.get('skipped_reports', 0)}"
    )
    if result.get("warnings"):
        print(f"Warnings: {len(result['warnings'])}")


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
                "daily_learning": report.get("daily_learning", {}),
                "llm_review": report.get("llm_review", {}),
            }
        )
        return
    _print_post_market_review(report)


def command_telegram_radar(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    if args.telegram_command == "ingest":
        report = telegram_radar_run_ingest(
            settings=settings,
            backfill=args.backfill,
            force=args.force,
            use_llm=not args.skip_llm,
        )
    elif args.telegram_command == "list":
        report = telegram_radar_list_records(
            settings=settings,
            days=args.days,
            only_opportunities=args.only_opportunities,
        )
    else:
        report = telegram_radar_build_report(
            settings=settings,
            days=args.days,
        )
        output_path = getattr(args, "out", None)
        if output_path:
            written = telegram_radar_write_markdown_report(report["markdown"], output_path)
            report["output_path"] = str(written)
    if args.json:
        _print_json(report)
        return
    if args.telegram_command == "ingest":
        print("TELEGRAM RADAR INGEST (research read-only)")
        print(f"posts_parsed={report['ingest'].get('posts_parsed', 0)} | extractions={report.get('extractions_created', 0)}")
        print(f"storage={report.get('paths', {})}")
        if report["ingest"].get("warnings"):
            print(f"warnings={report['ingest']['warnings']}")
        return
    if args.telegram_command == "report":
        if report.get("output_path"):
            print(f"TELEGRAM RADAR REPORT escrito en {report['output_path']}")
            return
        print(report["markdown"])
        return
    print("TELEGRAM RADAR LIST (research read-only)")
    print(f"returned={report['summary']['returned']} | posts={report['summary']['posts']}")
    for row in report["rows"][:20]:
        extraction = row.get("extraction") or {}
        tickers = ",".join(extraction.get("tickers", [])) or "-"
        print(
            f"- {row.get('message_id')} {row.get('posted_at') or '-'} "
            f"opp={bool(extraction.get('is_opportunity'))} tickers={tickers} "
            f"dir={extraction.get('direction', '-')}"
        )


def command_learning_postmortem(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    report = build_signal_postmortem_report(
        settings,
        store,
        settings.data_dir / "reports",
        new_id("pm_signals"),
        since_date=args.start,
        end_date=args.end,
        full=args.full,
    )
    if args.json:
        _print_json({"ok": True, **report})
        return
    _print_counterfactual_summary("POST-MORTEM DE SENALES", report)


def command_missed_opportunities(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    report = build_missed_opportunities_report(
        settings,
        store,
        settings.data_dir / "reports",
        new_id("missed"),
        since_date=args.start,
        end_date=args.end,
        top=args.top,
        full=args.full,
    )
    if args.json:
        _print_json({"ok": True, **report})
        return
    _print_counterfactual_summary("MISSED OPPORTUNITIES", report)


def command_decision_compare(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    report = build_decision_compare_report(
        settings,
        store,
        settings.data_dir / "reports",
        new_id("compare"),
        since_date=args.start,
        end_date=args.end,
        policy=args.policy,
        full=args.full,
    )
    if args.json:
        _print_json({"ok": True, **report})
        return
    _print_counterfactual_summary("COMPARACION OLD VS NEW", report)


def command_walk_forward_validate(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    report = build_walk_forward_validation_report(
        settings,
        store,
        settings.data_dir / "reports",
        new_id("wf"),
        since_date=args.start,
        end_date=args.end,
        policy=args.policy,
        train_days=args.train_days,
        test_days=args.test_days,
        full=args.full,
    )
    if args.json:
        _print_json({"ok": True, **report})
        return
    _print_counterfactual_summary("VALIDACION WALK-FORWARD", report)


def command_live_readiness(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    report = build_live_readiness_report(
        settings,
        store,
        settings.data_dir / "reports",
        new_id("live_ready"),
        since_date=args.start,
    )
    if args.json:
        _print_json({"ok": True, **report})
        return
    summary = report.get("summary", {}) or {}
    print("LIVE READINESS")
    print(f"Informe: {report.get('path')}")
    print(
        f"ready={summary.get('ready_for_live')} | "
        f"bloqueos={summary.get('blocks', 0)} | avisos={summary.get('warnings', 0)}"
    )
    for item in report.get("required_before_live", [])[:10]:
        print(f"  - BLOCK {item.get('key')}: {item.get('detail')}")
    for item in report.get("warnings", [])[:5]:
        print(f"  - WARN {item.get('key')}: {item.get('detail')}")


def command_market_data_quality(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    report = build_market_data_quality_report(
        settings,
        settings.data_dir / "reports",
        new_id("data_quality"),
        universe_name=args.universe,
        max_symbols=args.max_symbols if args.max_symbols > 0 else None,
        start=args.start,
        end=args.end,
    )
    if args.json:
        _print_json({"ok": True, **report})
        return
    _print_json({"ok": True, **report})


def command_market_data_reconciliation(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    symbols = [item.strip().upper() for item in str(args.symbols or "").split(",") if item.strip()] or None
    report = build_market_data_reconciliation_report(
        settings,
        settings.data_dir / "reports",
        new_id("data_reconcile"),
        symbols=symbols,
        start=args.start,
        end=args.end,
        tolerance_pct=args.tolerance_pct,
    )
    if args.json:
        _print_json({"ok": True, **report})
        return
    _print_json({"ok": True, **report})


def command_strategy_registry(args: argparse.Namespace) -> None:
    settings = get_settings()
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()

    # Acciones sobre el registro de estrategias plugables (T1.2).
    action_name = (
        getattr(args, "activate", None)
        or getattr(args, "shadow", None)
        or getattr(args, "retire", None)
    )
    if action_name:
        if getattr(args, "activate", None):
            new_status = "ACTIVE"
        elif getattr(args, "shadow", None):
            new_status = "SHADOW"
        else:
            new_status = "RETIRED"
        updated = store.set_strategy_status(action_name, new_status)
        if updated == 0:
            # Si aun no esta en strategy_versions, la registramos con ese estado.
            from .strategies.registry import register

            register(store, name=action_name, status=new_status)
        _print_json(
            {
                "ok": True,
                "action": new_status,
                "name": action_name,
                "strategies": store.strategy_versions(limit=args.limit),
            }
        )
        return

    if getattr(args, "list_registry", False):
        from .strategies.registry import discover

        active = [
            {"name": s.name, "version": s.version, "status": s.status}
            for s in discover(store)
        ]
        _print_json(
            {
                "ok": True,
                "discovered": active,
                "strategy_versions": store.strategy_versions(limit=args.limit),
            }
        )
        return

    proposals = store.continuous_improvement_proposals(limit=args.limit)
    validations = store.continuous_improvement_validations(limit=args.limit)
    validation_by_proposal = {
        str(item.get("proposal_id")): item
        for item in validations
        if item.get("proposal_id")
    }
    rows = []
    for proposal in proposals:
        payload = proposal.get("payload") or {}
        promotion_state = str(payload.get("promotion_state") or "unclassified")
        if args.active_only and promotion_state not in {"champion", "challenger", "shadow", "micro_experiment"}:
            continue
        validation = validation_by_proposal.get(str(proposal.get("proposal_id")))
        validation_payload = (validation or {}).get("payload") or {}
        checks = validation_payload.get("checks", []) or []
        blocking_checks = [item.get("name") for item in checks if item.get("passed") is False and item.get("name")]
        rows.append(
            {
                "proposal_id": proposal.get("proposal_id"),
                "target_component": proposal.get("target_component"),
                "target_identifier": proposal.get("target_identifier"),
                "promotion_state": promotion_state,
                "status": proposal.get("status"),
                "evaluation_window_frozen": bool(payload.get("evaluation_window_frozen")),
                "required_validations": payload.get("required_validations", []),
                "latest_validation_status": (validation or {}).get("status"),
                "latest_objective_status": validation_payload.get("objective_status"),
                "blocking_checks": blocking_checks,
                "next_review_at": payload.get("next_review_at"),
                "rollback_plan": payload.get("rollback_plan"),
            }
        )
    payload = {"ok": True, "strategies": rows, "summary": {"items": len(rows)}}
    _print_json(payload)


def command_weekly_review(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    report = build_weekly_trading_review(
        settings,
        store,
        settings.data_dir / "reports",
        new_id("weekly"),
        since_date=args.start,
        end_date=args.end,
    )
    if args.json:
        _print_json({"ok": True, **report})
        return
    _print_json({"ok": True, **report})


def command_selection_bandwidth_review(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    report = build_selection_bandwidth_review(
        settings,
        settings.data_dir / "reports",
        new_id("selection_bandwidth"),
        base_limit=args.base_limit,
        shadow_limit=args.shadow_limit,
    )
    if args.json:
        _print_json({"ok": True, **report})
        return
    _print_json({"ok": True, **report})


def command_backup_db(_: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    report = backup_database(settings, settings.data_dir / "reports", new_id("db_backup"))
    _print_json({"ok": True, **report})


def command_session_retrospective(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    report = build_session_retrospective_report(
        settings,
        store,
        settings.data_dir / "reports",
        new_id("retro"),
        since_date=args.start,
        end_date=args.end,
        sessions=args.sessions,
        policy=args.policy,
        full=args.full,
    )
    if args.json:
        _print_json({"ok": True, **report})
        return
    _print_counterfactual_summary("RETROSPECTIVA POR SESION", report)


def command_selector_replay(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    report = build_selector_replay_report(
        settings,
        settings.data_dir / "reports",
        new_id("selector_replay"),
        since_date=args.start,
        end_date=args.end,
        limit=args.limit,
        symbols=[item.strip() for item in str(args.symbols or "").split(",") if item.strip()],
        full=args.full,
    )
    if args.json:
        _print_json({"ok": True, **report})
        return
    _print_json({"ok": True, **report})


def command_winner_coverage_report(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    report = build_winner_coverage_report(
        settings,
        store,
        settings.data_dir / "reports",
        new_id("winner_coverage"),
        since_date=args.start,
        end_date=args.end,
        top_n=args.top,
        full=args.full,
    )
    if args.json:
        _print_json({"ok": True, **report})
        return
    _print_counterfactual_summary("COBERTURA DE GANADORAS", report)


def command_fallback_blocker_report(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    report = build_fallback_blocker_report(
        settings,
        store,
        settings.data_dir / "reports",
        new_id("fallback_blockers"),
        since_date=args.start,
        end_date=args.end,
        full=args.full,
    )
    if args.json:
        _print_json({"ok": True, **report})
        return
    _print_json({"ok": True, **report})


def command_commands(args: argparse.Namespace) -> None:
    if args.json:
        _print_json({"commands": available_command_catalog()})
        return
    print(command_cheatsheet())


def command_learning_daily_run(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    report = build_learning_daily_run(
        settings,
        store,
        settings.data_dir / "reports",
        new_id("learn_daily"),
        since_date=args.start,
        end_date=args.end,
        compact=not args.full,
    )
    if args.json:
        _print_json({"ok": True, **report})
        return
    print("LEARNING DAILY RUN")
    print(f"Periodo: {report['period']['from']} -> {report['period']['to']}")
    print(f"Observaciones canónicas: {report['observations_summary']['observations']}")
    print(f"Duplicados eliminados: {report['observations_summary']['duplicates_removed']}")
    print(f"Ejecutadas: {report['health']['executed_observations']}")
    print(f"Bloqueos: {len(report['health'].get('blockers', []))}")


def command_learning_health(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    report = build_learning_health_report(
        store,
        settings.data_dir / "reports",
        new_id("learn_health"),
        since_date=args.start,
        end_date=args.end,
    )
    if args.json:
        _print_json({"ok": True, **report})
        return
    health = report["health"]
    print("LEARNING HEALTH")
    print(
        f"raw={health['signals_raw']} | canonicas={health['canonical_observations']} | "
        f"duplicadas={health['duplicate_signals']} ({_pct(health['duplicate_ratio'])})"
    )
    print(f"outcomes disponibles={health['outcomes_available']} | ejecutadas={health['executed_observations']}")
    print(f"Cobertura: {health['horizon_coverage']}")
    for blocker in health.get("blockers", []):
        print(f"  - [{blocker['severity']}] {blocker['kind']}: {blocker['detail']}")


def command_learning_digest(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    report = build_learning_digest_report(
        store,
        settings.data_dir / "reports",
        new_id("learn_digest"),
        since_date=args.start,
        end_date=args.end,
    )
    if args.json:
        _print_json({"ok": True, **report})
        return
    digest = report["digest"]
    print("LEARNING DIGEST")
    print(f"Resumen: {digest['summary']}")
    if (digest.get("pre_earnings") or {}).get("available"):
        print(f"Pre-earnings: {(digest.get('pre_earnings') or {}).get('summary', {})}")
    print("Guidance:")
    for item in digest.get("guidance", []):
        print(f"  - {item}")


def command_policy_candidates(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    report = build_policy_candidates_report(store, settings.data_dir / "reports", new_id("policy"))
    if args.json:
        _print_json({"ok": True, **report})
        return
    print("POLICY CANDIDATES")
    for item in report.get("policies", []):
        print(
            f"  - [{item['status']}] {item['policy_id']} | {item['name']} | "
            f"auto={item['auto_activatable']} | metrics={item.get('metrics', {})}"
        )


def command_learning_promotions(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    report = build_learning_promotions_report(store, settings.data_dir / "reports", new_id("promotions"))
    if args.json:
        _print_json({"ok": True, **report})
        return
    print("LEARNING PROMOTIONS")
    for item in report.get("policies", []):
        print(f"  - [{item['status']}] {item['policy_id']} | promoted_at={item.get('promoted_at') or '-'}")


def command_autonomy_digest(args: argparse.Namespace) -> None:
    from .tools.autonomy_digest import build_autonomy_digest, pause_all, resume_all

    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    if getattr(args, "pause", False):
        _print_json({"ok": True, **pause_all(store, settings)})
        return
    if getattr(args, "resume", False):
        _print_json({"ok": True, **resume_all(store, settings)})
        return
    result = build_autonomy_digest(store, settings)
    if getattr(args, "json", False):
        _print_json({"ok": True, "date": result["date"], "path": result["path"], "state": result["state"]})
        return
    print(result["markdown"])


def command_edge_report(args: argparse.Namespace) -> None:
    from .tools.naive_benchmarks import edge_report

    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    report = edge_report(store, sessions=getattr(args, "sessions", 60))
    if getattr(args, "json", False):
        _print_json({"ok": True, "system_freeze_mode": settings.system_freeze_mode, **report})
        return
    print("EDGE REPORT")
    print(f"  Veredicto: {report['verdict']} (freeze={'on' if settings.system_freeze_mode else 'off'})")
    print(f"  Sesiones: {report['sessions']}")
    print(f"  alpha vs SPY: {report['alpha_vs_spy']} (t={report['t_stat_vs_spy']})")
    print(f"  alpha vs naive momentum: {report['alpha_vs_naive_momentum']} (t={report['t_stat_vs_naive_momentum']})")


def command_risk_budget(args: argparse.Namespace) -> None:
    from .risk_budget import available_now

    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    _print_json({"ok": True, "enabled": settings.risk_budget_enabled, **available_now(store, settings)})


def command_pattern_scorecard(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    if getattr(args, "build", False):
        from .tools.pattern_scorecard import build_pattern_scorecard

        _print_json({"ok": True, **build_pattern_scorecard(store, min_occurrences=settings.pattern_min_occurrences)})
        return
    _print_json({"ok": True, "patterns": store.pattern_stats(limit=getattr(args, "limit", 200))})


def command_factory_status(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    if getattr(args, "run", False):
        from .tools.hypothesis_factory import run_factory

        _print_json({"ok": True, **run_factory(store, settings)})
        return
    _print_json({"ok": True, "runs": store.factory_runs(limit=getattr(args, "limit", 30))})


def command_market_thesis(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    if getattr(args, "build", False):
        from .tools.macro_context import build_market_thesis
        from .tools.market_state import load_latest_market_state

        market_state = load_latest_market_state(settings.data_dir / "reports") or {}
        thesis = build_market_thesis(store, settings, market_state=market_state)
        _print_json({"ok": True, **thesis})
        return
    latest = store.latest_market_thesis()
    _print_json({"ok": bool(latest), "thesis": latest})


def command_lessons(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    if getattr(args, "retire", None):
        updated = store.set_lesson_status(args.retire, "RETIRED")
        _print_json({"ok": bool(updated), "retired": args.retire})
        return
    if getattr(args, "distill", False):
        from .continuous_improvement.lesson_distiller import distill_lessons

        _print_json({"ok": True, **distill_lessons(store, settings)})
        return
    if getattr(args, "revalidate", False):
        from .continuous_improvement.lesson_distiller import revalidate_lessons

        _print_json({"ok": True, **revalidate_lessons(store, settings)})
        return
    rows = store.distilled_lessons(limit=getattr(args, "limit", 100))
    if getattr(args, "json", False):
        _print_json({"ok": True, "lessons": rows})
        return
    print("DISTILLED LESSONS")
    for row in rows:
        print(f"  [{row['status']}] conf={row['confidence']:.2f} ({row['scope']}) {row['statement'][:80]}")


def command_retrospective(args: argparse.Namespace) -> None:
    from datetime import datetime, timezone

    from .tools.nightly_retrospective import run_nightly_retrospective

    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    session_date = getattr(args, "date", None) or datetime.now(timezone.utc).date().isoformat()
    result = run_nightly_retrospective(store, settings, session_date)
    _print_json({"ok": True, **result})


def command_prompts(args: argparse.Namespace) -> None:
    from . import prompt_store

    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    Store(settings.database_path, settings.agent_logs_dir).ensure_schema()
    if getattr(args, "import_defaults", False):
        result = prompt_store.import_prompts(settings, prompt_store.default_prompt_catalog())
        _print_json({"ok": True, **result})
        return
    if getattr(args, "promote", None) and getattr(args, "key", None):
        prompt_store.promote(settings, args.key, int(args.promote))
        _print_json({"ok": True, "promoted": {"key": args.key, "version": int(args.promote)}})
        return
    rows = prompt_store.list_prompts(settings)
    if getattr(args, "json", False):
        _print_json({"ok": True, "prompts": rows})
        return
    print("PROMPTS")
    for row in rows:
        print(f"  [{row['status']}] {row['prompt_key']} v{row['version']} (by {row['created_by']})")


def command_promotions(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    if getattr(args, "evaluate", False):
        from .continuous_improvement.promotion import PromotionManager

        decisions = PromotionManager(store, settings).evaluate_windows()
        _print_json({"ok": True, "decisions": decisions})
        return
    windows = store.promotion_windows(limit=getattr(args, "limit", 100))
    if getattr(args, "json", False):
        _print_json({"ok": True, "windows": windows})
        return
    print("PROMOTION WINDOWS")
    for window in windows:
        print(f"  [{window['status']}] {window['strategy']} v{window['version']} (slot={window['slot']})")


def command_llm_usage(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    if getattr(args, "by_role", False):
        rows = store.llm_usage_by_role(limit=getattr(args, "limit", 1000))
        if getattr(args, "json", False):
            _print_json({"ok": True, "by_role": rows})
            return
        print("LLM USAGE POR ROL")
        print("  rol           requests  prompt_tok  completion_tok  total_tok")
        for row in rows:
            print(
                f"  {row['role']:<12}  {row['requests']:>8}  {row['prompt_tokens']:>10}  "
                f"{row['completion_tokens']:>14}  {row['total_tokens']:>9}"
            )
        return
    rows = store.daily_llm_usage(limit=getattr(args, "limit", 30))
    if getattr(args, "json", False):
        _print_json({"ok": True, "daily": rows})
        return
    print("LLM USAGE DIARIO")
    for row in rows:
        print(f"  {row}")


def command_performance(args: argparse.Namespace) -> None:
    from datetime import datetime, timedelta, timezone

    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    days = max(1, int(getattr(args, "days", 30)))
    since = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    rows = store.performance_daily(limit=0, since_date=since)
    if getattr(args, "json", False):
        _print_json({"ok": True, "days": days, "rows": rows})
        return
    print(f"PERFORMANCE (ultimos {days} dias)")
    if not rows:
        print("  Sin filas de rendimiento todavia. Ejecuta el review post-mercado.")
        return
    print("  fecha       equity        pnl%     spy%     alpha     hit20   sharpe60  maxdd   iq")
    for row in rows:
        def _f(value, fmt):
            return fmt % value if isinstance(value, (int, float)) else "   -  "

        print(
            f"  {row['session_date']}  {_f(row.get('equity'), '%11.2f')}  "
            f"{_f(row.get('pnl_pct'), '%7.4f')}  {_f(row.get('spy_pct'), '%7.4f')}  "
            f"{_f(row.get('alpha'), '%8.4f')}  {_f(row.get('hit_rate_20'), '%6.2f')}  "
            f"{_f(row.get('sharpe_60'), '%8.2f')}  {_f(row.get('max_dd'), '%6.3f')}  "
            f"{_f(row.get('iq_score'), '%5.1f')}"
        )


def command_iq_score(args: argparse.Namespace) -> None:
    from .tools.performance_baseline import system_iq_score

    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    window = max(1, int(getattr(args, "window", 20)))
    score = system_iq_score(store, window_days=window)
    latest = store.latest_performance_daily()
    payload = {
        "iq_score": score,
        "window_days": window,
        "latest_session": (latest or {}).get("session_date"),
    }
    if getattr(args, "json", False):
        _print_json({"ok": True, **payload})
        return
    print("IQ SCORE")
    print(f"  Score compuesto (ventana {window}d): {score}")
    print(f"  Ultima sesion registrada: {payload['latest_session']}")


def command_kernel_unlock_live(args: argparse.Namespace) -> None:
    """Desbloqueo de live: SIEMPRE humano y doble (T4.3).

    Exige (1) ALLOW_LIVE_TRADING=true en .env y (2) confirmacion interactiva, y
    re-sella el manifest del kernel. Los agentes no pueden ejecutar esto.
    """

    from .kernel import kernel_seal
    from .tools.live_readiness import build_live_readiness_report

    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()

    if not settings.allow_live_trading:
        _print_json({"ok": False, "error": "Primero edita .env con ALLOW_LIVE_TRADING=true (paso manual 1/2)."})
        return
    report = build_live_readiness_report(settings, store, settings.data_dir / "reports", new_id("live_ready"))
    if not report["summary"]["ready_for_live"]:
        _print_json({"ok": False, "error": "live-readiness con bloqueos.", "blocks": report["required_before_live"]})
        return
    if not getattr(args, "yes", False):
        confirm = input("Escribe 'DESBLOQUEAR LIVE' para confirmar el desbloqueo: ")
        if confirm.strip() != "DESBLOQUEAR LIVE":
            _print_json({"ok": False, "error": "confirmacion no coincide; abortado."})
            return
    sealed = kernel_seal(settings)
    log_system_event(settings.logs_dir, "kernel_live_unlocked", {"manifest": sealed.get("path")})
    _print_json({"ok": True, "unlocked": True, "manifest": sealed.get("path"), "live_capital_fraction": settings.live_capital_fraction})


def command_kernel_seal(args: argparse.Namespace) -> None:
    from .kernel import kernel_seal

    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    result = kernel_seal(settings)
    if getattr(args, "json", False):
        _print_json({"ok": True, **result})
        return
    print("KERNEL SEAL")
    print(f"Manifest: {result['path']}")
    print(f"Sellado: {result['sealed_at']}")
    for rel, digest in result.get("files", {}).items():
        shown = digest[:16] + "..." if isinstance(digest, str) else "(ausente)"
        print(f"  - {rel}: {shown}")


def command_kernel_status(args: argparse.Namespace) -> None:
    from .kernel import kernel_integrity

    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    result = kernel_integrity(settings)
    if getattr(args, "json", False):
        _print_json({"ok": result.get("ok", False), **result})
        return
    print("KERNEL STATUS")
    print(f"Estado: {result['status']}")
    print(f"Sellado: {result.get('sealed_at')}")
    if result.get("violations"):
        print(f"Violaciones: {result['violations']}")
    for rel, info in (result.get("files") or {}).items():
        match = info.get("match")
        flag = "ok" if match else ("sin-sellar" if match is None else "ALTERADO")
        print(f"  - [{flag}] {rel}")


def command_operational_health(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    report = build_operational_health_report(
        settings,
        store,
        settings.data_dir / "reports",
        new_id("ops_health"),
    )
    if args.json:
        _print_json({"ok": True, **report})
        return
    print("OPERATIONAL HEALTH")
    print(f"Estado general: {report['summary']['overall_status']}")
    print(
        f"Alertas: {report['summary']['alerts']} | severidad={report['summary']['severity_counts']} | "
        f"responses={report['summary'].get('responses', 0)}"
    )
    for item in report.get("alerts", [])[:12]:
        scope = item.get("job") or item.get("scope") or "-"
        print(f"  - [{item['severity']}] {item['kind']} | {scope} | {item['detail']}")
    if report.get("responses"):
        print("Respuestas operativas:")
        for item in report["responses"][:8]:
            print(
                f"  - [{item['status']}] {item['action']} | {item.get('scope', '-')} | "
                f"{item.get('detail', '')}"
            )


def command_operational_responses(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    report = build_operational_health_report(
        settings,
        store,
        settings.data_dir / "reports",
        new_id("ops_resp"),
    )
    payload = {
        "run_id": report.get("run_id"),
        "as_of": report.get("as_of"),
        "summary": report.get("summary", {}),
        "responses": report.get("responses", []),
        "alerts": report.get("alerts", []),
        "path": report.get("path"),
    }
    if args.json:
        _print_json({"ok": True, **payload})
        return
    print("OPERATIONAL RESPONSES")
    print(f"Estado general: {payload['summary'].get('overall_status')}")
    print(f"Respuestas: {len(payload.get('responses', []))}")
    for item in payload.get("responses", [])[:12]:
        print(
            f"  - [{item['status']}] {item['action']} | {item.get('scope', '-')} | "
            f"{item.get('detail', '')}"
        )


def command_production_health(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    report = build_production_health_report(
        settings,
        store,
        settings.data_dir / "reports",
        new_id("prod_health"),
    )
    if args.json:
        _print_json({"ok": True, **report})
        return
    print("PRODUCTION HEALTH")
    print(f"Estado general: {report['summary']['overall_status']}")
    print(
        f"Salud: {report['summary']['healthy']} | alertas={report['summary']['alerts']} | "
        f"responses={report['summary'].get('responses', 0)}"
    )
    print(
        f"Scheduler: {report['summary'].get('scheduler_heartbeat', {}).get('status')} | "
        f"CI: {report['summary'].get('continuous_improvement_heartbeat', {}).get('status')}"
    )
    for item in report.get("alerts", [])[:12]:
        scope = item.get("job") or item.get("scope") or "-"
        print(f"  - [{item['severity']}] {item['kind']} | {scope} | {item['detail']}")


def command_continuous_improvement(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    orchestrator = ContinuousImprovementOrchestrator(settings, store)
    dedupe_key = args.dedupe_key
    report = orchestrator.run_cycle(mode=args.mode, dedupe_key=dedupe_key, force=args.force)
    if args.json:
        _print_json({"ok": True, **report})
        return
    print("MEJORA CONTINUA")
    print(f"Ciclo: {report.get('cycle_id')} | estado={report.get('status')} | dry_run={report.get('dry_run')}")
    print(f"LLM: {report.get('llm_status')} | call={report.get('llm_call_id')}")
    proposals = report.get("proposals", []) or (report.get("report", {}) or {}).get("proposals", []) or []
    new_count = len([item for item in proposals if not item.get("duplicate_existing")])
    print(f"Propuestas: {len(proposals)} | nuevas: {new_count}")
    for item in proposals[:10]:
        payload = item.get("payload", {}) or {}
        print(
            "  - "
            f"[{item.get('status')}] {item.get('proposal_type')} "
            f"{item.get('target_component')}:{item.get('target_identifier')} | "
            f"riesgo={item.get('risk_level')} | {payload.get('rationale', '')}"
        )
    if (report.get("report") or {}).get("path"):
        print(f"Informe: {report['report']['path']}")


def command_continuous_improvement_lab(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    runtime = ContinuousImprovementLabRuntime(settings, store)

    if args.lab_command == "start":
        runtime.run_forever(max_cycles=args.max_cycles)
        return
    if args.lab_command == "status":
        _print_json(
            {
                "ok": True,
                "runtime": store.continuous_improvement_runtime_state(),
                "latest_cycle": store.latest_continuous_improvement_cycle(),
                "events": store.continuous_improvement_events(limit=args.limit),
                "tasks": store.continuous_improvement_tasks(limit=args.limit),
                "hypotheses": store.continuous_improvement_hypotheses(limit=args.limit),
            }
        )
        return
    if args.lab_command == "run-once":
        report = runtime.run_once(mode="manual", trigger_event_type="manual_trigger", trigger_payload={"source": "cli"})
        if args.json:
            _print_json({"ok": True, **report})
        else:
            print(f"LAB RUN-ONCE | ciclo={report.get('cycle_id')} | estado={report.get('status')}")
        return
    if args.lab_command == "enqueue":
        payload = {}
        if args.payload:
            payload = json.loads(args.payload)
        response = runtime.enqueue_event(
            event_type=args.event_type,
            source="cli",
            domain=args.domain,
            payload=payload,
            force_unique=args.force_unique,
        )
        _print_json({"ok": True, **response})
        return
    if args.lab_command == "agents":
        _print_json({"ok": True, "agents": runtime.describe_agents()})
        return
    if args.lab_command == "applied-changes":
        statuses = args.status if args.status else None
        _print_json(
            {
                "ok": True,
                "applied_changes": store.continuous_improvement_applied_changes(
                    statuses=statuses,
                    limit=args.limit,
                ),
            }
        )
        return
    if args.lab_command == "digest":
        if args.out:
            target = Path(args.out)
            digest = build_lab_digest(store, days=args.days)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(format_lab_digest_text(digest), encoding="utf-8")
            result = {"ok": True, "path": str(target), "digest": digest}
            if args.json:
                _print_json(result)
            else:
                print(f"Digest escrito: {result['path']}")
            return
        digest = build_lab_digest(store, days=args.days)
        if args.json:
            _print_json({"ok": True, "digest": digest})
        else:
            print(format_lab_digest_text(digest))
        return
    if args.lab_command == "rollback":
        change = AutoApplyCodeAgent().rollback(
            settings=settings,
            store=store,
            applied_change_id=args.applied_change_id,
            actor="cli",
        )
        _print_json({"ok": bool(change), "applied_change": change})
        return
    if args.lab_command == "autonomy-status":
        from .continuous_improvement.autonomy import (
            AUTONOMY_TIERS,
            active_autonomy_level,
            autonomy_promotion_check,
        )

        committee_decisions = store.continuous_improvement_decisions(actor="DecisionCommitteeAgent", limit=1000)
        decision_counts: dict[str, int] = {}
        backlog_buckets: dict[str, int] = {}
        for item in committee_decisions:
            decision = str(item.get("decision") or "UNKNOWN")
            decision_counts[decision] = decision_counts.get(decision, 0) + 1
            bucket = str(((item.get("payload") or {}).get("committee_decision") or {}).get("backlog_bucket") or "UNKNOWN")
            backlog_buckets[bucket] = backlog_buckets.get(bucket, 0) + 1
        level = active_autonomy_level(store, settings)
        # Solo lectura: calcula el progreso sin persistir cambios de nivel.
        progress = autonomy_promotion_check(store, settings, persist=False)
        _print_json(
            {
                "ok": True,
                "enabled": settings.continuous_improvement_enabled,
                "dry_run": settings.improvement_dry_run,
                "allow_auto_apply": settings.allow_auto_apply_improvements,
                "require_human_approval_for_code_changes": settings.require_human_approval_for_code_changes,
                "allow_live_trading": settings.allow_live_trading,
                "workspace": str(settings.improvement_workspace_dir),
                "code_autonomy_level": level,
                "max_level": max(AUTONOMY_TIERS),
                "allowed_prefixes": list(AUTONOMY_TIERS[level]["allowed_prefixes"]),
                "promotion_progress": progress,
                "ready_to_apply": len(store.continuous_improvement_proposals(status="READY_TO_APPLY", limit=1000)),
                "applied": len(store.continuous_improvement_applied_changes(statuses=["APPLIED"], limit=1000)),
                "blocked": len(store.continuous_improvement_applied_changes(statuses=["BLOCKED"], limit=1000)),
                "rolled_back": len(store.continuous_improvement_applied_changes(statuses=["ROLLED_BACK"], limit=1000)),
                "committee_decisions": decision_counts,
                "backlog_buckets": backlog_buckets,
            }
        )
        return
    if args.lab_command == "phase1-status":
        experiments = store.continuous_improvement_experiments(limit=args.limit)
        ready = store.continuous_improvement_proposals(status="READY_TO_APPLY", limit=args.limit)
        applied = store.continuous_improvement_applied_changes(limit=args.limit)
        _print_json(
            {
                "ok": True,
                "runtime": store.continuous_improvement_runtime_state(),
                "experiments_count": len(store.continuous_improvement_experiments(limit=10000)),
                "ready_to_apply_count": len(store.continuous_improvement_proposals(status="READY_TO_APPLY", limit=10000)),
                "applied_changes_count": len(store.continuous_improvement_applied_changes(limit=10000)),
                "recent_experiments": experiments,
                "ready_to_apply": ready,
                "applied_changes": applied,
            }
        )
        return
    if args.lab_command == "dynamic-agents":
        if getattr(args, "score", False):
            from .continuous_improvement.dynamic_agents import score_dynamic_agents

            _print_json({"ok": True, "scores": score_dynamic_agents(store)})
            return
        _print_json({"ok": True, "agents": store.agent_definitions(limit=getattr(args, "limit", 100))})
        return
    if args.lab_command == "build-strategy":
        from .continuous_improvement.strategy_builder import build_strategy_from_spec

        try:
            spec = json.loads(args.spec) if getattr(args, "spec", None) else {}
        except json.JSONDecodeError as exc:
            _print_json({"ok": False, "error": f"spec JSON invalido: {exc}"})
            return
        result = build_strategy_from_spec(store, settings, spec)
        _print_json({"ok": result.get("ok", False), **result})
        return
    if args.lab_command == "gen-diff":
        from .continuous_improvement.codegen import (
            create_demo_codegen_proposal,
            generate_code_diff_for_proposal,
        )

        proposal_id = args.proposal
        if getattr(args, "demo", False):
            proposal_id = create_demo_codegen_proposal(store)
        if not proposal_id:
            _print_json({"ok": False, "error": "Indica --proposal <id> o usa --demo."})
            return
        result = generate_code_diff_for_proposal(settings=settings, store=store, proposal_id=proposal_id)
        if args.json:
            _print_json({"ok": result.get("ok", False), **result})
        else:
            artifact = result.get("artifact") or {}
            print(
                "GEN-DIFF | "
                f"proposal={proposal_id} | status={result.get('status')} | "
                f"artifact={artifact.get('artifact_id')} | type={artifact.get('artifact_type')}"
            )
        return
    if args.lab_command == "review":
        from .continuous_improvement.human_apply import review_code_diff_artifacts

        result = review_code_diff_artifacts(store, proposal_id=args.proposal, limit=args.limit)
        if args.json:
            _print_json(result)
        else:
            for artifact in result["artifacts"]:
                payload = artifact.get("payload") or {}
                print(
                    "DIFF READY | "
                    f"proposal={artifact.get('proposal_id')} | artifact={artifact.get('artifact_id')} | "
                    f"tests_ok={payload.get('tests_ok')} | targets={', '.join(artifact.get('target_paths') or [])}"
                )
                validation = payload.get("validation") or {}
                print(f"VALIDATION: ok={validation.get('ok')} steps={len(validation.get('steps') or [])}")
                print(artifact.get("content_text") or "")
        return
    if args.lab_command == "approve":
        from .continuous_improvement.human_apply import approve_and_apply_code_diff

        result = approve_and_apply_code_diff(
            settings=settings,
            store=store,
            proposal_id=args.proposal,
            actor=args.actor,
        )
        if args.json:
            _print_json({"ok": result.get("ok", False), **result})
        else:
            print(
                "APPROVE | "
                f"proposal={args.proposal} | status={result.get('status')} | "
                f"commit={result.get('commit')} | applied_change={result.get('applied_change_id')} | "
                f"error={result.get('error') or ''}"
            )
        return
    raise ValueError(f"Unknown lab command: {args.lab_command}")


def command_continuous_improvement_api(args: argparse.Namespace) -> None:
    run_api_server(host=args.host, port=args.port)


def command_validate_agent_config(args: argparse.Namespace) -> None:
    payload = validate_agent_task_config(load_agent_config(), load_task_config())
    if args.json or not payload["ok"]:
        _print_json(payload)
        return
    print("Configuracion valida")


def command_market_state(args: argparse.Namespace) -> None:
    settings = get_settings()
    if getattr(args, "latest", False):
        payload = load_latest_market_state(settings.data_dir / "reports")
        if payload is None:
            raise FileNotFoundError("No existe ningun market_state previo en data/reports.")
        if args.json:
            _print_json(payload)
            return
        print(payload.get("path") or "")
        return
    run_id = new_id("market_state")
    payload = build_market_state(
        settings,
        settings.data_dir / "reports",
        run_id,
    )
    if args.json:
        _print_json(payload)
        return
    print(payload.get("path") or "")


def command_agents(_: argparse.Namespace) -> None:
    config = load_agent_config()
    tasks = load_task_config()
    usage = validate_agent_task_config(config, tasks).get("agent_usage", {})
    rows = []
    for agent, meta in config.items():
        info = AGENTS.get(agent)
        rows.append(
            {
                "code": info.code if info else "AGNT",
                "agent": agent,
                "title": info.title if info else meta["role"],
                "lane": meta["lane"],
                "status": meta["status"],
                "uses_llm": meta["uses_llm"],
                "can_block_execution": meta["can_block_execution"],
                "runtime_entrypoints": meta["runtime_entrypoints"],
                "tasks": usage.get(agent, []),
            }
        )
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


def command_cycle_funnel(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    if getattr(args, "shadow_scoreboard", False):
        from .tools.cycle_funnel import build_shadow_scoreboard, format_shadow_scoreboard

        scoreboard = build_shadow_scoreboard(settings, limit=args.history or 10)
        if getattr(args, "json", False):
            _print_json(scoreboard)
        else:
            print(format_shadow_scoreboard(scoreboard))
        return
    if getattr(args, "history", 0) and args.history > 0:
        from .tools.cycle_funnel import build_cycle_funnel_history, format_cycle_funnel_history

        agg = build_cycle_funnel_history(store, settings, limit=args.history)
        if getattr(args, "json", False):
            _print_json(agg)
        else:
            print(format_cycle_funnel_history(agg))
        return

    from .tools.cycle_funnel import build_cycle_funnel, format_cycle_funnel

    funnel = build_cycle_funnel(store, settings)
    if getattr(args, "json", False):
        _print_json(funnel)
    else:
        print(format_cycle_funnel(funnel))


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
    elif args.job == "broker-reconciliation":
        report = broker_reconciliation_job(settings, store, verbose=not args.quiet, force=args.force)
        if report and not args.quiet:
            _print_json({"ok": True, **report})
    elif args.job == "pre-earnings":
        report = pre_earnings_job(
            settings,
            store,
            verbose=not args.quiet,
            force=args.force,
        )
        if report and not args.quiet:
            print()
            _print_pre_earnings_report(report)
    elif args.job == "opportunity-snapshot":
        opportunity_snapshot_job(
            settings,
            store,
            slot_time=parse_opportunity_snapshot_times(args.slot)[0],
            verbose=not args.quiet,
            force=args.force,
        )
    elif args.job == "continuous-improvement":
        report = continuous_improvement_job(settings, store, verbose=not args.quiet, force=True)
        if report and not args.quiet:
            _print_json({"ok": True, **report})
    elif args.job == "overnight-learning":
        report = overnight_learning_heartbeat_job(settings, store, verbose=not args.quiet, force=args.force)
        if report and not args.quiet:
            _print_json({"ok": True, **report})


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

    cycle_funnel = subparsers.add_parser(
        "cycle-funnel",
        help="Embudo del ultimo market_cycle: universo->candidatos->gates->fills con motivos de rechazo.",
    )
    cycle_funnel.add_argument("--json", action="store_true", help="Salida JSON en vez de texto.")
    cycle_funnel.add_argument(
        "--history",
        type=int,
        default=0,
        help="Agrega los ultimos N ciclos (motivos de rechazo acumulados) en vez del ultimo.",
    )
    cycle_funnel.add_argument(
        "--shadow-scoreboard",
        action="store_true",
        help="Resume shadow_candidates por estrategia en los ultimos N reportes tecnicos.",
    )
    cycle_funnel.set_defaults(func=command_cycle_funnel)

    retention_cleanup = subparsers.add_parser(
        "retention-cleanup",
        help="Aplica la politica de retencion sobre reports, logs y cache.",
    )
    retention_cleanup.set_defaults(func=command_retention_cleanup)

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

    backfill_signal_candidates = subparsers.add_parser(
        "backfill-signal-candidates",
        help="Reconstruye signal_outcomes historicos desde reportes cerrados persistidos en data/reports.",
    )
    backfill_signal_candidates.add_argument(
        "--from",
        dest="start",
        default=DEFAULT_HISTORY_START_DATE,
        help=f"Fecha inicial YYYY-MM-DD. Por defecto {DEFAULT_HISTORY_START_DATE}.",
    )
    backfill_signal_candidates.add_argument("--to", dest="end", help="Fecha final YYYY-MM-DD.")
    backfill_signal_candidates.add_argument(
        "--no-infer-selected",
        action="store_true",
        help="No infiere selected_candidates desde top_longs/top_shorts cuando falten en el reporte.",
    )
    backfill_signal_candidates.add_argument("--json", action="store_true", help="Devuelve el resultado en JSON.")
    backfill_signal_candidates.set_defaults(func=command_backfill_signal_candidates)

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

    learning_daily = subparsers.add_parser(
        "learning-daily-run",
        help="Ejecuta el ledger incremental diario con deduplicacion, digest y candidatos de politica.",
    )
    learning_daily.add_argument(
        "--from",
        dest="start",
        default=DEFAULT_DAILY_LEARNING_START,
        help=f"Fecha inicial YYYY-MM-DD. Por defecto {DEFAULT_DAILY_LEARNING_START}.",
    )
    learning_daily.add_argument("--to", dest="end", help="Fecha final YYYY-MM-DD.")
    learning_daily.add_argument("--full", action="store_true", help="Incluye observaciones y filas detalladas.")
    learning_daily.add_argument("--json", action="store_true", help="Devuelve el informe en JSON.")
    learning_daily.set_defaults(func=command_learning_daily_run)

    learning_health = subparsers.add_parser(
        "learning-health",
        help="Muestra bloqueos del aprendizaje: duplicados, cobertura de outcomes y volumen real.",
    )
    learning_health.add_argument(
        "--from",
        dest="start",
        default=DEFAULT_DAILY_LEARNING_START,
        help=f"Fecha inicial YYYY-MM-DD. Por defecto {DEFAULT_DAILY_LEARNING_START}.",
    )
    learning_health.add_argument("--to", dest="end", help="Fecha final YYYY-MM-DD.")
    learning_health.add_argument("--json", action="store_true", help="Devuelve el informe en JSON.")
    learning_health.set_defaults(func=command_learning_health)

    learning_digest = subparsers.add_parser(
        "learning-digest",
        help="Imprime el digest determinista que consume la siguiente decision de trading.",
    )
    learning_digest.add_argument(
        "--from",
        dest="start",
        default=DEFAULT_DAILY_LEARNING_START,
        help=f"Fecha inicial YYYY-MM-DD. Por defecto {DEFAULT_DAILY_LEARNING_START}.",
    )
    learning_digest.add_argument("--to", dest="end", help="Fecha final YYYY-MM-DD.")
    learning_digest.add_argument("--json", action="store_true", help="Devuelve el informe en JSON.")
    learning_digest.set_defaults(func=command_learning_digest)

    policy_candidates = subparsers.add_parser(
        "policy-candidates",
        help="Lista reglas shadow/candidate/guarded-active/active y su evidencia.",
    )
    policy_candidates.add_argument("--json", action="store_true", help="Devuelve el informe en JSON.")
    policy_candidates.set_defaults(func=command_policy_candidates)

    learning_promotions = subparsers.add_parser(
        "learning-promotions",
        help="Audita que reglas se promovieron, cuando y con que evidencia.",
    )
    learning_promotions.add_argument("--json", action="store_true", help="Devuelve el informe en JSON.")
    learning_promotions.set_defaults(func=command_learning_promotions)

    autonomy_digest = subparsers.add_parser(
        "autonomy-digest",
        help="Digest de autonomia y freno humano (T4.2): resumen, pausa o reanuda.",
    )
    autonomy_digest.add_argument("--pause", action="store_true", help="PAUSA TOTAL: kill switch + congelar laboratorio + cancelar ordenes.")
    autonomy_digest.add_argument("--resume", action="store_true", help="Reanuda tras una pausa total.")
    autonomy_digest.add_argument("--json", action="store_true", help="Salida JSON.")
    autonomy_digest.set_defaults(func=command_autonomy_digest)

    edge_report = subparsers.add_parser(
        "edge-report",
        help="Validacion del edge base vs SPY y momentum ingenuo (T5.1).",
    )
    edge_report.add_argument("--sessions", type=int, default=60, help="Numero de sesiones a evaluar.")
    edge_report.add_argument("--json", action="store_true", help="Salida JSON.")
    edge_report.set_defaults(func=command_edge_report)

    risk_budget = subparsers.add_parser(
        "risk-budget",
        help="Presupuesto de riesgo vigente (T4.1): VaR diario, riesgo nuevo y por cluster.",
    )
    risk_budget.add_argument("--json", action="store_true", help="Salida JSON.")
    risk_budget.set_defaults(func=command_risk_budget)

    pattern_scorecard = subparsers.add_parser(
        "pattern-scorecard",
        help="Scorecard de figuras auto-evaluado (T3.3): lift por patron.",
    )
    pattern_scorecard.add_argument("--build", action="store_true", help="Recalcula el scorecard ahora.")
    pattern_scorecard.add_argument("--limit", type=int, default=200)
    pattern_scorecard.add_argument("--json", action="store_true", help="Salida JSON.")
    pattern_scorecard.set_defaults(func=command_pattern_scorecard)

    factory_status = subparsers.add_parser(
        "factory-status",
        help="Granja de backtests en lote (T3.2): muestra runs o ejecuta uno.",
    )
    factory_status.add_argument("--run", action="store_true", help="Ejecuta la fabrica ahora.")
    factory_status.add_argument("--limit", type=int, default=30)
    factory_status.add_argument("--json", action="store_true", help="Salida JSON.")
    factory_status.set_defaults(func=command_factory_status)

    market_thesis = subparsers.add_parser(
        "market-thesis",
        help="Tesis de mercado viva (T3.1): muestra la ultima o construye una nueva.",
    )
    market_thesis.add_argument("--build", action="store_true", help="Construye la tesis del dia.")
    market_thesis.add_argument("--latest", action="store_true", help="Muestra la ultima tesis (por defecto).")
    market_thesis.add_argument("--json", action="store_true", help="Salida JSON.")
    market_thesis.set_defaults(func=command_market_thesis)

    lessons = subparsers.add_parser(
        "lessons",
        help="Memoria destilada (T2.4): lista, destila, revalida o retira lecciones.",
    )
    lessons.add_argument("--distill", action="store_true", help="Destila lecciones desde el historico.")
    lessons.add_argument("--revalidate", action="store_true", help="Revalida lecciones ACTIVE/WEAKENED.")
    lessons.add_argument("--retire", metavar="LESSON_ID", help="Retira una leccion por id.")
    lessons.add_argument("--limit", type=int, default=100)
    lessons.add_argument("--json", action="store_true", help="Devuelve las lecciones en JSON.")
    lessons.set_defaults(func=command_lessons)

    retrospective = subparsers.add_parser(
        "retrospective",
        help="Retrospectiva generativa nocturna: perdidas -> hipotesis (T2.3).",
    )
    retrospective.add_argument("--date", help="Fecha de sesion YYYY-MM-DD. Por defecto hoy.")
    retrospective.add_argument("--json", action="store_true", help="Devuelve el resultado en JSON.")
    retrospective.set_defaults(func=command_retrospective)

    prompts = subparsers.add_parser(
        "prompts",
        help="Prompts versionados (T2.1). Lista, importa defaults o promueve una version.",
    )
    prompts.add_argument("--import-defaults", dest="import_defaults", action="store_true", help="Carga los prompts por defecto como v1 ACTIVE (idempotente).")
    prompts.add_argument("--key", help="Clave de prompt a promover.")
    prompts.add_argument("--promote", help="Version a promover a ACTIVE (requiere --key).")
    prompts.add_argument("--json", action="store_true", help="Devuelve el listado en JSON.")
    prompts.set_defaults(func=command_prompts)

    promotions = subparsers.add_parser(
        "promotions",
        help="Ventanas de promocion champion/challenger de estrategias (T1.3).",
    )
    promotions.add_argument("--evaluate", action="store_true", help="Evalua las ventanas abiertas ahora.")
    promotions.add_argument("--limit", type=int, default=100, help="Maximo de ventanas a listar.")
    promotions.add_argument("--json", action="store_true", help="Devuelve las ventanas en JSON.")
    promotions.set_defaults(func=command_promotions)

    llm_usage = subparsers.add_parser(
        "llm-usage",
        help="Uso/coste de LLM. Con --by-role agrega por rol (fast/decision/deep).",
    )
    llm_usage.add_argument("--by-role", dest="by_role", action="store_true", help="Agrega el uso por rol.")
    llm_usage.add_argument("--limit", type=int, default=1000, help="Numero de registros recientes a considerar.")
    llm_usage.add_argument("--json", action="store_true", help="Devuelve el uso en JSON.")
    llm_usage.set_defaults(func=command_llm_usage)

    performance = subparsers.add_parser(
        "performance",
        help="Serie diaria de rendimiento del sistema (equity, alpha vs SPY, iq_score).",
    )
    performance.add_argument("--days", type=int, default=30, help="Numero de dias a mostrar. Por defecto 30.")
    performance.add_argument("--json", action="store_true", help="Devuelve la serie en JSON.")
    performance.set_defaults(func=command_performance)

    iq_score = subparsers.add_parser(
        "iq-score",
        help="Metrica unica de progreso: score compuesto 0-100.",
    )
    iq_score.add_argument("--window", type=int, default=20, help="Ventana en sesiones. Por defecto 20.")
    iq_score.add_argument("--json", action="store_true", help="Devuelve el score en JSON.")
    iq_score.set_defaults(func=command_iq_score)

    kernel_unlock_live = subparsers.add_parser(
        "kernel-unlock-live",
        help="Desbloqueo manual de live (T4.3): exige .env + confirmacion + re-sello.",
    )
    kernel_unlock_live.add_argument("--yes", action="store_true", help="Omite la confirmacion interactiva (uso avanzado).")
    kernel_unlock_live.set_defaults(func=command_kernel_unlock_live)

    kernel_seal = subparsers.add_parser(
        "kernel-seal",
        help="Regenera el manifest de integridad del kernel (uso manual).",
    )
    kernel_seal.add_argument("--json", action="store_true", help="Devuelve el resultado en JSON.")
    kernel_seal.set_defaults(func=command_kernel_seal)

    kernel_status = subparsers.add_parser(
        "kernel-status",
        help="Verifica la integridad del kernel contra el manifest sellado.",
    )
    kernel_status.add_argument("--json", action="store_true", help="Devuelve el estado en JSON.")
    kernel_status.set_defaults(func=command_kernel_status)

    operational_health = subparsers.add_parser(
        "operational-health",
        help="Combina salud de jobs, reportes recientes y degradacion por setup.",
    )
    operational_health.add_argument("--json", action="store_true", help="Devuelve el informe en JSON.")
    operational_health.set_defaults(func=command_operational_health)

    operational_responses = subparsers.add_parser(
        "operational-responses",
        help="Deriva respuestas operativas conservadoras a partir de la salud reciente.",
    )
    operational_responses.add_argument("--json", action="store_true", help="Devuelve el informe en JSON.")
    operational_responses.set_defaults(func=command_operational_responses)

    production_health = subparsers.add_parser(
        "production-health",
        help="Consolida salud operativa, scheduler y mejora continua en una sola vista.",
    )
    production_health.add_argument("--json", action="store_true", help="Devuelve el informe en JSON.")
    production_health.set_defaults(func=command_production_health)

    continuous_improvement = subparsers.add_parser(
        "continuous-improvement",
        help="Ejecuta un ciclo manual de mejora continua en dry-run y con LLM externo configurable.",
    )
    continuous_improvement.add_argument("--mode", default="manual", choices=["manual", "scheduled", "api"])
    continuous_improvement.add_argument("--dedupe-key", help="Clave opcional para no duplicar ciclos.")
    continuous_improvement.add_argument("--force", action="store_true", help="Ignora dedupe-key si ya existe.")
    continuous_improvement.add_argument("--json", action="store_true", help="Devuelve el ciclo completo en JSON.")
    continuous_improvement.set_defaults(func=command_continuous_improvement)

    continuous_improvement_api = subparsers.add_parser(
        "continuous-improvement-api",
        help="Sirve endpoints HTTP /api/continuous-improvement/*.",
    )
    continuous_improvement_api.add_argument("--host", default="127.0.0.1")
    continuous_improvement_api.add_argument("--port", type=int, default=8765)
    continuous_improvement_api.set_defaults(func=command_continuous_improvement_api)

    continuous_improvement_lab = subparsers.add_parser(
        "continuous-improvement-lab",
        help="Servicio residente y utilidades del laboratorio multiagente de mejora continua.",
    )
    ci_lab_subparsers = continuous_improvement_lab.add_subparsers(dest="lab_command", required=True)

    ci_lab_start = ci_lab_subparsers.add_parser("start", help="Arranca el runtime residente del laboratorio.")
    ci_lab_start.add_argument("--max-cycles", type=int, help="Numero maximo de ticks antes de salir.")
    ci_lab_start.set_defaults(func=command_continuous_improvement_lab)

    ci_lab_status = ci_lab_subparsers.add_parser("status", help="Muestra runtime, eventos, tareas e hipotesis.")
    ci_lab_status.add_argument("--limit", type=int, default=50)
    ci_lab_status.set_defaults(func=command_continuous_improvement_lab)

    ci_lab_run_once = ci_lab_subparsers.add_parser("run-once", help="Ejecuta un tick completo del laboratorio.")
    ci_lab_run_once.add_argument("--json", action="store_true", help="Devuelve el resultado completo en JSON.")
    ci_lab_run_once.set_defaults(func=command_continuous_improvement_lab)

    ci_lab_enqueue = ci_lab_subparsers.add_parser("enqueue", help="Encola un evento manual para el laboratorio.")
    ci_lab_enqueue.add_argument("--event-type", required=True)
    ci_lab_enqueue.add_argument("--domain", default="software-improvement")
    ci_lab_enqueue.add_argument("--payload", help="JSON compacto con el payload del evento.")
    ci_lab_enqueue.add_argument("--force-unique", action="store_true")
    ci_lab_enqueue.set_defaults(func=command_continuous_improvement_lab)

    ci_lab_agents = ci_lab_subparsers.add_parser("agents", help="Lista agentes y capacidades del laboratorio.")
    ci_lab_agents.set_defaults(func=command_continuous_improvement_lab)

    ci_lab_applied = ci_lab_subparsers.add_parser("applied-changes", help="Lista cambios autonomos aplicados o bloqueados.")
    ci_lab_applied.add_argument("--status", action="append", help="Filtra por estado; se puede repetir.")
    ci_lab_applied.add_argument("--limit", type=int, default=50)
    ci_lab_applied.set_defaults(func=command_continuous_improvement_lab)

    ci_lab_digest = ci_lab_subparsers.add_parser("digest", help="Resume el estado diario del laboratorio en modo solo lectura.")
    ci_lab_digest.add_argument("--days", type=int, default=1)
    ci_lab_digest.add_argument("--out", help="Ruta markdown opcional para escribir el digest.")
    ci_lab_digest.add_argument("--json", action="store_true", help="Devuelve JSON.")
    ci_lab_digest.set_defaults(func=command_continuous_improvement_lab)

    ci_lab_rollback = ci_lab_subparsers.add_parser("rollback", help="Marca rollback de un cambio aplicado.")
    ci_lab_rollback.add_argument("applied_change_id")
    ci_lab_rollback.set_defaults(func=command_continuous_improvement_lab)

    ci_lab_autonomy = ci_lab_subparsers.add_parser("autonomy-status", help="Muestra gates de autonomia de codigo.")
    ci_lab_autonomy.set_defaults(func=command_continuous_improvement_lab)

    ci_lab_phase1 = ci_lab_subparsers.add_parser("phase1-status", help="Resume experimentos y cola READY_TO_APPLY.")
    ci_lab_phase1.add_argument("--limit", type=int, default=20)
    ci_lab_phase1.set_defaults(func=command_continuous_improvement_lab)

    ci_lab_build = ci_lab_subparsers.add_parser("build-strategy", help="Construye una estrategia desde una spec (T1.4).")
    ci_lab_build.add_argument("--spec", help="Especificacion en JSON (string).")
    ci_lab_build.set_defaults(func=command_continuous_improvement_lab)

    ci_lab_dynamic = ci_lab_subparsers.add_parser("dynamic-agents", help="Lista o puntua agentes dinamicos (T2.2).")
    ci_lab_dynamic.add_argument("--score", action="store_true", help="Puntua y retira agentes inutiles.")
    ci_lab_dynamic.add_argument("--limit", type=int, default=100)
    ci_lab_dynamic.set_defaults(func=command_continuous_improvement_lab)

    ci_lab_gen_diff = ci_lab_subparsers.add_parser(
        "gen-diff",
        help="Genera por LLM un diff revisable para una propuesta CODE_CHANGE y lo valida en sandbox.",
    )
    ci_lab_gen_diff.add_argument("--proposal", help="ID de la propuesta CODE_CHANGE en READY_TO_APPLY.")
    ci_lab_gen_diff.add_argument("--demo", action="store_true", help="Crea una propuesta demo de bajo riesgo y genera su diff.")
    ci_lab_gen_diff.add_argument("--json", action="store_true", help="Devuelve el resultado completo en JSON.")
    ci_lab_gen_diff.set_defaults(func=command_continuous_improvement_lab)

    ci_lab_review = ci_lab_subparsers.add_parser(
        "review",
        help="Lista o muestra diffs validados listos para revision humana.",
    )
    ci_lab_review.add_argument("--proposal", help="ID de propuesta concreta.")
    ci_lab_review.add_argument("--limit", type=int, default=20)
    ci_lab_review.add_argument("--json", action="store_true", help="Devuelve la revision en JSON.")
    ci_lab_review.set_defaults(func=command_continuous_improvement_lab)

    ci_lab_approve = ci_lab_subparsers.add_parser(
        "approve",
        help="Aprobacion humana: aplica un diff validado, corre suite completa y crea commit reversible.",
    )
    ci_lab_approve.add_argument("--proposal", required=True, help="ID de propuesta con artefacto code_diff_preview valido.")
    ci_lab_approve.add_argument("--actor", default="cli", help="Operador que aprueba el cambio.")
    ci_lab_approve.add_argument("--json", action="store_true", help="Devuelve el resultado en JSON.")
    ci_lab_approve.set_defaults(func=command_continuous_improvement_lab)

    learning_postmortem = subparsers.add_parser(
        "learning-postmortem",
        help="Reconstruye cohortes de senales, explicaciones y fallos contrafactuales.",
    )
    learning_postmortem.add_argument(
        "--from",
        dest="start",
        default=DEFAULT_HISTORY_START_DATE,
        help=f"Fecha inicial YYYY-MM-DD. Por defecto {DEFAULT_HISTORY_START_DATE}.",
    )
    learning_postmortem.add_argument("--to", dest="end", help="Fecha final YYYY-MM-DD.")
    learning_postmortem.add_argument("--full", action="store_true", help="Incluye todas las filas reconstruidas.")
    learning_postmortem.add_argument("--json", action="store_true", help="Devuelve el informe en JSON.")
    learning_postmortem.set_defaults(func=command_learning_postmortem)

    missed_opportunities = subparsers.add_parser(
        "missed-opportunities",
        help="Lista senales no ejecutadas que luego tuvieron buen resultado forward.",
    )
    missed_opportunities.add_argument(
        "--from",
        dest="start",
        default=DEFAULT_HISTORY_START_DATE,
        help=f"Fecha inicial YYYY-MM-DD. Por defecto {DEFAULT_HISTORY_START_DATE}.",
    )
    missed_opportunities.add_argument("--to", dest="end", help="Fecha final YYYY-MM-DD.")
    missed_opportunities.add_argument("--top", type=int, default=20, help="Numero maximo de ejemplos por categoria.")
    missed_opportunities.add_argument("--full", action="store_true", help="Incluye todas las oportunidades detectadas.")
    missed_opportunities.add_argument("--json", action="store_true", help="Devuelve el informe en JSON.")
    missed_opportunities.set_defaults(func=command_missed_opportunities)

    decision_compare = subparsers.add_parser(
        "decision-compare",
        help="Compara la politica actual frente a la propuesta sobre el historico de senales.",
    )
    decision_compare.add_argument(
        "--from",
        dest="start",
        default=DEFAULT_HISTORY_START_DATE,
        help=f"Fecha inicial YYYY-MM-DD. Por defecto {DEFAULT_HISTORY_START_DATE}.",
    )
    decision_compare.add_argument("--to", dest="end", help="Fecha final YYYY-MM-DD.")
    decision_compare.add_argument(
        "--policy",
        choices=["current", "proposed"],
        default="proposed",
        help="Politica a comparar contra la actual.",
    )
    decision_compare.add_argument("--full", action="store_true", help="Incluye filas historicas usadas en la comparacion.")
    decision_compare.add_argument("--json", action="store_true", help="Devuelve el informe en JSON.")
    decision_compare.set_defaults(func=command_decision_compare)

    walk_forward = subparsers.add_parser(
        "walk-forward-validate",
        help="Evalua la politica propuesta con ventanas train/test cronologicas.",
    )
    walk_forward.add_argument(
        "--from",
        dest="start",
        default=DEFAULT_HISTORY_START_DATE,
        help=f"Fecha inicial YYYY-MM-DD. Por defecto {DEFAULT_HISTORY_START_DATE}.",
    )
    walk_forward.add_argument("--to", dest="end", help="Fecha final YYYY-MM-DD.")
    walk_forward.add_argument(
        "--policy",
        choices=["current", "proposed"],
        default="proposed",
        help="Politica evaluada en las ventanas de test.",
    )
    walk_forward.add_argument("--train-days", type=int, default=5, help="Numero de sesiones en train.")
    walk_forward.add_argument("--test-days", type=int, default=3, help="Numero de sesiones en test.")
    walk_forward.add_argument("--full", action="store_true", help="Incluye las filas historicas de soporte.")
    walk_forward.add_argument("--json", action="store_true", help="Devuelve el informe en JSON.")
    walk_forward.set_defaults(func=command_walk_forward_validate)

    session_retrospective = subparsers.add_parser(
        "session-retrospective",
        help="Resume por sesion cerrada que habria pasado con la politica nueva.",
    )
    session_retrospective.add_argument("--from", dest="start", help="Fecha inicial YYYY-MM-DD.")
    session_retrospective.add_argument("--to", dest="end", help="Fecha final YYYY-MM-DD.")
    session_retrospective.add_argument(
        "--sessions",
        type=int,
        default=DEFAULT_RETROSPECTIVE_SESSIONS,
        help=f"Numero de sesiones cerradas si no se pasa --from. Por defecto {DEFAULT_RETROSPECTIVE_SESSIONS}.",
    )
    session_retrospective.add_argument(
        "--policy",
        choices=["current", "proposed"],
        default="proposed",
        help="Politica evaluada para la retrospectiva.",
    )
    session_retrospective.add_argument("--full", action="store_true", help="Incluye filas historicas de soporte.")
    session_retrospective.add_argument("--json", action="store_true", help="Devuelve el informe en JSON.")
    session_retrospective.set_defaults(func=command_session_retrospective)

    selector_replay = subparsers.add_parser(
        "selector-replay",
        help="Rejuega el selector actual sobre reportes cerrados guardados y resume que tickers entrarian.",
    )
    selector_replay.add_argument("--from", dest="start", help="Fecha inicial YYYY-MM-DD.")
    selector_replay.add_argument("--to", dest="end", help="Fecha final YYYY-MM-DD.")
    selector_replay.add_argument("--limit", type=int, default=20, help="Numero maximo de seleccionados por sesion.")
    selector_replay.add_argument(
        "--symbols",
        default="DDOG,QCOM,MU,SNDK,CSCO,HPE,DELL,INTC,STX",
        help="Lista CSV de tickers a seguir dentro del replay.",
    )
    selector_replay.add_argument("--full", action="store_true", help="Incluye todas las sesiones y filas seleccionadas.")
    selector_replay.add_argument("--json", action="store_true", help="Devuelve el informe en JSON.")
    selector_replay.set_defaults(func=command_selector_replay)

    winner_coverage = subparsers.add_parser(
        "winner-coverage-report",
        help="Resume si el selector actual captura las mayores ganadoras historicas en fechas con reportes conservados.",
    )
    winner_coverage.add_argument("--from", dest="start", help="Fecha inicial YYYY-MM-DD.")
    winner_coverage.add_argument("--to", dest="end", help="Fecha final YYYY-MM-DD.")
    winner_coverage.add_argument("--top", type=int, default=15, help="Numero de ganadoras unicas a revisar.")
    winner_coverage.add_argument("--full", action="store_true", help="Incluye ejemplos de sesiones seleccionadas.")
    winner_coverage.add_argument("--json", action="store_true", help="Devuelve el informe en JSON.")
    winner_coverage.set_defaults(func=command_winner_coverage_report)

    fallback_blockers = subparsers.add_parser(
        "fallback-blocker-report",
        help="Resume por que motivos el fallback determinista deja fuera seleccionados y como rindieron a 5d.",
    )
    fallback_blockers.add_argument("--from", dest="start", help="Fecha inicial YYYY-MM-DD.")
    fallback_blockers.add_argument("--to", dest="end", help="Fecha final YYYY-MM-DD.")
    fallback_blockers.add_argument("--full", action="store_true", help="Incluye todas las filas bloqueadas.")
    fallback_blockers.add_argument("--json", action="store_true", help="Devuelve el informe en JSON.")
    fallback_blockers.set_defaults(func=command_fallback_blocker_report)

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

    live_readiness = subparsers.add_parser(
        "live-readiness",
        help="Checklist previo a live trading: seguridad, datos, aprendizaje, trazabilidad y gates.",
    )
    live_readiness.add_argument(
        "--from",
        dest="start",
        default=DEFAULT_HISTORY_START_DATE,
        help=f"Fecha inicial para auditar trazabilidad. Por defecto {DEFAULT_HISTORY_START_DATE}.",
    )
    live_readiness.add_argument("--json", action="store_true", help="Devuelve el informe en JSON.")
    live_readiness.set_defaults(func=command_live_readiness)

    market_data_quality = subparsers.add_parser(
        "market-data-quality",
        help="Audita cobertura, simbolos faltantes y anomalias OHLCV del universo configurado.",
    )
    market_data_quality.add_argument("--universe", help="Universo a validar. Por defecto CLOSED_MARKET_STUDY_UNIVERSE.")
    market_data_quality.add_argument("--max-symbols", type=int, default=0, help="Limite de simbolos a validar.")
    market_data_quality.add_argument("--from", dest="start", help="Fecha inicial YYYY-MM-DD. Por defecto 30 dias atras.")
    market_data_quality.add_argument("--to", dest="end", help="Fecha final YYYY-MM-DD. Por defecto manana UTC.")
    market_data_quality.add_argument("--json", action="store_true", help="Devuelve el informe en JSON.")
    market_data_quality.set_defaults(func=command_market_data_quality)

    market_data_reconciliation = subparsers.add_parser(
        "market-data-reconciliation",
        help="Compara OHLCV entre proveedor configurado y proveedor alternativo cuando existe.",
    )
    market_data_reconciliation.add_argument("--symbols", help="Tickers separados por coma. Por defecto usa el universo base.")
    market_data_reconciliation.add_argument("--from", dest="start", help="Fecha inicial YYYY-MM-DD. Por defecto 10 dias atras.")
    market_data_reconciliation.add_argument("--to", dest="end", help="Fecha final YYYY-MM-DD. Por defecto manana UTC.")
    market_data_reconciliation.add_argument(
        "--tolerance-pct",
        type=float,
        default=0.01,
        help="Tolerancia relativa para diferencias de cierre. Por defecto 0.01.",
    )
    market_data_reconciliation.add_argument("--json", action="store_true", help="Devuelve el informe en JSON.")
    market_data_reconciliation.set_defaults(func=command_market_data_reconciliation)

    strategy_registry = subparsers.add_parser(
        "strategy-registry",
        help="Muestra estrategias/reglas champion-challenger derivadas de propuestas de mejora continua.",
    )
    strategy_registry.add_argument("--limit", type=int, default=100, help="Maximo de propuestas/validaciones a leer.")
    strategy_registry.add_argument("--active-only", action="store_true", help="Solo estados champion/challenger/shadow/micro.")
    strategy_registry.add_argument("--list-registry", dest="list_registry", action="store_true", help="Lista las estrategias plugables descubiertas (T1.2).")
    strategy_registry.add_argument("--activate", metavar="NAME", help="Marca ACTIVE una estrategia plugable.")
    strategy_registry.add_argument("--shadow", metavar="NAME", help="Marca SHADOW una estrategia plugable.")
    strategy_registry.add_argument("--retire", metavar="NAME", help="Marca RETIRED una estrategia plugable.")
    strategy_registry.add_argument("--json", action="store_true", help="Devuelve el registro en JSON.")
    strategy_registry.set_defaults(func=command_strategy_registry)

    weekly_review = subparsers.add_parser(
        "weekly-review",
        help="Consolida rendimiento, gates, bloqueos, benchmark y readiness de la ultima ventana semanal.",
    )
    weekly_review.add_argument(
        "--from",
        dest="start",
        default=DEFAULT_HISTORY_START_DATE,
        help=f"Fecha inicial YYYY-MM-DD. Por defecto {DEFAULT_HISTORY_START_DATE}.",
    )
    weekly_review.add_argument("--to", dest="end", help="Fecha final YYYY-MM-DD.")
    weekly_review.add_argument("--json", action="store_true", help="Devuelve el informe en JSON.")
    weekly_review.set_defaults(func=command_weekly_review)

    selection_bandwidth_review = subparsers.add_parser(
        "selection-bandwidth-review",
        help="Compara en shadow el ancho actual de seleccion frente a un ancho mayor sin activarlo en trading.",
    )
    selection_bandwidth_review.add_argument(
        "--base-limit",
        type=int,
        default=8,
        help="Numero actual de candidatos seleccionados para el LLM. Por defecto 8.",
    )
    selection_bandwidth_review.add_argument(
        "--shadow-limit",
        type=int,
        default=12,
        help="Numero shadow de candidatos a comparar. Por defecto 12.",
    )
    selection_bandwidth_review.add_argument("--json", action="store_true", help="Devuelve el informe en JSON.")
    selection_bandwidth_review.set_defaults(func=command_selection_bandwidth_review)

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
    backtest.add_argument(
        "--setup-name",
        choices=[
            "trend_volume",
            "orderly_breakout",
            "event_momentum",
            "momentum_confirmation",
            "momentum_shakeout_hold",
            "range_expansion_breakout",
            "baseline_trend",
        ],
        help="Filtra el backtest a un setup concreto.",
    )
    backtest.add_argument("--json", action="store_true", help="Devuelve el informe completo en JSON.")
    backtest.set_defaults(func=command_backtest)

    backtest_baseline = subparsers.add_parser(
        "backtest-baseline",
        help="Ejecuta un baseline reproducible por setup principal sobre un simbolo.",
    )
    backtest_baseline.add_argument("--symbol", required=True, help="Ticker a simular, por ejemplo AAPL.")
    backtest_baseline.add_argument("--from", dest="start", required=True, help="Fecha inicial YYYY-MM-DD.")
    backtest_baseline.add_argument("--to", dest="end", help="Fecha final YYYY-MM-DD.")
    backtest_baseline.add_argument("--min-score", type=int, default=7, help="Score tecnico minimo.")
    backtest_baseline.add_argument(
        "--setup-quality",
        default="strong",
        help="Calidad requerida del setup tecnico. Por defecto strong.",
    )
    backtest_baseline.add_argument(
        "--max-holding-days",
        type=int,
        default=10,
        help="Time stop maximo en sesiones.",
    )
    backtest_baseline.add_argument("--json", action="store_true", help="Devuelve el informe consolidado en JSON.")
    backtest_baseline.set_defaults(func=command_backtest_baseline)

    backup_db = subparsers.add_parser(
        "backup-db",
        help="Crea una copia restaurable de la base SQLite y guarda instrucciones de restauracion.",
    )
    backup_db.set_defaults(func=command_backup_db)

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
        help="Limite de simbolos. Por defecto usa PRE_EARNINGS_MAX_SYMBOLS o CLOSED_MARKET_STUDY_MAX_SYMBOLS.",
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

    opportunity_snapshot = subparsers.add_parser(
        "opportunity-snapshot",
        help="Genera y guarda un snapshot historico de oportunidades para una hora concreta.",
    )
    opportunity_snapshot.add_argument(
        "--slot",
        required=True,
        help="Hora local del snapshot en formato HH:MM, por ejemplo 16:00.",
    )
    opportunity_snapshot.add_argument("--quiet", action="store_true", help="No imprime eventos en vivo.")
    opportunity_snapshot.add_argument(
        "--force",
        action="store_true",
        help="Regenera el snapshot aunque ya exista para esa fecha y hora.",
    )
    opportunity_snapshot.set_defaults(func=command_opportunity_snapshot)

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

    pre_earnings = subparsers.add_parser(
        "pre-earnings",
        help="Apartado informativo: acciones con earnings en el proximo cierre AMC, hipotesis y resultado si existe.",
    )
    pre_earnings.add_argument(
        "--universe",
        help=(
            "Universo a revisar. Por defecto usa CLOSED_MARKET_STUDY_UNIVERSE. "
            "Ejemplos: sp500_top300, sp500, default, AAPL,MSFT,NVDA."
        ),
    )
    pre_earnings.add_argument(
        "--max-symbols",
        type=int,
        default=0,
        help="Limite de simbolos. Por defecto usa CLOSED_MARKET_STUDY_MAX_SYMBOLS.",
    )
    pre_earnings.add_argument(
        "--days",
        type=int,
        default=0,
        help="Numero de cierres de mercado AMC a mostrar. Por defecto PRE_EARNINGS_DAYS.",
    )
    pre_earnings.add_argument("--json", action="store_true", help="Devuelve el informe completo en JSON.")
    pre_earnings.set_defaults(func=command_pre_earnings)

    pre_earnings_backtest = subparsers.add_parser(
        "pre-earnings-backtest",
        help="Event-study historico informativo de hipotesis pre-earnings AMC; no compra.",
    )
    pre_earnings_backtest.add_argument("--from", dest="start", required=True, help="Fecha inicial YYYY-MM-DD.")
    pre_earnings_backtest.add_argument("--to", dest="end", help="Fecha final YYYY-MM-DD. Por defecto hoy.")
    pre_earnings_backtest.add_argument(
        "--universe",
        help=(
            "Universo a revisar. Por defecto usa PRE_EARNINGS_UNIVERSE o CLOSED_MARKET_STUDY_UNIVERSE. "
            "Ejemplos: sp500_top300, default, AAPL,MSFT,NVDA."
        ),
    )
    pre_earnings_backtest.add_argument(
        "--max-symbols",
        type=int,
        default=0,
        help="Limite de simbolos. Por defecto PRE_EARNINGS_MAX_SYMBOLS o CLOSED_MARKET_STUDY_MAX_SYMBOLS.",
    )
    pre_earnings_backtest.add_argument("--json", action="store_true", help="Devuelve el informe completo en JSON.")
    pre_earnings_backtest.set_defaults(func=command_pre_earnings_backtest)

    pre_earnings_score = subparsers.add_parser(
        "pre-earnings-score-study",
        help="Estudia predicciones pre-earnings guardadas y calcula score V2 por dia y final.",
    )
    pre_earnings_score.add_argument(
        "--since",
        help="Fecha minima de prediccion YYYY-MM-DD. Por defecto usa todo el historico guardado.",
    )
    pre_earnings_score.add_argument(
        "--limit",
        type=int,
        default=10000,
        help="Maximo de predicciones persistidas a analizar.",
    )
    pre_earnings_score.add_argument("--json", action="store_true", help="Devuelve el informe completo en JSON.")
    pre_earnings_score.set_defaults(func=command_pre_earnings_score_study)

    pre_earnings_learning = subparsers.add_parser(
        "pre-earnings-learning-digest",
        help="Resume aprendizaje historico pre-earnings, vetos por riesgo y cobertura de estimaciones.",
    )
    pre_earnings_learning.add_argument(
        "--since",
        help="Fecha minima de prediccion YYYY-MM-DD. Por defecto usa todo el historico guardado.",
    )
    pre_earnings_learning.add_argument(
        "--limit",
        type=int,
        default=10000,
        help="Maximo de predicciones persistidas a analizar.",
    )
    pre_earnings_learning.add_argument("--json", action="store_true", help="Devuelve el informe completo en JSON.")
    pre_earnings_learning.set_defaults(func=command_pre_earnings_learning_digest)

    pre_earnings_backfill = subparsers.add_parser(
        "pre-earnings-backfill-estimates",
        help="Enriquece solo predicciones pending/futuras con estimaciones de analistas sin fuga temporal.",
    )
    pre_earnings_backfill.add_argument(
        "--since",
        help="Fecha minima para refrescar el digest posterior. Por defecto usa todo el historico del digest.",
    )
    pre_earnings_backfill.add_argument(
        "--limit",
        type=int,
        default=2000,
        help="Maximo de predicciones persistidas a inspeccionar.",
    )
    pre_earnings_backfill.add_argument("--json", action="store_true", help="Devuelve el informe completo en JSON.")
    pre_earnings_backfill.set_defaults(func=command_pre_earnings_backfill_estimates)

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

    telegram_radar = subparsers.add_parser(
        "telegram-radar",
        help="Radar research-only de posts publicos de Telegram; no opera ni cambia trading.",
    )
    telegram_subparsers = telegram_radar.add_subparsers(dest="telegram_command", required=True)
    telegram_ingest = telegram_subparsers.add_parser("ingest", help="Ingiere y extrae posts nuevos del canal publico.")
    telegram_ingest.add_argument("--backfill", type=int, default=1, help="Paginas a retroceder con ?before=<id>.")
    telegram_ingest.add_argument("--force", action="store_true", help="Ignora cache HTML local.")
    telegram_ingest.add_argument("--skip-llm", action="store_true", help="Usa solo heuristica local para extraccion.")
    telegram_ingest.add_argument("--json", action="store_true", help="Devuelve JSON.")
    telegram_ingest.set_defaults(func=command_telegram_radar)
    telegram_list = telegram_subparsers.add_parser("list", help="Lista posts guardados y extracciones.")
    telegram_list.add_argument("--days", type=int, default=7, help="Ventana reciente a listar.")
    telegram_list.add_argument("--only-opportunities", action="store_true", help="Muestra solo oportunidades extraidas.")
    telegram_list.add_argument("--json", action="store_true", help="Devuelve JSON.")
    telegram_list.set_defaults(func=command_telegram_radar)
    telegram_report = telegram_subparsers.add_parser("report", help="Genera marcador honesto y veredictos internos.")
    telegram_report.add_argument("--days", type=int, default=7, help="Ventana reciente para oportunidades/veredictos.")
    telegram_report.add_argument("--out", help="Ruta de salida markdown UTF-8. Si se omite, imprime por stdout.")
    telegram_report.add_argument("--json", action="store_true", help="Devuelve JSON con markdown incluido.")
    telegram_report.set_defaults(func=command_telegram_radar)

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
        choices=[
            "portfolio",
            "market",
            "closed-study",
            "daily",
            "post-market-review",
            "broker-reconciliation",
            "pre-earnings",
            "opportunity-snapshot",
            "continuous-improvement",
            "overnight-learning",
        ],
    )
    job_once.add_argument("--slot", default="16:00", help="Slot HH:MM usado por opportunity-snapshot.")
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
