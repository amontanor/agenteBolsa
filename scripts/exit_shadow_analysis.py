#!/usr/bin/env python3
"""Analyze realized exit behavior and compare against a shadow stale-guard policy."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any


def _loads(raw: str | None) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return round(sum(clean) / len(clean), 4)


def _profit_factor(values: list[float | None]) -> float | None:
    gains = sum(value for value in values if value is not None and value > 0)
    losses = -sum(value for value in values if value is not None and value < 0)
    if losses <= 0:
        return None
    return round(gains / losses, 4)


def _parse_time(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _stale_guard_shadow(outcome: dict[str, Any], *, days: int, max_peak_return: float, min_return: float) -> dict[str, Any]:
    current = dict(outcome.get("exit_policy_v2") or {})
    if not current:
        return {"available": False, "reason": "missing_exit_policy_v2"}
    first_hit = outcome.get("first_hit") or {}
    first_hit_day = int(first_hit.get("days") or 0)
    if first_hit.get("type") in {"stop_loss", "take_profit"} and 0 < first_hit_day <= days:
        return {
            "available": True,
            "exit_reason": str(first_hit.get("type")),
            "exit_day": first_hit_day,
            "return_pct": current.get("return_pct"),
            "basis": "first_hit_before_stale_window",
        }
    peak_return = _num(current.get("peak_return"))
    day_return = _num(outcome.get(f"return_{days}d"))
    matured = bool((outcome.get("matured_horizons") or {}).get(f"{days}d"))
    if matured and peak_return is not None and day_return is not None:
        if peak_return <= max_peak_return and day_return <= min_return:
            return {
                "available": True,
                "exit_reason": "stale_guard_v2",
                "exit_day": days,
                "return_pct": round(day_return, 4),
                "basis": "stale_guard_shadow",
            }
    return {
        "available": True,
        "exit_reason": current.get("exit_reason"),
        "exit_day": current.get("exit_day"),
        "return_pct": current.get("return_pct"),
        "basis": "fallback_current_policy",
    }


def _metrics(rows: list[dict[str, Any]], value_key: str) -> dict[str, Any]:
    values = [_num(row.get(value_key)) for row in rows]
    wins = sum(1 for value in values if value is not None and value > 0)
    matured = sum(1 for value in values if value is not None)
    return {
        "n": len(rows),
        "matured": matured,
        "expectancy": _mean(values),
        "hit_rate": round(wins / matured, 4) if matured else None,
        "profit_factor": _profit_factor(values),
    }


def main() -> int:
    from agente_bolsa.config import get_settings
    from agente_bolsa.tools.execution_linking import match_signal_row_for_buy_order
    from agente_bolsa.tools.trade_history import build_trade_history

    settings = get_settings()
    con = sqlite3.connect(settings.database_path)
    con.row_factory = sqlite3.Row
    history = build_trade_history(settings, limit=500, start_date="2026-04-01", scope="agent")
    realized_trade_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in history.get("trades", []):
        if str(trade.get("side") or "").lower() == "sell" and trade.get("order_id"):
            realized_trade_rows[str(trade["order_id"])].append(trade)

    buy_rows = {
        row["plan_id"]: row
        for row in con.execute(
            """
            SELECT plan_id, symbol, created_at, payload_json
            FROM broker_orders
            WHERE lower(side) = 'buy' AND lower(status) = 'filled'
            """
        )
    }
    closed: list[dict[str, Any]] = []
    for row in con.execute(
        """
        SELECT broker_order_id, plan_id, symbol, created_at, payload_json
        FROM broker_orders
        WHERE lower(side) = 'sell' AND lower(status) = 'filled'
        ORDER BY created_at ASC
        """
    ):
        payload = _loads(row["payload_json"])
        plan_payload = ((payload.get("plan") or {}).get("payload") or {})
        checks = ((plan_payload.get("risk_decision") or {}).get("checks") or {})
        source_plan_id = str(checks.get("source_plan_id") or "")
        buy_row = buy_rows.get(source_plan_id)
        if not buy_row:
            continue
        buy_payload = _loads(buy_row["payload_json"])
        signal = match_signal_row_for_buy_order(
            con,
            symbol=str(buy_row["symbol"]),
            order_created_at=buy_row["created_at"],
            plan_created_at=((buy_payload.get("plan") or {}).get("created_at")),
        )
        if not signal:
            continue
        outcome = signal.get("outcome") or {}
        exit_policy = outcome.get("exit_policy_v2") or {}
        buy_time = _parse_time(buy_row["created_at"])
        sell_time = _parse_time(row["created_at"])
        actual_hold_days = (sell_time - buy_time).days if buy_time and sell_time else None
        actual_rows = realized_trade_rows.get(str(row["broker_order_id"]), [])
        actual_return = _mean([_num(item.get("realized_plpc")) for item in actual_rows])
        actual_realized_pl = round(sum(_num(item.get("realized_pl")) or 0.0 for item in actual_rows), 2) if actual_rows else None
        shadow = _stale_guard_shadow(
            outcome,
            days=int(settings.exit_policy_v2_stale_guard_days),
            max_peak_return=float(settings.exit_policy_v2_stale_guard_max_peak_return),
            min_return=float(settings.exit_policy_v2_stale_guard_min_return),
        )
        closed.append(
            {
                "symbol": row["symbol"],
                "signal_date": signal.get("signal_date"),
                "actual_exit_reason": checks.get("trigger") or "llm_or_manual_exit",
                "actual_hold_days": actual_hold_days,
                "actual_return_pct": actual_return,
                "actual_realized_pl": actual_realized_pl,
                "planned_stop_loss": plan_payload.get("stop_loss"),
                "planned_take_profit": plan_payload.get("take_profit"),
                "mfe_10d": outcome.get("mfe_10d"),
                "mae_10d": outcome.get("mae_10d"),
                "first_hit": outcome.get("first_hit"),
                "current_policy_reason": exit_policy.get("exit_reason"),
                "current_policy_return_pct": exit_policy.get("return_pct"),
                "current_policy_exit_day": exit_policy.get("exit_day"),
                "shadow_exit_reason": shadow.get("exit_reason"),
                "shadow_return_pct": shadow.get("return_pct"),
                "shadow_exit_day": shadow.get("exit_day"),
                "shadow_basis": shadow.get("basis"),
            }
        )

    by_reason = Counter(item["actual_exit_reason"] for item in closed)
    actual_metrics = _metrics(closed, "actual_return_pct")
    current_policy_metrics = _metrics(closed, "current_policy_return_pct")
    shadow_metrics = _metrics(closed, "shadow_return_pct")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in closed:
        grouped[item["actual_exit_reason"]].append(item)
    per_reason = []
    for reason, rows in grouped.items():
        per_reason.append(
            {
                "reason": reason,
                "n": len(rows),
                "avg_hold_days": _mean([_num(item.get("actual_hold_days")) for item in rows]),
                "avg_actual_return_pct": _mean([_num(item.get("actual_return_pct")) for item in rows]),
                "avg_shadow_return_pct": _mean([_num(item.get("shadow_return_pct")) for item in rows]),
                "avg_mfe_10d": _mean([_num(item.get("mfe_10d")) for item in rows]),
                "avg_mae_10d": _mean([_num(item.get("mae_10d")) for item in rows]),
            }
        )
    report = {
        "closed_trade_count": len(closed),
        "actual_exit_reason_histogram": dict(by_reason),
        "actual_exit_metrics": actual_metrics,
        "current_policy_metrics": current_policy_metrics,
        "shadow_stale_guard_metrics": shadow_metrics,
        "shadow_profile": {
            "enabled": True,
            "days": settings.exit_policy_v2_stale_guard_days,
            "max_peak_return": settings.exit_policy_v2_stale_guard_max_peak_return,
            "min_return": settings.exit_policy_v2_stale_guard_min_return,
        },
        "per_reason": sorted(per_reason, key=lambda item: item["n"], reverse=True),
        "trades": closed,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
