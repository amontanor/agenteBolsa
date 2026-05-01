"""Local Streamlit dashboard for the trading agent."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from agente_bolsa.config import get_settings
from agente_bolsa.market_calendar import MarketCalendar
from agente_bolsa.storage import Store
from agente_bolsa.tools.adaptive_tuning import adaptive_status, update_adaptive_config
from agente_bolsa.tools.backtest import build_symbol_backtest
from agente_bolsa.tools.broker import BrokerClientFactory
from agente_bolsa.tools.command_catalog import available_command_catalog
from agente_bolsa.tools.operational_learning import build_operational_learning_review
from agente_bolsa.tools.signal_learning import build_learning_status, update_signal_outcomes
from agente_bolsa.tools.trade_history import build_trade_history


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_START_DATE = "2026-04-01"
PORTFOLIO_CHART_START_DATE = "2026-04-28"


def _settings():
    return get_settings()


def _store() -> Store:
    settings = _settings()
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


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
    path = _pid_file()
    if not path.exists():
        return {"running": False, "pid": None}
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return {"running": False, "pid": None}
    running = _is_pid_running(pid)
    if not running:
        path.unlink(missing_ok=True)
    return {"running": running, "pid": pid if running else None}


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
    for signal in signals:
        symbol = str(signal.get("symbol") or "")
        current = latest.get(symbol)
        if current is None or str(signal.get("created_at") or "") > str(current.get("created_at") or ""):
            latest[symbol] = signal
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
) -> None:
    market_color, market_bg, market_border = _status_color(bool(market.get("is_open")))
    auto_color, auto_bg, auto_border = _status_color(bool(settings.auto_paper_trading))
    today_color, today_bg, today_border = _status_color((today_pl or 0.0) >= 0)
    refreshed = datetime.now(ZoneInfo(settings.local_timezone)).strftime("%H:%M:%S")
    equity_text = _money(current_equity) if current_equity is not None else "-"
    pct_text = _pct_signed(today_pct) if today_pct is not None else "-"
    st.markdown(
        f"""
        <div class="dashboard-header">
            <div>
                <div class="dashboard-title">Resumen operativo</div>
                <div class="dashboard-subtitle">Lo importante: resultado, cartera abierta y decisiones recientes.</div>
            </div>
            <div class="dashboard-pills">
                <span class="equity-pill">
                    Equity hoy <strong>{equity_text}</strong>
                    <em style="color:{today_color}; background:{today_bg}; border-color:{today_border};">{pct_text}</em>
                </span>
                <span style="color:{market_color}; background:{market_bg}; border-color:{market_border};">
                    Mercado {'abierto' if market.get("is_open") else 'cerrado'}
                </span>
                <span style="color:{auto_color}; background:{auto_bg}; border-color:{auto_border};">
                    Auto paper {'activo' if settings.auto_paper_trading else 'manual'}
                </span>
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


def _estimated_portfolio_value_series(
    history: dict[str, Any],
    current_equity: float | None,
    *,
    start_date: str = PORTFOLIO_CHART_START_DATE,
) -> pd.DataFrame:
    if current_equity is None:
        return pd.DataFrame(columns=["fecha", "valor_cartera", "P/L dia", "% dia", "label", "fuente"])
    daily_by_date: dict[str, float] = {}
    for day in history.get("days", []):
        date = str(day.get("date") or "")
        if not date or date < start_date:
            continue
        day_pl = round((_num(day.get("realized_pl")) or 0.0) + (_num(day.get("open_unrealized_pl")) or 0.0), 2)
        daily_by_date[date] = round(daily_by_date.get(date, 0.0) + day_pl, 2)
    daily_rows = [
        {"fecha": date, "P/L dia": day_pl}
        for date, day_pl in sorted(daily_by_date.items(), key=lambda item: item[0])
    ]
    total_pl = round(sum(item["P/L dia"] for item in daily_rows), 2)
    if not daily_rows:
        today = datetime.now(ZoneInfo(_settings().local_timezone)).date().isoformat()
        return pd.DataFrame(
            [
                {
                    "fecha": today,
                    "valor_cartera": round(current_equity, 2),
                    "P/L dia": 0.0,
                    "% dia": 0.0,
                    "label": f"{_money(current_equity)} ({_pct_signed(0.0)})",
                    "fuente": "estimado",
                }
            ]
        )

    baseline = float(current_equity) - total_pl
    running = baseline
    rows = []
    for item in daily_rows:
        previous_equity = running
        running += item["P/L dia"]
        day_pct = round(item["P/L dia"] / previous_equity, 6) if previous_equity else 0.0
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
) -> None:
    df = _portfolio_value_series_from_alpaca(portfolio_history or {}, current_equity)
    used_estimate = False
    if df.empty:
        df = _estimated_portfolio_value_series(history, current_equity)
        used_estimate = True
    if df.empty:
        st.markdown("<div class='empty-box'>Sin datos suficientes para graficar la cartera.</div>", unsafe_allow_html=True)
        return
    chart_df = df.copy()
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
        st.caption("Grafico estimado desde operaciones/P/L porque no se pudo leer portfolio history de Alpaca.")


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


def _auto_refresh_control() -> None:
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
    if interval:
        components.html(
            f"""
            <script>
            setTimeout(function() {{
                window.parent.location.reload();
            }}, {int(interval) * 1000});
            </script>
            """,
            height=0,
        )


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


def _metric_card(label: str, value: Any, delta: Any | None = None) -> None:
    st.metric(label, value, delta=delta)


def _setup_page() -> None:
    st.set_page_config(page_title="Agente Bolsa", page_icon=None, layout="wide")
    st.markdown(
        """
        <style>
        .block-container {padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1500px;}
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


def page_dashboard() -> None:
    settings = _settings()
    store = _store()
    market = MarketCalendar(settings.market_calendar, settings.local_timezone).status().as_dict()

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

    today_total = 0.0
    today_pct = 0.0
    if history:
        today = datetime.now(ZoneInfo(settings.local_timezone)).date().isoformat()
        today_row = next((item for item in history.get("days", []) if item.get("date") == today), {})
        today_realized = _num(today_row.get("realized_pl")) or 0.0
        today_open = _num(today_row.get("open_unrealized_pl")) or 0.0
        today_total = round(today_realized + today_open, 2)
        today_denominator = (
            _num(today_row.get("sell_notional"))
            or _num(today_row.get("buy_notional"))
            or (portfolio.portfolio_value if portfolio else 0)
        )
        today_pct = round(today_total / today_denominator, 4) if today_denominator else 0.0

    exposure = stats.get("exposure") if stats else None
    exposure_pct = stats.get("exposure_pct") if stats else None
    total_pl = _num(stats.get("total_pl")) if stats else 0.0
    total_pct = _num(stats.get("total_plpc_on_equity")) if stats else 0.0
    current_equity = _num(portfolio.portfolio_value) if portfolio else _num(stats.get("equity"))
    current_cash = _num(portfolio.cash) if portfolio else _num(stats.get("cash"))
    initial_equity = round(current_equity - total_pl, 2) if current_equity is not None and total_pl is not None else None
    today_tone = "good" if today_total > 0 else "bad" if today_total < 0 else "neutral"
    total_tone = "good" if (total_pl or 0) > 0 else "bad" if (total_pl or 0) < 0 else "neutral"

    _dashboard_header(
        market,
        settings,
        current_equity=current_equity,
        today_pl=today_total,
        today_pct=today_pct,
    )

    latest_orders = _latest_order_details(limit=12)
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
            _portfolio_table(position_rows)

        st.markdown("<div class='dashboard-divider'></div>", unsafe_allow_html=True)
        with st.container(border=True):
            _section_title("Valor de cartera", "Evolucion diaria desde 2026-04-28. Las etiquetas muestran el valor total.")
            _portfolio_value_chart(history, portfolio.portfolio_value if portfolio else None, portfolio_history)
            p1, p2, p3 = st.columns(3)
            with p1:
                _compact_metric("P/L desde abril", _money(stats.get("total_pl")), _pct(stats.get("total_plpc_on_equity")), total_tone)
            with p2:
                open_pl = _num(stats.get("unrealized_pl")) if stats else 0.0
                _compact_metric("P/L abierto", _money(open_pl), tone="good" if open_pl > 0 else "bad" if open_pl < 0 else "neutral")
            with p3:
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
        col1, col2, col3, col4 = st.columns(4)
        symbol = col1.text_input("Simbolo", "AAPL").upper()
        start = col2.text_input("Desde", "2024-01-01")
        min_score = col3.number_input("Score minimo", min_value=1, max_value=30, value=7)
        max_holding = col4.number_input("Max dias", min_value=1, max_value=60, value=10)
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
            )
        metrics = result.get("metrics", {})
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            _metric_card("Trades", metrics.get("trades"))
        with c2:
            _metric_card("P/L", _pct(metrics.get("total_return")))
        with c3:
            _metric_card("Hit rate", _pct(metrics.get("hit_rate")))
        with c4:
            _metric_card("Sharpe", metrics.get("sharpe"))
        st.json(metrics)
        trades = pd.DataFrame(result.get("trades", []))
        if not trades.empty:
            st.dataframe(trades, use_container_width=True, hide_index=True)


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


def page_logs() -> None:
    store = _store()
    _page_header("Logs", "Eventos recientes sin el ruido de CrewAI ni mensajes minuto a minuto sin actividad.")
    limit = st.slider("Lineas", 20, 1000, 100, 20)
    events = store.latest_events(limit)
    if events:
        st.dataframe(_events_dataframe(events), use_container_width=True, hide_index=True)
        with st.expander("Evento bruto"):
            labels = [f"{item['created_at']} | {item['agent']} | {item['event_type']}" for item in events]
            selected = st.selectbox("Selecciona evento", labels)
            if selected:
                st.json(events[labels.index(selected)])
    else:
        st.info("No hay eventos.")


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
    st.subheader("SQLite")
    st.json(store.status())


def main() -> None:
    _setup_page()
    st.sidebar.title("Agente Bolsa")
    st.sidebar.caption("Panel local")
    _auto_refresh_control()
    page = st.sidebar.radio(
        "Vista",
        [
            "Dashboard",
            "Cartera",
            "Compras/Ventas",
            "Decisiones",
            "Rupturas",
            "Historico",
            "Senales",
            "Aprendizaje",
            "Diario aprendizaje",
            "Aprendizaje operativo",
            "Adaptativo",
            "Backtest",
            "Logs",
            "Comandos",
            "Configuracion",
        ],
    )
    if st.sidebar.button("Refrescar"):
        st.rerun()

    pages = {
        "Dashboard": page_dashboard,
        "Cartera": page_portfolio,
        "Compras/Ventas": page_recent_trades,
        "Decisiones": page_cycle_decisions,
        "Rupturas": page_breakouts,
        "Historico": page_history,
        "Senales": page_signals,
        "Aprendizaje": page_learning,
        "Diario aprendizaje": page_learning_diary,
        "Aprendizaje operativo": page_operational_learning,
        "Adaptativo": page_adaptive,
        "Backtest": page_backtest,
        "Logs": page_logs,
        "Comandos": page_commands,
        "Configuracion": page_config,
    }
    pages[page]()


if __name__ == "__main__":
    main()
