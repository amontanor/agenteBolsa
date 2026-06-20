#!/usr/bin/env python3
"""Operational metrics for the trading-improvement blocks."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any


def _loads(raw: str | None) -> dict:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _counter_dict(counter: Counter) -> dict:
    return {key: value for key, value in counter.most_common()}


def _order_fill(row: sqlite3.Row) -> dict[str, Any]:
    payload = _loads(row["payload_json"])
    fill = payload.get("broker_order_reconciled") or payload.get("broker_order") or {}
    plan = payload.get("plan") or {}
    plan_payload = plan.get("payload") or {}
    qty = fill.get("filled_qty") or fill.get("qty") or plan_payload.get("qty")
    price = fill.get("filled_avg_price") or plan_payload.get("entry_price")
    try:
        qty_float = float(qty)
        price_float = float(price)
    except (TypeError, ValueError):
        qty_float = 0.0
        price_float = 0.0
    return {
        "symbol": str(row["symbol"]).upper(),
        "side": str(row["side"]).lower(),
        "qty": qty_float,
        "price": price_float,
        "created_at": row["created_at"],
        "status": row["status"],
    }


def _realized_pnl_from_fills(rows: list[sqlite3.Row]) -> dict[str, Any]:
    lots: dict[str, list[dict[str, float]]] = defaultdict(list)
    realized = 0.0
    closed_qty = 0.0
    closed_trades = 0
    open_notional = 0.0
    for row in sorted(rows, key=lambda item: item["created_at"]):
        fill = _order_fill(row)
        if fill["qty"] <= 0 or fill["price"] <= 0 or "filled" not in str(fill["status"]).lower():
            continue
        if fill["side"] == "buy":
            lots[fill["symbol"]].append({"qty": fill["qty"], "price": fill["price"]})
            open_notional += fill["qty"] * fill["price"]
            continue
        if fill["side"] != "sell":
            continue
        remaining = fill["qty"]
        while remaining > 0 and lots[fill["symbol"]]:
            lot = lots[fill["symbol"]][0]
            qty = min(remaining, lot["qty"])
            realized += qty * (fill["price"] - lot["price"])
            closed_qty += qty
            closed_trades += 1
            open_notional -= qty * lot["price"]
            lot["qty"] -= qty
            remaining -= qty
            if lot["qty"] <= 1e-9:
                lots[fill["symbol"]].pop(0)
    return {
        "realized_pnl_fifo": round(realized, 2),
        "closed_lots": closed_trades,
        "closed_qty": round(closed_qty, 6),
        "remaining_open_lots": sum(len(items) for items in lots.values()),
        "remaining_cost_basis": round(max(0.0, open_notional), 2),
    }


def main() -> int:
    from agente_bolsa.config import get_settings

    settings = get_settings()
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    con = sqlite3.connect(settings.database_path)
    con.row_factory = sqlite3.Row

    events = con.execute(
        """
        SELECT created_at, payload_json
        FROM agent_events
        WHERE event_type = 'paper_auto_trade_completed'
          AND created_at >= ?
        ORDER BY created_at
        """,
        (since,),
    ).fetchall()
    final_rejected = Counter()
    gate_rejected = Counter()
    gate_seen = Counter()
    reasons = defaultdict(Counter)
    symbols = defaultdict(Counter)
    recommendations = 0
    buy_recommendations = 0
    approved_buys = 0
    submitted = 0

    for row in events:
        payload = _loads(row["payload_json"])
        recs = list(payload.get("recommendations") or [])
        recommendations += len(recs)
        buy_recommendations += sum(1 for item in recs if item.get("action") == "buy")
        approved_buys += len(payload.get("approved_buys") or [])
        submitted += len(payload.get("submitted") or [])
        for item in payload.get("rejected_order_plans") or []:
            stage = item.get("stage") or "UNKNOWN"
            final_rejected[stage] += 1
            reasons[stage][str(item.get("reason"))[:180]] += 1
            symbols[stage][item.get("symbol") or "?"] += 1
        for gate in ("deterministic_review", "adversarial_review", "entry_quality_gate", "backtest_gate"):
            value = payload.get(gate)
            items = value if isinstance(value, list) else ([value] if isinstance(value, dict) else [])
            for item in items:
                if not isinstance(item, dict) or "approved" not in item:
                    continue
                gate_seen[gate] += 1
                if item.get("approved") is False:
                    gate_rejected[gate] += 1
                    reasons[gate][str(item.get("reason"))[:180]] += 1
                    symbols[gate][item.get("symbol") or "?"] += 1

    broker_status = Counter()
    broker_rows = con.execute("SELECT * FROM broker_orders").fetchall()
    for row in broker_rows:
        broker_status[(str(row["status"]), str(row["side"]))] += 1
    realized = _realized_pnl_from_fills(broker_rows)

    signal_rows = con.execute("SELECT gate_json, outcome_json FROM signal_outcomes").fetchall()
    executed_signals = 0
    realized_signals = 0
    for row in signal_rows:
        gate = _loads(row["gate_json"])
        outcome = _loads(row["outcome_json"])
        if gate.get("executed_buy") or (outcome.get("execution") or {}).get("executed_buy"):
            executed_signals += 1
        if outcome.get("realized_pnl") is not None or outcome.get("pnl_realized") is not None:
            realized_signals += 1

    learning = con.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN executed_buy = 1 THEN 1 ELSE 0 END) AS executed
        FROM learning_observations
        """
    ).fetchone()
    performance = [dict(row) for row in con.execute("SELECT * FROM performance_daily ORDER BY session_date DESC LIMIT 5")]
    con.close()

    print(
        json.dumps(
            {
                "since": since,
                "paper_events": len(events),
                "recommendations_total": recommendations,
                "buy_recommendations": buy_recommendations,
                "approved_buys_payload": approved_buys,
                "submitted_orders_payload": submitted,
                "final_rejected_stage_histogram": _counter_dict(final_rejected),
                "gate_rejected_histogram": _counter_dict(gate_rejected),
                "gate_seen": _counter_dict(gate_seen),
                "top_reasons": {key: value.most_common(5) for key, value in reasons.items()},
                "top_symbols_by_stage": {key: value.most_common(5) for key, value in symbols.items()},
                "broker_status": [
                    {"status": status, "side": side, "count": count}
                    for (status, side), count in broker_status.most_common()
                ],
                "paper_realized_pnl": realized,
                "signal_outcomes_total": len(signal_rows),
                "signal_executed_observations": executed_signals,
                "signal_realized_observations": realized_signals,
                "learning_observations_total": int(learning["total"] or 0),
                "learning_executed_observations": int(learning["executed"] or 0),
                "latest_performance": performance,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
