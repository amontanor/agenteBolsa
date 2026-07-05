"""Runtime event reporting for visible agent activity."""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .models import AgentEvent
from .storage import Store

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentPhase:
    agent: str
    action: str
    detail: str


class EventReporter:
    """Writes each agent event to console, JSONL files and SQLite."""

    def __init__(self, store: Store, verbose: bool = True) -> None:
        self.store = store
        self.verbose = verbose

    def emit(
        self,
        agent: str,
        event_type: str,
        cycle_id: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        record_payload = {"message": message, **(payload or {})}
        event = AgentEvent(
            agent=agent,
            event_type=event_type,
            cycle_id=cycle_id,
            payload=record_payload,
        )
        self.store.record_agent_event(event)
        if self.verbose and should_display_event(event_type):
            try:
                print(format_live_event(agent, event_type, cycle_id, message), flush=True)
            except (OSError, ValueError) as exc:
                LOGGER.debug("Live event print skipped because stdout is unavailable: %s", exc)

    def emit_json(self, payload: dict[str, Any]) -> None:
        try:
            print(json.dumps(payload, indent=2, ensure_ascii=True, default=str), flush=True)
        except (OSError, ValueError) as exc:
            LOGGER.debug("JSON event print skipped because stdout is unavailable: %s", exc)


def _decode_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload_json")
    if payload:
        try:
            decoded = json.loads(payload)
            if isinstance(decoded, dict):
                return decoded
        except json.JSONDecodeError:
            return {"message": str(payload)}
    return {}


def _event_status(event_type: str) -> str:
    if event_type in {"cycle_started", "scheduler_started"}:
        return "START"
    if event_type in {"cycle_completed", "crew_completed"} or event_type.endswith("_completed"):
        return "OK"
    if event_type.endswith("_started"):
        return "START"
    if event_type.endswith("_skipped") or event_type == "crew_skipped":
        return "SKIP"
    if event_type.endswith("_failed") or event_type == "crew_failed":
        return "FAIL"
    if event_type.endswith("_saved"):
        return "SAVE"
    if event_type.endswith("_planned"):
        return "PLAN"
    if event_type.endswith("_check"):
        return "CHECK"
    if event_type == "market_closed_risk_check":
        return "CLOSED"
    if event_type == "intraday_risk_check":
        return "RISK"
    return "INFO"


IMPORTANT_EVENT_TYPES = {
    "cycle_started",
    "cycle_completed",
    "crew_started",
    "crew_completed",
    "crew_failed",
    "crew_skipped",
    "market_snapshot_completed",
    "market_snapshot_failed",
    "backtest_planned",
    "decision_saved",
    "portfolio_watch_started",
    "intraday_risk_check",
    "portfolio_watch_sleeping",
    "closed_market_study_started",
    "closed_market_study_completed",
    "news_sentiment_started",
    "news_sentiment_completed",
    "web_research_started",
    "web_research_completed",
    "closed_market_crew_started",
    "closed_market_crew_failed",
    "scheduled_market_cycle_check",
    "scheduled_market_cycle_skipped",
    "daily_study_started",
    "daily_study_skipped",
    "post_market_review_started",
    "post_market_review_completed",
    "intraday_technical_scan_started",
    "intraday_technical_scan_completed",
    "intraday_breakout_scan_completed",
    "intraday_candidate_universe_selected",
    "intraday_news_sentiment_started",
    "intraday_news_sentiment_completed",
    "open_position_news_guard_started",
    "open_position_news_guard_completed",
    "open_position_news_guard_blocked",
    "trade_execution_summary",
    "paper_auto_trade_started",
    "paper_auto_trade_completed",
    "paper_auto_trade_blocked",
    "paper_auto_trade_failed",
}


def should_display_event(event_type: str) -> bool:
    return (
        event_type in IMPORTANT_EVENT_TYPES
        or event_type.endswith("_failed")
        or event_type.endswith("_blocked")
    )


def _event_title(event_type: str) -> str:
    titles = {
        "cycle_started": "Ciclo iniciado",
        "cycle_completed": "Ciclo finalizado",
        "crew_started": "LLM iniciado",
        "crew_completed": "LLM finalizado",
        "crew_failed": "LLM fallido",
        "crew_skipped": "LLM omitido",
        "market_snapshot_completed": "Datos actualizados",
        "market_snapshot_failed": "Datos fallidos",
        "backtest_planned": "Validacion pendiente",
        "decision_saved": "Riesgo",
        "portfolio_watch_started": "Cartera",
        "intraday_risk_check": "Riesgo intradia",
        "portfolio_watch_sleeping": "Mercado cerrado",
        "closed_market_study_started": "Analisis cerrado",
        "closed_market_study_completed": "Candidatos",
        "news_sentiment_started": "Noticias",
        "news_sentiment_completed": "Sentimiento",
        "web_research_started": "Web research",
        "web_research_completed": "Evidencia web",
        "web_research_failed": "Web research fallido",
        "closed_market_crew_started": "Revision LLM",
        "closed_market_crew_failed": "Revision LLM fallida",
        "scheduled_market_cycle_check": "Check mercado",
        "scheduled_market_cycle_skipped": "Ciclo omitido",
        "daily_study_started": "Estudio diario",
        "daily_study_skipped": "Estudio omitido",
        "post_market_review_started": "Revision cierre",
        "post_market_review_completed": "Aprendizaje cierre",
        "intraday_technical_scan_started": "Scan tecnico",
        "intraday_technical_scan_completed": "Candidatos intradia",
        "intraday_breakout_scan_completed": "Rupturas",
        "intraday_breakout_scan_failed": "Rupturas fallidas",
        "intraday_candidate_universe_selected": "Universo LLM",
        "intraday_news_sentiment_started": "Noticias intradia",
        "intraday_news_sentiment_completed": "Sentimiento intradia",
        "open_position_news_guard_started": "Noticias cartera",
        "open_position_news_guard_completed": "Riesgo noticias",
        "open_position_news_guard_blocked": "Noticias omitidas",
        "trade_execution_summary": "Compra/Venta",
        "paper_auto_trade_started": "Auto paper",
        "paper_auto_trade_completed": "Ordenes paper",
        "paper_auto_trade_blocked": "Auto bloqueado",
        "paper_auto_trade_failed": "Auto fallido",
    }
    return titles.get(event_type, event_type.replace("_", " "))


def _run_kind(cycle_id: str) -> str:
    if cycle_id.startswith("watch_"):
        return "WATCH 1m"
    if cycle_id.startswith("mkt_"):
        return "MARKET 15m"
    if cycle_id.startswith("daily_"):
        return "DAILY"
    if cycle_id.startswith("pmr_"):
        return "REVIEW"
    if cycle_id.startswith("closed_"):
        return "CLOSED"
    if cycle_id.startswith("sched_"):
        return "SCHED"
    if cycle_id.startswith("202"):
        return "CYCLE"
    return "RUN"


def _format_time(value: str, local_timezone: str, use_utc: bool = False) -> str:
    if not value:
        return "--:--:--"
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if use_utc:
            return dt.astimezone(timezone.utc).strftime("%H:%M:%S UTC")
        return dt.astimezone(ZoneInfo(local_timezone)).strftime("%H:%M:%S")
    except ValueError:
        return value[:8]


def _short_cycle(cycle_id: str) -> str:
    if cycle_id.startswith("202") and len(cycle_id) >= 15:
        return cycle_id
    if "_" in cycle_id:
        prefix, suffix = cycle_id.split("_", maxsplit=1)
        return f"{prefix}_{suffix[:6]}"
    return cycle_id


def _supports_color() -> bool:
    return sys.stdout.isatty()


def _color(text: str, code: str) -> str:
    if not _supports_color():
        return text
    return f"\033[{code}m{text}\033[0m"


def _color_trade_message(message: str) -> str:
    result = message
    if "compras:" in result:
        before, marker, after = result.partition("compras:")
        if "; ventas:" in after:
            buy_text, separator, rest = after.partition("; ventas:")
            result = before + _color(marker + buy_text, "32") + separator + rest
        else:
            result = before + _color(marker + after, "32")
    if "ventas:" in result:
        before, marker, after = result.partition("ventas:")
        if ". " in after:
            sell_text, separator, rest = after.partition(". ")
            result = before + _color(marker + sell_text, "31") + separator + rest
        else:
            result = before + _color(marker + after, "31")
    return result


def format_live_event(agent: str, event_type: str, cycle_id: str, message: str) -> str:
    status = _event_status(event_type)
    timestamp = datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Madrid")).strftime("%H:%M:%S")
    if event_type in {"trade_execution_summary", "paper_auto_trade_completed"}:
        message = _color_trade_message(message)
    return f"{timestamp} | {_run_kind(cycle_id):<10} | {status:<5} | {_event_title(event_type):<22} | {message}"


def print_raw_tail_line(row: dict[str, Any]) -> None:
    payload = _decode_payload(row)
    message = payload.get("message") or json.dumps(payload, ensure_ascii=True)
    created_at = row.get("created_at", "")
    agent = row.get("agent", "unknown_agent")
    event_type = row.get("event_type", "event")
    cycle_id = row.get("cycle_id") or "-"
    sys.stdout.write(f"{created_at} [{cycle_id}] {agent} {event_type}: {message}\n")
    sys.stdout.flush()


class PrettyLogPrinter:
    def __init__(
        self,
        *,
        local_timezone: str = "Europe/Madrid",
        headers: bool = True,
        use_utc: bool = False,
        all_events: bool = False,
    ) -> None:
        self.local_timezone = local_timezone
        self.headers = headers
        self.use_utc = use_utc
        self.all_events = all_events
        self._last_cycle_id: str | None = None

    def print(self, row: dict[str, Any]) -> None:
        event_type = row.get("event_type", "event")
        if not self.all_events and not should_display_event(event_type):
            return

        cycle_id = row.get("cycle_id") or "-"
        if self.headers and cycle_id != self._last_cycle_id:
            self._print_header(cycle_id)
            self._last_cycle_id = cycle_id

        payload = _decode_payload(row)
        message = payload.get("message") or json.dumps(payload, ensure_ascii=True)
        if event_type in {"trade_execution_summary", "paper_auto_trade_completed"}:
            message = _color_trade_message(str(message))
        status = _event_status(event_type)
        created_at = _format_time(str(row.get("created_at", "")), self.local_timezone, self.use_utc)
        sys.stdout.write(
            f"{created_at:<12} | {status:<6} | {_event_title(event_type):<24} | {message}\n"
        )
        sys.stdout.flush()

    def _print_header(self, cycle_id: str) -> None:
        kind = _run_kind(cycle_id)
        time_label = "hora UTC" if self.use_utc else f"hora {self.local_timezone}"
        sys.stdout.write("\n")
        sys.stdout.write("=" * 96 + "\n")
        sys.stdout.write(f"{kind}  {_short_cycle(cycle_id)}\n")
        sys.stdout.write("-" * 96 + "\n")
        sys.stdout.write(f"{time_label:<12} | {'estado':<6} | {'tarea':<24} | resultado\n")
        sys.stdout.write("-" * 96 + "\n")
        sys.stdout.flush()
