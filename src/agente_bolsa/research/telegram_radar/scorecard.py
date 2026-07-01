"""Honest forward-return scorecard for Telegram radar mentions."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from agente_bolsa.config import Settings
from agente_bolsa.tools.market_data import download_daily_prices_with_metadata

from .models import TelegramScorecardRow

PriceLoader = Callable[[list[str], str, str], pd.DataFrame]
DEFAULT_HORIZONS = (5, 10, 20)
DEFAULT_COST_BPS = (10.0, 20.0, 30.0)


def build_scorecard(
    posts: list[dict[str, Any]],
    extractions: list[dict[str, Any]],
    *,
    settings: Settings,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    cost_bps_values: tuple[float, ...] = DEFAULT_COST_BPS,
    price_loader: PriceLoader | None = None,
) -> dict[str, Any]:
    rows = calculate_scorecard_rows(
        posts,
        extractions,
        settings=settings,
        horizons=horizons,
        cost_bps_values=cost_bps_values,
        price_loader=price_loader,
    )
    return {
        "rows": [row.to_dict() for row in rows],
        "summary": summarize_scorecard([row.to_dict() for row in rows]),
    }


def calculate_scorecard_rows(
    posts: list[dict[str, Any]],
    extractions: list[dict[str, Any]],
    *,
    settings: Settings,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    cost_bps_values: tuple[float, ...] = DEFAULT_COST_BPS,
    price_loader: PriceLoader | None = None,
) -> list[TelegramScorecardRow]:
    post_by_id = {int(item["message_id"]): item for item in posts}
    mentions = _mentions(post_by_id, extractions)
    if not mentions:
        return []
    symbols = sorted({mention["ticker"] for mention in mentions} | {settings.benchmark_symbol})
    start, end = _price_window(mentions)
    try:
        prices = _load_prices(symbols, start, end, settings, price_loader)
    except Exception:
        prices = pd.DataFrame()

    rows: list[TelegramScorecardRow] = []
    for mention in mentions:
        for horizon in horizons:
            for cost_bps in cost_bps_values:
                rows.append(_score_mention(mention, horizon, cost_bps, prices, settings.benchmark_symbol))
    return rows


def summarize_scorecard(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, int, float], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        coverage = "in_universe" if row.get("in_universe") else "out_of_coverage"
        groups[(coverage, int(row["horizon_days"]), float(row["cost_bps"]))].append(row)
    summary_rows = []
    for (coverage, horizon, cost_bps), items in sorted(groups.items()):
        scored = [item for item in items if item.get("status") == "scored"]
        wins = [item for item in scored if (item.get("signal_return_net") or 0.0) > 0]
        excess_values = [float(item["excess_vs_spy"]) for item in scored if item.get("excess_vs_spy") is not None]
        signal_values = [float(item["signal_return_net"]) for item in scored if item.get("signal_return_net") is not None]
        summary_rows.append(
            {
                "coverage": coverage,
                "horizon_days": horizon,
                "cost_bps": cost_bps,
                "n_mentions": len(items),
                "n_scored": len(scored),
                "n_no_data": len(items) - len(scored),
                "hit_rate": round(len(wins) / len(scored), 4) if scored else None,
                "avg_signal_return_net": _mean(signal_values),
                "avg_excess_vs_spy": _mean(excess_values),
            }
        )
    return {"groups": summary_rows}


def _mentions(post_by_id: dict[int, dict[str, Any]], extractions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for extraction in extractions:
        post = post_by_id.get(int(extraction["message_id"]))
        if not post:
            continue
        direction = str(extraction.get("direction") or "none").lower()
        if direction not in {"buy", "watch", "sell"}:
            continue
        coverage_by_ticker = {
            str(item.get("ticker") or "").upper(): item
            for item in extraction.get("ticker_coverage", []) or []
            if item.get("ticker")
        }
        for ticker in sorted({str(item).upper() for item in extraction.get("tickers", []) if str(item).strip()}):
            coverage = coverage_by_ticker.get(ticker, {})
            result.append(
                {
                    "message_id": int(extraction["message_id"]),
                    "posted_at": post.get("posted_at"),
                    "ticker": ticker,
                    "direction": direction,
                    "in_universe": bool(coverage.get("in_universe")),
                    "out_of_coverage": bool(coverage.get("out_of_coverage", not coverage.get("in_universe"))),
                }
            )
    return result


def _score_mention(
    mention: dict[str, Any],
    horizon: int,
    cost_bps: float,
    prices: pd.DataFrame,
    benchmark_symbol: str,
) -> TelegramScorecardRow:
    direction = str(mention["direction"])
    side = -1.0 if direction == "sell" else 1.0
    ticker_prices = _close_series(prices, str(mention["ticker"]))
    spy_prices = _close_series(prices, benchmark_symbol)
    posted_date = _date_text(mention.get("posted_at"))
    if posted_date is None:
        return _empty_row(mention, horizon, cost_bps, "posted_at_invalido")
    ticker_window = _forward_window(ticker_prices, posted_date, horizon)
    spy_window = _forward_window(spy_prices, posted_date, horizon)
    if ticker_window is None:
        return _empty_row(mention, horizon, cost_bps, "sin_datos_forward")
    if spy_window is None:
        return _empty_row(mention, horizon, cost_bps, "sin_spy_forward")
    entry_date, exit_date, entry_price, exit_price = ticker_window
    _spy_entry_date, _spy_exit_date, spy_entry, spy_exit = spy_window
    ticker_return = (exit_price / entry_price) - 1.0
    spy_return = (spy_exit / spy_entry) - 1.0
    cost = float(cost_bps) / 10_000.0
    signal_return_net = side * ticker_return - cost
    benchmark_signal = side * spy_return
    excess = signal_return_net - benchmark_signal
    beta_adjusted = _beta_adjusted_return(ticker_prices, spy_prices, posted_date, side, signal_return_net, spy_return)
    return TelegramScorecardRow(
        message_id=int(mention["message_id"]),
        ticker=str(mention["ticker"]).upper(),
        posted_at=mention.get("posted_at"),
        direction=direction,
        horizon_days=int(horizon),
        cost_bps=float(cost_bps),
        in_universe=bool(mention.get("in_universe")),
        out_of_coverage=bool(mention.get("out_of_coverage")),
        status="scored",
        entry_date=entry_date,
        exit_date=exit_date,
        ticker_return=round(ticker_return, 6),
        spy_return=round(spy_return, 6),
        signal_return_net=round(signal_return_net, 6),
        excess_vs_spy=round(excess, 6),
        beta_adjusted_return=round(beta_adjusted, 6) if beta_adjusted is not None else None,
    )


def _empty_row(mention: dict[str, Any], horizon: int, cost_bps: float, status: str) -> TelegramScorecardRow:
    return TelegramScorecardRow(
        message_id=int(mention["message_id"]),
        ticker=str(mention["ticker"]).upper(),
        posted_at=mention.get("posted_at"),
        direction=str(mention["direction"]),
        horizon_days=int(horizon),
        cost_bps=float(cost_bps),
        in_universe=bool(mention.get("in_universe")),
        out_of_coverage=bool(mention.get("out_of_coverage")),
        status=status,
        entry_date=None,
        exit_date=None,
        ticker_return=None,
        spy_return=None,
        signal_return_net=None,
        excess_vs_spy=None,
        beta_adjusted_return=None,
    )


def _forward_window(series: pd.Series, posted_date: str, horizon: int) -> tuple[str, str, float, float] | None:
    clean = pd.to_numeric(series, errors="coerce").dropna().sort_index()
    if clean.empty:
        return None
    clean.index = pd.to_datetime(clean.index).tz_localize(None)
    after_post = clean[clean.index > pd.Timestamp(posted_date)]
    if len(after_post) <= horizon:
        return None
    entry = after_post.iloc[0]
    exit_ = after_post.iloc[horizon]
    return (
        after_post.index[0].date().isoformat(),
        after_post.index[horizon].date().isoformat(),
        float(entry),
        float(exit_),
    )


def _beta_adjusted_return(
    ticker_prices: pd.Series,
    spy_prices: pd.Series,
    posted_date: str,
    side: float,
    signal_return_net: float,
    spy_forward_return: float,
) -> float | None:
    ticker_returns = pd.to_numeric(ticker_prices, errors="coerce").pct_change()
    spy_returns = pd.to_numeric(spy_prices, errors="coerce").pct_change()
    aligned = pd.concat({"ticker": ticker_returns, "spy": spy_returns}, axis=1).dropna()
    aligned.index = pd.to_datetime(aligned.index).tz_localize(None)
    history = aligned[aligned.index <= pd.Timestamp(posted_date)].tail(60)
    if len(history) < 20:
        return None
    variance = float(history["spy"].var())
    if variance == 0.0:
        return None
    beta = float(history["ticker"].cov(history["spy"]) / variance)
    return signal_return_net - beta * (side * spy_forward_return)


def _load_prices(
    symbols: list[str],
    start: str,
    end: str,
    settings: Settings,
    price_loader: PriceLoader | None,
) -> pd.DataFrame:
    if price_loader:
        return price_loader(symbols, start, end)
    frame, _meta = download_daily_prices_with_metadata(
        symbols,
        start,
        end,
        cache_dir=Path(settings.data_dir) / "cache" / "market_data",
        provider=settings.market_data_provider,
        fmp_api_key=settings.fmp_api_key,
    )
    return frame


def _price_window(mentions: list[dict[str, Any]]) -> tuple[str, str]:
    dates = [_date_text(item.get("posted_at")) for item in mentions]
    valid = [datetime.fromisoformat(item) for item in dates if item]
    start = min(valid) - timedelta(days=90)
    end = max(valid) + timedelta(days=45)
    return start.date().isoformat(), end.date().isoformat()


def _close_series(data: pd.DataFrame, symbol: str) -> pd.Series:
    if data.empty:
        return pd.Series(dtype=float)
    if isinstance(data.columns, pd.MultiIndex):
        if symbol in data.columns.get_level_values(0):
            frame = data[symbol]
        elif symbol in data.columns.get_level_values(-1):
            frame = data.xs(symbol, axis=1, level=-1)
        else:
            return pd.Series(dtype=float)
        if "Close" in frame.columns:
            return frame["Close"].copy()
        return pd.Series(dtype=float)
    if "Close" in data.columns:
        return data["Close"].copy()
    if symbol in data.columns:
        return data[symbol].copy()
    return pd.Series(dtype=float)


def _date_text(value: Any) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.date().isoformat()
    except ValueError:
        return None


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)
