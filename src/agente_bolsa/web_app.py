"""Local Streamlit dashboard for the trading agent."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
try:
    import altair as alt
except ModuleNotFoundError:  # pragma: no cover - import-only test environments may omit dashboard extras.
    alt = None  # type: ignore[assignment]
try:
    import streamlit as st
except ModuleNotFoundError:  # pragma: no cover - import-only test environments may omit dashboard extras.
    class _MissingStreamlit:
        dataframe = None

        def __getattr__(self, name: str):
            raise RuntimeError("Streamlit no esta instalado. Instala las dependencias del dashboard para usar web.")

    st = _MissingStreamlit()  # type: ignore[assignment]

from agente_bolsa import __version__
from agente_bolsa.config import get_settings
from agente_bolsa.continuous_improvement.runtime import ContinuousImprovementLabRuntime
from agente_bolsa.eventing import EventReporter
from agente_bolsa.market_calendar import MarketCalendar
from agente_bolsa.models import PortfolioSnapshot, TradeRecommendation, new_id
from agente_bolsa.scheduler import _run_pre_earnings_trade_operation, scheduler_status
from agente_bolsa.storage import Store
from agente_bolsa.tools.adaptive_tuning import adaptive_status, update_adaptive_config
from agente_bolsa.tools.backtest import build_symbol_backtest
from agente_bolsa.tools.broker import BrokerClientFactory
from agente_bolsa.tools.command_catalog import available_command_catalog
from agente_bolsa.tools.daily_learning import build_learning_digest_report, load_daily_learning_context
from agente_bolsa.tools.news_sentiment import fetch_symbol_news
from agente_bolsa.tools.operational_learning import build_operational_learning_review
from agente_bolsa.tools.opportunities import build_opportunity_snapshot, opportunity_assessment, opportunity_entry_risk
from agente_bolsa.tools.portfolio_insights import (
    latest_analyzed_news as build_latest_analyzed_news,
    position_chart_start_date as build_position_chart_start_date,
    position_entry_date as build_position_entry_date,
    position_evolution_summary as build_position_evolution_summary,
    position_first_buy_time as build_position_first_buy_time,
    position_price_series as build_position_price_series,
    single_symbol_price_frame as build_single_symbol_price_frame,
)
from agente_bolsa.tools.pre_earnings import (
    backfill_pending_pre_earnings_estimates,
    build_pre_earnings_event_study,
    build_pre_earnings_estimation_history,
    build_pre_earnings_learning_digest,
    build_pre_earnings_report,
    build_pre_earnings_resolved_history,
    build_pre_earnings_score_study,
    build_pre_earnings_tracking_status,
    enrich_report_with_local_analyst_revisions,
    enrich_report_with_pre_earnings_score_v2,
    record_pre_earnings_analyst_snapshots,
    record_pre_earnings_predictions,
    target_after_close_session,
    update_pre_earnings_outcomes,
)
from agente_bolsa.tools.retention import cleanup_runtime_data
from agente_bolsa.tools.signal_learning import build_learning_status, update_signal_outcomes
from agente_bolsa.tools.trade_decision import build_buy_order_plans, load_latest_technical_candidates
from agente_bolsa.tools.trade_history import build_trade_history
from agente_bolsa.tools.universe import resolve_study_universe


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_START_DATE = "2026-04-01"
PORTFOLIO_CHART_START_DATE = "2026-04-28"
PRE_EARNINGS_CONFIDENCE_THRESHOLD = 0.80


def _settings():
    return get_settings()


def _store() -> Store:
    settings = _settings()
    cleanup_runtime_data(settings)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def _safe_cache_data(**kwargs: Any):
    try:
        return st.cache_data(**kwargs)
    except Exception:
        return lambda func: func


def _streamlit_fallback_notice(key: str, message: str) -> None:
    try:
        notices = st.session_state.setdefault("_runtime_fallback_notices", set())
        if key in notices:
            return
        notices.add(key)
    except Exception:
        pass
    st.caption(message)


def _render_streamlit_table_fallback(data: Any) -> None:
    try:
        if isinstance(data, pd.Series):
            frame = data.to_frame()
        elif isinstance(data, pd.DataFrame):
            frame = data
        elif hasattr(data, "data") and hasattr(data, "columns"):
            frame = pd.DataFrame(data.data, columns=data.columns)
        else:
            frame = pd.DataFrame(data)
    except Exception:
        st.code(_json(data))
        return
    st.markdown(frame.to_html(index=False, escape=True), unsafe_allow_html=True)


def _install_streamlit_runtime_fallbacks() -> None:
    dataframe = getattr(st, "dataframe", None)
    if callable(dataframe) and not getattr(dataframe, "__name__", "").startswith("_safe_streamlit_"):
        original_dataframe = dataframe

        def _safe_streamlit_dataframe(data: Any = None, *args: Any, **kwargs: Any):
            try:
                return original_dataframe(data, *args, **kwargs)
            except Exception as exc:
                _streamlit_fallback_notice(
                    "dataframe_runtime_fallback",
                    f"Vista degradada: tabla HTML por dependencia opcional no disponible ({type(exc).__name__}).",
                )
                _render_streamlit_table_fallback(data)
                return None

        st.dataframe = _safe_streamlit_dataframe  # type: ignore[assignment]


_install_streamlit_runtime_fallbacks()


def _sidebar_version_label() -> str:
    return f"v{__version__}"


def _render_sidebar_version() -> None:
    st.sidebar.markdown(
        (
            "<div style='text-align: right; color: #4b5563; font-weight: 700; "
            "font-size: 0.82rem; margin-top: 0.9rem; margin-bottom: 0.15rem;'>"
            f"{escape(_sidebar_version_label())}"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _money(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "-"


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "-"


def _pct_signed(value: Any) -> str:
    try:
        amount = float(value) * 100
    except (TypeError, ValueError):
        return "-"
    sign = "+" if amount > 0 else ""
    return f"{sign}{amount:.2f}%"


def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _short(value: Any, length: int = 140) -> str:
    text = str(value or "").strip()
    if len(text) <= length:
        return text
    return f"{text[: length - 1].rstrip()}..."


def _local_dt(value: Any, timezone_name: str | None = None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed.astimezone(ZoneInfo(timezone_name or _settings().local_timezone))


def _local_time(value: Any, timezone_name: str | None = None) -> str:
    parsed = _local_dt(value, timezone_name)
    return parsed.strftime("%H:%M:%S") if parsed else "-"


def _local_datetime(value: Any, timezone_name: str | None = None) -> str:
    parsed = _local_dt(value, timezone_name)
    return parsed.strftime("%Y-%m-%d %H:%M:%S") if parsed else str(value or "-")


def _status_color(ok: bool) -> tuple[str, str, str]:
    return ("#15803d", "#f0fdf4", "#86efac") if ok else ("#b91c1c", "#fef2f2", "#fecaca")


def _tone_color(tone: str) -> tuple[str, str, str]:
    palette = {
        "good": ("#15803d", "#f0fdf4", "#86efac"),
        "bad": ("#b91c1c", "#fef2f2", "#fecaca"),
        "neutral": ("#374151", "#f9fafb", "#d1d5db"),
    }
    return palette.get(tone, palette["neutral"])


def _run_command(args: list[str], timeout: int = 120) -> tuple[int, str]:
    command = [sys.executable, "-m", "agente_bolsa.main", *args]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    output = "\n".join(part for part in [completed.stdout, completed.stderr] if part.strip())
    return completed.returncode, output.strip()


def _pid_file() -> Path:
    return _settings().state_dir / "web_schedule.pid"


def _schedule_log_file() -> Path:
    return _settings().logs_dir / "web_schedule.out.log"


def _web_preferences_file() -> Path:
    return _settings().state_dir / "web_preferences.json"


def _load_web_preferences() -> dict[str, Any]:
    path = _web_preferences_file()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_web_preferences(preferences: dict[str, Any]) -> None:
    path = _web_preferences_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json(preferences), encoding="utf-8")


def _is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _schedule_process_status() -> dict[str, Any]:
    web_pid_path = _pid_file()
    lock_path = _settings().state_dir / "scheduler.lock"
    candidates: list[tuple[str, Path]] = [("web", web_pid_path), ("scheduler", lock_path)]
    stale_paths: list[Path] = []
    for source, path in candidates:
        if not path.exists():
            continue
        try:
            pid = int(path.read_text(encoding="utf-8").strip())
        except ValueError:
            stale_paths.append(path)
            continue
        running = _is_pid_running(pid)
        if running:
            return {"running": True, "pid": pid, "source": source}
        stale_paths.append(path)
    for path in stale_paths:
        path.unlink(missing_ok=True)
    return {"running": False, "pid": None, "source": None}


def _start_schedule() -> dict[str, Any]:
    status = _schedule_process_status()
    if status["running"]:
        return status
    settings = _settings()
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    log_path = _schedule_log_file()
    log_handle = log_path.open("a", encoding="utf-8")
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        [sys.executable, "-m", "agente_bolsa.main", "schedule"],
        cwd=REPO_ROOT,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    _pid_file().write_text(str(process.pid), encoding="utf-8")
    return {"running": True, "pid": process.pid, "log": str(log_path)}


def _stop_schedule() -> dict[str, Any]:
    status = _schedule_process_status()
    pid = status.get("pid")
    if not pid:
        return {"stopped": False, "reason": "No hay proceso schedule lanzado desde la web."}
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False, capture_output=True)
    else:
        os.kill(int(pid), signal.SIGTERM)
    _pid_file().unlink(missing_ok=True)
    return {"stopped": True, "pid": pid}


def _events_dataframe(events: list[dict[str, Any]]) -> pd.DataFrame:
    settings = _settings()
    rows = []
    for event in events:
        payload = {}
        try:
            payload = json.loads(event.get("payload_json") or "{}")
        except json.JSONDecodeError:
            payload = {"raw": event.get("payload_json")}
        rows.append(
            {
                "hora": _local_time(event.get("created_at"), settings.local_timezone),
                "agente": event.get("agent"),
                "estado": event.get("event_type"),
                "tarea": payload.get("task") or payload.get("title") or payload.get("name"),
                "resultado": payload.get("message") or payload.get("result") or payload.get("raw"),
                "cycle_id": event.get("cycle_id"),
            }
        )
    return pd.DataFrame(rows)


def _signal_outcome_status(outcome: dict[str, Any]) -> str:
    if not outcome:
        return "pendiente de actualizar"
    if outcome.get("available") is False:
        reason = outcome.get("reason") or "sin resultado"
        return f"sin datos: {reason}"
    verdict = outcome.get("verdict")
    if verdict and verdict != "pending":
        return str(verdict)
    horizons = [outcome.get("return_5d"), outcome.get("return_10d")]
    if all(value is None for value in horizons):
        return "sin horizonte suficiente"
    return "pendiente"


def _signal_value(value: Any, *, pct: bool = False) -> Any:
    if value is None:
        return "pendiente"
    if pct:
        return _pct(value)
    return value


def _latest_signal_per_symbol(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for item in signals:
        symbol = str(item.get("symbol") or "")
        current = latest.get(symbol)
        if current is None or str(item.get("created_at") or "") > str(current.get("created_at") or ""):
            latest[symbol] = item
    return sorted(
        latest.values(),
        key=lambda item: (str(item.get("signal_date") or ""), str(item.get("created_at") or "")),
        reverse=True,
    )


def _signals_dataframe(signals: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for signal_row in signals:
        features = signal_row.get("features") or {}
        gate = signal_row.get("gate") or {}
        outcome = signal_row.get("outcome") or {}
        chart = features.get("chart_patterns") or {}
        first_hit = outcome.get("first_hit") or {}
        rows.append(
            {
                "fecha": signal_row.get("signal_date"),
                "hora": _local_time(signal_row.get("created_at")),
                "simbolo": signal_row.get("symbol"),
                "fuente": signal_row.get("source"),
                "run": signal_row.get("source_run_id"),
                "decision": signal_row.get("decision"),
                "score": features.get("score"),
                "setup": features.get("setup_quality"),
                "rsi": features.get("rsi_14"),
                "dist_sma20": features.get("distance_sma20"),
                "macd_diff": features.get("macd_diff"),
                "vol_z": features.get("volume_zscore_20"),
                "figuras": chart.get("labels"),
                "estado_resultado": _signal_outcome_status(outcome),
                "ret_5d": _signal_value(outcome.get("return_5d"), pct=True),
                "mfe_10d": _signal_value(outcome.get("mfe_10d"), pct=True),
                "mae_10d": _signal_value(outcome.get("mae_10d"), pct=True),
                "primer_evento": first_hit.get("type") or "pendiente",
                "llm": (gate.get("llm") or {}).get("reason") or "no aplica",
            }
        )
    return pd.DataFrame(rows)


def _latest_learning_digest() -> dict[str, Any]:
    return load_daily_learning_context(_settings().data_dir)


def _learning_compact_summary(digest: dict[str, Any]) -> dict[str, Any]:
    top_setup = ((digest or {}).get("setup_stats_3d", []) or [{}])[0]
    calibration = ((digest or {}).get("confidence_calibration_3d", []) or [])
    best_conf = None
    if calibration:
        best_conf = max(
            calibration,
            key=lambda item: (
                float(item.get("avg_return") or -999),
                float(item.get("win_rate") or -1),
            ),
        )
    worst_accuracy = ((digest or {}).get("prior_accuracy_3d", []) or [{}])[0]
    top_symbol_setup = ((digest or {}).get("symbol_setup_memory_3d", []) or [{}])[0]
    return {
        "top_setup": top_setup if isinstance(top_setup, dict) else {},
        "top_symbol_setup": top_symbol_setup if isinstance(top_symbol_setup, dict) else {},
        "best_confidence_bucket": best_conf if isinstance(best_conf, dict) else {},
        "worst_accuracy": worst_accuracy if isinstance(worst_accuracy, dict) else {},
    }


def _bar_chart(data: list[dict[str, Any]], x: str, y: str, color_field: str | None = None, *, height: int = 220):
    frame = pd.DataFrame(data)
    if frame.empty or x not in frame.columns or y not in frame.columns:
        st.info("Todavia no hay datos suficientes.")
        return
    if alt is None:
        st.dataframe(frame, use_container_width=True)
        return
    chart = alt.Chart(frame).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
        x=alt.X(f"{x}:N", sort="-y", title=""),
        y=alt.Y(f"{y}:Q", title=""),
        tooltip=list(frame.columns),
    )
    if color_field and color_field in frame.columns:
        chart = chart.encode(color=alt.Color(f"{color_field}:N", legend=None))
    st.altair_chart(chart.properties(height=height), use_container_width=True)


def _orders_dataframe(orders: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "fecha": item.get("time"),
                "simbolo": item.get("symbol"),
                "lado": item.get("side"),
                "estado": item.get("status"),
                "notional": item.get("notional"),
                "qty": item.get("qty"),
                "stop_loss": item.get("stop_loss"),
                "take_profit": item.get("take_profit"),
                "cycle_id": item.get("cycle_id"),
            }
            for item in orders
        ]
    )


def _load_json_cell(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}


def _latest_report_json(filename: str) -> dict[str, Any]:
    path = _settings().data_dir / "reports" / filename
    if not path.exists():
        return {"available": False, "path": str(path)}
    try:
        return {"available": True, "path": str(path), "payload": json.loads(path.read_text(encoding="utf-8"))}
    except (OSError, json.JSONDecodeError):
        return {"available": False, "path": str(path)}


def _llm_daily_usage_dataframe(store: Store, *, limit: int = 1000) -> pd.DataFrame:
    settings = _settings()
    totals: dict[str, dict[str, Any]] = {}
    for row in store.latest_llm_usage(limit):
        created_at = _local_dt(row.get("created_at"), settings.local_timezone)
        date_key = created_at.date().isoformat() if created_at else str(row.get("created_at") or "")[:10]
        if not date_key:
            continue
        day = totals.setdefault(
            date_key,
            {
                "fecha": date_key,
                "peticiones": 0,
                "tokens": 0,
                "tokens_prompt": 0,
                "tokens_respuesta": 0,
            },
        )
        day["peticiones"] += int(row.get("request_count") or 0)
        day["tokens"] += int(row.get("total_tokens") or 0)
        day["tokens_prompt"] += int(row.get("prompt_tokens") or 0)
        day["tokens_respuesta"] += int(row.get("completion_tokens") or 0)
    return pd.DataFrame(sorted(totals.values(), key=lambda item: item["fecha"], reverse=True))


def _latest_trade_decision_llm_usage(store: Store, *, limit: int = 200) -> dict[str, Any]:
    for row in store.latest_llm_usage(limit):
        if str(row.get("source") or "").strip().lower() != "trade_decision":
            continue
        payload = _load_json_cell(row.get("payload_json"))
        return {
            "source": row.get("source"),
            "model": row.get("model"),
            "request_count": row.get("request_count"),
            "prompt_tokens": row.get("prompt_tokens"),
            "completion_tokens": row.get("completion_tokens"),
            "total_tokens": row.get("total_tokens"),
            "payload": payload,
            "created_at": row.get("created_at"),
        }
    return {}


def _latest_order_details(limit: int = 50, start_date: str = DEFAULT_START_DATE) -> list[dict[str, Any]]:
    settings = _settings()
    if not settings.database_path.exists():
        return []
    import sqlite3

    with sqlite3.connect(settings.database_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT broker_order_id, plan_id, cycle_id, symbol, side, status, payload_json, created_at
            FROM broker_orders
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    result = []
    for row in rows:
        date_value = str(row["created_at"] or "")[:10]
        if start_date and date_value < start_date:
            continue
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        plan = payload.get("plan", {}) or {}
        plan_payload = plan.get("payload", {}) or {}
        recommendation = plan_payload.get("recommendation", {}) or {}
        result.append(
            {
                "time": row["created_at"],
                "date": date_value,
                "symbol": row["symbol"],
                "side": str(row["side"] or "").lower(),
                "status": row["status"],
                "notional": plan.get("notional"),
                "qty": plan_payload.get("qty"),
                "entry_price": plan_payload.get("entry_price"),
                "stop_loss": plan_payload.get("stop_loss"),
                "take_profit": plan_payload.get("take_profit"),
                "confidence": recommendation.get("confidence"),
                "reason": recommendation.get("reason"),
                "broker_order_id": row["broker_order_id"],
                "cycle_id": row["cycle_id"],
            }
        )
    return result


def _empty_portfolio_snapshot() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        account_id="unavailable",
        status="unavailable",
        currency="USD",
        cash=0.0,
        portfolio_value=0.0,
        buying_power=0.0,
        positions=[],
        open_orders=[],
    )


def _opportunity_sort_key(candidate: dict[str, Any]) -> tuple[float, float, float]:
    return (
        _num(candidate.get("selection_score")) or float("-inf"),
        _num(candidate.get("rank_priority_score")) or float("-inf"),
        _num(candidate.get("score")) or float("-inf"),
    )


def _opportunity_candidates(technical_context: dict[str, Any], *, limit: int = 20) -> list[dict[str, Any]]:
    rows = []
    seen: set[str] = set()
    for candidate in [
        *(technical_context.get("selected_candidates", []) or []),
        *(technical_context.get("top_longs", []) or []),
        *(technical_context.get("all_candidates", []) or []),
    ]:
        if not isinstance(candidate, dict):
            continue
        symbol = str(candidate.get("symbol") or "").upper().strip()
        if not symbol or symbol in seen:
            continue
        if str(candidate.get("direction") or "").lower() != "long":
            continue
        rows.append(candidate)
        seen.add(symbol)
    rows.sort(key=_opportunity_sort_key, reverse=True)
    return rows[:limit]


def _opportunity_risk_plan(candidate: dict[str, Any]) -> dict[str, Any]:
    risk_plan = candidate.get("risk_plan", {}) or {}
    entry = _num(risk_plan.get("entry_price"))
    close = _num((candidate.get("technical_state", {}) or {}).get("close"))
    stop = _num(risk_plan.get("stop_loss"))
    take = _num(risk_plan.get("take_profit"))
    reward_risk = _num(risk_plan.get("reward_risk"))
    if reward_risk is None and entry is not None and stop is not None and take is not None and entry > stop:
        reward_risk = round((take - entry) / (entry - stop), 2)
    return {
        "entry_price": entry if entry is not None else close,
        "current_price": close if close is not None else entry,
        "stop_loss": stop,
        "take_profit": take,
        "reward_risk": reward_risk,
        "invalidation": risk_plan.get("invalidation"),
        "time_stop": risk_plan.get("time_stop"),
    }


def _opportunity_summary_row(candidate: dict[str, Any]) -> dict[str, Any]:
    risk = _opportunity_risk_plan(candidate)
    technical = candidate.get("technical_state", {}) or {}
    assessment = opportunity_assessment(candidate)
    entry_risk = opportunity_entry_risk(candidate)
    score_value = _num(candidate.get("selection_score"))
    if score_value is None:
        score_value = _num(candidate.get("rank_priority_score"))
    if score_value is None:
        score_value = _num(candidate.get("score"))
    return {
        "simbolo": candidate.get("symbol"),
        "ranking": candidate.get("selection_rank"),
        "puntuacion": round(score_value, 4) if score_value is not None else None,
        "score_compra": candidate.get("selection_score"),
        "score_tecnico": candidate.get("score"),
        "oportunidad": assessment["label"],
        "riesgo_entrada": entry_risk["label"],
        "lectura": assessment["summary"],
        "setup": candidate.get("setup_name"),
        "calidad": candidate.get("setup_quality"),
        "precio_actual": risk.get("current_price"),
        "entrada": risk.get("entry_price"),
        "stop_loss": risk.get("stop_loss"),
        "take_profit": risk.get("take_profit"),
        "rr": risk.get("reward_risk"),
        "rsi": technical.get("rsi_14"),
        "ret_20d": technical.get("return_20d"),
        "vol_z": technical.get("volume_zscore_20"),
    }


def _fallback_opportunity_snapshot(settings: Any, store: Store) -> dict[str, Any] | None:
    technical_context = load_latest_technical_candidates(settings.data_dir, per_side=50)
    if not technical_context.get("path"):
        return None
    snapshot = build_opportunity_snapshot(
        settings,
        store,
        technical_context,
        slot_time="sin_archivar",
        limit=20,
    )
    snapshot["summary"]["archived"] = False
    return snapshot


def _group_snapshots_by_slot(snapshots: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for snapshot in snapshots:
        slot_time = str(snapshot.get("slot_time") or "")
        if slot_time:
            grouped[slot_time] = snapshot
    return grouped


def _next_opportunity_snapshot_run_text(settings: Any, now_local: datetime | None = None) -> str:
    local_tz = ZoneInfo(settings.local_timezone)
    current = now_local.astimezone(local_tz) if now_local and now_local.tzinfo else now_local.replace(tzinfo=local_tz) if now_local else datetime.now(local_tz)
    slots = []
    for slot in settings.opportunity_snapshot_times:
        hour_text, minute_text = str(slot).split(":")
        candidate = current.replace(hour=int(hour_text), minute=int(minute_text), second=0, microsecond=0)
        if candidate > current:
            slots.append(candidate)
    if slots:
        return min(slots).strftime("%Y-%m-%d %H:%M")
    first_slot = str(settings.opportunity_snapshot_times[0])
    hour_text, minute_text = first_slot.split(":")
    next_day = current + pd.Timedelta(days=1)
    return next_day.replace(hour=int(hour_text), minute=int(minute_text), second=0, microsecond=0).strftime("%Y-%m-%d %H:%M")


def _pending_buy_plans_by_symbol(store: Store) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in store.pending_order_plans(limit=500):
        symbol = str(item.get("symbol") or "").upper().strip()
        if symbol and symbol not in result:
            result[symbol] = item
    return result


def _latest_llm_context_by_symbol(store: Store, symbols: list[str]) -> dict[str, dict[str, Any]]:
    requested = {str(symbol or "").upper().strip() for symbol in symbols if str(symbol or "").strip()}
    if not requested:
        return {}
    result: dict[str, dict[str, Any]] = {}
    with store.connect() as conn:
        for symbol in requested:
            learning_row = conn.execute(
                """
                SELECT symbol, signal_date, decision, explanation, llm_considered,
                       approved_buy, blocked_entry_quality, blocked_backtest,
                       executed_buy, gate_json, updated_at
                FROM learning_observations
                WHERE symbol = ?
                ORDER BY signal_date DESC, updated_at DESC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
            if learning_row:
                gate = _load_json_cell(learning_row["gate_json"])
                result[symbol] = {
                    "symbol": symbol,
                    "source": "learning_observations",
                    "signal_date": learning_row["signal_date"],
                    "decision": learning_row["decision"],
                    "explanation": learning_row["explanation"],
                    "llm_considered": bool(learning_row["llm_considered"]),
                    "approved_buy": bool(learning_row["approved_buy"]),
                    "blocked_entry_quality": bool(learning_row["blocked_entry_quality"]),
                    "blocked_backtest": bool(learning_row["blocked_backtest"]),
                    "executed_buy": bool(learning_row["executed_buy"]),
                    "llm_gate": gate.get("llm", {}) if isinstance(gate, dict) else {},
                    "updated_at": learning_row["updated_at"],
                }
                continue

            signal_row = conn.execute(
                """
                SELECT symbol, signal_date, decision, gate_json, updated_at
                FROM signal_outcomes
                WHERE symbol = ?
                ORDER BY signal_date DESC, updated_at DESC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
            if signal_row:
                gate = _load_json_cell(signal_row["gate_json"])
                llm_gate = gate.get("llm", {}) if isinstance(gate, dict) else {}
                result[symbol] = {
                    "symbol": symbol,
                    "source": "signal_outcomes",
                    "signal_date": signal_row["signal_date"],
                    "decision": signal_row["decision"],
                    "explanation": llm_gate.get("reason") or "",
                    "llm_considered": bool(llm_gate),
                    "approved_buy": str(signal_row["decision"] or "").lower() == "buy",
                    "blocked_entry_quality": False,
                    "blocked_backtest": False,
                    "executed_buy": False,
                    "llm_gate": llm_gate,
                    "updated_at": signal_row["updated_at"],
                }
    return result


def _llm_status_reason(llm_context: dict[str, Any] | None) -> tuple[str, str, str]:
    if not llm_context:
        return (
            "neutral",
            "Sin revision LLM",
            "No hay una decision LLM reciente guardada para este simbolo.",
        )
    decision = str(llm_context.get("decision") or "").lower()
    explanation = str(llm_context.get("explanation") or "").strip()
    llm_gate = llm_context.get("llm_gate", {}) or {}
    llm_reason = str(llm_gate.get("reason") or "").strip()
    detail = explanation or llm_reason or "Sin explicacion LLM guardada."
    if llm_context.get("approved_buy") or decision == "buy":
        return ("good", "LLM aprobo compra", detail)
    if llm_context.get("blocked_entry_quality"):
        return ("bad", "LLM bloqueada calidad", detail)
    if llm_context.get("blocked_backtest"):
        return ("bad", "LLM bloqueada backtest", detail)
    if decision in {"hold", "watch", "candidate"}:
        return ("neutral", f"LLM {decision}", detail)
    if decision:
        return ("neutral", f"LLM {decision}", detail)
    return ("neutral", "LLM sin dictamen", detail)


def _study_price(features: dict[str, Any]) -> float | None:
    return _num(features.get("close")) or _num(features.get("entry_price"))


def _company_study_signal_rows(
    store: Store,
    *,
    since_date: str | None,
    sources: list[str] | None = None,
    symbol: str | None = None,
    limit: int = 200000,
) -> list[dict[str, Any]]:
    query = """
        SELECT signal_id, source_run_id, source, symbol, signal_date,
               decision, features_json, gate_json, outcome_json,
               created_at, updated_at
        FROM signal_outcomes
        WHERE 1 = 1
    """
    params: list[Any] = []
    if since_date:
        query += " AND signal_date >= ?"
        params.append(since_date)
    if sources:
        placeholders = ",".join("?" for _ in sources)
        query += f" AND source IN ({placeholders})"
        params.extend(sources)
    if symbol:
        query += " AND symbol = ?"
        params.append(symbol.upper())
    query += " ORDER BY signal_date DESC, created_at DESC LIMIT ?"
    params.append(limit)
    with store.connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [
        {
            "signal_id": row["signal_id"],
            "source_run_id": row["source_run_id"],
            "source": row["source"],
            "symbol": row["symbol"],
            "signal_date": row["signal_date"],
            "decision": row["decision"],
            "features": json.loads(row["features_json"] or "{}"),
            "gate": json.loads(row["gate_json"] or "{}"),
            "outcome": json.loads(row["outcome_json"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def _company_study_symbol_summary(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in signals:
        symbol = str(item.get("symbol") or "").upper().strip()
        if symbol:
            grouped.setdefault(symbol, []).append(item)
    rows = []
    for symbol, items in grouped.items():
        latest = max(items, key=lambda item: (str(item.get("signal_date") or ""), str(item.get("created_at") or "")))
        features = latest.get("features") or {}
        rows.append(
            {
                "simbolo": symbol,
                "iteraciones": len(items),
                "ultima_fecha": latest.get("signal_date"),
                "ultima_hora": _local_time(latest.get("created_at")),
                "ultimo_precio": _study_price(features),
                "ultimo_score": features.get("score"),
                "ultima_decision": latest.get("decision"),
                "ultima_fuente": latest.get("source"),
                "ultimo_motivo": _company_study_reason(latest, {}, {}, {})["reason"],
            }
        )
    return sorted(rows, key=lambda item: (str(item.get("ultima_fecha") or ""), str(item.get("simbolo") or "")), reverse=True)


def _company_study_reason(
    signal: dict[str, Any],
    learning_by_signal: dict[str, dict[str, Any]],
    recommendations_by_cycle_symbol: dict[tuple[str, str], dict[str, Any]],
    plans_by_cycle_symbol: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    signal_id = str(signal.get("signal_id") or "")
    symbol = str(signal.get("symbol") or "").upper()
    run_id = str(signal.get("source_run_id") or "")
    learning = learning_by_signal.get(signal_id)
    if learning:
        if learning.get("executed_buy"):
            label = "Compra ejecutada"
            tone = "good"
        elif learning.get("approved_buy"):
            label = "Compra aprobada"
            tone = "good"
        elif learning.get("blocked_entry_quality"):
            label = "No compra: calidad"
            tone = "bad"
        elif learning.get("blocked_backtest"):
            label = "No compra: backtest"
            tone = "bad"
        else:
            label = f"No compra: {learning.get('decision') or 'decision'}"
            tone = "neutral"
        return {
            "source": "learning_observations",
            "label": label,
            "reason": learning.get("explanation") or "Decision de aprendizaje sin explicacion.",
            "tone": tone,
            "payload": learning,
        }

    recommendation = recommendations_by_cycle_symbol.get((run_id, symbol))
    if recommendation:
        payload = _load_json_cell(recommendation.get("payload_json"))
        action = str(recommendation.get("action") or payload.get("action") or "").lower()
        tone = "good" if action == "buy" else "neutral"
        return {
            "source": "trade_recommendations",
            "label": f"LLM {action or 'decision'}",
            "reason": payload.get("reason") or "Recomendacion LLM sin motivo guardado.",
            "tone": tone,
            "payload": payload,
        }

    plan = plans_by_cycle_symbol.get((run_id, symbol))
    if plan:
        payload = _load_json_cell(plan.get("payload_json"))
        risk = payload.get("risk_decision") or {}
        recommendation_payload = payload.get("recommendation") or {}
        approved = bool(plan.get("approved"))
        return {
            "source": "order_plans",
            "label": "Plan aprobado" if approved else "Plan bloqueado",
            "reason": risk.get("reason") or recommendation_payload.get("reason") or "Plan sin motivo detallado.",
            "tone": "good" if approved else "bad",
            "payload": payload,
        }

    gate = signal.get("gate") or {}
    llm_gate = gate.get("llm") if isinstance(gate, dict) else {}
    if isinstance(llm_gate, dict) and llm_gate:
        return {
            "source": "signal_outcomes",
            "label": f"Senal {signal.get('decision') or 'candidate'}",
            "reason": llm_gate.get("reason") or "Senal con gate LLM sin motivo.",
            "tone": "good" if str(signal.get("decision") or "").lower() == "buy" else "neutral",
            "payload": gate,
        }

    return {
        "source": "fallback",
        "label": "Candidato tecnico",
        "reason": "Candidato tecnico; no llego a compra/recomendacion registrada.",
        "tone": "neutral",
        "payload": signal,
    }


def _company_study_decision_context(store: Store, signals: list[dict[str, Any]]) -> dict[str, Any]:
    signal_ids = [str(item.get("signal_id") or "") for item in signals if item.get("signal_id")]
    cycle_symbols = {
        (str(item.get("source_run_id") or ""), str(item.get("symbol") or "").upper())
        for item in signals
        if item.get("source_run_id") and item.get("symbol")
    }
    learning_by_signal: dict[str, dict[str, Any]] = {}
    recommendations_by_cycle_symbol: dict[tuple[str, str], dict[str, Any]] = {}
    plans_by_cycle_symbol: dict[tuple[str, str], dict[str, Any]] = {}
    orders_by_plan_id: dict[str, dict[str, Any]] = {}
    if not signals:
        return {
            "learning_by_signal": learning_by_signal,
            "recommendations_by_cycle_symbol": recommendations_by_cycle_symbol,
            "plans_by_cycle_symbol": plans_by_cycle_symbol,
            "orders_by_plan_id": orders_by_plan_id,
        }
    with store.connect() as conn:
        if signal_ids:
            for start in range(0, len(signal_ids), 500):
                chunk = signal_ids[start : start + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"""
                    SELECT observation_id, signal_date, symbol, source_family, best_signal_id,
                           decision, explanation, llm_considered, approved_buy,
                           blocked_entry_quality, blocked_backtest, executed_buy,
                           gate_json, outcome_json, execution_json, updated_at
                    FROM learning_observations
                    WHERE best_signal_id IN ({placeholders})
                    """,
                    chunk,
                ).fetchall()
                for row in rows:
                    learning_by_signal[str(row["best_signal_id"])] = {
                        **dict(row),
                        "llm_considered": bool(row["llm_considered"]),
                        "approved_buy": bool(row["approved_buy"]),
                        "blocked_entry_quality": bool(row["blocked_entry_quality"]),
                        "blocked_backtest": bool(row["blocked_backtest"]),
                        "executed_buy": bool(row["executed_buy"]),
                        "gate": _load_json_cell(row["gate_json"]),
                        "outcome": _load_json_cell(row["outcome_json"]),
                        "execution": _load_json_cell(row["execution_json"]),
                    }
        for run_id, symbol in cycle_symbols:
            rec = conn.execute(
                """
                SELECT symbol, action, confidence, payload_json, created_at
                FROM trade_recommendations
                WHERE cycle_id = ? AND symbol = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (run_id, symbol),
            ).fetchone()
            if rec:
                recommendations_by_cycle_symbol[(run_id, symbol)] = dict(rec)
            plan = conn.execute(
                """
                SELECT plan_id, symbol, side, notional, approved, dry_run, payload_json, created_at
                FROM order_plans
                WHERE cycle_id = ? AND symbol = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (run_id, symbol),
            ).fetchone()
            if plan:
                plan_dict = dict(plan)
                plans_by_cycle_symbol[(run_id, symbol)] = plan_dict
                order = conn.execute(
                    """
                    SELECT broker_order_id, plan_id, symbol, side, status, payload_json, created_at
                    FROM broker_orders
                    WHERE plan_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (plan_dict["plan_id"],),
                ).fetchone()
                if order:
                    orders_by_plan_id[str(plan_dict["plan_id"])] = dict(order)
    return {
        "learning_by_signal": learning_by_signal,
        "recommendations_by_cycle_symbol": recommendations_by_cycle_symbol,
        "plans_by_cycle_symbol": plans_by_cycle_symbol,
        "orders_by_plan_id": orders_by_plan_id,
    }


def _company_study_news_files(reports_dir: Path) -> list[Path]:
    return sorted(
        [
            path
            for path in reports_dir.glob("news_sentiment_*.json")
            if not path.name.endswith(".manifest.json") and not path.name.startswith("latest_")
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def _news_sort_key(row: dict[str, Any]) -> tuple[str, str, str]:
    published_at = str(row.get("published_at") or "")
    analyzed_at = str(row.get("analyzed_at") or "")
    title = str(row.get("title") or "")
    return (published_at or analyzed_at, analyzed_at, title)


@_safe_cache_data(show_spinner=False, ttl=120)
def _latest_analyzed_news(reports_dir: Path, limit: int = 20) -> list[dict[str, Any]]:
    return build_latest_analyzed_news(reports_dir, limit=limit)


@_safe_cache_data(show_spinner=False, ttl=120)
def _company_study_news_for_symbol(reports_dir: Path, symbol: str, run_id: str | None = None) -> list[dict[str, Any]]:
    symbol = str(symbol or "").upper().strip()
    if not symbol:
        return []
    matches = []
    for path in _company_study_news_files(reports_dir):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if run_id and str(report.get("run_id") or "") != str(run_id):
            continue
        for item in report.get("results", []) or []:
            if str(item.get("symbol") or "").upper() == symbol:
                matches.append({**item, "report_path": str(path), "run_id": report.get("run_id"), "as_of": report.get("as_of")})
    return matches


@_safe_cache_data(show_spinner=False, ttl=120)
def _company_study_news_by_symbol(reports_dir: Path) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for path in _company_study_news_files(reports_dir):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for item in report.get("results", []) or []:
            symbol = str(item.get("symbol") or "").upper().strip()
            if not symbol:
                continue
            grouped.setdefault(symbol, []).append(
                {**item, "report_path": str(path), "run_id": report.get("run_id"), "as_of": report.get("as_of")}
            )
    return grouped


def _company_study_export_payload(
    *,
    symbol: str,
    signals: list[dict[str, Any]],
    reasons: list[dict[str, Any]],
    symbol_news: list[dict[str, Any]],
    filters: dict[str, Any],
    generated_at: str | None = None,
) -> dict[str, Any]:
    iterations = []
    approved_count = 0
    blocked_count = 0
    for sig, reason in zip(signals, reasons):
        run_id = str(sig.get("source_run_id") or "")
        news_items = [item for item in symbol_news if str(item.get("run_id") or "") == run_id]
        if not news_items:
            news_items = symbol_news[:1]
        if reason.get("tone") == "good":
            approved_count += 1
        if reason.get("tone") == "bad":
            blocked_count += 1
        features = sig.get("features") or {}
        iterations.append(
            {
                "signal_id": sig.get("signal_id"),
                "run_id": run_id,
                "source": sig.get("source"),
                "signal_date": sig.get("signal_date"),
                "created_at": sig.get("created_at"),
                "price": _study_price(features),
                "entry_price": _num(features.get("entry_price")),
                "decision": sig.get("decision"),
                "decision_reason": reason,
                "technical_features": features,
                "gate": sig.get("gate") or {},
                "outcome": sig.get("outcome") or {},
                "news_sentiment": news_items,
            }
        )
    latest_features = (signals[0].get("features") or {}) if signals else {}
    return {
        "schema": "agente_bolsa.company_studies.deepresearch.v1",
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "intended_consumer": "LLM/deepresearch",
        "symbol": str(symbol or "").upper(),
        "filters": filters,
        "summary": {
            "iterations": len(iterations),
            "approved_or_bought": approved_count,
            "blocked": blocked_count,
            "latest_signal_date": signals[0].get("signal_date") if signals else None,
            "latest_price": _study_price(latest_features),
            "latest_score": latest_features.get("score"),
            "sources": sorted({str(item.get("source") or "") for item in signals if item.get("source")}),
            "news_reports_matched": len(symbol_news),
        },
        "iterations": iterations,
    }


def _company_study_global_export_payload(
    *,
    signals: list[dict[str, Any]],
    context: dict[str, Any],
    news_by_symbol: dict[str, list[dict[str, Any]]],
    filters: dict[str, Any],
    generated_at: str | None = None,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for sig in signals:
        symbol = str(sig.get("symbol") or "").upper().strip()
        if symbol:
            grouped.setdefault(symbol, []).append(sig)

    companies = []
    total_iterations = 0
    total_approved = 0
    total_blocked = 0
    for symbol in sorted(grouped):
        symbol_signals = sorted(
            grouped[symbol],
            key=lambda item: (str(item.get("signal_date") or ""), str(item.get("created_at") or "")),
            reverse=True,
        )
        reasons = [
            _company_study_reason(
                signal,
                context["learning_by_signal"],
                context["recommendations_by_cycle_symbol"],
                context["plans_by_cycle_symbol"],
            )
            for signal in symbol_signals
        ]
        payload = _company_study_export_payload(
            symbol=symbol,
            signals=symbol_signals,
            reasons=reasons,
            symbol_news=news_by_symbol.get(symbol, []),
            filters=filters,
            generated_at=generated_at,
        )
        total_iterations += int(payload["summary"]["iterations"])
        total_approved += int(payload["summary"]["approved_or_bought"])
        total_blocked += int(payload["summary"]["blocked"])
        companies.append(payload)

    return {
        "schema": "agente_bolsa.company_studies.deepresearch.all_companies.v1",
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "intended_consumer": "LLM/deepresearch",
        "filters": filters,
        "summary": {
            "companies": len(companies),
            "iterations": total_iterations,
            "approved_or_bought": total_approved,
            "blocked": total_blocked,
            "sources": sorted({str(item.get("source") or "") for item in signals if item.get("source")}),
        },
        "companies": companies,
    }


def _manual_opportunity_recommendation(candidate: dict[str, Any], settings: Any) -> TradeRecommendation:
    risk = _opportunity_risk_plan(candidate)
    reason = "; ".join((candidate.get("reasons", []) or [])[:4]) or "oportunidad tecnica seleccionada manualmente"
    return TradeRecommendation(
        symbol=str(candidate.get("symbol") or "").upper(),
        action="buy",
        confidence=float(settings.min_llm_confidence_to_trade),
        reason=reason,
        entry_price=risk.get("entry_price"),
        stop_loss=risk.get("stop_loss"),
        take_profit=risk.get("take_profit"),
        time_horizon=str((candidate.get("risk_plan", {}) or {}).get("time_stop") or "5-10 sesiones"),
        invalidation=str((candidate.get("risk_plan", {}) or {}).get("invalidation") or "") or None,
        source="manual_opportunity_screen",
    )


def _opportunity_status(
    candidate: dict[str, Any],
    *,
    portfolio: PortfolioSnapshot,
    pending_plans_by_symbol: dict[str, dict[str, Any]],
    settings: Any,
    llm_context: dict[str, Any] | None = None,
) -> dict[str, str]:
    symbol = str(candidate.get("symbol") or "").upper()
    open_order_symbols = {str(item.symbol or "").upper() for item in portfolio.open_orders}
    position_symbols = {
        str(item.symbol or "").upper()
        for item in portfolio.positions
        if str(item.side or "long").lower() == "long" and float(item.qty or 0.0) > 0
    }
    if symbol in pending_plans_by_symbol:
        return {"tone": "neutral", "label": "Plan pendiente", "reason": "Ya existe un plan pendiente de ejecucion."}
    if symbol in open_order_symbols:
        return {"tone": "neutral", "label": "Orden abierta", "reason": "Ya hay una orden abierta en broker para este simbolo."}
    if symbol in position_symbols:
        return {"tone": "neutral", "label": "Posicion abierta", "reason": "Ya existe una posicion larga y no se deberia duplicar."}
    if candidate.get("blocked_auto_buy"):
        return {
            "tone": "bad",
            "label": "Bloqueada auto-compra",
            "reason": str(candidate.get("blocked_auto_buy_reason") or "La configuracion marca este setup como shadow/watch."),
        }
    if not settings.auto_paper_trading:
        return {
            "tone": "neutral",
            "label": "Manual por configuracion",
            "reason": "AUTO_PAPER_TRADING=false: el sistema no compra automaticamente.",
        }
    if settings.require_human_approval:
        return {
            "tone": "neutral",
            "label": "Requiere aprobacion",
            "reason": "REQUIRE_HUMAN_APPROVAL=true: necesita confirmacion humana antes de ejecucion.",
        }
    tone, label, reason = _llm_status_reason(llm_context)
    return {"tone": tone, "label": label, "reason": reason}


def _create_manual_opportunity_plan(
    *,
    candidate: dict[str, Any],
    settings: Any,
    store: Store,
    portfolio: PortfolioSnapshot,
) -> dict[str, Any]:
    symbol = str(candidate.get("symbol") or "").upper().strip()
    pending = _pending_buy_plans_by_symbol(store)
    if symbol in pending:
        return {
            "ok": False,
            "reason": "Ya existe un plan pendiente para este simbolo.",
            "code": "duplicate_pending_plan",
            "plan_id": pending[symbol].get("plan_id"),
        }

    recommendation = _manual_opportunity_recommendation(candidate, settings)
    rejected: list[dict[str, Any]] = []
    plans = build_buy_order_plans(
        settings,
        portfolio,
        [recommendation],
        dry_run=True,
        rejected=rejected,
    )
    if not plans:
        rejected_item = rejected[0] if rejected else {}
        return {
            "ok": False,
            "reason": rejected_item.get("reason") or "No se pudo crear el plan.",
            "stage": rejected_item.get("stage"),
            "checks": rejected_item.get("checks", {}),
            "recommendation": asdict(recommendation),
        }

    plan = plans[0]
    cycle_id = f"manual_opportunity_{datetime.now(ZoneInfo(settings.local_timezone)).strftime('%Y%m%d_%H%M%S')}"
    recommendation_id = new_id("rec")
    plan_id = new_id("plan")
    store.save_trade_recommendation(
        recommendation_id=recommendation_id,
        cycle_id=cycle_id,
        symbol=recommendation.symbol,
        action=recommendation.action,
        confidence=recommendation.confidence,
        payload=asdict(recommendation),
    )
    store.save_order_plan(
        plan_id=plan_id,
        cycle_id=cycle_id,
        symbol=plan.symbol,
        side=plan.side,
        notional=plan.notional,
        approved=plan.risk_decision.approved,
        dry_run=plan.dry_run,
        payload=asdict(plan),
    )
    return {
        "ok": True,
        "plan_id": plan_id,
        "cycle_id": cycle_id,
        "recommendation_id": recommendation_id,
        "plan": asdict(plan),
    }


def _order_cards(orders: list[dict[str, Any]], *, max_items: int = 8) -> None:
    if not orders:
        st.info("No hay compras/ventas recientes registradas por el agente.")
        return
    settings = _settings()
    for item in orders[:max_items]:
        side = str(item.get("side") or "").lower()
        is_buy = side == "buy"
        color = "#15803d" if is_buy else "#b91c1c"
        bg = "#f0fdf4" if is_buy else "#fef2f2"
        label = "COMPRA" if is_buy else "VENTA"
        stop = _money(item.get("stop_loss")) if item.get("stop_loss") is not None else "-"
        take = _money(item.get("take_profit")) if item.get("take_profit") is not None else "-"
        entry = _money(item.get("entry_price")) if item.get("entry_price") is not None else "-"
        confidence = item.get("confidence")
        confidence_text = f" | confianza {float(confidence):.2f}" if confidence is not None else ""
        st.markdown(
            f"""
            <div style="border:1px solid {color}; border-left:8px solid {color}; background:{bg};
                        border-radius:8px; padding:12px 14px; margin:8px 0;">
                <div style="font-weight:700; color:{color}; font-size:1.05rem;">
                    {label} {item.get("symbol")} | {_money(item.get("notional"))} | {item.get("status")}{confidence_text}
                </div>
                <div style="color:#374151; margin-top:4px;">
                    {_local_datetime(item.get("time"), settings.local_timezone)} | entrada {entry} | stop {stop} | take {take}
                </div>
                <div style="color:#111827; margin-top:6px;">
                    {item.get("reason") or "Sin motivo guardado en la orden local."}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _pl_card(label: str, value: Any, pct_value: Any | None = None) -> None:
    amount = _num(value) or 0.0
    pct_text = f" ({_pct(pct_value)})" if pct_value is not None else ""
    if amount > 0:
        color = "#15803d"
        bg = "#f0fdf4"
        border = "#86efac"
    elif amount < 0:
        color = "#b91c1c"
        bg = "#fef2f2"
        border = "#fecaca"
    else:
        color = "#374151"
        bg = "#f9fafb"
        border = "#e5e7eb"
    st.markdown(
        f"""
        <div style="background:{bg}; border:1px solid {border}; border-radius:8px; padding:14px 16px;">
            <div style="color:#6b7280; font-size:0.85rem; margin-bottom:4px;">{label}</div>
            <div style="color:{color}; font-size:1.7rem; font-weight:700;">{_money(amount)}{pct_text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _pl_color(value: Any) -> str:
    amount = _num(value) or 0.0
    if amount > 0:
        return "color: #15803d; font-weight: 700"
    if amount < 0:
        return "color: #b91c1c; font-weight: 700"
    return "color: #374151"


def _compact_metric(label: str, value: Any, detail: Any | None = None, tone: str = "neutral") -> None:
    colors = {
        "good": ("#15803d", "#f0fdf4", "#bbf7d0"),
        "bad": ("#b91c1c", "#fef2f2", "#fecaca"),
        "neutral": ("#111827", "#ffffff", "#e5e7eb"),
    }
    color, bg, border = colors.get(tone, colors["neutral"])
    detail_html = f"<div class='mini-metric-detail'>{detail if detail is not None else '&nbsp;'}</div>"
    st.markdown(
        f"""
        <div class="mini-metric" style="background:{bg}; border-color:{border};">
            <div class="mini-metric-label">{label}</div>
            <div class="mini-metric-value" style="color:{color};">{value}</div>
            {detail_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _section_title(title: str, subtitle: str | None = None) -> None:
    sub = f"<div class='section-subtitle'>{subtitle}</div>" if subtitle else ""
    st.markdown(f"<div class='section-title'>{title}</div>{sub}", unsafe_allow_html=True)


def _account_group(
    *,
    initial_equity: float | None,
    current_equity: float | None,
    cash: float | None,
    exposure: float | None,
    exposure_pct: float | None,
    total_pl: float | None,
    total_pct: float | None,
    today_pl: float | None,
    today_pct: float | None,
    positions_count: int,
    orders_count: int,
) -> None:
    total_tone = "good" if (total_pl or 0.0) > 0 else "bad" if (total_pl or 0.0) < 0 else "neutral"
    today_tone = "good" if (today_pl or 0.0) > 0 else "bad" if (today_pl or 0.0) < 0 else "neutral"
    tone_class = f"account-pl {total_tone}"
    today_class = f"account-kpi {today_tone}"
    st.markdown(
        f"""
        <div class="account-strip">
            <div class="account-title">
                <span>Cuenta</span>
                <strong class="{tone_class}">{_money(total_pl)} {_pct_signed(total_pct)}</strong>
            </div>
            <div class="account-items">
                <div><span>Equity inicial</span><strong>{_money(initial_equity)}</strong></div>
                <div><span>Equity actual</span><strong>{_money(current_equity)}</strong></div>
                <div><span>Cash</span><strong>{_money(cash)}</strong></div>
                <div><span>Invertido</span><strong>{_money(exposure)}</strong><em>{_pct(exposure_pct)}</em></div>
            </div>
            <div class="account-kpis">
                <div class="{today_class}"><span>P/L hoy</span><strong>{_money(today_pl)}</strong><em>{_pct(today_pct)}</em></div>
                <div class="account-kpi"><span>Posiciones</span><strong>{positions_count}</strong><em>&nbsp;</em></div>
                <div class="account-kpi"><span>Ordenes</span><strong>{orders_count}</strong><em>&nbsp;</em></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _dashboard_header(
    market: dict[str, Any],
    settings: Any,
    current_equity: float | None = None,
    today_pl: float | None = None,
    today_pct: float | None = None,
    llm_pills: list[dict[str, str]] | None = None,
) -> None:
    market_color, market_bg, market_border = _status_color(bool(market.get("is_open")))
    auto_color, auto_bg, auto_border = _status_color(bool(settings.auto_paper_trading))
    today_color, today_bg, today_border = _status_color((today_pl or 0.0) >= 0)
    refreshed = datetime.now(ZoneInfo(settings.local_timezone)).strftime("%H:%M:%S")
    equity_text = _money(current_equity) if current_equity is not None else "-"
    pct_text = _pct_signed(today_pct) if today_pct is not None else "-"
    extra_pills = ""
    for item in llm_pills or []:
        tone_color, tone_bg, tone_border = _tone_color(str(item.get("tone") or "neutral"))
        extra_pills += (
            f"<span style=\"color:{tone_color}; background:{tone_bg}; border-color:{tone_border};\">"
            f"{escape(str(item.get('text') or ''))}</span>"
        )
    st.markdown(
        f"""
        <div class="dashboard-header">
            <div>
                <div class="dashboard-title">Resumen operativo</div>
                <div class="dashboard-subtitle">Lo importante: resultado, cartera abierta y decisiones recientes.</div>
            </div>
            <div class="dashboard-pills">
                <span class="equity-pill">
                    Equity actual <strong>{equity_text}</strong>
                    <em style="color:{today_color}; background:{today_bg}; border-color:{today_border};">{pct_text}</em>
                </span>
                <span style="color:{market_color}; background:{market_bg}; border-color:{market_border};">
                    Mercado {'abierto' if market.get("is_open") else 'cerrado'}
                </span>
                <span style="color:{auto_color}; background:{auto_bg}; border-color:{auto_border};">
                    Auto paper {'activo' if settings.auto_paper_trading else 'manual'}
                </span>
                {extra_pills}
                <span>Refresco {refreshed}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _position_rows(history: dict[str, Any]) -> list[dict[str, Any]]:
    risk_levels = history.get("risk_levels", {})
    rows = []
    for item in history.get("open_positions", []):
        symbol = str(item.get("symbol", "")).upper()
        risk = risk_levels.get(symbol, {})
        rows.append(
            {
                "Simbolo": symbol,
                "Valor": item.get("market_value"),
                "Qty": item.get("qty"),
                "Entrada": item.get("avg_entry_price"),
                "Actual": item.get("current_price"),
                "P/L $": item.get("unrealized_pl"),
                "P/L %": item.get("unrealized_plpc"),
                "Stop": item.get("stop_loss"),
                "Take": item.get("take_profit"),
                "Motivo": risk.get("reason"),
            }
        )
    return rows


def _portfolio_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        st.markdown("<div class='empty-box'>No hay posiciones abiertas.</div>", unsafe_allow_html=True)
        return
    sorted_rows = sorted(rows, key=lambda item: abs(_num(item.get("P/L $")) or 0), reverse=True)
    body = []
    for item in sorted_rows:
        pl = _num(item.get("P/L $")) or 0.0
        plpc = item.get("P/L %")
        tone = "gain" if pl > 0 else "loss" if pl < 0 else "flat"
        symbol = escape(str(item.get("Simbolo") or "-"))
        body.append(
            "<tr>"
            f"<td><strong>{symbol}</strong></td>"
            f"<td>{_money(item.get('Valor'))}<span>qty {_num(item.get('Qty')) or 0:g}</span></td>"
            f"<td>{_money(item.get('Actual'))}<span>entrada {_money(item.get('Entrada'))}</span></td>"
            f"<td><b class=\"pl-chip {tone}\">{_money(pl)} <em>{_pct(plpc)}</em></b></td>"
            f"<td>{_money(item.get('Stop'))}</td>"
            f"<td>{_money(item.get('Take'))}</td>"
            "</tr>"
        )
    st.markdown(
        "<table class=\"portfolio-table compact-positions\">"
        "<thead><tr>"
        "<th>Accion</th><th>Valor</th><th>Precio</th><th>P/L</th><th>Stop</th><th>Take</th>"
        "</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table>",
        unsafe_allow_html=True,
    )


def _portfolio_action_table(rows: list[dict[str, Any]], *, key_prefix: str = "portfolio_symbol") -> str | None:
    if not rows:
        st.markdown("<div class='empty-box'>No hay posiciones abiertas.</div>", unsafe_allow_html=True)
        return None
    clicked_symbol = None
    sorted_rows = sorted(rows, key=lambda item: abs(_num(item.get("P/L $")) or 0), reverse=True)
    header = st.columns([1.0, 1.25, 1.25, 1.25, 1.0, 1.0])
    for column, label in zip(header, ["Accion", "Valor", "Precio", "P/L", "Stop", "Take"]):
        column.markdown(f"<div class='portfolio-native-header'>{escape(label)}</div>", unsafe_allow_html=True)
    for item in sorted_rows:
        pl = _num(item.get("P/L $")) or 0.0
        plpc = item.get("P/L %")
        tone = "gain" if pl > 0 else "loss" if pl < 0 else "flat"
        symbol = str(item.get("Simbolo") or "-").upper()
        c1, c2, c3, c4, c5, c6 = st.columns([1.0, 1.25, 1.25, 1.25, 1.0, 1.0])
        with c1:
            if st.button(symbol, key=f"{key_prefix}_{symbol}", use_container_width=True):
                clicked_symbol = symbol
        c2.markdown(
            f"<div class='portfolio-native-cell'>{_money(item.get('Valor'))}<span>qty {_num(item.get('Qty')) or 0:g}</span></div>",
            unsafe_allow_html=True,
        )
        c3.markdown(
            f"<div class='portfolio-native-cell'>{_money(item.get('Actual'))}<span>entrada {_money(item.get('Entrada'))}</span></div>",
            unsafe_allow_html=True,
        )
        c4.markdown(
            f"<div class='portfolio-native-cell'><b class='pl-chip {tone}'>{_money(pl)} <em>{_pct(plpc)}</em></b></div>",
            unsafe_allow_html=True,
        )
        c5.markdown(f"<div class='portfolio-native-cell'>{_money(item.get('Stop'))}</div>", unsafe_allow_html=True)
        c6.markdown(f"<div class='portfolio-native-cell'>{_money(item.get('Take'))}</div>", unsafe_allow_html=True)
    return clicked_symbol


def _position_first_buy_time(history: dict[str, Any], symbol: str) -> str | None:
    return build_position_first_buy_time(history, symbol)


def _position_entry_date(history: dict[str, Any], symbol: str) -> str | None:
    return build_position_entry_date(history, symbol)


def _position_chart_start_date(history: dict[str, Any], symbol: str, *, pre_entry_days: int = 7) -> str:
    return build_position_chart_start_date(
        history,
        symbol,
        pre_entry_days=pre_entry_days,
        local_timezone=_settings().local_timezone,
    )


def _single_symbol_price_frame(data: pd.DataFrame, symbol: str) -> pd.DataFrame:
    return build_single_symbol_price_frame(data, symbol)


def _position_price_series(
    settings: Any,
    symbol: str,
    history: dict[str, Any],
    *,
    current_price: float | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    return build_position_price_series(settings, symbol, history, current_price=current_price)


def _position_evolution_summary(
    price_df: pd.DataFrame,
    *,
    entry_price: float | None,
    stop_loss: float | None,
    take_profit: float | None,
) -> dict[str, Any]:
    return build_position_evolution_summary(
        price_df,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )


def _render_position_price_chart(
    price_df: pd.DataFrame,
    *,
    entry_price: float | None,
    stop_loss: float | None,
    take_profit: float | None,
    entry_date: str | None,
) -> None:
    if price_df.empty:
        st.markdown("<div class='empty-box'>Sin precios suficientes para graficar esta posicion.</div>", unsafe_allow_html=True)
        return
    if alt is None:
        st.dataframe(price_df, use_container_width=True, hide_index=True)
        return

    chart_df = price_df.copy()
    chart_df["label"] = chart_df["close"].map(lambda value: _money(value))
    y_values = [float(value) for value in chart_df["close"].dropna().tolist()]
    for value in [entry_price, stop_loss, take_profit]:
        if value:
            y_values.append(float(value))
    min_value = min(y_values)
    max_value = max(y_values)
    padding = max((max_value - min_value) * 0.18, max_value * 0.01, 1.0)
    base = alt.Chart(chart_df).encode(
        x=alt.X("fecha:N", title=None, sort=None, axis=alt.Axis(labelAngle=0, labelOverlap=True, labelLimit=90)),
        y=alt.Y(
            "close:Q",
            title="Precio",
            scale=alt.Scale(domain=[min_value - padding, max_value + padding]),
            axis=alt.Axis(format="$,.2f"),
        ),
        tooltip=[
            alt.Tooltip("fecha:N", title="Fecha"),
            alt.Tooltip("close:Q", title="Cierre", format="$,.2f"),
            alt.Tooltip("volume:Q", title="Volumen", format=",.0f"),
        ],
    )
    layers = [
        base.mark_line(color="#2563eb", strokeWidth=3),
        base.mark_circle(size=60, color="#2563eb", opacity=0.9),
    ]
    level_rows = []
    for name, value, color in [
        ("Entrada", entry_price, "#4b5563"),
        ("Stop", stop_loss, "#dc2626"),
        ("Take", take_profit, "#16a34a"),
    ]:
        if value:
            level_rows.append({"nivel": name, "precio": float(value), "color": color})
    if level_rows:
        levels = pd.DataFrame(level_rows)
        rule = (
            alt.Chart(levels)
            .mark_rule(strokeDash=[6, 4], strokeWidth=2)
            .encode(
                y="precio:Q",
                color=alt.Color("nivel:N", scale=alt.Scale(domain=[row["nivel"] for row in level_rows], range=[row["color"] for row in level_rows])),
                tooltip=[alt.Tooltip("nivel:N", title="Nivel"), alt.Tooltip("precio:Q", title="Precio", format="$,.2f")],
            )
        )
        labels = (
            alt.Chart(levels)
            .mark_text(align="left", dx=6, dy=-4, fontSize=11)
            .encode(y="precio:Q", text="nivel:N", color=alt.Color("nivel:N", legend=None))
        )
        layers.extend([rule, labels])
    if entry_date:
        entry_rows = pd.DataFrame([{"fecha": entry_date}])
        layers.append(alt.Chart(entry_rows).mark_rule(color="#111827", strokeDash=[2, 3]).encode(x="fecha:N"))
    st.altair_chart(alt.layer(*layers).properties(height=360), use_container_width=True)


def _render_position_news(settings: Any, symbol: str) -> None:
    stored_news = _company_study_news_for_symbol(settings.data_dir / "reports", symbol)
    rows = []
    for report in stored_news[:3]:
        sentiment = report.get("sentiment", {}) or {}
        for item in report.get("news", []) or []:
            rows.append(
                {
                    "publicada": _local_datetime(item.get("published_at"), settings.local_timezone)
                    if item.get("published_at")
                    else "-",
                    "fuente": item.get("publisher"),
                    "titular": item.get("title"),
                    "sentimiento": sentiment.get("sentiment"),
                    "score": sentiment.get("sentiment_score"),
                    "enlace": item.get("link"),
                }
            )
    if not rows:
        try:
            rows = [
                {
                    "publicada": _local_datetime(item.get("published_at"), settings.local_timezone)
                    if item.get("published_at")
                    else "-",
                    "fuente": item.get("publisher"),
                    "titular": item.get("title"),
                    "sentimiento": "-",
                    "score": None,
                    "enlace": item.get("link"),
                }
                for item in fetch_symbol_news(symbol, max_items=6)
            ]
        except Exception as exc:  # noqa: BLE001
            st.caption(f"No se pudieron descargar noticias recientes de {symbol}: {exc}")
            rows = []
    if not rows:
        st.markdown("<div class='empty-box'>Sin noticias recientes para esta posicion.</div>", unsafe_allow_html=True)
        return
    kwargs: dict[str, Any] = {"use_container_width": True, "hide_index": True}
    try:
        kwargs["column_config"] = {"enlace": st.column_config.LinkColumn("enlace", display_text="abrir")}
    except Exception:
        pass
    st.dataframe(pd.DataFrame(rows[:8]), **kwargs)


def _render_position_detail_content(settings: Any, history: dict[str, Any], rows: list[dict[str, Any]], symbol: str) -> None:
    if not rows:
        return
    sorted_rows = sorted(rows, key=lambda item: str(item.get("Simbolo") or ""))
    symbols = [str(item.get("Simbolo") or "").upper() for item in sorted_rows if item.get("Simbolo")]
    symbol = str(symbol or "").upper()
    if symbol not in symbols:
        symbol = symbols[0]
    item = next((row for row in sorted_rows if str(row.get("Simbolo") or "").upper() == symbol), sorted_rows[0])
    risk = (history.get("risk_levels", {}) or {}).get(symbol, {}) or {}
    executed_entry_price = _num(item.get("Entrada"))
    planned_entry_price = _num(risk.get("entry_price"))
    entry_price = executed_entry_price or planned_entry_price
    stop_loss = _num(item.get("Stop")) or _num(risk.get("stop_loss"))
    take_profit = _num(item.get("Take")) or _num(risk.get("take_profit"))
    entry_date = _position_entry_date(history, symbol)

    _section_title(f"{symbol}: evolucion y tesis", "Desde una semana antes de la compra, con entrada, stop, take y noticias.")
    try:
        price_df, meta = _position_price_series(settings, symbol, history, current_price=_num(item.get("Actual")))
    except Exception as exc:  # noqa: BLE001
        price_df, meta = pd.DataFrame(), {"error": str(exc)}
        st.warning(f"No se pudo cargar evolucion de {symbol}: {exc}")

    summary = _position_evolution_summary(
        price_df,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        _compact_metric("Entrada", _money(entry_price), entry_date or "-")
    with c2:
        _compact_metric("Actual", _money(summary.get("last_price") or item.get("Actual")), _pct(summary.get("return_from_entry")))
    with c3:
        _compact_metric("Stop", _money(stop_loss), _pct(summary.get("distance_to_stop")) if summary.get("distance_to_stop") is not None else "-")
    with c4:
        _compact_metric("Take", _money(take_profit), _pct(summary.get("distance_to_take")) if summary.get("distance_to_take") is not None else "-")
    with c5:
        confidence = _num(risk.get("confidence"))
        _compact_metric("Confianza", _pct(confidence) if confidence is not None else "-", f"{summary.get('bars', 0)} barras")

    _render_position_price_chart(
        price_df,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        entry_date=entry_date,
    )
    source = meta.get("source") or meta.get("provider_requested") or "-"
    cache = "cache" if meta.get("cache_hit") else "descarga"
    st.caption(f"Datos de precio: {source} ({cache}). Ventana desde {_position_chart_start_date(history, symbol)}.")

    left, right = st.columns([1.1, 1], gap="large")
    with left:
        _section_title("Tesis y riesgo", None)
        st.markdown(
            f"""
            <div class="position-thesis">
                <div><strong>Motivo guardado</strong><span>{escape(_short(risk.get("reason") or item.get("Motivo"), 900) or "Sin motivo guardado.")}</span></div>
                <div><strong>Plan</strong><span>Entrada plan {_money(planned_entry_price)} | entrada real {_money(executed_entry_price)} | stop {_money(stop_loss)} | take {_money(take_profit)}</span></div>
                <div><strong>Orden origen</strong><span>{escape(str(risk.get("source_plan_id") or "-"))}</span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        symbol_trades = [
            trade
            for trade in history.get("trades", [])
            if str(trade.get("symbol") or "").upper() == symbol
        ]
        if symbol_trades:
            st.dataframe(
                pd.DataFrame(symbol_trades).sort_values("time", ascending=False).head(8),
                use_container_width=True,
                hide_index=True,
            )
    with right:
        _section_title("Ultimas noticias", None)
        _render_position_news(settings, symbol)


def _position_detail_panel(settings: Any, history: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    symbols = sorted({str(item.get("Simbolo") or "").upper() for item in rows if item.get("Simbolo")})
    if not symbols:
        return
    current = st.session_state.get("selected_position_symbol")
    if current not in symbols:
        current = symbols[0]
    selected = st.selectbox(
        "Detalle de posicion",
        symbols,
        index=symbols.index(current),
        key="selected_position_symbol",
    )
    _render_position_detail_content(settings, history, rows, str(selected or current))


def _position_detail_dialog(settings: Any, history: dict[str, Any], rows: list[dict[str, Any]], symbol: str) -> None:
    symbol = str(symbol or "").upper()
    if hasattr(st, "dialog"):

        @st.dialog(f"{symbol}: evolucion y tesis", width="large")
        def _dialog() -> None:
            _render_position_detail_content(settings, history, rows, symbol)

        _dialog()
        return
    _render_position_detail_content(settings, history, rows, symbol)


def _portfolio_value_series_from_alpaca(
    portfolio_history: dict[str, Any],
    current_equity: float | None,
    *,
    start_date: str = PORTFOLIO_CHART_START_DATE,
) -> pd.DataFrame:
    timestamps = portfolio_history.get("timestamp") or []
    equities = portfolio_history.get("equity") or []
    if not timestamps or not equities:
        return pd.DataFrame()

    by_date: dict[str, float] = {}
    timezone_name = _settings().local_timezone
    for raw_ts, raw_equity in zip(timestamps, equities):
        equity = _num(raw_equity)
        if equity is None:
            continue
        try:
            if isinstance(raw_ts, (int, float)):
                parsed = datetime.fromtimestamp(float(raw_ts), tz=ZoneInfo("UTC"))
            else:
                parsed = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
        except (TypeError, ValueError, OSError):
            continue
        date = parsed.astimezone(ZoneInfo(timezone_name)).date().isoformat()
        if date >= start_date:
            by_date[date] = round(equity, 2)

    today = datetime.now(ZoneInfo(timezone_name)).date().isoformat()
    if current_equity is not None and today >= start_date:
        by_date[today] = round(float(current_equity), 2)
    if not by_date:
        return pd.DataFrame()

    rows = []
    previous_equity: float | None = None
    for date, equity in sorted(by_date.items(), key=lambda item: item[0]):
        if previous_equity is None:
            day_pl = 0.0
            day_pct = 0.0
        else:
            day_pl = round(equity - previous_equity, 2)
            day_pct = round(day_pl / previous_equity, 6) if previous_equity else 0.0
        rows.append(
            {
                "fecha": date,
                "valor_cartera": equity,
                "P/L dia": day_pl,
                "% dia": day_pct,
                "label": f"{_money(equity)} ({_pct_signed(day_pct)})",
                "fuente": "Alpaca",
            }
        )
        previous_equity = equity
    return pd.DataFrame(rows)


def _trim_portfolio_chart_range(df: pd.DataFrame, *, days: int) -> pd.DataFrame:
    if df.empty:
        return df
    window = max(int(days), 1)
    trimmed = df.sort_values("fecha").tail(window).reset_index(drop=True)
    return trimmed


def _portfolio_chart_visible_summary(df: pd.DataFrame) -> dict[str, float | int | None]:
    if df.empty:
        return {"days": 0, "pl": None, "pl_pct": None}
    ordered = df.sort_values("fecha").reset_index(drop=True)
    first_value = _num(ordered.iloc[0].get("valor_cartera"))
    last_value = _num(ordered.iloc[-1].get("valor_cartera"))
    if first_value is None or last_value is None:
        return {"days": int(len(ordered)), "pl": None, "pl_pct": None}
    pl = round(last_value - first_value, 2)
    pl_pct = round((pl / first_value), 6) if first_value else 0.0
    return {"days": int(len(ordered)), "pl": pl, "pl_pct": pl_pct}


def _latest_daily_equity_change(
    history: dict[str, Any],
    current_equity: float | None,
    portfolio_history: dict[str, Any] | None = None,
) -> dict[str, float | str | None]:
    df = _portfolio_value_series_from_alpaca(portfolio_history or {}, current_equity)
    if df.empty:
        df = _estimated_portfolio_value_series(history, current_equity, days=7)
    if df.empty:
        return {"date": None, "equity": current_equity, "pl": None, "pl_pct": None, "source": None}
    ordered = df.sort_values("fecha").reset_index(drop=True)
    latest = ordered.iloc[-1]
    return {
        "date": str(latest.get("fecha") or ""),
        "equity": _num(latest.get("valor_cartera")),
        "pl": _num(latest.get("P/L dia")),
        "pl_pct": _num(latest.get("% dia")),
        "source": str(latest.get("fuente") or ""),
    }


def _estimated_portfolio_value_series(
    history: dict[str, Any],
    current_equity: float | None,
    *,
    days: int = 7,
) -> pd.DataFrame:
    if current_equity is None:
        return pd.DataFrame(columns=["fecha", "valor_cartera", "P/L dia", "% dia", "label", "fuente"])
    timezone_name = _settings().local_timezone
    today = datetime.now(ZoneInfo(timezone_name)).date()
    history_dates = []
    for day in history.get("days", []):
        date_text = str(day.get("date") or "")[:10]
        if not date_text:
            continue
        try:
            history_dates.append(datetime.fromisoformat(date_text).date())
        except ValueError:
            continue
    anchor = max((item for item in history_dates if item <= today), default=today)
    start = anchor - pd.Timedelta(days=max(int(days), 1) - 1)
    daily_by_date: dict[str, dict[str, float]] = {}
    for day in history.get("days", []):
        date = str(day.get("date") or "")
        if not date or date < start.isoformat() or date > anchor.isoformat():
            continue
        day_pl = round((_num(day.get("realized_pl")) or 0.0) + (_num(day.get("open_unrealized_pl")) or 0.0), 2)
        denominator = _num(day.get("sell_notional")) or _num(day.get("buy_notional")) or 0.0
        item = daily_by_date.setdefault(date, {"P/L dia": 0.0, "denominador": 0.0})
        item["P/L dia"] = round(item["P/L dia"] + day_pl, 2)
        item["denominador"] = max(item["denominador"], float(denominator or 0.0))
    daily_rows = []
    for offset in range(max(int(days), 1)):
        date = (start + pd.Timedelta(days=offset)).isoformat()
        item = daily_by_date.get(date, {"P/L dia": 0.0, "denominador": 0.0})
        daily_rows.append({"fecha": date, **item})
    total_pl = round(sum(item["P/L dia"] for item in daily_rows), 2)

    baseline = float(current_equity) - total_pl
    running = baseline
    rows = []
    for item in daily_rows:
        previous_equity = running
        running += item["P/L dia"]
        denominator = previous_equity
        day_pct = round(item["P/L dia"] / denominator, 6) if denominator else 0.0
        rounded_equity = round(running, 2)
        rows.append(
            {
                "fecha": item["fecha"],
                "valor_cartera": rounded_equity,
                "P/L dia": item["P/L dia"],
                "% dia": day_pct,
                "label": f"{_money(rounded_equity)} ({_pct_signed(day_pct)})",
                "fuente": "estimado",
            }
        )
    return pd.DataFrame(rows)


def _portfolio_value_chart(
    history: dict[str, Any],
    current_equity: float | None,
    portfolio_history: dict[str, Any] | None = None,
    *,
    days: int = 7,
) -> dict[str, float | int | None]:
    df = _portfolio_value_series_from_alpaca(portfolio_history or {}, current_equity)
    used_estimate = False
    if not df.empty:
        df = _trim_portfolio_chart_range(df, days=days)
    if df.empty:
        df = _estimated_portfolio_value_series(history, current_equity, days=days)
        used_estimate = not df.empty
    if df.empty:
        st.markdown("<div class='empty-box'>Sin datos suficientes para graficar la cartera.</div>", unsafe_allow_html=True)
        return {"days": 0, "pl": None, "pl_pct": None}
    chart_df = df.copy()
    visible_summary = _portfolio_chart_visible_summary(chart_df)
    if alt is None:
        _streamlit_fallback_notice(
            "portfolio_chart_runtime_fallback",
            "Vista degradada: grafico no disponible por dependencia opcional faltante; mostrando serie tabular.",
        )
        st.dataframe(
            chart_df[["fecha", "valor_cartera", "P/L dia", "% dia", "fuente"]],
            use_container_width=True,
            hide_index=True,
        )
        if used_estimate:
            st.caption("Grafico estimado desde operaciones/P/L del agente para cuadrar con los valores de cabecera.")
        return visible_summary
    min_value = float(chart_df["valor_cartera"].min())
    max_value = float(chart_df["valor_cartera"].max())
    padding = max((max_value - min_value) * 0.28, 90.0)
    date_axis = alt.X(
        "fecha:N",
        title=None,
        sort=None,
        axis=alt.Axis(labelAngle=0, labelOverlap=True, labelLimit=80),
    )
    line = (
        alt.Chart(chart_df)
        .mark_line(color="#2563eb", strokeWidth=3)
        .encode(
            x=date_axis,
            y=alt.Y(
                "valor_cartera:Q",
                title="Valor cartera",
                scale=alt.Scale(domain=[min_value - padding, max_value + padding]),
                axis=alt.Axis(format="$,.0f"),
            ),
            tooltip=[
                alt.Tooltip("fecha:N", title="Fecha"),
                alt.Tooltip("valor_cartera:Q", title="Equity", format="$,.2f"),
                alt.Tooltip("P/L dia:Q", title="P/L dia", format="$,.2f"),
                alt.Tooltip("% dia:Q", title="% dia", format="+.2%"),
                alt.Tooltip("fuente:N", title="Fuente"),
            ],
        )
    )
    points = (
        alt.Chart(chart_df)
        .mark_circle(size=76, color="#2563eb", opacity=0.95)
        .encode(x=date_axis, y="valor_cartera:Q")
    )
    labels = (
        alt.Chart(chart_df)
        .mark_text(align="center", baseline="bottom", dy=-12, color="#111827", fontSize=10)
        .encode(x=date_axis, y="valor_cartera:Q", text="label:N")
    )
    st.altair_chart((line + points + labels).properties(height=292), use_container_width=True)
    if used_estimate:
        st.caption("Grafico estimado desde operaciones/P/L del agente para cuadrar con los valores de cabecera.")
    return visible_summary


def _positions_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        st.info("No hay posiciones abiertas.")
        return
    df = pd.DataFrame(rows)
    styled = (
        df.style.format(
            {
                "Valor": "${:,.2f}",
                "Qty": "{:,.4f}",
                "Entrada": "${:,.2f}",
                "Actual": "${:,.2f}",
                "P/L $": "${:,.2f}",
                "P/L %": "{:.2%}",
                "Stop": "${:,.2f}",
                "Take": "${:,.2f}",
            },
            na_rep="-",
        )
        .map(_pl_color, subset=["P/L $", "P/L %"])
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


def _position_cards(rows: list[dict[str, Any]], *, max_items: int = 8) -> None:
    if not rows:
        st.info("No hay posiciones abiertas.")
        return
    for item in rows[:max_items]:
        pl = _num(item.get("P/L $")) or 0.0
        plpc = item.get("P/L %")
        color = "#15803d" if pl > 0 else "#b91c1c" if pl < 0 else "#374151"
        bg = "#f0fdf4" if pl > 0 else "#fef2f2" if pl < 0 else "#f9fafb"
        border = "#86efac" if pl > 0 else "#fecaca" if pl < 0 else "#e5e7eb"
        st.markdown(
            f"""
            <div style="border:1px solid {border}; border-left:8px solid {color}; background:{bg};
                        border-radius:8px; padding:10px 12px; margin:8px 0;">
                <div style="display:flex; justify-content:space-between; gap:12px;">
                    <div style="font-weight:700; color:#111827;">{item.get("Simbolo")}</div>
                    <div style="font-weight:700; color:{color};">{_money(pl)} | {_pct(plpc)}</div>
                </div>
                <div style="color:#374151; margin-top:4px;">
                    valor {_money(item.get("Valor"))} | actual {_money(item.get("Actual"))} | entrada {_money(item.get("Entrada"))}
                </div>
                <div style="color:#4b5563; margin-top:4px;">
                    stop {_money(item.get("Stop"))} | take {_money(item.get("Take"))}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _compact_order_list(orders: list[dict[str, Any]], *, max_items: int = 5) -> None:
    if not orders:
        st.markdown("<div class='empty-box'>Sin compras/ventas recientes.</div>", unsafe_allow_html=True)
        return
    settings = _settings()
    items = []
    for item in orders[:max_items]:
        side = str(item.get("side") or "").lower()
        is_buy = side == "buy"
        color = "#15803d" if is_buy else "#b91c1c"
        label = "Compra" if is_buy else "Venta"
        items.append(
            f"""
            <div class="compact-order" style="border-left-color:{color};">
                <div class="compact-order-top">
                    <span style="color:{color};">{label}</span>
                    <strong>{item.get("symbol")}</strong>
                    <span>{_money(item.get("notional"))}</span>
                </div>
                <div class="compact-order-meta">
                    {_local_datetime(item.get("time"), settings.local_timezone)} | {item.get("status")} | stop {_money(item.get("stop_loss"))} | take {_money(item.get("take_profit"))}
                </div>
                <div class="compact-order-reason">{_short(item.get("reason"), 150) or "Sin motivo guardado."}</div>
            </div>
            """
        )
    st.markdown("".join(items), unsafe_allow_html=True)


def _latest_relevant_events(store: Store, limit: int = 8) -> list[dict[str, Any]]:
    settings = _settings()
    events = store.latest_events(80)
    rows = []
    interesting = {"Compra/Venta", "Ordenes paper", "Ciclo finalizado", "Candidatos intradia", "Auto paper"}
    for event in events:
        payload = {}
        try:
            payload = json.loads(event.get("payload_json") or "{}")
        except json.JSONDecodeError:
            payload = {}
        task = payload.get("task") or payload.get("title") or payload.get("name")
        if task not in interesting:
            continue
        rows.append(
            {
                "hora": _local_time(event.get("created_at"), settings.local_timezone),
                "tarea": task,
                "resultado": _short(payload.get("message") or payload.get("result"), 180),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _render_latest_news_panel(settings: Any, limit: int = 20) -> None:
    rows = _latest_analyzed_news(settings.data_dir / "reports", limit=limit)
    if not rows:
        latest_sentiment = _latest_report_json("latest_news_sentiment.json")
        warnings = (latest_sentiment.get("payload") or {}).get("warnings", [])
        st.markdown("<div class='empty-box'>No hay noticias analizadas disponibles.</div>", unsafe_allow_html=True)
        if warnings:
            st.caption(f"Ultimo intento: {warnings[0]}")
        return

    frame = pd.DataFrame(
        [
            {
                "analizada": _local_datetime(row.get("analyzed_at"), settings.local_timezone),
                "publicada": _local_datetime(row.get("published_at"), settings.local_timezone)
                if row.get("published_at")
                else "-",
                "tipo": row.get("scope"),
                "simbolo": row.get("symbol"),
                "titular": row.get("title"),
                "fuente": row.get("publisher"),
                "sentimiento": row.get("sentiment"),
                "score": row.get("sentiment_score"),
                "riesgo": row.get("material_risk"),
                "enlace": row.get("link"),
            }
            for row in rows
        ]
    )
    kwargs: dict[str, Any] = {"use_container_width": True, "hide_index": True}
    try:
        kwargs["column_config"] = {
            "enlace": st.column_config.LinkColumn("enlace", display_text="abrir"),
        }
    except Exception:
        pass
    st.dataframe(frame, **kwargs)


def _auto_refresh_control() -> int:
    options = [0, 10, 30, 60, 120, 300, 600]
    preferences = _load_web_preferences()
    saved_interval = preferences.get("refresh_interval_seconds", 30)
    default_interval = int(st.session_state.get("refresh_interval_seconds", saved_interval))
    default_index = options.index(default_interval) if default_interval in options else options.index(30)
    interval = st.sidebar.selectbox(
        "Refresco automatico",
        options,
        index=default_index,
        key="refresh_interval_seconds",
        format_func=lambda value: "desactivado"
        if value == 0
        else f"{value // 60} min" if value >= 60 else f"{value}s",
    )
    if preferences.get("refresh_interval_seconds") != interval:
        preferences["refresh_interval_seconds"] = int(interval)
        _save_web_preferences(preferences)
    return int(interval)


def _render_refreshable_page(page_func: Any, refresh_interval_seconds: int) -> None:
    if refresh_interval_seconds and hasattr(st, "fragment"):

        @st.fragment(run_every=f"{refresh_interval_seconds}s")
        def _live_page_values() -> None:
            page_func()

        _live_page_values()
        return

    page_func()


def _page_header(title: str, subtitle: str) -> None:
    st.title(title)
    st.caption(subtitle)


def _screen_help(title: str, body: str) -> None:
    if hasattr(st, "popover"):
        with st.popover(f"Info: {title}"):
            st.markdown(body)
    else:
        with st.expander(f"Info: {title}", expanded=False):
            st.markdown(body)


def _info_icon(title: str, body: str) -> None:
    if hasattr(st, "popover"):
        with st.popover("i"):
            st.markdown(f"**{title}**")
            st.markdown(body)
    else:
        with st.expander(f"i {title}", expanded=False):
            st.markdown(body)


def _metric_card(label: str, value: Any, delta: Any | None = None) -> None:
    st.metric(label, value, delta=delta)


def _setup_page() -> None:
    st.set_page_config(page_title="Agente Bolsa", page_icon=None, layout="wide")
    st.markdown(
        """
        <style>
        .block-container {padding-top: 3.25rem; padding-bottom: 2rem; max-width: 1500px;}
        div[data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            padding: 12px 14px;
        }
        div[data-testid="stMetric"] label {font-size: 0.82rem; color: #6b7280;}
        div[data-testid="stMetricValue"] {font-size: 1.35rem;}
        .stTabs [data-baseweb="tab-list"] {gap: 4px;}
        .dashboard-header {
            display:flex;
            justify-content:space-between;
            gap:24px;
            align-items:flex-start;
            padding: 10px 0 18px 0;
            border-bottom: 1px solid #e5e7eb;
            margin-bottom: 16px;
            margin-top: 0.25rem;
        }
        .dashboard-title {font-size: 1.65rem; font-weight: 750; color:#111827; line-height:1.15;}
        .dashboard-subtitle {color:#6b7280; margin-top:4px; font-size:0.96rem;}
        .dashboard-pills {display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end;}
        .dashboard-pills span {
            border:1px solid #e5e7eb;
            background:#f9fafb;
            color:#374151;
            border-radius:999px;
            padding:6px 10px;
            font-size:0.85rem;
            white-space:nowrap;
        }
        .dashboard-pills .equity-pill {
            display:flex;
            align-items:center;
            gap:7px;
            background:#ffffff;
            border-color:#d1d5db;
            color:#111827;
        }
        .dashboard-pills .equity-pill strong {font-weight:760;}
        .dashboard-pills .equity-pill em {
            border:1px solid;
            border-radius:999px;
            font-style:normal;
            font-size:0.78rem;
            padding:2px 6px;
        }
        .dashboard-panel {
            border:1px solid #e5e7eb;
            border-radius:8px;
            background:#ffffff;
            padding:14px 16px;
            min-height:100%;
        }
        .account-strip {
            display:block;
            border:1px solid #d1d5db;
            border-radius:8px;
            background:#ffffff;
            padding:12px 14px;
            min-height:100%;
            box-sizing:border-box;
        }
        .account-title {
            display:flex;
            justify-content:space-between;
            gap:10px;
            align-items:flex-start;
            margin-bottom:10px;
        }
        .account-title span {
            display:block;
            color:#6b7280;
            font-size:0.78rem;
            margin-bottom:4px;
        }
        .account-title strong {
            display:block;
            font-size:0.94rem;
            line-height:1.15;
        }
        .account-items {
            display:grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap:8px 10px;
        }
        .account-items div {
            border-top:1px solid #e5e7eb;
            padding-top:7px;
            min-width:0;
        }
        .account-items span {
            display:block;
            color:#6b7280;
            font-size:0.74rem;
            line-height:1.05;
            margin-bottom:4px;
        }
        .account-items strong {
            display:block;
            color:#111827;
            font-size:1.05rem;
            line-height:1.15;
            font-weight:760;
            white-space:nowrap;
        }
        .account-items em {
            display:block;
            color:#6b7280;
            font-size:0.74rem;
            font-style:normal;
            margin-top:2px;
        }
        .account-pl.good {color:#15803d;}
        .account-pl.bad {color:#b91c1c;}
        .account-pl.neutral {color:#374151;}
        .account-kpis {
            display:grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap:8px;
            margin-top:12px;
            padding-top:12px;
            border-top:1px solid #e5e7eb;
        }
        .account-kpi {
            border:1px solid #e5e7eb;
            border-radius:8px;
            padding:9px 10px;
            min-height:70px;
            box-sizing:border-box;
            background:#ffffff;
        }
        .account-kpi span {
            display:block;
            color:#6b7280;
            font-size:0.76rem;
            margin-bottom:5px;
        }
        .account-kpi strong {
            display:block;
            color:#111827;
            font-size:1.12rem;
            font-weight:760;
            line-height:1.15;
        }
        .account-kpi em {
            display:block;
            color:#6b7280;
            font-size:0.74rem;
            font-style:normal;
            margin-top:3px;
        }
        .account-kpi.good {background:#f0fdf4; border-color:#bbf7d0;}
        .account-kpi.good strong {color:#15803d;}
        .account-kpi.bad {background:#fef2f2; border-color:#fecaca;}
        .account-kpi.bad strong {color:#b91c1c;}
        .section-title {
            font-size: 1rem;
            font-weight: 750;
            color: #111827;
            margin: 8px 0 2px 0;
        }
        .section-subtitle {
            color:#6b7280;
            font-size:0.82rem;
            margin-bottom: 10px;
        }
        .mini-metric {
            border:1px solid #e5e7eb;
            border-radius:8px;
            padding:10px 12px;
            min-height:92px;
            box-sizing:border-box;
            display:flex;
            flex-direction:column;
            justify-content:center;
        }
        .mini-metric-label {
            color:#6b7280;
            font-size:0.78rem;
            margin-bottom:4px;
        }
        .mini-metric-value {
            font-size:1.18rem;
            font-weight:760;
            line-height:1.2;
        }
        .mini-metric-detail {
            color:#6b7280;
            font-size:0.78rem;
            margin-top:3px;
            min-height:0.95rem;
        }
        .empty-box {
            border:1px dashed #d1d5db;
            border-radius:8px;
            padding:18px;
            color:#6b7280;
            background:#f9fafb;
        }
        .position-thesis {
            border:1px solid #e5e7eb;
            border-radius:8px;
            background:#ffffff;
            margin:8px 0 12px 0;
            overflow:hidden;
        }
        .position-thesis div {
            padding:10px 12px;
            border-bottom:1px solid #f3f4f6;
        }
        .position-thesis div:last-child {border-bottom:none;}
        .position-thesis strong {
            display:block;
            color:#111827;
            font-size:0.82rem;
            margin-bottom:4px;
        }
        .position-thesis span {
            display:block;
            color:#374151;
            font-size:0.86rem;
            line-height:1.35;
        }
        .portfolio-table {
            width:100%;
            border-collapse: separate;
            border-spacing: 0;
            overflow:hidden;
            border:1px solid #e5e7eb;
            border-radius:8px;
            background:#ffffff;
            font-size:0.92rem;
        }
        .portfolio-table th {
            text-align:left;
            padding:9px 10px;
            background:#f9fafb;
            color:#6b7280;
            font-weight:650;
            border-bottom:1px solid #e5e7eb;
        }
        .portfolio-table td {
            padding:7px 9px;
            border-bottom:1px solid #f3f4f6;
            vertical-align:middle;
        }
        .portfolio-table tr:last-child td {border-bottom:none;}
        .portfolio-table td span {
            display:block;
            color:#6b7280;
            font-size:0.72rem;
            line-height:1.15;
            margin-top:2px;
        }
        .portfolio-native-header {
            background:#f9fafb;
            color:#6b7280;
            font-weight:650;
            font-size:0.80rem;
            border-top:1px solid #e5e7eb;
            border-bottom:1px solid #e5e7eb;
            padding:7px 4px;
        }
        .portfolio-native-cell {
            color:#111827;
            font-size:0.84rem;
            padding:7px 4px 5px 4px;
            border-bottom:1px solid #f3f4f6;
            min-height:42px;
            box-sizing:border-box;
        }
        .portfolio-native-cell span {
            display:block;
            color:#6b7280;
            font-size:0.72rem;
            line-height:1.15;
            margin-top:2px;
        }
        .compact-positions {font-size:0.86rem;}
        .compact-positions th {padding:7px 9px;}
        .pl-chip {
            display:inline-block;
            border-radius:6px;
            padding:3px 7px;
            line-height:1.15;
            min-width:92px;
        }
        .pl-chip em {font-style:normal; font-size:0.74rem;}
        .pl-chip.gain {background:#f0fdf4; color:#15803d;}
        .pl-chip.loss {background:#fef2f2; color:#b91c1c;}
        .pl-chip.flat {background:#f9fafb; color:#374151;}
        .compact-order {
            border:1px solid #e5e7eb;
            border-left:6px solid #6b7280;
            border-radius:8px;
            padding:8px 10px;
            background:#ffffff;
            margin:8px 0 7px 0;
        }
        .compact-order-top {
            display:grid;
            grid-template-columns: 58px 1fr auto;
            gap:8px;
            align-items:center;
            color:#111827;
        }
        .compact-order-top strong {text-align:center;}
        .compact-order-top span:first-child {font-weight:750;}
        .compact-order-meta {
            color:#6b7280;
            font-size:0.76rem;
            margin-top:4px;
        }
        .compact-order-reason {
            color:#374151;
            font-size:0.80rem;
            margin-top:5px;
            display:-webkit-box;
            -webkit-line-clamp:2;
            -webkit-box-orient:vertical;
            overflow:hidden;
        }
        .dashboard-divider {height:12px;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_performance_baseline(store: Any) -> None:
    """Grafico de equity vs SPY acumulado e iq_score (T0.2)."""

    try:
        rows = store.performance_daily(limit=0)
    except Exception:  # noqa: BLE001 - vista degradable.
        rows = []
    with st.container(border=True):
        _section_title("Baseline de rendimiento e iq_score", None)
        if not rows:
            st.markdown(
                "<div class='empty-box'>Sin baseline todavia. Se genera tras el review post-mercado.</div>",
                unsafe_allow_html=True,
            )
            return

        cum_pnl = 0.0
        cum_spy = 0.0
        chart_rows = []
        for row in rows:
            pnl = row.get("pnl_pct") if isinstance(row.get("pnl_pct"), (int, float)) else 0.0
            spy = row.get("spy_pct") if isinstance(row.get("spy_pct"), (int, float)) else 0.0
            cum_pnl += pnl
            cum_spy += spy
            chart_rows.append(
                {
                    "fecha": row.get("session_date"),
                    "Sistema": round(cum_pnl, 6),
                    "SPY": round(cum_spy, 6),
                    "iq_score": row.get("iq_score"),
                }
            )
        frame = pd.DataFrame(chart_rows)
        latest = rows[-1]
        m1, m2, m3 = st.columns(3)
        with m1:
            _compact_metric("iq_score", latest.get("iq_score"))
        with m2:
            _compact_metric("Alpha acumulado", _pct(round(cum_pnl - cum_spy, 6)))
        with m3:
            _compact_metric("Sharpe 60", latest.get("sharpe_60"))
        if alt is None:
            st.dataframe(frame, use_container_width=True, hide_index=True)
            return
        long_frame = frame.melt(
            id_vars=["fecha"],
            value_vars=["Sistema", "SPY"],
            var_name="serie",
            value_name="retorno_acumulado",
        )
        equity_chart = (
            alt.Chart(long_frame)
            .mark_line(strokeWidth=2.5)
            .encode(
                x=alt.X("fecha:N", title=None, axis=alt.Axis(labelAngle=0, labelOverlap=True)),
                y=alt.Y("retorno_acumulado:Q", title="Retorno acumulado", axis=alt.Axis(format="+.1%")),
                color=alt.Color("serie:N", title=None),
                tooltip=[
                    alt.Tooltip("fecha:N", title="Fecha"),
                    alt.Tooltip("serie:N", title="Serie"),
                    alt.Tooltip("retorno_acumulado:Q", title="Acumulado", format="+.2%"),
                ],
            )
        )
        st.altair_chart(equity_chart.properties(height=240), use_container_width=True)
        iq_chart = (
            alt.Chart(frame)
            .mark_line(color="#7c3aed", strokeWidth=2.5)
            .encode(
                x=alt.X("fecha:N", title=None, axis=alt.Axis(labelAngle=0, labelOverlap=True)),
                y=alt.Y("iq_score:Q", title="iq_score", scale=alt.Scale(domain=[0, 100])),
                tooltip=[alt.Tooltip("fecha:N", title="Fecha"), alt.Tooltip("iq_score:Q", title="iq_score")],
            )
        )
        st.altair_chart(iq_chart.properties(height=200), use_container_width=True)


def _render_autonomy_panel(store: Any, settings: Any) -> None:
    """Pestana de autonomia y freno humano (T4.2)."""

    try:
        from .tools.autonomy_digest import collect_autonomy_state, pause_all, resume_all
    except Exception:  # noqa: BLE001
        return
    with st.container(border=True):
        _section_title("Autonomia y freno humano", None)
        try:
            state = collect_autonomy_state(store, settings)
        except Exception:  # noqa: BLE001
            st.markdown("<div class='empty-box'>Estado de autonomia no disponible.</div>", unsafe_allow_html=True)
            return
        a1, a2, a3, a4 = st.columns(4)
        with a1:
            _compact_metric("Nivel autonomia", state.get("autonomy_level"))
        with a2:
            _compact_metric("Aplicados", state.get("applied"))
        with a3:
            _compact_metric("Revertidos", state.get("rolled_back"))
        with a4:
            _compact_metric("Agentes dinamicos", state.get("dynamic_agents"))
        thesis = state.get("market_thesis") or {}
        st.caption(
            f"iq_score: {state.get('iq_score')} | lecciones activas: {state.get('active_lessons')} | "
            f"promociones abiertas: {state.get('promotions_open')} | tesis: {thesis.get('stance')}"
        )
        try:
            from .tools.naive_benchmarks import edge_report as _edge_report

            edge = _edge_report(store, sessions=60)
            freeze = "ON" if getattr(settings, "system_freeze_mode", False) else "off"
            st.caption(f"Edge base (T5.1): **{edge['verdict']}** | freeze={freeze} | t_vs_SPY={edge['t_stat_vs_spy']}")
        except Exception:  # noqa: BLE001
            pass
        paused = bool(state.get("lab_enabled") is False)
        col_pause, col_resume = st.columns(2)
        with col_pause:
            if st.button("PAUSA TOTAL", type="primary", disabled=paused):
                pause_all(store, settings)
                st.warning("Sistema pausado: kill switch activo y laboratorio congelado.")
        with col_resume:
            if st.button("Reanudar", disabled=not paused):
                resume_all(store, settings)
                st.success("Sistema reanudado.")


def page_dashboard() -> None:
    settings = _settings()
    store = _store()
    market = MarketCalendar(settings.market_calendar, settings.local_timezone).status().as_dict()
    latest_ci_llm_result = _latest_ci_llm_result(store.latest_events(400))

    portfolio = None
    portfolio_error = None
    try:
        portfolio = BrokerClientFactory(settings).alpaca_portfolio_snapshot()
    except Exception as exc:  # noqa: BLE001
        portfolio_error = str(exc)
    db_status = store.status()
    history: dict[str, Any] = {}
    stats: dict[str, Any] = {}
    position_rows: list[dict[str, Any]] = []
    portfolio_history: dict[str, Any] = {}
    try:
        history = build_trade_history(settings, limit=1000, start_date=DEFAULT_START_DATE)
        stats = history.get("current_statistics", {})
        position_rows = _position_rows(history)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"No se pudo leer historico/P/L: {exc}")
    try:
        portfolio_history = BrokerClientFactory(settings).alpaca_portfolio_history(period="3M", timeframe="1D")
    except Exception as exc:  # noqa: BLE001
        st.warning(f"No se pudo leer portfolio history de Alpaca para el grafico: {exc}")

    if portfolio_error:
        st.warning(f"No se pudo leer cartera Alpaca: {portfolio_error}")

    exposure = stats.get("exposure") if stats else None
    exposure_pct = stats.get("exposure_pct") if stats else None
    total_pl = _num(stats.get("total_pl")) if stats else 0.0
    total_pct = _num(stats.get("total_plpc_on_equity")) if stats else 0.0
    current_equity = _num(portfolio.portfolio_value) if portfolio else _num(stats.get("equity"))
    current_cash = _num(portfolio.cash) if portfolio else _num(stats.get("cash"))
    today_change = _latest_daily_equity_change(history, current_equity, portfolio_history)
    today_total = _num(today_change.get("pl")) or 0.0
    today_pct = _num(today_change.get("pl_pct")) or 0.0
    initial_equity = round(current_equity - total_pl, 2) if current_equity is not None and total_pl is not None else None
    total_tone = "good" if (total_pl or 0) > 0 else "bad" if (total_pl or 0) < 0 else "neutral"

    _dashboard_header(
        market,
        settings,
        current_equity=current_equity,
        today_pl=today_total,
        today_pct=today_pct,
        llm_pills=_dashboard_llm_pills(settings, store, latest_ci_llm_result),
    )

    latest_orders = _latest_order_details(limit=12)
    learning_digest = _latest_learning_digest()
    learning_summary = _learning_compact_summary(learning_digest)
    latest_quality = _latest_report_json("latest_market_data_quality.json")
    latest_readiness = _latest_report_json("latest_live_readiness.json")
    latest_weekly = _latest_report_json("latest_weekly_trading_review.json")
    buys = [item for item in latest_orders if item.get("side") == "buy"]
    sells = [item for item in latest_orders if item.get("side") == "sell"]
    last_order = latest_orders[0] if latest_orders else None

    main_left, main_right = st.columns([1.72, 1.0], gap="large")
    with main_left:
        _account_group(
            initial_equity=initial_equity,
            current_equity=current_equity,
            cash=current_cash,
            exposure=_num(exposure),
            exposure_pct=_num(exposure_pct),
            total_pl=total_pl,
            total_pct=total_pct,
            today_pl=today_total,
            today_pct=today_pct,
            positions_count=len(portfolio.positions) if portfolio else 0,
            orders_count=len(portfolio.open_orders) if portfolio else 0,
        )

        st.markdown("<div class='dashboard-divider'></div>", unsafe_allow_html=True)
        with st.container(border=True):
            _section_title("Cartera abierta", None)
            selected_position = _portfolio_action_table(position_rows, key_prefix="dashboard_position")
            if selected_position:
                _position_detail_dialog(settings, history, position_rows, selected_position)

        st.markdown("<div class='dashboard-divider'></div>", unsafe_allow_html=True)
        with st.container(border=True):
            chart_title, chart_control = st.columns([3, 1])
            with chart_title:
                _section_title("Valor de cartera", "Evolucion diaria. Las etiquetas muestran valor total y % del dia.")
            with chart_control:
                chart_days = st.selectbox(
                    "Rango",
                    [7, 15, 30],
                    format_func=lambda value: f"Ultimos {value} dias",
                    key="portfolio_chart_days",
                    label_visibility="collapsed",
                )
            visible_range_summary = _portfolio_value_chart(
                history,
                portfolio.portfolio_value if portfolio else None,
                portfolio_history,
                days=int(chart_days),
            )
            p1, p2, p3, p4 = st.columns(4)
            with p1:
                _compact_metric("P/L desde abril", _money(stats.get("total_pl")), _pct(stats.get("total_plpc_on_equity")), total_tone)
            with p2:
                visible_pl = _num((visible_range_summary or {}).get("pl"))
                visible_pct = _num((visible_range_summary or {}).get("pl_pct"))
                visible_tone = "good" if (visible_pl or 0.0) > 0 else "bad" if (visible_pl or 0.0) < 0 else "neutral"
                _compact_metric(
                    f"P/L ultimos {int(chart_days)}d",
                    _money(visible_pl),
                    _pct(visible_pct) if visible_pct is not None else None,
                    visible_tone,
                )
            with p3:
                open_pl = _num(stats.get("unrealized_pl")) if stats else 0.0
                _compact_metric("P/L abierto", _money(open_pl), tone="good" if open_pl > 0 else "bad" if open_pl < 0 else "neutral")
            with p4:
                realized_pl = _num(stats.get("realized_pl")) if stats else 0.0
                _compact_metric("P/L realizado", _money(realized_pl), tone="good" if realized_pl > 0 else "bad" if realized_pl < 0 else "neutral")

    with main_right:
        with st.container(border=True):
            _section_title("Compras y ventas recientes", None)
            c1, c2, c3 = st.columns(3)
            with c1:
                _compact_metric("Compras", len(buys))
            with c2:
                _compact_metric("Ventas", len(sells))
            with c3:
                _compact_metric(
                    "Ultima",
                    f"{last_order.get('side', '-').upper()} {last_order.get('symbol', '')}" if last_order else "-",
                )
            _compact_order_list(latest_orders, max_items=3)

        st.markdown("<div class='dashboard-divider'></div>", unsafe_allow_html=True)
        with st.container(border=True):
            _section_title("Actividad del sistema", "Eventos relevantes, sin ruido minuto a minuto.")
            relevant_events = _latest_relevant_events(store, limit=6)
            if relevant_events:
                st.dataframe(pd.DataFrame(relevant_events), width="stretch", hide_index=True)
            else:
                st.markdown("<div class='empty-box'>Sin eventos relevantes recientes.</div>", unsafe_allow_html=True)

        st.markdown("<div class='dashboard-divider'></div>", unsafe_allow_html=True)
        with st.container(border=True):
            _section_title("Ultimas noticias analizadas", "Titulares usados por el analisis de sentimiento.")
            _render_latest_news_panel(settings, limit=20)

        st.markdown("<div class='dashboard-divider'></div>", unsafe_allow_html=True)
        with st.container(border=True):
            _section_title("Controles operativos", "Cobertura de datos, readiness y ultimo resumen semanal.")
            q = (latest_quality.get("payload") or {}).get("summary", {}) if latest_quality.get("available") else {}
            r = (latest_readiness.get("payload") or {}).get("summary", {}) if latest_readiness.get("available") else {}
            w = (latest_weekly.get("payload") or {}).get("summary", {}) if latest_weekly.get("available") else {}
            c1, c2, c3 = st.columns(3)
            with c1:
                coverage = _num(q.get("coverage_ratio"))
                _compact_metric(
                    "Cobertura datos",
                    _pct(coverage) if coverage is not None else "-",
                    str(q.get("provider_used") or "sin informe"),
                    "good" if (coverage or 0.0) >= 0.95 else "bad" if coverage is not None else "neutral",
                )
            with c2:
                _compact_metric(
                    "Live readiness",
                    "OK" if r.get("ready_for_live") else "BLOCK" if latest_readiness.get("available") else "-",
                    f"{r.get('blocks', 0)} blocks",
                    "bad" if latest_readiness.get("available") and not r.get("ready_for_live") else "neutral",
                )
            with c3:
                _compact_metric(
                    "Bloqueos semana",
                    int((w.get("blocked_entry_quality") or 0) + (w.get("blocked_backtest") or 0)) if w else "-",
                    str(w.get("benchmark_symbol") or "-"),
                )

        st.markdown("<div class='dashboard-divider'></div>", unsafe_allow_html=True)
        with st.container(border=True):
            _section_title("Aprendizaje reciente", "Una vista minima de edge, confianza y error de estimacion.")
            top_setup = learning_summary.get("top_setup", {}) or {}
            top_symbol_setup = learning_summary.get("top_symbol_setup", {}) or {}
            best_conf = learning_summary.get("best_confidence_bucket", {}) or {}
            worst_accuracy = learning_summary.get("worst_accuracy", {}) or {}
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                _compact_metric(
                    "Setup 3d",
                    str(top_setup.get("setup") or "-"),
                    _pct_signed(top_setup.get("avg_return")) if top_setup.get("avg_return") is not None else "-",
                    "good" if (_num(top_setup.get("avg_return")) or 0.0) > 0 else "neutral",
                )
            with c2:
                _compact_metric(
                    "Ticker/setup",
                    f"{top_symbol_setup.get('symbol', '-')}/{top_symbol_setup.get('setup', '-')}",
                    _pct_signed(top_symbol_setup.get("avg_return")) if top_symbol_setup.get("avg_return") is not None else "-",
                    "good" if (_num(top_symbol_setup.get("avg_return")) or 0.0) > 0 else "bad" if top_symbol_setup.get("avg_return") is not None else "neutral",
                )
            with c3:
                _compact_metric(
                    "Confianza",
                    str(best_conf.get("bucket") or "-"),
                    _pct_signed(best_conf.get("avg_return")) if best_conf.get("avg_return") is not None else "-",
                    "good" if (_num(best_conf.get("avg_return")) or 0.0) > 0 else "neutral",
                )
            with c4:
                error_value = _num(worst_accuracy.get("avg_abs_error"))
                _compact_metric(
                    "Error prior",
                    _pct(error_value) if error_value is not None else "-",
                    str(worst_accuracy.get("setup") or "-"),
                    "bad" if (error_value or 0.0) >= 0.04 else "neutral",
                )

    _render_performance_baseline(store)
    _render_autonomy_panel(store, settings)

    with st.expander("Ver log completo reciente"):
        st.caption(
            f"Broker: {settings.broker} ({'paper' if settings.alpaca_paper else 'live'}). "
            f"Ordenes locales registradas: {db_status['tables'].get('broker_orders', 0)}."
        )
        events = store.latest_events(20)
        if events:
            st.dataframe(_events_dataframe(events), width="stretch", hide_index=True)
        else:
            st.info("Todavia no hay eventos registrados.")


def page_portfolio() -> None:
    settings = _settings()
    _page_header("Cartera", "Posiciones, ordenes abiertas, stops, takes y motivos guardados por el sistema.")
    try:
        portfolio = BrokerClientFactory(settings).alpaca_portfolio_snapshot()
    except Exception as exc:  # noqa: BLE001
        st.error(f"No se pudo leer Alpaca: {exc}")
        return

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _metric_card("Cash", _money(portfolio.cash))
    with c2:
        _metric_card("Valor cartera", _money(portfolio.portfolio_value))
    with c3:
        _metric_card("Buying power", _money(portfolio.buying_power))
    with c4:
        _metric_card("Ordenes abiertas", len(portfolio.open_orders))

    history = build_trade_history(settings, limit=300, start_date=DEFAULT_START_DATE)
    risk_levels = history.get("risk_levels", {})
    position_rows = _position_rows(history)
    positions = []
    for item in history.get("open_positions", []):
        risk = risk_levels.get(str(item.get("symbol")).upper(), {})
        positions.append(
            {
                "simbolo": item.get("symbol"),
                "qty": item.get("qty"),
                "valor": item.get("market_value"),
                "precio_medio": item.get("avg_entry_price"),
                "precio_actual": item.get("current_price"),
                "P/L abierto": item.get("unrealized_pl"),
                "P/L %": item.get("unrealized_plpc"),
                "stop_loss": item.get("stop_loss"),
                "take_profit": item.get("take_profit"),
                "confianza": risk.get("confidence"),
                "motivo compra": risk.get("reason"),
            }
        )

    st.subheader("Posiciones abiertas")
    if positions:
        st.dataframe(pd.DataFrame(positions), use_container_width=True, hide_index=True)
        st.markdown("<div class='dashboard-divider'></div>", unsafe_allow_html=True)
        _position_detail_panel(settings, history, position_rows)
    else:
        st.info("No hay posiciones abiertas.")

    st.subheader("Ordenes abiertas en Alpaca")
    if portfolio.open_orders:
        st.dataframe(pd.DataFrame([asdict(item) for item in portfolio.open_orders]), use_container_width=True)
    else:
        st.info("No hay ordenes abiertas.")

    st.subheader("Ordenes enviadas por el agente")
    orders = _orders_dataframe(history.get("local_broker_orders", []))
    if not orders.empty:
        st.dataframe(orders.sort_values("fecha", ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("No hay ordenes locales desde abril de 2026.")


def page_history() -> None:
    settings = _settings()
    _page_header("Historico", "Compras, ventas, P/L realizado, P/L abierto y resumen global.")
    limit = st.slider("Operaciones a cargar", 50, 1000, 300, 50)
    history = build_trade_history(settings, limit=limit, start_date=DEFAULT_START_DATE)
    stats = history.get("current_statistics", {})

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _metric_card("P/L total", _money(stats.get("total_pl")), _pct(stats.get("total_plpc_on_equity")))
    with c2:
        _metric_card("P/L realizado", _money(stats.get("realized_pl")))
    with c3:
        _metric_card("P/L abierto", _money(stats.get("unrealized_pl")))
    with c4:
        _metric_card("Exposicion", _money(stats.get("exposure")), _pct(stats.get("exposure_pct")))

    c5, c6, c7, c8 = st.columns(4)
    with c5:
        _metric_card("Cash", _money(stats.get("cash")), _pct(stats.get("cash_pct")))
    with c6:
        _metric_card("Comprado", _money(stats.get("buy_notional")))
    with c7:
        _metric_card("Vendido", _money(stats.get("sell_notional")))
    with c8:
        _metric_card("Posiciones abiertas", stats.get("open_positions", 0))

    st.subheader("Resumen por dia")
    daily_rows = []
    for day in history.get("days", []):
        daily_rows.append(
            {
                "fecha": day.get("date"),
                "comprado": day.get("buy_notional"),
                "vendido": day.get("sell_notional"),
                "P/L realizado": day.get("realized_pl"),
                "P/L realizado %": day.get("realized_plpc"),
                "P/L abierto": day.get("open_unrealized_pl"),
                "P/L abierto %": day.get("open_unrealized_plpc"),
                "trades": len(day.get("trades", [])),
                "posiciones abiertas": len(day.get("open_positions", [])),
            }
        )
    if daily_rows:
        st.dataframe(pd.DataFrame(daily_rows).sort_values("fecha", ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("No hay historico visible desde abril de 2026.")

    st.subheader("Operaciones")
    trades = pd.DataFrame(history.get("trades", []))
    if not trades.empty:
        st.dataframe(trades.sort_values("time", ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("No hay fills de Alpaca para el filtro actual.")

    with st.expander("Resumen tecnico completo"):
        st.json(history.get("summary", {}))
        st.json(history.get("current_statistics", {}))


def page_recent_trades() -> None:
    settings = _settings()
    _page_header("Compras/Ventas", "Ultimas ordenes del agente y fills reales, con motivo, stop, take y estado.")
    limit = st.slider("Ordenes a cargar", 20, 500, 100, 20)
    orders = _latest_order_details(limit=limit)

    buys = [item for item in orders if item.get("side") == "buy"]
    sells = [item for item in orders if item.get("side") == "sell"]
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _metric_card("Compras", len(buys), _money(sum(_num(item.get("notional")) or 0 for item in buys)))
    with c2:
        _metric_card("Ventas", len(sells), _money(sum(_num(item.get("notional")) or 0 for item in sells)))
    with c3:
        _metric_card("Ultima compra", buys[0].get("symbol") if buys else "-")
    with c4:
        _metric_card("Ultima venta", sells[0].get("symbol") if sells else "-")

    tab_cards, tab_table, tab_fills = st.tabs(["Vista rapida", "Tabla ordenes", "Fills Alpaca"])
    with tab_cards:
        _order_cards(orders, max_items=20)
    with tab_table:
        if orders:
            st.dataframe(pd.DataFrame(orders), use_container_width=True, hide_index=True)
        else:
            st.info("No hay ordenes locales desde abril de 2026.")
    with tab_fills:
        history = build_trade_history(settings, limit=limit, start_date=DEFAULT_START_DATE)
        trades = pd.DataFrame(history.get("trades", []))
        if not trades.empty:
            st.dataframe(trades.sort_values("time", ascending=False), use_container_width=True, hide_index=True)
        else:
            st.info("No hay fills de Alpaca para el filtro actual.")


def page_opportunities() -> None:
    settings = _settings()
    store = _store()
    _page_header(
        "Oportunidades",
        "Snapshots historicos de oportunidades largas, organizados por dia y por hora de captura.",
    )
    _screen_help(
        "Oportunidades de compra",
        (
            "Cada snapshot guarda un escaneo tecnico nuevo y su top 20. "
            "Puedes navegar por fecha y hora, y crear planes de compra desde cualquier snapshot. "
            "Si aun no existe historico, la pantalla cae temporalmente al ultimo estudio tecnico como vista no archivada."
        ),
    )

    latest_snapshot = store.latest_opportunity_snapshot()
    fallback_snapshot = None
    archived_mode = latest_snapshot is not None
    if latest_snapshot is None:
        fallback_snapshot = _fallback_opportunity_snapshot(settings, store)
        if fallback_snapshot is None:
            st.info("Todavia no hay snapshots de oportunidades ni estudio tecnico reciente.")
            st.code(r".\.venv\Scripts\python.exe -m agente_bolsa.main opportunity-snapshot --slot 16:00", language="powershell")
            return

    active_snapshot = latest_snapshot or fallback_snapshot
    opportunities = list(active_snapshot.get("opportunities", []) or [])
    if not opportunities:
        st.info("No hay oportunidades disponibles para el snapshot seleccionado.")
        return

    portfolio = _empty_portfolio_snapshot()
    portfolio_error = None
    try:
        portfolio = BrokerClientFactory(settings).alpaca_portfolio_snapshot()
    except Exception as exc:  # noqa: BLE001
        portfolio_error = str(exc)
        st.warning(f"No se pudo leer la cartera Alpaca. La compra quedara deshabilitada: {exc}")

    pending_plans = _pending_buy_plans_by_symbol(store)
    summary = active_snapshot.get("summary", {}) or {}

    if archived_mode:
        available_dates = store.opportunity_snapshot_dates(limit=60)
        default_date = str(active_snapshot.get("session_date") or available_dates[0])
        selected_date = st.selectbox(
            "Dia",
            available_dates,
            index=available_dates.index(default_date) if default_date in available_dates else 0,
            key="opportunity_snapshot_date",
        )
        day_snapshots = store.opportunity_snapshots(session_date=selected_date, limit=10)
        snapshots_by_slot = _group_snapshots_by_slot(day_snapshots)
        visible_slots = [slot for slot in settings.opportunity_snapshot_times if slot in snapshots_by_slot]
        for slot in snapshots_by_slot:
            if slot not in visible_slots:
                visible_slots.append(slot)
        if not visible_slots:
            st.info("No hay snapshots guardados para el dia seleccionado.")
            return
        default_slot = str(active_snapshot.get("slot_time") or visible_slots[0])
        selected_slot = st.selectbox(
            "Listado horario",
            visible_slots,
            index=visible_slots.index(default_slot) if default_slot in visible_slots else 0,
            key="opportunity_snapshot_slot",
        )
        active_snapshot = snapshots_by_slot[selected_slot]
        opportunities = list(active_snapshot.get("opportunities", []) or [])
        summary = active_snapshot.get("summary", {}) or {}
    else:
        st.caption("Vista temporal no archivada basada en el ultimo estudio tecnico disponible.")

    summary_rows = []
    for candidate in opportunities:
        row = dict(candidate.get("summary_row") or _opportunity_summary_row(candidate))
        ranking_value = row.get("ranking")
        score_value = row.get("puntuacion")
        ranking_text = f"#{int(ranking_value)}" if isinstance(ranking_value, (int, float)) else str(ranking_value or "-")
        score_text = f"{float(score_value):.4f}" if isinstance(score_value, (int, float)) else "-"
        row["ranking"] = f"{ranking_text} | {score_text}"
        row.setdefault("riesgo_entrada", opportunity_entry_risk(candidate)["label"])
        row["estado"] = ((candidate.get("operational_status") or {}).get("label") or "-")
        summary_rows.append(row)

    next_snapshot_run = _next_opportunity_snapshot_run_text(settings)
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    with m1:
        _metric_card("Fecha", summary.get("session_date") or "-")
    with m2:
        _metric_card("Hora listado", summary.get("slot_time") or "-")
    with m3:
        _metric_card("Top oportunidades", summary.get("opportunities_count") if summary.get("opportunities_count") is not None else len(opportunities))
    with m4:
        _metric_card("Accionables", summary.get("actionable_count") if summary.get("actionable_count") is not None else "-")
    with m5:
        best_score = summary.get("best_puntuacion")
        _metric_card("Mejor puntuacion", f"{float(best_score):.4f}" if isinstance(best_score, (int, float)) else "-")
    with m6:
        _metric_card("Siguiente ejecucion", next_snapshot_run)

    st.subheader("Resumen")
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
    st.caption(
        f"Fuente: {active_snapshot.get('report_path') or '-'} | "
        f"as_of {_local_datetime(summary.get('as_of'))} | "
        f"seleccion {summary.get('selection_method') or '-'} | "
        f"{'archivado' if archived_mode else 'no archivado'}"
    )

    if portfolio_error:
        st.caption("Sin cartera Alpaca no se puede calcular sizing/riesgo real; por eso el boton de crear plan queda deshabilitado.")

    for index, candidate in enumerate(opportunities, start=1):
        symbol = str(candidate.get("symbol") or "").upper()
        risk = candidate.get("risk_snapshot") or _opportunity_risk_plan(candidate)
        technical = candidate.get("technical_state", {}) or {}
        status = candidate.get("operational_status") or _opportunity_status(
            candidate,
            portfolio=portfolio,
            pending_plans_by_symbol=pending_plans,
            settings=settings,
            llm_context=(candidate.get("llm_context") or {}),
        )
        llm_context = candidate.get("llm_context", {})
        assessment = candidate.get("assessment") or opportunity_assessment(candidate)
        entry_risk = opportunity_entry_risk(candidate)
        confirmed_patterns = [
            str(item.get("label") or item.get("pattern"))
            for item in (technical.get("chart_patterns", []) or [])
            if isinstance(item, dict)
        ]
        score_value = candidate.get("puntuacion")
        if not isinstance(score_value, (int, float)):
            score_value = _num(candidate.get("selection_score"))
        if not isinstance(score_value, (int, float)):
            score_value = _num(candidate.get("rank_priority_score"))
        title = (
            f"{index}. {symbol} | {assessment['label']} | puntuacion {f'{float(score_value):.4f}' if isinstance(score_value, (int, float)) else '-'}"
            f" | tecnico {candidate.get('score', '-')}"
        )
        with st.expander(title, expanded=index <= 3):
            top_left, top_mid, top_right = st.columns([1.1, 1.2, 0.9])
            with top_left:
                _compact_metric("Lectura", assessment["label"], assessment["summary"], tone=assessment["tone"])
                _compact_metric("Setup", candidate.get("setup_name") or "-", candidate.get("setup_quality") or "-")
                _compact_metric("Estado", status["label"], tone=status["tone"])
            with top_mid:
                _compact_metric("Precio actual", _money(risk.get("current_price")))
                _compact_metric("Entrada / stop / take", f"{_money(risk.get('entry_price'))} / {_money(risk.get('stop_loss'))} / {_money(risk.get('take_profit'))}")
            with top_right:
                _compact_metric("Reward/Risk", risk.get("reward_risk") if risk.get("reward_risk") is not None else "-")
                _compact_metric("Riesgo entrada", entry_risk["label"], entry_risk["reason"], tone="bad" if entry_risk["level"] == "alto" else "neutral")
                _compact_metric("Fuerza relativa 20d", _pct_signed(candidate.get("relative_return_20d")))

            st.markdown(f"**Conclusion:** {assessment['summary']}")
            st.markdown(f"**Por que:** {assessment['reason']}")

            tech_a, tech_b, tech_c, tech_d = st.columns(4)
            with tech_a:
                _compact_metric("RSI", technical.get("rsi_14"))
                _compact_metric("Vol z-score", technical.get("volume_zscore_20"))
            with tech_b:
                _compact_metric("Ret 5d", _pct_signed(technical.get("return_5d")))
                _compact_metric("Ret 20d", _pct_signed(technical.get("return_20d")))
            with tech_c:
                _compact_metric("SMA20", _money(technical.get("sma_20")))
                _compact_metric("SMA50", _money(technical.get("sma_50")))
            with tech_d:
                _compact_metric("SMA200", _money(technical.get("sma_200")))
                _compact_metric("ATR14", _money(technical.get("atr_14")))

            st.markdown(f"**Motivo de no compra automatica:** {status['reason']}")
            st.markdown(
                f"**Contexto LLM:** "
                f"{status['label']} | decision {str(llm_context.get('decision') or '-')} | "
                f"fecha {str(llm_context.get('signal_date') or '-')}"
            )
            if llm_context:
                llm_reason = str(llm_context.get("explanation") or ((llm_context.get("llm_gate") or {}).get("reason")) or "").strip()
                st.markdown(f"**Explicacion LLM:** {llm_reason or 'Sin explicacion guardada.'}")
            st.markdown(f"**Invalidacion:** {risk.get('invalidation') or '-'}")
            st.markdown(f"**Time stop:** {risk.get('time_stop') or '-'}")
            st.markdown(f"**Razones tecnicas:** {'; '.join(candidate.get('reasons', []) or []) or '-'}")
            st.markdown(
                f"**Patrones / velas:** "
                f"{', '.join(confirmed_patterns) if confirmed_patterns else '-'} | "
                f"velas {', '.join(technical.get('candle_patterns', []) or []) or '-'}"
            )
            st.markdown(
                f"**Riesgos detectados:** "
                f"{'breakout_failure_risk' if technical.get('breakout_failure_risk') else 'sin riesgo de fallo de ruptura destacado'}"
            )

            button_disabled = portfolio_error is not None
            if st.button("Crear plan de compra", key=f"create_opportunity_plan_{symbol}_{index}", disabled=button_disabled):
                result = _create_manual_opportunity_plan(
                    candidate=candidate,
                    settings=settings,
                    store=store,
                    portfolio=portfolio,
                )
                if result.get("ok"):
                    plan = (result.get("plan") or {})
                    st.success(
                        "Plan creado: "
                        f"{plan.get('symbol')} | qty {plan.get('qty')} | "
                        f"notional {_money(plan.get('notional'))} | "
                        f"entrada {_money(plan.get('entry_price'))} | "
                        f"stop {_money(plan.get('stop_loss'))} | take {_money(plan.get('take_profit'))}"
                    )
                else:
                    stage = result.get("stage")
                    suffix = f" [{stage}]" if stage else ""
                    st.error(f"No se pudo crear el plan{suffix}: {result.get('reason')}")
                    checks = result.get("checks")
                    if checks:
                        st.json(checks)


def _company_study_iteration_title(signal: dict[str, Any], reason: dict[str, Any]) -> str:
    features = signal.get("features") or {}
    price = _study_price(features)
    price_text = _money(price) if price is not None else "-"
    score = features.get("score")
    rank = features.get("score_rank") or features.get("source_rank") or "-"
    return (
        f"{signal.get('signal_date')} {_local_time(signal.get('created_at'))} | "
        f"{signal.get('source')} | precio {price_text} | score {score if score is not None else '-'} | "
        f"rank {rank} | {reason['label']}"
    )


def _render_company_study_news(news_items: list[dict[str, Any]]) -> None:
    if not news_items:
        st.caption("No hay noticias/sentimiento guardado para esta iteracion o simbolo.")
        return
    latest = news_items[0]
    sentiment = latest.get("sentiment") or {}
    material = latest.get("material_risk") or {}
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _compact_metric("Sentimiento", sentiment.get("sentiment") or "-", tone="bad" if sentiment.get("sentiment") == "negative" else "neutral")
    with c2:
        _compact_metric("Score noticias", sentiment.get("sentiment_score", "-"))
    with c3:
        _compact_metric("Apoya setup", "Si" if sentiment.get("supports_technical_setup") else "No")
    with c4:
        _compact_metric("Riesgo material", "Si" if material.get("material") else material.get("severity") or "No", tone="bad" if material.get("material") else "neutral")
    rows = []
    for news in latest.get("news", []) or []:
        rows.append(
            {
                "fecha": news.get("published_at"),
                "medio": news.get("publisher"),
                "titular": news.get("title"),
                "resumen": _short(news.get("summary"), 180),
                "link": news.get("link"),
            }
        )
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(f"Informe noticias: {latest.get('report_path') or '-'}")


def _render_company_study_iteration(
    signal: dict[str, Any],
    reason: dict[str, Any],
    news_items: list[dict[str, Any]],
    *,
    expanded: bool,
) -> None:
    features = signal.get("features") or {}
    outcome = signal.get("outcome") or {}
    price = _study_price(features)
    entry = _num(features.get("entry_price"))
    stop = _num(features.get("stop_loss"))
    take = _num(features.get("take_profit"))
    title = _company_study_iteration_title(signal, reason)
    with st.expander(title, expanded=expanded):
        meta1, meta2, meta3, meta4, meta5 = st.columns(5)
        with meta1:
            _compact_metric("Precio", _money(price))
        with meta2:
            _compact_metric("Entrada", _money(entry))
        with meta3:
            _compact_metric("Stop / Take", f"{_money(stop)} / {_money(take)}")
        with meta4:
            _compact_metric("Direccion", features.get("direction") or "-")
        with meta5:
            _compact_metric("Decision", reason["label"], _short(reason["reason"], 80), tone=reason["tone"])

        st.markdown(f"**Motivo:** {reason['reason']}")
        if reason["source"] == "order_plans":
            plan_id = str((reason.get("payload") or {}).get("plan_id") or "")
            if plan_id:
                st.caption(f"Plan: {plan_id}")

        tech1, tech2, tech3, tech4 = st.columns(4)
        with tech1:
            _compact_metric("Score", features.get("score"))
            _compact_metric("Setup", features.get("setup_name") or "-", features.get("setup_quality") or "-")
        with tech2:
            _compact_metric("RSI", features.get("rsi_14"))
            _compact_metric("Vol z-score", features.get("volume_zscore_20"))
        with tech3:
            _compact_metric("Ret 5d", _pct_signed(features.get("return_5d")))
            _compact_metric("Ret 20d", _pct_signed(features.get("return_20d")))
        with tech4:
            _compact_metric("Ret 60d", _pct_signed(features.get("return_60d")))
            _compact_metric("Dist SMA20", _pct_signed(features.get("distance_sma20")))

        ma1, ma2, ma3, ma4 = st.columns(4)
        with ma1:
            _compact_metric("SMA20", _money(features.get("sma_20")))
        with ma2:
            _compact_metric("SMA50", _money(features.get("sma_50")))
        with ma3:
            _compact_metric("SMA200", _money(features.get("sma_200")))
        with ma4:
            _compact_metric("MACD diff", features.get("macd_diff"))

        patterns = features.get("chart_patterns") or {}
        pattern_text = patterns.get("labels") if isinstance(patterns, dict) else patterns
        st.markdown(f"**Razones tecnicas:** {'; '.join(features.get('reasons', []) or []) or '-'}")
        st.markdown(f"**Patrones:** {pattern_text or '-'}")
        if outcome:
            st.markdown(
                f"**Resultado posterior:** {_signal_outcome_status(outcome)} | "
                f"ret 5d {_signal_value(outcome.get('return_5d'), pct=True)} | "
                f"MFE 10d {_signal_value(outcome.get('mfe_10d'), pct=True)} | "
                f"MAE 10d {_signal_value(outcome.get('mae_10d'), pct=True)}"
            )

        with st.expander("Noticias y sentimiento", expanded=False):
            _render_company_study_news(news_items)
        with st.expander("Ver JSON bruto", expanded=False):
            st.json({"signal": signal, "decision_reason": reason, "news": news_items})


def page_company_studies() -> None:
    settings = _settings()
    store = _store()
    _page_header("Estudios", "Todas las empresas, sus iteraciones tecnicas, noticias y motivo de compra/no compra.")
    _screen_help(
        "Estudios por empresa",
        (
            "La tabla inicial sale de SQLite y no lee los informes tecnicos completos. "
            "Selecciona una empresa para cargar solo sus iteraciones; las noticias se leen bajo demanda."
        ),
    )
    all_sources = ["intraday_scan", "closed_market_study", "opportunity_snapshot", "manual_scan", "closed_market_study_backfill"]
    c1, c2, c3, c4 = st.columns([0.9, 1.4, 0.9, 1.2])
    with c1:
        since = st.text_input("Desde", DEFAULT_START_DATE, key="company_studies_since")
    with c2:
        selected_sources = st.multiselect("Fuentes", all_sources, default=all_sources[:4], key="company_studies_sources")
    with c3:
        detail_limit = st.slider("Iteraciones detalle", 10, 500, 80, 10)
    with c4:
        search = st.text_input("Buscar simbolo/texto", "", key="company_studies_search")

    signals = _company_study_signal_rows(
        store,
        since_date=since,
        sources=selected_sources,
        limit=200000,
    )
    if search.strip():
        needle = search.strip().upper()
        signals = [
            item
            for item in signals
            if needle in str(item.get("symbol") or "").upper()
            or needle in " ".join(str(x) for x in (item.get("features") or {}).get("reasons", [])).upper()
        ]
    if not signals:
        st.info("No hay estudios para los filtros seleccionados.")
        return

    summary_rows = _company_study_symbol_summary(signals)
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        _metric_card("Empresas", len(summary_rows))
    with m2:
        _metric_card("Iteraciones", len(signals))
    with m3:
        _metric_card("Fuentes", len({item.get("source") for item in signals}))
    with m4:
        _metric_card("Ultima fecha", summary_rows[0].get("ultima_fecha") if summary_rows else "-")

    st.subheader("Empresas")
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    global_filters = {
        "since_date": since,
        "sources": selected_sources,
        "search": search,
        "signal_rows_loaded": len(signals),
    }
    if st.checkbox("Preparar descarga global de todas las empresas", value=False, key="company_studies_prepare_global_export"):
        with st.spinner("Preparando JSON global para deepresearch..."):
            global_context = _company_study_decision_context(store, signals)
            global_news_by_symbol = _company_study_news_by_symbol(settings.data_dir / "reports")
            global_payload = _company_study_global_export_payload(
                signals=signals,
                context=global_context,
                news_by_symbol=global_news_by_symbol,
                filters=global_filters,
            )
        st.download_button(
            "Descargar informe completo global JSON",
            data=_json(global_payload),
            file_name=f"estudios_todas_empresas_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
            use_container_width=True,
        )

    symbols = [row["simbolo"] for row in summary_rows]
    selected_symbol = st.selectbox("Empresa", symbols, key="company_studies_symbol")
    symbol_signals = _company_study_signal_rows(
        store,
        since_date=since,
        sources=selected_sources,
        symbol=selected_symbol,
        limit=detail_limit,
    )
    if not symbol_signals:
        st.info("No hay iteraciones para la empresa seleccionada.")
        return
    context = _company_study_decision_context(store, symbol_signals)
    approved_count = 0
    blocked_count = 0
    reasons_by_signal = []
    for sig in symbol_signals:
        reason = _company_study_reason(
            sig,
            context["learning_by_signal"],
            context["recommendations_by_cycle_symbol"],
            context["plans_by_cycle_symbol"],
        )
        reasons_by_signal.append(reason)
        if reason["tone"] == "good":
            approved_count += 1
        if reason["tone"] == "bad":
            blocked_count += 1

    latest_features = symbol_signals[0].get("features") or {}
    d1, d2, d3, d4, d5 = st.columns(5)
    with d1:
        _compact_metric("Empresa", selected_symbol)
    with d2:
        _compact_metric("Iteraciones cargadas", len(symbol_signals))
    with d3:
        _compact_metric("Compras/aprobadas", approved_count, tone="good" if approved_count else "neutral")
    with d4:
        _compact_metric("Bloqueos", blocked_count, tone="bad" if blocked_count else "neutral")
    with d5:
        _compact_metric("Ultimo precio", _money(_study_price(latest_features)))

    symbol_news = _company_study_news_for_symbol(settings.data_dir / "reports", selected_symbol)
    export_payload = _company_study_export_payload(
        symbol=selected_symbol,
        signals=symbol_signals,
        reasons=reasons_by_signal,
        symbol_news=symbol_news,
        filters={
            "since_date": since,
            "sources": selected_sources,
            "detail_limit": detail_limit,
            "search": search,
            "scope": "single_company",
        },
    )
    st.download_button(
        "Descargar informe completo JSON",
        data=_json(export_payload),
        file_name=f"estudios_{selected_symbol}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json",
        mime="application/json",
        use_container_width=True,
    )

    st.subheader("Iteraciones")
    for index, (sig, reason) in enumerate(zip(symbol_signals, reasons_by_signal), start=1):
        run_id = str(sig.get("source_run_id") or "")
        news_items = [item for item in symbol_news if str(item.get("run_id") or "") == run_id]
        if not news_items:
            news_items = symbol_news[:1]
        _render_company_study_iteration(sig, reason, news_items[:3], expanded=index == 1)


def page_signals() -> None:
    settings = _settings()
    store = _store()
    _page_header("Senales", "Candidatos, decisiones, puertas de calidad, resultado posterior y razon del LLM.")
    c1, c2, c3 = st.columns([1.0, 1.0, 1.25])
    with c1:
        limit = st.slider("Senales a cargar", 50, 10000, 2000, 50)
    with c2:
        since = st.text_input("Desde", DEFAULT_START_DATE)
    with c3:
        view_mode = st.selectbox(
            "Vista",
            ["Ultima por simbolo", "Solo decisiones relevantes", "Todas las senales"],
            index=0,
        )
    signals = store.signal_outcomes(limit=limit, since_date=since)
    if not signals:
        st.info("Todavia no hay senales registradas.")
        return
    if st.button("Actualizar resultados posteriores"):
        with st.spinner("Actualizando outcomes con precios posteriores..."):
            result = update_signal_outcomes(settings, store, since_date=since)
        st.success(f"Actualizadas {result.get('updated', 0)} senales de {result.get('signals', 0)}.")
        if result.get("warnings"):
            st.warning(result["warnings"])
        signals = store.signal_outcomes(limit=limit, since_date=since)

    all_sources = sorted({str(item.get("source") or "unknown") for item in signals})
    all_decisions = sorted({str(item.get("decision") or "unknown") for item in signals})
    f1, f2 = st.columns(2)
    with f1:
        selected_sources = st.multiselect("Fuentes", all_sources, default=all_sources)
    with f2:
        selected_decisions = st.multiselect("Decisiones", all_decisions, default=all_decisions)

    filtered = [
        item
        for item in signals
        if str(item.get("source") or "unknown") in selected_sources
        and str(item.get("decision") or "unknown") in selected_decisions
    ]
    if view_mode == "Ultima por simbolo":
        visible = _latest_signal_per_symbol(filtered)
    elif view_mode == "Solo decisiones relevantes":
        visible = [
            item
            for item in filtered
            if item.get("decision") not in {"candidate"}
            or item.get("source") not in {"intraday_scan", "closed_market_study"}
        ]
    else:
        visible = filtered

    pending = sum(1 for item in visible if _signal_outcome_status(item.get("outcome") or {}).startswith("pendiente"))
    with_data = sum(1 for item in visible if (item.get("outcome") or {}).get("available") is True)
    llm_rows = sum(1 for item in visible if ((item.get("gate") or {}).get("llm") or {}).get("reason"))
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        _metric_card("Mostradas", len(visible))
    with m2:
        _metric_card("Simbolos", len({item.get("symbol") for item in visible}))
    with m3:
        _metric_card("Con resultado", with_data)
    with m4:
        _metric_card("Con LLM", llm_rows)

    if pending or len(visible) != len(filtered):
        st.caption(
            "Nota: las senales intradia son candidatos tecnicos repetidos por cada escaneo. "
            "La vista recomendada muestra solo la ultima por simbolo; los retornos futuros quedan pendientes hasta tener barras posteriores."
        )

    if not visible:
        st.info("No hay senales para los filtros seleccionados.")
        return

    df = _signals_dataframe(visible)
    st.dataframe(df, use_container_width=True, hide_index=True)

    selected = st.selectbox(
        "Detalle de senal",
        [
            f"{item['signal_date']} { _local_time(item.get('created_at')) } | {item['symbol']} | {item['decision']} | {item.get('source')}"
            for item in visible
        ],
    )
    if selected:
        labels = [
            f"{item['signal_date']} { _local_time(item.get('created_at')) } | {item['symbol']} | {item['decision']} | {item.get('source')}"
            for item in visible
        ]
        index = labels.index(selected)
        st.json(visible[index])


def page_breakouts() -> None:
    settings = _settings()
    _page_header("Rupturas", "Rupturas confirmadas o inminentes de resistencia, con filtro conservador de riesgo.")
    _screen_help(
        "Rupturas",
        (
            "Esta pantalla no ejecuta compras. Muestra el ultimo escaneo de resistencias 20/55 sesiones. "
            "`confirmed_breakout` significa cierre sobre resistencia; `watch_breakout` significa que el precio "
            "esta cerca pero aun no confirma. Una ruptura solo se marca operable si no esta demasiado extendida, "
            "tiene riesgo acotado y volumen suficiente."
        ),
    )
    latest_path = settings.data_dir / "reports" / "latest_breakout_scan.json"
    if not latest_path.exists():
        st.info("Todavia no hay escaneo de rupturas. Ejecuta breakout-scan o espera al siguiente ciclo de mercado.")
        st.code(r".\.venv\Scripts\python.exe -m agente_bolsa.main breakout-scan")
        return
    try:
        report = json.loads(latest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        st.error(f"No se pudo leer el ultimo escaneo de rupturas: {exc}")
        return

    alerts = report.get("alerts", []) or []
    confirmed = report.get("confirmed", []) or []
    watch = report.get("watch", []) or []
    tradable = [item for item in confirmed if item.get("tradable")]
    blocked = report.get("blocked_or_failed", []) or []
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _metric_card("Confirmadas", len(confirmed))
    with c2:
        _metric_card("Operables", len(tradable))
    with c3:
        _metric_card("Vigilancia", len(watch))
    with c4:
        _metric_card("Bloqueadas/fallidas", len(blocked))
    st.caption(
        f"Ultimo escaneo: {_local_datetime(report.get('as_of'))} | "
        f"simbolos con datos {report.get('symbols_with_data', 0)}/{report.get('symbols_scanned', 0)}"
    )

    if st.button("Lanzar escaneo ahora"):
        with st.spinner("Ejecutando breakout-scan..."):
            code, output = _run_command(["breakout-scan"], timeout=180)
        if code == 0:
            st.success("Escaneo completado.")
            st.code(output)
            st.rerun()
        else:
            st.error("El escaneo fallo.")
            st.code(output)

    if not alerts:
        st.info("No hay rupturas ni precios suficientemente cerca de resistencia en el ultimo escaneo.")
        return

    rows = []
    for item in alerts:
        rows.append(
            {
                "simbolo": item.get("symbol"),
                "estado": item.get("status"),
                "operable": "si" if item.get("tradable") else "no",
                "riesgo": item.get("risk_level"),
                "cierre": item.get("close"),
                "resistencia": item.get("resistance"),
                "% ruptura": _pct_signed(item.get("breakout_pct")),
                "vol_z": item.get("volume_zscore_20"),
                "RSI": item.get("rsi_14"),
                "dist SMA20": _pct_signed(item.get("sma20_distance")),
                "stop": item.get("stop_loss"),
                "take": item.get("take_profit"),
                "plan": item.get("entry_style"),
                "motivos": "; ".join(item.get("reasons", []) or []),
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def page_learning() -> None:
    settings = _settings()
    store = _store()
    _page_header("Aprendizaje", "Que indicadores estan ayudando, cuales fallan y como se actualizan outcomes.")
    since = st.text_input("Desde", DEFAULT_START_DATE, key="learning_since")
    if st.button("Actualizar resultados de senales"):
        with st.spinner("Actualizando outcomes con precios posteriores..."):
            result = update_signal_outcomes(settings, store, since_date=since)
        st.success(f"Actualizadas {result.get('updated', 0)} senales de {result.get('signals', 0)}.")
        if result.get("warnings"):
            st.warning(result["warnings"])

    report = build_learning_status(store, since_date=since)
    digest = _latest_learning_digest()
    c1, c2, c3 = st.columns(3)
    with c1:
        _metric_card("Senales", report.get("signals", 0))
    with c2:
        _metric_card("Decisiones", len(report.get("decisions", {})))
    with c3:
        resolved = sum(v for k, v in report.get("verdicts", {}).items() if k != "pending")
        _metric_card("Resueltas", resolved)

    left, right = st.columns(2)
    with left:
        st.subheader("Decisiones")
        st.dataframe(pd.DataFrame(report.get("decisions", {}).items(), columns=["decision", "count"]), hide_index=True)
    with right:
        st.subheader("Veredictos")
        st.dataframe(pd.DataFrame(report.get("verdicts", {}).items(), columns=["veredicto", "count"]), hide_index=True)

    st.subheader("Indicadores que mejor funcionan")
    st.dataframe(pd.DataFrame(report.get("best_indicators", [])), use_container_width=True, hide_index=True)
    st.subheader("Indicadores que peor funcionan")
    st.dataframe(pd.DataFrame(report.get("worst_indicators", [])), use_container_width=True, hide_index=True)

    st.markdown("")
    _section_title("Aprendizaje diario reciente", "Sin cambiar de pantalla: edge por setup, calibracion de confianza y error de estimacion.")
    s1, s2, s3, s4 = st.columns(4)
    summary = (digest or {}).get("summary", {}) or {}
    with s1:
        _metric_card("Canonicas", summary.get("canonical_observations", 0))
    with s2:
        _metric_card("Ejecutadas", summary.get("executed_observations", 0))
    with s3:
        _metric_card("Duplicadas", _pct(summary.get("duplicate_ratio")))
    with s4:
        _metric_card("Cobertura 3d", (summary.get("horizon_coverage", {}) or {}).get("3d", 0))

    top_row = st.columns(3)
    with top_row[0]:
        st.caption("Setup edge 3d")
        _bar_chart((digest or {}).get("setup_stats_3d", [])[:6], "setup", "avg_return")
    with top_row[1]:
        st.caption("Confianza reciente")
        _bar_chart((digest or {}).get("confidence_calibration_3d", []), "bucket", "avg_return")
    with top_row[2]:
        st.caption("Error de estimacion")
        _bar_chart((digest or {}).get("prior_accuracy_3d", [])[:6], "profile_key", "avg_abs_error")

    lower_left, lower_mid, lower_right = st.columns(3)
    with lower_left:
        st.subheader("Perfiles con mejor expectativa")
        st.dataframe(
            pd.DataFrame((digest or {}).get("setup_priors_3d", [])[:8]),
            use_container_width=True,
            hide_index=True,
        )
    with lower_mid:
        st.subheader("Memoria por ticker/setup")
        st.dataframe(
            pd.DataFrame((digest or {}).get("symbol_setup_memory_3d", [])[:10]),
            use_container_width=True,
            hide_index=True,
        )
    with lower_right:
        st.subheader("Guidance activo")
        guidance = (digest or {}).get("guidance", []) or []
        if guidance:
            for item in guidance[:6]:
                st.markdown(f"- {item}")
        else:
            st.info("Todavia no hay guidance diario.")


def page_adaptive() -> None:
    settings = _settings()
    store = _store()
    _page_header("Autoaprendizaje adaptativo", "Propuestas de parametros en shadow mode, overrides activos y evidencia.")
    if st.button("Generar ajuste adaptativo"):
        result = update_adaptive_config(settings, store, since_date=DEFAULT_START_DATE)
        changed = ", ".join(result.get("changed", [])) or "sin cambios"
        st.success(f"Ajuste generado: {changed}")

    status = adaptive_status(settings)
    c1, c2, c3 = st.columns(3)
    with c1:
        _metric_card("Archivo existe", "si" if status.get("exists") else "no")
    with c2:
        _metric_card("Overrides activos", len(status.get("active_overrides", {})))
    with c3:
        _metric_card("Ultimo ajuste", (status.get("last_tuning") or {}).get("as_of", "-"))

    st.subheader("Parametros")
    st.dataframe(pd.DataFrame(status.get("parameters", [])), use_container_width=True, hide_index=True)
    st.subheader("Overrides activos")
    st.json(status.get("active_overrides", {}))
    with st.expander("Estado completo"):
        st.json(status)


def page_operational_learning() -> None:
    settings = _settings()
    store = _store()
    _page_header(
        "Aprendizaje operativo",
        "Memoria de operaciones, reglas en shadow mode y aprendizaje que modifica el razonamiento del LLM.",
    )
    col_a, col_b = st.columns([1, 1])
    with col_a:
        if st.button("Actualizar aprendizaje operativo"):
            with st.spinner("Sincronizando memoria y evaluando reglas shadow..."):
                report = build_operational_learning_review(
                    settings,
                    store,
                    settings.data_dir / "reports",
                    "web",
                    since_date=DEFAULT_START_DATE,
                    use_llm=False,
                )
            st.success(f"Actualizado. Memorias: {report['summary'].get('trade_memories', 0)}")
    with col_b:
        if st.button("Actualizar con LLM"):
            with st.spinner("Pidiendo revision LLM y reglas candidatas..."):
                report = build_operational_learning_review(
                    settings,
                    store,
                    settings.data_dir / "reports",
                    "web_llm",
                    since_date=DEFAULT_START_DATE,
                    use_llm=True,
                )
            st.success(f"Revision LLM guardada. Reglas nuevas: {len(report.get('llm_rules_created', []))}")

    latest_path = settings.data_dir / "reports" / "latest_operational_learning.json"
    latest = {}
    if latest_path.exists():
        try:
            latest = json.loads(latest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            st.warning("latest_operational_learning.json no es JSON valido.")

    rules = store.strategy_rules(limit=300)
    memories = store.trade_memory(limit=200, since_date=DEFAULT_START_DATE)
    active = [rule for rule in rules if rule.get("status") == "active"]
    shadow = [rule for rule in rules if rule.get("status") == "shadow"]
    rejected = [rule for rule in rules if rule.get("status") == "rejected"]
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        _metric_card("Memorias", len(memories))
    with m2:
        _metric_card("Activas", len(active))
    with m3:
        _metric_card("Shadow", len(shadow))
    with m4:
        _metric_card("Rechazadas", len(rejected))

    st.subheader("Reglas")
    if rules:
        rows = []
        for rule in rules:
            metrics = rule.get("metrics", {}) or {}
            rows.append(
                {
                    "estado": rule.get("status"),
                    "regla": rule.get("rule_id"),
                    "nombre": rule.get("name"),
                    "efecto": rule.get("effect"),
                    "casos": metrics.get("cases", 0),
                    "net_shadow_pl": metrics.get("net_shadow_pl", 0),
                    "hit_rate": metrics.get("hit_rate"),
                    "descripcion": rule.get("description"),
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("Todavia no hay reglas. Pulsa actualizar aprendizaje operativo.")

    st.subheader("Memoria reciente")
    if memories:
        rows = []
        for item in memories[:80]:
            thesis = item.get("thesis", {}) or {}
            features = item.get("features", {}) or {}
            rows.append(
                {
                    "fecha": _local_datetime(item.get("trade_time"), settings.local_timezone),
                    "simbolo": item.get("symbol"),
                    "lado": item.get("side"),
                    "notional": item.get("notional"),
                    "veredicto": item.get("verdict"),
                    "P/L": (item.get("outcome") or {}).get("pl"),
                    "score": features.get("score"),
                    "rsi": features.get("rsi_14"),
                    "dist_sma20": features.get("distance_sma20"),
                    "vol_z": features.get("volume_zscore_20"),
                    "motivo": _short(thesis.get("reason"), 120),
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("Todavia no hay memoria operativa.")

    if latest.get("llm_review"):
        st.subheader("Ultima opinion LLM")
        st.json(latest["llm_review"])
    with st.expander("Informe operativo completo"):
        st.json(latest or {"available": False})


def _local_date(value: Any, timezone_name: str | None = None) -> str | None:
    parsed = _local_dt(value, timezone_name)
    return parsed.date().isoformat() if parsed else None


def _learning_diary_dates(
    memories: list[dict[str, Any]],
    evaluations: list[dict[str, Any]],
    rules: list[dict[str, Any]],
) -> list[str]:
    dates = {
        date
        for date in [
            *[_local_date(item.get("trade_time")) for item in memories],
            *[_local_date(item.get("created_at")) for item in evaluations],
            *[_local_date(item.get("updated_at")) for item in rules],
        ]
        if date
    }
    today = datetime.now(ZoneInfo(_settings().local_timezone)).date().isoformat()
    dates.add(today)
    return sorted(dates, reverse=True)


def _learning_diary_bullets(
    *,
    selected_date: str,
    day_memories: list[dict[str, Any]],
    day_evaluations: list[dict[str, Any]],
    day_rules: list[dict[str, Any]],
    latest: dict[str, Any],
) -> list[str]:
    bullets = []
    if day_memories:
        winners = sum(1 for item in day_memories if str(item.get("verdict", "")).startswith("winner"))
        losers = sum(1 for item in day_memories if str(item.get("verdict", "")).startswith("loser"))
        pending = sum(1 for item in day_memories if item.get("verdict") == "pending")
        bullets.append(
            f"Se revisaron {len(day_memories)} memorias de operaciones del dia: "
            f"{winners} ganadoras, {losers} perdedoras y {pending} pendientes."
        )
    else:
        bullets.append("No hay nuevas memorias de operaciones para este dia; si no hubo fills nuevos, es normal.")
    if day_evaluations:
        would_block = sum(1 for item in day_evaluations if item.get("would_block"))
        avoided = sum(_num(item.get("avoided_loss")) or 0.0 for item in day_evaluations)
        missed = sum(_num(item.get("missed_gain")) or 0.0 for item in day_evaluations)
        bullets.append(
            f"Se evaluaron {len(day_evaluations)} casos de reglas shadow; "
            f"{would_block} habrian bloqueado operaciones. Impacto shadow neto: {_money(avoided - missed)}."
        )
    else:
        bullets.append("No se registraron nuevas evaluaciones shadow en esta fecha.")
    if day_rules:
        statuses = {}
        for rule in day_rules:
            statuses[rule.get("status")] = statuses.get(rule.get("status"), 0) + 1
        status_text = ", ".join(f"{key}: {value}" for key, value in sorted(statuses.items()))
        bullets.append(f"Reglas actualizadas en el dia: {len(day_rules)} ({status_text}).")
    else:
        bullets.append("No hubo cambios de estado ni recalculo de reglas ese dia.")
    if latest.get("as_of"):
        bullets.append(f"Ultimo informe operativo disponible: {_local_datetime(latest.get('as_of'))}.")
    if selected_date == datetime.now(ZoneInfo(_settings().local_timezone)).date().isoformat() and not day_memories:
        bullets.append("Hoy puede seguir aprendiendo al cierre o al pulsar actualizar, pero necesita nuevas operaciones o P/L actualizado.")
    return bullets


def page_learning_diary() -> None:
    settings = _settings()
    store = _store()
    _page_header("Diario de aprendizaje", "Resumen diario de lo que el sistema aprendio y que podria cambiar.")
    _screen_help(
        "Diario de aprendizaje",
        """
Esta pantalla esta pensada para revisarla una vez al dia.

Como interpretarla:
- **Memorias** son operaciones paper/fills enriquecidos con tesis, indicadores y resultado.
- **Reglas shadow** son reglas que el sistema prueba sin aplicarlas todavia.
- **Impacto shadow** estima si una regla habria evitado perdidas o bloqueado ganancias.
- Si no hay datos de hoy, normalmente significa que no hubo nuevas operaciones o que aun no se ejecuto la revision.
- Una regla solo deberia activarse cuando acumula evidencia suficiente; mientras tanto queda en `shadow`.
        """,
    )

    latest_path = settings.data_dir / "reports" / "latest_operational_learning.json"
    latest = {}
    if latest_path.exists():
        try:
            latest = json.loads(latest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            st.warning("latest_operational_learning.json no es JSON valido.")

    memories = store.trade_memory(limit=5000, since_date=DEFAULT_START_DATE)
    rules = store.strategy_rules(limit=500)
    evaluations = store.rule_evaluations(limit=5000)
    dates = _learning_diary_dates(memories, evaluations, rules)

    col_date, col_action = st.columns([1, 1])
    with col_date:
        selected_date = st.selectbox("Fecha", dates, index=0 if dates else None)
    with col_action:
        if st.button("Actualizar aprendizaje operativo ahora"):
            with st.spinner("Sincronizando memoria y evaluando reglas..."):
                latest = build_operational_learning_review(
                    settings,
                    store,
                    settings.data_dir / "reports",
                    "web_diary",
                    since_date=DEFAULT_START_DATE,
                    use_llm=False,
                )
            memories = store.trade_memory(limit=5000, since_date=DEFAULT_START_DATE)
            rules = store.strategy_rules(limit=500)
            evaluations = store.rule_evaluations(limit=5000)
            st.success("Diario actualizado.")

    if not dates:
        st.info("Todavia no hay datos de aprendizaje operativo.")
        return

    day_memories = [item for item in memories if _local_date(item.get("trade_time"), settings.local_timezone) == selected_date]
    day_evaluations = [
        item for item in evaluations if _local_date(item.get("created_at"), settings.local_timezone) == selected_date
    ]
    day_rules = [item for item in rules if _local_date(item.get("updated_at"), settings.local_timezone) == selected_date]
    active = [rule for rule in rules if rule.get("status") == "active"]
    shadow = [rule for rule in rules if rule.get("status") == "shadow"]
    rejected = [rule for rule in rules if rule.get("status") == "rejected"]

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        _metric_card("Memorias del dia", len(day_memories))
    with m2:
        _metric_card("Eval. shadow", len(day_evaluations))
    with m3:
        _metric_card("Reglas shadow", len(shadow))
    with m4:
        _metric_card("Activas/Rechazadas", f"{len(active)}/{len(rejected)}")

    st.subheader("Aprendido en la fecha")
    for bullet in _learning_diary_bullets(
        selected_date=selected_date,
        day_memories=day_memories,
        day_evaluations=day_evaluations,
        day_rules=day_rules,
        latest=latest,
    ):
        st.markdown(f"- {bullet}")

    st.subheader("Cambios o reglas observadas")
    if day_rules:
        rows = []
        for rule in day_rules:
            metrics = rule.get("metrics", {}) or {}
            rows.append(
                {
                    "estado": rule.get("status"),
                    "regla": rule.get("name"),
                    "efecto": rule.get("effect"),
                    "casos": metrics.get("cases"),
                    "net_shadow_pl": metrics.get("net_shadow_pl"),
                    "hit_rate": metrics.get("hit_rate"),
                    "descripcion": rule.get("description"),
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No se actualizaron reglas en esta fecha.")

    st.subheader("Operaciones usadas para aprender")
    if day_memories:
        rows = []
        for item in day_memories:
            thesis = item.get("thesis", {}) or {}
            features = item.get("features", {}) or {}
            rows.append(
                {
                    "hora": _local_time(item.get("trade_time"), settings.local_timezone),
                    "simbolo": item.get("symbol"),
                    "lado": item.get("side"),
                    "notional": item.get("notional"),
                    "veredicto": item.get("verdict"),
                    "P/L": (item.get("outcome") or {}).get("pl"),
                    "score": features.get("score"),
                    "rsi": features.get("rsi_14"),
                    "vol_z": features.get("volume_zscore_20"),
                    "motivo": _short(thesis.get("reason"), 160),
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No hay operaciones nuevas en memoria para la fecha seleccionada.")

    st.subheader("Evaluaciones shadow del dia")
    if day_evaluations:
        rows = []
        for item in day_evaluations:
            rows.append(
                {
                    "hora": _local_time(item.get("created_at"), settings.local_timezone),
                    "regla": item.get("rule_id"),
                    "simbolo": item.get("symbol"),
                    "bloquearia": item.get("would_block"),
                    "resultado_real": item.get("actual_outcome"),
                    "evita_perdida": item.get("avoided_loss"),
                    "pierde_ganancia": item.get("missed_gain"),
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No hubo evaluaciones shadow registradas ese dia.")

    with st.expander("Ultimo informe operativo completo"):
        st.json(latest or {"available": False})


def page_backtest() -> None:
    settings = _settings()
    _page_header("Backtest", "Prueba historica de la regla tecnica actual con stop, take, costes y slippage.")
    with st.form("backtest_form"):
        col1, col2, col3, col4, col5 = st.columns(5)
        symbol = col1.text_input("Simbolo", "AAPL").upper()
        start = col2.text_input("Desde", "2024-01-01")
        min_score = col3.number_input("Score minimo", min_value=1, max_value=30, value=7)
        max_holding = col4.number_input("Max dias", min_value=1, max_value=60, value=10)
        setup_name = col5.selectbox(
            "Setup",
            ["todos", "trend_volume", "orderly_breakout", "event_momentum", "momentum_confirmation", "momentum_shakeout_hold", "range_expansion_breakout"],
        )
        submitted = st.form_submit_button("Ejecutar backtest")
    if submitted:
        with st.spinner(f"Ejecutando backtest de {symbol}..."):
            result = build_symbol_backtest(
                symbol=symbol,
                output_dir=settings.data_dir / "reports",
                run_id="web",
                start=start,
                min_score=int(min_score),
                max_holding_days=int(max_holding),
                allowed_setup_names=None if setup_name == "todos" else {setup_name},
            )
        metrics = result.get("metrics", {})
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        with c1:
            _metric_card("Trades", metrics.get("trades"))
        with c2:
            _metric_card("P/L", _pct(metrics.get("total_return")))
        with c3:
            _metric_card("Hit rate", _pct(metrics.get("hit_rate")))
        with c4:
            _metric_card("Sharpe", metrics.get("sharpe"))
        with c5:
            _metric_card("Sortino", metrics.get("sortino"))
        with c6:
            _metric_card("Calmar", metrics.get("calmar"))
        d1, d2, d3 = st.columns(3)
        with d1:
            _metric_card("Expectancy", _money(metrics.get("expectancy_per_trade")))
        with d2:
            _metric_card("Turnover", _pct(metrics.get("turnover")))
        with d3:
            _metric_card("Exposure time", _pct(metrics.get("exposure_time_pct")))
        st.json(metrics)
        trades = pd.DataFrame(result.get("trades", []))
        if not trades.empty:
            st.dataframe(trades, use_container_width=True, hide_index=True)


def _pre_earnings_history_panel(events: list[dict[str, Any]]) -> None:
    if not events:
        return

    def tone_for(hypothesis: str) -> tuple[str, str]:
        if hypothesis == "subida_probable":
            return "green", "alcista fuerte"
        if hypothesis == "neutral_alcista":
            return "blue", "sesgo positivo"
        return "gray", "sin ventaja"

    for event in events:
        item = event["item"]
        history = event["history"]
        rows = history.get("rows", []) or []
        if not rows:
            continue
        symbol = str(item.get("symbol") or "")
        earnings_date = str(item.get("earnings_date") or item.get("session_date") or "")
        earnings_session = str(item.get("earnings_session") or "")
        official_id = history.get("official_prediction_id")
        official = next((row for row in rows if row.get("prediction_id") == official_id), rows[-1])
        first = rows[0]
        change = float(official.get("score") or 0) - float(first.get("score") or 0)
        change_text = f"+{change:.0f}" if change > 0 else f"{change:.0f}"
        first_hypothesis = history.get("first_hypothesis") or first.get("hypothesis")
        official_hypothesis = history.get("official_hypothesis") or official.get("hypothesis")
        headline = (
            f"{first_hypothesis} sin cambio"
            if first_hypothesis == official_hypothesis
            else f"{first_hypothesis} -> {official_hypothesis}"
        )

        with st.container(border=True):
            h1, h2, h3 = st.columns([1.2, 2, 1])
            with h1:
                st.markdown(f"**{symbol}**")
                st.caption(f"{earnings_date} · {earnings_session}")
            with h2:
                st.caption("Evolución")
                st.markdown(f"`{headline}`")
            with h3:
                st.metric("Cambio score", change_text)

            if len(rows) > 5:
                st.caption("Mostrando las últimas 5 estimaciones.")
                visible_rows = rows[-5:]
            else:
                visible_rows = rows
            cols = st.columns(max(min(len(visible_rows), 5), 1))

            previous_score = None
            for col, row in zip(cols, visible_rows, strict=False):
                hypothesis = str(row.get("hypothesis") or "")
                score = float(row.get("score") or 0)
                max_score = int(row.get("max_score") or 0)
                diff_text = ""
                if previous_score is not None:
                    diff = score - previous_score
                    if diff:
                        sign = "+" if diff > 0 else ""
                        diff_text = f" ({sign}{diff:.0f})"
                previous_score = score
                tone, label = tone_for(hypothesis)
                official_text = " · oficial" if row.get("prediction_id") == official_id else ""
                reason = str(row.get("reason") or "Sin motivo registrado.")
                short_reason = reason if len(reason) <= 180 else f"{reason[:177]}..."
                with col:
                    with st.container(border=True):
                        st.caption(f"{row.get('prediction_date')}{official_text}")
                        st.markdown(f"**{hypothesis}**")
                        st.metric("Score", f"{score:.0f}/{max_score}", diff_text or None)
                        st.caption(label)
                        st.caption(f"Motivo: {short_reason}")


def _score_percent(score: Any, max_score: Any) -> float | None:
    try:
        score_value = float(score)
        max_value = float(max_score)
    except (TypeError, ValueError):
        return None
    if max_value <= 0:
        return None
    return score_value / max_value


def _pre_earnings_event_key(item: dict[str, Any]) -> str:
    return "|".join(
        [
            str(item.get("symbol") or "").upper(),
            str(item.get("earnings_date") or item.get("session_date") or "")[:10],
            str(item.get("earnings_session") or "post-market"),
        ]
    )


def _pre_earnings_score_text(score: Any, max_score: Any) -> str:
    try:
        return f"{int(float(score or 0))}/{int(float(max_score or 0))}"
    except (TypeError, ValueError):
        return "sin datos"


def _pre_earnings_prediction_line(row: dict[str, Any]) -> str:
    features = row.get("features") or {}
    v2 = features.get("pre_earnings_score_v2")
    v2_label = features.get("score_v2_label")
    v2_text = f" | v2 {v2_label} {float(v2):.1f}/100" if v2 is not None and v2_label else ""
    return (
        f"{str(row.get('prediction_date') or '-')}: "
        f"{row.get('hypothesis') or 'sin_datos'} "
        f"{_pre_earnings_score_text(row.get('score'), row.get('max_score'))}"
        f"{v2_text}"
    )


def _pre_earnings_official_from_history(
    item: dict[str, Any],
    history: dict[str, Any],
) -> dict[str, Any]:
    rows = history.get("rows", []) or []
    official_id = history.get("official_prediction_id")
    official = next((row for row in rows if row.get("prediction_id") == official_id), None)
    if official:
        return official
    return {
        "prediction_date": item.get("estimated_on") or item.get("session_date"),
        "hypothesis": item.get("hypothesis"),
        "score": item.get("score"),
        "max_score": item.get("max_score"),
        "reason": item.get("reason"),
        "outcome": item.get("outcome") or {},
        "features": {
            "pre_earnings_score_v2": item.get("pre_earnings_score_v2"),
            "score_v2_label": item.get("score_v2_label"),
            "high_conviction_pre_earnings_long": item.get("high_conviction_pre_earnings_long"),
            "high_conviction_pre_earnings_reason": item.get("high_conviction_pre_earnings_reason"),
            "score_v2_components": item.get("score_v2_components"),
            "score_v2_drivers": item.get("score_v2_drivers"),
        },
    }


def _pre_earnings_result_label(hypothesis: Any, return_pct: Any, confidence_pct: Any) -> str:
    if return_pct is None:
        return "pendiente"
    try:
        if confidence_pct is None or float(confidence_pct) < PRE_EARNINGS_CONFIDENCE_THRESHOLD:
            return "azar"
    except (TypeError, ValueError):
        return "azar"
    if hypothesis not in {"subida_probable", "neutral_alcista"}:
        return "no era alcista"
    try:
        return "acierto" if float(return_pct) > 0 else "fallo"
    except (TypeError, ValueError):
        return "pendiente"


def _pre_earnings_event_groups(store: Store) -> dict[str, list[dict[str, Any]]]:
    predictions = store.pre_earnings_predictions(limit=5000)
    by_event: dict[str, list[dict[str, Any]]] = {}
    for prediction in predictions:
        features = prediction.get("features") or {}
        key = "|".join(
            [
                str(prediction.get("symbol") or "").upper(),
                str(features.get("earnings_date") or prediction.get("earnings_datetime") or "")[:10],
                str(features.get("earnings_session") or "post-market"),
            ]
        )
        by_event.setdefault(key, []).append(prediction)
    for event_rows in by_event.values():
        event_rows.sort(key=lambda row: (str(row.get("prediction_date") or ""), str(row.get("created_at") or "")))
    return by_event


def _pre_earnings_confident_metrics(store: Store) -> dict[str, Any]:
    resolved_count = 0
    confident_count = 0
    hits = 0
    misses = 0
    random_count = 0
    for event_rows in _pre_earnings_event_groups(store).values():
        resolved = [row for row in event_rows if (row.get("outcome") or {}).get("return_pct") is not None]
        if not resolved:
            continue
        official = resolved[-1]
        outcome = official.get("outcome") or {}
        result = _pre_earnings_result_label(
            official.get("hypothesis"),
            outcome.get("return_pct"),
            _score_percent(official.get("score"), official.get("max_score")),
        )
        resolved_count += 1
        if result == "acierto":
            hits += 1
            confident_count += 1
        elif result == "fallo":
            misses += 1
            confident_count += 1
        elif result == "azar":
            random_count += 1
    success_rate = (hits / confident_count) if confident_count else None
    return {
        "resolved_count": resolved_count,
        "confident_count": confident_count,
        "success_rate": success_rate,
        "hits": hits,
        "misses": misses,
        "random_count": random_count,
    }


def _pre_earnings_next_day_block(
    sessions: list[dict[str, Any]],
    estimation_history: dict[str, dict[str, Any]],
) -> None:
    if not sessions:
        return
    session = sessions[0]
    session_date = str(session.get("session_date") or "-")
    rows = []
    details: list[dict[str, Any]] = []
    for item in session.get("items", []) or []:
        event_key = _pre_earnings_event_key(item)
        history = estimation_history.get(event_key, {})
        official = _pre_earnings_official_from_history(item, history)
        score = official.get("score")
        max_score = official.get("max_score")
        pct = _score_percent(score, max_score)
        official_features = official.get("features") or {}
        v2_score = official_features.get("pre_earnings_score_v2") or item.get("pre_earnings_score_v2")
        v2_label = official_features.get("score_v2_label") or item.get("score_v2_label")
        timeline_rows = history.get("rows", []) or [official]
        outcome = item.get("outcome", {}) or official.get("outcome", {}) or {}
        result_text = _pre_earnings_result_label(official.get("hypothesis"), outcome.get("return_pct"), pct)
        rows.append(
            {
                "simbolo": item.get("symbol"),
                "earnings": (
                    f"{item.get('earnings_date') or item.get('session_date')} "
                    f"{item.get('earnings_session') or 'post-market'} "
                    f"{item.get('earnings_time') or str(item.get('earnings_datetime') or '')[11:16]}"
                ),
                "estimaciones diarias": " -> ".join(_pre_earnings_prediction_line(row) for row in timeline_rows),
                "valor final": official.get("hypothesis"),
                "score final": _pre_earnings_score_text(score, max_score),
                "% final": pct,
                "valor v2": v2_label,
                "score v2": v2_score,
                "fecha final": official.get("prediction_date"),
                "resultado": result_text,
            }
        )
        details.append({"item": item, "history": history, "official": official, "timeline_rows": timeline_rows})

    st.subheader(f"1. Siguiente dia de earnings ({session_date})")
    st.caption("Incluye los resultados de hoy post-market y los de la siguiente sesion pre-market.")
    if not rows:
        st.info("No hay earnings detectados para el siguiente dia de estimacion.")
        return

    frame = pd.DataFrame(rows)

    def color_estimation(value: float | None) -> str:
        if value is None:
            return ""
        color = "#047857" if value >= 0.8 else "#b45309" if value >= 0.5 else "#b91c1c"
        background = "#ecfdf5" if value >= 0.8 else "#fffbeb" if value >= 0.5 else "#fef2f2"
        return f"color: {color}; background-color: {background}; font-weight: 700;"

    styled = (
        frame.style.format(
            {
                "% final": lambda value: "sin datos" if pd.isna(value) else f"{value:.1%}",
                "score v2": lambda value: "sin datos" if pd.isna(value) else f"{value:.1f}/100",
            }
        )
        .map(color_estimation, subset=["% final"])
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)

    with st.expander("Ver estimaciones diarias por simbolo", expanded=False):
        for detail in details:
            item = detail["item"]
            symbol = str(item.get("symbol") or "")
            st.markdown(f"**{symbol}**")
            timeline = []
            official_id = (detail.get("history") or {}).get("official_prediction_id")
            for row in detail["timeline_rows"]:
                pct = _score_percent(row.get("score"), row.get("max_score"))
                timeline.append(
                    {
                        "fecha estimacion": row.get("prediction_date"),
                        "hipotesis": row.get("hypothesis"),
                        "score": _pre_earnings_score_text(row.get("score"), row.get("max_score")),
                        "%": pct,
                        "valor v2": (row.get("features") or {}).get("score_v2_label"),
                        "score v2": (row.get("features") or {}).get("pre_earnings_score_v2"),
                        "final": "si" if row.get("prediction_id") == official_id else "",
                        "motivo": row.get("reason") or item.get("reason"),
                    }
                )
            st.dataframe(
                pd.DataFrame(timeline).style.format(
                    {
                        "%": lambda value: "sin datos" if pd.isna(value) else f"{value:.1%}",
                        "score v2": lambda value: "sin datos" if pd.isna(value) else f"{value:.1f}/100",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )


def _pre_earnings_previous_events_block(store: Store) -> None:
    rows_by_date: dict[str, list[dict[str, Any]]] = {}
    details_by_date: dict[str, list[dict[str, Any]]] = {}
    for key, event_rows in _pre_earnings_event_groups(store).items():
        resolved = [row for row in event_rows if (row.get("outcome") or {}).get("return_pct") is not None]
        if not resolved:
            continue
        official = resolved[-1]
        features = official.get("features") or {}
        outcome = official.get("outcome") or {}
        return_pct = outcome.get("return_pct")
        score_pct = _score_percent(official.get("score"), official.get("max_score"))
        result_text = _pre_earnings_result_label(official.get("hypothesis"), return_pct, score_pct)
        timeline = " -> ".join(_pre_earnings_prediction_line(row) for row in event_rows)
        earnings_date = str(features.get("earnings_date") or str(official.get("earnings_datetime") or "")[:10])
        row = {
            "simbolo": official.get("symbol"),
            "sesion": features.get("earnings_session") or "post-market",
            "evolucion": timeline,
            "valor final": official.get("hypothesis"),
            "score final": _pre_earnings_score_text(official.get("score"), official.get("max_score")),
            "% final": score_pct,
            "fecha final": official.get("prediction_date"),
            "resultado real": _pct_signed(return_pct),
            "evaluacion": result_text,
        }
        detail = {"key": key, "rows": event_rows, "official": official, "outcome": outcome}
        rows_by_date.setdefault(earnings_date, []).append(row)
        details_by_date.setdefault(earnings_date, []).append(detail)

    st.subheader("2. Earnings anteriores: evolucion, final y resultado real")
    if not rows_by_date:
        st.info("Todavia no hay earnings anteriores resueltos con predicciones guardadas.")
        return

    def color_result(value: str) -> str:
        if value == "acierto":
            return "color: #047857; background-color: #ecfdf5; font-weight: 700;"
        if value == "fallo":
            return "color: #b91c1c; background-color: #fef2f2; font-weight: 700;"
        if value == "azar":
            return "color: #92400e; background-color: #fffbeb; font-weight: 700;"
        return "color: #6b7280; background-color: #f9fafb;"

    for earnings_date in sorted(rows_by_date.keys(), reverse=True):
        date_rows = sorted(
            rows_by_date[earnings_date],
            key=lambda item: (
                -float(item.get("% final") or 0),
                str(item.get("simbolo") or ""),
            ),
        )
        with st.expander(f"{earnings_date} ({len(date_rows)} simbolos)", expanded=False):
            frame = pd.DataFrame(date_rows)
            styled = (
                frame.style.format({"% final": lambda value: "sin datos" if pd.isna(value) else f"{value:.1%}"})
                .map(color_result, subset=["evaluacion"])
            )
            st.dataframe(styled, use_container_width=True, hide_index=True)

            with st.expander("Detalle de predicciones de este dia", expanded=False):
                for detail in details_by_date.get(earnings_date, [])[:50]:
                    official = detail["official"]
                    st.markdown(f"**{official.get('symbol')}**")
                    rows_detail = []
                    official_id = official.get("prediction_id")
                    for row in detail["rows"]:
                        rows_detail.append(
                            {
                                "fecha estimacion": row.get("prediction_date"),
                                "hipotesis": row.get("hypothesis"),
                                "score": _pre_earnings_score_text(row.get("score"), row.get("max_score")),
                                "%": _score_percent(row.get("score"), row.get("max_score")),
                                "final": "si" if row.get("prediction_id") == official_id else "",
                                "motivo": row.get("reason"),
                            }
                        )
                    st.dataframe(
                        pd.DataFrame(rows_detail).style.format(
                            {"%": lambda value: "sin datos" if pd.isna(value) else f"{value:.1%}"}
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )


def _pre_earnings_previous_events_block_old(store: Store) -> None:
    predictions = store.pre_earnings_predictions(limit=5000)
    by_event: dict[str, list[dict[str, Any]]] = {}
    for prediction in predictions:
        features = prediction.get("features") or {}
        key = "|".join(
            [
                str(prediction.get("symbol") or "").upper(),
                str(features.get("earnings_date") or prediction.get("earnings_datetime") or "")[:10],
                str(features.get("earnings_session") or "post-market"),
            ]
        )
        by_event.setdefault(key, []).append(prediction)

    rows = []
    details = []
    for key, event_rows in by_event.items():
        event_rows.sort(key=lambda row: (str(row.get("prediction_date") or ""), str(row.get("created_at") or "")))
        resolved = [row for row in event_rows if (row.get("outcome") or {}).get("return_pct") is not None]
        if not resolved:
            continue
        official = resolved[-1]
        features = official.get("features") or {}
        outcome = official.get("outcome") or {}
        return_pct = outcome.get("return_pct")
        score_pct = _score_percent(official.get("score"), official.get("max_score"))
        result_text = _pre_earnings_result_label(official.get("hypothesis"), return_pct, score_pct)
        timeline = " -> ".join(_pre_earnings_prediction_line(row) for row in event_rows)
        rows.append(
            {
                "simbolo": official.get("symbol"),
                "earnings": (
                    f"{features.get('earnings_date') or str(official.get('earnings_datetime') or '')[:10]} "
                    f"{features.get('earnings_session') or 'post-market'}"
                ),
                "evolucion": timeline,
                "valor final": official.get("hypothesis"),
                "score final": _pre_earnings_score_text(official.get("score"), official.get("max_score")),
                "% final": score_pct,
                "fecha final": official.get("prediction_date"),
                "resultado real": _pct_signed(return_pct),
                "evaluacion": result_text,
            }
        )
        details.append({"key": key, "rows": event_rows, "official": official, "outcome": outcome})

    st.subheader("2. Earnings anteriores: evolucion, final y resultado real")
    if not rows:
        st.info("Todavia no hay earnings anteriores resueltos con predicciones guardadas.")
        return

    frame = pd.DataFrame(rows).sort_values(["earnings", "simbolo"], ascending=[False, True])

    def color_result(value: str) -> str:
        if value == "acierto":
            return "color: #047857; background-color: #ecfdf5; font-weight: 700;"
        if value == "fallo":
            return "color: #b91c1c; background-color: #fef2f2; font-weight: 700;"
        if value == "azar":
            return "color: #92400e; background-color: #fffbeb; font-weight: 700;"
        return "color: #6b7280; background-color: #f9fafb;"

    styled = (
        frame.style.format({"% final": lambda value: "sin datos" if pd.isna(value) else f"{value:.1%}"})
        .map(color_result, subset=["evaluacion"])
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)

    with st.expander("Ver detalle de predicciones anteriores", expanded=False):
        for detail in details[:50]:
            official = detail["official"]
            st.markdown(f"**{official.get('symbol')}**")
            rows_detail = []
            official_id = official.get("prediction_id")
            for row in detail["rows"]:
                rows_detail.append(
                    {
                        "fecha estimacion": row.get("prediction_date"),
                        "hipotesis": row.get("hypothesis"),
                        "score": _pre_earnings_score_text(row.get("score"), row.get("max_score")),
                        "%": _score_percent(row.get("score"), row.get("max_score")),
                        "final": "si" if row.get("prediction_id") == official_id else "",
                        "motivo": row.get("reason"),
                    }
                )
            st.dataframe(
                pd.DataFrame(rows_detail).style.format(
                    {"%": lambda value: "sin datos" if pd.isna(value) else f"{value:.1%}"}
                ),
                use_container_width=True,
                hide_index=True,
            )


def _pre_earnings_next_day_block_old(
    sessions: list[dict[str, Any]],
    estimation_history: dict[str, dict[str, Any]],
) -> None:
    if not sessions:
        return
    session = sessions[0]
    session_date = str(session.get("session_date") or "-")
    rows = []
    for item in session.get("items", []) or []:
        event_key = _pre_earnings_event_key(item)
        history = estimation_history.get(event_key, {})
        score = history.get("official_score", item.get("score"))
        max_score = history.get("official_max_score", item.get("max_score"))
        pct = _score_percent(score, max_score)
        rows.append(
            {
                "simbolo": item.get("symbol"),
                "fecha earnings": item.get("earnings_date") or item.get("session_date"),
                "sesion": item.get("earnings_session") or "post-market",
                "hora": item.get("earnings_time") or str(item.get("earnings_datetime") or "")[11:16],
                "hipotesis": history.get("official_hypothesis") or item.get("hypothesis"),
                "score": f"{int(float(score or 0))}/{int(float(max_score or 0))}",
                "% estimacion": pct,
                "estado": ">= 80%" if pct is not None and pct >= 0.8 else "< 80%",
            }
        )

    st.subheader(f"Earnings próximo día ({session_date})")
    if not rows:
        st.info("No hay earnings detectados para el próximo día de estimación.")
        return

    frame = pd.DataFrame(rows)

    def color_estimation(value: float | None) -> str:
        if value is None:
            return ""
        color = "#047857" if value >= 0.8 else "#b91c1c"
        background = "#ecfdf5" if value >= 0.8 else "#fef2f2"
        return f"color: {color}; background-color: {background}; font-weight: 700;"

    styled = frame.style.format({"% estimacion": lambda value: "sin datos" if pd.isna(value) else f"{value:.1%}"}).map(
        color_estimation,
        subset=["% estimacion"],
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


def _pre_earnings_target_session(settings: Any) -> str:
    calendar = MarketCalendar(settings.market_calendar, settings.local_timezone)
    return target_after_close_session(calendar).isoformat()


def _is_stale_pre_earnings_report(report: dict[str, Any], settings: Any) -> bool:
    session_date = str(report.get("session_date") or "")
    if not session_date:
        return True
    return session_date < _pre_earnings_target_session(settings)


def _latest_pre_earnings_report(settings: Any) -> dict[str, Any] | None:
    files = sorted(
        [
            path
            for path in (settings.data_dir / "reports").glob("pre_earnings_*.json")
            if not path.name.startswith("pre_earnings_event_study_")
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not files:
        return None
    try:
        report = json.loads(files[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    report["path"] = str(files[0])
    return report


def _format_pre_earnings_dt(value: str | None, settings: Any) -> str:
    if not value:
        return "sin datos"
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(settings.local_timezone))
    return parsed.astimezone(ZoneInfo(settings.local_timezone)).strftime("%Y-%m-%d %H:%M")


def _next_pre_earnings_run_text(settings: Any) -> str:
    calendar = MarketCalendar(settings.market_calendar, settings.local_timezone)
    now_utc = datetime.now(ZoneInfo("UTC"))
    minutes = int(settings.pre_earnings_before_close_minutes)
    calendar_obj = getattr(calendar, "_calendar", None)
    if calendar_obj is not None:
        start = now_utc.astimezone(calendar.market_tz).date().isoformat()
        end = (now_utc.astimezone(calendar.market_tz).date() + pd.Timedelta(days=14)).isoformat()
        schedule = calendar_obj.schedule(start_date=start, end_date=end)
        for _, row in schedule.iterrows():
            close_utc = row["market_close"].to_pydatetime().astimezone(ZoneInfo("UTC"))
            run_utc = close_utc - pd.Timedelta(minutes=minutes)
            if run_utc > now_utc:
                return run_utc.astimezone(ZoneInfo(settings.local_timezone)).strftime("%Y-%m-%d %H:%M")

    status = calendar.status()
    close_raw = status.market_close or status.next_close
    if not close_raw:
        return "sin proxima sesion"
    try:
        close_dt = datetime.fromisoformat(close_raw)
    except ValueError:
        return "sin datos"
    run_dt = close_dt - pd.Timedelta(minutes=minutes)
    return run_dt.astimezone(ZoneInfo(settings.local_timezone)).strftime("%Y-%m-%d %H:%M")


def _pre_earnings_top_summary(settings: Any) -> None:
    latest = _latest_pre_earnings_report(settings)
    next_run = _next_pre_earnings_run_text(settings)
    col1, col2 = st.columns(2)
    with col1:
        if latest:
            summary = latest.get("summary", {}) or {}
            st.metric(
                "Ultimo analisis pre-earnings",
                _format_pre_earnings_dt(latest.get("as_of"), settings),
                f"Sesion {latest.get('session_date') or '-'} | {summary.get('total_events', latest.get('events_found', 0))} eventos",
            )
            st.caption(f"Archivo: {latest.get('path')}")
        else:
            st.metric("Ultimo analisis pre-earnings", "sin informe")
            st.caption("Se creara automaticamente cuando llegue la ventana programada.")
    with col2:
        st.metric(
            "Siguiente analisis automatico",
            next_run,
            f"{settings.pre_earnings_before_close_minutes} min antes del cierre NYSE",
        )
        st.caption("El scheduler lo ejecuta una vez por sesion si esta activo.")


def _pre_earnings_resolved_history_block(store: Store) -> None:
    rows = []
    for item in build_pre_earnings_resolved_history(store, limit=5000)[:100]:
        rows.append(
            {
                "simbolo": item.get("symbol"),
                "fecha earnings": item.get("earnings_date"),
                "sesion": item.get("earnings_session"),
                "fecha oficial": item.get("official_prediction_date"),
                "hipotesis": item.get("hypothesis"),
                "% estimacion": item.get("score_pct"),
                "resultado": item.get("status"),
                "% subida real": item.get("return_pct"),
                "estimaciones": item.get("predictions_count"),
            }
        )

    st.subheader("Histórico evaluado")
    if not rows:
        st.info("Todavía no hay earnings ya resueltos que hubieran sido evaluados previamente.")
        return

    frame = pd.DataFrame(rows)

    def color_result(value: str) -> str:
        if value == "acierto":
            return "color: #047857; background-color: #ecfdf5; font-weight: 700;"
        if value == "fallo":
            return "color: #b91c1c; background-color: #fef2f2; font-weight: 700;"
        return "color: #6b7280; background-color: #f9fafb;"

    def color_return(value: float | None) -> str:
        if value is None or pd.isna(value):
            return ""
        color = "#047857" if value > 0 else "#b91c1c"
        background = "#ecfdf5" if value > 0 else "#fef2f2"
        return f"color: {color}; background-color: {background}; font-weight: 700;"

    styled = (
        frame.style.format(
            {
                "% estimacion": lambda value: "sin datos" if pd.isna(value) else f"{value:.1%}",
                "% subida real": lambda value: "sin datos" if pd.isna(value) else f"{value:+.2%}",
            }
        )
        .map(color_result, subset=["resultado"])
        .map(color_return, subset=["% subida real"])
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


def _pre_earnings_score_v2_block(settings: Any, store: Store) -> None:
    with st.expander("Estudio Score V2", expanded=False):
        st.caption(
            "Analiza las predicciones pre-earnings guardadas, subidas >5%, falsos positivos y score V2. "
            "No usa informacion posterior para puntuar eventos futuros."
        )
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            since = st.text_input("Desde prediccion", "", key="pre_earnings_score_since")
        with c2:
            limit = st.number_input(
                "Limite predicciones",
                min_value=100,
                max_value=50000,
                value=10000,
                step=100,
                key="pre_earnings_score_limit",
            )
        with c3:
            run_score = st.button("Calcular Score V2", key="pre_earnings_score_run")
        if not run_score:
            st.info("Ejecuta el estudio para ver captura de subidas >5%, falsos positivos y score V2 diario.")
            return

        with st.spinner("Calculando estudio Score V2..."):
            study = build_pre_earnings_score_study(
                store,
                settings.data_dir / "reports",
                f"web-score-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
                since_date=since.strip() or None,
                limit=int(limit),
            )

        metrics = study.get("metrics", {}) or {}
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        with m1:
            _metric_card("Eventos resueltos", metrics.get("resolved_events", 0))
        with m2:
            _metric_card("Subidas >5%", metrics.get("big_winners_gt_5", 0))
        with m3:
            rate = metrics.get("legacy_big_winner_capture_rate")
            _metric_card("Captura antigua", _pct(rate) if rate is not None else "sin datos")
        with m4:
            rate = metrics.get("v2_big_winner_capture_rate")
            _metric_card("Captura V2", _pct(rate) if rate is not None else "sin datos")
        with m5:
            rate = metrics.get("v2_false_positive_rate")
            _metric_card("FP V2", _pct(rate) if rate is not None else "sin datos")
        with m6:
            rate = metrics.get("v2_high_conviction_capture_rate")
            _metric_card("Alta conviccion", _pct(rate) if rate is not None else "sin datos")
        st.caption(f"Informe: {study.get('path')}")

        winners = study.get("big_winners", []) or []
        if winners:
            rows = [
                {
                    "simbolo": item.get("symbol"),
                    "fecha earnings": item.get("earnings_date"),
                    "retorno": item.get("return_pct"),
                    "valor antiguo": item.get("legacy_hypothesis"),
                    "score antiguo": item.get("legacy_score_pct"),
                    "valor v2": item.get("final_label_v2"),
                    "score v2": item.get("final_score_v2"),
                    "alta conviccion": item.get("high_conviction_pre_earnings_long"),
                    "accionable": item.get("actionable_pre_earnings_long"),
                    "fallo/acierto": item.get("classification"),
                    "diagnostico": item.get("failure_analysis"),
                }
                for item in winners
            ]
            frame = pd.DataFrame(rows)
            st.dataframe(
                frame.style.format(
                    {
                        "retorno": lambda value: "sin datos" if pd.isna(value) else f"{value:+.2%}",
                        "score antiguo": lambda value: "sin datos" if pd.isna(value) else f"{value:.1f}",
                        "score v2": lambda value: "sin datos" if pd.isna(value) else f"{value:.1f}",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )
        false_positive = study.get("false_positive_bullish", []) or []
        blocked_big_winners = study.get("blocked_big_winners", []) or []
        if blocked_big_winners:
            with st.expander("Ganadores fuertes vetados por actionable"):
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "simbolo": item.get("symbol"),
                                "fecha earnings": item.get("earnings_date"),
                                "retorno": item.get("return_pct"),
                                "valor v2": item.get("final_label_v2"),
                                "score v2": item.get("final_score_v2"),
                                "motivo veto": item.get("actionable_pre_earnings_reason"),
                                "diagnostico": item.get("failure_analysis"),
                            }
                            for item in blocked_big_winners
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
        if false_positive:
            with st.expander("Falsos positivos alcistas"):
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "simbolo": item.get("symbol"),
                                "fecha earnings": item.get("earnings_date"),
                                "retorno": item.get("return_pct"),
                                "valor antiguo": item.get("legacy_hypothesis"),
                                "valor v2": item.get("final_label_v2"),
                                "score v2": item.get("final_score_v2"),
                                "diagnostico": item.get("failure_analysis"),
                            }
                            for item in false_positive
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )


def _build_and_store_pre_earnings_report(
    settings: Any,
    store: Store,
    universe_name: str,
    max_symbols: int,
    days: int,
) -> dict[str, Any]:
    symbols = resolve_study_universe(
        universe_name,
        settings.universe,
        int(max_symbols),
        settings.data_dir / "cache",
    )
    report = build_pre_earnings_report(
        symbols=symbols,
        output_dir=settings.data_dir / "reports",
        run_id=f"web-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        calendar_name=settings.market_calendar,
        local_timezone=settings.local_timezone,
        session_count=int(days),
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
    build_learning_digest_report(store, settings.data_dir / "reports", f"{report['run_id']}_learn_refresh")
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
    return report


def page_pre_earnings() -> None:
    settings = _settings()
    store = _store()
    tracking_update = update_pre_earnings_outcomes(store)
    _page_header(
        "Pre-earnings",
        "Acciones que presentan resultados en el proximo cierre de mercado. Solo informativo, sin compras.",
    )
    _screen_help(
        "Pre-earnings",
        (
            "Esta pantalla es solo informativa: no compra, no crea planes y no envia ordenes.\n\n"
            "**Controles**\n\n"
            "- `Universo`: grupo de simbolos a revisar, por ejemplo `sp500_top300`, `default` o `AAPL,MSFT,NVDA`.\n"
            "- `Max simbolos`: limite de empresas consultadas.\n"
            "- `Dias`: cuantos dias futuros se calculan, aunque la vista principal muestra el siguiente.\n"
            "- `Actualizar`: recalcula el informe.\n\n"
            "**1. Siguiente dia de earnings**\n\n"
            "Muestra una fila por simbolo. Junta los earnings de hoy `post-market` y los de la siguiente sesion "
            "`pre-market`, porque ambos se pueden valorar con la informacion disponible antes del cierre. "
            "`estimaciones diarias` muestra todas las valoraciones guardadas para ese mismo earnings. "
            "`valor final` es la ultima valoracion guardada antes de la publicacion.\n\n"
            "**2. Earnings anteriores**\n\n"
            "Muestra eventos ya resueltos. Para cada simbolo se ve la evolucion de la prediccion, el valor final, "
            "el retorno real tras el earnings y la evaluacion. Solo cuenta como acierto o fallo si el valor final "
            "supero el 80%; por debajo se marca como azar."
        ),
    )
    st.warning("Este apartado no genera recomendaciones operativas, planes de orden ni compras paper/live.")
    _pre_earnings_top_summary(settings)
    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
    with col1:
        universe_name = st.text_input(
            "Universo",
            settings.pre_earnings_universe or settings.closed_market_study_universe,
        )
    with col2:
        max_symbols = st.number_input(
            "Max simbolos",
            min_value=1,
            max_value=505,
            value=int(settings.pre_earnings_max_symbols or settings.closed_market_study_max_symbols),
        )
    with col3:
        days = st.number_input("Dias", min_value=1, max_value=15, value=int(settings.pre_earnings_days))
    with col4:
        run = st.button("Actualizar")

    latest_files = sorted(
        [
            path
            for path in (settings.data_dir / "reports").glob("pre_earnings_*.json")
            if not path.name.startswith("pre_earnings_event_study_")
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    report: dict[str, Any] | None = None
    if run:
        with st.spinner("Buscando earnings AMC y calculando hipotesis..."):
            report = _build_and_store_pre_earnings_report(
                settings,
                store,
                universe_name,
                int(max_symbols),
                int(days),
            )
        st.success("Informe actualizado.")
    elif latest_files:
        try:
            report = json.loads(latest_files[0].read_text(encoding="utf-8"))
            report["path"] = str(latest_files[0])
            if _is_stale_pre_earnings_report(report, settings):
                with st.spinner("El informe pre-earnings estaba caducado. Recalculando automaticamente..."):
                    report = _build_and_store_pre_earnings_report(
                        settings,
                        store,
                        universe_name,
                        int(max_symbols),
                        int(days),
                    )
                st.info("Informe pre-earnings recalculado automaticamente.")
        except (OSError, json.JSONDecodeError):
            report = None

    if not report:
        with st.spinner("No habia informe pre-earnings disponible. Creandolo automaticamente..."):
            report = _build_and_store_pre_earnings_report(
                settings,
                store,
                universe_name,
                int(max_symbols),
                int(days),
            )
        st.info("Informe pre-earnings creado automaticamente.")

    summary = report.get("summary", {}) or {}
    total_events = summary.get("total_events", report.get("events_found", 0))
    tracking = build_pre_earnings_tracking_status(store)
    confident_metrics = _pre_earnings_confident_metrics(store)
    success_rate = confident_metrics.get("success_rate")
    success_value = _pct(success_rate) if success_rate is not None else "sin datos"
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    trading_operation = report.get("trading_operation", {}) or {}
    with c1:
        _metric_card("Exito >=80%", success_value)
    with c2:
        _metric_card("Aciertos >=80%", confident_metrics.get("hits", 0))
    with c3:
        _metric_card("Fallos >=80%", confident_metrics.get("misses", 0))
    with c4:
        _metric_card("Azar <80%", confident_metrics.get("random_count", 0))
    with c5:
        _metric_card("Eventos", total_events)
    with c6:
        operable = "SI" if report.get("operation_allowed") else "NO"
        if report.get("operation_allowed"):
            operable = f"SI ({len(trading_operation.get('buy_order_plans', []))})"
        _metric_card("Operable", operable)
    st.caption(f"Informe: {report.get('path')}")
    if report.get("operation_allowed"):
        st.caption(
            "Operacion pre-earnings activa: "
            f"recomendaciones {len(trading_operation.get('recommendations', []))} | "
            f"planes buy {len(trading_operation.get('buy_order_plans', []))} | "
            f"enviadas {len(trading_operation.get('submitted', []))}"
        )
    quality = report.get("data_quality", {}) or {}
    if quality:
        st.caption(
            "Datos: "
            f"fuente {quality.get('calendar_source')} | "
            f"cache {quality.get('cache_hits', 0)} | "
            f"consultas {quality.get('yfinance_calls', 0)} | "
            f"errores {quality.get('calendar_errors', 0)}"
        )
        if quality.get("analyst_source") != "none":
            st.caption(
                "Analistas: "
                f"fuente {quality.get('analyst_source')} | "
                f"cache {quality.get('analyst_cache_hits', 0)} | "
                f"consultas {quality.get('analyst_calls', 0)} | "
                f"errores {quality.get('analyst_errors', 0)}"
    )
    if tracking.get("total_predictions"):
        st.caption(
            "Seguimiento persistente: "
            f"hipotesis guardadas {tracking.get('total_predictions', 0)} | "
            f"resueltas {tracking.get('resolved_count', 0)} | "
            f"pendientes {tracking.get('pending_count', 0)} | "
            f"evaluables >=80% {confident_metrics.get('confident_count', 0)} | "
            f"azar <80% {confident_metrics.get('random_count', 0)} | "
            f"exito >=80% {success_value} | "
            f"actualizadas ahora {tracking_update.get('updated', 0)}"
        )

    sessions = report.get("sessions") or [
        {
            "session_date": report.get("session_date"),
            "events_found": report.get("events_found", 0),
            "items": report.get("items", []) or [],
        }
    ]
    estimation_history = build_pre_earnings_estimation_history(store, report)
    _pre_earnings_next_day_block(sessions, estimation_history)
    _pre_earnings_previous_events_block(store)
    _pre_earnings_score_v2_block(settings, store)
    if report.get("warnings"):
        with st.expander("Avisos"):
            st.json(report["warnings"])

    with st.expander("Event-study historico"):
        st.caption("Analisis historico de hipotesis pre-earnings AMC. Sirve para validar scoring, no para ejecutar compras pasadas.")
        b1, b2, b3, b4 = st.columns([1, 2, 1, 1])
        with b1:
            start = st.text_input("Desde", "2025-01-01", key="pre_earnings_backtest_start")
        with b2:
            bt_universe = st.text_input("Universo backtest", universe_name, key="pre_earnings_backtest_universe")
        with b3:
            bt_max_symbols = st.number_input(
                "Max backtest",
                min_value=1,
                max_value=505,
                value=int(max_symbols),
                key="pre_earnings_backtest_max",
            )
        with b4:
            run_backtest = st.button("Medir", key="pre_earnings_backtest_run")
        if run_backtest:
            symbols = resolve_study_universe(
                bt_universe,
                settings.universe,
                int(bt_max_symbols),
                settings.data_dir / "cache",
            )
            with st.spinner("Ejecutando event-study pre-earnings..."):
                study = build_pre_earnings_event_study(
                    symbols=symbols,
                    output_dir=settings.data_dir / "reports",
                    run_id=f"web-bt-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
                    start=start,
                    calendar_name=settings.market_calendar,
                    local_timezone=settings.local_timezone,
                    cache_dir=settings.data_dir / "cache",
                    fmp_api_key=settings.fmp_api_key,
                )
            metrics = study.get("metrics", {}) or {}
            m1, m2, m3, m4, m5 = st.columns(5)
            with m1:
                _metric_card("Eventos hist.", metrics.get("events", 0))
            with m2:
                _metric_card("Resueltos", metrics.get("resolved", 0))
            with m3:
                rate = metrics.get("success_rate")
                _metric_card("Exito alcista", _pct(rate) if rate is not None else "sin datos")
            with m4:
                avg = metrics.get("avg_return")
                _metric_card("Ret medio", _pct_signed(avg) if avg is not None else "sin datos")
            with m5:
                bull_avg = metrics.get("bullish_avg_return")
                _metric_card("Ret alcista", _pct_signed(bull_avg) if bull_avg is not None else "sin datos")
            st.caption(f"Informe: {study.get('path')}")
            by_hypothesis = metrics.get("by_hypothesis", {}) or {}
            if by_hypothesis:
                rows = [{"hipotesis": name, **values} for name, values in by_hypothesis.items()]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                st.info("No hay eventos historicos resueltos para ese filtro.")


def _cycle_summaries(store: Store, *, since_date: str, limit: int) -> list[dict[str, Any]]:
    since_dt = f"{since_date}T00:00:00"
    with store.connect() as conn:
        cycle_rows = conn.execute(
            """
            SELECT cycle_id, MIN(created_at) AS started_at, MAX(created_at) AS ended_at, COUNT(*) AS events
            FROM agent_events
            WHERE cycle_id LIKE '20%' AND created_at >= ?
            GROUP BY cycle_id
            ORDER BY ended_at DESC
            LIMIT ?
            """,
            (since_dt, limit),
        ).fetchall()
        cycles = [dict(row) for row in cycle_rows]
        for cycle in cycles:
            cycle_id = cycle["cycle_id"]
            event_rows = conn.execute(
                """
                SELECT agent, event_type, payload_json, created_at
                FROM agent_events
                WHERE cycle_id = ?
                ORDER BY created_at
                """,
                (cycle_id,),
            ).fetchall()
            rec_rows = conn.execute(
                """
                SELECT symbol, action, confidence, payload_json, created_at
                FROM trade_recommendations
                WHERE cycle_id = ?
                ORDER BY created_at DESC
                """,
                (cycle_id,),
            ).fetchall()
            plan_rows = conn.execute(
                """
                SELECT plan_id, symbol, side, notional, approved, dry_run, payload_json, created_at
                FROM order_plans
                WHERE cycle_id = ?
                ORDER BY created_at DESC
                """,
                (cycle_id,),
            ).fetchall()
            order_rows = conn.execute(
                """
                SELECT broker_order_id, plan_id, symbol, side, status, payload_json, created_at
                FROM broker_orders
                WHERE cycle_id = ?
                ORDER BY created_at DESC
                """,
                (cycle_id,),
            ).fetchall()
            cycle["events"] = [dict(row) for row in event_rows]
            cycle["recommendations"] = [dict(row) for row in rec_rows]
            cycle["plans"] = [dict(row) for row in plan_rows]
            cycle["orders"] = [dict(row) for row in order_rows]
    return cycles


def _cycle_event_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"universe": None, "scan": None, "final": None, "auto": None}
    for event in events:
        payload = _load_json_cell(event.get("payload_json"))
        message = payload.get("message") or payload.get("result") or ""
        task = payload.get("task") or payload.get("title") or payload.get("name") or ""
        text = str(message or task)
        if "Universo:" in text:
            summary["universe"] = text.split("Universo:", 1)[-1].strip()
        if "Escaneo tecnico listo" in text or "Candidatos intradia" in text:
            summary["scan"] = text
        if task in {"Ordenes paper", "Compra/Venta"} or "Ordenes paper" in text or "compra" in text.lower():
            summary["auto"] = text
        if "Ciclo finalizado" in text:
            summary["final"] = text
    return summary


def _cycle_recommendations_dataframe(recommendations: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for row in recommendations:
        payload = _load_json_cell(row.get("payload_json"))
        rows.append(
            {
                "hora": _local_time(row.get("created_at")),
                "simbolo": row.get("symbol"),
                "accion": row.get("action"),
                "conf": row.get("confidence"),
                "entrada": payload.get("entry_price"),
                "stop": payload.get("stop_loss"),
                "take": payload.get("take_profit"),
                "motivo": payload.get("reason"),
            }
        )
    return pd.DataFrame(rows)


def _cycle_plans_dataframe(plans: list[dict[str, Any]], orders: list[dict[str, Any]]) -> pd.DataFrame:
    sent_by_plan = {row.get("plan_id"): row for row in orders}
    rows = []
    for row in plans:
        payload = _load_json_cell(row.get("payload_json"))
        risk = payload.get("risk_decision") or {}
        recommendation = payload.get("recommendation") or {}
        order = sent_by_plan.get(row.get("plan_id"))
        rows.append(
            {
                "hora": _local_time(row.get("created_at")),
                "simbolo": row.get("symbol"),
                "lado": row.get("side"),
                "notional": row.get("notional"),
                "aprobado": bool(row.get("approved")),
                "dry_run": bool(row.get("dry_run")),
                "enviado": bool(order),
                "estado_orden": order.get("status") if order else "-",
                "riesgo": risk.get("reason"),
                "motivo_llm": recommendation.get("reason"),
            }
        )
    return pd.DataFrame(rows)


def page_cycle_decisions() -> None:
    store = _store()
    _page_header("Decisiones por ciclo", "Por que se compra, se mantiene, se bloquea o no se hace nada en cada iteracion.")
    col1, col2 = st.columns([1, 1])
    with col1:
        since = st.text_input("Desde", DEFAULT_START_DATE, key="cycle_decisions_since")
    with col2:
        limit = st.slider("Ciclos", 5, 100, 25, 5)
    cycles = _cycle_summaries(store, since_date=since, limit=limit)
    if not cycles:
        st.info("No hay ciclos para el filtro seleccionado.")
        return

    overview = []
    for cycle in cycles:
        recommendations = cycle["recommendations"]
        plans = cycle["plans"]
        orders = cycle["orders"]
        actions = ", ".join(
            f"{row['symbol']}:{row['action']}:{float(row['confidence'] or 0):.2f}"
            for row in recommendations[:5]
        )
        overview.append(
            {
                "ciclo": cycle["cycle_id"],
                "inicio": _local_time(cycle["started_at"]),
                "fin": _local_time(cycle["ended_at"]),
                "recomendaciones": len(recommendations),
                "planes": len(plans),
                "ordenes": len(orders),
                "acciones_top": actions or "-",
            }
        )
    st.dataframe(pd.DataFrame(overview), use_container_width=True, hide_index=True)

    labels = [f"{item['cycle_id']} | {_local_datetime(item['ended_at'])}" for item in cycles]
    selected = st.selectbox("Detalle de ciclo", labels)
    cycle = cycles[labels.index(selected)]
    summary = _cycle_event_summary(cycle["events"])

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _metric_card("Recomendaciones", len(cycle["recommendations"]))
    with c2:
        _metric_card("Planes", len(cycle["plans"]))
    with c3:
        _metric_card("Ordenes", len(cycle["orders"]))
    with c4:
        sent = sum(1 for plan in cycle["plans"] if any(order.get("plan_id") == plan.get("plan_id") for order in cycle["orders"]))
        _metric_card("Enviadas", sent)

    if summary.get("scan"):
        st.info(summary["scan"])
    if summary.get("universe"):
        st.caption(f"Universo LLM: {summary['universe']}")
    if summary.get("auto"):
        st.warning(summary["auto"] if "No compra" in summary["auto"] else summary["auto"])

    st.subheader("Recomendaciones LLM / decisión")
    if cycle["recommendations"]:
        st.dataframe(_cycle_recommendations_dataframe(cycle["recommendations"]), use_container_width=True, hide_index=True)
    else:
        st.info("Este ciclo no tiene recomendaciones estructuradas guardadas.")

    st.subheader("Planes, riesgo y envio")
    if cycle["plans"]:
        st.dataframe(_cycle_plans_dataframe(cycle["plans"], cycle["orders"]), use_container_width=True, hide_index=True)
    else:
        st.info("No hubo planes de orden aprobados o pendientes en este ciclo.")

    with st.expander("Eventos del ciclo"):
        st.dataframe(_events_dataframe(cycle["events"]), use_container_width=True, hide_index=True)
    with st.expander("Datos brutos"):
        st.json(cycle)


def _ci_proposals_dataframe(proposals: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for item in proposals:
        payload = item.get("payload") or {}
        rows.append(
            {
                "estado": item.get("status"),
                "tipo": item.get("proposal_type"),
                "riesgo": item.get("risk_level"),
                "componente": item.get("target_component"),
                "objetivo": item.get("target_identifier"),
                "propuesta": _short(payload.get("proposed_value"), 120),
                "motivo": _short(payload.get("rationale"), 160),
                "proposal_id": item.get("proposal_id"),
            }
        )
    return pd.DataFrame(rows)


def _ci_agent_activity(events: list[dict[str, Any]], *, cycle_id: str | None = None, limit: int = 200) -> pd.DataFrame:
    rows = []
    filtered = []
    for item in events:
        current_cycle_id = str(item.get("cycle_id") or "")
        if cycle_id:
            if current_cycle_id != cycle_id:
                continue
        elif not current_cycle_id.startswith("ci_cycle_"):
            continue
        filtered.append(item)
    for item in filtered[:limit]:
        payload = _load_json_cell(item.get("payload_json"))
        rows.append(
            {
                "hora": _local_datetime(item.get("created_at")),
                "agente": item.get("agent"),
                "evento": item.get("event_type"),
                "mensaje": _short(
                    payload.get("summary")
                    or payload.get("message")
                    or payload.get("status")
                    or payload.get("event_type")
                    or payload.get("error")
                    or "",
                    160,
                ),
                "detalle": payload,
            }
        )
    return pd.DataFrame(rows)


def _ci_task_activity(
    events: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    *,
    cycle_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    task_index = {str(item.get("task_id") or ""): item for item in tasks}
    grouped: dict[str, dict[str, Any]] = {}
    seen_order: list[str] = []
    for item in events:
        current_cycle_id = str(item.get("cycle_id") or "")
        if cycle_id and current_cycle_id != cycle_id:
            continue
        if not cycle_id and not current_cycle_id.startswith("ci_cycle_"):
            continue
        payload = _load_json_cell(item.get("payload_json"))
        task_id = str(payload.get("task_id") or "")
        task = task_index.get(task_id, {})
        event_id = str(payload.get("event_id") or task.get("event_id") or "")
        initiative_id = (
            str(payload.get("initiative_id") or "")
            or str((task.get("payload") or {}).get("initiative_id") or "")
            or str((task.get("payload") or {}).get("initiative_key") or "")
            or event_id
            or task_id
            or f"misc:{item.get('event_id')}"
        )
        if initiative_id not in grouped:
            group_label = (
                (task.get("payload") or {}).get("initiative_title")
                or (task.get("payload") or {}).get("focus")
                or payload.get("focus")
                or payload.get("event_type")
                or payload.get("target_component")
                or "actividad"
            )
            grouped[initiative_id] = {
                "initiative_id": initiative_id,
                "initiative_key": (task.get("payload") or {}).get("initiative_key") or payload.get("initiative_key"),
                "initiative_title": (task.get("payload") or {}).get("initiative_title") or payload.get("initiative_title"),
                "task_ids": [],
                "agent_names": [],
                "status": task.get("status") or payload.get("status") or "-",
                "focus": str(group_label),
                "event_id": event_id or "-",
                "event_type": payload.get("event_type") or item.get("event_type") or "-",
                "messages": [],
                "updated_at": item.get("created_at"),
            }
            seen_order.append(initiative_id)
        group = grouped[initiative_id]
        if task_id and task_id not in group["task_ids"]:
            group["task_ids"].append(task_id)
        agent_name = str(task.get("agent_name") or item.get("agent") or "-")
        if agent_name not in group["agent_names"]:
            group["agent_names"].append(agent_name)
        group["status"] = task_index.get(task_id, {}).get("status") or payload.get("status") or group["status"]
        group["updated_at"] = item.get("created_at")
        group["messages"].append(
            {
                "hora": _local_datetime(item.get("created_at")),
                "agente": item.get("agent"),
                "evento": item.get("event_type"),
                "mensaje": _short(
                    payload.get("summary")
                    or payload.get("message")
                    or payload.get("status")
                    or payload.get("error")
                    or payload.get("reason")
                    or "",
                    180,
                ),
                "payload": payload,
            }
        )
    items = [grouped[key] for key in reversed(seen_order)]
    return items[:limit]


def _ci_agent_color(agent_name: str) -> str:
    palette = {
        "MarketEstimatorAgent": "#0f766e",
        "MarketRegimeAgent": "#0f766e",
        "TechnicalAnalystAgent": "#b45309",
        "TechnicalEdgeAgent": "#d97706",
        "SentimentAnalystAgent": "#9d174d",
        "StrategyEvaluatorAgent": "#1d4ed8",
        "ProgrammerAgent": "#6d28d9",
        "SoftwareReliabilityAgent": "#6d28d9",
        "PreEarningsSpecialistAgent": "#be123c",
        "RiskCapitalAgent": "#c2410c",
        "DataQualityAgent": "#047857",
        "ExperimentDesignerAgent": "#7c3aed",
        "DecisionCommitteeAgent": "#334155",
        "ChiefInvestmentOrchestratorAgent": "#be123c",
        "ImprovementStrategistAgent": "#be123c",
        "RiskGuardAgent": "#c2410c",
        "ValidationAgent": "#047857",
        "ReportAgent": "#475569",
        "OrchestratorAgent": "#0f172a",
    }
    return palette.get(str(agent_name), "#475569")


def _ci_initiative_summary(initiative: dict[str, Any] | None) -> dict[str, Any]:
    initiative = initiative or {}
    evidence = initiative.get("evidence") or []
    latest_decision = initiative.get("latest_decision") or {}
    return {
        "title": initiative.get("title") or "-",
        "status": initiative.get("status") or "-",
        "owner_agent": initiative.get("owner_agent") or "-",
        "risk_level": initiative.get("risk_level") or "-",
        "target_metric": initiative.get("target_metric") or "-",
        "latest_decision": latest_decision.get("decision") or "-",
        "decision_reason": latest_decision.get("reason") or latest_decision.get("source") or "-",
        "next_action": initiative.get("next_action") or "-",
        "evidence_count": len(evidence),
    }


def _ci_conversation_stage(message_type: str) -> str:
    mapping = {
        "proposal": "Propuesta del orquestador",
        "proposal_persisted": "Propuesta consolidada",
        "task_started": "Inicio de analisis",
        "task_completed": "Respuesta del agente",
        "task_skipped": "Tarea descartada",
        "validation_recorded": "Resultado de validacion",
        "lab_event_planned": "Evento planificado",
        "lab_cycle_started": "Ciclo iniciado",
        "lab_task_started": "Inicio de tarea",
        "lab_task_completed": "Evento del agente",
    }
    return mapping.get(message_type, message_type.replace("_", " ").strip() or "mensaje")


def _ci_conversation_body(payload: dict[str, Any] | None, *, fallback: str = "-") -> str:
    payload = payload or {}
    response = payload.get("response") or {}
    validation = payload.get("validation") or {}
    proposal = payload.get("proposal") or {}
    for part in (
        payload.get("summary"),
        response.get("summary") if isinstance(response, dict) else None,
        validation.get("summary") if isinstance(validation, dict) else None,
        validation.get("objective_summary") if isinstance(validation, dict) else None,
    ):
        text = str(part or "").strip()
        if text:
            return text
    if validation:
        status = validation.get("status") or payload.get("status") or "VALIDATING"
        proposal_id = proposal.get("proposal_id") or validation.get("proposal_id") or ""
        return f"Validacion {status}{f' para {proposal_id}' if proposal_id else ''}."
    actions = response.get("actions") if isinstance(response, dict) else None
    if isinstance(actions, list) and actions:
        title = str((actions[0] or {}).get("title") or "").strip()
        rationale = str((actions[0] or {}).get("rationale") or "").strip()
        if title and rationale:
            return f"{title}. {rationale}"
        if title:
            return title
    return fallback


def _ci_conversation_rollup(
    *,
    status: str,
    next_action: str,
    updated_at: Any,
    messages: list[dict[str, Any]],
) -> dict[str, str]:
    message_times = [str(item.get("created_at") or "") for item in messages if item.get("created_at")]
    last_message_at = max(message_times) if message_times else ""
    proposal_count = len([item for item in messages if item.get("stage") == _ci_conversation_stage("proposal_persisted")])
    validation_count = len([item for item in messages if item.get("stage") == _ci_conversation_stage("validation_recorded")])
    response_count = len([item for item in messages if item.get("stage") == _ci_conversation_stage("task_completed")])
    agents = sorted(
        {
            str(item.get("agent_name") or "")
            for item in messages
            if item.get("agent_name") and item.get("agent_name") != "OrchestratorAgent"
        }
    )
    status_upper = str(status or "").upper()
    if status_upper == "VALIDATING":
        now = "Validando evidencia o gates antes de decidir si se promueve, se rechaza o queda pendiente."
    elif status_upper in {"READY_TO_APPLY", "APPROVED"}:
        now = "Lista para aplicar cuando las condiciones de seguridad lo permitan."
    elif status_upper in {"OPEN", "ANALYZING"}:
        now = "Abierta para analisis; todavia puede recibir trabajo de agentes."
    elif status_upper in {"REJECTED", "CLOSED", "COMPLETED"}:
        now = "Cerrada; no deberia requerir accion salvo reapertura manual."
    else:
        now = f"Estado actual: {status or '-'}."

    done_parts = []
    if proposal_count:
        done_parts.append(f"{proposal_count} propuesta{'s' if proposal_count != 1 else ''}")
    if validation_count:
        done_parts.append(f"{validation_count} validacion{'es' if validation_count != 1 else ''}")
    if response_count:
        done_parts.append(f"{response_count} respuesta{'s' if response_count != 1 else ''} de agente")
    if agents:
        done_parts.append(f"agentes: {', '.join(agents[:4])}{'...' if len(agents) > 4 else ''}")
    done = "; ".join(done_parts) if done_parts else "Solo consta la apertura de la iniciativa; no hay trabajo enlazado visible."

    remaining = str(next_action or "").strip() or "No hay siguiente paso registrado."
    if status_upper == "VALIDATING" and "valid" not in remaining.lower():
        remaining = f"Validar evidencia objetiva. {remaining}"

    why = ""
    if status_upper == "VALIDATING" and proposal_count > 0 and validation_count == 0:
        why = "Hay propuestas abiertas, pero no consta una validacion enlazada a esta iniciativa."
    elif status_upper == "VALIDATING" and validation_count > 0:
        why = "La iniciativa sigue en fase de validacion y no ha cerrado en READY_TO_APPLY o REJECTED."
    elif status_upper in {"OPEN", "ANALYZING"} and response_count > 0:
        why = "Ya hay trabajo de agentes, pero la iniciativa sigue abierta y aun no ha cerrado su siguiente decision."
    elif proposal_count == 0 and response_count == 0:
        why = "No hay trabajo enlazado mas alla de la apertura de la iniciativa."
    last_dt = _local_dt(last_message_at) if last_message_at else None
    if last_dt is None:
        last_dt = _local_dt(updated_at)
    inactivity_days = 0
    if last_dt:
        inactivity_days = max(0, (datetime.now(timezone.utc) - last_dt.astimezone(timezone.utc)).days)
    if inactivity_days > 0:
        suffix = f" Han pasado {inactivity_days} dia{'s' if inactivity_days != 1 else ''} sin actividad nueva visible en este hilo."
        why = f"{why}{suffix}".strip() if why else suffix.strip()

    freshness = f"Actualizado: {_local_datetime(updated_at)}"
    if last_message_at:
        freshness += f" | Ultimo mensaje: {_local_datetime(last_message_at)}"
        if str(updated_at or "") > last_message_at:
            freshness += " | Hay cambios de estado posteriores al ultimo mensaje."
    else:
        freshness += " | Sin mensajes de trabajo enlazados."
    return {
        "now": now,
        "done": done,
        "remaining": remaining,
        "why": why or "Sin causa explicita registrada en el hilo.",
        "freshness": freshness,
        "last_message_at": last_message_at or "",
    }


def _ci_conversation_groups(
    initiatives: list[dict[str, Any]],
    initiative_messages: list[dict[str, Any]],
    recent_agent_events: list[dict[str, Any]],
    task_groups: list[dict[str, Any]],
    proposals: list[dict[str, Any]],
    validations: list[dict[str, Any]],
    *,
    cycle_id: str | None = None,
    limit: int = 12,
) -> list[dict[str, Any]]:
    messages_by_initiative: dict[str, list[dict[str, Any]]] = {}
    for item in initiative_messages:
        current_cycle_id = str(item.get("cycle_id") or "")
        if cycle_id and current_cycle_id and current_cycle_id != cycle_id:
            continue
        initiative_id = str(item.get("initiative_id") or "")
        if not initiative_id:
            continue
        messages_by_initiative.setdefault(initiative_id, []).append(item)

    raw_events: list[dict[str, Any]] = []
    for item in recent_agent_events:
        current_cycle_id = str(item.get("cycle_id") or "")
        if cycle_id:
            if current_cycle_id != cycle_id:
                continue
        elif not current_cycle_id.startswith("ci_cycle_"):
            continue
        raw_events.append(item)

    linked_event_index: dict[str, list[dict[str, Any]]] = {}
    for event in raw_events:
        payload = _load_json_cell(event.get("payload_json"))
        event_id = str(payload.get("event_id") or "")
        if event_id:
            linked_event_index.setdefault(event_id, []).append(event)
    proposal_index = {str(item.get("proposal_id") or ""): item for item in proposals}
    validation_index = {str(item.get("validation_id") or ""): item for item in validations}
    validations_by_proposal: dict[str, list[dict[str, Any]]] = {}
    for validation in validations:
        proposal_id = str(validation.get("proposal_id") or "")
        if proposal_id:
            validations_by_proposal.setdefault(proposal_id, []).append(validation)
    for linked_validations in validations_by_proposal.values():
        linked_validations.sort(key=lambda item: str(item.get("created_at") or ""))

    groups: list[dict[str, Any]] = []
    known_ids: set[str] = set()
    known_keys: set[str] = set()
    for initiative in initiatives:
        initiative_id = str(initiative.get("initiative_id") or "")
        initiative_key = str(initiative.get("initiative_key") or "")
        if initiative_id:
            known_ids.add(initiative_id)
        if initiative_key:
            known_keys.add(initiative_key)
        title = str(initiative.get("title") or initiative_key or initiative_id or "Iniciativa")
        conversation = [
            {
                "created_at": initiative.get("created_at"),
                "agent_name": "OrchestratorAgent",
                "stage": _ci_conversation_stage("proposal"),
                "body": (
                    f"Se abre la iniciativa '{title}' para mejorar {initiative.get('target_metric') or 'el sistema'}. "
                    f"Siguiente paso: {initiative.get('next_action') or 'coordinar analisis de agentes'}."
                ),
                "tone": "orchestrator",
            }
        ]
        for event_id in initiative.get("linked_event_ids") or []:
            for event in linked_event_index.get(str(event_id), []):
                if event.get("event_type") not in {"lab_event_planned", "lab_cycle_started"}:
                    continue
                payload = _load_json_cell(event.get("payload_json"))
                conversation.append(
                    {
                        "created_at": event.get("created_at"),
                        "agent_name": event.get("agent") or "OrchestratorAgent",
                        "stage": _ci_conversation_stage(str(event.get("event_type") or "")),
                        "body": _ci_conversation_body(
                            payload,
                            fallback=(
                                f"Evento {payload.get('event_type') or event.get('event_type') or '-'} "
                                "registrado para esta iniciativa."
                            ),
                        ),
                        "tone": "orchestrator",
                    }
                )
        for message in reversed(messages_by_initiative.get(initiative_id, [])):
            content = message.get("content") or {}
            conversation.append(
                {
                    "created_at": message.get("created_at"),
                    "agent_name": message.get("agent_name") or "-",
                    "stage": _ci_conversation_stage(str(message.get("message_type") or "")),
                    "body": _ci_conversation_body(content),
                    "tone": "validation" if str(message.get("message_type") or "") == "validation_recorded" else "agent",
                }
            )
        for proposal_id in initiative.get("linked_proposal_ids") or []:
            proposal = proposal_index.get(str(proposal_id))
            if not proposal:
                continue
            payload = proposal.get("payload") or {}
            conversation.append(
                {
                    "created_at": proposal.get("created_at"),
                    "agent_name": "RiskGuardAgent",
                    "stage": _ci_conversation_stage("proposal_persisted"),
                    "body": _ci_conversation_body(
                        {
                            "summary": payload.get("proposed_value") or payload.get("rationale"),
                            "response": {"summary": payload.get("expected_impact")},
                        },
                        fallback=f"Se registra la propuesta {proposal.get('proposal_id') or '-'} para {proposal.get('target_identifier') or '-'}.",
                    ),
                    "tone": "agent",
                }
            )
        appended_validation_ids: set[str] = set()
        for validation_id in initiative.get("linked_validation_ids") or []:
            validation = validation_index.get(str(validation_id))
            if not validation:
                continue
            appended_validation_ids.add(str(validation.get("validation_id") or validation_id))
            payload = validation.get("payload") or {}
            conversation.append(
                {
                    "created_at": validation.get("created_at"),
                    "agent_name": "ValidationAgent",
                    "stage": _ci_conversation_stage("validation_recorded"),
                    "body": _ci_conversation_body(
                        {
                            "summary": payload.get("objective_summary") or payload.get("summary"),
                            "validation": {
                                "status": validation.get("status"),
                                "proposal_id": validation.get("proposal_id"),
                            },
                        },
                        fallback=f"Validacion {validation.get('status') or '-'} para {validation.get('proposal_id') or '-'}",
                    ),
                    "tone": "validation",
                }
            )
        for proposal_id in initiative.get("linked_proposal_ids") or []:
            for validation in validations_by_proposal.get(str(proposal_id), []):
                validation_id = str(validation.get("validation_id") or "")
                if validation_id in appended_validation_ids:
                    continue
                appended_validation_ids.add(validation_id)
                payload = validation.get("payload") or {}
                conversation.append(
                    {
                        "created_at": validation.get("created_at"),
                        "agent_name": "ValidationAgent",
                        "stage": _ci_conversation_stage("validation_recorded"),
                        "body": _ci_conversation_body(
                            {
                                "summary": payload.get("objective_summary") or payload.get("summary"),
                                "validation": {
                                    "status": validation.get("status"),
                                    "proposal_id": validation.get("proposal_id"),
                                },
                            },
                            fallback=f"Validacion {validation.get('status') or '-'} para {validation.get('proposal_id') or '-'}",
                        ),
                        "tone": "validation",
                    }
                )
        messages_sorted = sorted(conversation, key=lambda item: str(item.get("created_at") or ""))
        updated_at = max(
            [str(item.get("created_at") or "") for item in conversation if item.get("created_at")] + [str(initiative.get("updated_at") or "")]
        )
        rollup = _ci_conversation_rollup(
            status=str(initiative.get("status") or "-"),
            next_action=str(initiative.get("next_action") or "-"),
            updated_at=updated_at,
            messages=messages_sorted,
        )
        groups.append(
            {
                "group_id": initiative_id or initiative_key or title,
                "initiative_id": initiative_id,
                "initiative_key": initiative_key,
                "title": title,
                "status": initiative.get("status") or "-",
                "owner_agent": initiative.get("owner_agent") or "-",
                "target_metric": initiative.get("target_metric") or "-",
                "risk_level": initiative.get("risk_level") or "-",
                "decision": (initiative.get("latest_decision") or {}).get("decision") or "-",
                "next_action": initiative.get("next_action") or "-",
                "updated_at": updated_at,
                "last_message_at": rollup["last_message_at"],
                "rollup": rollup,
                "messages": messages_sorted,
            }
        )

    for group in task_groups:
        group_initiative_id = str(group.get("initiative_id") or "")
        group_initiative_key = str(group.get("initiative_key") or "")
        if group_initiative_id in known_ids or group_initiative_key in known_keys:
            continue
        messages = []
        for message in group.get("messages", []):
            payload = message.get("payload") or {}
            event_type = str(message.get("evento") or "")
            messages.append(
                {
                    "created_at": str(payload.get("created_at") or message.get("hora") or ""),
                    "agent_name": message.get("agente") or "-",
                    "stage": _ci_conversation_stage(event_type),
                    "body": _ci_conversation_body(payload, fallback=str(message.get("mensaje") or event_type or "-")),
                    "tone": "orchestrator" if message.get("agente") == "OrchestratorAgent" else "agent",
                }
            )
        messages_sorted = sorted(messages, key=lambda item: str(item.get("created_at") or ""))
        rollup = _ci_conversation_rollup(
            status=str(group.get("status") or "-"),
            next_action="-",
            updated_at=str(group.get("updated_at") or ""),
            messages=messages_sorted,
        )
        groups.append(
            {
                "group_id": group_initiative_id or group_initiative_key or str(group.get("event_id") or group.get("focus") or "actividad"),
                "initiative_id": group_initiative_id,
                "initiative_key": group_initiative_key,
                "title": str(group.get("initiative_title") or group.get("focus") or "Actividad"),
                "status": group.get("status") or "-",
                "owner_agent": ", ".join(group.get("agent_names") or []) or "-",
                "target_metric": "-",
                "risk_level": "-",
                "decision": "-",
                "next_action": "-",
                "updated_at": str(group.get("updated_at") or ""),
                "last_message_at": rollup["last_message_at"],
                "rollup": rollup,
                "messages": messages_sorted,
            }
        )

    groups.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return groups[:limit]


def _render_ci_live_chat_panels(
    conversation_groups: list[dict[str, Any]],
    *,
    validation_lookup: dict[str, dict[str, Any]] | None = None,
) -> None:
    if not conversation_groups:
        st.info("Todavia no hay actividad del laboratorio para mostrar en directo.")
        return
    st.markdown(
        """
        <style>
        .ci-conversation-card { border: 1px solid rgba(15,23,42,0.12); border-radius: 14px; padding: 14px; background: linear-gradient(180deg, rgba(248,250,252,0.98), rgba(241,245,249,0.96)); }
        .ci-conversation-meta { font-size: 0.76rem; color: #475569; margin-bottom: 8px; }
        .ci-conversation-pill { display: inline-block; padding: 3px 8px; border-radius: 999px; font-size: 0.68rem; font-weight: 700; margin: 0 6px 6px 0; background: rgba(226,232,240,0.95); color: #0f172a; }
        .ci-conversation-summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin: 10px 0 12px 0; }
        .ci-conversation-summary-item { border: 1px solid rgba(15,23,42,0.10); border-radius: 8px; padding: 10px; background: rgba(255,255,255,0.72); }
        .ci-conversation-summary-label { font-size: 0.68rem; font-weight: 800; color: #334155; text-transform: uppercase; margin-bottom: 4px; }
        .ci-conversation-summary-body { font-size: 0.82rem; color: #0f172a; line-height: 1.35; }
        .ci-conversation-history-label { font-size: 0.72rem; font-weight: 800; color: #475569; margin: 8px 0; text-transform: uppercase; }
        .ci-conversation-message { margin: 0 0 10px 0; padding: 12px; border-radius: 12px; color: #0f172a; background: white; border-left: 4px solid #94a3b8; }
        .ci-conversation-message.orchestrator { background: #e0f2fe; border-left-color: #0284c7; }
        .ci-conversation-message.agent { background: #f8fafc; border-left-color: #475569; }
        .ci-conversation-message.validation { background: #ecfdf5; border-left-color: #059669; }
        .ci-conversation-stage { font-size: 0.74rem; font-weight: 700; color: #0f172a; margin-bottom: 4px; }
        .ci-conversation-message-meta { font-size: 0.72rem; color: #475569; margin-bottom: 6px; }
        .ci-conversation-message-body { font-size: 0.88rem; line-height: 1.4; white-space: pre-wrap; }
        @media (max-width: 900px) { .ci-conversation-summary { grid-template-columns: 1fr; } }
        </style>
        """,
        unsafe_allow_html=True,
    )
    for index, group in enumerate(conversation_groups):
        validation = (validation_lookup or {}).get(str(group.get("initiative_key") or "")) or (
            (validation_lookup or {}).get(str(group.get("initiative_id") or ""))
        ) or {}
        status = str(group.get("status") or "-")
        objective = str(validation.get("objective_status") or validation.get("status") or "-")
        updated_at = _local_datetime(group.get("updated_at"))
        with st.expander(f"{group.get('title')} · {status} · {updated_at}", expanded=index < 3):
            pills = [
                f"<span class='ci-conversation-pill'>Meta: {escape(str(group.get('target_metric') or '-'))}</span>",
                f"<span class='ci-conversation-pill'>Owner: {escape(str(group.get('owner_agent') or '-'))}</span>",
                f"<span class='ci-conversation-pill'>Riesgo: {escape(str(group.get('risk_level') or '-'))}</span>",
                f"<span class='ci-conversation-pill'>Decision: {escape(str(group.get('decision') or '-'))}</span>",
                f"<span class='ci-conversation-pill'>Objetivo: {escape(objective)}</span>",
            ]
            messages_html = []
            for message in group.get("messages", []):
                messages_html.append(
                    f"<div class='ci-conversation-message {escape(str(message.get('tone') or 'agent'))}'>"
                    f"<div class='ci-conversation-stage'>{escape(str(message.get('stage') or 'mensaje'))}</div>"
                    f"<div class='ci-conversation-message-meta'>{escape(_local_datetime(message.get('created_at')))} | "
                    f"{escape(str(message.get('agent_name') or '-'))}</div>"
                    f"<div class='ci-conversation-message-body'>{escape(str(message.get('body') or '-'))}</div>"
                    f"</div>"
                )
            conversation_html = "".join(messages_html) or (
                "<div class='ci-conversation-message agent'>"
                "<div class='ci-conversation-message-body'>Sin mensajes todavia.</div>"
                "</div>"
            )
            st.markdown(
                (
                    "<div class='ci-conversation-card'>"
                    f"<div class='ci-conversation-meta'>Iniciativa: {escape(str(group.get('initiative_key') or group.get('initiative_id') or '-'))}</div>"
                    f"<div class='ci-conversation-meta'>Siguiente paso: {escape(str(group.get('next_action') or '-'))}</div>"
                    f"{''.join(pills)}"
                    f"{conversation_html}"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )


def _render_ci_initiative_status_panels(
    conversation_groups: list[dict[str, Any]],
    *,
    validation_lookup: dict[str, dict[str, Any]] | None = None,
) -> None:
    if not conversation_groups:
        st.info("Todavia no hay actividad del laboratorio para mostrar en directo.")
        return
    st.markdown(
        """
        <style>
        .ci-work-card { border: 1px solid rgba(15,23,42,0.12); border-radius: 10px; padding: 14px; background: linear-gradient(180deg, rgba(248,250,252,0.98), rgba(241,245,249,0.96)); }
        .ci-work-meta { font-size: 0.76rem; color: #475569; margin-bottom: 8px; }
        .ci-work-pill { display: inline-block; padding: 3px 8px; border-radius: 999px; font-size: 0.68rem; font-weight: 700; margin: 0 6px 6px 0; background: rgba(226,232,240,0.95); color: #0f172a; }
        .ci-work-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin: 10px 0 12px 0; }
        .ci-work-summary-item { border: 1px solid rgba(15,23,42,0.10); border-radius: 8px; padding: 10px; background: rgba(255,255,255,0.78); }
        .ci-work-summary-label { font-size: 0.68rem; font-weight: 800; color: #334155; text-transform: uppercase; margin-bottom: 4px; }
        .ci-work-summary-body { font-size: 0.82rem; color: #0f172a; line-height: 1.35; }
        .ci-work-history-label { font-size: 0.72rem; font-weight: 800; color: #475569; margin: 8px 0; text-transform: uppercase; }
        .ci-work-message { margin: 0 0 10px 0; padding: 12px; border-radius: 8px; color: #0f172a; background: white; border-left: 4px solid #94a3b8; }
        .ci-work-message.orchestrator { background: #e0f2fe; border-left-color: #0284c7; }
        .ci-work-message.agent { background: #f8fafc; border-left-color: #475569; }
        .ci-work-message.validation { background: #ecfdf5; border-left-color: #059669; }
        .ci-work-stage { font-size: 0.74rem; font-weight: 700; color: #0f172a; margin-bottom: 4px; }
        .ci-work-message-meta { font-size: 0.72rem; color: #475569; margin-bottom: 6px; }
        .ci-work-message-body { font-size: 0.88rem; line-height: 1.4; white-space: pre-wrap; }
        @media (max-width: 900px) { .ci-work-summary { grid-template-columns: 1fr; } }
        </style>
        """,
        unsafe_allow_html=True,
    )
    for index, group in enumerate(conversation_groups):
        validation = (validation_lookup or {}).get(str(group.get("initiative_key") or "")) or (
            (validation_lookup or {}).get(str(group.get("initiative_id") or ""))
        ) or {}
        status = str(group.get("status") or "-")
        objective = str(validation.get("objective_status") or validation.get("status") or "-")
        updated_at = _local_datetime(group.get("updated_at"))
        last_message = _local_datetime(group.get("last_message_at")) if group.get("last_message_at") else "sin mensajes"
        rollup = group.get("rollup") or {}
        title = f"{group.get('title')} | {status} | act. {updated_at} | msg. {last_message}"
        with st.expander(title, expanded=index < 3):
            pills = [
                f"<span class='ci-work-pill'>Meta: {escape(str(group.get('target_metric') or '-'))}</span>",
                f"<span class='ci-work-pill'>Owner: {escape(str(group.get('owner_agent') or '-'))}</span>",
                f"<span class='ci-work-pill'>Riesgo: {escape(str(group.get('risk_level') or '-'))}</span>",
                f"<span class='ci-work-pill'>Decision: {escape(str(group.get('decision') or '-'))}</span>",
                f"<span class='ci-work-pill'>Objetivo: {escape(objective)}</span>",
            ]
            messages_html = []
            for message in reversed(group.get("messages", [])):
                messages_html.append(
                    f"<div class='ci-work-message {escape(str(message.get('tone') or 'agent'))}'>"
                    f"<div class='ci-work-stage'>{escape(str(message.get('stage') or 'mensaje'))}</div>"
                    f"<div class='ci-work-message-meta'>{escape(_local_datetime(message.get('created_at')))} | "
                    f"{escape(str(message.get('agent_name') or '-'))}</div>"
                    f"<div class='ci-work-message-body'>{escape(str(message.get('body') or '-'))}</div>"
                    f"</div>"
                )
            conversation_html = "".join(messages_html) or (
                "<div class='ci-work-message agent'>"
                "<div class='ci-work-message-body'>Sin mensajes todavia.</div>"
                "</div>"
            )
            st.markdown(
                (
                    "<div class='ci-work-card'>"
                    f"<div class='ci-work-meta'>Iniciativa: {escape(str(group.get('initiative_key') or group.get('initiative_id') or '-'))}</div>"
                    f"<div class='ci-work-meta'>{escape(str(rollup.get('freshness') or '-'))}</div>"
                    f"{''.join(pills)}"
                    "<div class='ci-work-summary'>"
                    "<div class='ci-work-summary-item'>"
                    "<div class='ci-work-summary-label'>Ahora</div>"
                    f"<div class='ci-work-summary-body'>{escape(str(rollup.get('now') or '-'))}</div>"
                    "</div>"
                    "<div class='ci-work-summary-item'>"
                    "<div class='ci-work-summary-label'>Hecho</div>"
                    f"<div class='ci-work-summary-body'>{escape(str(rollup.get('done') or '-'))}</div>"
                    "</div>"
                    "<div class='ci-work-summary-item'>"
                    "<div class='ci-work-summary-label'>Falta</div>"
                    f"<div class='ci-work-summary-body'>{escape(str(rollup.get('remaining') or '-'))}</div>"
                    "</div>"
                    "<div class='ci-work-summary-item'>"
                    "<div class='ci-work-summary-label'>Por Que No Avanza</div>"
                    f"<div class='ci-work-summary-body'>{escape(str(rollup.get('why') or '-'))}</div>"
                    "</div>"
                    "</div>"
                    "<div class='ci-work-history-label'>Historial, de reciente a antiguo</div>"
                    f"{conversation_html}"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )


def _render_ci_live_task_groups(task_groups: list[dict[str, Any]]) -> None:
    if not task_groups:
        st.info("Todavia no hay actividad del laboratorio para mostrar en directo.")
        return
    for group in task_groups:
        title = (
            f"{', '.join(group.get('agent_names') or ['-'])} | {group['focus']} | "
            f"{group['status']} | {_local_datetime(group['updated_at'])}"
        )
        with st.expander(title, expanded=group.get("status") not in {"COMPLETED", "FAILED", "CANCELLED"}):
            st.caption(f"Iniciativa: {group.get('initiative_id')} | Evento: {group['event_id']}")
            feed = pd.DataFrame(
                [
                    {
                        "hora": item["hora"],
                        "agente": item["agente"],
                        "evento": item["evento"],
                        "mensaje": item["mensaje"],
                    }
                    for item in group["messages"]
                ]
            )
            st.dataframe(feed, use_container_width=True, hide_index=True)
            latest_payload = group["messages"][-1]["payload"] if group["messages"] else {}
            if latest_payload:
                st.json(latest_payload)


def _latest_ci_llm_failure(events: list[dict[str, Any]]) -> str | None:
    latest_completed = None
    for item in events:
        current_cycle_id = str(item.get("cycle_id") or "")
        if not current_cycle_id.startswith("ci_cycle_"):
            continue
        if item.get("agent") not in {"ImprovementStrategistAgent", "ChiefInvestmentOrchestratorAgent"}:
            continue
        if item.get("event_type") != "lab_llm_call_completed":
            continue
        latest_completed = item
        break
    if latest_completed:
        payload = _load_json_cell(latest_completed.get("payload_json"))
        if str(payload.get("status") or "").lower() == "failed":
            return str(payload.get("error") or "LLM call failed")
    return None


def _latest_ci_llm_result(events: list[dict[str, Any]]) -> dict[str, Any]:
    for item in events:
        current_cycle_id = str(item.get("cycle_id") or "")
        if not current_cycle_id.startswith("ci_cycle_"):
            continue
        if item.get("agent") not in {"ImprovementStrategistAgent", "ChiefInvestmentOrchestratorAgent"}:
            continue
        if item.get("event_type") != "lab_llm_call_completed":
            continue
        payload = _load_json_cell(item.get("payload_json"))
        return {
            "status": str(payload.get("status") or "").lower(),
            "error": payload.get("error"),
            "provider": payload.get("provider"),
            "model": payload.get("model"),
            "base_url": payload.get("base_url"),
            "fallback_used": bool(payload.get("fallback_used")),
            "prompt_tokens_estimate": payload.get("prompt_tokens_estimate"),
            "context_limit_tokens": payload.get("context_limit_tokens"),
            "context_compacted": payload.get("context_compacted"),
            "truncation_report": payload.get("truncation_report") or {},
            "created_at": item.get("created_at"),
        }
    return {}


def _ci_api_connection_status(
    settings: Any,
    latest_cycle: dict[str, Any] | None,
    latest_llm_failure: str | None,
    latest_llm_result: dict[str, Any] | None = None,
) -> tuple[str, str]:
    if not settings.improvement_llm_enabled:
        return ("off", "LLM externo desactivado")
    if not settings.improvement_llm_api_key:
        return ("sin token", "Falta IMPROVEMENT_LLM_API_KEY")
    if latest_llm_failure:
        return ("error", _short(latest_llm_failure, 120))
    if (latest_llm_result or {}).get("status") == "ok":
        return ("conectada", f"Ultima llamada LLM correcta: {_local_datetime((latest_llm_result or {}).get('created_at'))}")
    llm_status = str((latest_cycle or {}).get("llm_status") or "").strip().lower()
    if llm_status == "ok":
        return ("conectada", "Ultima llamada LLM completada")
    if llm_status == "failed":
        return ("error", "Ultima llamada LLM fallida")
    return ("pendiente", "Aun no hay handshake confirmado con la API")


def _ci_llm_route_label(settings: Any, latest_llm_result: dict[str, Any] | None = None) -> str:
    result = latest_llm_result or {}
    provider = str(result.get("provider") or "").strip()
    model = str(result.get("model") or "").strip()
    base_url = str(result.get("base_url") or "").strip()
    fallback_used = bool(result.get("fallback_used"))
    if provider or model or base_url:
        prefix = "fallback local" if fallback_used else "primario"
        return f"{prefix}: {provider or '-'} | {model or '-'} | {base_url or '-'}"
    return (
        f"configurado: {settings.improvement_llm_provider} | "
        f"{settings.improvement_llm_orchestrator_model} | {settings.improvement_llm_base_url}"
    )


def _ci_llm_usage_label(latest_llm_result: dict[str, Any] | None = None) -> str:
    result = latest_llm_result or {}
    estimate = result.get("prompt_tokens_estimate")
    limit = result.get("context_limit_tokens")
    compacted = result.get("context_compacted")
    if estimate is None and limit is None:
        return "sin datos todavia"
    compacted_label = "si" if compacted else "no"
    return f"{estimate or '-'} / {limit or '-'} tokens | compactado: {compacted_label}"


def _ci_llm_truncation_label(latest_llm_result: dict[str, Any] | None = None) -> str:
    report = (latest_llm_result or {}).get("truncation_report") or {}
    truncations = report.get("truncations") or []
    if not truncations:
        return ""
    first = truncations[0]
    remaining = max(0, len(truncations) - 1)
    suffix = f" y {remaining} mas" if remaining else ""
    return (
        f"Recorte CI: {first.get('path')} "
        f"({first.get('original')} -> {first.get('kept')}){suffix}"
    )


def _ci_status_tone(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"ok", "connected", "conectada", "fresh", "active", "activo", "running", "completed"}:
        return "good"
    if normalized in {"failed", "error", "warning", "blocked", "missing", "off", "idle"}:
        return "bad"
    return "neutral"


def _ci_runtime_alert(runtime_state: dict[str, Any] | None, ci_job_state: dict[str, Any] | None) -> dict[str, str] | None:
    runtime_state = runtime_state or {}
    ci_job_state = ci_job_state or {}
    payload = runtime_state.get("payload") or {}
    extra = ci_job_state.get("extra") or {}
    runtime_status = str(runtime_state.get("status") or "").upper()
    runtime_payload_status = str(payload.get("status") or "").upper()
    job_status = str(ci_job_state.get("status") or "").upper()
    if runtime_status != "FAILED" and runtime_payload_status != "FAILED" and job_status not in {"FAILED", "RETRY_WAIT"}:
        return None
    error_text = str(payload.get("error") or ci_job_state.get("detail") or "Fallo sin detalle disponible.").strip()
    retry_at = str(payload.get("next_retry_at") or extra.get("next_retry_at") or "").strip()
    retry_attempt = int(payload.get("retry_attempt") or extra.get("retry_attempt") or 0)
    message = error_text
    if retry_at:
        message += f" Reintento automatico: {_local_datetime(retry_at)}."
    if retry_attempt > 0:
        message += f" Intento acumulado: {retry_attempt}."
    return {"title": "La mejora continua ha fallado.", "message": message}


def _dashboard_llm_pills(
    settings: Any,
    store: Store,
    latest_ci_llm_result: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    pills: list[dict[str, str]] = []
    latest_trade_llm = _latest_trade_decision_llm_usage(store)
    primary_model = str(getattr(settings, "openai_model", "") or "").strip()
    local_model = str(getattr(settings, "llm_local_fallback_model", "") or "").strip()
    trade_model = str(latest_trade_llm.get("model") or settings.openai_model or "-").strip()
    trade_created_at = latest_trade_llm.get("created_at")
    if latest_trade_llm:
        if trade_model == primary_model:
            trade_route = "mimo"
            trade_tone = "good"
        elif trade_model == local_model:
            trade_route = "local"
            trade_tone = "good"
        else:
            trade_route = "historico"
            trade_tone = "neutral"
        pills.append(
            {
                "tone": trade_tone,
                "text": f"Trading LLM {trade_model} | {trade_route} {_local_time(trade_created_at)}",
            }
        )
    else:
        pills.append(
            {
                "tone": "neutral",
                "text": f"Trading LLM {trade_model} | sin uso reciente",
            }
        )

    ci_result = latest_ci_llm_result or {}
    ci_model = str(ci_result.get("model") or settings.improvement_llm_orchestrator_model or "-").strip()
    ci_status = str(ci_result.get("status") or "").lower().strip()
    if ci_status == "ok":
        ci_route = "fallback local" if ci_result.get("fallback_used") else "primario"
        pills.append(
            {
                "tone": "good",
                "text": f"CI LLM {ci_model} | {ci_route} {_local_time(ci_result.get('created_at'))}",
            }
        )
    elif ci_status == "failed":
        pills.append(
            {
                "tone": "bad",
                "text": f"CI LLM {ci_model} | fallo reciente",
            }
        )
    else:
        pills.append(
            {
                "tone": "neutral",
                "text": f"CI LLM {ci_model} | pendiente",
            }
        )
    return pills


def _ci_llm_responses(store: Store, *, limit: int = 10000) -> list[dict[str, Any]]:
    with store.connect() as conn:
        rows = conn.execute(
            """
            SELECT llm_call_id, cycle_id, provider, model, status, request_json,
                   response_json, raw_response, error, created_at
            FROM continuous_improvement_llm_responses
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "llm_call_id": row["llm_call_id"],
            "cycle_id": row["cycle_id"],
            "provider": row["provider"],
            "model": row["model"],
            "status": row["status"],
            "request": _load_json_cell(row["request_json"]),
            "response": _load_json_cell(row["response_json"]),
            "raw_response": row["raw_response"],
            "error": row["error"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _ci_export_dataset(store: Store, *, limit: int = 10000) -> dict[str, Any]:
    cycles = store.continuous_improvement_cycles(limit=limit)
    proposals = store.continuous_improvement_proposals(limit=limit)
    validations = store.continuous_improvement_validations(limit=limit)
    decisions = store.continuous_improvement_decisions(limit=limit)
    events = store.continuous_improvement_events(limit=limit)
    tasks = store.continuous_improvement_tasks(limit=limit)
    hypotheses = store.continuous_improvement_hypotheses(limit=limit)
    initiatives = store.continuous_improvement_initiatives(limit=limit)
    initiative_messages = store.continuous_improvement_initiative_messages(limit=limit)
    experiments = store.continuous_improvement_experiments(limit=limit)
    applied_changes = store.continuous_improvement_applied_changes(limit=limit)
    memories = store.continuous_improvement_memories()
    llm_responses = _ci_llm_responses(store, limit=limit)
    recent_agent_events = [
        item
        for item in store.latest_events(limit)
        if str(item.get("cycle_id") or "").startswith("ci_cycle_")
        or str(item.get("agent") or "").lower().startswith("continuous")
        or "ci_" in str(item.get("payload_json") or "")
    ]
    task_groups = _ci_task_activity(recent_agent_events, tasks, cycle_id=None, limit=limit)
    conversation_groups = _ci_conversation_groups(
        initiatives,
        initiative_messages,
        recent_agent_events,
        task_groups,
        proposals,
        validations,
        cycle_id=None,
        limit=limit,
    )
    return {
        "cycles": cycles,
        "proposals": proposals,
        "validations": validations,
        "decisions": decisions,
        "events": events,
        "tasks": tasks,
        "hypotheses": hypotheses,
        "initiatives": initiatives,
        "initiative_messages": initiative_messages,
        "experiments": experiments,
        "applied_changes": applied_changes,
        "memories": memories,
        "llm_responses": llm_responses,
        "agent_events": recent_agent_events,
        "conversation_groups": conversation_groups,
    }


def _ci_status_counts(items: list[dict[str, Any]], key: str = "status") -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        status = str(item.get(key) or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _ci_global_export_payload(
    dataset: dict[str, Any],
    *,
    generated_at: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    proposals = list(dataset.get("proposals") or [])
    tasks = list(dataset.get("tasks") or [])
    initiatives = list(dataset.get("initiatives") or [])
    events = list(dataset.get("events") or [])
    pending_proposals = [
        item
        for item in proposals
        if str(item.get("status") or "").upper() in {"PENDING", "OPEN", "READY_TO_APPLY", "APPROVED"}
    ]
    studied_proposals = [
        item
        for item in proposals
        if str(item.get("status") or "").upper() not in {"PENDING", "OPEN"}
    ]
    pending_tasks = [
        item
        for item in tasks
        if str(item.get("status") or "").upper() not in {"COMPLETED", "CANCELLED", "FAILED"}
    ]
    open_initiatives = [
        item
        for item in initiatives
        if str(item.get("status") or "").upper() not in {"CLOSED", "REJECTED", "COMPLETED"}
    ]
    open_events = [
        item
        for item in events
        if str(item.get("status") or "").upper() not in {"COMPLETED", "CANCELLED", "RESOLVED", "REJECTED"}
    ]
    return {
        "schema": "agente_bolsa.continuous_improvement.deepresearch.all_history.v1",
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "intended_consumer": "LLM/deepresearch",
        "export_limit_per_collection": limit,
        "summary": {
            "cycles": len(dataset.get("cycles") or []),
            "initiatives": len(initiatives),
            "open_initiatives": len(open_initiatives),
            "conversation_threads": len(dataset.get("conversation_groups") or []),
            "proposals": len(proposals),
            "studied_proposals": len(studied_proposals),
            "pending_or_applicable_proposals": len(pending_proposals),
            "validations": len(dataset.get("validations") or []),
            "decisions": len(dataset.get("decisions") or []),
            "tasks": len(tasks),
            "pending_tasks": len(pending_tasks),
            "events": len(events),
            "open_events": len(open_events),
            "hypotheses": len(dataset.get("hypotheses") or []),
            "experiments": len(dataset.get("experiments") or []),
            "applied_changes": len(dataset.get("applied_changes") or []),
            "llm_responses": len(dataset.get("llm_responses") or []),
            "proposal_status_counts": _ci_status_counts(proposals),
            "initiative_status_counts": _ci_status_counts(initiatives),
            "task_status_counts": _ci_status_counts(tasks),
            "event_status_counts": _ci_status_counts(events),
        },
        "pending": {
            "initiatives": open_initiatives,
            "proposals": pending_proposals,
            "tasks": pending_tasks,
            "events": open_events,
        },
        "studied": {
            "proposals": studied_proposals,
            "validations": dataset.get("validations") or [],
            "decisions": dataset.get("decisions") or [],
            "experiments": dataset.get("experiments") or [],
            "applied_changes": dataset.get("applied_changes") or [],
        },
        "conversations": dataset.get("conversation_groups") or [],
        "raw_collections": dataset,
    }


def page_continuous_improvement() -> None:
    settings = _settings()
    store = _store()
    runtime = ContinuousImprovementLabRuntime(settings, store)
    _page_header("Mejora continua", "Laboratorio multiagente residente: eventos, tareas, hipotesis, propuestas y validaciones.")

    latest = store.latest_continuous_improvement_cycle()
    runtime_state = store.continuous_improvement_runtime_state()
    proposals = store.continuous_improvement_proposals(limit=200)
    pending = [item for item in proposals if item.get("status") == "PENDING"]
    review: list[dict[str, Any]] = []
    hypotheses = store.continuous_improvement_hypotheses(limit=200)
    events = store.continuous_improvement_events(limit=200)
    tasks = store.continuous_improvement_tasks(limit=200)
    validations = store.continuous_improvement_validations(limit=200)
    initiatives = store.continuous_improvement_initiatives(limit=200)
    initiative_messages = store.continuous_improvement_initiative_messages(limit=500)
    validation_lookup: dict[str, dict[str, Any]] = {}
    for item in validations:
        initiative_id = str(item.get("initiative_id") or item.get("payload", {}).get("initiative_id") or "")
        initiative_key = str(item.get("payload", {}).get("initiative_key") or "")
        if initiative_id:
            validation_lookup[initiative_id] = item
        if initiative_key:
            validation_lookup[initiative_key] = item
    recent_agent_events = store.latest_events(400)
    ci_activity = _ci_agent_activity(recent_agent_events, cycle_id=(latest or {}).get("cycle_id"), limit=200)
    ci_task_groups = _ci_task_activity(recent_agent_events, tasks, cycle_id=(latest or {}).get("cycle_id"), limit=100)
    conversation_proposals = store.continuous_improvement_proposals(limit=10000)
    conversation_validations = store.continuous_improvement_validations(limit=10000)
    ci_conversation_groups = _ci_conversation_groups(
        initiatives,
        initiative_messages,
        recent_agent_events,
        ci_task_groups,
        conversation_proposals,
        conversation_validations,
        cycle_id=(latest or {}).get("cycle_id"),
        limit=20,
    )
    latest_llm_failure = _latest_ci_llm_failure(recent_agent_events)
    latest_llm_result = _latest_ci_llm_result(recent_agent_events)
    latest_production_health = _latest_report_json("latest_production_health.json")
    scheduler_snapshot = scheduler_status(settings)
    production_summary = (
        (latest_production_health.get("payload") or {}).get("summary", {})
        if latest_production_health.get("available")
        else {}
    )
    schedule_status = _schedule_process_status()
    ci_job_state = (scheduler_snapshot.get("job_runtime") or {}).get("continuous_improvement") or {}
    api_status, api_detail = _ci_api_connection_status(settings, latest, latest_llm_failure, latest_llm_result)
    refresh_interval_seconds = int(st.session_state.get("refresh_interval_seconds", 30) or 0)
    pending_tasks = len([item for item in tasks if item.get("status") not in {"COMPLETED", "CANCELLED"}])
    ready_to_apply = len([item for item in initiatives if item.get("status") == "READY_TO_APPLY"])
    objective_validations = len([item for item in validations if (item.get("payload") or {}).get("objective_status")])
    runtime_status = str((runtime_state or {}).get("status") or "IDLE")
    llm_status = str((latest_llm_result or {}).get("status") or (latest or {}).get("llm_status") or "pendiente")
    llm_model = str((latest_llm_result or {}).get("model") or settings.improvement_llm_orchestrator_model or "-")
    cycle_label = latest.get("status") if latest else "sin ciclo"
    top_summary = (
        " · ".join(
            [
                f"sistema {'activo' if settings.continuous_improvement_enabled else 'off'}",
                f"scheduler {'activo' if schedule_status.get('running') else 'parado'}",
                f"auto {'on' if settings.continuous_improvement_schedule_enabled else 'off'}",
                f"dry-run {'si' if settings.improvement_dry_run else 'no'}",
                f"produccion {production_summary.get('overall_status') or 'unknown'}",
            ]
        )
    )

    with st.container(border=True):
        _section_title("Estado general", "Solo lo necesario para saber si el laboratorio esta bien.")
        s1, s2, s3, s4 = st.columns(4)
        with s1:
            _compact_metric("Runtime", runtime_status, _local_time((runtime_state or {}).get("heartbeat_at")), _ci_status_tone(runtime_status))
        with s2:
            _compact_metric("LLM", llm_status, llm_model, _ci_status_tone(llm_status))
        with s3:
            _compact_metric("Pendientes", pending_tasks, f"{len(pending)} propuestas | {ready_to_apply} listas")
        with s4:
            _compact_metric("Ultimo ciclo", cycle_label, _local_time((latest or {}).get("updated_at") or (latest or {}).get("created_at")))
        st.caption(top_summary)
        export_col1, export_col2 = st.columns([1.1, 1.4])
        with export_col1:
            ci_export_limit = st.number_input(
                "Registros max por coleccion",
                min_value=100,
                max_value=50000,
                value=10000,
                step=500,
                key="ci_global_export_limit",
            )
        with export_col2:
            prepare_ci_export = st.checkbox(
                "Preparar descarga completa de mejora continua",
                value=False,
                key="ci_prepare_global_export",
            )
        if prepare_ci_export:
            with st.spinner("Preparando historico completo de mejora continua para deepresearch..."):
                ci_export_dataset = _ci_export_dataset(store, limit=int(ci_export_limit))
                ci_export_payload = _ci_global_export_payload(
                    ci_export_dataset,
                    limit=int(ci_export_limit),
                )
            st.download_button(
                "Descargar historico completo de mejora continua JSON",
                data=_json(ci_export_payload),
                file_name=f"mejora_continua_historico_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json",
                use_container_width=True,
            )
    st.caption(f"CI LLM: {_ci_llm_route_label(settings, latest_llm_result)}")
    st.caption(f"Uso prompt: {_ci_llm_usage_label(latest_llm_result)}")
    truncation_label = _ci_llm_truncation_label(latest_llm_result)

    if settings.allow_live_trading:
        st.error("ALLOW_LIVE_TRADING=true. El laboratorio no aplicara cambios ni activara trading real.")
    if settings.allow_auto_apply_improvements and settings.improvement_dry_run:
        st.warning("ALLOW_AUTO_APPLY_IMPROVEMENTS=true, pero IMPROVEMENT_DRY_RUN sigue activo.")
    if not settings.continuous_improvement_schedule_enabled:
        st.warning("El laboratorio autonomo esta desactivado: CONTINUOUS_IMPROVEMENT_SCHEDULE_ENABLED=false.")
    if not schedule_status.get("running"):
        st.warning("No hay proceso schedule gestionado desde la web. El laboratorio no se esta ejecutando de forma residente.")
    runtime_alert = _ci_runtime_alert(runtime_state, ci_job_state)
    if runtime_alert:
        st.error(f"{runtime_alert['title']} {runtime_alert['message']}")
    if latest_llm_failure:
        st.error(f"El LLM externo esta fallando: {latest_llm_failure}")

    left, right = st.columns([1, 1.6], gap="large")
    with left:
        with st.container(border=True):
            _section_title("Acciones", "Controles manuales y detalle tecnico cuando haga falta.")
            a1, a2, a3, a4 = st.columns(4)
            with a1:
                if st.button("Run once", disabled=not settings.continuous_improvement_enabled, use_container_width=True):
                    try:
                        with st.spinner("Ejecutando tick del laboratorio..."):
                            result = runtime.run_once(mode="manual", trigger_event_type="manual_trigger", trigger_payload={"source": "streamlit"})
                        st.success(f"Ciclo terminado: {result.get('status')}")
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001 - dashboard should keep explaining failures.
                        st.error(f"Run once fallo: {exc}")
            with a2:
                if st.button("Encolar evento", disabled=not settings.continuous_improvement_enabled, use_container_width=True):
                    runtime.enqueue_event(
                        event_type="manual_ui_event",
                        source="streamlit",
                        domain="software-improvement",
                        payload={"requested_at": datetime.now(ZoneInfo("UTC")).isoformat()},
                        force_unique=True,
                    )
                    st.success("Evento encolado.")
                    st.rerun()
            with a3:
                if st.button("Iniciar scheduler", use_container_width=True):
                    result = _start_schedule()
                    st.success(f"Scheduler iniciado. PID: {result.get('pid')}")
                    st.rerun()
            with a4:
                if st.button("Reintentar ahora", disabled=not settings.continuous_improvement_enabled, use_container_width=True):
                    try:
                        with st.spinner("Reintentando mejora continua..."):
                            result = runtime.run_once(mode="manual", trigger_event_type="manual_retry", trigger_payload={"source": "streamlit_retry"})
                        st.success(f"Reintento terminado: {result.get('status')}")
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001 - dashboard should keep explaining failures.
                        st.error(f"Reintento manual fallido: {exc}")
            with st.expander("Detalle tecnico", expanded=False):
                st.write(f"API LLM: {api_detail}")
                st.write(f"Proveedor: {settings.improvement_llm_provider}")
                st.write(f"Modelo especialistas: {settings.improvement_llm_model}")
                st.write(f"Modelo orquestador: {settings.improvement_llm_orchestrator_model}")
                st.write(f"Fallback local CI: {'activo' if settings.improvement_llm_local_fallback_enabled else 'off'}")
                st.write(f"Ruta LLM activa: {_ci_llm_route_label(settings, latest_llm_result)}")
                st.write(f"Tokens prompt CI: {_ci_llm_usage_label(latest_llm_result)}")
                if truncation_label:
                    st.write(truncation_label)
                st.write(f"Heartbeat: {_local_datetime((runtime_state or {}).get('heartbeat_at'))}")
                st.write(f"Scheduler CI: {ci_job_state.get('status') or '-'}")
                if ci_job_state:
                    st.json(ci_job_state)
                st.write(f"Validaciones objetivas: {objective_validations}")
                st.code(
                    r".\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab run-once --json",
                    language="powershell",
                )
    with right:
        with st.container(border=True):
            _section_title("Ultimo ciclo", "Resumen corto del ultimo trabajo ejecutado.")
            if latest:
                summary = (latest.get("evaluation") or {}).get("summary", {})
                status_value = str(latest.get("status") or "-")
                errors_value = int(summary.get("recent_errors", 0) or 0)
                incidents_value = int(summary.get("operational_incidents", 0) or 0)
                llm_value = str(latest.get("llm_status") or "-")
                meta1, meta2, meta3, meta4 = st.columns(4)
                with meta1:
                    _compact_metric("Estado", status_value, tone=_ci_status_tone(status_value))
                with meta2:
                    _compact_metric("Senales", summary.get("signals", 0))
                with meta3:
                    _compact_metric(
                        "Fallos runtime",
                        errors_value,
                        f"{incidents_value} incidencias",
                        tone="bad" if errors_value > 0 else "good",
                    )
                with meta4:
                    _compact_metric("LLM", llm_value, tone=_ci_status_tone(llm_value))
                st.caption(
                    f"{_local_datetime(latest.get('updated_at') or latest.get('created_at'))} | "
                    f"{summary.get('signals', 0)} senales | {errors_value} fallos runtime | "
                    f"{incidents_value} incidencias | LLM {llm_value}"
                )
            else:
                st.markdown("<div class='empty-box'>Todavia no hay ciclos del laboratorio.</div>", unsafe_allow_html=True)

    artifact_paths = {
        "backtest": settings.data_dir / "reports" / "latest_daily_learning_digest.json",
        "walk_forward": settings.data_dir / "reports" / "latest_walk_forward_validation.json",
        "session_retrospective": settings.data_dir / "reports" / "latest_session_retrospective.json",
    }
    artifact_rows = []
    for name, path in artifact_paths.items():
        payload = {}
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {"available": False, "error": "json invalido"}
        artifact_rows.append(
            {
                "artefacto": name,
                "disponible": bool(payload),
                "fecha": _local_datetime((payload or {}).get("as_of")),
                "resumen": _short(str((payload or {}).get("summary") or (payload or {}).get("metrics") or ""), 120),
            }
        )

    tab_runtime, tab_live, tab_queue, tab_hypotheses, tab_proposals, tab_report = st.tabs(
        ["Runtime", "Directo", "Cola", "Hipotesis", "Propuestas", "Informe"]
    )
    with tab_runtime:
        st.subheader("Agentes")
        st.dataframe(pd.DataFrame(runtime.describe_agents()), use_container_width=True, hide_index=True)
        st.subheader("Estado runtime")
        st.json(runtime_state or {})
        st.subheader("Artefactos de validacion")
        st.dataframe(pd.DataFrame(artifact_rows), use_container_width=True, hide_index=True)
        st.subheader("Validacion objetiva")
        objective_rows = []
        for item in validations[:12]:
            payload = item.get("payload") or {}
            evidence = payload.get("evidence")
            artifact_preview = ""
            if isinstance(evidence, dict):
                artifact_preview = str(evidence.get("artifacts") or evidence.get("artifact") or "")
            elif isinstance(evidence, list):
                artifact_preview = ", ".join(str(entry) for entry in evidence[:3] if entry)
            objective_rows.append(
                {
                    "iniciativa": item.get("initiative_id") or payload.get("initiative_key") or "-",
                    "estado": item.get("status"),
                    "objetivo": payload.get("objective_status") or "-",
                    "resumen": _short(payload.get("objective_summary") or payload.get("summary") or "", 140),
                    "artefacto": _short(artifact_preview, 110),
                }
            )
        if objective_rows:
            st.dataframe(pd.DataFrame(objective_rows), use_container_width=True, hide_index=True)
        else:
            st.info("No hay validaciones objetivas registradas todavia.")
    with tab_live:
        st.subheader("Conversacion y actividad")
        if refresh_interval_seconds > 0:
            st.caption(
                f"Vista en directo activa. Se refresca cada {refresh_interval_seconds}s y agrupa mensajes por iniciativa."
            )
        else:
            st.warning("El refresco automatico esta desactivado en la barra lateral. Activalo para ver nuevos mensajes en directo.")
        active_tasks = [item for item in tasks if item.get("status") not in {"COMPLETED", "CANCELLED", "FAILED"}]
        c_live_1, c_live_2, c_live_3 = st.columns(3)
        with c_live_1:
            _metric_card("Iniciativas activas", len([item for item in initiatives if item.get("status") not in {"CLOSED", "REJECTED"}]))
        with c_live_2:
            _metric_card("Mensajes", 0 if ci_activity.empty else len(ci_activity))
        with c_live_3:
            _metric_card("Ult. actualizacion", _local_time((runtime_state or {}).get("heartbeat_at")))
        st.caption("Cada bloque muestra la conversacion completa de una iniciativa: propuesta, respuestas de agentes y validacion.")
        st.subheader("Conversaciones por iniciativa")
        _render_ci_initiative_status_panels(
            ci_conversation_groups,
            validation_lookup=validation_lookup,
        )
        st.subheader("Tareas activas")
        if active_tasks:
            active_rows = []
            for item in active_tasks:
                active_rows.append(
                    {
                        "tarea": item.get("task_id"),
                        "agente": item.get("agent_name"),
                        "estado": item.get("status"),
                        "foco": (item.get("payload") or {}).get("focus") or "-",
                        "evento": item.get("event_id"),
                        "inicio": _local_datetime(item.get("started_at") or item.get("created_at")),
                    }
                )
            st.dataframe(pd.DataFrame(active_rows), use_container_width=True, hide_index=True)
        else:
            st.caption("No hay tareas activas en este momento.")
        st.subheader("Iniciativas con estado")
        if initiatives:
            initiative_rows = []
            for item in initiatives[:20]:
                initiative_rows.append(
                    {
                        "iniciativa": item.get("title"),
                        "estado": item.get("status"),
                        "meta": item.get("target_metric"),
                        "riesgo": item.get("risk_level"),
                        "decision": (item.get("latest_decision") or {}).get("decision"),
                        "proxima_accion": _short(item.get("next_action"), 80),
                        "evidencias": len(item.get("evidence") or []),
                    }
                )
            st.dataframe(pd.DataFrame(initiative_rows), use_container_width=True, hide_index=True)
        else:
            st.caption("Sin iniciativas activas.")
        if initiatives:
            initiative_status_rows = []
            for item in initiatives[:20]:
                initiative_status_rows.append(
                    {
                        "iniciativa": item.get("title"),
                        "estado": item.get("status"),
                        "responsable": item.get("owner_agent"),
                        "meta": item.get("target_metric"),
                        "riesgo": item.get("risk_level"),
                        "decision": (item.get("latest_decision") or {}).get("decision"),
                        "ultima_validacion": (validation_lookup.get(str(item.get("initiative_key") or item.get("initiative_id") or "")) or {}).get("status"),
                        "siguiente": _short(item.get("next_action"), 90),
                    }
                )
            st.dataframe(pd.DataFrame(initiative_status_rows), use_container_width=True, hide_index=True)
        with st.expander("Linea temporal completa"):
            if not ci_activity.empty:
                st.dataframe(
                    ci_activity[["hora", "agente", "evento", "mensaje"]],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("Sin mensajes todavia.")
    with tab_queue:
        st.subheader("Eventos")
        st.dataframe(pd.DataFrame(events), use_container_width=True, hide_index=True)
        st.subheader("Tareas")
        st.dataframe(pd.DataFrame(tasks), use_container_width=True, hide_index=True)
        st.subheader("Iniciativas")
        if initiatives:
            initiative_table = []
            for item in initiatives:
                initiative_table.append(
                    {
                        "iniciativa": item.get("title"),
                        "estado": item.get("status"),
                        "responsable": item.get("owner_agent"),
                        "meta": item.get("target_metric"),
                        "riesgo": item.get("risk_level"),
                        "decision": (item.get("latest_decision") or {}).get("decision"),
                        "siguiente": _short(item.get("next_action"), 90),
                    }
                )
            st.dataframe(pd.DataFrame(initiative_table), use_container_width=True, hide_index=True)
        else:
            st.info("No hay iniciativas guardadas.")
    with tab_hypotheses:
        if hypotheses:
            st.dataframe(pd.DataFrame(hypotheses), use_container_width=True, hide_index=True)
        else:
            st.info("No hay hipotesis abiertas.")
    with tab_proposals:
        if proposals:
            st.dataframe(_ci_proposals_dataframe(proposals), use_container_width=True, hide_index=True)
            if review:
                selected = st.selectbox(
                    "Revision humana",
                    [f"{item['proposal_id']} | {item['proposal_type']} | {item['target_component']}" for item in review],
                )
                item = review[[f"{p['proposal_id']} | {p['proposal_type']} | {p['target_component']}" for p in review].index(selected)]
                artifact = store.continuous_improvement_proposal_artifact(item["proposal_id"])
                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("Aprobar propuesta"):
                        store.update_continuous_improvement_proposal_status(
                            item["proposal_id"],
                            status="APPROVED",
                            actor="web",
                            reason="Aprobada manualmente desde Streamlit.",
                        )
                        st.rerun()
                with col_b:
                    if st.button("Rechazar propuesta"):
                        store.update_continuous_improvement_proposal_status(
                            item["proposal_id"],
                            status="REJECTED",
                            actor="web",
                            reason="Rechazada manualmente desde Streamlit.",
                        )
                        st.rerun()
                st.json(item)
                if artifact:
                    st.subheader("Artefacto sugerido")
                    st.code(artifact.get("content_text") or "", language="markdown")
        else:
            st.info("No hay propuestas guardadas.")
        st.subheader("Validaciones")
        st.dataframe(pd.DataFrame(validations), use_container_width=True, hide_index=True)
    with tab_report:
        if latest and latest.get("report"):
            st.json(latest["report"])
        else:
            st.info("No hay informe disponible.")


def page_logs() -> None:
    store = _store()
    _page_header("Logs", "Eventos recientes sin el ruido de CrewAI ni mensajes minuto a minuto sin actividad.")
    limit = st.slider("Lineas", 20, 1000, 100, 20)
    events = store.latest_events(limit)
    if events:
        st.dataframe(_events_dataframe(events), use_container_width=True, hide_index=True)
        with st.expander("Evento bruto"):
            labels = [
                f"{_local_datetime(item.get('created_at'))} | {item['agent']} | {item['event_type']}"
                for item in events
            ]
            selected = st.selectbox("Selecciona evento", labels)
            if selected:
                st.json(events[labels.index(selected)])
    else:
        st.info("No hay eventos.")


def page_llm() -> None:
    store = _store()
    settings = _settings()
    _page_header("LLM", "Contador diario de peticiones y tokens registrados.")
    limit = st.slider("Registros leidos", 100, 5000, 1000, 100)
    daily = _llm_daily_usage_dataframe(store, limit=int(limit))
    today = datetime.now(ZoneInfo(settings.local_timezone)).date().isoformat()
    today_row = daily[daily["fecha"] == today].iloc[0].to_dict() if not daily.empty and today in set(daily["fecha"]) else {}

    col1, col2 = st.columns(2)
    with col1:
        _metric_card("Peticiones hoy", int(today_row.get("peticiones") or 0))
    with col2:
        _metric_card("Tokens hoy", f"{int(today_row.get('tokens') or 0):,}")

    if daily.empty:
        st.info("Todavia no hay uso LLM registrado.")
        return

    st.dataframe(daily, use_container_width=True, hide_index=True)


def page_commands() -> None:
    _page_header("Comandos", "Lanzar o consultar las mismas acciones disponibles por consola.")
    status = _schedule_process_status()
    left, right = st.columns([2, 1])
    with left:
        st.subheader("Sistema desatendido")
        st.code(r".\.venv\Scripts\python.exe -m agente_bolsa.main schedule", language="powershell")
        st.write(f"Estado desde web: {'corriendo' if status['running'] else 'parado'}")
        if status.get("pid"):
            st.write(f"PID: {status['pid']}")
    with right:
        if st.button("Iniciar schedule"):
            result = _start_schedule()
            st.success(f"Schedule iniciado. PID: {result.get('pid')}")
        if st.button("Detener schedule iniciado desde web"):
            result = _stop_schedule()
            if result.get("stopped"):
                st.success(f"Schedule detenido. PID: {result.get('pid')}")
            else:
                st.info(result.get("reason"))

    st.subheader("Acciones rapidas")
    command_options = {
        "Estado general": ["status"],
        "Broker status": ["broker-status"],
        "Cartera": ["portfolio-status"],
        "Historico": ["trade-history", "--json"],
        "Aprendizaje": ["learning-status", "--update", "--json"],
        "Adaptativo": ["adaptive-status", "--json"],
        "Schedule status": ["schedule-status"],
    }
    choice = st.selectbox("Comando", list(command_options))
    if st.button("Ejecutar comando seleccionado"):
        with st.spinner("Ejecutando..."):
            code, output = _run_command(command_options[choice])
        if code == 0:
            st.success("Comando ejecutado.")
        else:
            st.error(f"Fallo con codigo {code}.")
        st.code(output or "(sin salida)", language="json" if output.strip().startswith("{") else "text")

    st.subheader("Catalogo completo")
    catalog = pd.DataFrame(available_command_catalog())
    st.dataframe(catalog, use_container_width=True, hide_index=True)


def page_config() -> None:
    settings = _settings()
    store = _store()
    _page_header("Configuracion", "Modo operativo, LLM, riesgo, broker y base de datos.")
    rows = [
        {"clave": "trading_mode", "valor": settings.trading_mode},
        {"clave": "allow_live_trading", "valor": settings.allow_live_trading},
        {"clave": "auto_paper_trading", "valor": settings.auto_paper_trading},
        {"clave": "require_human_approval", "valor": settings.require_human_approval},
        {"clave": "use_bracket_orders", "valor": settings.use_bracket_orders},
        {"clave": "broker", "valor": settings.broker},
        {"clave": "alpaca_paper", "valor": settings.alpaca_paper},
        {"clave": "alpaca_endpoint", "valor": settings.alpaca_endpoint},
        {"clave": "openai_model", "valor": settings.openai_model},
        {"clave": "openai_api_base", "valor": settings.openai_api_base},
        {"clave": "llm_local_fallback_model", "valor": settings.llm_local_fallback_model},
        {"clave": "llm_local_fallback_api_base", "valor": settings.llm_local_fallback_api_base},
        {"clave": "closed_market_study_universe", "valor": settings.closed_market_study_universe},
        {"clave": "closed_market_study_max_symbols", "valor": settings.closed_market_study_max_symbols},
        {"clave": "breakout_extra_symbols", "valor": ", ".join(settings.breakout_watchlist) or "-"},
        {"clave": "max_orders_per_cycle", "valor": settings.max_orders_per_cycle},
        {"clave": "max_daily_buy_orders", "valor": settings.max_daily_buy_orders},
        {"clave": "entry_quality_max_rsi", "valor": settings.entry_quality_max_rsi},
        {"clave": "entry_quality_max_sma20_distance", "valor": settings.entry_quality_max_sma20_distance},
        {"clave": "database", "valor": str(settings.database_path)},
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    latest_quality = _latest_report_json("latest_market_data_quality.json")
    latest_readiness = _latest_report_json("latest_live_readiness.json")
    latest_backup = _latest_report_json("latest_database_backup.json")
    st.subheader("Controles recientes")
    c1, c2, c3 = st.columns(3)
    with c1:
        summary = (latest_quality.get("payload") or {}).get("summary", {}) if latest_quality.get("available") else {}
        _metric_card("Cobertura datos", _pct(summary.get("coverage_ratio")) if summary else "-")
    with c2:
        summary = (latest_readiness.get("payload") or {}).get("summary", {}) if latest_readiness.get("available") else {}
        _metric_card("Live blocks", summary.get("blocks") if summary else "-")
    with c3:
        summary = (latest_backup.get("payload") or {}).get("summary", {}) if latest_backup.get("available") else {}
        _metric_card("Backup SQLite", summary.get("size_bytes") if summary else "-")
    st.subheader("SQLite")
    st.json(store.status())


def main() -> None:
    _setup_page()
    st.sidebar.title("Agente Bolsa")
    st.sidebar.caption("Panel local")
    refresh_interval_seconds = _auto_refresh_control()
    page_names = [
        "Dashboard",
        "Cartera",
        "Compras/Ventas",
        "Oportunidades",
        "Estudios",
        "Decisiones",
        "Rupturas",
        "Pre-earnings",
        "Historico",
        "Senales",
        "Aprendizaje",
        "Diario aprendizaje",
        "Aprendizaje operativo",
        "Mejora continua",
        "Adaptativo",
        "Backtest",
        "LLM",
        "Logs",
        "Comandos",
        "Configuracion",
    ]
    if "selected_page" not in st.session_state or st.session_state.selected_page not in page_names:
        st.session_state.selected_page = "Dashboard"
    page = st.sidebar.radio(
        "Vista",
        page_names,
        index=page_names.index(st.session_state.selected_page),
        key="selected_page",
    )
    _render_sidebar_version()
    if st.sidebar.button("Refrescar"):
        st.session_state.selected_page = page
        st.rerun()

    pages = {
        "Dashboard": page_dashboard,
        "Cartera": page_portfolio,
        "Compras/Ventas": page_recent_trades,
        "Oportunidades": page_opportunities,
        "Estudios": page_company_studies,
        "Decisiones": page_cycle_decisions,
        "Rupturas": page_breakouts,
        "Pre-earnings": page_pre_earnings,
        "Historico": page_history,
        "Senales": page_signals,
        "Aprendizaje": page_learning,
        "Diario aprendizaje": page_learning_diary,
        "Aprendizaje operativo": page_operational_learning,
        "Mejora continua": page_continuous_improvement,
        "Adaptativo": page_adaptive,
        "Backtest": page_backtest,
        "LLM": page_llm,
        "Logs": page_logs,
        "Comandos": page_commands,
        "Configuracion": page_config,
    }
    _render_refreshable_page(pages[page], refresh_interval_seconds)


if __name__ == "__main__":
    main()
