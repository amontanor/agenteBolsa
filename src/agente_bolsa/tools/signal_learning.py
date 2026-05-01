"""Persistent signal learning and outcome attribution."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from agente_bolsa.config import Settings
from agente_bolsa.models import TradeRecommendation
from agente_bolsa.storage import Store

from .market_data import download_daily_prices


HORIZONS = (1, 3, 5, 10)


def _num(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _date(value: Any) -> str:
    text = str(value or "")
    if "T" in text:
        return text[:10]
    return text[:10] if text else datetime.now(timezone.utc).date().isoformat()


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value.upper()).strip("_")


def _chart_pattern_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    technical_state = candidate.get("technical_state", {}) or {}
    patterns = technical_state.get("chart_patterns", []) or candidate.get("chart_patterns", []) or []
    confirmed = [item for item in patterns if item.get("status") == "confirmed"]
    bullish = [item for item in confirmed if item.get("bias") == "bullish"]
    bearish = [item for item in confirmed if item.get("bias") == "bearish"]
    return {
        "confirmed_count": len(confirmed),
        "bullish_confirmed_count": len(bullish),
        "bearish_confirmed_count": len(bearish),
        "labels": [str(item.get("label") or item.get("pattern")) for item in confirmed[:5]],
    }


def _signal_features(candidate: dict[str, Any]) -> dict[str, Any]:
    technical_state = candidate.get("technical_state", {}) or {}
    risk = candidate.get("risk_plan", {}) or {}
    close = _num(technical_state.get("close"))
    sma20 = _num(technical_state.get("sma_20"))
    sma200 = _num(technical_state.get("sma_200"))
    macd = _num(technical_state.get("macd"))
    macd_signal = _num(technical_state.get("macd_signal"))
    return {
        "direction": candidate.get("direction"),
        "score": candidate.get("score"),
        "setup_quality": candidate.get("setup_quality"),
        "last_date": _date(candidate.get("last_date")),
        "close": close,
        "entry_price": _num(risk.get("entry_price"), close),
        "stop_loss": _num(risk.get("stop_loss")),
        "take_profit": _num(risk.get("take_profit")),
        "return_5d": _num(technical_state.get("return_5d")),
        "return_20d": _num(technical_state.get("return_20d")),
        "return_60d": _num(technical_state.get("return_60d")),
        "rsi_14": _num(technical_state.get("rsi_14")),
        "macd_diff": (macd - macd_signal) if macd is not None and macd_signal is not None else None,
        "volume_zscore_20": _num(technical_state.get("volume_zscore_20")),
        "bollinger_pct_b_20": _num(technical_state.get("bollinger_pct_b_20")),
        "distance_sma20": ((close - sma20) / sma20) if close and sma20 else None,
        "distance_sma200": ((close - sma200) / sma200) if close and sma200 else None,
        "chart_patterns": _chart_pattern_summary(candidate),
        "reasons": candidate.get("reasons", [])[:8],
    }


def record_signal_candidates(store: Store, report: dict[str, Any], *, source: str) -> int:
    source_run_id = str(report.get("run_id") or "")
    if not source_run_id:
        return 0
    count = 0
    for candidate in report.get("all_candidates", []) or []:
        symbol = str(candidate.get("symbol", "")).upper()
        if not symbol:
            continue
        features = _signal_features(candidate)
        signal_date = _date(features.get("last_date"))
        signal_id = f"{source_run_id}:{_slug(symbol)}"
        store.save_signal_outcome(
            signal_id=signal_id,
            source_run_id=source_run_id,
            source=source,
            symbol=symbol,
            signal_date=signal_date,
            decision="candidate",
            features=features,
            gate={},
            outcome={},
        )
        count += 1
    return count


def _gate_by_symbol(items: list[dict[str, Any]], name: str) -> dict[str, dict[str, Any]]:
    result = {}
    for item in items or []:
        result[str(item.get("symbol", "")).upper()] = {
            name: {
                "approved": item.get("approved"),
                "reason": item.get("reason"),
                "checks": item.get("checks") or item.get("metrics") or {},
            }
        }
    return result


def update_signal_decisions(
    store: Store,
    *,
    source_run_id: str | None,
    recommendations: list[TradeRecommendation],
    entry_quality_gate: list[dict[str, Any]],
    backtest_gate: list[dict[str, Any]],
) -> int:
    if not source_run_id:
        return 0
    gate_by_symbol = defaultdict(dict)
    for symbol, gate in _gate_by_symbol(entry_quality_gate, "entry_quality_gate").items():
        gate_by_symbol[symbol].update(gate)
    for symbol, gate in _gate_by_symbol(backtest_gate, "backtest_gate").items():
        gate_by_symbol[symbol].update(gate)

    updated = 0
    for recommendation in recommendations:
        symbol = recommendation.symbol.upper()
        decision = recommendation.action
        gate = dict(gate_by_symbol.get(symbol, {}))
        if recommendation.action == "buy":
            entry_gate = gate.get("entry_quality_gate")
            backtest = gate.get("backtest_gate")
            if entry_gate and not entry_gate.get("approved"):
                decision = "blocked_entry_quality"
            elif backtest and not backtest.get("approved"):
                decision = "blocked_backtest"
            else:
                decision = "approved_buy"
        store.update_signal_decision(
            source_run_id=source_run_id,
            symbol=symbol,
            decision=decision,
            gate={
                **gate,
                "llm": {
                    "action": recommendation.action,
                    "confidence": recommendation.confidence,
                    "reason": recommendation.reason,
                },
            },
        )
        updated += 1
    return updated


def _symbol_frame(data: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if isinstance(data.columns, pd.MultiIndex):
        return data[symbol].copy().dropna(how="all")
    return data.copy().dropna(how="all")


def _bar_date(index: Any) -> str:
    if hasattr(index, "date"):
        return str(index.date())
    return str(index)[:10]


def _outcome_for_signal(signal: dict[str, Any], frame: pd.DataFrame) -> dict[str, Any]:
    features = signal.get("features", {}) or {}
    entry = _num(features.get("entry_price") or features.get("close"))
    stop = _num(features.get("stop_loss"))
    take = _num(features.get("take_profit"))
    if not entry:
        return {"available": False, "reason": "sin entry_price"}

    signal_date = signal["signal_date"]
    future = frame.loc[frame.index.map(_bar_date) > signal_date].copy()
    if future.empty:
        return {"available": False, "reason": "sin barras posteriores"}

    closes = [_num(value) for value in future["Close"].tolist()]
    highs = [_num(value) for value in future["High"].tolist()]
    lows = [_num(value) for value in future["Low"].tolist()]
    dates = [_bar_date(index) for index in future.index]
    returns = {}
    for horizon in HORIZONS:
        if len(closes) >= horizon and closes[horizon - 1] is not None:
            returns[f"return_{horizon}d"] = round((closes[horizon - 1] - entry) / entry, 4)
        else:
            returns[f"return_{horizon}d"] = None

    window_highs = [value for value in highs[:10] if value is not None]
    window_lows = [value for value in lows[:10] if value is not None]
    first_hit = None
    for index, (date, high, low) in enumerate(zip(dates[:10], highs[:10], lows[:10]), start=1):
        if low is not None and stop is not None and low <= stop:
            first_hit = {"type": "stop_loss", "date": date, "days": index}
            break
        if high is not None and take is not None and high >= take:
            first_hit = {"type": "take_profit", "date": date, "days": index}
            break

    outcome = {
        "available": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        **returns,
        "mfe_10d": round((max(window_highs) - entry) / entry, 4) if window_highs else None,
        "mae_10d": round((min(window_lows) - entry) / entry, 4) if window_lows else None,
        "first_hit": first_hit,
    }
    outcome["verdict"] = _verdict(outcome)
    return outcome


def _verdict(outcome: dict[str, Any]) -> str:
    first_hit = outcome.get("first_hit") or {}
    if first_hit.get("type") == "take_profit":
        return "winner_take_profit"
    if first_hit.get("type") == "stop_loss":
        return "loser_stop_loss"
    ret_5d = outcome.get("return_5d")
    ret_10d = outcome.get("return_10d")
    ref = ret_10d if ret_10d is not None else ret_5d
    if ref is None:
        return "pending"
    if ref > 0.01:
        return "winner_open"
    if ref < -0.01:
        return "loser_open"
    return "flat"


def update_signal_outcomes(
    settings: Settings,
    store: Store,
    *,
    limit: int = 1000,
    since_date: str = "2026-04-01",
) -> dict[str, Any]:
    signals = store.signal_outcomes(limit=limit, since_date=since_date)
    symbols = sorted({signal["symbol"] for signal in signals})
    if not signals or not symbols:
        return {"updated": 0, "signals": 0, "symbols": 0, "warnings": []}
    start = min(signal["signal_date"] for signal in signals)
    end = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    warnings = []
    try:
        data = download_daily_prices(symbols, start=start, end=end)
    except Exception as exc:  # noqa: BLE001
        return {"updated": 0, "signals": len(signals), "symbols": len(symbols), "warnings": [str(exc)]}

    updated = 0
    for signal in signals:
        try:
            frame = _symbol_frame(data, signal["symbol"]).dropna(how="all")
            if frame.empty:
                continue
            outcome = _outcome_for_signal(signal, frame)
            store.update_signal_outcome(signal["signal_id"], outcome)
            updated += 1
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{signal['symbol']}: {exc}")
    return {"updated": updated, "signals": len(signals), "symbols": len(symbols), "warnings": warnings[:20]}


def _bucket(value: Any, buckets: list[tuple[str, float, float]]) -> str:
    number = _num(value)
    if number is None:
        return "unknown"
    for label, low, high in buckets:
        if low <= number < high:
            return label
    return buckets[-1][0]


def _indicator_tags(signal: dict[str, Any]) -> list[str]:
    features = signal.get("features", {}) or {}
    chart = features.get("chart_patterns", {}) or {}
    tags = [
        f"score:{_bucket(features.get('score'), [('lt12', -999, 12), ('12_14', 12, 15), ('gte15', 15, 999)])}",
        f"rsi:{_bucket(features.get('rsi_14'), [('lt60', -999, 60), ('60_75', 60, 75), ('75_85', 75, 85), ('gt85', 85, 999)])}",
        f"sma20_dist:{_bucket(features.get('distance_sma20'), [('lt0', -999, 0), ('0_6pct', 0, 0.06), ('6_12pct', 0.06, 0.12), ('gt12pct', 0.12, 999)])}",
        f"macd:{'positive' if _num(features.get('macd_diff'), 0) and _num(features.get('macd_diff'), 0) > 0 else 'non_positive'}",
        f"volume_z:{_bucket(features.get('volume_zscore_20'), [('lt0', -999, 0), ('0_1', 0, 1), ('gt1', 1, 999)])}",
        f"chart_confirmed:{'yes' if chart.get('bullish_confirmed_count', 0) else 'no'}",
    ]
    return tags


def build_learning_status(store: Store, *, since_date: str = "2026-04-01", limit: int = 1000) -> dict[str, Any]:
    signals = store.signal_outcomes(limit=limit, since_date=since_date)
    by_tag: dict[str, list[dict[str, Any]]] = defaultdict(list)
    verdicts = Counter()
    decisions = Counter()
    for signal in signals:
        decisions[signal["decision"]] += 1
        verdict = (signal.get("outcome") or {}).get("verdict", "pending")
        verdicts[verdict] += 1
        for tag in _indicator_tags(signal):
            by_tag[tag].append(signal)

    indicator_stats = []
    for tag, items in by_tag.items():
        resolved = [item for item in items if (item.get("outcome") or {}).get("verdict") not in {None, "pending"}]
        winners = [
            item
            for item in resolved
            if str((item.get("outcome") or {}).get("verdict", "")).startswith("winner")
        ]
        avg_5d_values = [
            _num((item.get("outcome") or {}).get("return_5d"))
            for item in resolved
            if _num((item.get("outcome") or {}).get("return_5d")) is not None
        ]
        indicator_stats.append(
            {
                "tag": tag,
                "signals": len(items),
                "resolved": len(resolved),
                "win_rate": round(len(winners) / len(resolved), 4) if resolved else None,
                "avg_return_5d": round(sum(avg_5d_values) / len(avg_5d_values), 4) if avg_5d_values else None,
            }
        )
    indicator_stats.sort(
        key=lambda item: (
            item["resolved"],
            item["win_rate"] if item["win_rate"] is not None else -1,
            item["avg_return_5d"] if item["avg_return_5d"] is not None else -1,
        ),
        reverse=True,
    )
    return {
        "since_date": since_date,
        "signals": len(signals),
        "decisions": dict(decisions),
        "verdicts": dict(verdicts),
        "best_indicators": indicator_stats[:10],
        "worst_indicators": sorted(
            [item for item in indicator_stats if item["resolved"]],
            key=lambda item: (
                item["win_rate"] if item["win_rate"] is not None else 1,
                item["avg_return_5d"] if item["avg_return_5d"] is not None else 1,
            ),
        )[:10],
    }


def write_learning_report(report: dict[str, Any], reports_dir: Path, run_id: str) -> dict[str, Any]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"signal_learning_{run_id}.json"
    latest_path = reports_dir / "latest_signal_learning.json"
    report["path"] = str(path)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    latest_path.write_text(json.dumps(report, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    return report
