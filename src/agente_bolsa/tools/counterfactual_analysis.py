"""Counterfactual diagnostics for signal decisions and conservative policy changes."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store

from .reporting import write_json_report
from .signal_learning import build_learning_status, update_signal_outcomes

DEFAULT_RETROSPECTIVE_SESSIONS = 8
POLICIES = {"current", "proposed"}
RETURN_REFERENCE_KEY = "return_5d"


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: Any, digits: int = 4) -> float | None:
    number = _num(value)
    if number is None:
        return None
    return round(number, digits)


def _date_text(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    return text[:10]


def _parse_date(value: str | None) -> date | None:
    text = _date_text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _today_iso() -> str:
    return datetime.utcnow().date().isoformat()


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _write_report(report: dict[str, Any], reports_dir: Path, prefix: str, run_id: str) -> dict[str, Any]:
    return write_json_report(report, reports_dir, prefix, run_id)


def _decision_rank(decision: str) -> int:
    order = {
        "approved_buy": 5,
        "blocked_backtest": 4,
        "blocked_entry_quality": 3,
        "hold": 2,
        "candidate": 1,
    }
    return order.get(str(decision or ""), 0)


def _winner(outcome: dict[str, Any]) -> bool:
    verdict = str(outcome.get("verdict") or "")
    if verdict.startswith("winner"):
        return True
    ref = _num(outcome.get(RETURN_REFERENCE_KEY))
    return ref is not None and ref > 0.01


def _loser(outcome: dict[str, Any]) -> bool:
    verdict = str(outcome.get("verdict") or "")
    if verdict.startswith("loser"):
        return True
    ref = _num(outcome.get(RETURN_REFERENCE_KEY))
    return ref is not None and ref < -0.01


def _outcome_label(outcome: dict[str, Any]) -> str:
    verdict = str(outcome.get("verdict") or "")
    if verdict:
        return verdict
    if not outcome.get("matured"):
        return "pending"
    if _winner(outcome):
        return "winner_open"
    if _loser(outcome):
        return "loser_open"
    return "flat"


def _signal_rows(
    store: Store,
    *,
    since_date: str,
    end_date: str | None,
    limit: int = 200000,
) -> list[dict[str, Any]]:
    rows = store.signal_outcomes(limit=limit, since_date=since_date)
    if end_date:
        rows = [row for row in rows if row["signal_date"] <= end_date]
    return sorted(rows, key=lambda item: (item.get("signal_date", ""), item.get("created_at", ""), item.get("signal_id", "")))


def _buy_order_rows(store: Store, *, since_date: str, end_date: str | None) -> list[dict[str, Any]]:
    with store.connect() as conn:
        rows = conn.execute(
            """
            SELECT broker_order_id, plan_id, cycle_id, symbol, side, status, payload_json, created_at
            FROM broker_orders
            WHERE lower(side) = 'buy'
            ORDER BY created_at ASC
            """
        ).fetchall()
    result = []
    for row in rows:
        order_date = _date_text(row["created_at"])
        if order_date < since_date:
            continue
        if end_date and order_date > end_date:
            continue
        payload = json.loads(row["payload_json"] or "{}")
        plan = payload.get("plan", {}) or {}
        plan_payload = plan.get("payload", {}) or {}
        recommendation = plan_payload.get("recommendation", {}) or {}
        result.append(
            {
                "broker_order_id": row["broker_order_id"],
                "plan_id": row["plan_id"],
                "cycle_id": row["cycle_id"],
                "symbol": str(row["symbol"]).upper(),
                "side": str(row["side"]).lower(),
                "status": row["status"],
                "created_at": row["created_at"],
                "created_date": order_date,
                "entry_price": _num(plan_payload.get("entry_price")),
                "qty": _num(plan_payload.get("qty")),
                "notional": _num(plan.get("notional") or plan_payload.get("notional")),
                "recommendation": recommendation,
            }
        )
    return result


def _trade_recommendation_rows(store: Store, *, since_date: str, end_date: str | None) -> list[dict[str, Any]]:
    with store.connect() as conn:
        rows = conn.execute(
            """
            SELECT recommendation_id, cycle_id, symbol, action, confidence, payload_json, created_at
            FROM trade_recommendations
            ORDER BY created_at ASC
            """
        ).fetchall()
    result = []
    for row in rows:
        created_date = _date_text(row["created_at"])
        if created_date < since_date:
            continue
        if end_date and created_date > end_date:
            continue
        payload = json.loads(row["payload_json"] or "{}")
        result.append(
            {
                "recommendation_id": row["recommendation_id"],
                "cycle_id": row["cycle_id"],
                "symbol": str(row["symbol"]).upper(),
                "action": str(row["action"]).lower(),
                "confidence": _num(row["confidence"]),
                "payload": payload,
                "created_at": row["created_at"],
                "created_date": created_date,
            }
        )
    return result


def _trade_memory_outcomes(store: Store, *, since_date: str, end_date: str | None) -> dict[tuple[str, str], dict[str, Any]]:
    memories = store.trade_memory(limit=10000, since_date=since_date)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for memory in memories:
        if str(memory.get("side") or "").lower() != "buy":
            continue
        trade_date = _date_text(memory.get("trade_date"))
        if end_date and trade_date > end_date:
            continue
        grouped[(trade_date, str(memory.get("symbol") or "").upper())].append(memory)

    outcomes = {}
    for key, items in grouped.items():
        pl = sum(_num((item.get("outcome") or {}).get("pl")) or _num(item.get("open_pl")) or _num(item.get("realized_pl")) or 0.0 for item in items)
        notional = sum(_num(item.get("notional")) or 0.0 for item in items)
        plpc_values = [
            _num(item.get("open_plpc"))
            if _num(item.get("open_plpc")) is not None
            else _num(item.get("realized_plpc"))
            for item in items
        ]
        clean_plpc = [value for value in plpc_values if value is not None]
        plpc = sum(clean_plpc) / len(clean_plpc) if clean_plpc else (pl / notional if notional else None)
        if pl > 0:
            verdict = "winner_trade_memory"
        elif pl < 0:
            verdict = "loser_trade_memory"
        else:
            verdict = "flat_trade_memory"
        outcomes[key] = {
            "available": True,
            "matured": True,
            "source": "trade_memory",
            "trade_memory_pl": round(pl, 2),
            "trade_memory_plpc": _round(plpc, 4),
            "return_5d": _round(plpc, 4),
            "verdict": verdict,
            "bars_seen": 0,
            "matured_horizons": {"1d": False, "3d": False, "5d": True, "10d": False},
        }
    return outcomes


def _candidate_score(row: dict[str, Any]) -> float:
    return float(_num((row.get("features") or {}).get("score")) or 0.0)


def _rank_value(row: dict[str, Any], key: str) -> int | None:
    value = _num((row.get("features") or {}).get(key) or row.get(key))
    return int(value) if value is not None and value > 0 else None


def _regime_context(features: dict[str, Any]) -> dict[str, Any]:
    return_20d = _num(features.get("return_20d"))
    return_60d = _num(features.get("return_60d"))
    distance_sma200 = _num(features.get("distance_sma200"))
    distance_sma20 = _num(features.get("distance_sma20"))
    volume_z = _num(features.get("volume_zscore_20"))
    rsi = _num(features.get("rsi_14"))

    if distance_sma200 is not None:
        trend = "bull_trend" if distance_sma200 > 0 else "bear_trend"
    elif return_60d is not None:
        trend = "bull_trend" if return_60d > 0 else "bear_trend"
    else:
        trend = "unknown_trend"

    if return_20d is None:
        momentum = "unknown_momentum"
    elif return_20d > 0.05:
        momentum = "strong_momentum"
    elif return_20d > 0:
        momentum = "positive_momentum"
    else:
        momentum = "negative_momentum"

    if distance_sma20 is None:
        extension = "unknown_extension"
    elif distance_sma20 > 0.08:
        extension = "extended"
    elif distance_sma20 < 0:
        extension = "below_sma20"
    else:
        extension = "normal_extension"

    if volume_z is None:
        volume = "unknown_volume"
    elif volume_z >= 1:
        volume = "volume_confirmed"
    elif volume_z < 0:
        volume = "weak_volume"
    else:
        volume = "neutral_volume"

    if rsi is None:
        heat = "unknown_heat"
    elif rsi >= 85:
        heat = "extreme_rsi"
    elif rsi >= 75:
        heat = "hot_rsi"
    else:
        heat = "normal_rsi"

    return {
        "trend": trend,
        "momentum": momentum,
        "extension": extension,
        "volume": volume,
        "heat": heat,
        "key": "|".join([trend, momentum, extension, volume, heat]),
    }


def _score_reason(row: dict[str, Any]) -> str:
    features = row.get("features", {}) or {}
    score = _num(features.get("score"))
    rsi = _num(features.get("rsi_14"))
    dist = _num(features.get("distance_sma20"))
    rank = _rank_value(row, "score_rank")
    return (
        f"score={score if score is not None else '-'}; "
        f"rank={rank if rank is not None else '-'}; "
        f"rsi={round(rsi, 2) if rsi is not None else '-'}; "
        f"dist_sma20={round(dist, 4) if dist is not None else '-'}"
    )


def _explanation(row: dict[str, Any]) -> str:
    decision = str(row.get("decision") or "")
    gate = row.get("gate", {}) or {}
    if decision == "approved_buy":
        return f"Compra aprobada; {_score_reason(row)}"
    if decision == "blocked_entry_quality":
        reason = ((gate.get("entry_quality_gate") or {}).get("reason")) or "filtro de calidad de entrada"
        return f"Bloqueada por entry-quality: {reason}."
    if decision == "blocked_backtest":
        reason = ((gate.get("backtest_gate") or {}).get("reason")) or "backtest gate"
        return f"Bloqueada por backtest gate: {reason}."
    if decision == "hold":
        llm = gate.get("llm", {}) or {}
        reason = llm.get("reason") or "el LLM prefirio no abrir posicion"
        return f"Hold LLM: {reason}."
    if decision == "candidate":
        return f"Candidata tecnica no seleccionada; {_score_reason(row)}"
    return f"Decision {decision or 'desconocida'}."


def _outcome_with_maturity(outcome: dict[str, Any], signal_date: str) -> dict[str, Any]:
    current = dict(outcome or {})
    ref_horizons = [1, 3, 5, 10]
    maturity_horizon = 10
    for horizon in ref_horizons:
        if current.get(f"return_{horizon}d") is not None:
            maturity_horizon = max(maturity_horizon, horizon)
    signal_day = _parse_date(signal_date)
    today = _parse_date(_today_iso())
    days_elapsed = (today - signal_day).days if signal_day and today else None
    current["bars_seen"] = int(current.get("bars_seen") or 0)
    current["available"] = bool(current.get("available"))
    current["matured_horizons"] = {
        f"{h}d": current.get(f"return_{h}d") is not None for h in ref_horizons
    }
    current["matured"] = bool(current.get("matured")) or bool(current["matured_horizons"]["10d"])
    if not current["available"] and current["bars_seen"] > 0:
        current["available"] = True
    if not current["matured"] and days_elapsed is not None and days_elapsed >= 10 and current["bars_seen"] >= 10:
        current["matured"] = True
    current["days_elapsed"] = days_elapsed
    current["label"] = _outcome_label(current)
    return current


def _group_buy_orders(
    buy_orders: list[dict[str, Any]],
) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], dict[tuple[str, str], int]]:
    by_date_symbol: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    count_by_cycle_symbol: dict[tuple[str, str], int] = Counter()
    for order in buy_orders:
        by_date_symbol[(order["created_date"], order["symbol"])].append(order)
        if order.get("cycle_id"):
            count_by_cycle_symbol[(order["cycle_id"], order["symbol"])] += 1
    return by_date_symbol, count_by_cycle_symbol


def _rebuild_signal_cohorts(
    store: Store,
    *,
    since_date: str,
    end_date: str | None,
) -> list[dict[str, Any]]:
    signals = _signal_rows(store, since_date=since_date, end_date=end_date)
    buy_orders = _buy_order_rows(store, since_date=since_date, end_date=end_date)
    recommendations = _trade_recommendation_rows(store, since_date=since_date, end_date=end_date)
    trade_memory_outcomes = _trade_memory_outcomes(store, since_date=since_date, end_date=end_date)
    orders_by_date_symbol, cycle_symbol_counts = _group_buy_orders(buy_orders)
    recommendations_by_date_symbol: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for recommendation in recommendations:
        recommendations_by_date_symbol[(recommendation["created_date"], recommendation["symbol"])].append(recommendation)

    rows: list[dict[str, Any]] = []
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for raw in signals:
        signal_date = raw["signal_date"]
        symbol = raw["symbol"]
        source_run_id = raw.get("source_run_id") or ""
        decision = str(raw.get("decision") or "candidate")
        orders_same_day = orders_by_date_symbol.get((signal_date, symbol), [])
        executed_buy = decision == "approved_buy" and bool(orders_same_day)
        duplicate_execution = False
        if executed_buy:
            duplicate_execution = len(orders_same_day) > 1 or cycle_symbol_counts.get((orders_same_day[0].get("cycle_id") or "", symbol), 0) > 1

        outcome = _outcome_with_maturity(raw.get("outcome", {}) or {}, signal_date)
        if executed_buy and not outcome.get("matured"):
            trade_outcome = trade_memory_outcomes.get((signal_date, symbol))
            if trade_outcome:
                outcome = _outcome_with_maturity(trade_outcome, signal_date)
        row = {
            "signal_id": raw["signal_id"],
            "source_run_id": source_run_id,
            "source": raw.get("source"),
            "signal_date": signal_date,
            "symbol": symbol,
            "decision": decision,
            "features": raw.get("features", {}) or {},
            "gate": raw.get("gate", {}) or {},
            "outcome": outcome,
            "created_at": raw.get("created_at"),
            "updated_at": raw.get("updated_at"),
            "considered_by_llm": decision != "candidate" or bool(recommendations_by_date_symbol.get((signal_date, symbol))),
            "executed_buy": executed_buy,
            "orders_same_day": len(orders_same_day),
            "recommendations_same_day": len(recommendations_by_date_symbol.get((signal_date, symbol), [])),
            "duplicate_execution": duplicate_execution,
            "explanation": _explanation(raw),
            "score": _candidate_score(raw),
        }
        rows.append(row)
        by_source[source_run_id].append(row)

    for source_rows in by_source.values():
        ranked_source_rows = sorted(
            source_rows,
            key=lambda item: (-item["score"], item.get("signal_id", "")),
        )
        source_count = len(ranked_source_rows)
        for rank, row in enumerate(ranked_source_rows, start=1):
            features = row["features"]
            if not _rank_value(row, "score_rank"):
                features["score_rank"] = rank
            if not _rank_value(row, "source_candidate_count"):
                features["source_candidate_count"] = source_count
            if features.get("score_rank_percentile") is None and source_count:
                features["score_rank_percentile"] = round(rank / source_count, 4)
            row["rank_context"] = {
                "score_rank": _rank_value(row, "score_rank"),
                "source_rank": _rank_value(row, "source_rank"),
                "source_candidate_count": _rank_value(row, "source_candidate_count"),
                "score_rank_percentile": features.get("score_rank_percentile"),
            }
            row["regime"] = _regime_context(features)
        executed = [item for item in source_rows if item["executed_buy"]]
        max_executed_score = max((_candidate_score(item) for item in executed), default=None)
        any_executed = bool(executed)
        max_orders_reached = len(executed) >= 2
        executed_loser = any(_loser(item["outcome"]) for item in executed)
        for row in source_rows:
            missed_opportunity = (not row["executed_buy"]) and row["outcome"].get("matured") and _winner(row["outcome"])
            ranking_failure = (
                missed_opportunity
                and any_executed
                and executed_loser
                and max_executed_score is not None
                and row["score"] >= max_executed_score
            )
            timing_failure = (
                missed_opportunity
                and (row["decision"] == "approved_buy" or max_orders_reached)
                and not ranking_failure
            )
            risk_failure = row["decision"] in {"blocked_entry_quality", "blocked_backtest"}
            feature_gap = missed_opportunity and not ranking_failure and not timing_failure and not risk_failure
            row["cohort"] = (
                "executed_buy"
                if row["executed_buy"]
                else "approved_buy"
                if row["decision"] == "approved_buy"
                else "blocked_entry_quality"
                if row["decision"] == "blocked_entry_quality"
                else "blocked_backtest"
                if row["decision"] == "blocked_backtest"
                else "considered_by_llm"
                if row["considered_by_llm"]
                else "held_or_not_selected"
            )
            row["flags"] = {
                "missed_opportunity": missed_opportunity,
                "ranking_failure": ranking_failure,
                "timing_failure": timing_failure,
                "risk_failure": risk_failure,
                "feature_gap": feature_gap,
                "duplicate_execution": row["duplicate_execution"],
            }
            row["outcome_label"] = row["outcome"]["label"]
    return rows


def _summary_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    cohorts = Counter(row["cohort"] for row in rows)
    flags = Counter(
        name
        for row in rows
        for name, enabled in (row.get("flags") or {}).items()
        if enabled
    )
    matured = [row for row in rows if row["outcome"].get("matured")]
    missed = [row for row in rows if row["flags"]["missed_opportunity"]]
    return {
        "signals": len(rows),
        "matured": len(matured),
        "cohorts": dict(cohorts),
        "flags": dict(flags),
        "missed_opportunities": len(missed),
        "missed_winners": sum(1 for row in missed if _winner(row["outcome"])),
        "executed_duplicates": sum(1 for row in rows if row["duplicate_execution"] and row["executed_buy"]),
        "rank_shadow": _rank_shadow_summary(rows),
        "regime_summary": _regime_summary(rows),
    }


def _reference_return(row: dict[str, Any]) -> float:
    outcome = row.get("outcome", {}) or {}
    ref = _num(outcome.get(RETURN_REFERENCE_KEY))
    if ref is not None:
        return ref
    return float(_num(outcome.get("return_10d")) or 0.0)


def _confirmed_pattern_count(features: dict[str, Any]) -> int:
    chart = features.get("chart_patterns", {}) or {}
    if isinstance(chart, dict):
        return int(chart.get("bullish_confirmed_count") or 0)
    if isinstance(chart, list):
        return sum(1 for item in chart if item.get("bias") == "bullish" and item.get("status") == "confirmed")
    return 0


def _shadow_rank_priority(row: dict[str, Any]) -> float:
    features = row.get("features", {}) or {}
    score = _num(features.get("score")) or 0.0
    return_20d = _num(features.get("return_20d")) or 0.0
    distance_sma20 = _num(features.get("distance_sma20"))
    volume_z = _num(features.get("volume_zscore_20")) or 0.0
    rsi = _num(features.get("rsi_14"))
    confirmed_patterns = _confirmed_pattern_count(features)
    score_component = min(0.04, max(0.0, score / 1000.0))
    momentum_component = min(0.03, max(-0.01, return_20d * 0.25))
    volume_component = 0.01 if volume_z >= 1.0 else -0.01 if volume_z < 0 else 0.0
    pattern_component = min(0.02, confirmed_patterns * 0.01)
    extension_component = 0.0
    if distance_sma20 is not None:
        if 0 <= distance_sma20 <= 0.08:
            extension_component = 0.01
        elif distance_sma20 > 0.12:
            extension_component = -0.01
        elif distance_sma20 < 0:
            extension_component = -0.005
    weak_heat_penalty = 0.0
    if rsi is not None and rsi < 62.0 and volume_z < 0:
        weak_heat_penalty = 0.03
    event_bonus = (
        0.02
        if bool(features.get("event_momentum_long"))
        or bool(features.get("range_expansion_breakout_long"))
        or bool(features.get("orderly_breakout_long"))
        or bool(features.get("momentum_shakeout_hold_long"))
        else 0.0
    )
    return round(
        score_component
        + momentum_component
        + volume_component
        + pattern_component
        + extension_component
        + event_bonus
        - weak_heat_penalty,
        4,
    )


def _proposed_policy_blocks_row(row: dict[str, Any]) -> bool:
    features = row.get("features", {}) or {}
    if (
        bool(features.get("event_momentum_long"))
        or bool(features.get("range_expansion_breakout_long"))
        or bool(features.get("orderly_breakout_long"))
        or bool(features.get("momentum_shakeout_hold_long"))
    ):
        return False
    rsi = _num(features.get("rsi_14"))
    volume_z = _num(features.get("volume_zscore_20"))
    return rsi is not None and rsi < 62.0 and volume_z is not None and volume_z < 0.0


def _policy_executions(rows: list[dict[str, Any]], policy: str) -> list[dict[str, Any]]:
    if policy not in POLICIES:
        raise ValueError(f"Unsupported policy: {policy}")
    executed = [row for row in rows if row["executed_buy"]]
    if policy == "current":
        return executed

    accepted: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for row in sorted(executed, key=lambda item: (item["signal_date"], item.get("source_run_id", ""), item["symbol"], item["signal_id"])):
        if _proposed_policy_blocks_row(row):
            continue
        key = (row["signal_date"], row["symbol"])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        accepted.append(row)
    return accepted


def _rank_shadow_replacements(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    replacements = []
    rows_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        rows_by_source[str(row.get("source_run_id") or row["signal_date"])].append(row)

    for source_run_id, source_rows in rows_by_source.items():
        executed = [row for row in source_rows if row["executed_buy"]]
        candidates = [
            row for row in source_rows
            if not row["executed_buy"] and row["decision"] in {"candidate", "hold", "approved_buy"}
        ]
        if not executed or not candidates:
            continue
        ordered_executed = sorted(
            executed,
            key=lambda row: (_shadow_rank_priority(row), row["score"]),
        )
        ordered_candidates = sorted(
            candidates,
            key=lambda row: (_shadow_rank_priority(row), row["score"]),
            reverse=True,
        )
        for executed_row, candidate_row in zip(ordered_executed, ordered_candidates):
            candidate_priority = _shadow_rank_priority(candidate_row)
            executed_priority = _shadow_rank_priority(executed_row)
            if candidate_priority <= executed_priority:
                continue
            if not executed_row["outcome"].get("matured") or not candidate_row["outcome"].get("matured"):
                continue
            delta = _reference_return(candidate_row) - _reference_return(executed_row)
            replacements.append(
                {
                    "source_run_id": source_run_id,
                    "signal_date": executed_row["signal_date"],
                    "replace_symbol": executed_row["symbol"],
                    "with_symbol": candidate_row["symbol"],
                    "replace_score": executed_row["score"],
                    "with_score": candidate_row["score"],
                    "replace_priority": executed_priority,
                    "with_priority": candidate_priority,
                    "replace_return_5d": executed_row["outcome"].get("return_5d"),
                    "with_return_5d": candidate_row["outcome"].get("return_5d"),
                    "delta_return": _round(delta, 4),
                    "avoided_loser": _loser(executed_row["outcome"]),
                    "missed_winner": _winner(executed_row["outcome"]),
                    "new_winner": _winner(candidate_row["outcome"]),
                }
            )
    return replacements


def _rank_shadow_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    replacements = _rank_shadow_replacements(rows)
    return {
        "candidate_replacements": len(replacements),
        "positive_replacements": sum(1 for item in replacements if (_num(item.get("delta_return")) or 0.0) > 0),
        "negative_replacements": sum(1 for item in replacements if (_num(item.get("delta_return")) or 0.0) < 0),
        "avoided_losers": sum(1 for item in replacements if item.get("avoided_loser")),
        "missed_winners": sum(1 for item in replacements if item.get("missed_winner")),
        "delta_net_opportunity": _round(sum(_num(item.get("delta_return")) or 0.0 for item in replacements), 4),
        "examples": replacements[:20],
    }


def _regime_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_regime: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        regime = (row.get("regime") or {}).get("key") or "unknown"
        by_regime[regime].append(row)
    summary = []
    for regime, items in by_regime.items():
        matured = [row for row in items if row["outcome"].get("matured")]
        executed = [row for row in matured if row["executed_buy"]]
        winners = [row for row in matured if _winner(row["outcome"])]
        summary.append(
            {
                "regime": regime,
                "signals": len(items),
                "matured": len(matured),
                "executed": len(executed),
                "win_rate": _round(len(winners) / len(matured), 4) if matured else None,
                "avg_return_5d": _round(sum(_reference_return(row) for row in matured) / len(matured), 4) if matured else None,
            }
        )
    return sorted(
        summary,
        key=lambda item: (item["matured"], item["win_rate"] if item["win_rate"] is not None else -1),
        reverse=True,
    )[:20]


def _filter_reason(row: dict[str, Any]) -> str:
    decision = str(row.get("decision") or "")
    gate = row.get("gate", {}) or {}
    if decision == "blocked_entry_quality":
        item = gate.get("entry_quality_gate") or {}
        return str(item.get("reason") or "entry_quality_gate")
    if decision == "blocked_backtest":
        item = gate.get("backtest_gate") or {}
        return str(item.get("reason") or "backtest_gate")
    return decision or "unknown"


def _filter_calibration(rows: list[dict[str, Any]], *, decision: str) -> dict[str, Any]:
    blocked = [row for row in rows if str(row.get("decision") or "") == decision]
    matured = [row for row in blocked if row["outcome"].get("matured")]
    by_reason: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_regime: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in matured:
        by_reason[_filter_reason(row)].append(row)
        regime_key = ((row.get("regime") or {}).get("key")) or "unknown"
        by_regime[regime_key].append(row)

    def summarize(items: list[dict[str, Any]], label: str) -> dict[str, Any]:
        missed_winners = sum(1 for row in items if _winner(row["outcome"]))
        avoided_losers = sum(1 for row in items if _loser(row["outcome"]))
        avg_return = _round(sum(_reference_return(row) for row in items) / len(items), 4) if items else None
        return {
            "label": label,
            "signals": len(items),
            "missed_winners": missed_winners,
            "avoided_losers": avoided_losers,
            "net_winner_gap": missed_winners - avoided_losers,
            "avg_return_5d": avg_return,
            "delta_net_opportunity": _round(sum(_reference_return(row) for row in items), 4) if items else None,
        }

    return {
        "decision": decision,
        "signals": len(blocked),
        "matured": len(matured),
        "missed_winners": sum(1 for row in matured if _winner(row["outcome"])),
        "avoided_losers": sum(1 for row in matured if _loser(row["outcome"])),
        "avg_return_5d": _round(sum(_reference_return(row) for row in matured) / len(matured), 4) if matured else None,
        "delta_net_opportunity": _round(sum(_reference_return(row) for row in matured), 4) if matured else None,
        "by_reason": [
            summarize(items, reason)
            for reason, items in sorted(by_reason.items(), key=lambda item: len(item[1]), reverse=True)[:10]
        ],
        "by_regime": [
            summarize(items, regime)
            for regime, items in sorted(by_regime.items(), key=lambda item: len(item[1]), reverse=True)[:10]
        ],
    }


def _compare_policy_rows(rows: list[dict[str, Any]], policy: str) -> dict[str, Any]:
    current_rows = _policy_executions(rows, "current")
    proposed_rows = _policy_executions(rows, policy)
    blocked_ids = {row["signal_id"] for row in current_rows} - {row["signal_id"] for row in proposed_rows}
    blocked_rows = [row for row in current_rows if row["signal_id"] in blocked_ids]

    def aggregate(items: list[dict[str, Any]]) -> dict[str, Any]:
        matured = [row for row in items if row["outcome"].get("matured")]
        return {
            "executed": len(items),
            "matured": len(matured),
            "winners": sum(1 for row in matured if _winner(row["outcome"])),
            "losers": sum(1 for row in matured if _loser(row["outcome"])),
            "avg_return_5d": _round(sum(_reference_return(row) for row in matured) / len(matured), 4) if matured else None,
        }

    avoided_losers = [row for row in blocked_rows if row["outcome"].get("matured") and _loser(row["outcome"])]
    missed_winners = [row for row in blocked_rows if row["outcome"].get("matured") and _winner(row["outcome"])]
    delta = sum(-_reference_return(row) for row in blocked_rows if row["outcome"].get("matured"))
    return {
        "policy": policy,
        "current": aggregate(current_rows),
        "proposed": aggregate(proposed_rows),
        "blocked_by_policy": len(blocked_rows),
        "avoided_losers": len(avoided_losers),
        "missed_winners": len(missed_winners),
        "delta_net_opportunity": _round(delta, 4),
        "blocked_examples": [
            {
                "signal_date": row["signal_date"],
                "symbol": row["symbol"],
                "decision": row["decision"],
                "outcome_label": row["outcome_label"],
                "return_5d": row["outcome"].get("return_5d"),
                "explanation": "Bloqueada por politica propuesta: compra duplicada del mismo simbolo."
                if policy == "proposed"
                else row["explanation"],
            }
            for row in blocked_rows[:20]
        ],
        "rank_shadow": _rank_shadow_summary(rows),
        "regime_summary": _regime_summary(rows),
    }


def _session_dates(rows: list[dict[str, Any]]) -> list[str]:
    return sorted({row["signal_date"] for row in rows})


def _default_session_window(rows: list[dict[str, Any]], sessions: int) -> tuple[str | None, str | None]:
    dates = _session_dates(rows)
    if not dates:
        return None, None
    return dates[max(0, len(dates) - sessions)], dates[-1]


def build_signal_postmortem_report(
    settings: Settings,
    store: Store,
    reports_dir: Path,
    run_id: str,
    *,
    since_date: str,
    end_date: str | None = None,
    full: bool = False,
) -> dict[str, Any]:
    update_result = update_signal_outcomes(settings, store, since_date=since_date, limit=200000)
    rows = _rebuild_signal_cohorts(store, since_date=since_date, end_date=end_date)
    learning = build_learning_status(store, since_date=since_date, limit=200000)
    report = {
        "run_id": run_id,
        "as_of": datetime.utcnow().isoformat(),
        "period": {"from": since_date, "to": end_date or max(_session_dates(rows), default=since_date)},
        "update_result": update_result,
        "summary": _summary_from_rows(rows),
        "learning_status": learning,
        "notable_missed_opportunities": [row for row in rows if row["flags"]["missed_opportunity"]][:50],
        "ranking_failures": [row for row in rows if row["flags"]["ranking_failure"]][:50],
        "timing_failures": [row for row in rows if row["flags"]["timing_failure"]][:50],
        "risk_failures": [row for row in rows if row["flags"]["risk_failure"]][:50],
        "duplicate_executions": [row for row in rows if row["flags"]["duplicate_execution"] and row["executed_buy"]][:50],
        "recommendations": [
            "Mantener filtros de features nuevos en shadow hasta tener evidencia out-of-sample.",
            "Activar solo la deduplicacion de compras por simbolo y ciclo/source_run_id.",
            "Revisar cohortes de missed opportunities antes de tocar ranking o timing.",
        ],
    }
    if full:
        report["signal_rows"] = rows
    return _write_report(report, reports_dir, "postmortem_signals", run_id)


def build_missed_opportunities_report(
    settings: Settings,
    store: Store,
    reports_dir: Path,
    run_id: str,
    *,
    since_date: str,
    end_date: str | None = None,
    top: int = 20,
    full: bool = False,
) -> dict[str, Any]:
    update_signal_outcomes(settings, store, since_date=since_date, limit=200000)
    rows = _rebuild_signal_cohorts(store, since_date=since_date, end_date=end_date)
    missed = [row for row in rows if row["flags"]["missed_opportunity"]]
    ranking = [row for row in missed if row["flags"]["ranking_failure"]]
    timing = [row for row in missed if row["flags"]["timing_failure"]]
    blocked = [row for row in missed if row["decision"] in {"blocked_entry_quality", "blocked_backtest"}]
    entry_quality_calibration = _filter_calibration(rows, decision="blocked_entry_quality")
    backtest_calibration = _filter_calibration(rows, decision="blocked_backtest")
    report = {
        "run_id": run_id,
        "as_of": datetime.utcnow().isoformat(),
        "period": {"from": since_date, "to": end_date or max(_session_dates(rows), default=since_date)},
        "summary": {
            "missed_opportunities": len(missed),
            "ranking_failures": len(ranking),
            "timing_failures": len(timing),
            "blocked_by_filters": len(blocked),
        },
        "filter_calibration": {
            "entry_quality": entry_quality_calibration,
            "backtest_gate": backtest_calibration,
        },
        "top_missed_opportunities": sorted(
            missed,
            key=lambda row: (_reference_return(row), row["score"]),
            reverse=True,
        )[:top],
        "blocked_by_filters": blocked[:top],
        "ranking_failures": ranking[:top],
        "timing_failures": timing[:top],
    }
    if full:
        report["all_missed_opportunities"] = missed
    return _write_report(report, reports_dir, "missed_opportunities", run_id)


def build_decision_compare_report(
    settings: Settings,
    store: Store,
    reports_dir: Path,
    run_id: str,
    *,
    since_date: str,
    end_date: str | None = None,
    policy: str = "proposed",
    full: bool = False,
) -> dict[str, Any]:
    update_signal_outcomes(settings, store, since_date=since_date, limit=200000)
    rows = _rebuild_signal_cohorts(store, since_date=since_date, end_date=end_date)
    comparison = _compare_policy_rows(rows, policy)
    report = {
        "run_id": run_id,
        "as_of": datetime.utcnow().isoformat(),
        "period": {"from": since_date, "to": end_date or max(_session_dates(rows), default=since_date)},
        "summary": comparison,
    }
    if full:
        report["rows"] = rows
    return _write_report(report, reports_dir, "decision_compare", run_id)


def build_walk_forward_validation_report(
    settings: Settings,
    store: Store,
    reports_dir: Path,
    run_id: str,
    *,
    since_date: str,
    end_date: str | None = None,
    policy: str = "proposed",
    train_days: int = 5,
    test_days: int = 3,
    full: bool = False,
) -> dict[str, Any]:
    update_signal_outcomes(settings, store, since_date=since_date, limit=200000)
    rows = _rebuild_signal_cohorts(store, since_date=since_date, end_date=end_date)
    session_dates = _session_dates(rows)
    windows = []
    if not session_dates:
        report = {
            "run_id": run_id,
            "as_of": datetime.utcnow().isoformat(),
            "period": {"from": since_date, "to": end_date or since_date},
            "policy": policy,
            "train_days": train_days,
            "test_days": test_days,
            "windows": [],
            "summary": {"windows": 0},
        }
        return _write_report(report, reports_dir, "walk_forward_validation", run_id)

    for start_index in range(train_days, len(session_dates), test_days):
        train_slice = session_dates[max(0, start_index - train_days):start_index]
        test_slice = session_dates[start_index:start_index + test_days]
        if not test_slice:
            continue
        train_rows = [row for row in rows if row["signal_date"] in train_slice]
        test_rows = [row for row in rows if row["signal_date"] in test_slice]
        windows.append(
            {
                "train_period": {"from": train_slice[0], "to": train_slice[-1]} if train_slice else None,
                "test_period": {"from": test_slice[0], "to": test_slice[-1]},
                "train_summary": _summary_from_rows(train_rows),
                "test_comparison": _compare_policy_rows(test_rows, policy),
            }
        )
    report = {
        "run_id": run_id,
        "as_of": datetime.utcnow().isoformat(),
        "period": {"from": since_date, "to": end_date or session_dates[-1]},
        "policy": policy,
        "train_days": train_days,
        "test_days": test_days,
        "windows": windows,
        "summary": {
            "windows": len(windows),
            "stable_windows": sum(
                1
                for window in windows
                if (_num(((window.get("test_comparison") or {}).get("delta_net_opportunity"))) or 0.0) >= 0
            ),
        },
    }
    if full:
        report["rows"] = rows
    return _write_report(report, reports_dir, "walk_forward_validation", run_id)


def build_session_retrospective_report(
    settings: Settings,
    store: Store,
    reports_dir: Path,
    run_id: str,
    *,
    since_date: str | None = None,
    end_date: str | None = None,
    sessions: int = DEFAULT_RETROSPECTIVE_SESSIONS,
    policy: str = "proposed",
    full: bool = False,
) -> dict[str, Any]:
    update_signal_outcomes(settings, store, since_date=since_date or "1900-01-01", limit=200000)
    all_rows = _rebuild_signal_cohorts(store, since_date=since_date or "1900-01-01", end_date=end_date)
    if since_date is None:
        default_from, default_to = _default_session_window(all_rows, sessions)
        since_date = default_from or "1900-01-01"
        end_date = end_date or default_to
    rows = [
        row for row in all_rows
        if row["signal_date"] >= since_date and (end_date is None or row["signal_date"] <= end_date)
    ]
    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_session[row["signal_date"]].append(row)

    sessions_report = []
    for session_date in sorted(by_session):
        session_rows = by_session[session_date]
        comparison = _compare_policy_rows(session_rows, policy)
        rank_shadow = comparison.get("rank_shadow", {})
        sessions_report.append(
            {
                "session_date": session_date,
                "signals_considered": len(session_rows),
                "approved": sum(1 for row in session_rows if row["decision"] == "approved_buy"),
                "executed_current": comparison["current"]["executed"],
                "executed_proposed": comparison["proposed"]["executed"],
                "blocked_by_new_policy": comparison["blocked_by_policy"],
                "avoided_losers": comparison["avoided_losers"],
                "missed_winners": comparison["missed_winners"],
                "delta_net_opportunity": comparison["delta_net_opportunity"],
                "delta_fragmentation": comparison["blocked_by_policy"],
                "rank_shadow_replacements": rank_shadow.get("candidate_replacements", 0),
                "rank_shadow_delta": rank_shadow.get("delta_net_opportunity"),
                "top_regimes": comparison.get("regime_summary", [])[:3],
                "headline": (
                    "La politica nueva habria reducido duplicados sin coste neto material."
                    if (_num(comparison["delta_net_opportunity"]) or 0.0) >= 0
                    else "La politica nueva habria evitado duplicados pero con perdida de oportunidad en esa sesion."
                ),
                "examples": comparison["blocked_examples"][:5],
            }
        )

    best_day = max(sessions_report, key=lambda item: _num(item.get("delta_net_opportunity")) or -999, default=None)
    worst_day = min(sessions_report, key=lambda item: _num(item.get("delta_net_opportunity")) or 999, default=None)
    aggregate_delta = sum(_num(item.get("delta_net_opportunity")) or 0.0 for item in sessions_report)
    report = {
        "run_id": run_id,
        "as_of": datetime.utcnow().isoformat(),
        "policy": policy,
        "period": {"from": since_date, "to": end_date or max(_session_dates(rows), default=since_date)},
        "sessions": sessions_report,
        "summary": {
            "sessions": len(sessions_report),
            "aggregate_delta_net_opportunity": _round(aggregate_delta, 4),
            "aggregate_blocked_duplicates": sum(item["blocked_by_new_policy"] for item in sessions_report),
            "aggregate_avoided_losers": sum(item["avoided_losers"] for item in sessions_report),
            "aggregate_missed_winners": sum(item["missed_winners"] for item in sessions_report),
            "aggregate_rank_shadow_replacements": sum(item["rank_shadow_replacements"] for item in sessions_report),
            "aggregate_rank_shadow_delta": _round(
                sum(_num(item.get("rank_shadow_delta")) or 0.0 for item in sessions_report),
                4,
            ),
            "best_day": best_day,
            "worst_day": worst_day,
        },
    }
    if full:
        report["rows"] = rows
    return _write_report(report, reports_dir, "session_retrospective", run_id)
