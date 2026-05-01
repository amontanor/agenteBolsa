"""Breakout scanner with conservative risk classification."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .market_data import download_daily_prices
from .technical_analysis import add_basic_technical_features


def merge_breakout_universe(symbols: list[str], extras: list[str] | None = None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for symbol in [*symbols, *(extras or [])]:
        normalized = str(symbol or "").strip().upper()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _symbol_frame(data: pd.DataFrame, symbol: str, multi_symbol: bool) -> pd.DataFrame:
    if multi_symbol:
        if symbol not in data.columns.get_level_values(0):
            return pd.DataFrame()
        return data[symbol].copy().dropna(how="all")
    return data.copy().dropna(how="all")


def _num(value: Any, precision: int = 4) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), precision)


def _safe_pct(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def classify_breakout(symbol: str, features: pd.DataFrame) -> dict[str, Any] | None:
    """Return a breakout alert for the latest bar, or None if nothing relevant is near."""

    if len(features) < 60:
        return None

    latest = features.iloc[-1]
    previous = features.iloc[:-1]
    close = float(latest["Close"])
    high = float(latest["High"])
    low = float(latest["Low"])
    volume = float(latest.get("Volume") or 0)
    prev_high_20 = _num(previous["High"].rolling(20).max().iloc[-1])
    prev_high_55 = _num(previous["High"].rolling(55).max().iloc[-1])
    resistance_candidates = [value for value in [prev_high_20, prev_high_55] if value and value > 0]
    if not resistance_candidates:
        return None

    resistance = max(resistance_candidates)
    distance_to_resistance = (close / resistance) - 1
    intraday_breakout = (high / resistance) - 1
    volume_z = _num(latest.get("volume_zscore_20"), 2)
    atr = _num(latest.get("atr_14"))
    sma20 = _num(latest.get("sma_20"))
    rsi = _num(latest.get("rsi_14"), 2)
    return_20d = _num(latest.get("return_20d"), 4)
    sma20_distance = _safe_pct(close - sma20, sma20) if sma20 else None
    atr_pct = _safe_pct(atr, close)

    status = ""
    reasons: list[str] = []
    if close >= resistance * 1.003:
        status = "confirmed_breakout"
        reasons.append("cierre por encima de resistencia 20/55 sesiones")
    elif high >= resistance * 1.003 and close < resistance:
        status = "failed_breakout"
        reasons.append("rompio resistencia intradia pero no cerro por encima")
    elif -0.02 <= distance_to_resistance < 0.003:
        status = "watch_breakout"
        reasons.append("precio a menos de 2% de resistencia relevante")
    else:
        return None

    if volume_z is not None and volume_z >= 1.0:
        reasons.append("volumen confirma ruptura")
    elif status == "confirmed_breakout":
        reasons.append("ruptura sin confirmacion suficiente de volumen")

    too_extended = bool(
        (sma20_distance is not None and sma20_distance > 0.12)
        or distance_to_resistance > 0.06
        or (rsi is not None and rsi > 88)
    )
    if too_extended:
        reasons.append("precio extendido: no perseguir sin retesteo")
    if atr_pct is not None and atr_pct > 0.08:
        reasons.append("ATR elevado: riesgo de stop amplio")

    stop_loss = None
    take_profit = None
    reward_risk = None
    risk_level = "watch"
    tradable = False
    entry_style = "vigilar"

    if status == "confirmed_breakout":
        atr_stop = close - (1.5 * atr) if atr else close * 0.94
        level_stop = resistance * 0.985
        stop_loss = min(close * 0.98, max(atr_stop, level_stop))
        risk_per_share = close - stop_loss
        if risk_per_share > 0:
            take_profit = close + (2.0 * risk_per_share)
            reward_risk = 2.0
        risk_pct = _safe_pct(risk_per_share, close)
        if too_extended or (volume_z is not None and volume_z < 1.0) or (risk_pct is not None and risk_pct > 0.06):
            risk_level = "high"
            entry_style = "esperar retesteo; no perseguir vela vertical"
        else:
            risk_level = "moderate"
            tradable = True
            entry_style = "entrada solo si mantiene cierre sobre resistencia"
    elif status == "watch_breakout":
        risk_level = "watch"
        entry_style = "esperar ruptura confirmada con volumen"
    else:
        risk_level = "blocked"
        entry_style = "descartar hasta nuevo cierre sobre resistencia"

    return {
        "symbol": symbol,
        "date": str(features.index[-1].date()) if hasattr(features.index[-1], "date") else str(features.index[-1]),
        "status": status,
        "tradable": tradable,
        "risk_level": risk_level,
        "entry_style": entry_style,
        "close": _num(close),
        "high": _num(high),
        "low": _num(low),
        "volume": int(volume),
        "resistance": _num(resistance),
        "prev_high_20": prev_high_20,
        "prev_high_55": prev_high_55,
        "breakout_pct": _num(distance_to_resistance, 4),
        "intraday_breakout_pct": _num(intraday_breakout, 4),
        "volume_zscore_20": volume_z,
        "rsi_14": rsi,
        "return_20d": return_20d,
        "sma20_distance": _num(sma20_distance, 4),
        "atr_14": atr,
        "atr_pct": _num(atr_pct, 4),
        "stop_loss": _num(stop_loss),
        "take_profit": _num(take_profit),
        "reward_risk": reward_risk,
        "reasons": reasons,
    }


def build_breakout_scan(
    symbols: list[str],
    output_dir: Path,
    run_id: str,
    lookback_days: int = 420,
) -> dict[str, Any]:
    end = datetime.now(timezone.utc).date() + timedelta(days=1)
    start = end - timedelta(days=lookback_days)
    data = download_daily_prices(symbols, start=start.isoformat(), end=end.isoformat())
    multi_symbol = isinstance(data.columns, pd.MultiIndex)

    alerts: list[dict[str, Any]] = []
    warnings: list[str] = []
    with_data = 0
    for symbol in symbols:
        try:
            frame = _symbol_frame(data, symbol, multi_symbol)
            if frame.empty:
                warnings.append(f"{symbol}: sin datos")
                continue
            with_data += 1
            features = add_basic_technical_features(frame)
            alert = classify_breakout(symbol, features)
            if alert:
                alerts.append(alert)
        except Exception as exc:  # noqa: BLE001 - one symbol must not block the scan.
            warnings.append(f"{symbol}: {exc}")

    priority = {"confirmed_breakout": 0, "watch_breakout": 1, "failed_breakout": 2}
    alerts = sorted(
        alerts,
        key=lambda item: (
            priority.get(str(item.get("status")), 9),
            0 if item.get("tradable") else 1,
            -(float(item.get("volume_zscore_20") or -99)),
            str(item.get("symbol") or ""),
        ),
    )
    report = {
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "symbols_scanned": len(symbols),
        "symbols_with_data": with_data,
        "alerts": alerts,
        "confirmed": [item for item in alerts if item["status"] == "confirmed_breakout"],
        "watch": [item for item in alerts if item["status"] == "watch_breakout"],
        "blocked_or_failed": [item for item in alerts if item["status"] == "failed_breakout" or item["risk_level"] in {"high", "blocked"}],
        "warnings": warnings[:100],
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"breakout_scan_{run_id}.json"
    latest_path = output_dir / "latest_breakout_scan.json"
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    latest_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    report["path"] = str(output_path)
    report["latest_path"] = str(latest_path)
    return report
