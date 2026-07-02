"""Read-only shadow observations for SPY exposure overlays."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from agente_bolsa.config import get_settings
from agente_bolsa.tools.strategy_edge_backtest import (
    DEFAULT_OVERLAY_VOL_LOOKBACK,
    _normalize_download_frame,
    download_prices_read_only,
    exposure_regime_on_off,
    exposure_vol_target,
)

DEFAULT_OVERLAY_SHADOW_START = "2020-01-01"
DEFAULT_OUTPUT_DIR = Path("data/research/overlay_shadow")


def build_overlay_shadow_observation(spy_close: pd.Series, *, as_of: date | None = None) -> dict[str, Any]:
    close = pd.to_numeric(spy_close, errors="coerce").dropna().sort_index()
    if close.empty:
        raise ValueError("SPY no tiene cierres validos para overlay shadow.")
    latest_ts = pd.Timestamp(close.index.max())
    if as_of is not None:
        eligible = close.loc[: str(as_of)]
        if eligible.empty:
            raise ValueError(f"SPY no tiene cierres hasta {as_of}.")
        close = eligible
        latest_ts = pd.Timestamp(close.index.max())

    realized = close.pct_change().rolling(DEFAULT_OVERLAY_VOL_LOOKBACK).std() * (252**0.5)
    vt10 = exposure_vol_target(close, target_vol=0.10)
    vt12 = exposure_vol_target(close, target_vol=0.12)
    sma200 = exposure_regime_on_off(close, sma_window=200)
    latest = latest_ts
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "data_date": str(latest.date()),
        "symbol": "SPY",
        "source": "yfinance",
        "price": _round_or_none(close.loc[latest]),
        "realized_vol_lookback_days": DEFAULT_OVERLAY_VOL_LOOKBACK,
        "realized_vol_annualized": _round_or_none(realized.loc[latest]),
        "target_exposures": {
            "vol_target_10pct": _round_or_none(vt10.loc[latest]),
            "vol_target_12pct": _round_or_none(vt12.loc[latest]),
            "regime_sma200": _round_or_none(sma200.loc[latest]),
        },
        "method": {
            "vol_target": "target_vol / realized_vol_20d_annualized, clipped 0..1, identical to exposure_vol_target.",
            "regime_sma200": "1.0 if SPY close >= SMA200 else 0.0, identical to exposure_regime_on_off.",
        },
    }


def run_overlay_shadow_once(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    start: str = DEFAULT_OVERLAY_SHADOW_START,
    end: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    end = end or date.today().isoformat()
    prices, meta = download_prices_read_only(
        ["SPY"],
        start=start,
        end=end,
        provider="yfinance",
        fmp_api_key=None,
        batch_size=1,
    )
    frame = _normalize_download_frame(prices, "SPY")
    if frame.empty or "Close" not in frame.columns:
        raise ValueError("SPY no disponible para overlay shadow.")
    close = pd.to_numeric(frame["Close"], errors="coerce").dropna().sort_index()
    observation = build_overlay_shadow_observation(close)
    observation["download"] = meta
    return persist_overlay_shadow_observation(observation, output_dir=settings.data_dir / "research" / "overlay_shadow" if output_dir == DEFAULT_OUTPUT_DIR else output_dir)


def persist_overlay_shadow_observation(observation: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    data_date = str(observation["data_date"])
    daily_path = output_dir / f"overlay_shadow_{data_date}.json"
    log_path = output_dir / "overlay_shadow_log.jsonl"
    daily_path.write_text(json.dumps(observation, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(observation, ensure_ascii=False, default=str) + "\n")
    return {"ok": True, "path": str(daily_path), "log_path": str(log_path), "observation": observation}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Calcula overlay shadow SPY read-only.")
    parser.add_argument("--start", default=DEFAULT_OVERLAY_SHADOW_START)
    parser.add_argument("--to", dest="end", default=date.today().isoformat())
    parser.add_argument("--out-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = run_overlay_shadow_once(output_dir=Path(args.out_dir), start=args.start, end=args.end)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        obs = result["observation"]
        print(
            "Overlay shadow SPY "
            f"date={obs['data_date']} vt12={obs['target_exposures']['vol_target_12pct']} "
            f"path={result['path']}"
        )
    return 0


def _round_or_none(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
