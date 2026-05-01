"""Deterministic long-only backtest for the current technical entry rule."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .costs import TransactionCostModel
from .market_data import download_daily_prices
from .technical_analysis import add_basic_technical_features
from .technical_state_validator import validate_symbol_technical_state


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _date_label(value: Any) -> str:
    if hasattr(value, "date"):
        return str(value.date())
    return str(value)


def _symbol_frame(data: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if isinstance(data.columns, pd.MultiIndex):
        return data[symbol].copy().dropna(how="all")
    return data.copy().dropna(how="all")


def _signal_from_window(
    symbol: str,
    window: pd.DataFrame,
    *,
    min_score: int,
    setup_quality: str,
) -> dict[str, Any] | None:
    state = validate_symbol_technical_state(symbol, window)
    if state.get("direction") != "long":
        return None
    if int(state.get("score") or 0) < min_score:
        return None
    if setup_quality and state.get("setup_quality") != setup_quality:
        return None
    risk = state.get("risk_plan", {}) or {}
    if not risk.get("entry_price") or not risk.get("stop_loss") or not risk.get("take_profit"):
        return None
    return state


def _exit_trade(
    future: pd.DataFrame,
    *,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    max_holding_days: int,
) -> tuple[str, str, float, int]:
    hold = 0
    last_date = ""
    last_close = entry_price
    for index, row in future.head(max_holding_days).iterrows():
        hold += 1
        last_date = _date_label(index)
        low = _safe_float(row.get("Low"))
        high = _safe_float(row.get("High"))
        close = _safe_float(row.get("Close"), entry_price)
        last_close = close
        if low <= stop_loss:
            return last_date, "stop_loss", stop_loss, hold
        if high >= take_profit:
            return last_date, "take_profit", take_profit, hold
    return last_date, "time_stop", last_close, hold


def backtest_technical_long_rule(
    symbol: str,
    prices: pd.DataFrame,
    *,
    min_score: int = 7,
    setup_quality: str = "strong",
    warmup_days: int = 260,
    max_holding_days: int = 10,
    initial_equity: float = 10_000.0,
    position_exposure: float = 0.05,
    costs: TransactionCostModel | None = None,
) -> dict[str, Any]:
    """Backtest the current long setup: strong technical state + ATR stop/take."""

    symbol = symbol.upper().strip()
    costs = costs or TransactionCostModel()
    features = add_basic_technical_features(prices).dropna(subset=["Close"]).copy()
    trades: list[dict[str, Any]] = []
    equity_curve = [{"date": _date_label(features.index[min(warmup_days, len(features) - 1)]), "equity": initial_equity}]
    equity = initial_equity
    index = max(warmup_days, 260)

    while index < len(features) - 2:
        window = features.iloc[: index + 1]
        try:
            signal = _signal_from_window(
                symbol,
                window,
                min_score=min_score,
                setup_quality=setup_quality,
            )
        except Exception:
            signal = None
        if not signal:
            index += 1
            continue

        entry_row = features.iloc[index + 1]
        entry_date = _date_label(features.index[index + 1])
        entry_price = _safe_float(entry_row.get("Open") or entry_row.get("Close"))
        if entry_price <= 0:
            index += 1
            continue

        risk = signal["risk_plan"]
        stop_loss = _safe_float(risk.get("stop_loss"))
        take_profit = _safe_float(risk.get("take_profit"))
        if not (0 < stop_loss < entry_price < take_profit):
            index += 1
            continue

        notional = min(equity * position_exposure, equity)
        qty = math.floor(notional / entry_price)
        if qty <= 0:
            index += 1
            continue
        notional = qty * entry_price

        future = features.iloc[index + 1 :]
        exit_date, exit_reason, exit_price, holding_days = _exit_trade(
            future,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            max_holding_days=max_holding_days,
        )
        gross_pl = qty * (exit_price - entry_price)
        cost = costs.round_trip_cost(notional)
        net_pl = gross_pl - cost
        net_return = net_pl / notional if notional else 0.0
        equity += net_pl
        trades.append(
            {
                "symbol": symbol,
                "entry_date": entry_date,
                "exit_date": exit_date,
                "exit_reason": exit_reason,
                "holding_days": holding_days,
                "qty": qty,
                "entry_price": round(entry_price, 4),
                "exit_price": round(exit_price, 4),
                "stop_loss": round(stop_loss, 4),
                "take_profit": round(take_profit, 4),
                "notional": round(notional, 2),
                "gross_pl": round(gross_pl, 2),
                "cost": round(cost, 2),
                "net_pl": round(net_pl, 2),
                "net_return": round(net_return, 6),
                "signal_score": signal.get("score"),
                "signal_reasons": signal.get("reasons", [])[:6],
            }
        )
        equity_curve.append({"date": exit_date, "equity": round(equity, 2)})
        index += max(holding_days, 1) + 1

    return _build_report(
        symbol=symbol,
        trades=trades,
        equity_curve=equity_curve,
        initial_equity=initial_equity,
        final_equity=equity,
        min_score=min_score,
        setup_quality=setup_quality,
        max_holding_days=max_holding_days,
        costs=costs,
    )


def _max_drawdown(equity_curve: list[dict[str, Any]]) -> float:
    peak = None
    max_dd = 0.0
    for point in equity_curve:
        equity = _safe_float(point.get("equity"))
        if peak is None or equity > peak:
            peak = equity
        if peak and peak > 0:
            max_dd = min(max_dd, (equity - peak) / peak)
    return max_dd


def _sharpe(returns: list[float]) -> float | None:
    if len(returns) < 2:
        return None
    series = pd.Series(returns)
    std = float(series.std())
    if std <= 0:
        return None
    return float(series.mean() / std * math.sqrt(252 / 10))


def _build_report(
    *,
    symbol: str,
    trades: list[dict[str, Any]],
    equity_curve: list[dict[str, Any]],
    initial_equity: float,
    final_equity: float,
    min_score: int,
    setup_quality: str,
    max_holding_days: int,
    costs: TransactionCostModel,
) -> dict[str, Any]:
    wins = [trade for trade in trades if trade["net_pl"] > 0]
    losses = [trade for trade in trades if trade["net_pl"] <= 0]
    gross_profit = sum(trade["net_pl"] for trade in wins)
    gross_loss = abs(sum(trade["net_pl"] for trade in losses))
    returns = [float(trade["net_return"]) for trade in trades]
    metrics = {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "hit_rate": round(len(wins) / len(trades), 4) if trades else 0.0,
        "total_net_pl": round(final_equity - initial_equity, 2),
        "total_return": round((final_equity - initial_equity) / initial_equity, 4) if initial_equity else 0.0,
        "avg_trade_return": round(sum(returns) / len(returns), 6) if returns else 0.0,
        "avg_profit": round(sum(trade["net_pl"] for trade in trades) / len(trades), 2) if trades else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss > 0 else None,
        "max_drawdown": round(_max_drawdown(equity_curve), 4),
        "sharpe": round(_sharpe(returns), 4) if _sharpe(returns) is not None else None,
    }
    return {
        "symbol": symbol,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "strategy": {
            "name": "technical_long_strong_atr_stop_take",
            "direction": "long",
            "entry_rule": f"direction=long, setup_quality={setup_quality}, score>={min_score}",
            "exit_rule": "stop_loss or take_profit or time_stop",
            "max_holding_days": max_holding_days,
            "costs": {
                "commission_bps": costs.commission_bps,
                "slippage_bps": costs.slippage_bps,
                "round_trip_bps": costs.round_trip_bps,
            },
        },
        "metrics": metrics,
        "equity_curve": equity_curve,
        "trades": trades,
    }


def build_symbol_backtest(
    symbol: str,
    output_dir: Path,
    run_id: str,
    *,
    start: str,
    end: str | None = None,
    min_score: int = 7,
    setup_quality: str = "strong",
    max_holding_days: int = 10,
) -> dict[str, Any]:
    end_value = end or (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    data = download_daily_prices([symbol], start=start, end=end_value)
    frame = _symbol_frame(data, symbol.upper())
    report = backtest_technical_long_rule(
        symbol,
        frame,
        min_score=min_score,
        setup_quality=setup_quality,
        max_holding_days=max_holding_days,
    )
    report["period"] = {"from": start, "to": end_value}
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"backtest_{symbol.upper()}_{run_id}.json"
    report["path"] = str(path)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    return report
