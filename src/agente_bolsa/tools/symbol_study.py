"""Full single-symbol study helpers."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from agente_bolsa.config import Settings

from .market_data import download_daily_prices
from .news_sentiment import analyze_news_sentiment_for_candidates, fetch_symbol_news
from .technical_analysis import add_basic_technical_features
from .technical_state_validator import validate_symbol_technical_state


def _symbol_frame(data: pd.DataFrame, symbol: str, multi_symbol: bool) -> pd.DataFrame:
    if multi_symbol:
        return data[symbol].copy().dropna(how="all")
    return data.copy().dropna(how="all")


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def _latest_bar(frame: pd.DataFrame) -> dict[str, Any]:
    latest = frame.dropna(subset=["Close"]).iloc[-1]
    return {
        "date": str(latest.name.date()) if hasattr(latest.name, "date") else str(latest.name),
        "open": _safe_float(latest.get("Open")),
        "high": _safe_float(latest.get("High")),
        "low": _safe_float(latest.get("Low")),
        "close": _safe_float(latest.get("Close")),
        "volume": _safe_float(latest.get("Volume")),
    }


def _recent_bars(features: pd.DataFrame, count: int = 10) -> list[dict[str, Any]]:
    rows = []
    columns = [
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
        "return_5d",
        "return_20d",
        "sma_20",
        "sma_50",
        "sma_200",
        "rsi_14",
        "atr_14",
        "volume_zscore_20",
    ]
    for index, row in features.dropna(subset=["Close"]).tail(count).iterrows():
        rows.append(
            {
                "date": str(index.date()) if hasattr(index, "date") else str(index),
                **{key.lower(): _safe_float(row.get(key)) for key in columns},
            }
        )
    return rows


def _relative_strength(features: pd.DataFrame, benchmark_features: pd.DataFrame) -> dict[str, Any]:
    symbol = features.dropna(subset=["Close"]).copy()
    benchmark = benchmark_features.dropna(subset=["Close"]).copy()
    joined = symbol[["Close"]].join(benchmark[["Close"]], how="inner", lsuffix="_symbol", rsuffix="_benchmark")
    if len(joined) < 61:
        return {"available": False, "reason": "historial insuficiente contra benchmark"}
    result: dict[str, Any] = {"available": True}
    for window in (20, 60):
        symbol_return = joined["Close_symbol"].pct_change(window).iloc[-1]
        benchmark_return = joined["Close_benchmark"].pct_change(window).iloc[-1]
        result[f"symbol_return_{window}d"] = _safe_float(symbol_return)
        result[f"benchmark_return_{window}d"] = _safe_float(benchmark_return)
        result[f"relative_return_{window}d"] = _safe_float(symbol_return - benchmark_return)
    return result


def _fundamental_snapshot(symbol: str) -> dict[str, Any]:
    try:
        import yfinance as yf
    except ImportError:
        return {"available": False, "error": "yfinance no esta instalado"}

    try:
        ticker = yf.Ticker(symbol)
        fast_info = dict(getattr(ticker, "fast_info", {}) or {})
        info = dict(getattr(ticker, "info", {}) or {})
    except Exception as exc:  # noqa: BLE001 - fundamentals are optional context.
        return {"available": False, "error": str(exc)}

    keys = [
        "sector",
        "industry",
        "marketCap",
        "trailingPE",
        "forwardPE",
        "priceToBook",
        "beta",
        "dividendYield",
        "profitMargins",
        "revenueGrowth",
        "earningsGrowth",
        "recommendationKey",
        "targetMeanPrice",
        "fiftyTwoWeekHigh",
        "fiftyTwoWeekLow",
    ]
    payload = {key: info.get(key) for key in keys if info.get(key) is not None}
    payload.update(
        {
            "last_price": fast_info.get("last_price"),
            "market_cap_fast": fast_info.get("market_cap") or fast_info.get("marketCap"),
            "year_high": fast_info.get("year_high"),
            "year_low": fast_info.get("year_low"),
        }
    )
    return {"available": True, **{key: value for key, value in payload.items() if value is not None}}


def build_symbol_study(
    symbol: str,
    settings: Settings,
    output_dir: Path,
    run_id: str,
    *,
    lookback_days: int = 420,
    include_news: bool = False,
    include_news_llm: bool = False,
    news_items: int = 5,
) -> dict[str, Any]:
    """Build and persist a complete study for one symbol.

    The study is deterministic except optional yfinance fundamentals/news and
    optional LLM news validation.
    """

    symbol = symbol.upper().strip()
    benchmark = settings.benchmark_symbol.upper().strip()
    end = datetime.now(timezone.utc).date() + timedelta(days=1)
    start = end - timedelta(days=lookback_days)
    symbols = sorted({symbol, benchmark})
    data = download_daily_prices(symbols, start=start.isoformat(), end=end.isoformat())
    multi_symbol = isinstance(data.columns, pd.MultiIndex)

    frame = _symbol_frame(data, symbol, multi_symbol)
    if frame.empty:
        raise ValueError(f"{symbol}: sin datos descargados")
    features = add_basic_technical_features(frame)
    technical = validate_symbol_technical_state(symbol, features)

    benchmark_context: dict[str, Any] = {"symbol": benchmark}
    if benchmark != symbol:
        benchmark_frame = _symbol_frame(data, benchmark, multi_symbol)
        if not benchmark_frame.empty:
            benchmark_features = add_basic_technical_features(benchmark_frame)
            benchmark_context.update(
                {
                    "latest_bar": _latest_bar(benchmark_frame),
                    "relative_strength": _relative_strength(features, benchmark_features),
                }
            )

    news_context: dict[str, Any] = {"enabled": include_news, "items": []}
    if include_news:
        news_context["items"] = fetch_symbol_news(symbol, max_items=news_items)
    if include_news_llm:
        sentiment_report = analyze_news_sentiment_for_candidates(
            settings,
            [technical],
            output_dir,
            f"{run_id}_{symbol.lower()}",
            max_news_items=news_items,
        )
        news_context["llm_sentiment"] = sentiment_report["results"][0] if sentiment_report["results"] else None
        news_context["llm_sentiment_path"] = sentiment_report["path"]

    report = {
        "run_id": run_id,
        "symbol": symbol,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "lookback_days": lookback_days,
        "benchmark": benchmark_context,
        "latest_bar": _latest_bar(frame),
        "technical": technical,
        "fundamentals": _fundamental_snapshot(symbol),
        "news": news_context,
        "recent_bars": _recent_bars(features),
        "summary": {
            "direction": technical.get("direction"),
            "score": technical.get("score"),
            "setup_quality": technical.get("setup_quality"),
            "reasons": technical.get("reasons", [])[:6],
            "risk_plan": technical.get("risk_plan"),
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"symbol_study_{symbol}_{run_id}.json"
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    report["path"] = str(output_path)
    return report
