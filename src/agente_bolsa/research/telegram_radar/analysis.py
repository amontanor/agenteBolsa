"""Read-only gate analysis for Telegram radar mentions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from agente_bolsa.config import Settings
from agente_bolsa.models import TradeRecommendation
from agente_bolsa.tools.market_data import download_daily_prices_with_metadata
from agente_bolsa.tools.technical_analysis import add_basic_technical_features
from agente_bolsa.tools.trade_decision import filter_entry_quality

from .models import TelegramGateVerdict

PriceLoader = Callable[[list[str], str, str], pd.DataFrame]


def build_gate_verdicts(
    posts: list[dict[str, Any]],
    extractions: list[dict[str, Any]],
    *,
    settings: Settings,
    price_loader: PriceLoader | None = None,
) -> list[dict[str, Any]]:
    post_by_id = {int(item["message_id"]): item for item in posts}
    rows: list[dict[str, Any]] = []
    for extraction in extractions:
        if not extraction.get("is_opportunity"):
            continue
        post = post_by_id.get(int(extraction["message_id"]))
        if not post:
            continue
        for coverage in extraction.get("ticker_coverage", []) or []:
            if not coverage.get("in_universe"):
                continue
            ticker = str(coverage.get("ticker") or "").upper().strip()
            if ticker:
                rows.append(
                    analyze_ticker_gate(
                        post,
                        extraction,
                        ticker,
                        settings=settings,
                        price_loader=price_loader,
                    ).to_dict()
                )
    return rows


def analyze_ticker_gate(
    post: dict[str, Any],
    extraction: dict[str, Any],
    ticker: str,
    *,
    settings: Settings,
    price_loader: PriceLoader | None = None,
) -> TelegramGateVerdict:
    posted_at = post.get("posted_at")
    direction = str(extraction.get("direction") or "none").lower()
    reasons: list[str] = []
    metrics: dict[str, Any] = {
        "confidence": _round(_to_float(extraction.get("confidence")), 4),
        "direction": direction,
    }
    if direction not in {"buy", "watch"}:
        return TelegramGateVerdict(
            message_id=int(post["message_id"]),
            ticker=ticker.upper(),
            posted_at=posted_at,
            direction=direction,
            our_gate="fail",
            reasons=["direccion_no_larga_para_entry_quality"],
            metrics=metrics,
        )

    as_of = _date_text(posted_at)
    if as_of is None:
        return TelegramGateVerdict(
            message_id=int(post["message_id"]),
            ticker=ticker.upper(),
            posted_at=posted_at,
            direction=direction,
            our_gate="fail",
            reasons=["posted_at_invalido"],
            metrics=metrics,
        )

    try:
        frame = _load_price_frame([ticker.upper(), settings.benchmark_symbol], as_of, settings, price_loader)
        ticker_features = _features_until(frame, ticker.upper(), as_of)
        spy_features = _features_until(frame, settings.benchmark_symbol, as_of)
    except Exception as exc:
        return TelegramGateVerdict(
            message_id=int(post["message_id"]),
            ticker=ticker.upper(),
            posted_at=posted_at,
            direction=direction,
            our_gate="fail",
            reasons=[f"datos_tecnicos_no_disponibles:{exc}"],
            metrics=metrics,
        )

    metrics.update(_gate_metrics(ticker_features, spy_features))
    recommendation = _recommendation_from_metrics(ticker.upper(), direction, extraction, metrics)
    technical_context = {"all_candidates": [_candidate_from_metrics(ticker.upper(), metrics)]}
    _kept, decisions = filter_entry_quality(settings, [recommendation], technical_context, {})
    decision = decisions[0] if decisions else {"approved": False, "reason": "entry_quality_sin_decision", "checks": {}}
    checks = decision.get("checks") or {}
    metrics["entry_quality_reason"] = decision.get("reason")
    metrics["entry_quality_checks"] = _compact_checks(checks)

    if not metrics.get("spy_regime_bull"):
        reasons.append("regimen_spy_bajista_o_indisponible")
    if metrics.get("sma20_extension") is None:
        reasons.append("extension_sma20_indisponible")
    elif float(metrics["sma20_extension"]) > float(settings.entry_quality_max_sma20_distance):
        reasons.append("extension_sma20_excesiva")
    if metrics.get("rsi_14") is None:
        reasons.append("rsi_indisponible")
    elif float(metrics["rsi_14"]) > float(settings.entry_quality_max_rsi):
        reasons.append("rsi_excesivo")
    if metrics.get("reward_risk") is None:
        reasons.append("reward_risk_indisponible")
    elif float(metrics["reward_risk"]) < float(settings.entry_score_v2_min_reward_risk):
        reasons.append("reward_risk_bajo")
    if metrics.get("confidence") is None:
        reasons.append("confidence_indisponible")
    elif float(metrics["confidence"]) < float(settings.min_llm_confidence_to_trade):
        reasons.append("confidence_baja")
    if not bool(decision.get("approved")):
        reasons.append(f"entry_quality:{decision.get('reason')}")

    clean_reasons = sorted(dict.fromkeys(str(item) for item in reasons if item))
    return TelegramGateVerdict(
        message_id=int(post["message_id"]),
        ticker=ticker.upper(),
        posted_at=posted_at,
        direction=direction,
        our_gate="pass" if not clean_reasons else "fail",
        reasons=clean_reasons,
        metrics=metrics,
    )


def _load_price_frame(
    symbols: list[str],
    as_of: str,
    settings: Settings,
    price_loader: PriceLoader | None,
) -> pd.DataFrame:
    end = (datetime.fromisoformat(as_of) + timedelta(days=1)).date().isoformat()
    start = (datetime.fromisoformat(as_of) - timedelta(days=360)).date().isoformat()
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


def _features_until(frame: pd.DataFrame, symbol: str, as_of: str) -> dict[str, Any]:
    symbol_frame = _symbol_frame(frame, symbol)
    if symbol_frame.empty:
        raise ValueError(f"{symbol}: sin precios")
    symbol_frame = symbol_frame.sort_index()
    symbol_frame.index = pd.to_datetime(symbol_frame.index).tz_localize(None)
    cutoff = pd.Timestamp(as_of)
    historical = symbol_frame[symbol_frame.index <= cutoff]
    if historical.empty:
        raise ValueError(f"{symbol}: sin barras hasta {as_of}")
    features = add_basic_technical_features(historical)
    latest = features.iloc[-1]
    return {key: _to_float(latest.get(key)) for key in features.columns}


def _gate_metrics(ticker_features: dict[str, Any], spy_features: dict[str, Any]) -> dict[str, Any]:
    close = _to_float(ticker_features.get("Close"))
    sma20 = _to_float(ticker_features.get("sma_20"))
    low20 = _to_float(ticker_features.get("low_20"))
    high20 = _to_float(ticker_features.get("high_20"))
    atr = _to_float(ticker_features.get("atr_14"))
    stop = min(low20, close - atr) if close is not None and low20 is not None and atr is not None else None
    take = high20 if high20 is not None and close is not None and high20 > close else None
    reward_risk = None
    if close is not None and stop is not None and take is not None and close > stop:
        reward_risk = (take - close) / (close - stop)
    spy_close = _to_float(spy_features.get("Close"))
    spy_sma200 = _to_float(spy_features.get("sma_200"))
    return {
        "close": _round(close, 4),
        "sma_20": _round(sma20, 4),
        "sma20_extension": _round((close - sma20) / sma20, 4) if close is not None and sma20 else None,
        "rsi_14": _round(_to_float(ticker_features.get("rsi_14")), 2),
        "reward_risk": _round(reward_risk, 4),
        "return_20d": _round(_to_float(ticker_features.get("return_20d")), 4),
        "volume_zscore_20": _round(_to_float(ticker_features.get("volume_zscore_20")), 4),
        "spy_close": _round(spy_close, 4),
        "spy_sma_200": _round(spy_sma200, 4),
        "spy_regime_bull": bool(spy_close is not None and spy_sma200 is not None and spy_close > spy_sma200),
    }


def _recommendation_from_metrics(
    ticker: str,
    direction: str,
    extraction: dict[str, Any],
    metrics: dict[str, Any],
) -> TradeRecommendation:
    close = _to_float(metrics.get("close"))
    reward_risk = _to_float(metrics.get("reward_risk"))
    stop = close * 0.95 if close else None
    take = close + (close - stop) * reward_risk if close and stop and reward_risk else None
    return TradeRecommendation(
        symbol=ticker,
        action="buy" if direction in {"buy", "watch"} else "hold",
        confidence=float(_to_float(extraction.get("confidence")) or 0.0),
        reason=str(extraction.get("thesis") or "mencion Telegram radar")[:500],
        entry_price=close,
        stop_loss=stop,
        take_profit=take,
        source="telegram_radar_research",
    )


def _candidate_from_metrics(ticker: str, metrics: dict[str, Any]) -> dict[str, Any]:
    score = 12
    if bool(metrics.get("spy_regime_bull")):
        score += 2
    if (_to_float(metrics.get("sma20_extension")) or 99.0) <= 0.08:
        score += 2
    if (_to_float(metrics.get("rsi_14")) or 99.0) <= 75.0:
        score += 2
    return {
        "symbol": ticker,
        "score": score,
        "setup_quality": "telegram_radar_research",
        "direction": "long",
        "relative_return_20d": 0.0,
        "technical_state": {
            "close": metrics.get("close"),
            "sma_20": metrics.get("sma_20"),
            "rsi_14": metrics.get("rsi_14"),
            "return_20d": metrics.get("return_20d"),
            "volume_zscore_20": metrics.get("volume_zscore_20"),
            "chart_patterns": [],
        },
    }


def _compact_checks(checks: dict[str, Any]) -> dict[str, Any]:
    keep = {
        "score",
        "rsi_14",
        "sma20_distance",
        "return_20d",
        "volume_zscore_20",
        "entry_score_v2",
    }
    return {key: checks.get(key) for key in keep if key in checks}


def _symbol_frame(data: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if isinstance(data.columns, pd.MultiIndex):
        if symbol in data.columns.get_level_values(0):
            return data[symbol].dropna(how="all").copy()
        if symbol in data.columns.get_level_values(-1):
            return data.xs(symbol, axis=1, level=-1).dropna(how="all").copy()
        return pd.DataFrame()
    return data.dropna(how="all").copy()


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


def _to_float(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: float | None, digits: int) -> float | None:
    return round(value, digits) if value is not None else None
