"""Helpers to link filled broker buys back to the originating signal rows."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

# Antiguedad maxima (dias naturales) de una senal para enlazarse a una orden.
# Evita heredar fills de senales historicas: una orden pertenece al mismo evento
# (mismo dia o pocos dias antes), no de semanas atras.
DEFAULT_MAX_SIGNAL_AGE_DAYS = 5


def _json_loads(raw: str | None) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _cutoff(order_created_at: str | None, plan_created_at: str | None = None) -> tuple[str | None, str | None]:
    timestamps = [item for item in (_parse_iso(plan_created_at), _parse_iso(order_created_at)) if item is not None]
    if not timestamps:
        return None, None
    chosen = min(timestamps)
    return chosen.date().isoformat(), chosen.isoformat()


def match_signal_row_for_buy_order(
    conn: Any,
    *,
    symbol: str,
    order_created_at: str | None,
    plan_created_at: str | None = None,
    broker_order_id: str | None = None,
    limit: int = 50,
    max_signal_age_days: int | None = DEFAULT_MAX_SIGNAL_AGE_DAYS,
) -> dict[str, Any] | None:
    signal_date_cutoff, timestamp_cutoff = _cutoff(order_created_at, plan_created_at)
    if not signal_date_cutoff:
        return None
    floor_date: str | None = None
    if max_signal_age_days is not None and max_signal_age_days >= 0:
        try:
            floor_date = (
                date.fromisoformat(signal_date_cutoff) - timedelta(days=max_signal_age_days)
            ).isoformat()
        except ValueError:
            floor_date = None
    if floor_date is not None:
        rows = conn.execute(
            """
            SELECT signal_id, source_run_id, source, symbol, signal_date, decision,
                   features_json, gate_json, outcome_json, created_at, updated_at
            FROM signal_outcomes
            WHERE symbol = ?
              AND signal_date <= ?
              AND signal_date >= ?
              AND coalesce(source, '') != 'lab_book'
            ORDER BY signal_date DESC, created_at DESC, signal_id DESC
            LIMIT ?
            """,
            (symbol.upper(), signal_date_cutoff, floor_date, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT signal_id, source_run_id, source, symbol, signal_date, decision,
                   features_json, gate_json, outcome_json, created_at, updated_at
            FROM signal_outcomes
            WHERE symbol = ?
              AND signal_date <= ?
              AND coalesce(source, '') != 'lab_book'
            ORDER BY signal_date DESC, created_at DESC, signal_id DESC
            LIMIT ?
            """,
            (symbol.upper(), signal_date_cutoff, limit),
        ).fetchall()
    fallback = None
    for row in rows:
        gate = _json_loads(row["gate_json"])
        linked_order_id = str(gate.get("broker_order_id") or "")
        if linked_order_id and broker_order_id and linked_order_id != broker_order_id:
            continue
        created_at = str(row["created_at"] or "").strip()
        if timestamp_cutoff and created_at and created_at > timestamp_cutoff:
            fallback = fallback or {
                "signal_id": row["signal_id"],
                "source_run_id": row["source_run_id"],
                "source": row["source"],
                "symbol": row["symbol"],
                "signal_date": row["signal_date"],
                "decision": row["decision"],
                "features": _json_loads(row["features_json"]),
                "gate": gate,
                "outcome": _json_loads(row["outcome_json"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            continue
        return {
            "signal_id": row["signal_id"],
            "source_run_id": row["source_run_id"],
            "source": row["source"],
            "symbol": row["symbol"],
            "signal_date": row["signal_date"],
            "decision": row["decision"],
            "features": _json_loads(row["features_json"]),
            "gate": gate,
            "outcome": _json_loads(row["outcome_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    return fallback


def match_learning_observation_for_signal(
    conn: Any,
    *,
    symbol: str,
    signal_date: str,
    source: str | None = None,
) -> dict[str, Any] | None:
    params: list[Any] = [symbol.upper(), signal_date]
    query = """
        SELECT observation_id, source_family, execution_json
        FROM learning_observations
        WHERE symbol = ?
          AND signal_date = ?
    """
    if source:
        params.append(str(source).strip().lower())
        query += " AND source_family = ?"
    query += " ORDER BY updated_at DESC, observation_id DESC LIMIT 1"
    row = conn.execute(query, params).fetchone()
    if not row:
        return None
    return {
        "observation_id": row["observation_id"],
        "source_family": row["source_family"],
        "execution": _json_loads(row["execution_json"]),
    }
