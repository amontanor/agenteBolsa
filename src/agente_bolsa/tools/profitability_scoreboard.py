"""Profitability scoreboard for paper edge and promotion decisions."""

from __future__ import annotations

from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store

from .edge_analysis import linked_executed_buy_signals
from .signal_learning import HORIZONS


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _max_drawdown_from_returns(values: list[float]) -> float | None:
    if not values:
        return None
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for value in values:
        equity *= 1.0 + value
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)
    return round(max_dd, 4)


def _performance_summary(store: Store, *, since_date: str) -> dict[str, Any]:
    rows = store.performance_daily(limit=0, since_date=since_date)
    if not rows:
        return {
            "available": False,
            "rows": 0,
            "latest_equity": None,
            "cumulative_pnl_pct": None,
            "cumulative_spy_pct": None,
            "cumulative_alpha": None,
            "max_drawdown": None,
            "latest_iq_score": None,
        }
    pnl_values = [_num(row.get("pnl_pct")) or 0.0 for row in rows]
    spy_values = [_num(row.get("spy_pct")) or 0.0 for row in rows]
    alpha_values = [_num(row.get("alpha")) for row in rows]
    explicit_dd = [_num(row.get("max_dd")) for row in rows if _num(row.get("max_dd")) is not None]
    latest = rows[-1]
    cumulative_pnl = round(sum(pnl_values), 6)
    cumulative_spy = round(sum(spy_values), 6)
    cumulative_alpha = (
        round(sum(value for value in alpha_values if value is not None), 6)
        if any(value is not None for value in alpha_values)
        else round(cumulative_pnl - cumulative_spy, 6)
    )
    return {
        "available": True,
        "rows": len(rows),
        "start_date": rows[0].get("session_date"),
        "end_date": rows[-1].get("session_date"),
        "latest_equity": latest.get("equity"),
        "cumulative_pnl_pct": cumulative_pnl,
        "cumulative_spy_pct": cumulative_spy,
        "cumulative_alpha": cumulative_alpha,
        "max_drawdown": max(explicit_dd) if explicit_dd else _max_drawdown_from_returns(pnl_values),
        "latest_iq_score": latest.get("iq_score"),
        "latest_hit_rate_20": latest.get("hit_rate_20"),
        "latest_sharpe_60": latest.get("sharpe_60"),
        "series": rows,
    }


def _table_rows(section: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    table: list[dict[str, Any]] = []
    for item in rows:
        key = item.get("key")
        for horizon in HORIZONS:
            table.append(
                {
                    "section": section,
                    "key": key,
                    "horizon": f"{horizon}d",
                    "n": item.get("n"),
                    "matured": item.get(f"matured_{horizon}d"),
                    "expectancy": item.get(f"expectancy_{horizon}d"),
                    "hit_rate": item.get(f"hit_rate_{horizon}d"),
                    "profit_factor": item.get(f"profit_factor_{horizon}d"),
                    "alpha": item.get(f"alpha_{horizon}d"),
                }
            )
    return table


def build_profitability_scoreboard(
    settings: Settings,
    store: Store,
    *,
    since_date: str = "2026-04-01",
) -> dict[str, Any]:
    executed = linked_executed_buy_signals(settings, store, since_date=since_date)
    edge_tables = {
        "setup_quality": executed["setup_quality"],
        "setup": executed["setup_key"],
        "tag": executed["tag"],
        "regime": executed["regime"],
    }
    flat_rows: list[dict[str, Any]] = []
    for section, rows in edge_tables.items():
        flat_rows.extend(_table_rows(section, rows))
    return {
        "since_date": since_date,
        "performance": _performance_summary(store, since_date=since_date),
        "execution": {
            "linked_executed_buys": len(executed["linked_rows"]),
            "unmatched_order_ids": len(executed["unmatched_order_ids"]),
            "benchmark_points": executed["benchmark_points"],
        },
        "edge": edge_tables,
        "edge_table": flat_rows,
    }
