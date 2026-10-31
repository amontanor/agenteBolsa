"""P-L186H: shadow book observacional de cortos.

Registra entradas virtuales de setups short fuertes y las cierra por stop, take
o tiempo usando el precio del escaneo. No crea ordenes, no toca el broker y no
alimenta la decision; solo acumula evidencia para la promocion de la linea
corta.
"""

from __future__ import annotations

import json
import os
from datetime import date
from typing import Any

from agente_bolsa.config import Settings

SCHEMA_VERSION = "p-l186.short-shadow-book.v1"
LATEST_FILENAME = "latest_short_shadow_book.json"
MAX_CLOSED_ENTRIES = 300


def _book_path(settings: Settings):
    return settings.data_dir / "reports" / LATEST_FILENAME


def _load_book(settings: Settings) -> dict[str, Any]:
    path = _book_path(settings)
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "open": [], "closed": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema_version": SCHEMA_VERSION, "open": [], "closed": []}
    if not isinstance(payload, dict):
        return {"schema_version": SCHEMA_VERSION, "open": [], "closed": []}
    payload.setdefault("open", [])
    payload.setdefault("closed", [])
    payload["schema_version"] = SCHEMA_VERSION
    return payload


def _write_book(settings: Settings, payload: dict[str, Any]) -> None:
    path = _book_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed and parsed not in (float("inf"), float("-inf")) else None


def _candidate_price(candidate: dict[str, Any]) -> float | None:
    technical = candidate.get("technical_state") or {}
    return _number(technical.get("close")) or _number(candidate.get("close"))


def _candidate_risk(candidate: dict[str, Any]) -> tuple[float, float, float] | None:
    risk = candidate.get("risk_plan") or {}
    entry = _number(risk.get("entry_price"))
    stop = _number(risk.get("stop_loss"))
    take = _number(risk.get("take_profit"))
    if entry is None or stop is None or take is None:
        return None
    if not (0 < take < entry < stop):
        return None
    return entry, stop, take


def _candidates(report: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for bucket in ("top_shorts", "all_candidates"):
        for item in report.get(bucket, []) or []:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "").upper().strip()
            if not symbol or symbol in seen:
                continue
            if str(item.get("direction") or "").lower() != "short":
                continue
            seen.add(symbol)
            result.append(item)
    result.sort(key=lambda item: _number(item.get("score")) or 0.0, reverse=True)
    return result


def _days_between(start: str | None, end: str | None) -> int | None:
    try:
        return (date.fromisoformat(str(end)[:10]) - date.fromisoformat(str(start)[:10])).days
    except (TypeError, ValueError):
        return None


def update_short_shadow_book(
    settings: Settings,
    report: dict[str, Any],
    *,
    session_date: str | None = None,
) -> dict[str, Any]:
    """Update the virtual short book from one technical report.

    Purely observational: no broker, no Store, no orders. Fail-open by design;
    callers must not let a shadow failure block the cycle.
    """

    if not settings.shorts_shadow_enabled:
        return {"status": "disabled", "reason": "shorts_shadow_disabled"}
    session = str(session_date or report.get("as_of") or date.today().isoformat())[:10]
    book = _load_book(settings)
    candidates = _candidates(report)
    prices = {
        str(item.get("symbol") or "").upper(): _candidate_price(item)
        for item in candidates
    }
    prices = {symbol: price for symbol, price in prices.items() if price is not None}

    open_entries: list[dict[str, Any]] = []
    closed_entries: list[dict[str, Any]] = list(book.get("closed") or [])
    for entry in book.get("open") or []:
        if not isinstance(entry, dict):
            continue
        price = prices.get(str(entry.get("symbol") or "").upper())
        reason = None
        stop = _number(entry.get("stop"))
        take = _number(entry.get("take"))
        held_days = _days_between(entry.get("opened_session"), session)
        if price is not None and stop is not None and price >= stop:
            reason = "stop_loss"
        elif price is not None and take is not None and price <= take:
            reason = "take_profit"
        elif held_days is not None and held_days >= int(settings.short_max_days_held):
            reason = "time_stop"
        if reason is None:
            if price is not None:
                entry = {**entry, "last_price": price, "last_session": session}
            open_entries.append(entry)
            continue
        exit_price = price if price is not None else _number(entry.get("entry"))
        entry_price = _number(entry.get("entry"))
        pnl_pct = (
            (entry_price - exit_price) / entry_price
            if exit_price is not None and entry_price
            else None
        )
        closed_entries.append(
            {
                **entry,
                "status": "closed",
                "closed_session": session,
                "exit_price": exit_price,
                "reason": reason,
                "pnl_pct": round(pnl_pct, 6) if pnl_pct is not None else None,
            }
        )

    existing_symbols = {
        str(entry.get("symbol") or "").upper()
        for entry in open_entries
        if entry.get("opened_session") == session
    }
    closed_symbols_session = {
        str(entry.get("symbol") or "").upper()
        for entry in closed_entries
        if entry.get("closed_session") == session
    }
    max_open = max(10, int(settings.max_open_short_positions) * 5)
    added = 0
    for candidate in candidates:
        if len(open_entries) >= max_open:
            break
        symbol = str(candidate.get("symbol") or "").upper()
        if symbol in existing_symbols or symbol in closed_symbols_session:
            continue
        if str(candidate.get("setup_quality") or "").lower() != "strong":
            continue
        if (_number(candidate.get("score")) or 0.0) < 7.0:
            continue
        if candidate.get("blocked_auto_buy"):
            continue
        risk = _candidate_risk(candidate)
        price = _candidate_price(candidate)
        if risk is None or price is None or price < float(settings.short_min_price):
            continue
        entry, stop, take = risk
        open_entries.append(
            {
                "symbol": symbol,
                "direction": "short",
                "status": "open",
                "opened_session": session,
                "opened_at": str(report.get("as_of") or session),
                "entry": entry,
                "stop": stop,
                "take": take,
                "last_price": price,
                "last_session": session,
                "score": _number(candidate.get("score")),
                "setup_quality": candidate.get("setup_quality"),
                "signal_id": candidate.get("signal_id"),
                "candidate_id": candidate.get("candidate_id"),
            }
        )
        existing_symbols.add(symbol)
        added += 1

    closed_entries = closed_entries[-MAX_CLOSED_ENTRIES:]
    pnl_values = [
        _number(item.get("pnl_pct"))
        for item in closed_entries
        if _number(item.get("pnl_pct")) is not None
    ]
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": "updated",
        "session_date": session,
        "as_of": str(report.get("as_of") or ""),
        "open": open_entries,
        "closed": closed_entries,
        "summary": {
            "open_count": len(open_entries),
            "closed_count": len(closed_entries),
            "added": added,
            "win_rate": (
                round(sum(1 for value in pnl_values if value > 0) / len(pnl_values), 4)
                if pnl_values
                else None
            ),
            "avg_pnl_pct": (
                round(sum(pnl_values) / len(pnl_values), 6) if pnl_values else None
            ),
            "by_reason": {
                reason: sum(1 for item in closed_entries if item.get("reason") == reason)
                for reason in ("stop_loss", "take_profit", "time_stop")
            },
        },
        "authority": "observational_only_no_orders",
    }
    _write_book(settings, summary)
    return summary
