"""Forward-edge diagnostics for executed buys and backtest veto cohorts."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Callable

import pandas as pd

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store

from .execution_linking import match_signal_row_for_buy_order
from .market_data import download_daily_prices
from .signal_learning import HORIZONS, _indicator_tags, _setup_key


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _winner(value: float | None) -> bool:
    return value is not None and value > 0


def _profit_factor(values: list[float | None]) -> float | None:
    gains = sum(value for value in values if value is not None and value > 0)
    losses = -sum(value for value in values if value is not None and value < 0)
    if gains <= 0 and losses <= 0:
        return None
    if losses <= 0:
        return None
    return round(gains / losses, 4)


def _mean(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return round(sum(clean) / len(clean), 4)


def _date_text(value: str | None) -> str:
    return str(value or "")[:10]


def _loads(raw: str | None) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _order_plan_created_at(payload: dict[str, Any]) -> str | None:
    return str(((payload.get("plan") or {}).get("created_at")) or "").strip() or None


def _build_spy_forward_returns(
    settings: Settings,
    *,
    start: str,
    end: str,
) -> dict[tuple[str, int], float | None]:
    return _build_spy_forward_context(settings, start=start, end=end)["returns"]


def _regime_from_benchmark(close: float | None, sma50: float | None, sma200: float | None) -> str:
    if close is None or sma50 is None or sma200 is None:
        return "unknown"
    if close >= sma50 >= sma200:
        return "bullish"
    if close <= sma50 <= sma200:
        return "bearish"
    return "neutral"


def _build_spy_forward_context(
    settings: Settings,
    *,
    start: str,
    end: str,
) -> dict[str, dict[Any, Any]]:
    download_start = start
    download_end = end
    try:
        download_start = (date.fromisoformat(start[:10]) - timedelta(days=300)).isoformat()
        download_end = (date.fromisoformat(end[:10]) + timedelta(days=max(HORIZONS) * 3)).isoformat()
    except ValueError:
        pass
    try:
        frame = download_daily_prices(
            [settings.benchmark_symbol or "SPY"],
            start=download_start,
            end=download_end,
            cache_dir=settings.data_dir / "cache" / "market_data",
            provider=settings.market_data_provider,
            fmp_api_key=settings.fmp_api_key,
        )
    except Exception:
        return {"returns": {}, "regimes": {}}
    if frame.empty:
        return {"returns": {}, "regimes": {}}
    benchmark_symbol = str(settings.benchmark_symbol or "SPY").upper()
    if isinstance(frame.columns, pd.MultiIndex):
        if benchmark_symbol not in frame.columns.get_level_values(0):
            return {"returns": {}, "regimes": {}}
        spy = frame[benchmark_symbol].copy()
    else:
        spy = frame.copy()
    if "Close" not in spy.columns:
        return {"returns": {}, "regimes": {}}
    closes = spy["Close"].dropna()
    if closes.empty:
        return {"returns": {}, "regimes": {}}
    returns: dict[tuple[str, int], float | None] = {}
    regimes: dict[str, str] = {}
    sma50 = closes.rolling(50, min_periods=20).mean()
    sma200 = closes.rolling(200, min_periods=50).mean()
    values = list(closes.items())
    for index, (ts, close) in enumerate(values):
        try:
            close_float = float(close)
        except (TypeError, ValueError):
            continue
        date_key = str(ts)[:10]
        regimes[date_key] = _regime_from_benchmark(
            close_float,
            _num(sma50.iloc[index]),
            _num(sma200.iloc[index]),
        )
        for horizon in HORIZONS:
            future_index = index + horizon
            if future_index >= len(values):
                returns[(date_key, horizon)] = None
                continue
            future_close = values[future_index][1]
            try:
                future_float = float(future_close)
            except (TypeError, ValueError):
                returns[(date_key, horizon)] = None
                continue
            returns[(date_key, horizon)] = round((future_float / close_float) - 1.0, 6)
    return {"returns": returns, "regimes": regimes}


def build_spy_daily_returns(
    settings: Settings,
    *,
    start: str,
    end: str,
) -> dict[str, float]:
    """Return close-to-close SPY returns keyed by trading session."""

    download_start = start
    download_end = end
    try:
        download_start = (date.fromisoformat(start[:10]) - timedelta(days=10)).isoformat()
        download_end = (date.fromisoformat(end[:10]) + timedelta(days=1)).isoformat()
    except ValueError:
        pass
    try:
        frame = download_daily_prices(
            [settings.benchmark_symbol or "SPY"],
            start=download_start,
            end=download_end,
            cache_dir=settings.data_dir / "cache" / "market_data",
            provider=settings.market_data_provider,
            fmp_api_key=settings.fmp_api_key,
        )
    except Exception:
        return {}
    if frame is None or frame.empty:
        return {}
    benchmark_symbol = str(settings.benchmark_symbol or "SPY").upper()
    if isinstance(frame.columns, pd.MultiIndex):
        if benchmark_symbol not in frame.columns.get_level_values(0):
            return {}
        frame = frame[benchmark_symbol].copy()
    if "Close" not in frame.columns:
        return {}
    closes = pd.to_numeric(frame["Close"], errors="coerce").dropna()
    returns = closes.pct_change()
    return {
        str(timestamp)[:10]: round(float(value), 6)
        for timestamp, value in returns.items()
        if pd.notna(value) and start[:10] <= str(timestamp)[:10] <= end[:10]
    }


def _metrics(rows: list[dict[str, Any]], benchmark: dict[tuple[str, int], float | None]) -> dict[str, Any]:
    out: dict[str, Any] = {"n": len(rows)}
    for horizon in HORIZONS:
        values = [_num((row.get("outcome") or {}).get(f"return_{horizon}d")) for row in rows]
        alpha_values = []
        wins = 0
        matured = 0
        for row, value in zip(rows, values):
            if value is None:
                continue
            matured += 1
            if _winner(value):
                wins += 1
            spy_return = benchmark.get((_date_text(row.get("signal_date")), horizon))
            if spy_return is not None:
                alpha_values.append(value - spy_return)
        out[f"matured_{horizon}d"] = matured
        out[f"expectancy_{horizon}d"] = _mean(values)
        out[f"hit_rate_{horizon}d"] = _round((wins / matured), 4) if matured else None
        out[f"profit_factor_{horizon}d"] = _profit_factor(values)
        out[f"alpha_{horizon}d"] = _mean(alpha_values)
    return out


def summarize_by_group(
    rows: list[dict[str, Any]],
    benchmark: dict[tuple[str, int], float | None],
    *,
    key_fn: Callable[[dict[str, Any]], str | None],
    min_rows: int = 1,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = key_fn(row)
        if not key:
            continue
        grouped[key].append(row)
    summaries = []
    for key, items in grouped.items():
        if len(items) < min_rows:
            continue
        metrics = _metrics(items, benchmark)
        summaries.append({"key": key, **metrics})
    return sorted(
        summaries,
        key=lambda item: (
            item.get("expectancy_5d") is not None,
            item.get("expectancy_5d") or -999,
            item.get("n") or 0,
        ),
        reverse=True,
    )


def linked_executed_buy_signals(
    settings: Settings,
    store: Store,
    *,
    since_date: str,
) -> dict[str, Any]:
    with store.connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT broker_order_id, plan_id, symbol, side, status, created_at, payload_json
            FROM broker_orders
            WHERE lower(side) = 'buy'
              AND lower(status) = 'filled'
              AND created_at >= ?
            ORDER BY created_at ASC
            """,
            (f"{since_date}T00:00:00",),
        ).fetchall()
        linked = []
        unmatched = []
        for row in rows:
            payload = _loads(row["payload_json"])
            signal = match_signal_row_for_buy_order(
                conn,
                symbol=str(row["symbol"]),
                order_created_at=row["created_at"],
                plan_created_at=_order_plan_created_at(payload),
                broker_order_id=str(row["broker_order_id"]),
            )
            if not signal:
                unmatched.append(str(row["broker_order_id"]))
                continue
            linked.append(
                {
                    **signal,
                    "broker_order_id": row["broker_order_id"],
                    "plan_id": row["plan_id"],
                    "order_created_at": row["created_at"],
                }
            )
    if linked:
        start = min(_date_text(item.get("signal_date")) for item in linked)
        end = max(_date_text(item.get("signal_date")) for item in linked)
    else:
        start = since_date
        end = since_date
    benchmark_context = _build_spy_forward_context(settings, start=start, end=end)
    benchmark = benchmark_context["returns"]
    benchmark_regimes = benchmark_context["regimes"]
    regime_sources: dict[str, int] = {"persisted": 0, "benchmark": 0, "unknown": 0}
    for row in linked:
        features = row.get("features") or {}
        row["setup_quality"] = str(features.get("setup_quality") or "unknown")
        row["setup_key"] = _setup_key(row)
        row["tags"] = _indicator_tags(row)
        persisted_regime = features.get("market_regime") or features.get("regime")
        benchmark_regime = benchmark_regimes.get(_date_text(row.get("signal_date")))
        row["regime"] = str(persisted_regime or benchmark_regime or "unknown")
        regime_source = (
            "persisted"
            if persisted_regime
            else "benchmark"
            if benchmark_regime and benchmark_regime != "unknown"
            else "unknown"
        )
        row["regime_source"] = regime_source
        regime_sources[regime_source] += 1
    return {
        "linked_rows": linked,
        "unmatched_order_ids": unmatched,
        "benchmark_points": len(benchmark),
        "regime_coverage": {
            **regime_sources,
            "known_ratio": round(
                (regime_sources["persisted"] + regime_sources["benchmark"]) / len(linked),
                4,
            )
            if linked
            else 0.0,
        },
        "setup_quality": summarize_by_group(linked, benchmark, key_fn=lambda row: row.get("setup_quality")),
        "setup_key": summarize_by_group(linked, benchmark, key_fn=lambda row: row.get("setup_key")),
        "tag": summarize_by_group(
            [
                {**row, "tag": tag}
                for row in linked
                for tag in list(row.get("tags") or [])
            ],
            benchmark,
            key_fn=lambda row: row.get("tag"),
            min_rows=2,
        ),
        "regime": summarize_by_group(linked, benchmark, key_fn=lambda row: row.get("regime")),
    }


def veto_forward_cohorts(
    settings: Settings,
    store: Store,
    *,
    since_date: str,
) -> dict[str, Any]:
    rows = [
        row
        for row in store.signal_outcomes(limit=200000, since_date=since_date)
        if str(row.get("decision") or "") == "blocked_backtest"
    ]
    if rows:
        start = min(_date_text(row.get("signal_date")) for row in rows)
        end = max(_date_text(row.get("signal_date")) for row in rows)
    else:
        start = since_date
        end = since_date
    benchmark = _build_spy_forward_returns(settings, start=start, end=end)
    for row in rows:
        reason = str((((row.get("gate") or {}).get("backtest_gate") or {}).get("reason")) or "unknown").strip()
        row["veto_reason"] = reason or "unknown"
    return {
        "total_rows": len(rows),
        "by_reason": summarize_by_group(rows, benchmark, key_fn=lambda row: row.get("veto_reason")),
    }
