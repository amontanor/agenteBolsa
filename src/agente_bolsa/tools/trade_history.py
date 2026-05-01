"""Trade history and P/L reporting."""

from __future__ import annotations

import json
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from agente_bolsa.config import Settings
from agente_bolsa.models import PortfolioSnapshot

from .broker import BrokerClientFactory

DEFAULT_HISTORY_START_DATE = "2026-04-01"


def _float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _activity_time(item: dict[str, Any]) -> str:
    return str(
        item.get("transaction_time")
        or item.get("date")
        or item.get("created_at")
        or item.get("updated_at")
        or ""
    )


def _activity_side(item: dict[str, Any]) -> str:
    side = str(item.get("side") or item.get("order_side") or "").lower()
    if side in {"buy", "sell"}:
        return side
    qty = _float(item.get("qty"))
    return "sell" if qty < 0 else "buy"


def _activity_qty(item: dict[str, Any]) -> float:
    return abs(_float(item.get("qty") or item.get("cum_qty") or item.get("filled_qty")))


def _activity_price(item: dict[str, Any]) -> float:
    return _float(item.get("price") or item.get("filled_avg_price") or item.get("avg_price"))


def _activity_symbol(item: dict[str, Any]) -> str:
    return str(item.get("symbol", "")).upper()


def _date_key(value: str, timezone_name: str = "Europe/Madrid") -> str:
    if not value:
        return "sin_fecha"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(ZoneInfo(timezone_name)).date().isoformat()
    except ValueError:
        return value[:10]


def _parse_activity_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _local_agent_order_scope(database_path: Path) -> dict[str, Any]:
    import sqlite3

    if not database_path.exists():
        return {"order_ids": set(), "symbols": set(), "first_time": None}
    with sqlite3.connect(database_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT broker_order_id, symbol, created_at
            FROM broker_orders
            ORDER BY created_at ASC
            """
        ).fetchall()

    order_ids = {str(row["broker_order_id"]) for row in rows if row["broker_order_id"]}
    symbols = {str(row["symbol"]).upper() for row in rows if row["symbol"]}
    first_time = None
    for row in rows:
        parsed = _parse_activity_datetime(str(row["created_at"] or ""))
        if parsed is not None:
            first_time = parsed
            break
    return {"order_ids": order_ids, "symbols": symbols, "first_time": first_time}


def _filter_fills_for_agent(fills: list[dict[str, Any]], scope: dict[str, Any]) -> list[dict[str, Any]]:
    order_ids: set[str] = scope.get("order_ids", set())
    symbols: set[str] = scope.get("symbols", set())
    first_time: datetime | None = scope.get("first_time")
    if not order_ids and not symbols:
        return []

    result = []
    for fill in fills:
        order_id = str(fill.get("order_id") or fill.get("id") or "")
        symbol = _activity_symbol(fill)
        activity_time = _parse_activity_datetime(_activity_time(fill))
        if order_id in order_ids:
            result.append(fill)
        elif symbol in symbols and first_time is not None and activity_time is not None and activity_time >= first_time:
            result.append(fill)
    return result


def _filter_fills_from_date(
    fills: list[dict[str, Any]],
    start_date: str | None,
    timezone_name: str,
) -> list[dict[str, Any]]:
    if not start_date:
        return fills
    return [fill for fill in fills if _date_key(_activity_time(fill), timezone_name) >= start_date]


def realized_pl_from_fills(fills: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Calculate realized P/L using FIFO lots from fill activities."""

    chronological = sorted(fills, key=_activity_time)
    lots: dict[str, deque[dict[str, float]]] = defaultdict(deque)
    rows: list[dict[str, Any]] = []
    total_realized_pl = 0.0
    total_buy_notional = 0.0
    total_sell_notional = 0.0
    realized_trades = 0
    unknown_realized_trades = 0

    for fill in chronological:
        symbol = _activity_symbol(fill)
        side = _activity_side(fill)
        qty = _activity_qty(fill)
        price = _activity_price(fill)
        notional = round(qty * price, 2)
        realized_pl = None
        realized_plpc = None

        if not symbol or qty <= 0 or price <= 0:
            continue

        if side == "buy":
            lots[symbol].append({"qty": qty, "price": price})
            total_buy_notional += notional
        elif side == "sell":
            remaining = qty
            matched_qty = 0.0
            cost_basis = 0.0
            while remaining > 1e-9 and lots[symbol]:
                lot = lots[symbol][0]
                matched = min(remaining, lot["qty"])
                matched_qty += matched
                cost_basis += matched * lot["price"]
                lot["qty"] -= matched
                remaining -= matched
                if lot["qty"] <= 1e-9:
                    lots[symbol].popleft()
            proceeds = matched_qty * price
            realized_pl = round(proceeds - cost_basis, 2) if matched_qty > 0 and cost_basis else None
            realized_plpc = round((proceeds - cost_basis) / cost_basis, 4) if cost_basis else None
            if realized_pl is not None:
                total_realized_pl += realized_pl
                realized_trades += 1
            if remaining > 1e-9:
                unknown_realized_trades += 1
            total_sell_notional += notional

        rows.append(
            {
                "time": _activity_time(fill),
                "date": _date_key(_activity_time(fill)),
                "symbol": symbol,
                "side": side,
                "qty": round(qty, 6),
                "price": round(price, 4),
                "notional": notional,
                "realized_pl": realized_pl,
                "realized_plpc": realized_plpc,
                "realized_pl_known": realized_pl is not None or side == "buy",
                "order_id": str(fill.get("order_id") or fill.get("id") or ""),
            }
        )

    rows = sorted(rows, key=lambda item: item["time"])
    return rows, {
        "fills": len(rows),
        "buy_notional": round(total_buy_notional, 2),
        "sell_notional": round(total_sell_notional, 2),
        "realized_pl": round(total_realized_pl, 2),
        "realized_trades": realized_trades,
        "unknown_realized_trades": unknown_realized_trades,
    }


def _open_positions_summary(portfolio: PortfolioSnapshot) -> list[dict[str, Any]]:
    return [
        {
            "symbol": position.symbol,
            "qty": position.qty,
            "market_value": round(position.market_value, 2),
            "avg_entry_price": round(position.avg_entry_price, 4),
            "current_price": round(position.current_price, 4),
            "unrealized_pl": round(position.unrealized_pl, 2),
            "unrealized_plpc": round(position.unrealized_plpc, 4),
        }
        for position in portfolio.positions
    ]


def _local_buy_risk_plans(database_path: Path) -> dict[str, dict[str, Any]]:
    import sqlite3

    if not database_path.exists():
        return {}
    with sqlite3.connect(database_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT symbol, payload_json, created_at
            FROM broker_orders
            WHERE lower(side) = 'buy'
            ORDER BY created_at DESC
            """
        ).fetchall()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row["symbol"]).upper()
        if symbol in result:
            continue
        payload = json.loads(row["payload_json"])
        plan = payload.get("plan", {}) or {}
        plan_payload = plan.get("payload", {}) or {}
        recommendation = plan_payload.get("recommendation", {}) or {}
        result[symbol] = {
            "source_plan_id": plan.get("plan_id"),
            "source_order_time": row["created_at"],
            "entry_price": plan_payload.get("entry_price"),
            "stop_loss": plan_payload.get("stop_loss"),
            "take_profit": plan_payload.get("take_profit"),
            "confidence": recommendation.get("confidence"),
            "reason": recommendation.get("reason"),
        }
    return result


def _attach_risk_levels(
    trades: list[dict[str, Any]],
    open_positions: list[dict[str, Any]],
    risk_by_symbol: dict[str, dict[str, Any]],
) -> None:
    for trade in trades:
        risk = risk_by_symbol.get(str(trade["symbol"]).upper(), {})
        trade["stop_loss"] = risk.get("stop_loss")
        trade["take_profit"] = risk.get("take_profit")
        trade["risk_entry_price"] = risk.get("entry_price")
    for position in open_positions:
        risk = risk_by_symbol.get(str(position["symbol"]).upper(), {})
        position["stop_loss"] = risk.get("stop_loss")
        position["take_profit"] = risk.get("take_profit")
        position["risk_entry_price"] = risk.get("entry_price")


def _daily_groups(
    trades: list[dict[str, Any]],
    open_positions: list[dict[str, Any]],
    *,
    today: str,
    portfolio_value: float,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for trade in trades:
        date = str(trade.get("date") or _date_key(str(trade.get("time", ""))))
        day = grouped.setdefault(
            date,
            {
                "date": date,
                "buy_notional": 0.0,
                "sell_notional": 0.0,
                "realized_pl": 0.0,
                "realized_known_trades": 0,
                "unknown_realized_trades": 0,
                "open_unrealized_pl": None,
                "open_unrealized_plpc": None,
                "trades": [],
                "open_positions": [],
            },
        )
        day["trades"].append(trade)
        if trade["side"] == "buy":
            day["buy_notional"] += trade["notional"]
        elif trade["side"] == "sell":
            day["sell_notional"] += trade["notional"]
            if trade.get("realized_pl") is None:
                day["unknown_realized_trades"] += 1
            else:
                day["realized_pl"] += trade["realized_pl"]
                day["realized_known_trades"] += 1

    if open_positions:
        day = grouped.setdefault(
            today,
            {
                "date": today,
                "buy_notional": 0.0,
                "sell_notional": 0.0,
                "realized_pl": 0.0,
                "realized_known_trades": 0,
                "unknown_realized_trades": 0,
                "open_unrealized_pl": None,
                "open_unrealized_plpc": None,
                "trades": [],
                "open_positions": [],
            },
        )
        open_pl = round(sum(item["unrealized_pl"] for item in open_positions), 2)
        day["open_unrealized_pl"] = open_pl
        day["open_unrealized_plpc"] = round(open_pl / portfolio_value, 4) if portfolio_value else 0.0
        day["open_positions"] = open_positions

    for day in grouped.values():
        day["buy_notional"] = round(day["buy_notional"], 2)
        day["sell_notional"] = round(day["sell_notional"], 2)
        day["realized_pl"] = round(day["realized_pl"], 2)
        denominator = day["sell_notional"] or day["buy_notional"]
        day["realized_plpc"] = round(day["realized_pl"] / denominator, 4) if denominator else 0.0

    return sorted(grouped.values(), key=lambda item: item["date"])


def _local_broker_orders(database_path: Path, limit: int, start_date: str | None = None) -> list[dict[str, Any]]:
    import sqlite3

    if not database_path.exists():
        return []
    with sqlite3.connect(database_path) as conn:
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
        date = _date_key(row["created_at"])
        if start_date and date < start_date:
            continue
        payload = json.loads(row["payload_json"])
        plan = payload.get("plan", {})
        result.append(
            {
                "time": row["created_at"],
                "date": date,
                "symbol": row["symbol"],
                "side": row["side"],
                "status": row["status"],
                "notional": plan.get("notional"),
                "qty": plan.get("payload", {}).get("qty"),
                "stop_loss": plan.get("payload", {}).get("stop_loss"),
                "take_profit": plan.get("payload", {}).get("take_profit"),
                "broker_order_id": row["broker_order_id"],
                "cycle_id": row["cycle_id"],
            }
        )
    return sorted(result, key=lambda item: item["time"])


def _pl_candidate(kind: str, item: dict[str, Any], pl_key: str, pc_key: str) -> dict[str, Any] | None:
    pl = item.get(pl_key)
    if pl is None:
        return None
    return {
        "kind": kind,
        "symbol": item.get("symbol"),
        "pl": round(float(pl), 2),
        "plpc": item.get(pc_key),
        "time": item.get("time"),
    }


def _current_statistics(
    summary: dict[str, Any],
    trades: list[dict[str, Any]],
    open_positions: list[dict[str, Any]],
) -> dict[str, Any]:
    realized_candidates = [
        candidate
        for trade in trades
        if (candidate := _pl_candidate("trade_realizado", trade, "realized_pl", "realized_plpc")) is not None
    ]
    open_candidates = [
        candidate
        for position in open_positions
        if (candidate := _pl_candidate("posicion_abierta", position, "unrealized_pl", "unrealized_plpc")) is not None
    ]
    all_candidates = realized_candidates + open_candidates
    equity = float(summary.get("equity") or 0)
    exposure = round(sum(float(item.get("market_value") or 0) for item in open_positions), 2)
    total_pl = round(float(summary.get("realized_pl") or 0) + float(summary.get("unrealized_pl") or 0), 2)
    return {
        "equity": summary.get("equity", 0.0),
        "cash": summary.get("cash", 0.0),
        "cash_pct": round(float(summary.get("cash") or 0) / equity, 4) if equity else 0.0,
        "open_positions": summary.get("open_positions", 0),
        "exposure": exposure,
        "exposure_pct": round(exposure / equity, 4) if equity else 0.0,
        "buy_notional": summary.get("buy_notional", 0.0),
        "sell_notional": summary.get("sell_notional", 0.0),
        "realized_pl": summary.get("realized_pl", 0.0),
        "unrealized_pl": summary.get("unrealized_pl", 0.0),
        "total_pl": total_pl,
        "total_plpc_on_equity": round(total_pl / equity, 4) if equity else 0.0,
        "best_realized_trade": max(realized_candidates, key=lambda item: item["pl"], default=None),
        "worst_realized_trade": min(realized_candidates, key=lambda item: item["pl"], default=None),
        "best_open_position": max(open_candidates, key=lambda item: item["pl"], default=None),
        "worst_open_position": min(open_candidates, key=lambda item: item["pl"], default=None),
        "biggest_gain": max(all_candidates, key=lambda item: item["pl"], default=None),
        "biggest_loss": min(all_candidates, key=lambda item: item["pl"], default=None),
    }


def build_trade_history(
    settings: Settings,
    *,
    limit: int = 100,
    start_date: str | None = DEFAULT_HISTORY_START_DATE,
    scope: str = "account",
) -> dict[str, Any]:
    broker = BrokerClientFactory(settings)
    portfolio = broker.alpaca_portfolio_snapshot()
    warnings = []
    fills = []
    try:
        fills = broker.alpaca_trade_activities(limit=max(limit, 100))
    except Exception as exc:  # noqa: BLE001 - local order fallback is still useful.
        warnings.append(f"No se pudieron leer fills de Alpaca: {exc}")

    agent_scope = _local_agent_order_scope(settings.database_path)
    account_fill_count = len(fills)
    if scope == "agent":
        fills = _filter_fills_for_agent(fills, agent_scope)
        warnings.append(
            "Historico filtrado a operaciones del agente. Usa --scope account para incluir toda la cuenta Alpaca."
        )
    fills = _filter_fills_from_date(fills, start_date, settings.local_timezone)

    trades, summary = realized_pl_from_fills(fills)
    open_positions = _open_positions_summary(portfolio)
    if scope == "agent":
        local_symbols = agent_scope.get("symbols", set())
        open_positions = [item for item in open_positions if str(item["symbol"]).upper() in local_symbols]
    risk_by_symbol = _local_buy_risk_plans(settings.database_path)
    _attach_risk_levels(trades, open_positions, risk_by_symbol)
    unrealized_pl = round(sum(item["unrealized_pl"] for item in open_positions), 2)
    summary = {
        **summary,
        "scope": scope,
        "start_date": start_date,
        "account_fills_seen": account_fill_count,
        "agent_symbols": sorted(agent_scope.get("symbols", set())),
        "open_positions": len(open_positions),
        "unrealized_pl": unrealized_pl,
        "equity": round(portfolio.portfolio_value, 2),
        "cash": round(portfolio.cash, 2),
    }
    visible_trades = trades[-limit:] if limit > 0 else trades
    today = datetime.now(ZoneInfo(settings.local_timezone)).date().isoformat()
    daily = _daily_groups(
        visible_trades,
        open_positions,
        today=today,
        portfolio_value=portfolio.portfolio_value,
    )
    return {
        "summary": summary,
        "current_statistics": _current_statistics(summary, trades, open_positions),
        "trades": visible_trades,
        "days": daily,
        "open_positions": open_positions,
        "risk_levels": risk_by_symbol,
        "local_broker_orders": _local_broker_orders(settings.database_path, limit, start_date),
        "warnings": warnings,
    }
