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
        "setup_name": candidate.get("setup_name"),
        "selection_score": _num(candidate.get("selection_score")),
        "selection_rank": candidate.get("selection_rank"),
        "selection_reason": candidate.get("selection_reason"),
        "blocked_auto_buy": bool(candidate.get("blocked_auto_buy")),
        "blocked_auto_buy_reason": candidate.get("blocked_auto_buy_reason"),
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
        "gap_pct": _num(technical_state.get("gap_pct")),
        "close_position_in_range": _num(technical_state.get("close_position_in_range")),
        "breakout_continuation_long": bool(technical_state.get("breakout_continuation_long")),
        "range_expansion_breakout_long": bool(technical_state.get("range_expansion_breakout_long")),
        "orderly_breakout_long": bool(technical_state.get("orderly_breakout_long")),
        "breakout_failure_risk": bool(technical_state.get("breakout_failure_risk")),
        "event_momentum_long": bool(technical_state.get("event_momentum_long")),
        "momentum_shakeout_hold_long": bool(technical_state.get("momentum_shakeout_hold_long")),
        "distance_sma20": ((close - sma20) / sma20) if close and sma20 else None,
        "distance_sma200": ((close - sma200) / sma200) if close and sma200 else None,
        "chart_patterns": _chart_pattern_summary(candidate),
        "reasons": candidate.get("reasons", [])[:8],
    }


def _market_regime_features(report: dict[str, Any]) -> dict[str, Any]:
    state = report.get("market_state") if isinstance(report.get("market_state"), dict) else {}
    return {
        "market_regime": state.get("market_regime") or report.get("market_regime") or report.get("regime"),
        "volatility_regime": state.get("volatility_regime") or report.get("volatility_regime"),
        "risk_posture": state.get("risk_posture") or report.get("risk_posture"),
        "market_state_quality": ((state.get("data_quality") or {}).get("status") if isinstance(state.get("data_quality"), dict) else None)
        or report.get("market_state_quality"),
    }


def record_signal_candidates(store: Store, report: dict[str, Any], *, source: str) -> int:
    source_run_id = str(report.get("run_id") or "")
    if not source_run_id:
        return 0
    rows = []
    candidates = list(report.get("all_candidates", []) or [])
    selected_by_symbol = {
        str(candidate.get("symbol", "")).upper(): candidate
        for candidate in list(report.get("selected_candidates", []) or [])
        if str(candidate.get("symbol", "")).strip()
    }
    selection_method = str((report.get("selection_metadata", {}) or {}).get("method") or "").strip() or None
    regime_features = {key: value for key, value in _market_regime_features(report).items() if value not in (None, "")}
    score_rank_by_symbol = {
        str(candidate.get("symbol", "")).upper(): index
        for index, candidate in enumerate(
            sorted(
                candidates,
                key=lambda item: _num(item.get("score"), 0.0) or 0.0,
                reverse=True,
            ),
            start=1,
        )
        if str(candidate.get("symbol", "")).upper()
    }
    candidate_count = len(candidates)
    for original_index, candidate in enumerate(candidates, start=1):
        symbol = str(candidate.get("symbol", "")).upper()
        if not symbol:
            continue
        features = _signal_features(candidate)
        features.update(regime_features)
        selected_candidate = selected_by_symbol.get(symbol)
        if selected_candidate:
            features["selected_for_llm"] = True
            if features.get("selection_score") is None:
                features["selection_score"] = _num(selected_candidate.get("selection_score"))
            if features.get("selection_rank") is None:
                features["selection_rank"] = selected_candidate.get("selection_rank")
            if not features.get("selection_reason"):
                features["selection_reason"] = selected_candidate.get("selection_reason")
        else:
            features["selected_for_llm"] = False
        if selection_method:
            features["selection_method"] = selection_method
        score_rank = score_rank_by_symbol.get(symbol)
        features["source_rank"] = original_index
        features["score_rank"] = score_rank
        features["source_candidate_count"] = candidate_count
        features["score_rank_percentile"] = (
            round(score_rank / candidate_count, 4)
            if score_rank is not None and candidate_count
            else None
        )
        signal_date = _date(features.get("last_date"))
        signal_id = f"{source_run_id}:{_slug(symbol)}"
        rows.append(
            {
                "signal_id": signal_id,
                "source_run_id": source_run_id,
                "source": source,
                "symbol": symbol,
                "signal_date": signal_date,
                "decision": "candidate",
                "features": features,
                "gate": {},
                "outcome": {},
            }
        )
    if hasattr(store, "save_signal_outcomes_bulk"):
        store.save_signal_outcomes_bulk(rows)
    else:
        for row in rows:
            store.save_signal_outcome(**row)
    return len(rows)


def _signal_report_date(report: dict[str, Any]) -> str:
    report_date = _date(report.get("as_of") or report.get("session_date") or report.get("date"))
    if report_date:
        return report_date
    candidates = list(report.get("all_candidates", []) or [])
    if candidates:
        return _date(candidates[0].get("last_date"))
    return ""


def _inferred_selected_candidates(report: dict[str, Any], settings: Settings) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    top_longs = list(report.get("top_longs", []) or [])
    top_shorts = list(report.get("top_shorts", []) or [])
    long_limit = max(12, int(settings.news_sentiment_top_n), int(settings.trade_selection_top_n))
    short_limit = max(1, int(settings.news_sentiment_top_n // 2))
    selected = top_longs[:long_limit]
    if settings.allow_short_selling:
        selected = [*selected, *top_shorts[:short_limit]]
    metadata = {
        "method": "backfill_inferred_from_top_lists",
        "inferred": True,
        "long_limit": long_limit,
        "short_limit": short_limit if settings.allow_short_selling else 0,
    }
    return selected, metadata


def backfill_signal_candidates_from_reports(
    settings: Settings,
    store: Store,
    reports_dir: Path,
    *,
    since_date: str | None = None,
    end_date: str | None = None,
    source: str = "closed_market_study_backfill",
    infer_selected: bool = True,
) -> dict[str, Any]:
    reports = sorted(reports_dir.glob("closed_market_technical_study_*.json"))
    saved_reports = 0
    saved_signals = 0
    inferred_reports = 0
    skipped_reports = 0
    warnings: list[str] = []

    for path in reports:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - best-effort historical recovery.
            skipped_reports += 1
            warnings.append(f"{path.name}: {exc}")
            continue
        if not isinstance(report, dict):
            skipped_reports += 1
            warnings.append(f"{path.name}: formato no soportado")
            continue
        if not report.get("run_id") or not list(report.get("all_candidates", []) or []):
            skipped_reports += 1
            continue

        report_date = _signal_report_date(report)
        if since_date and report_date and report_date < since_date:
            continue
        if end_date and report_date and report_date > end_date:
            continue

        payload = dict(report)
        if infer_selected and not list(payload.get("selected_candidates", []) or []):
            selected, metadata = _inferred_selected_candidates(payload, settings)
            if selected:
                payload["selected_candidates"] = selected
                payload["selection_metadata"] = metadata
                inferred_reports += 1

        saved = record_signal_candidates(store, payload, source=source)
        if saved <= 0:
            skipped_reports += 1
            continue
        saved_reports += 1
        saved_signals += saved

    return {
        "reports_scanned": len(reports),
        "reports_saved": saved_reports,
        "signals_saved": saved_signals,
        "inferred_reports": inferred_reports,
        "skipped_reports": skipped_reports,
        "since_date": since_date,
        "end_date": end_date,
        "source": source,
        "warnings": warnings[:50],
    }


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
    settings: Settings | None = None,
) -> int:
    if not source_run_id:
        return 0
    settings = settings or Settings()
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
            entry_score = ((entry_gate or {}).get("checks") or {}).get("entry_score_v2") or {}
            entry_micro = bool(entry_score.get("micro_experiment") or recommendation.micro_experiment)
            if entry_gate and not entry_gate.get("approved") and not entry_micro:
                decision = "blocked_entry_quality"
            elif backtest and not backtest.get("approved"):
                if _paper_backtest_soft_override(settings, recommendation, gate):
                    decision = "approved_buy_soft_backtest"
                    gate["backtest_soft_override"] = {
                        "approved": True,
                        "reason": "paper_high_conviction_micro_override",
                    }
                else:
                    decision = "blocked_backtest"
                    shadow = _backtest_near_miss_shadow(settings, backtest)
                    if shadow:
                        gate["backtest_near_miss_shadow"] = shadow
            elif entry_micro:
                decision = "approved_buy_micro"
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


_BACKTEST_NEAR_MISS_SHADOW_RULES = {
    "hit-rate 44.00% < minimo 45.00%": "hit_rate_44_vs_45",
    "trade-window alpha -0.15% < minimo 0.00%": "trade_window_alpha_minus_0_15",
    "trades 8 < minimo 10": "trades_8_vs_10",
}


def _backtest_near_miss_shadow(settings: Settings, backtest_gate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not settings.backtest_gate_near_miss_shadow_enabled or not backtest_gate:
        return None
    reason = str(backtest_gate.get("reason") or "").strip()
    rule_id = _BACKTEST_NEAR_MISS_SHADOW_RULES.get(reason)
    if not rule_id:
        return None
    return {
        "enabled": True,
        "rule_id": rule_id,
        "reason": reason,
        "mode": "shadow_only",
        "action": "track_forward_outcome_without_relaxing_gate",
    }


def update_signal_execution_status(
    store: Store,
    *,
    source_run_id: str | None,
    approved_symbols: list[str] | None = None,
    rejected_order_plans: list[dict[str, Any]] | None = None,
    planned_symbols: list[str] | None = None,
    submitted: list[dict[str, Any]] | None = None,
    failed: list[dict[str, Any]] | None = None,
    effective_max_orders_per_cycle: int | None = None,
    effective_max_daily_buy_orders: int | None = None,
) -> int:
    if not source_run_id:
        return 0

    rejected_by_symbol: dict[str, dict[str, Any]] = {}
    for item in rejected_order_plans or []:
        symbol = str(item.get("symbol") or "").upper().strip()
        if symbol and symbol not in rejected_by_symbol:
            rejected_by_symbol[symbol] = item
    submitted_by_symbol = {
        str(item.get("symbol") or "").upper().strip(): item
        for item in (submitted or [])
        if str(item.get("symbol") or "").strip()
    }
    failed_by_symbol = {
        str(item.get("symbol") or "").upper().strip(): item
        for item in (failed or [])
        if str(item.get("symbol") or "").strip()
    }
    planned = {str(symbol).upper().strip() for symbol in (planned_symbols or []) if str(symbol).strip()}
    updated = 0

    for raw_symbol in approved_symbols or []:
        symbol = str(raw_symbol or "").upper().strip()
        if not symbol:
            continue
        payload = {
            "effective_max_orders_per_cycle": effective_max_orders_per_cycle,
            "effective_max_daily_buy_orders": effective_max_daily_buy_orders,
        }
        if symbol in submitted_by_symbol:
            item = submitted_by_symbol[symbol]
            payload.update(
                {
                    "status": "submitted",
                    "broker_status": item.get("status"),
                    "notional": item.get("notional"),
                }
            )
        elif symbol in failed_by_symbol:
            item = failed_by_symbol[symbol]
            payload.update(
                {
                    "status": "submit_failed",
                    "side": item.get("side"),
                    "error": item.get("error"),
                }
            )
        elif symbol in rejected_by_symbol:
            item = rejected_by_symbol[symbol]
            payload.update(
                {
                    "status": "plan_rejected",
                    "stage": item.get("stage"),
                    "reason": item.get("reason"),
                    "checks": item.get("checks", {}),
                }
            )
        elif symbol in planned:
            payload["status"] = "plan_created"
        else:
            payload["status"] = "approved_not_planned"
        store.update_signal_gate(
            source_run_id=source_run_id,
            symbol=symbol,
            gate={"execution": payload},
        )
        updated += 1
    return updated


def _paper_backtest_soft_override(
    settings: Settings,
    recommendation: TradeRecommendation,
    gate: dict[str, Any],
) -> bool:
    if not settings.backtest_gate_paper_soft_override_enabled:
        return False
    if settings.trading_mode != "paper":
        return False
    if settings.trade_aggressiveness_profile not in {"opportunistic", "aggressive"}:
        return False
    if recommendation.backtest_soft_override or "backtest_soft_override_eligible" in list(
        recommendation.soft_override_reasons or []
    ):
        return True
    entry_gate = gate.get("entry_quality_gate") or {}
    entry_checks = entry_gate.get("checks") or {}
    entry_score = entry_checks.get("entry_score_v2") or {}
    if entry_gate and not entry_gate.get("approved") and not entry_score.get("micro_experiment"):
        return False

    reward_risk = _num(entry_score.get("reward_risk"))
    score = _num(entry_checks.get("score"), 0.0)
    volume_z = _num(entry_checks.get("volume_zscore_20"), 0.0)
    close_position = _num(entry_checks.get("close_position_in_range"), 0.0)
    sma20_distance = _num(entry_checks.get("sma20_distance"))
    rsi = _num(entry_checks.get("rsi_14"))
    confirmed = int(entry_checks.get("confirmed_bullish_patterns") or 0)
    sentiment_score = _num(entry_checks.get("sentiment_score"))
    sentiment_confidence = _num(entry_checks.get("sentiment_confidence"), 0.0) or 0.0
    confirmed_negative_sentiment = (
        sentiment_score is not None
        and sentiment_confidence >= 0.5
        and sentiment_score <= -0.5
    )

    return bool(
        (score or 0.0) >= 16
        and (volume_z or 0.0) >= 1.25
        and confirmed >= 1
        and reward_risk is not None
        and reward_risk >= 1.5
        and (close_position or 0.0) >= 0.80
        and (sma20_distance is None or sma20_distance <= 0.26)
        and (rsi is None or rsi <= 88.0)
        and not confirmed_negative_sentiment
    )


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
    bar_dates = frame.index.map(_bar_date)
    future = frame.loc[bar_dates > signal_date].copy()
    if future.empty:
        return {
            "available": False,
            "matured": False,
            "bars_seen": 0,
            "matured_horizons": {f"{h}d": False for h in HORIZONS},
            "reason": "sin barras posteriores",
        }

    closes = [_num(value) for value in future["Close"].tolist()]
    highs = [_num(value) for value in future["High"].tolist()]
    lows = [_num(value) for value in future["Low"].tolist()]
    dates = [_bar_date(index) for index in future.index]
    returns = {}
    matured_horizons = {}
    for horizon in HORIZONS:
        if len(closes) >= horizon and closes[horizon - 1] is not None:
            returns[f"return_{horizon}d"] = round((closes[horizon - 1] - entry) / entry, 4)
            matured_horizons[f"{horizon}d"] = True
        else:
            returns[f"return_{horizon}d"] = None
            matured_horizons[f"{horizon}d"] = False

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
        "matured": len(closes) >= max(HORIZONS),
        "bars_seen": len(closes),
        "matured_horizons": matured_horizons,
        "as_of": datetime.now(timezone.utc).isoformat(),
        **returns,
        "mfe_10d": round((max(window_highs) - entry) / entry, 4) if window_highs else None,
        "mae_10d": round((min(window_lows) - entry) / entry, 4) if window_lows else None,
        "first_hit": first_hit,
        "exit_policy_v2": _simulate_exit_policy_v2(
            entry=entry,
            stop=stop,
            take=take,
            closes=closes,
            highs=highs,
            lows=lows,
            dates=dates,
        ),
    }
    outcome["verdict"] = _verdict(outcome)
    return outcome


def _simulate_exit_policy_v2(
    *,
    entry: float,
    stop: float | None,
    take: float | None,
    closes: list[float | None],
    highs: list[float | None],
    lows: list[float | None],
    dates: list[str],
    partial_r: float = 1.0,
    trailing_r: float = 2.0,
    trailing_giveback_r: float = 1.0,
    time_stop_days: int = 5,
    time_stop_min_return: float = 0.0,
    stale_guard_enabled: bool = False,
    stale_guard_days: int = 10,
    stale_guard_max_peak_return: float = 0.05,
    stale_guard_min_return: float = 0.01,
) -> dict[str, Any]:
    if not entry or not closes:
        return {"available": False, "reason": "sin barras"}
    initial_risk = entry - stop if stop is not None and stop < entry else None
    if initial_risk is None or initial_risk <= 0:
        initial_risk = entry * 0.05
    partial_taken = False
    peak_price = entry
    trailing_stop = stop
    events: list[dict[str, Any]] = []
    exit_price = closes[min(len(closes), 10) - 1] or entry
    exit_reason = "horizon_10d" if len(closes) >= 10 else "pending"
    exit_day = min(len(closes), 10)
    max_window = min(len(closes), 10)
    for index in range(max_window):
        day = index + 1
        date = dates[index] if index < len(dates) else ""
        high = highs[index]
        low = lows[index]
        close = closes[index]
        if high is not None:
            peak_price = max(peak_price, high)
        if not partial_taken and high is not None and high >= entry + (partial_r * initial_risk):
            partial_taken = True
            events.append(
                {
                    "type": "partial_take_profit",
                    "date": date,
                    "days": day,
                    "price": round(entry + (partial_r * initial_risk), 4),
                    "fraction": 0.5,
                }
            )
        if high is not None and high >= entry + (trailing_r * initial_risk):
            candidate_stop = peak_price - (trailing_giveback_r * initial_risk)
            trailing_stop = max(trailing_stop or 0.0, candidate_stop)
        active_stop = trailing_stop or stop
        if low is not None and active_stop is not None and low <= active_stop:
            exit_price = active_stop
            exit_reason = "trailing_stop" if trailing_stop and trailing_stop != stop else "stop_loss"
            exit_day = day
            events.append({"type": exit_reason, "date": date, "days": day, "price": round(exit_price, 4)})
            break
        if high is not None and take is not None and high >= take:
            exit_price = take
            exit_reason = "take_profit"
            exit_day = day
            events.append({"type": "take_profit", "date": date, "days": day, "price": round(exit_price, 4)})
            break
        if day >= time_stop_days and close is not None and ((close - entry) / entry) <= time_stop_min_return:
            exit_price = close
            exit_reason = "time_stop"
            exit_day = day
            events.append({"type": "time_stop", "date": date, "days": day, "price": round(exit_price, 4)})
            break
        if (
            stale_guard_enabled
            and day >= stale_guard_days
            and close is not None
            and ((peak_price - entry) / entry) <= stale_guard_max_peak_return
            and ((close - entry) / entry) <= stale_guard_min_return
        ):
            exit_price = close
            exit_reason = "stale_guard"
            exit_day = day
            events.append({"type": "stale_guard", "date": date, "days": day, "price": round(exit_price, 4)})
            break
    gross_return = (exit_price - entry) / entry
    if partial_taken and exit_reason not in {"pending"}:
        partial_price = entry + (partial_r * initial_risk)
        gross_return = (((partial_price - entry) / entry) * 0.5) + (((exit_price - entry) / entry) * 0.5)
    # Retorno neto de slippage sintetico (T5.5), aditivo: no altera return_pct
    # (que sigue siendo el bruto) para no romper metricas/tests existentes.
    from .cost_calibration import apply_synthetic_slippage

    net_return = apply_synthetic_slippage(gross_return, slippage_bps=10)
    return {
        "available": True,
        "exit_reason": exit_reason,
        "exit_day": exit_day,
        "exit_price": round(exit_price, 4),
        "return_pct": round(gross_return, 4),
        "gross_return_pct": round(gross_return, 4),
        "net_return_pct": round(net_return, 4),
        "partial_taken": partial_taken,
        "peak_return": round((peak_price - entry) / entry, 4),
        "events": events,
        "parameters": {
            "partial_r": partial_r,
            "trailing_r": trailing_r,
            "trailing_giveback_r": trailing_giveback_r,
            "time_stop_days": time_stop_days,
            "time_stop_min_return": time_stop_min_return,
            "stale_guard_enabled": stale_guard_enabled,
            "stale_guard_days": stale_guard_days,
            "stale_guard_max_peak_return": stale_guard_max_peak_return,
            "stale_guard_min_return": stale_guard_min_return,
        },
    }


def _verdict(outcome: dict[str, Any]) -> str:
    if not outcome.get("matured") and not (outcome.get("first_hit") or {}).get("type"):
        return "pending"
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
    outcome_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
    outcomes_to_save: dict[str, dict[str, Any]] = {}
    for signal in signals:
        try:
            frame = _symbol_frame(data, signal["symbol"]).dropna(how="all")
            if frame.empty:
                continue
            features = signal.get("features", {}) or {}
            cache_key = (
                signal["symbol"],
                signal["signal_date"],
                _num(features.get("entry_price") or features.get("close")),
                _num(features.get("stop_loss")),
                _num(features.get("take_profit")),
            )
            outcome = outcome_cache.get(cache_key)
            if outcome is None:
                outcome = _outcome_for_signal(signal, frame)
                outcome_cache[cache_key] = outcome
            outcomes_to_save[signal["signal_id"]] = outcome
            updated += 1
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{signal['symbol']}: {exc}")
    if hasattr(store, "update_signal_outcomes_bulk"):
        store.update_signal_outcomes_bulk(outcomes_to_save)
    else:
        for signal_id, outcome in outcomes_to_save.items():
            store.update_signal_outcome(signal_id, outcome)
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


def _combo_key(signal: dict[str, Any]) -> str:
    features = signal.get("features", {}) or {}
    chart = features.get("chart_patterns", {}) or {}
    score = _bucket(features.get("score"), [("lt12", -999, 12), ("12_14", 12, 15), ("gte15", 15, 999)])
    rsi = _bucket(features.get("rsi_14"), [("lt60", -999, 60), ("60_75", 60, 75), ("75_85", 75, 85), ("gt85", 85, 999)])
    dist = _bucket(
        features.get("distance_sma20"),
        [("lt0", -999, 0), ("0_6pct", 0, 0.06), ("6_12pct", 0.06, 0.12), ("gt12pct", 0.12, 999)],
    )
    macd = "macd_pos" if _num(features.get("macd_diff"), 0) and _num(features.get("macd_diff"), 0) > 0 else "macd_nonpos"
    volume = _bucket(features.get("volume_zscore_20"), [("vol_lt0", -999, 0), ("vol_0_1", 0, 1), ("vol_gt1", 1, 999)])
    pattern = "pattern_yes" if chart.get("bullish_confirmed_count", 0) else "pattern_no"
    return "|".join([f"score_{score}", f"rsi_{rsi}", f"sma20_{dist}", macd, volume, pattern])


def _setup_key(signal: dict[str, Any]) -> str:
    features = signal.get("features", {}) or {}
    if bool(features.get("event_momentum_long")):
        return "event_momentum"
    if bool(features.get("range_expansion_breakout_long")):
        return "range_expansion_breakout"
    if bool(features.get("orderly_breakout_long")):
        return "orderly_breakout"
    if bool(features.get("momentum_shakeout_hold_long")):
        return "momentum_shakeout"
    chart = features.get("chart_patterns", {}) or {}
    if chart.get("bullish_confirmed_count", 0):
        return "confirmed_pattern"
    volume_z = _num(features.get("volume_zscore_20")) or 0.0
    return_20d = _num(features.get("return_20d")) or 0.0
    if volume_z >= 1.0 and return_20d > 0:
        return "trend_volume"
    return "baseline_trend"


def _resolved_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        signal
        for signal in signals
        if (
            (signal.get("outcome") or {}).get("verdict") not in {None, "", "pending"}
            or any((signal.get("outcome") or {}).get(f"return_{h}d") is not None for h in HORIZONS)
        )
    ]


def _signal_stat(items: list[dict[str, Any]], *, key: str | None = None) -> dict[str, Any]:
    resolved = _resolved_signals(items)
    winners = [
        item
        for item in resolved
        if str((item.get("outcome") or {}).get("verdict", "")).startswith("winner")
    ]
    returns_1d = [_num((item.get("outcome") or {}).get("return_1d")) for item in resolved]
    returns_3d = [_num((item.get("outcome") or {}).get("return_3d")) for item in resolved]
    returns_5d = [_num((item.get("outcome") or {}).get("return_5d")) for item in resolved]
    returns_10d = [_num((item.get("outcome") or {}).get("return_10d")) for item in resolved]
    mfe = [_num((item.get("outcome") or {}).get("mfe_10d")) for item in resolved]
    mae = [_num((item.get("outcome") or {}).get("mae_10d")) for item in resolved]

    def avg(values: list[float | None]) -> float | None:
        clean = [value for value in values if value is not None]
        return round(sum(clean) / len(clean), 4) if clean else None

    out = {
        "signals": len(items),
        "resolved": len(resolved),
        "pending": len(items) - len(resolved),
        "win_rate": round(len(winners) / len(resolved), 4) if resolved else None,
        "avg_return_1d": avg(returns_1d),
        "avg_return_3d": avg(returns_3d),
        "avg_return_5d": avg(returns_5d),
        "avg_return_10d": avg(returns_10d),
        "avg_mfe_10d": avg(mfe),
        "avg_mae_10d": avg(mae),
    }
    if key is not None:
        out["key"] = key
    return out


def build_learning_status(store: Store, *, since_date: str = "2026-04-01", limit: int = 1000) -> dict[str, Any]:
    signals = store.signal_outcomes(limit=limit, since_date=since_date)
    by_tag: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_combo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_setup: dict[str, list[dict[str, Any]]] = defaultdict(list)
    verdicts = Counter()
    decisions = Counter()
    for signal in signals:
        decisions[signal["decision"]] += 1
        verdict = (signal.get("outcome") or {}).get("verdict", "pending")
        verdicts[verdict] += 1
        for tag in _indicator_tags(signal):
            by_tag[tag].append(signal)
        by_combo[_combo_key(signal)].append(signal)
        by_setup[_setup_key(signal)].append(signal)

    indicator_stats = []
    for tag, items in by_tag.items():
        stat = _signal_stat(items, key=tag)
        stat["tag"] = stat.pop("key")
        indicator_stats.append(stat)
    combo_stats = []
    for combo, items in by_combo.items():
        stat = _signal_stat(items, key=combo)
        combo_stats.append(stat)
    setup_stats = []
    for setup, items in by_setup.items():
        stat = _signal_stat(items, key=setup)
        stat["setup"] = stat.pop("key")
        setup_stats.append(stat)
    indicator_stats.sort(
        key=lambda item: (
            item["resolved"],
            item["win_rate"] if item["win_rate"] is not None else -1,
            item["avg_return_5d"] if item["avg_return_5d"] is not None else -1,
        ),
        reverse=True,
    )
    combo_stats.sort(
        key=lambda item: (
            item["resolved"],
            item["win_rate"] if item["win_rate"] is not None else -1,
            item["avg_return_5d"] if item["avg_return_5d"] is not None else -1,
        ),
        reverse=True,
    )
    setup_stats.sort(
        key=lambda item: (
            item["resolved"],
            item["avg_return_5d"] if item["avg_return_5d"] is not None else -1,
            item["win_rate"] if item["win_rate"] is not None else -1,
        ),
        reverse=True,
    )
    resolved_total = len(_resolved_signals(signals))
    horizon_maturity = {
        f"{h}d": sum(
            1
            for signal in signals
            if ((signal.get("outcome") or {}).get("matured_horizons", {}) or {}).get(f"{h}d")
            or (signal.get("outcome") or {}).get(f"return_{h}d") is not None
        )
        for h in HORIZONS
    }
    return {
        "since_date": since_date,
        "signals": len(signals),
        "resolved": resolved_total,
        "pending": len(signals) - resolved_total,
        "maturity": {
            "resolved_ratio": round(resolved_total / len(signals), 4) if signals else 0.0,
            "horizon_coverage": horizon_maturity,
            "enough_for_rules": resolved_total >= 50,
            "note": "usar 1d/3d para aprendizaje temprano y 5d/10d para validacion mas fuerte; no promover reglas sin evidencia suficiente",
        },
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
        "best_combinations": combo_stats[:10],
        "setup_stats": setup_stats,
        "worst_combinations": sorted(
            [item for item in combo_stats if item["resolved"]],
            key=lambda item: (
                item["win_rate"] if item["win_rate"] is not None else 1,
                item["avg_return_5d"] if item["avg_return_5d"] is not None else 1,
            ),
        )[:10],
        "worst_setups": sorted(
            [item for item in setup_stats if item["resolved"]],
            key=lambda item: (
                item["win_rate"] if item["win_rate"] is not None else 1,
                item["avg_return_5d"] if item["avg_return_5d"] is not None else 1,
            ),
        )[:5],
    }


def write_learning_report(report: dict[str, Any], reports_dir: Path, run_id: str) -> dict[str, Any]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"signal_learning_{run_id}.json"
    latest_path = reports_dir / "latest_signal_learning.json"
    report["path"] = str(path)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    latest_path.write_text(json.dumps(report, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    return report
