"""Profitability scoreboard for paper edge and promotion decisions."""

from __future__ import annotations

import math
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store

from .edge_analysis import build_spy_daily_returns, linked_executed_buy_signals
from .exit_horizon_shadow import build_exit_horizon_shadow
from .signal_learning import HORIZONS


def _num(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _max_drawdown_from_returns(values: list[Any]) -> float | None:
    clean = [number for value in values if (number := _num(value)) is not None]
    if not clean:
        return None
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for value in clean:
        equity *= 1.0 + value
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)
    return round(max_dd, 4)


def _metric_coverage(values: list[float | None]) -> dict[str, int | str]:
    total = len(values)
    available = sum(value is not None for value in values)
    status = "available" if available == total and total else "partial" if available else "unavailable"
    return {"available": available, "total": total, "status": status}


def _sum_or_none(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    return round(sum(clean), 6) if clean else None


def _performance_summary(settings: Settings, store: Store, *, since_date: str) -> dict[str, Any]:
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
    benchmark = build_spy_daily_returns(
        settings,
        start=str(rows[0].get("session_date") or since_date),
        end=str(rows[-1].get("session_date") or since_date),
    )
    enriched_rows = []
    for original in rows:
        row = dict(original)
        session_date = str(row.get("session_date") or "")[:10]
        pnl = _num(row.get("pnl_pct"))
        spy = _num(row.get("spy_pct"))
        benchmark_source = "persisted"
        if spy is None:
            spy = benchmark.get(session_date)
            benchmark_source = "fetched" if spy is not None else "missing"
        alpha = _num(row.get("alpha"))
        if alpha is None and pnl is not None and spy is not None:
            alpha = round(pnl - spy, 6)
        row["spy_pct"] = spy
        row["alpha"] = alpha
        row["benchmark_source"] = benchmark_source
        enriched_rows.append(row)
    rows = enriched_rows
    pnl_values = [_num(row.get("pnl_pct")) for row in rows]
    spy_values = [_num(row.get("spy_pct")) for row in rows]
    alpha_values = [_num(row.get("alpha")) for row in rows]
    explicit_dd = [_num(row.get("max_dd")) for row in rows if _num(row.get("max_dd")) is not None]
    latest = rows[-1]
    cumulative_pnl = _sum_or_none(pnl_values)
    cumulative_spy = _sum_or_none(spy_values)
    cumulative_alpha = _sum_or_none(alpha_values)
    return {
        "available": True,
        "rows": len(rows),
        "start_date": rows[0].get("session_date"),
        "end_date": rows[-1].get("session_date"),
        "latest_equity": latest.get("equity"),
        "cumulative_pnl_pct": cumulative_pnl,
        "cumulative_spy_pct": cumulative_spy,
        "cumulative_alpha": cumulative_alpha,
        "metric_coverage": {
            "pnl_pct": _metric_coverage(pnl_values),
            "spy_pct": _metric_coverage(spy_values),
            "alpha": _metric_coverage(alpha_values),
            "max_dd": _metric_coverage([_num(row.get("max_dd")) for row in rows]),
        },
        "benchmark_coverage": {
            "available": sum(value is not None for value in spy_values),
            "total": len(rows),
            "ratio": round(sum(value is not None for value in spy_values) / len(rows), 4),
        },
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
    horizon_shadow = build_exit_horizon_shadow(
        settings,
        store,
        since_date=since_date,
        linked_rows=executed["linked_rows"],
    )
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
        "performance": _performance_summary(settings, store, since_date=since_date),
        "execution": {
            "linked_executed_buys": len(executed["linked_rows"]),
            "unmatched_order_ids": len(executed["unmatched_order_ids"]),
            "benchmark_points": executed["benchmark_points"],
            "regime_coverage": executed["regime_coverage"],
        },
        "edge": edge_tables,
        "edge_table": flat_rows,
        "exit_horizon_shadow": horizon_shadow,
    }
