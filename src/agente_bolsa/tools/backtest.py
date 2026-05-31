"""Deterministic long-only backtest for the current technical entry rule."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .costs import TransactionCostModel
from .market_data import download_daily_prices_with_metadata
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


def _price_on_or_after(frame: pd.DataFrame, date_text: str, column: str) -> float | None:
    if frame.empty:
        return None
    matches = frame.loc[frame.index.astype(str).str[:10] >= date_text]
    if matches.empty:
        return None
    return _safe_float(matches.iloc[0].get(column), default=float("nan"))


def _signal_from_window(
    symbol: str,
    window: pd.DataFrame,
    *,
    min_score: int,
    setup_quality: str,
    allowed_setup_names: set[str] | None = None,
) -> dict[str, Any] | None:
    state = validate_symbol_technical_state(symbol, window)
    if state.get("direction") != "long":
        return None
    if int(state.get("score") or 0) < min_score:
        return None
    if setup_quality and state.get("setup_quality") != setup_quality:
        return None
    setup_name = _setup_name(state)
    if allowed_setup_names and setup_name not in allowed_setup_names:
        return None
    risk = state.get("risk_plan", {}) or {}
    if not risk.get("entry_price") or not risk.get("stop_loss") or not risk.get("take_profit"):
        return None
    state["setup_name"] = setup_name
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


def _entry_regime(signal: dict[str, Any], window: pd.DataFrame) -> tuple[str, str]:
    technical_state = signal.get("technical_state", {}) or {}
    above_long = technical_state.get("above_long_trend")
    recent_return = technical_state.get("return_20d")
    if above_long is True:
        trend = "bull_trend"
    elif above_long is False:
        trend = "bear_trend"
    else:
        trend = "unknown_trend"
    if isinstance(recent_return, (int, float)) and recent_return > 0.05:
        momentum = "strong_momentum"
    elif isinstance(recent_return, (int, float)) and recent_return > 0:
        momentum = "positive_momentum"
    elif isinstance(recent_return, (int, float)):
        momentum = "negative_momentum"
    else:
        momentum = "unknown_momentum"
    return trend, momentum


def _setup_name(signal: dict[str, Any]) -> str:
    technical_state = signal.get("technical_state", {}) or {}
    if technical_state.get("event_momentum_long"):
        return "event_momentum"
    if technical_state.get("range_expansion_breakout_long"):
        return "range_expansion_breakout"
    if technical_state.get("orderly_breakout_long"):
        return "orderly_breakout"
    if technical_state.get("momentum_shakeout_hold_long"):
        return "momentum_shakeout_hold"
    breakout_continuation = bool(technical_state.get("breakout_continuation_long"))
    positive_trend = bool(technical_state.get("trend_positive")) and bool(technical_state.get("above_long_trend"))
    positive_volume = _safe_float(technical_state.get("volume_zscore_20"), default=0.0) > 0
    if breakout_continuation and not positive_volume:
        return "momentum_confirmation"
    if breakout_continuation:
        return "trend_volume"
    if positive_trend and positive_volume:
        return "trend_volume"
    return "baseline_trend"


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
    allowed_setup_names: set[str] | None = None,
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
                allowed_setup_names=allowed_setup_names,
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
        regime_trend, regime_momentum = _entry_regime(signal, window)

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
                "setup_name": signal.get("setup_name") or _setup_name(signal),
                "signal_reasons": signal.get("reasons", [])[:6],
                "regime_trend": regime_trend,
                "regime_momentum": regime_momentum,
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
        allowed_setup_names=allowed_setup_names,
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


def _sortino(returns: list[float]) -> float | None:
    if len(returns) < 2:
        return None
    series = pd.Series(returns)
    downside = series[series < 0]
    if downside.empty:
        return None
    downside_std = float(downside.std())
    if downside_std <= 0:
        return None
    return float(series.mean() / downside_std * math.sqrt(252 / 10))


def _calmar(total_return: float, max_drawdown: float, trades: int, avg_holding_days: float) -> float | None:
    if max_drawdown >= 0:
        return None
    periods = max(trades * max(avg_holding_days, 1.0), 1.0)
    annualized_return = (1.0 + total_return) ** (252.0 / periods) - 1.0 if total_return > -1.0 else -1.0
    denominator = abs(max_drawdown)
    if denominator <= 0:
        return None
    return float(annualized_return / denominator)


def _drawdown_windows(equity_curve: list[dict[str, Any]]) -> dict[str, float | None]:
    windows = {"20d": 20, "60d": 60, "120d": 120}
    result: dict[str, float | None] = {}
    if len(equity_curve) < 2:
        return {key: None for key in windows}
    for label, size in windows.items():
        points = equity_curve[-size:] if len(equity_curve) > size else equity_curve
        result[label] = round(_max_drawdown(points), 4) if len(points) >= 2 else None
    return result


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
    allowed_setup_names: set[str] | None = None,
) -> dict[str, Any]:
    wins = [trade for trade in trades if trade["net_pl"] > 0]
    losses = [trade for trade in trades if trade["net_pl"] <= 0]
    gross_profit = sum(trade["net_pl"] for trade in wins)
    gross_loss = abs(sum(trade["net_pl"] for trade in losses))
    returns = [float(trade["net_return"]) for trade in trades]
    avg_holding_days = (
        round(sum(int(trade["holding_days"]) for trade in trades) / len(trades), 2) if trades else 0.0
    )
    total_return = round((final_equity - initial_equity) / initial_equity, 4) if initial_equity else 0.0
    max_drawdown = round(_max_drawdown(equity_curve), 4)
    avg_win_return = sum(float(trade["net_return"]) for trade in wins) / len(wins) if wins else 0.0
    avg_loss_return = sum(float(trade["net_return"]) for trade in losses) / len(losses) if losses else 0.0
    expectancy_return = (
        (len(wins) / len(trades)) * avg_win_return - (len(losses) / len(trades)) * abs(avg_loss_return)
        if trades
        else 0.0
    )
    total_holding_days = sum(int(trade["holding_days"]) for trade in trades)
    start_date = pd.to_datetime(equity_curve[0]["date"]) if equity_curve else None
    end_date = pd.to_datetime(equity_curve[-1]["date"]) if equity_curve else None
    period_days = max(int((end_date - start_date).days), 1) if start_date is not None and end_date is not None else 1
    metrics = {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "hit_rate": round(len(wins) / len(trades), 4) if trades else 0.0,
        "total_net_pl": round(final_equity - initial_equity, 2),
        "total_return": total_return,
        "avg_trade_return": round(sum(returns) / len(returns), 6) if returns else 0.0,
        "avg_profit": round(sum(trade["net_pl"] for trade in trades) / len(trades), 2) if trades else 0.0,
        "expectancy_per_trade": round(sum(float(trade["net_pl"]) for trade in trades) / len(trades), 2) if trades else 0.0,
        "expectancy_return": round(expectancy_return, 6),
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss > 0 else None,
        "max_drawdown": max_drawdown,
        "sharpe": round(_sharpe(returns), 4) if _sharpe(returns) is not None else None,
        "sortino": round(_sortino(returns), 4) if _sortino(returns) is not None else None,
        "calmar": round(_calmar(total_return, max_drawdown, len(trades), avg_holding_days), 4)
        if _calmar(total_return, max_drawdown, len(trades), avg_holding_days) is not None
        else None,
        "total_cost": round(sum(float(trade["cost"]) for trade in trades), 2),
        "avg_holding_days": avg_holding_days,
        "exposure_time_pct": round(min(total_holding_days / period_days, 1.0), 4) if trades else 0.0,
        "turnover": round(sum(float(trade["notional"]) for trade in trades) / initial_equity, 4) if initial_equity else 0.0,
        "exit_reasons": dict(pd.Series([trade["exit_reason"] for trade in trades]).value_counts()) if trades else {},
        "drawdown_windows": _drawdown_windows(equity_curve),
    }
    setup_summary: dict[str, dict[str, Any]] = {}
    for trade in trades:
        key = str(trade.get("setup_name") or "unknown")
        bucket = setup_summary.setdefault(key, {"trades": 0, "wins": 0, "total_return": 0.0, "total_pl": 0.0})
        bucket["trades"] += 1
        bucket["wins"] += int(float(trade["net_pl"]) > 0)
        bucket["total_return"] += float(trade["net_return"])
        bucket["total_pl"] += float(trade["net_pl"])
    for bucket in setup_summary.values():
        bucket["win_rate"] = round(bucket["wins"] / bucket["trades"], 4) if bucket["trades"] else None
        bucket["avg_return"] = round(bucket["total_return"] / bucket["trades"], 6) if bucket["trades"] else None
        bucket["avg_pl"] = round(bucket["total_pl"] / bucket["trades"], 2) if bucket["trades"] else None
        bucket.pop("total_return", None)
        bucket.pop("total_pl", None)
    regime_summary: dict[str, dict[str, Any]] = {}
    for trade in trades:
        key = f"{trade.get('regime_trend')}|{trade.get('regime_momentum')}"
        bucket = regime_summary.setdefault(
            key,
            {"trades": 0, "wins": 0, "avg_return": 0.0, "total_return": 0.0},
        )
        bucket["trades"] += 1
        if float(trade["net_pl"]) > 0:
            bucket["wins"] += 1
        bucket["total_return"] += float(trade["net_return"])
    for bucket in regime_summary.values():
        bucket["win_rate"] = round(bucket["wins"] / bucket["trades"], 4) if bucket["trades"] else None
        bucket["avg_return"] = round(bucket["total_return"] / bucket["trades"], 6) if bucket["trades"] else None
        bucket.pop("total_return", None)
    return {
        "symbol": symbol,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "strategy": {
            "name": "technical_long_strong_atr_stop_take",
            "direction": "long",
            "entry_rule": f"direction=long, setup_quality={setup_quality}, score>={min_score}",
            "exit_rule": "stop_loss or take_profit or time_stop",
            "max_holding_days": max_holding_days,
            "allowed_setup_names": sorted(allowed_setup_names) if allowed_setup_names else [],
            "costs": {
                "commission_bps": costs.commission_bps,
                "slippage_bps": costs.slippage_bps,
                "round_trip_bps": costs.round_trip_bps,
            },
        },
        "metrics": metrics,
        "setup_summary": setup_summary,
        "regime_summary": regime_summary,
        "equity_curve": equity_curve,
        "trades": trades,
    }


def _benchmark_report(
    benchmark_symbol: str,
    benchmark_prices: pd.DataFrame,
    trades: list[dict[str, Any]],
    period: dict[str, str],
    strategy_total_return: float | None,
) -> dict[str, Any]:
    benchmark_symbol = benchmark_symbol.upper().strip()
    if benchmark_prices.empty:
        return {
            "symbol": benchmark_symbol,
            "available": False,
            "reason": "benchmark sin datos",
            "metrics": {},
        }

    close = benchmark_prices.dropna(subset=["Close"]).copy()
    if close.empty:
        return {
            "symbol": benchmark_symbol,
            "available": False,
            "reason": "benchmark sin cierres validos",
            "metrics": {},
        }

    start_close = _safe_float(close.iloc[0].get("Close"), default=float("nan"))
    end_close = _safe_float(close.iloc[-1].get("Close"), default=float("nan"))
    total_return = ((end_close / start_close) - 1.0) if start_close and end_close else None

    window_returns: list[float] = []
    beat_count = 0
    for trade in trades:
        entry_price = _price_on_or_after(close, str(trade.get("entry_date") or ""), "Open")
        if not entry_price or pd.isna(entry_price):
            entry_price = _price_on_or_after(close, str(trade.get("entry_date") or ""), "Close")
        exit_price = _price_on_or_after(close, str(trade.get("exit_date") or ""), "Close")
        if not entry_price or not exit_price or pd.isna(entry_price) or pd.isna(exit_price):
            continue
        benchmark_return = (exit_price - entry_price) / entry_price
        window_returns.append(float(benchmark_return))
        if float(trade.get("net_return") or 0.0) > benchmark_return:
            beat_count += 1

    avg_trade_window_return = sum(window_returns) / len(window_returns) if window_returns else None
    trade_window_alpha = None
    if window_returns and trades:
        strategy_avg = sum(float(trade.get("net_return") or 0.0) for trade in trades) / len(trades)
        trade_window_alpha = strategy_avg - avg_trade_window_return

    return {
        "symbol": benchmark_symbol,
        "available": True,
        "period": period,
        "metrics": {
            "benchmark_total_return": round(total_return, 4) if total_return is not None else None,
            "benchmark_avg_trade_window_return": round(avg_trade_window_return, 6)
            if avg_trade_window_return is not None
            else None,
            "trade_windows_compared": len(window_returns),
            "trades_beating_benchmark": beat_count,
            "beat_rate": round(beat_count / len(window_returns), 4) if window_returns else None,
            "alpha_vs_benchmark": round(strategy_total_return - total_return, 4)
            if strategy_total_return is not None and total_return is not None
            else None,
            "trade_window_alpha": round(trade_window_alpha, 6) if trade_window_alpha is not None else None,
        },
    }


def evaluate_backtest_gate(
    report: dict[str, Any],
    *,
    min_trades: int,
    min_hit_rate: float,
    min_profit_factor: float,
    max_drawdown: float,
    min_alpha_vs_benchmark: float | None = None,
    min_trade_window_alpha: float | None = None,
    min_regime_trades: int = 0,
    max_negative_regimes: int | None = None,
) -> dict[str, Any]:
    metrics = report.get("metrics", {}) or {}
    benchmark = ((report.get("benchmark") or {}).get("metrics")) or {}
    trades = int(metrics.get("trades") or 0)
    hit_rate = float(metrics.get("hit_rate") or 0.0)
    profit_factor = metrics.get("profit_factor")
    observed_drawdown = float(metrics.get("max_drawdown") or 0.0)
    if trades < min_trades:
        return {"approved": False, "reason": f"trades {trades} < minimo {min_trades}"}
    if hit_rate < min_hit_rate:
        return {"approved": False, "reason": f"hit-rate {hit_rate:.2%} < minimo {min_hit_rate:.2%}"}
    if profit_factor is None and min_profit_factor > 0:
        return {"approved": False, "reason": f"profit-factor {profit_factor} < minimo {min_profit_factor}"}
    if profit_factor is not None and float(profit_factor) < min_profit_factor:
        return {"approved": False, "reason": f"profit-factor {profit_factor} < minimo {min_profit_factor}"}
    if observed_drawdown < -max_drawdown:
        return {"approved": False, "reason": f"max drawdown {observed_drawdown:.2%} excede {max_drawdown:.2%}"}
    trade_window_alpha = _safe_float(benchmark.get("trade_window_alpha"), default=float("nan"))
    if min_trade_window_alpha is not None and not pd.isna(trade_window_alpha) and trade_window_alpha < min_trade_window_alpha:
        return {
            "approved": False,
            "reason": f"trade-window alpha {trade_window_alpha:.2%} < minimo {min_trade_window_alpha:.2%}",
        }
    alpha_vs_benchmark = _safe_float(benchmark.get("alpha_vs_benchmark"), default=float("nan"))
    trade_window_compared = int(benchmark.get("trade_windows_compared") or 0)
    use_period_alpha_as_guardrail = trade_window_compared <= 0 or pd.isna(trade_window_alpha)
    if (
        use_period_alpha_as_guardrail
        and min_alpha_vs_benchmark is not None
        and not pd.isna(alpha_vs_benchmark)
        and alpha_vs_benchmark < min_alpha_vs_benchmark
    ):
        return {
            "approved": False,
            "reason": f"alpha vs benchmark {alpha_vs_benchmark:.2%} < minimo {min_alpha_vs_benchmark:.2%}",
        }
    if min_regime_trades > 0 and max_negative_regimes is not None:
        negative_regimes = 0
        for bucket in (report.get("regime_summary") or {}).values():
            bucket_trades = int(bucket.get("trades") or 0)
            bucket_avg = _safe_float(bucket.get("avg_return"), default=float("nan"))
            if bucket_trades >= min_regime_trades and not pd.isna(bucket_avg) and bucket_avg < 0:
                negative_regimes += 1
        if negative_regimes > max_negative_regimes:
            return {
                "approved": False,
                "reason": (
                    f"regimenes negativos {negative_regimes} > maximo {max_negative_regimes} "
                    f"con minimo {min_regime_trades} trades"
                ),
            }
    return {"approved": True, "reason": "backtest aprobado"}


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
    benchmark_symbol: str | None = None,
    provider: str | None = None,
    fmp_api_key: str | None = None,
    gate_config: dict[str, Any] | None = None,
    allowed_setup_names: set[str] | None = None,
) -> dict[str, Any]:
    end_value = end or (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    universe = [symbol]
    benchmark_value = (benchmark_symbol or "").upper().strip()
    if benchmark_value and benchmark_value != symbol.upper():
        universe.append(benchmark_value)
    data, market_data_meta = download_daily_prices_with_metadata(
        universe,
        start=start,
        end=end_value,
        provider=provider,
        fmp_api_key=fmp_api_key,
    )
    frame = _symbol_frame(data, symbol.upper())
    report = backtest_technical_long_rule(
        symbol,
        frame,
        min_score=min_score,
        setup_quality=setup_quality,
        max_holding_days=max_holding_days,
        allowed_setup_names=allowed_setup_names,
    )
    report["period"] = {"from": start, "to": end_value}
    if benchmark_value and benchmark_value != symbol.upper():
        try:
            benchmark_frame = _symbol_frame(data, benchmark_value)
        except KeyError:
            benchmark_frame = pd.DataFrame()
        total_return = _safe_float((report.get("metrics") or {}).get("total_return"), default=float("nan"))
        report["benchmark"] = _benchmark_report(
            benchmark_value,
            benchmark_frame,
            report.get("trades", []),
            report["period"],
            None if pd.isna(total_return) else total_return,
        )
    elif benchmark_value:
        report["benchmark"] = {
            "symbol": benchmark_value,
            "available": False,
            "reason": "benchmark coincide con simbolo principal",
            "metrics": {},
        }
    report["backtest_context"] = {
        "universe": [item.upper() for item in universe],
        "window": {"from": start, "to": end_value},
        "benchmark_symbol": benchmark_value or None,
        "data_source": market_data_meta.get("source"),
        "market_data": market_data_meta,
        "walk_forward": {"enabled": False, "status": "not_run"},
    }
    if gate_config:
        report["validation"] = {
            "gate": {
                **gate_config,
                **evaluate_backtest_gate(
                    report,
                    min_trades=int(gate_config.get("min_trades") or 0),
                    min_hit_rate=float(gate_config.get("min_hit_rate") or 0.0),
                    min_profit_factor=float(gate_config.get("min_profit_factor") or 0.0),
                    max_drawdown=float(gate_config.get("max_drawdown") or 0.0),
                    min_alpha_vs_benchmark=_safe_float(gate_config.get("min_alpha_vs_benchmark"), default=float("nan"))
                    if gate_config.get("min_alpha_vs_benchmark") is not None
                    else None,
                    min_trade_window_alpha=_safe_float(gate_config.get("min_trade_window_alpha"), default=float("nan"))
                    if gate_config.get("min_trade_window_alpha") is not None
                    else None,
                    min_regime_trades=int(gate_config.get("min_regime_trades") or 0),
                    max_negative_regimes=int(gate_config.get("max_negative_regimes"))
                    if gate_config.get("max_negative_regimes") is not None
                    else None,
                ),
            }
        }
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"backtest_{symbol.upper()}_{run_id}.json"
    report["path"] = str(path)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    return report
