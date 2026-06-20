"""Unified market state built once per cycle."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from agente_bolsa.config import Settings

from .market_data import download_daily_prices_with_metadata
from .retention import latest_report_path
from .technical_analysis import add_basic_technical_features
from .trade_decision import load_latest_sentiment

SECTOR_ETFS = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY", "XLC"]
PROMPT_VERSION = "market_state.v2"


def _latest_close_features(frame: pd.DataFrame) -> pd.Series | None:
    prepared = add_basic_technical_features(frame.copy())
    rows = prepared.dropna(subset=["Close"])
    if rows.empty:
        return None
    return rows.iloc[-1]


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _quality_status(*, coverage_ratio: float, sector_count: int, has_earnings: bool, has_macro: bool) -> str:
    if coverage_ratio < 0.5:
        return "INSUFFICIENT"
    if coverage_ratio < 0.8 or sector_count < 5 or not has_earnings or not has_macro:
        return "PARTIAL"
    return "GOOD"


def _formal_provider(settings: Settings, provider: str | None) -> bool:
    provider_name = str(provider or settings.market_data_provider or "auto").lower()
    return provider_name == "fmp" or (provider_name == "auto" and bool(settings.fmp_api_key))


def _benchmark_regime(benchmark: dict[str, Any], breadth: dict[str, Any]) -> str:
    close = _float(benchmark.get("close"))
    sma_50 = _float(benchmark.get("sma_50"))
    sma_200 = _float(benchmark.get("sma_200"))
    breadth_ratio = float(breadth.get("trend_positive_ratio") or 0.0)
    if close is None or sma_50 is None or sma_200 is None:
        return "unknown"
    if close > sma_50 > sma_200 and breadth_ratio >= 0.55:
        return "bullish"
    if close < sma_50 < sma_200 and breadth_ratio <= 0.45:
        return "bearish"
    return "neutral"


def _volatility_regime(benchmark: dict[str, Any]) -> str:
    close = _float(benchmark.get("close"))
    atr = _float(benchmark.get("atr_14"))
    if close is None or close <= 0 or atr is None:
        return "unknown"
    atr_pct = atr / close
    if atr_pct >= 0.035:
        return "high"
    if atr_pct <= 0.015:
        return "low"
    return "normal"


def _market_regime_policy(
    settings: Settings,
    *,
    market_regime: str,
    volatility_regime: str,
    quality_status: str,
) -> dict[str, Any]:
    if not settings.market_regime_policy_enabled:
        return {
            "enabled": False,
            "profile": "policy_disabled",
            "allow_new_buys": True,
            "requires_micro_experiment": False,
            "size_multiplier": 1.0,
            "backtest_soft_override_allowed": bool(settings.backtest_gate_paper_soft_override_enabled),
        }
    if quality_status == "INSUFFICIENT":
        return {
            "enabled": True,
            "profile": "insufficient_data",
            "allow_new_buys": False,
            "requires_micro_experiment": False,
            "size_multiplier": 0.0,
            "backtest_soft_override_allowed": False,
            "reason": "market_state_data_quality_insufficient",
        }
    if volatility_regime == "high":
        return {
            "enabled": True,
            "profile": "high_volatility",
            "allow_new_buys": True,
            "requires_micro_experiment": True,
            "size_multiplier": min(0.5, float(settings.micro_experiment_size_multiplier)),
            "backtest_soft_override_allowed": False,
            "reason": "high_volatility_regime",
        }
    if market_regime == "bearish":
        return {
            "enabled": True,
            "profile": "bearish",
            "allow_new_buys": settings.trading_mode == "paper",
            "requires_micro_experiment": True,
            "size_multiplier": min(0.5, float(settings.micro_experiment_size_multiplier)),
            "backtest_soft_override_allowed": False,
            "reason": "bearish_market_regime",
        }
    if market_regime == "bullish" and quality_status == "GOOD":
        return {
            "enabled": True,
            "profile": "bullish",
            "allow_new_buys": True,
            "requires_micro_experiment": False,
            "size_multiplier": 1.0,
            "backtest_soft_override_allowed": bool(settings.backtest_gate_paper_soft_override_enabled),
            "reason": "constructive_market_regime",
        }
    return {
        "enabled": True,
        "profile": "neutral",
        "allow_new_buys": True,
        "requires_micro_experiment": quality_status == "PARTIAL",
        "size_multiplier": min(0.75, float(settings.micro_experiment_size_multiplier) if quality_status == "PARTIAL" else 1.0),
        "backtest_soft_override_allowed": quality_status == "GOOD" and bool(settings.backtest_gate_paper_soft_override_enabled),
        "reason": "neutral_or_partial_market_regime",
    }


def _risk_posture(policy: dict[str, Any]) -> str:
    if not policy.get("allow_new_buys"):
        return "halt_new_buys"
    profile = str(policy.get("profile") or "")
    if profile in {"bearish", "high_volatility", "insufficient_data"}:
        return "defensive"
    if policy.get("requires_micro_experiment"):
        return "defensive"
    if profile == "bullish":
        return "risk_on"
    return "balanced"


def _breadth(snapshot: dict[str, Any]) -> dict[str, Any]:
    rows = list((snapshot.get("symbols") or {}).values())
    count = len(rows)
    if not count:
        return {"symbols": 0, "trend_positive_ratio": 0.0, "above_long_trend_ratio": 0.0}
    trend_positive = sum(1 for row in rows if bool(row.get("trend_positive")))
    above_long_trend = sum(1 for row in rows if bool(row.get("above_long_trend")))
    return {
        "symbols": count,
        "trend_positive_ratio": round(trend_positive / count, 4),
        "above_long_trend_ratio": round(above_long_trend / count, 4),
    }


def _relative_strength(snapshot: dict[str, Any]) -> dict[str, Any]:
    benchmark_symbol = str(snapshot.get("benchmark") or "")
    benchmark_return = _float(((snapshot.get("symbols") or {}).get(benchmark_symbol) or {}).get("return_20d")) or 0.0
    rows: list[dict[str, Any]] = []
    for symbol, data in (snapshot.get("symbols") or {}).items():
        return_20d = _float(data.get("return_20d"))
        if return_20d is None:
            continue
        rows.append(
            {
                "symbol": symbol,
                "return_20d": return_20d,
                "relative_to_benchmark_20d": round(return_20d - benchmark_return, 4),
            }
        )
    leaders = sorted(rows, key=lambda item: item["relative_to_benchmark_20d"], reverse=True)[:5]
    laggards = sorted(rows, key=lambda item: item["relative_to_benchmark_20d"])[:5]
    return {
        "benchmark_return_20d": benchmark_return,
        "leaders": leaders,
        "laggards": laggards,
    }


def _sector_leadership(settings: Settings) -> tuple[dict[str, Any], list[str]]:
    end = datetime.now(timezone.utc).date() + timedelta(days=1)
    start = end - timedelta(days=60)
    warnings: list[str] = []
    try:
        data, meta = download_daily_prices_with_metadata(
            SECTOR_ETFS,
            start=start.isoformat(),
            end=end.isoformat(),
            provider=settings.market_data_provider,
            fmp_api_key=settings.fmp_api_key,
        )
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "leaders": [], "laggards": [], "coverage_ratio": 0.0}, [f"sector_data: {exc}"]

    leaders: list[dict[str, Any]] = []
    for symbol in meta.get("symbols_with_data", []):
        frame = data[symbol].copy() if isinstance(data.columns, pd.MultiIndex) else data.copy()
        frame = frame.dropna(how="all")
        latest = _latest_close_features(frame)
        if latest is None:
            warnings.append(f"sector:{symbol}: sin features")
            continue
        leaders.append(
            {
                "symbol": symbol,
                "return_20d": _float(latest.get("return_20d")),
                "trend_positive": bool(latest.get("trend_positive", False)),
            }
        )
    sorted_rows = [item for item in leaders if item.get("return_20d") is not None]
    sorted_rows.sort(key=lambda item: float(item["return_20d"]), reverse=True)
    return {
        "available": True,
        "leaders": sorted_rows[:3],
        "laggards": sorted_rows[-3:],
        "coverage_ratio": float(meta.get("coverage_ratio") or 0.0),
    }, warnings


def _earnings_calendar_summary(settings: Settings) -> dict[str, Any]:
    path = latest_report_path(settings.data_dir, "pre_earnings", "latest_pre_earnings.json")
    if path is None:
        return {"available": False, "source": None, "event_count": 0}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"available": False, "source": str(path), "event_count": 0}
    summary = payload.get("summary", {}) or {}
    return {
        "available": True,
        "source": str(path),
        "event_count": int(summary.get("total_events") or payload.get("events_found") or 0),
        "pending_count": int(summary.get("pending_count") or 0),
        "resolved_count": int(summary.get("resolved_count") or 0),
    }


def _macro_calendar_summary() -> dict[str, Any]:
    return {
        "available": False,
        "source": None,
        "summary": "Sin fuente macro estructurada en esta fase.",
    }


def _sentiment_summary(settings: Settings, sentiment_context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = sentiment_context if isinstance(sentiment_context, dict) and sentiment_context else load_latest_sentiment(settings.data_dir)
    rows = list(context.get("results", []) or [])
    scores = []
    supportive = 0
    material_risk = 0
    for item in rows:
        sentiment = item.get("sentiment", {}) or {}
        score = _float(sentiment.get("sentiment_score"))
        if score is not None:
            scores.append(score)
        if sentiment.get("supports_technical_setup") is True:
            supportive += 1
        if item.get("material_risk"):
            material_risk += 1
    avg_score = round(sum(scores) / len(scores), 4) if scores else None
    return {
        "available": bool(rows),
        "source": context.get("path"),
        "symbols_analyzed": len(rows),
        "average_score": avg_score,
        "supportive_count": supportive,
        "material_risk_count": material_risk,
    }


def _sentiment_decay_summary(settings: Settings, sentiment_context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = sentiment_context if isinstance(sentiment_context, dict) and sentiment_context else load_latest_sentiment(settings.data_dir)
    rows = list(context.get("results", []) or [])
    by_symbol: dict[str, dict[str, Any]] = {}
    scores = []
    material_risk_symbols = []
    for item in rows:
        symbol = str(item.get("symbol") or "").upper()
        sentiment = item.get("sentiment", {}) or {}
        score = _float(sentiment.get("sentiment_score"))
        if not symbol or score is None:
            continue
        material_risk = bool(item.get("material_risk"))
        scores.append(score)
        if material_risk:
            material_risk_symbols.append(symbol)
        by_symbol[symbol] = {
            "decayed_score": score,
            "material_risk": material_risk,
            "source": "latest_sentiment_report",
        }
    return {
        "available": len(scores) >= 2,
        "source": context.get("path"),
        "method": "latest_sentiment_equal_weight_v1",
        "market_score": round(sum(scores) / len(scores), 4) if scores else None,
        "symbols": by_symbol,
        "material_risk_symbols": sorted(set(material_risk_symbols)),
        "warning": None if len(scores) >= 2 else "sentiment_window_insufficient",
    }


def _macro_event_risk(macro: dict[str, Any]) -> dict[str, Any]:
    if not macro.get("available"):
        return {"level": "unknown", "available": False, "reason": "macro_calendar_unavailable"}
    severity = str(macro.get("severity") or macro.get("level") or "normal").lower()
    if severity in {"high", "critical"}:
        return {"level": "high", "available": True, "reason": "high_severity_macro_event"}
    return {"level": "normal", "available": True, "reason": "macro_calendar_available"}


def _data_vendor_quality(
    settings: Settings,
    *,
    provider: str | None,
    coverage_ratio: float,
    warnings: list[str],
) -> dict[str, Any]:
    formal = _formal_provider(settings, provider)
    degraded_symbols = sorted(
        {
            str(item).split(":", 1)[0].strip().upper()
            for item in warnings
            if ":" in str(item) and str(item).split(":", 1)[0].strip()
        }
    )
    severity = "OK"
    if coverage_ratio < 0.5:
        severity = "BLOCK"
    elif not formal or coverage_ratio < 0.95 or warnings:
        severity = "WARN"
    return {
        "provider_used": provider or settings.market_data_provider,
        "provider_configured": settings.market_data_provider,
        "formal_provider": formal,
        "coverage_ratio": coverage_ratio,
        "degraded_symbols": degraded_symbols,
        "warnings_count": len(warnings),
        "severity": severity,
    }


def compact_market_state_for_prompt(state: dict[str, Any], max_chars: int = 3000) -> str:
    text = json.dumps(state, ensure_ascii=True, indent=2)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 200] + "\n...TRUNCATED..."


def load_latest_market_state(output_dir: Path) -> dict[str, Any] | None:
    candidates = sorted(output_dir.glob("market_state_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            payload["path"] = str(path)
            return payload
    return None


def build_market_state(
    settings: Settings,
    output_dir: Path,
    run_id: str,
    *,
    market_snapshot: dict[str, Any] | None = None,
    sentiment_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = market_snapshot or {"symbols": {}, "benchmark": settings.benchmark_symbol, "provider": settings.market_data_provider, "warnings": []}
    breadth = _breadth(snapshot)
    benchmark = (snapshot.get("symbols") or {}).get(settings.benchmark_symbol) or {}
    relative_strength = _relative_strength(snapshot)
    sector_leadership, sector_warnings = _sector_leadership(settings)
    earnings = _earnings_calendar_summary(settings)
    macro = _macro_calendar_summary()
    sentiment = _sentiment_summary(settings, sentiment_context)
    warnings = list(snapshot.get("warnings", []) or []) + sector_warnings
    provider = snapshot.get("provider") or settings.market_data_provider
    coverage_ratio = 0.0
    symbols = snapshot.get("symbols") or {}
    if settings.universe:
        coverage_ratio = round(len(symbols) / max(len(settings.universe), 1), 4)
    quality_status = _quality_status(
        coverage_ratio=coverage_ratio,
        sector_count=len(list(sector_leadership.get("leaders") or [])) + len(list(sector_leadership.get("laggards") or [])),
        has_earnings=bool(earnings.get("available")),
        has_macro=bool(macro.get("available")),
    )
    quality_notes = []
    if not earnings.get("available"):
        quality_notes.append("earnings_summary_missing")
    if not macro.get("available"):
        quality_notes.append("macro_summary_missing")
    if sector_warnings:
        quality_notes.append("sector_data_partial")
    data_vendor_quality = _data_vendor_quality(
        settings,
        provider=provider,
        coverage_ratio=coverage_ratio,
        warnings=warnings,
    )
    if not data_vendor_quality.get("formal_provider"):
        quality_notes.append("informal_market_data_provider")
    market_regime = _benchmark_regime(benchmark, breadth)
    volatility_regime = _volatility_regime(benchmark)
    regime_policy = _market_regime_policy(
        settings,
        market_regime=market_regime,
        volatility_regime=volatility_regime,
        quality_status=quality_status,
    )
    sentiment_decay = _sentiment_decay_summary(settings, sentiment_context)
    macro_event_risk = _macro_event_risk(macro)
    state = {
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "benchmark": settings.benchmark_symbol,
        "prompt_version": PROMPT_VERSION,
        "market_regime": market_regime,
        "breadth": breadth,
        "volatility_regime": volatility_regime,
        "risk_posture": _risk_posture(regime_policy),
        "market_regime_policy": regime_policy,
        "relative_strength": relative_strength,
        "sector_leadership": sector_leadership,
        "earnings_calendar_summary": earnings,
        "macro_calendar_summary": macro,
        "macro_event_risk": macro_event_risk,
        "sentiment_summary": sentiment,
        "sentiment_decay_summary": sentiment_decay,
        "data_quality": {
            "status": quality_status,
            "coverage_ratio": coverage_ratio,
            "data_vendor_quality": data_vendor_quality,
            "notes": quality_notes,
        },
        "warnings": warnings[:20],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"market_state_{run_id}.json"
    output_path.write_text(json.dumps(state, ensure_ascii=True, indent=2), encoding="utf-8")
    state["path"] = str(output_path)
    return state
