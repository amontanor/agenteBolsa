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

from .execution_linking import match_learning_observation_for_signal, match_signal_row_for_buy_order
from .execution_quality import reconciled_snapshot

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
        WHERE (
            lower(status) NOT LIKE '%filled%'
            AND lower(status) NOT LIKE '%cancel%'
            AND lower(status) NOT LIKE '%expired%'
            AND lower(status) NOT LIKE '%rejected%'
            AND lower(status) NOT LIKE '%done_for_day%'
            AND lower(status) NOT LIKE '%replaced%'
            AND lower(status) NOT LIKE '%stopped%'
        )
        OR json_extract(payload_json, '$.reconciliation_finalization.status') = 'pending'
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        row
        for row in rows
        if normalize_status(row["status"]) not in TERMINAL_STATUSES
        or _json_loads(row["payload_json"]).get("reconciliation_finalization", {}).get("status") == "pending"
    ]


def _has_pending_finalization(payload: dict[str, Any]) -> bool:
    marker = payload.get("reconciliation_finalization")
    return isinstance(marker, dict) and marker.get("status") == "pending"


def _get_remote_order(client: Any, broker_order_id: str, payload: dict[str, Any]) -> Any:
    try:
        return client.get_order_by_id(broker_order_id)
    except Exception:  # noqa: BLE001 - Alpaca may need client_order_id fallback.
        broker_payload = payload.get("broker_order") or {}
        client_order_id = broker_payload.get("client_order_id") or f"agente-{payload.get('plan_id', '')}"
        return client.get_order_by_client_id(client_order_id)


def _merge_reconciliation_payload(payload: dict[str, Any], snapshot: dict[str, Any], *, at: str, plan_status: str | None = None) -> dict[str, Any]:
    history = list(payload.get("reconciliation_history") or [])[-4:]
    history.append({"at": at, "status": snapshot.get("status")})
    merged = {
        **payload,
        "broker_order_reconciled": snapshot,
        "reconciliation_history": history,
    }
    execution_snapshot = dict(payload.get("execution_quality_snapshot") or {})
    if execution_snapshot:
        merged["execution_quality_snapshot"] = reconciled_snapshot(
            execution_snapshot,
            broker_snapshot=snapshot,
            observed_at=at,
            plan_status=plan_status,
        )
    return merged


def _mark_signal_execution(
    conn: sqlite3.Connection,
    *,
    symbol: str,
    side: str,
    plan_id: str,
    status: str,
    snapshot: dict[str, Any],
    order_created_at: str | None,
    plan_created_at: str | None,
    now: str,
) -> int:
    if side.lower() != "buy" or status != "filled":
        return 0
    row = match_signal_row_for_buy_order(
        conn,
        symbol=symbol,
        order_created_at=order_created_at,
        plan_created_at=plan_created_at,
        broker_order_id=str(snapshot.get("id") or ""),
    )
    if not row:
        return 0
    gate = dict(row.get("gate") or {})
    if gate.get("executed_buy") and gate.get("broker_order_id") == snapshot.get("id"):
        return 0
    execution = {
        "executed_buy": True,
        "broker_order_id": snapshot.get("id"),
        "plan_id": plan_id,
        "filled_qty": snapshot.get("filled_qty"),
        "filled_avg_price": snapshot.get("filled_avg_price"),
        "filled_at": snapshot.get("filled_at"),
    }
    gate.update(execution)
    outcome = dict(row.get("outcome") or {})
    outcome.setdefault("execution", {}).update(execution)
    conn.execute(
        """
        UPDATE signal_outcomes
        SET gate_json = ?, outcome_json = ?, updated_at = ?
        WHERE signal_id = ?
        """,
        (_json_dumps(gate), _json_dumps(outcome), now, row["signal_id"]),
    )
    return 1


def _mark_learning_execution(
    conn: sqlite3.Connection,
    *,
    symbol: str,
    side: str,
    plan_id: str,
    status: str,
    snapshot: dict[str, Any],
    order_created_at: str | None,
    plan_created_at: str | None,
    now: str,
) -> int:
    if side.lower() != "buy" or status != "filled":
        return 0
    signal = match_signal_row_for_buy_order(
        conn,
        symbol=symbol,
        order_created_at=order_created_at,
        plan_created_at=plan_created_at,
        broker_order_id=str(snapshot.get("id") or ""),
    )
    if not signal:
        return 0
    row = match_learning_observation_for_signal(
        conn,
        symbol=symbol,
        signal_date=str(signal.get("signal_date") or ""),
        source=signal.get("source"),
    )
    if not row:
        return 0
    execution = dict(row.get("execution") or {})
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
        "execution_quality_updates": 0,
        "finalization_applied": 0,
        "finalization_skipped": 0,
        "signal_outcome_update": {"updated": 0, "signals": 0, "symbols": 0, "warnings": []},
    }
    with store.connect() as conn:
        pending = _pending_orders(conn, limit)
    result["checked"] = len(pending)
    result["pending"] = len(pending)
    if not pending:
        if update_learning:
            result["signal_outcome_update"] = update_signal_outcomes(
                settings,
                store,
                since_date="2026-04-01",
                limit=200000,
            )
        return result

    changes: list[dict[str, Any]] = []
    remote_pending: list[sqlite3.Row] = []
    for row in pending:
        payload = _json_loads(row["payload_json"])
        if _has_pending_finalization(payload):
            snapshot = payload.get("broker_order_reconciled")
            if not isinstance(snapshot, dict) or not normalize_status(snapshot.get("status")):
                result["errors"].append(
                    {
                        "broker_order_id": row["broker_order_id"],
                        "stage": "local_finalization",
                        "error": "reconciled_snapshot_missing",
                    }
                )
                continue
            old_status = normalize_status(row["status"])
            changes.append(
                {
                    "broker_order_id": row["broker_order_id"],
                    "plan_id": row["plan_id"],
                    "cycle_id": row["cycle_id"],
                    "symbol": row["symbol"],
                    "side": row["side"],
                    "old": old_status,
                    "new": old_status,
                    "fill": dict(snapshot),
                    "payload": payload,
                    "created_at": row["created_at"],
                    "finalization_pending": True,
                }
            )
        else:
            remote_pending.append(row)

    client = None
    if remote_pending:
        try:
            client = BrokerClientFactory(settings).alpaca_trading_client()
        except Exception as exc:  # noqa: BLE001
            result["errors"].append({"stage": "connect", "error": str(exc)[:240]})

    for row in remote_pending:
        if client is None:
            continue
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
                    "created_at": row["created_at"],
                    "finalization_pending": False,
                }
            )
    result["changes"] = [{k: v for k, v in item.items() if k != "payload"} for item in changes]
    if not apply or not changes:
        return result

    signal_updates = 0
    learning_updates = 0
    execution_quality_updates = 0
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for change in changes:
            payload = dict(change["payload"])
            finalization_pending = bool(change.get("finalization_pending"))
            if finalization_pending:
                current = conn.execute(
                    "SELECT payload_json FROM broker_orders WHERE broker_order_id = ?",
                    (change["broker_order_id"],),
                ).fetchone()
                current_payload = _json_loads(current["payload_json"] if current else None)
                if not _has_pending_finalization(current_payload):
                    result["finalization_skipped"] += 1
                    continue
                marker = dict(current_payload.get("reconciliation_finalization") or {})
                marker.update({"status": "processing", "claimed_at": now})
                payload = dict(current_payload)
                payload["reconciliation_finalization"] = marker
                payload["reconciliation_finalization_pending"] = True
                payload["reconciliation_finalization_applied"] = False
                fill = dict(payload.get("broker_order_reconciled") or change["fill"])
                new_status = normalize_status(change["new"])
            else:
                current = conn.execute(
                    "SELECT status, payload_json FROM broker_orders WHERE broker_order_id = ?",
                    (change["broker_order_id"],),
                ).fetchone()
                current_status = normalize_status(current["status"] if current else "")
                current_payload = _json_loads(current["payload_json"] if current else None)
                if current_status in TERMINAL_STATUSES:
                    if not _has_pending_finalization(current_payload):
                        result["finalization_skipped"] += 1
                        continue
                    finalization_pending = True
                    payload = current_payload
                    fill = dict(payload.get("broker_order_reconciled") or change["fill"])
                    new_status = current_status
                    marker = dict(payload.get("reconciliation_finalization") or {})
                    marker.update({"status": "processing", "claimed_at": now})
                    payload["reconciliation_finalization"] = marker
                    payload["reconciliation_finalization_pending"] = True
                    payload["reconciliation_finalization_applied"] = False
                else:
                    plan_row = conn.execute("SELECT status FROM order_plans WHERE plan_id = ?", (change["plan_id"],)).fetchone()
                    payload = _merge_reconciliation_payload(
                        payload,
                        change["fill"],
                        at=now,
                        plan_status=str(plan_row["status"]) if plan_row else None,
                    )
                    fill = change["fill"]
                    new_status = change["new"]
            plan_created_at = str(((change["payload"].get("plan") or {}).get("created_at")) or "").strip() or None
            conn.execute(
                """
                UPDATE broker_orders
                SET status = ?, payload_json = ?
                WHERE broker_order_id = ?
                """,
                (new_status, _json_dumps(payload), change["broker_order_id"]),
            )
            signal_delta = _mark_signal_execution(
                conn,
                symbol=change["symbol"],
                side=change["side"],
                plan_id=change["plan_id"],
                status=new_status,
                snapshot=fill,
                order_created_at=change.get("created_at"),
                plan_created_at=plan_created_at,
                now=now,
            )
            learning_delta = _mark_learning_execution(
                conn,
                symbol=change["symbol"],
                side=change["side"],
                plan_id=change["plan_id"],
                status=new_status,
                snapshot=fill,
                order_created_at=change.get("created_at"),
                plan_created_at=plan_created_at,
                now=now,
            )
            signal_updates += signal_delta
            learning_updates += learning_delta
            execution_snapshot = dict(payload.get("execution_quality_snapshot") or {})
            execution_delta = 0
            if execution_snapshot.get("lineage_status") == "verified" and execution_snapshot.get("signal_id"):
                attached = store.attach_execution_quality_snapshot(
                    str(execution_snapshot["signal_id"]),
                    execution_snapshot,
                    connection=conn,
                )
                execution_delta = int(attached in {"attached", "idempotent"})
                execution_quality_updates += execution_delta
            if finalization_pending:
                marker = dict(payload.get("reconciliation_finalization") or {})
                marker.update(
                    {
                        "status": "applied",
                        "applied_at": now,
                        "effects": {
                            "signal_execution_updates": signal_delta,
                            "learning_execution_updates": learning_delta,
                            "execution_quality_updates": execution_delta,
                        },
                    }
                )
                payload["reconciliation_finalization"] = marker
                payload["reconciliation_finalization_pending"] = False
                payload["reconciliation_finalization_applied"] = True
                conn.execute(
                    "UPDATE broker_orders SET payload_json = ? WHERE broker_order_id = ?",
                    (_json_dumps(payload), change["broker_order_id"]),
                )
                result["finalization_applied"] += 1
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
    result["execution_quality_updates"] = execution_quality_updates
    if update_learning:
        result["signal_outcome_update"] = update_signal_outcomes(settings, store, since_date="2026-04-01", limit=200000)
    return result
