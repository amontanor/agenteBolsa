"""Build compact market snapshots for LLM agents."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .market_data import download_daily_prices
from .technical_analysis import add_basic_technical_features


def _symbol_frame(data: pd.DataFrame, symbol: str, multi_symbol: bool) -> pd.DataFrame:
    if multi_symbol:
        frame = data[symbol].copy()
    else:
        frame = data.copy()
    return frame.dropna(how="all")


def _latest_number(row: pd.Series, key: str) -> float | None:
    value = row.get(key)
    if pd.isna(value):
        return None
    return round(float(value), 4)


def build_market_snapshot(
    symbols: list[str],
    benchmark_symbol: str,
    output_dir: Path,
    cycle_id: str,
    lookback_days: int = 420,
    *,
    provider: str | None = None,
    fmp_api_key: str | None = None,
) -> dict[str, Any]:
    end = datetime.now(timezone.utc).date() + timedelta(days=1)
    start = end - timedelta(days=lookback_days)
    unique_symbols = sorted(set(symbols + [benchmark_symbol]))
    data = download_daily_prices(
        unique_symbols,
        start=start.isoformat(),
        end=end.isoformat(),
        provider=provider,
        fmp_api_key=fmp_api_key,
    )

    multi_symbol = isinstance(data.columns, pd.MultiIndex)
    snapshot: dict[str, Any] = {
        "as_of": date.today().isoformat(),
        "benchmark": benchmark_symbol,
        "provider": provider or "default",
        "symbols": {},
        "warnings": [],
    }

    # Iterar sobre unique_symbols (candidatos + benchmark): el benchmark se
    # descarga en la linea de arriba pero antes NO se anadia a snapshot["symbols"]
    # si no estaba en el universo de candidatos -> el market_state quedaba sin
    # benchmark (regime="unknown", benchmark_return_20d=0) y forzaba modo defensivo.
    for symbol in unique_symbols:
        try:
            frame = _symbol_frame(data, symbol, multi_symbol)
            if frame.empty:
                snapshot["warnings"].append(f"{symbol}: sin datos descargados")
                continue
            features = add_basic_technical_features(frame)
            latest = features.dropna(subset=["Close"]).iloc[-1]
            snapshot["symbols"][symbol] = {
                "last_date": str(features.dropna(subset=["Close"]).index[-1].date()),
                "close": _latest_number(latest, "Close"),
                "return_20d": _latest_number(latest, "return_20d"),
                "sma_20": _latest_number(latest, "sma_20"),
                "sma_50": _latest_number(latest, "sma_50"),
                "sma_200": _latest_number(latest, "sma_200"),
                "volume_zscore_20": _latest_number(latest, "volume_zscore_20"),
                "atr_14": _latest_number(latest, "atr_14"),
                "trend_positive": bool(latest.get("trend_positive", False)),
                "above_long_trend": bool(latest.get("above_long_trend", False)),
            }
        except Exception as exc:  # noqa: BLE001 - snapshot should continue per symbol.
            snapshot["warnings"].append(f"{symbol}: {exc}")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"market_snapshot_{cycle_id}.json"
    output_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=True), encoding="utf-8")
    snapshot["path"] = str(output_path)
    return snapshot


def compact_snapshot_for_prompt(snapshot: dict[str, Any], max_chars: int = 6000) -> str:
    text = json.dumps(snapshot, indent=2, ensure_ascii=True)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 200] + "\n...TRUNCATED..."
