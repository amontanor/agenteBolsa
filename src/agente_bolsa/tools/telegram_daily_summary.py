"""Resumen postmarket enviado a Telegram sin autoridad sobre trading."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping
from typing import Any
from urllib.request import Request, urlopen

SCHEMA_VERSION = "p-l71.telegram-daily-summary.v1"
EVENT_TYPE = "telegram_daily_summary_sent"


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _money(value: Any) -> str:
    number = _finite(value)
    return "n/d" if number is None else f"{number:+,.2f} USD"


def _pct(value: Any) -> str:
    number = _finite(value)
    return "n/d" if number is None else f"{number:+.2%}"


def build_daily_summary(
    *,
    session_date: str,
    performance: Mapping[str, Any] | None,
    portfolio: Any,
) -> dict[str, Any]:
    """Construye el mensaje únicamente desde objetos ya obtenidos por PMR."""

    row = dict(performance or {})
    contract = row.get("performance_benchmark") or {}
    benchmark = contract.get("benchmark") or {}
    benchmark_quality = benchmark.get("data_quality")
    if isinstance(benchmark_quality, Mapping):
        benchmark_quality = benchmark_quality.get("status")
    benchmark_status = str(benchmark.get("comparison_status") or "").lower()
    if benchmark_status not in {"comparable", "provisional", "unavailable"}:
        benchmark_status = (
            "comparable"
            if benchmark_quality == "available"
            and benchmark.get("price_basis") in {"adjusted_ohlc", "close_unadjusted"}
            and benchmark.get("source")
            and benchmark.get("as_of")
            and benchmark.get("eod_authority")
            else "provisional"
            if _finite(row.get("spy_pct")) is not None
            else "unavailable"
        )
    spy_return = _finite(row.get("spy_pct"))
    benchmark_payload = {
        "symbol": str(benchmark.get("symbol") or "SPY").upper(),
        "instrument_label": benchmark.get("instrument_label") or "SPY (ETF S&P 500)",
        "daily_return": spy_return,
        "status": benchmark_status,
        "source": benchmark.get("source"),
        "price_basis": benchmark.get("price_basis"),
        "generated_at": contract.get("generated_at") or contract.get("captured_at"),
        "as_of": benchmark.get("as_of"),
        "eod_authority": benchmark.get("eod_authority"),
    }
    positions: list[dict[str, Any]] = []
    for position in getattr(portfolio, "positions", None) or []:
        positions.append(
            {
                "symbol": str(getattr(position, "symbol", "") or "").upper(),
                "market_value": _finite(getattr(position, "market_value", None)),
                "total_pl": _finite(getattr(position, "unrealized_pl", None)),
                "total_pl_pct": _finite(getattr(position, "unrealized_plpc", None)),
                "today_pl": _finite(getattr(position, "unrealized_intraday_pl", None)),
                "today_pl_pct": _finite(getattr(position, "unrealized_intraday_plpc", None)),
            }
        )
    positions.sort(key=lambda item: item["symbol"])
    payload = {
        "schema_version": SCHEMA_VERSION,
        "session_date": session_date,
        "account_daily_return": _finite(row.get("pnl_pct")),
        "spy_daily_return": spy_return,
        "benchmark": benchmark_payload,
        "equity": _finite(row.get("equity")) or _finite(getattr(portfolio, "portfolio_value", None)),
        "open_total_pl": sum(item["total_pl"] for item in positions if item["total_pl"] is not None)
        if any(item["total_pl"] is not None for item in positions)
        else None,
        "open_today_pl": sum(item["today_pl"] for item in positions if item["today_pl"] is not None)
        if any(item["today_pl"] is not None for item in positions)
        else None,
        "positions": positions,
    }
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    payload["content_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload


def format_daily_summary(payload: Mapping[str, Any]) -> str:
    benchmark = payload.get("benchmark") or {}
    benchmark_status = str(benchmark.get("status") or "unavailable")
    benchmark_value = _pct(benchmark.get("daily_return"))
    benchmark_suffix = ""
    if benchmark_status == "provisional":
        benchmark_suffix = " · Provisional"
    elif benchmark_status == "unavailable":
        benchmark_suffix = " · n/d"
    benchmark_label = str(benchmark.get("instrument_label") or "SPY (ETF S&P 500)")
    lines = [
        f"📊 Resumen agenteBolsa — {payload['session_date']}",
        "",
        f"Sistema (variación diaria de equity): {_pct(payload.get('account_daily_return'))}",
        f"{benchmark_label}: {benchmark_value}{benchmark_suffix}",
        f"Equity: {_money(payload.get('equity'))}",
        f"P/L abierto total: {_money(payload.get('open_total_pl'))}",
        f"P/L abierto hoy: {_money(payload.get('open_today_pl'))}",
        "",
        "Cartera abierta:",
    ]
    positions = list(payload.get("positions") or [])
    if not positions:
        lines.append("• Sin posiciones")
    for item in positions:
        lines.append(
            f"• {item['symbol']}: total {_money(item.get('total_pl'))} "
            f"({_pct(item.get('total_pl_pct'))}); hoy {_money(item.get('today_pl'))} "
            f"({_pct(item.get('today_pl_pct'))})"
        )
    return "\n".join(lines)


def send_telegram_message(
    *,
    token: str,
    chat_id: str,
    text: str,
    timeout_seconds: int,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """Envía texto por HTTPS sin exponer el token en payloads o excepciones."""

    request = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(
            {"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            ensure_ascii=False,
        ).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with opener(request, timeout=timeout_seconds) as response:
            result = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"telegram_send_failed:{type(exc).__name__}") from None
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError("telegram_send_rejected")
    message = result.get("result") if isinstance(result.get("result"), dict) else {}
    return {"ok": True, "message_id": message.get("message_id")}


def publish_daily_summary(settings: Any, store: Any, *, session_date: str, performance: Any, portfolio: Any) -> dict[str, Any]:
    if not bool(getattr(settings, "telegram_daily_summary_enabled", False)):
        return {"status": "disabled"}
    token = str(getattr(settings, "telegram_bot_token", "") or "").strip()
    chat_id = str(getattr(settings, "telegram_daily_summary_chat_id", "") or "").strip()
    if not token or not chat_id:
        return {"status": "unavailable", "reason": "telegram_configuration_missing"}
    event_id = f"telegram_daily_summary:{session_date}"
    existing = [
        row
        for row in store.agent_events(event_type_prefix=EVENT_TYPE, limit=20)
        if row.get("event_id") == event_id
    ]
    if existing:
        return {"status": "idempotent", "event_id": event_id}
    payload = build_daily_summary(session_date=session_date, performance=performance, portfolio=portfolio)
    sent = send_telegram_message(
        token=token,
        chat_id=chat_id,
        text=format_daily_summary(payload),
        timeout_seconds=int(getattr(settings, "telegram_timeout_seconds", 15)),
    )
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "session_date": session_date,
        "content_hash": payload["content_hash"],
        "message_id": sent.get("message_id"),
        "status": "sent",
    }
    persisted = store.record_append_only_event(
        event_id=event_id,
        event_type=EVENT_TYPE,
        cycle_id=session_date,
        payload=receipt,
    )
    return {"status": "sent", "event_id": event_id, "persistence": persisted}
