"""Broker order reconciliation and execution learning bridge."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.broker import BrokerClientFactory
from agente_bolsa.tools.signal_learning import update_signal_outcomes

TERMINAL_STATUSES = {
    "filled",
    "canceled",
    "cancelled",
    "expired",
    "rejected",
    "done_for_day",
    "replaced",
    "stopped",
}


def normalize_status(raw: Any) -> str:
    text = str(raw or "").strip()
    if "." in text:
        text = text.split(".")[-1]
    return text.lower()


def _json_loads(raw: str | None) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _json_dumps(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _order_snapshot(order: Any) -> dict[str, Any]:
    return {
        "id": str(getattr(order, "id", "") or ""),
        "client_order_id": str(getattr(order, "client_order_id", "") or ""),
        "status": normalize_status(getattr(order, "status", "")),
        "filled_qty": _float_or_none(getattr(order, "filled_qty", None)),
        "filled_avg_price": _float_or_none(getattr(order, "filled_avg_price", None)),
        "qty": _float_or_none(getattr(order, "qty", None)),
        "notional": _float_or_none(getattr(order, "notional", None)),
        "submitted_at": _iso_or_none(getattr(order, "submitted_at", None)),
        "filled_at": _iso_or_none(getattr(order, "filled_at", None)),
        "updated_at": _iso_or_none(getattr(order, "updated_at", None)),
    }


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _pending_orders(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT broker_order_id, plan_id, cycle_id, symbol, side, status, payload_json, created_at
        FROM broker_orders
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [row for row in rows if normalize_status(row["status"]) not in TERMINAL_STATUSES]


def _get_remote_order(client: Any, broker_order_id: str, payload: dict[str, Any]) -> Any:
    try:
        return client.get_order_by_id(broker_order_id)
    except Exception:  # noqa: BLE001 - Alpaca may need client_order_id fallback.
        broker_payload = payload.get("broker_order") or {}
        client_order_id = broker_payload.get("client_order_id") or f"agente-{payload.get('plan_id', '')}"
        return client.get_order_by_client_id(client_order_id)


def _merge_reconciliation_payload(payload: dict[str, Any], snapshot: dict[str, Any], *, at: str) -> dict[str, Any]:
    history = list(payload.get("reconciliation_history") or [])[-4:]
    history.append({"at": at, "status": snapshot.get("status")})
    return {
        **payload,
        "broker_order_reconciled": snapshot,
        "reconciliation_history": history,
    }


def _mark_signal_execution(
    conn: sqlite3.Connection,
    *,
    symbol: str,
    side: str,
    plan_id: str,
    status: str,
    snapshot: dict[str, Any],
    now: str,
) -> int:
    if side.lower() != "buy" or status != "filled":
        return 0
    rows = conn.execute(
        """
        SELECT signal_id, gate_json, outcome_json
        FROM signal_outcomes
        WHERE symbol = ?
        ORDER BY signal_date DESC, created_at DESC
        LIMIT 20
        """,
        (symbol.upper(),),
    ).fetchall()
    updated = 0
    for row in rows:
        gate = _json_loads(row["gate_json"])
        if gate.get("executed_buy") and gate.get("broker_order_id") == snapshot.get("id"):
            continue
        execution = {
            "executed_buy": True,
            "broker_order_id": snapshot.get("id"),
            "plan_id": plan_id,
            "filled_qty": snapshot.get("filled_qty"),
            "filled_avg_price": snapshot.get("filled_avg_price"),
            "filled_at": snapshot.get("filled_at"),
        }
        gate.update(execution)
        outcome = _json_loads(row["outcome_json"])
        outcome.setdefault("execution", {}).update(execution)
        conn.execute(
            """
            UPDATE signal_outcomes
            SET gate_json = ?, outcome_json = ?, updated_at = ?
            WHERE signal_id = ?
            """,
            (_json_dumps(gate), _json_dumps(outcome), now, row["signal_id"]),
        )
        updated += 1
    return updated


def _mark_learning_execution(
    conn: sqlite3.Connection,
    *,
    symbol: str,
    side: str,
    plan_id: str,
    status: str,
    snapshot: dict[str, Any],
    now: str,
) -> int:
    if side.lower() != "buy" or status != "filled":
        return 0
    row = conn.execute(
        """
        SELECT observation_id, execution_json
        FROM learning_observations
        WHERE symbol = ?
        ORDER BY signal_date DESC, updated_at DESC
        LIMIT 1
        """,
        (symbol.upper(),),
    ).fetchone()
    if not row:
        return 0
    execution = _json_loads(row["execution_json"])
    execution.update(
        {
            "broker_order_id": snapshot.get("id"),
            "plan_id": plan_id,
            "status": status,
            "filled_qty": snapshot.get("filled_qty"),
            "filled_avg_price": snapshot.get("filled_avg_price"),
            "filled_at": snapshot.get("filled_at"),
        }
    )
    conn.execute(
        """
        UPDATE learning_observations
        SET executed_buy = 1, execution_json = ?, updated_at = ?
        WHERE observation_id = ?
        """,
        (_json_dumps(execution), now, row["observation_id"]),
    )
    return 1


def reconcile_broker_orders(
    settings: Settings,
    store: Store,
    *,
    apply: bool = False,
    limit: int = 200,
    update_learning: bool = True,
) -> dict[str, Any]:
    store.ensure_schema()
    now = datetime.now(timezone.utc).isoformat()
    result: dict[str, Any] = {
        "checked": 0,
        "pending": 0,
        "changes": [],
        "errors": [],
        "applied": bool(apply),
        "signal_execution_updates": 0,
        "learning_execution_updates": 0,
        "signal_outcome_update": {"updated": 0, "signals": 0, "symbols": 0, "warnings": []},
    }
    with store.connect() as conn:
        pending = _pending_orders(conn, limit)
    result["checked"] = limit
    result["pending"] = len(pending)
    if not pending:
        return result

    try:
        client = BrokerClientFactory(settings).alpaca_trading_client()
    except Exception as exc:  # noqa: BLE001
        result["errors"].append({"stage": "connect", "error": str(exc)[:240]})
        return result

    changes: list[dict[str, Any]] = []
    for row in pending:
        payload = _json_loads(row["payload_json"])
        try:
            order = _get_remote_order(client, row["broker_order_id"], payload)
            snapshot = _order_snapshot(order)
        except Exception as exc:  # noqa: BLE001
            result["errors"].append({"broker_order_id": row["broker_order_id"], "error": str(exc)[:240]})
            continue
        old_status = normalize_status(row["status"])
        new_status = normalize_status(snapshot.get("status"))
        if new_status and new_status != old_status:
            changes.append(
                {
                    "broker_order_id": row["broker_order_id"],
                    "plan_id": row["plan_id"],
                    "cycle_id": row["cycle_id"],
                    "symbol": row["symbol"],
                    "side": row["side"],
                    "old": old_status,
                    "new": new_status,
                    "fill": snapshot,
                    "payload": payload,
                }
            )
    result["changes"] = [{k: v for k, v in item.items() if k != "payload"} for item in changes]
    if not apply or not changes:
        return result

    signal_updates = 0
    learning_updates = 0
    with store.connect() as conn:
        for change in changes:
            payload = _merge_reconciliation_payload(change["payload"], change["fill"], at=now)
            conn.execute(
                """
                UPDATE broker_orders
                SET status = ?, payload_json = ?
                WHERE broker_order_id = ?
                """,
                (change["new"], _json_dumps(payload), change["broker_order_id"]),
            )
            signal_updates += _mark_signal_execution(
                conn,
                symbol=change["symbol"],
                side=change["side"],
                plan_id=change["plan_id"],
                status=change["new"],
                snapshot=change["fill"],
                now=now,
            )
            learning_updates += _mark_learning_execution(
                conn,
                symbol=change["symbol"],
                side=change["side"],
                plan_id=change["plan_id"],
                status=change["new"],
                snapshot=change["fill"],
                now=now,
            )
        conn.execute(
            "INSERT OR REPLACE INTO runtime_state (key, value_json, updated_at) VALUES (?, ?, ?)",
            (
                "broker_orders_reconcile_last_run",
                _json_dumps(
                    {
                        "at": now,
                        "updated": len(changes),
                        "signal_execution_updates": signal_updates,
                        "learning_execution_updates": learning_updates,
                    }
                ),
                now,
            ),
        )
    result["signal_execution_updates"] = signal_updates
    result["learning_execution_updates"] = learning_updates
    if update_learning:
        result["signal_outcome_update"] = update_signal_outcomes(settings, store, since_date="2026-04-01", limit=200000)
    return result
