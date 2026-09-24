"""Resumen postmarket enviado a Telegram sin autoridad sobre trading."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any
from urllib.request import Request, urlopen

from .equity_metrics import daily_equity_change
from .opening_performance import opening_performance_context
from .performance_benchmark import overlay_eod_benchmark

SCHEMA_VERSION = "p-l70.telegram-daily-summary.v2"
OPENING_SCHEMA_VERSION = "p-l72.telegram-daily-summary.v3"
EVENT_TYPE = "telegram_daily_summary_sent"
TELEGRAM_MESSAGE_LIMIT_UNITS = 4096
# Backwards-compatible name for callers/tests; enforcement uses UTF-16 units.
MAX_TELEGRAM_MESSAGE_LENGTH = TELEGRAM_MESSAGE_LIMIT_UNITS


def _telegram_utf16_units(text: str) -> int:
    """Return the conservative Telegram length in UTF-16 code units."""

    return len(text.encode("utf-16-le", errors="surrogatepass")) // 2


def _rendered_text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_EOD_AUTHORITIES = {
    "confirmed",
    "eod_final",
    "next_session_confirmed",
    "post_session_cache",
}


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


def _balance(value: Any) -> str:
    number = _finite(value)
    return "n/d" if number is None else f"{number:,.2f} USD"


def _pct(value: Any) -> str:
    number = _finite(value)
    return "n/d" if number is None else f"{number:+.2%}"


def _pp(value: Any) -> str:
    number = _finite(value)
    return "n/d" if number is None else f"{number * 100:+.2f} pp"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _performance_contract(row: Mapping[str, Any]) -> Mapping[str, Any]:
    contract = row.get("performance_benchmark")
    if isinstance(contract, Mapping):
        return contract
    nested = _mapping(row.get("payload")).get("performance_benchmark")
    return nested if isinstance(nested, Mapping) else {}


def _coverage(values: list[float | None]) -> tuple[float | None, dict[str, Any]]:
    total = len(values)
    known = [value for value in values if value is not None]
    if total == 0:
        return 0.0, {"known": 0, "total": 0, "status": "not_applicable"}
    if not known:
        return None, {"known": 0, "total": total, "status": "unavailable"}
    status = "complete" if len(known) == total else "partial"
    return sum(known), {"known": len(known), "total": total, "status": status}


def _comparison_contract(
    *,
    row: Mapping[str, Any],
    contract: Mapping[str, Any],
    account_daily_return: float | None,
    spy_daily_return: float | None,
) -> tuple[str, list[str], float | None]:
    benchmark = _mapping(contract.get("benchmark"))
    explicit_status = str(
        row.get("comparison_status")
        or contract.get("comparison_status")
        or _mapping(contract.get("comparison")).get("comparison_status")
        or ""
    ).strip().lower()
    basis = str(benchmark.get("price_basis") or "").strip().lower()
    raw_quality = benchmark.get("data_quality")
    if isinstance(raw_quality, Mapping):
        quality = str(raw_quality.get("status") or raw_quality.get("quality") or "").strip().lower()
    else:
        quality = str(raw_quality or "").strip().lower()
    previous_close = _finite(benchmark.get("previous_close"))
    close = _finite(benchmark.get("close"))
    reason_codes: list[str] = []
    if account_daily_return is None:
        reason_codes.append("account_daily_return_unavailable")
    if spy_daily_return is None:
        reason_codes.append("spy_daily_return_unavailable")
    if previous_close is None or previous_close <= 0 or close is None or close <= 0:
        reason_codes.append("benchmark_pair_unavailable")
    if basis not in {"adjusted_ohlc", "close_unadjusted"}:
        reason_codes.append("benchmark_price_basis_not_comparable")
    if quality not in {"available", "complete"}:
        reason_codes.append("benchmark_quality_not_comparable")
    if not benchmark.get("source"):
        reason_codes.append("benchmark_source_unavailable")
    if not benchmark.get("as_of"):
        reason_codes.append("benchmark_as_of_unavailable")
    numeric = account_daily_return is not None and spy_daily_return is not None
    comparable_inputs = numeric and not reason_codes
    comparable = comparable_inputs and explicit_status not in {"pending", "partial", "unavailable", "conflict"}
    status = "comparable" if comparable else "provisional" if numeric else "unavailable"
    difference = account_daily_return - spy_daily_return if numeric else None
    return status, sorted(set(reason_codes)), difference


def _position_group(total_pl: float | None) -> str:
    if total_pl is None:
        return "incomplete"
    if total_pl > 0:
        return "profit"
    if total_pl < 0:
        return "loss"
    return "unchanged"


def _position_sort_key(item: Mapping[str, Any]) -> tuple[float, str]:
    total_pl = _finite(item.get("total_pl"))
    return (-(abs(total_pl) if total_pl is not None else 0.0), str(item.get("symbol") or ""))


def _grouped_positions(payload: Mapping[str, Any]) -> list[tuple[str, str, list[dict[str, Any]]]]:
    labels = (
        ("profit", "🟢 En beneficio"),
        ("loss", "🔴 En pérdida"),
        ("unchanged", "⚪ Sin cambio"),
        ("incomplete", "⚠️ Datos incompletos"),
    )
    groups = {key: [] for key, _label in labels}
    for item in payload.get("positions") or []:
        if isinstance(item, Mapping):
            groups[_position_group(_finite(item.get("total_pl")))].append(dict(item))
    return [(key, label, sorted(groups[key], key=_position_sort_key)) for key, label in labels if groups[key]]


def _position_line(item: Mapping[str, Any]) -> str:
    return (
        f"• {item.get('symbol') or '-'}  Total {_money(item.get('total_pl'))} "
        f"({_pct(item.get('total_pl_pct'))}) · Hoy {_money(item.get('today_pl'))} "
        f"({_pct(item.get('today_pl_pct'))})"
    )


def _date_label(session_date: Any) -> str:
    try:
        value = date.fromisoformat(str(session_date))
    except (TypeError, ValueError):
        return str(session_date or "n/d")
    months = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
    return f"{value.day:02d} {months[value.month - 1]} {value.year}"
def _canonical_eod_benchmark(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Devuelve solo el benchmark EOD ya proyectado y autoritativo.

    Los escalares legacy del nivel superior son deliberadamente ignorados:
    pueden pertenecer a una captura distinta o a un cache same-day mutable.
    ``eod_overlay`` prueba que el consumidor pasó por la frontera común de
    proyección antes de construir el mensaje.
    """

    contract = _performance_contract(row)
    if not isinstance(contract, Mapping):
        return None
    overlay = contract.get("eod_overlay") or {}
    benchmark = contract.get("benchmark") or {}
    if not isinstance(overlay, Mapping) or not isinstance(benchmark, Mapping):
        return None
    if str(overlay.get("status") or "").lower() not in {"available", "comparable"}:
        return None
    if str(benchmark.get("comparison_status") or "").lower() != "comparable":
        return None
    if str(benchmark.get("eod_authority") or "").lower() not in _EOD_AUTHORITIES:
        return None
    quality = benchmark.get("data_quality")
    if isinstance(quality, Mapping):
        quality = quality.get("status")
    if str(quality or "").lower() != "available":
        return None
    if benchmark.get("price_basis") not in {"adjusted_ohlc", "close_unadjusted"}:
        return None
    if not str(benchmark.get("source") or "").strip() or not str(benchmark.get("as_of") or "").strip():
        return None
    daily_return = _finite(benchmark.get("daily_return"))
    if daily_return is None:
        return None
    return dict(benchmark)


def build_daily_summary(
    *,
    session_date: str,
    performance: Mapping[str, Any] | None,
    portfolio: Any,
    opening_performance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Construye el mensaje únicamente desde objetos ya obtenidos por PMR."""

    row = dict(performance) if isinstance(performance, Mapping) else {}
    contract = _performance_contract(row)
    account = _mapping(contract.get("account"))
    raw_benchmark = _mapping(contract.get("benchmark"))
    canonical_benchmark = _canonical_eod_benchmark(row)
    benchmark = canonical_benchmark or raw_benchmark
    overlay_present = isinstance(contract.get("eod_overlay"), Mapping)
    opening = _mapping(opening_performance)
    opening_account = _mapping(opening.get("account_current"))
    opening_comparison = _mapping(opening.get("current"))
    opening_available = _finite(opening_account.get("system_pct")) is not None
    equity = _finite(opening_account.get("current_equity")) if opening_available else None
    if equity is None:
        equity = _finite(account.get("equity"))
    if equity is None:
        equity = _finite(row.get("equity"))
    if equity is None:
        equity = _finite(getattr(portfolio, "portfolio_value", None))
    previous_equity = _finite(opening_account.get("opening_equity")) if opening_available else None
    daily_metric = daily_equity_change(
        equity,
        getattr(portfolio, "previous_close_equity", None),
        source="Alpaca account.last_equity",
    )
    provider_previous_close = _finite(getattr(portfolio, "previous_close_equity", None))
    if opening_available:
        account_daily_return = _finite(opening_account.get("system_pct"))
        equity_delta = (
            equity - previous_equity
            if equity is not None and previous_equity is not None
            else None
        )
        account_daily_return_source = "session_open_snapshot"
    elif provider_previous_close is not None:
        previous_equity = _finite(daily_metric.get("previous_close_equity"))
        account_daily_return = _finite(daily_metric.get("daily_equity_return"))
        equity_delta = _finite(daily_metric.get("daily_equity_pl"))
        account_daily_return_source = "alpaca_account.last_equity" if account_daily_return is not None else "unavailable"
    else:
        previous_equity = _finite(account.get("previous_equity"))
        exact_daily_return = (
            equity / previous_equity - 1.0
            if equity is not None and previous_equity is not None and previous_equity > 0
            else None
        )
        legacy_daily_return = _finite(row.get("pnl_pct"))
        account_daily_return = exact_daily_return if exact_daily_return is not None else legacy_daily_return
        equity_delta = equity - previous_equity if exact_daily_return is not None else None
        account_daily_return_source = (
            "performance_benchmark.account_equity_pair"
            if exact_daily_return is not None
            else "legacy_percentage"
            if legacy_daily_return is not None
            else "unavailable"
        )
    spy_daily_return = (
        _finite(opening_comparison.get("spy_pct"))
        if opening_available
        else _finite(canonical_benchmark.get("daily_return"))
        if canonical_benchmark
        else None
        if overlay_present
        else _finite(raw_benchmark.get("daily_return"))
    )
    if opening_available:
        comparison_reasons = [] if spy_daily_return is not None else ["spy_opening_interval_unavailable"]
        comparison_status = "in_progress" if spy_daily_return is not None else "unavailable"
        difference = account_daily_return - spy_daily_return if spy_daily_return is not None else None
    else:
        comparison_status, comparison_reasons, difference = _comparison_contract(
            row=row,
            contract=contract,
            account_daily_return=account_daily_return,
            spy_daily_return=spy_daily_return,
        )
    benchmark_status = (
        "in_progress"
        if opening_available and spy_daily_return is not None
        else "comparable"
        if canonical_benchmark is not None
        else comparison_status
        if not overlay_present
        else "unavailable"
    )
    benchmark_payload = {
        "symbol": str(benchmark.get("symbol") or "SPY").upper(),
        "instrument_label": benchmark.get("instrument_label") or "SPY (ETF S&P 500)",
        "daily_return": spy_daily_return,
        "status": benchmark_status,
        "source": (
            opening_comparison.get("spy_source") if opening_available else benchmark.get("source")
        ),
        "price_basis": (
            opening_comparison.get("price_basis") if opening_available else benchmark.get("price_basis")
        ),
        "generated_at": contract.get("generated_at") or contract.get("captured_at"),
        "as_of": (
            opening_comparison.get("spy_end_at") if opening_available else benchmark.get("as_of")
        ),
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
    positions.sort(key=lambda item: (_position_group(item.get("total_pl")), _position_sort_key(item)))
    open_total_pl, open_total_coverage = _coverage([item["total_pl"] for item in positions])
    open_today_pl, open_today_coverage = _coverage([item["today_pl"] for item in positions])
    groups = _grouped_positions({"positions": positions})
    payload = {
        "schema_version": OPENING_SCHEMA_VERSION if opening_available else SCHEMA_VERSION,
        "session_date": session_date,
        "account_daily_return": account_daily_return,
        "account_daily_return_source": account_daily_return_source,
        "daily_equity_pl": equity_delta,
        "daily_equity_return": account_daily_return,
        "daily_equity_source": daily_metric.get("source"),
        "equity": equity,
        "previous_equity": previous_equity,
        "equity_delta": equity_delta,
        "spy_daily_return": spy_daily_return,
        "benchmark": benchmark_payload,
        "comparison_status": comparison_status,
        "comparison_reason_codes": comparison_reasons,
        "comparison_difference": difference,
        "benchmark_source": (
            opening_comparison.get("spy_source") if opening_available else benchmark.get("source")
        ),
        "benchmark_price_basis": (
            opening_comparison.get("price_basis") if opening_available else benchmark.get("price_basis")
        ),
        "benchmark_as_of": (
            opening_comparison.get("spy_end_at") if opening_available else benchmark.get("as_of")
        ),
        "interval_start_at": opening_account.get("system_start_at") if opening_available else None,
        "interval_end_at": opening_account.get("system_end_at") if opening_available else None,
        "open_total_pl": open_total_pl,
        "open_total_pl_coverage": open_total_coverage,
        "open_today_pl": open_today_pl,
        "open_today_pl_coverage": open_today_coverage,
        "position_groups": {key: len(items) for key, _label, items in groups},
        "positions": positions,
    }
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    payload["content_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload


def format_daily_summary(payload) -> str:
    """Resumen compacto P-L129: una linea por bloque, sin redundancia."""
    comparison_status = str(payload.get("comparison_status") or "unavailable")
    status_word = {
        "comparable": "comparable",
        "in_progress": "en curso",
        "provisional": "provisional",
    }.get(comparison_status, "n/d")
    spy_daily_return = payload.get("spy_daily_return")
    difference = payload.get("comparison_difference")
    if spy_daily_return is None:
        spy_line = "SP500 n/d (sin datos comparables)"
    else:
        spy_line = "SP500 " + _pct(spy_daily_return)
        if difference is not None and comparison_status in {"comparable", "provisional", "in_progress"}:
            direction = "por debajo" if difference < 0 else "por encima"
            spy_line += " - vas " + _pp(abs(difference)) + " " + direction
        spy_line += " (" + status_word + ")"
    positions = list(payload.get("positions") or [])
    def _mover_key(item):
        for field in ("today_pl", "total_pl"):
            value = item.get(field)
            if isinstance(value, (int, float)):
                return abs(value)
        return -1.0
    movers = sorted(positions, key=_mover_key, reverse=True)
    total_count = len(positions)
    if not movers:
        positions_block = ["Sin posiciones abiertas."]
    else:
        shown = []
        for item in movers[:3]:
            pl = item.get("today_pl")
            pl = pl if isinstance(pl, (int, float)) else item.get("total_pl")
            shown.append(str(item.get("symbol", "?")) + " " + _money(pl))
        partial = any(
            str((payload.get(key) or {}).get("status") or "") == "partial"
            for key in ("open_total_pl_coverage", "open_today_pl_coverage")
        )
        positions_block = [
            "Abiertas (" + str(total_count) + "): total " + _money(payload.get("open_total_pl"))
            + " - hoy " + _money(payload.get("open_today_pl"))
            + (" - parcial" if partial else ""),
            "Top: " + " - ".join(shown) + ((" - +" + str(total_count - 3) + " mas") if total_count > 3 else ""),
        ]
    full_lines = [
        "Resumen " + _date_label(payload.get("session_date")),
        "",
        "Cuenta",
        "- Equity: " + _balance(payload.get("equity"))
        + " (" + _money(payload.get("equity_delta")) + " / " + _pct(payload.get("account_daily_return")) + ")",
        "- " + spy_line,
        "",
    ] + positions_block
    if comparison_status == "provisional":
        full_lines.extend(["", "SP500 provisional: base no plenamente comparable."])
    elif comparison_status == "unavailable":
        full_lines.extend(["", "SP500 n/d por falta de datos comparables."])
    full_text = chr(10).join(full_lines)
    if _telegram_utf16_units(full_text) <= TELEGRAM_MESSAGE_LIMIT_UNITS:
        return full_text
    footer_template = chr(10) + chr(10) + "Mensaje abreviado: {omitted} posiciones omitidas."
    visible_lines = list(full_lines)
    while visible_lines and _telegram_utf16_units(chr(10).join(visible_lines) + footer_template.format(omitted=total_count)) > TELEGRAM_MESSAGE_LIMIT_UNITS:
        visible_lines.pop()
    return chr(10).join(visible_lines) + footer_template.format(omitted=total_count)
def send_telegram_message(
    *,
    token: str,
    chat_id: str,
    text: str,
    timeout_seconds: int,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """Envía texto por HTTPS sin exponer el token en payloads o excepciones."""

    if _telegram_utf16_units(text) > TELEGRAM_MESSAGE_LIMIT_UNITS:
        raise ValueError("telegram_message_too_long")

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
    projected_performance = performance
    if isinstance(performance, Mapping):
        # Both the 22:05 job and the PMR fallback call this same boundary.
        # Projection is local/read-only; failure must not make a stale scalar
        # authoritative, so the builder degrades to unavailable.
        projected_performance = overlay_eod_benchmark(performance, settings)
    try:
        opening = opening_performance_context(
            settings,
            store,
            current_equity=getattr(portfolio, "portfolio_value", None),
        )
    except Exception:
        opening = {}
    payload = build_daily_summary(
        session_date=session_date,
        performance=projected_performance,
        portfolio=portfolio,
        opening_performance=opening,
    )
    text = format_daily_summary(payload)
    sent = send_telegram_message(
        token=token,
        chat_id=chat_id,
        text=text,
        timeout_seconds=int(getattr(settings, "telegram_timeout_seconds", 15)),
    )
    receipt = {
        "schema_version": payload["schema_version"],
        "session_date": session_date,
        "content_hash": payload["content_hash"],
        "message_id": sent.get("message_id"),
        "message_length": len(text),
        "message_utf16_units": _telegram_utf16_units(text),
        "text": text,
        "text_sha256": _rendered_text_sha256(text),
        "positions_total": len(payload.get("positions") or []),
        "truncated": "Mensaje abreviado:" in text,
        "status": "sent",
    }
    persisted = store.record_append_only_event(
        event_id=event_id,
        event_type=EVENT_TYPE,
        cycle_id=session_date,
        payload=receipt,
    )
    return {"status": "sent", "event_id": event_id, "persistence": persisted}
