"""Reusable portfolio insight helpers for UI surfaces and operators."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from .market_data import download_daily_prices_with_metadata


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _short(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def news_report_files(reports_dir: Path) -> list[Path]:
    return sorted(
        [
            path
            for path in reports_dir.glob("news_sentiment_*.json")
            if not path.name.endswith(".manifest.json") and not path.name.startswith("latest_")
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def _news_sort_key(row: dict[str, Any]) -> tuple[str, str, str]:
    published_at = str(row.get("published_at") or "")
    analyzed_at = str(row.get("analyzed_at") or "")
    title = str(row.get("title") or "")
    return (published_at or analyzed_at, analyzed_at, title)


def latest_analyzed_news(reports_dir: Path, limit: int = 20) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for path in news_report_files(reports_dir):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        analyzed_at = str(report.get("as_of") or "")
        run_id = str(report.get("run_id") or "")
        for result in report.get("results", []) or []:
            if not isinstance(result, dict):
                continue
            symbol = str(result.get("symbol") or "").upper().strip()
            sentiment = result.get("sentiment") if isinstance(result.get("sentiment"), dict) else {}
            material_risk = result.get("material_risk") if isinstance(result.get("material_risk"), dict) else {}
            for item in result.get("news", []) or []:
                if not isinstance(item, dict):
                    continue
                title = _short(item.get("title"), 180)
                link = str(item.get("link") or "").strip()
                key = (symbol, title, link)
                if not title or key in seen:
                    continue
                seen.add(key)
                rows.append(
                    {
                        "analyzed_at": analyzed_at,
                        "published_at": item.get("published_at"),
                        "scope": "accion" if symbol else "mercado",
                        "symbol": symbol or "MERCADO",
                        "title": title,
                        "publisher": item.get("publisher") or "-",
                        "sentiment": sentiment.get("sentiment") or "-",
                        "sentiment_score": sentiment.get("sentiment_score"),
                        "material_risk": material_risk.get("severity")
                        or ("material" if material_risk.get("material") else "none"),
                        "summary": _short(item.get("summary"), 220),
                        "link": link,
                        "run_id": run_id,
                    }
                )
    rows.sort(key=_news_sort_key, reverse=True)
    return rows[: max(1, int(limit))]


def position_first_buy_time(history: dict[str, Any], symbol: str) -> str | None:
    target = str(symbol or "").upper()
    buy_times = [
        str(trade.get("time") or "")
        for trade in history.get("trades", [])
        if str(trade.get("symbol") or "").upper() == target and str(trade.get("side") or "").lower() == "buy"
    ]
    return min((item for item in buy_times if item), default=None)


def position_entry_date(history: dict[str, Any], symbol: str) -> str | None:
    target = str(symbol or "").upper()
    risk = (history.get("risk_levels", {}) or {}).get(target, {}) or {}
    return str(risk.get("source_order_time") or position_first_buy_time(history, target) or "")[:10] or None


def position_chart_start_date(
    history: dict[str, Any],
    symbol: str,
    *,
    pre_entry_days: int = 7,
    local_timezone: str = "Europe/Madrid",
) -> str:
    entry_date = position_entry_date(history, symbol)
    if entry_date:
        try:
            return (datetime.fromisoformat(entry_date).date() - timedelta(days=pre_entry_days)).isoformat()
        except ValueError:
            pass
    return (datetime.now(ZoneInfo(local_timezone)).date() - timedelta(days=30)).isoformat()


def single_symbol_price_frame(data: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame(columns=["fecha", "close", "volume"])
    target = str(symbol or "").upper()
    if isinstance(data.columns, pd.MultiIndex):
        if target not in data.columns.get_level_values(0):
            return pd.DataFrame(columns=["fecha", "close", "volume"])
        frame = data[target].copy()
    else:
        frame = data.copy()
    if "Close" not in frame.columns:
        return pd.DataFrame(columns=["fecha", "close", "volume"])
    result = frame.reset_index().rename(columns={"index": "fecha", "Date": "fecha", "date": "fecha"})
    result["fecha"] = pd.to_datetime(result["fecha"], errors="coerce").dt.date.astype("string")
    result["close"] = pd.to_numeric(result["Close"], errors="coerce")
    if "Volume" in result:
        result["volume"] = pd.to_numeric(result["Volume"], errors="coerce")
    else:
        result["volume"] = pd.NA
    return result.dropna(subset=["fecha", "close"])[["fecha", "close", "volume"]].reset_index(drop=True)


def position_price_series(
    settings: Any,
    symbol: str,
    history: dict[str, Any],
    *,
    current_price: float | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    local_timezone = str(getattr(settings, "local_timezone", "Europe/Madrid") or "Europe/Madrid")
    start = position_chart_start_date(history, symbol, local_timezone=local_timezone)
    end = (datetime.now(ZoneInfo(local_timezone)).date() + timedelta(days=1)).isoformat()
    data, meta = download_daily_prices_with_metadata(
        [symbol],
        start,
        end,
        cache_dir=settings.data_dir / "cache" / "market_data",
        provider=settings.market_data_provider,
        fmp_api_key=settings.fmp_api_key,
    )
    frame = single_symbol_price_frame(data, symbol)
    today = datetime.now(ZoneInfo(local_timezone)).date().isoformat()
    if current_price is not None and (frame.empty or str(frame.iloc[-1].get("fecha")) < today):
        frame = pd.concat(
            [
                frame,
                pd.DataFrame([{"fecha": today, "close": round(float(current_price), 4), "volume": pd.NA}]),
            ],
            ignore_index=True,
        ).drop_duplicates(subset=["fecha"], keep="last")
    return frame.sort_values("fecha").reset_index(drop=True), meta


def position_evolution_summary(
    price_df: pd.DataFrame,
    *,
    entry_price: float | None,
    stop_loss: float | None,
    take_profit: float | None,
) -> dict[str, Any]:
    if price_df.empty:
        return {
            "bars": 0,
            "last_price": None,
            "return_from_entry": None,
            "distance_to_stop": None,
            "distance_to_take": None,
        }
    last_price = _num(price_df.iloc[-1].get("close"))
    first_price = _num(price_df.iloc[0].get("close"))
    basis = entry_price or first_price
    return {
        "bars": int(len(price_df)),
        "last_price": last_price,
        "return_from_entry": round((last_price - basis) / basis, 6) if last_price is not None and basis else None,
        "distance_to_stop": round((last_price - stop_loss) / last_price, 6)
        if last_price is not None and stop_loss
        else None,
        "distance_to_take": round((take_profit - last_price) / last_price, 6)
        if last_price is not None and take_profit
        else None,
    }
