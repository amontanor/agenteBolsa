"""Notificaciones Telegram de fills reconciliados, sin autoridad de trading."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

from .telegram_daily_summary import send_telegram_message

SCHEMA_VERSION = "p-l66.telegram-trade-fill.v1"
EVENT_TYPE = "telegram_trade_fill_sent"


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _payload(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _filled_price(payload: Mapping[str, Any]) -> float | None:
    reconciled = payload.get("broker_order_reconciled")
    broker = payload.get("broker_order")
    for source in (reconciled, broker):
        if isinstance(source, Mapping):
            price = _finite(source.get("filled_avg_price"))
            if price is not None and price > 0:
                return price
    return None


def _source_plan_id(payload: Mapping[str, Any]) -> str | None:
    plan = payload.get("plan")
    if not isinstance(plan, Mapping):
        return None
    plan_payload = plan.get("payload")
    if not isinstance(plan_payload, Mapping):
        return None
    risk = plan_payload.get("risk_decision")
    checks = risk.get("checks") if isinstance(risk, Mapping) else None
    for source in (checks, plan_payload, plan):
        if isinstance(source, Mapping):
            value = str(source.get("source_plan_id") or "").strip()
            if value:
                return value
    return None


def build_trade_fill(store: Any, change: Mapping[str, Any]) -> dict[str, Any] | None:
    """Construye un fill canónico; nunca enlaza una salida por símbolo/fecha."""

    if str(change.get("new") or "").lower() != "filled":
        return None
    broker_order_id = str(change.get("broker_order_id") or "").strip()
    if not broker_order_id:
        return None
    fill = change.get("fill") if isinstance(change.get("fill"), Mapping) else {}
    side = str(change.get("side") or "").lower().removeprefix("orderside.")
    exit_or_entry = _finite(fill.get("filled_avg_price"))
    qty = _finite(fill.get("filled_qty"))
    with store.connect() as conn:
        row = conn.execute(
            "SELECT payload_json FROM broker_orders WHERE broker_order_id = ?",
            (broker_order_id,),
        ).fetchone()
    current_payload = _payload(row["payload_json"]) if row else {}
    if exit_or_entry is None:
        exit_or_entry = _filled_price(current_payload)

    entry_price = exit_or_entry if side == "buy" else None
    entry_link_status = "self_fill" if side == "buy" and entry_price is not None else "unavailable"
    source_plan_id = _source_plan_id(current_payload) if side == "sell" else None
    if side == "sell" and source_plan_id:
        with store.connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM broker_orders
                WHERE plan_id = ?
                  AND lower(side) IN ('buy', 'orderside.buy')
                  AND lower(status) IN ('filled', 'orderstatus.filled')
                ORDER BY broker_order_id
                """,
                (source_plan_id,),
            ).fetchall()
        prices = [_filled_price(_payload(item["payload_json"])) for item in rows]
        valid_prices = [price for price in prices if price is not None]
        if len(rows) == 1 and len(valid_prices) == 1:
            entry_price = valid_prices[0]
            entry_link_status = "exact_source_plan"
        elif len(rows) > 1:
            entry_link_status = "ambiguous_source_plan"

    gross_pl = None
    gross_pl_pct = None
    if side == "sell" and entry_price and exit_or_entry is not None and qty is not None:
        gross_pl = (exit_or_entry - entry_price) * qty
        gross_pl_pct = (exit_or_entry / entry_price) - 1.0
    return {
        "schema_version": SCHEMA_VERSION,
        "broker_order_id": broker_order_id,
        "plan_id": change.get("plan_id"),
        "cycle_id": change.get("cycle_id"),
        "symbol": str(change.get("symbol") or "").upper(),
        "side": side,
        "filled_qty": qty,
        "filled_avg_price": exit_or_entry,
        "filled_at": fill.get("filled_at"),
        "source_plan_id": source_plan_id,
        "entry_price": entry_price,
        "entry_link_status": entry_link_status,
        "gross_pl": gross_pl,
        "gross_pl_pct": gross_pl_pct,
    }


def format_trade_fill(payload: Mapping[str, Any]) -> str:
    side = str(payload.get("side") or "")
    qty = _finite(payload.get("filled_qty"))
    price = _finite(payload.get("filled_avg_price"))
    symbol = str(payload.get("symbol") or "-")
    qty_text = "n/d" if qty is None else f"{qty:g}"
    price_text = "n/d" if price is None else f"${price:,.4f}"
    if side == "buy":
        return f"🟢 COMPRA ejecutada\n{symbol} · {qty_text} acciones\nEntrada real: {price_text}"
    entry = _finite(payload.get("entry_price"))
    pl = _finite(payload.get("gross_pl"))
    pl_pct = _finite(payload.get("gross_pl_pct"))
    entry_text = "n/d" if entry is None else f"${entry:,.4f}"
    pl_text = "n/d" if pl is None else f"{pl:+,.2f} USD"
    pct_text = "n/d" if pl_pct is None else f"{pl_pct:+.2%}"
    return (
        f"🔴 VENTA ejecutada\n{symbol} · {qty_text} acciones\n"
        f"Entrada real: {entry_text}\nSalida real: {price_text}\n"
        f"P/L bruto: {pl_text} ({pct_text})"
    )


def publish_trade_fill_notifications(settings: Any, store: Any, changes: list[dict[str, Any]]) -> dict[str, Any]:
    """Publica fills nuevos tras su commit local; errores externos son fail-open."""

    if not bool(getattr(settings, "telegram_trade_notifications_enabled", False)):
        return {"status": "disabled", "sent": 0}
    token = str(getattr(settings, "telegram_bot_token", "") or "").strip()
    chat_id = str(getattr(settings, "telegram_daily_summary_chat_id", "") or "").strip()
    if not token or not chat_id:
        return {"status": "unavailable", "reason": "telegram_configuration_missing", "sent": 0}
    sent = 0
    errors: list[dict[str, str]] = []
    for change in changes:
        payload = build_trade_fill(store, change)
        if payload is None:
            continue
        event_id = f"telegram_trade_fill:{payload['broker_order_id']}"
        existing = [
            row
            for row in store.agent_events(event_type_prefix=EVENT_TYPE, limit=100)
            if row.get("event_id") == event_id
        ]
        if existing:
            continue
        text = format_trade_fill(payload)
        content_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()
        claim = store.claim_trade_fill_notification(
            broker_order_id=str(payload["broker_order_id"]),
            content_hash=content_hash,
            cycle_id=str(payload.get("cycle_id") or ""),
        )
        if claim.get("status") != "acquired":
            continue
        send_accepted = False
        try:
            response = send_telegram_message(
                token=token,
                chat_id=chat_id,
                text=text,
                timeout_seconds=int(getattr(settings, "telegram_timeout_seconds", 15)),
            )
            send_accepted = True
            receipt = store.record_append_only_event(
                event_id=event_id,
                event_type=EVENT_TYPE,
                cycle_id=str(payload.get("cycle_id") or ""),
                payload={
                    "schema_version": SCHEMA_VERSION,
                    "broker_order_id": payload["broker_order_id"],
                    "message_id": response.get("message_id"),
                    "status": "sent",
                    "content_hash": content_hash,
                },
            )
            if receipt.get("status") == "conflict":
                raise RuntimeError("telegram_trade_fill_receipt_conflict")
            sent += 1
        except Exception as exc:  # noqa: BLE001 - Telegram nunca afecta trading.
            # A failure known to have occurred before acceptance is retryable.
            # If receipt persistence failed after an accepted send, keeping the
            # claim avoids promising exactly-once or sending an automatic duplicate.
            reason = f"telegram_trade_fill_failed:{type(exc).__name__}"
            if not send_accepted:
                try:
                    store.release_trade_fill_notification_claim(
                        claim_id=str(claim.get("claim_id") or ""),
                        broker_order_id=str(payload["broker_order_id"]),
                        content_hash=content_hash,
                        cycle_id=str(payload.get("cycle_id") or ""),
                        reason=reason,
                    )
                except Exception as release_exc:  # noqa: BLE001 - preserve fail-open outcome.
                    reason = f"{reason}:release_{type(release_exc).__name__}"
            errors.append(
                {
                    "broker_order_id": str(payload["broker_order_id"]),
                    "reason": reason,
                }
            )
    return {"status": "sent" if sent else "noop", "sent": sent, "errors": errors}
