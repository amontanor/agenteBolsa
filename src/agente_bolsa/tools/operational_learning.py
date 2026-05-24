"""Operational trade memory, shadow rules and learning review."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

from agente_bolsa.config import Settings
from agente_bolsa.llm_usage import record_llm_response
from agente_bolsa.models import new_id
from agente_bolsa.storage import Store

from .trade_history import DEFAULT_HISTORY_START_DATE, build_trade_history


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _short(value: Any, max_chars: int = 500) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _stable_id(*parts: Any) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _parse_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _local_order_contexts(store: Store) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    with store.connect() as conn:
        rows = conn.execute(
            """
            SELECT broker_order_id, plan_id, cycle_id, symbol, side, status, payload_json, created_at
            FROM broker_orders
            ORDER BY created_at DESC
            """
        ).fetchall()
    by_order_id: dict[str, dict[str, Any]] = {}
    by_symbol_side: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        payload = _parse_json(row["payload_json"])
        plan = payload.get("plan", {}) or {}
        plan_payload = plan.get("payload", {}) or {}
        recommendation = plan_payload.get("recommendation", {}) or {}
        risk_decision = plan_payload.get("risk_decision", {}) or {}
        context = {
            "broker_order_id": row["broker_order_id"],
            "plan_id": row["plan_id"],
            "cycle_id": row["cycle_id"],
            "symbol": str(row["symbol"]).upper(),
            "side": str(row["side"]).lower(),
            "status": row["status"],
            "created_at": row["created_at"],
            "plan": plan,
            "recommendation": recommendation,
            "risk_decision": risk_decision,
        }
        if row["broker_order_id"]:
            by_order_id[str(row["broker_order_id"])] = context
        key = (context["symbol"], context["side"])
        by_symbol_side.setdefault(key, context)
    return by_order_id, by_symbol_side


def _signal_context(store: Store, symbol: str, *, as_of_date: str | None = None) -> dict[str, Any]:
    if as_of_date:
        with store.connect() as conn:
            row = conn.execute(
                """
                SELECT signal_id, source_run_id, source, symbol, signal_date,
                       decision, features_json, gate_json, outcome_json,
                       created_at, updated_at
                FROM signal_outcomes
                WHERE symbol = ?
                  AND signal_date <= ?
                ORDER BY signal_date DESC, created_at DESC
                LIMIT 1
                """,
                (symbol.upper(), as_of_date),
            ).fetchone()
        if row:
            signal = {
                "signal_id": row["signal_id"],
                "source_run_id": row["source_run_id"],
                "source": row["source"],
                "symbol": row["symbol"],
                "signal_date": row["signal_date"],
                "decision": row["decision"],
                "features": json.loads(row["features_json"] or "{}"),
                "gate": json.loads(row["gate_json"] or "{}"),
                "outcome": json.loads(row["outcome_json"] or "{}"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        else:
            signal = None
    else:
        signal = store.latest_signal_for_symbol(symbol)
    if not signal:
        return {}
    return {
        "signal_id": signal.get("signal_id"),
        "source_run_id": signal.get("source_run_id"),
        "signal_date": signal.get("signal_date"),
        "decision": signal.get("decision"),
        "features": signal.get("features", {}),
        "gate": signal.get("gate", {}),
        "outcome": signal.get("outcome", {}),
    }


def _flatten_features(
    *,
    signal: dict[str, Any],
    order_context: dict[str, Any],
    same_symbol_buys_day: int,
) -> dict[str, Any]:
    signal_features = signal.get("features", {}) or {}
    gate = signal.get("gate", {}) or {}
    gate_checks = gate.get("checks", {}) if isinstance(gate, dict) else {}
    risk_checks = (order_context.get("risk_decision", {}) or {}).get("checks", {}) or {}
    recommendation = order_context.get("recommendation", {}) or {}
    position_sizing = risk_checks.get("position_sizing", {}) or {}

    return {
        "score": signal_features.get("score") or gate_checks.get("score"),
        "setup_quality": signal_features.get("setup_quality") or gate_checks.get("setup_quality"),
        "direction": signal_features.get("direction") or gate_checks.get("direction"),
        "rsi_14": signal_features.get("rsi_14") or gate_checks.get("rsi_14"),
        "distance_sma20": signal_features.get("distance_sma20") or gate_checks.get("sma20_distance"),
        "macd_diff": signal_features.get("macd_diff"),
        "volume_zscore_20": signal_features.get("volume_zscore_20") or gate_checks.get("volume_zscore_20"),
        "relative_return_20d": signal_features.get("relative_return_20d") or gate_checks.get("relative_return_20d"),
        "return_20d": signal_features.get("return_20d") or gate_checks.get("return_20d"),
        "chart_patterns": signal_features.get("chart_patterns") or {},
        "confirmed_patterns": gate_checks.get("confirmed_bullish_patterns"),
        "sentiment_score": gate_checks.get("sentiment_score"),
        "sentiment_confidence": gate_checks.get("sentiment_confidence"),
        "llm_confidence": recommendation.get("confidence"),
        "target_exposure_pct": recommendation.get("target_exposure_pct"),
        "risk_per_dollar": position_sizing.get("risk_per_dollar"),
        "max_position_notional": position_sizing.get("max_position_notional"),
        "same_symbol_buys_day": same_symbol_buys_day,
    }


def _outcome_for_trade(trade: dict[str, Any], open_position: dict[str, Any] | None) -> dict[str, Any]:
    realized_pl = _num(trade.get("realized_pl"))
    open_pl = _num(open_position.get("unrealized_pl")) if open_position else None
    open_plpc = _num(open_position.get("unrealized_plpc")) if open_position else None
    pl = realized_pl if realized_pl is not None else open_pl
    if pl is None:
        verdict = "pending"
    elif pl > 0:
        verdict = "winner_open" if realized_pl is None else "winner_realized"
    elif pl < 0:
        verdict = "loser_open" if realized_pl is None else "loser_realized"
    else:
        verdict = "flat"
    return {
        "verdict": verdict,
        "pl": round(pl, 2) if pl is not None else None,
        "plpc": trade.get("realized_plpc") if realized_pl is not None else open_plpc,
        "realized": realized_pl is not None,
    }


def _decision_group_key(memory: dict[str, Any]) -> tuple[str, str, str, str]:
    thesis = memory.get("thesis", {}) or {}
    source_order = thesis.get("source_order", {}) or {}
    cycle_id = str(source_order.get("cycle_id") or "")
    if cycle_id:
        return (
            str(memory.get("trade_date") or ""),
            str(memory.get("symbol") or "").upper(),
            str(memory.get("side") or "").lower(),
            cycle_id,
        )
    return (
        str(memory.get("trade_date") or ""),
        str(memory.get("symbol") or "").upper(),
        str(memory.get("side") or "").lower(),
        str(memory.get("trade_time") or "")[:16],
    )


def _weighted_average(items: list[dict[str, Any]], value_key: str, weight_key: str = "qty") -> float | None:
    total_weight = 0.0
    total_value = 0.0
    for item in items:
        value = _num(item.get(value_key))
        weight = _num(item.get(weight_key)) or 0.0
        if value is None or weight <= 0:
            continue
        total_weight += weight
        total_value += value * weight
    if total_weight <= 0:
        return None
    return round(total_value / total_weight, 4)


def _feature_family(features: dict[str, Any]) -> list[str]:
    score = _num(features.get("score"))
    rsi = _num(features.get("rsi_14"))
    dist = _num(features.get("distance_sma20"))
    rel = _num(features.get("relative_return_20d"))
    vol = _num(features.get("volume_zscore_20"))
    macd = _num(features.get("macd_diff"))
    tags = []
    if score is not None:
        tags.append("score_alto" if score >= 15 else "score_medio" if score >= 12 else "score_bajo")
    if rsi is not None:
        tags.append("rsi_extremo" if rsi >= 85 else "rsi_alto" if rsi >= 75 else "rsi_normal")
    if dist is not None:
        tags.append("extendida" if dist > 0.08 else "no_extendida")
    if rel is not None:
        tags.append("rs_positiva" if rel > 0 else "rs_negativa")
    if vol is not None:
        tags.append("vol_confirma" if vol >= 1 else "vol_debil" if vol < 0 else "vol_neutro")
    if macd is not None:
        tags.append("macd_positivo" if macd > 0 else "macd_negativo")
    return tags


def _classify_error(decision: dict[str, Any]) -> str:
    side = str(decision.get("side") or "").lower()
    features = decision.get("features", {}) or {}
    verdict = str(decision.get("verdict") or "")
    pl = _num((decision.get("outcome") or {}).get("pl"))
    if not verdict.startswith("loser") and not (pl is not None and pl < 0):
        return "none"
    same_symbol_orders = int(decision.get("orders") or 0)
    dist = _num(features.get("distance_sma20"))
    rsi = _num(features.get("rsi_14"))
    vol = _num(features.get("volume_zscore_20"))
    rel = _num(features.get("relative_return_20d"))
    if same_symbol_orders > 1:
        return "execution_fragmentation"
    if side == "buy" and dist is not None and dist > 0.08 and (vol is None or vol < 0):
        return "overextended_without_volume"
    if side == "buy" and rsi is not None and rsi > 85 and (vol is None or vol < 1):
        return "extreme_rsi_without_confirmation"
    if side == "buy" and rel is not None and rel <= 0:
        return "weak_relative_strength"
    return "signal_or_market_noise"


def build_decision_memory(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group multiple fills/orders into one learning decision per symbol/session thesis."""

    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for memory in memories:
        groups[_decision_group_key(memory)].append(memory)

    decisions = []
    for index, (key, items) in enumerate(groups.items()):
        trade_date, symbol, side, group_ref = key
        sorted_items = sorted(items, key=lambda item: str(item.get("trade_time") or ""))
        qty = sum(_num(item.get("qty")) or 0.0 for item in sorted_items)
        notional = sum(_num(item.get("notional")) or 0.0 for item in sorted_items)
        realized_pl_values = [_num(item.get("realized_pl")) for item in sorted_items]
        open_pl_values = [_num(item.get("open_pl")) for item in sorted_items]
        realized_pl = sum(value for value in realized_pl_values if value is not None)
        open_pl = sum(value for value in open_pl_values if value is not None)
        has_realized = any(value is not None for value in realized_pl_values)
        has_open = any(value is not None for value in open_pl_values)
        pl = realized_pl if has_realized else open_pl if has_open else None
        if pl is None:
            verdict = "pending"
        elif pl > 0:
            verdict = "winner_realized" if has_realized else "winner_open"
        elif pl < 0:
            verdict = "loser_realized" if has_realized else "loser_open"
        else:
            verdict = "flat"

        features = dict((sorted_items[-1].get("features") or {}))
        decision = {
            "decision_id": f"td_{_stable_id(trade_date, symbol, side, group_ref)}",
            "trade_date": trade_date,
            "symbol": symbol,
            "side": side,
            "orders": len(sorted_items),
            "qty": round(qty, 6),
            "avg_price": _weighted_average(sorted_items, "price"),
            "notional": round(notional, 2),
            "first_trade_time": sorted_items[0].get("trade_time"),
            "last_trade_time": sorted_items[-1].get("trade_time"),
            "stop_loss": sorted_items[-1].get("stop_loss"),
            "take_profit": sorted_items[-1].get("take_profit"),
            "verdict": verdict,
            "features": features,
            "feature_family": _feature_family(features),
            "outcome": {
                "pl": round(pl, 2) if pl is not None else None,
                "realized": has_realized,
                "open": has_open and not has_realized,
            },
            "source_memory_ids": [item.get("memory_id") for item in sorted_items],
        }
        decision["error_type"] = _classify_error(decision)
        decisions.append(decision)

    decisions.sort(key=lambda item: str(item.get("last_trade_time") or ""), reverse=True)
    return decisions


def _decision_summary(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    verdicts = Counter(item.get("verdict") for item in decisions)
    errors = Counter(item.get("error_type") for item in decisions if item.get("error_type") != "none")
    repeated = [item for item in decisions if int(item.get("orders") or 0) > 1]
    resolved = [item for item in decisions if item.get("verdict") not in {None, "pending"}]
    winners = [item for item in resolved if str(item.get("verdict", "")).startswith("winner")]
    return {
        "decisions": len(decisions),
        "resolved": len(resolved),
        "win_rate": round(len(winners) / len(resolved), 4) if resolved else None,
        "verdicts": dict(verdicts),
        "error_types": dict(errors),
        "fragmented_decisions": len(repeated),
        "avg_orders_per_decision": round(
            sum(int(item.get("orders") or 0) for item in decisions) / len(decisions), 2
        )
        if decisions
        else 0.0,
    }


def _learning_journal(
    summary: dict[str, Any],
    shadow_eval: dict[str, Any],
    decisions: list[dict[str, Any]],
) -> list[str]:
    decision_summary = summary.get("decision_summary", {}) or {}
    notes = [
        (
            f"Decisiones agrupadas: {decision_summary.get('decisions', 0)} "
            f"desde {summary.get('trade_memories', 0)} memorias de orden/fill."
        )
    ]
    if decision_summary.get("fragmented_decisions", 0):
        notes.append(
            f"Hay {decision_summary['fragmented_decisions']} decision(es) fragmentadas; "
            "el aprendizaje las trata como una tesis unica para no inflar evidencia."
        )
    errors = decision_summary.get("error_types", {}) or {}
    if errors:
        main_error, count = Counter(errors).most_common(1)[0]
        notes.append(f"Principal tipo de error detectado: {main_error} ({count} caso(s)).")
    else:
        notes.append("No hay patron de error dominante en decisiones resueltas.")

    metrics = shadow_eval.get("metrics_by_rule", {}) or {}
    near_rules = []
    for rule_id, rule_metrics in metrics.items():
        cases = int(rule_metrics.get("cases") or 0)
        net = _num(rule_metrics.get("net_shadow_pl")) or 0.0
        if cases >= 10 and net >= 0:
            near_rules.append(f"{rule_id}: {cases} casos, net shadow {net:.2f}")
    if near_rules:
        notes.append("Reglas shadow con evidencia parcial: " + "; ".join(near_rules[:4]) + ".")
    else:
        notes.append("Ninguna regla shadow tiene todavia evidencia suficiente para activarse.")

    latest = decisions[:3]
    if latest:
        latest_text = ", ".join(
            f"{item['symbol']} {item['side']} {item['verdict']} ({item.get('orders')} orden(es))"
            for item in latest
        )
        notes.append(f"Ultimas decisiones revisadas: {latest_text}.")
    return notes


def sync_trade_memory(settings: Settings, store: Store, *, since_date: str = DEFAULT_HISTORY_START_DATE) -> dict[str, Any]:
    """Persist enriched trade memory rows from Alpaca fills plus local decisions."""

    history = build_trade_history(settings, limit=1000, start_date=since_date, scope="agent")
    by_order_id, by_symbol_side = _local_order_contexts(store)
    open_positions = {
        str(item.get("symbol", "")).upper(): item
        for item in history.get("open_positions", [])
    }
    buy_counts: Counter[tuple[str, str]] = Counter()
    seen_buy_orders: set[tuple[str, str, str]] = set()
    updated = 0
    warnings: list[str] = []

    for trade in history.get("trades", []):
        symbol = str(trade.get("symbol", "")).upper()
        side = str(trade.get("side", "")).lower()
        date = str(trade.get("date") or str(trade.get("time", ""))[:10])
        order_id = str(trade.get("order_id") or "")
        order_context = by_order_id.get(order_id) or by_symbol_side.get((symbol, side), {})
        plan_id = str(order_context.get("plan_id") or order_id or trade.get("time") or "")
        if side == "buy":
            order_key = (date, symbol, plan_id)
            if order_key not in seen_buy_orders:
                seen_buy_orders.add(order_key)
                buy_counts[(date, symbol)] += 1
        signal = _signal_context(store, symbol, as_of_date=date)
        open_position = open_positions.get(symbol)
        outcome = _outcome_for_trade(trade, open_position)
        features = _flatten_features(
            signal=signal,
            order_context=order_context,
            same_symbol_buys_day=buy_counts[(date, symbol)],
        )
        recommendation = order_context.get("recommendation", {}) or {}
        thesis = {
            "reason": recommendation.get("reason"),
            "confidence": recommendation.get("confidence"),
            "time_horizon": recommendation.get("time_horizon"),
            "invalidation": recommendation.get("invalidation"),
            "source_order": {
                "broker_order_id": order_context.get("broker_order_id"),
                "plan_id": order_context.get("plan_id"),
                "cycle_id": order_context.get("cycle_id"),
                "status": order_context.get("status"),
            },
            "signal": signal,
        }
        memory_id = f"tm_{_stable_id(order_id, trade.get('time'), symbol, side, trade.get('qty'), trade.get('price'))}"
        item = {
            "memory_id": memory_id,
            "trade_time": trade.get("time"),
            "trade_date": date,
            "symbol": symbol,
            "side": side,
            "qty": trade.get("qty") or 0.0,
            "price": trade.get("price") or 0.0,
            "notional": trade.get("notional") or 0.0,
            "stop_loss": trade.get("stop_loss") or order_context.get("plan", {}).get("payload", {}).get("stop_loss"),
            "take_profit": trade.get("take_profit") or order_context.get("plan", {}).get("payload", {}).get("take_profit"),
            "realized_pl": trade.get("realized_pl"),
            "realized_plpc": trade.get("realized_plpc"),
            "open_pl": open_position.get("unrealized_pl") if open_position else None,
            "open_plpc": open_position.get("unrealized_plpc") if open_position else None,
            "verdict": outcome["verdict"],
            "features": features,
            "thesis": thesis,
            "outcome": outcome,
        }
        try:
            store.save_trade_memory(item)
            updated += 1
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{symbol}: {exc}")

    return {
        "updated": updated,
        "trades_seen": len(history.get("trades", [])),
        "warnings": warnings,
    }


def audit_trade_memory_traceability(store: Store, *, since_date: str = DEFAULT_HISTORY_START_DATE) -> dict[str, Any]:
    memories = store.trade_memory(limit=5000, since_date=since_date)
    issues: list[dict[str, Any]] = []
    with store.connect() as conn:
        broker_order_ids = {
            str(row["broker_order_id"])
            for row in conn.execute("SELECT broker_order_id FROM broker_orders").fetchall()
            if row["broker_order_id"]
        }
        plan_ids = {
            str(row["plan_id"])
            for row in conn.execute("SELECT plan_id FROM broker_orders").fetchall()
            if row["plan_id"]
        }
        signal_ids = {
            str(row["signal_id"])
            for row in conn.execute("SELECT signal_id FROM signal_outcomes").fetchall()
            if row["signal_id"]
        }

    for memory in memories:
        thesis = memory.get("thesis", {}) or {}
        source_order = thesis.get("source_order", {}) or {}
        signal = thesis.get("signal", {}) or {}
        memory_id = memory.get("memory_id")
        symbol = str(memory.get("symbol") or "").upper()
        order_id = str(source_order.get("broker_order_id") or "")
        plan_id = str(source_order.get("plan_id") or "")
        signal_id = str(signal.get("signal_id") or "")
        signal_symbol = str(signal.get("symbol") or "").upper()
        signal_date = str(signal.get("signal_date") or "")
        trade_date = str(memory.get("trade_date") or "")
        if not source_order or not order_id:
            issues.append({"memory_id": memory_id, "symbol": symbol, "kind": "missing_order_context"})
        elif order_id not in broker_order_ids:
            issues.append({"memory_id": memory_id, "symbol": symbol, "kind": "unknown_broker_order_id", "broker_order_id": order_id})
        if plan_id and plan_id not in plan_ids:
            issues.append({"memory_id": memory_id, "symbol": symbol, "kind": "unknown_plan_id", "plan_id": plan_id})
        if not signal_id:
            issues.append({"memory_id": memory_id, "symbol": symbol, "kind": "missing_signal_context"})
        elif signal_id not in signal_ids:
            issues.append({"memory_id": memory_id, "symbol": symbol, "kind": "unknown_signal_id", "signal_id": signal_id})
        if signal_symbol and signal_symbol != symbol:
            issues.append(
                {
                    "memory_id": memory_id,
                    "symbol": symbol,
                    "kind": "signal_symbol_mismatch",
                    "signal_symbol": signal_symbol,
                }
            )
        if signal_date and trade_date and signal_date > trade_date:
            issues.append(
                {
                    "memory_id": memory_id,
                    "symbol": symbol,
                    "kind": "signal_after_trade",
                    "signal_date": signal_date,
                    "trade_date": trade_date,
                }
            )
    issue_counts = Counter(item["kind"] for item in issues)
    return {
        "since_date": since_date,
        "memories_checked": len(memories),
        "issues": len(issues),
        "issue_counts": dict(issue_counts),
        "examples": issues[:25],
        "complete": len(issues) == 0,
    }


DEFAULT_RULES = [
    {
        "rule_id": "rule_avoid_extended_low_volume",
        "name": "Evitar entrada extendida sin volumen",
        "description": "Bloquear compras cuando el precio esta >8% sobre SMA20 y volumen relativo es negativo.",
        "condition": {
            "all": [
                {"field": "side", "op": "==", "value": "buy"},
                {"field": "features.distance_sma20", "op": ">", "value": 0.08},
                {"field": "features.volume_zscore_20", "op": "<", "value": 0.0},
            ]
        },
        "effect": "block_buy",
    },
    {
        "rule_id": "rule_require_relative_strength_for_extended",
        "name": "Exigir fuerza relativa en entradas extendidas",
        "description": "Bloquear compras extendidas si la fuerza relativa 20d no supera 2%.",
        "condition": {
            "all": [
                {"field": "side", "op": "==", "value": "buy"},
                {"field": "features.distance_sma20", "op": ">", "value": 0.08},
                {"field": "features.relative_return_20d", "op": "<", "value": 0.02},
            ]
        },
        "effect": "block_buy",
    },
    {
        "rule_id": "rule_avoid_extreme_rsi_without_volume",
        "name": "RSI extremo exige volumen",
        "description": "Bloquear compras con RSI >85 si no hay volumen de confirmacion.",
        "condition": {
            "all": [
                {"field": "side", "op": "==", "value": "buy"},
                {"field": "features.rsi_14", "op": ">", "value": 85.0},
                {"field": "features.volume_zscore_20", "op": "<", "value": 1.0},
            ]
        },
        "effect": "block_buy",
    },
    {
        "rule_id": "rule_limit_symbol_reentry_same_session",
        "name": "Evitar reentradas repetidas por simbolo",
        "description": "Bloquear compras adicionales del mismo simbolo en la misma sesion.",
        "condition": {
            "all": [
                {"field": "side", "op": "==", "value": "buy"},
                {"field": "features.same_symbol_buys_day", "op": ">", "value": 1},
            ]
        },
        "effect": "cap_symbol_session",
    },
]


def ensure_default_shadow_rules(store: Store) -> list[str]:
    changed = []
    for rule in DEFAULT_RULES:
        existing = store.strategy_rule(rule["rule_id"])
        if existing:
            continue
        store.upsert_strategy_rule(
            {
                **rule,
                "status": "shadow",
                "source": "deterministic_rule_miner",
                "evidence": {"created_from": "operational_learning"},
                "metrics": {},
            }
        )
        changed.append(rule["rule_id"])
    return changed


def _field_value(memory: dict[str, Any], field: str) -> Any:
    current: Any = memory
    for part in field.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _condition_matches(condition: dict[str, Any], memory: dict[str, Any]) -> bool:
    clauses = condition.get("all", [])
    for clause in clauses:
        left = _field_value(memory, str(clause.get("field", "")))
        right = clause.get("value")
        op = clause.get("op")
        if op == "==":
            if str(left).lower() != str(right).lower():
                return False
        else:
            left_num = _num(left)
            right_num = _num(right)
            if left_num is None or right_num is None:
                return False
            if op == ">" and not left_num > right_num:
                return False
            if op == ">=" and not left_num >= right_num:
                return False
            if op == "<" and not left_num < right_num:
                return False
            if op == "<=" and not left_num <= right_num:
                return False
    return True


def _rule_walk_forward_summary(
    memories: list[dict[str, Any]],
    *,
    window_sessions: int,
    min_cases_per_window: int,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for memory in memories:
        grouped[str(memory.get("trade_date") or "")].append(memory)
    session_dates = sorted(date_text for date_text in grouped if date_text)
    windows = []
    for start_index in range(0, len(session_dates), window_sessions):
        slice_dates = session_dates[start_index:start_index + window_sessions]
        if not slice_dates:
            continue
        items = [memory for date_text in slice_dates for memory in grouped.get(date_text, [])]
        cases = len(items)
        avoided_loss = round(
            sum(abs(_num((item.get("outcome") or {}).get("pl")) or 0.0) for item in items if (_num((item.get("outcome") or {}).get("pl")) or 0.0) < 0),
            2,
        )
        missed_gain = round(
            sum((_num((item.get("outcome") or {}).get("pl")) or 0.0) for item in items if (_num((item.get("outcome") or {}).get("pl")) or 0.0) > 0),
            2,
        )
        losses_blocked = sum(1 for item in items if (_num((item.get("outcome") or {}).get("pl")) or 0.0) < 0)
        gains_blocked = sum(1 for item in items if (_num((item.get("outcome") or {}).get("pl")) or 0.0) > 0)
        eligible = cases >= min_cases_per_window
        net_shadow_pl = round(avoided_loss - missed_gain, 2)
        stable = eligible and net_shadow_pl >= 0 and losses_blocked >= gains_blocked
        windows.append(
            {
                "from": slice_dates[0],
                "to": slice_dates[-1],
                "cases": cases,
                "eligible": eligible,
                "stable": stable,
                "losses_blocked": losses_blocked,
                "gains_blocked": gains_blocked,
                "net_shadow_pl": net_shadow_pl,
            }
        )
    eligible_windows = [item for item in windows if item["eligible"]]
    stable_windows = [item for item in eligible_windows if item["stable"]]
    return {
        "window_sessions": window_sessions,
        "min_cases_per_window": min_cases_per_window,
        "windows": windows,
        "eligible_windows": len(eligible_windows),
        "stable_windows": len(stable_windows),
        "stable_ratio": round(len(stable_windows) / len(eligible_windows), 4) if eligible_windows else None,
    }


def evaluate_shadow_rules(
    store: Store,
    *,
    since_date: str = DEFAULT_HISTORY_START_DATE,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or Settings()
    memories = store.trade_memory(limit=1000, since_date=since_date)
    rules = [rule for rule in store.strategy_rules(limit=500) if rule["status"] in {"shadow", "active", "rejected"}]
    evaluations = 0
    metrics_by_rule: dict[str, dict[str, Any]] = {}

    for rule in rules:
        rule_metrics = {
            "cases": 0,
            "would_block": 0,
            "avoided_loss": 0.0,
            "missed_gain": 0.0,
            "net_shadow_pl": 0.0,
            "losses_blocked": 0,
            "gains_blocked": 0,
        }
        for memory in memories:
            would_block = _condition_matches(rule.get("condition", {}), memory)
            if not would_block:
                continue
            pl = _num((memory.get("outcome") or {}).get("pl"))
            actual_outcome = (memory.get("outcome") or {}).get("verdict") or "unknown"
            avoided_loss = abs(pl) if pl is not None and pl < 0 else 0.0
            missed_gain = pl if pl is not None and pl > 0 else 0.0
            evaluation = {
                "evaluation_id": f"re_{_stable_id(rule['rule_id'], memory['memory_id'])}",
                "rule_id": rule["rule_id"],
                "memory_id": memory["memory_id"],
                "symbol": memory["symbol"],
                "would_block": True,
                "actual_outcome": actual_outcome,
                "avoided_loss": round(avoided_loss, 2),
                "missed_gain": round(missed_gain, 2),
                "payload": {
                    "rule": rule["name"],
                    "trade_time": memory["trade_time"],
                    "features": memory.get("features", {}),
                    "outcome": memory.get("outcome", {}),
                },
            }
            store.save_rule_evaluation(evaluation)
            evaluations += 1
            rule_metrics["cases"] += 1
            rule_metrics["would_block"] += 1
            rule_metrics["avoided_loss"] += avoided_loss
            rule_metrics["missed_gain"] += missed_gain
            if avoided_loss:
                rule_metrics["losses_blocked"] += 1
            if missed_gain:
                rule_metrics["gains_blocked"] += 1
        rule_metrics["avoided_loss"] = round(rule_metrics["avoided_loss"], 2)
        rule_metrics["missed_gain"] = round(rule_metrics["missed_gain"], 2)
        rule_metrics["net_shadow_pl"] = round(rule_metrics["avoided_loss"] - rule_metrics["missed_gain"], 2)
        rule_metrics["hit_rate"] = (
            round(rule_metrics["losses_blocked"] / rule_metrics["cases"], 4)
            if rule_metrics["cases"]
            else None
        )
        matched_memories = [
            memory for memory in memories if _condition_matches(rule.get("condition", {}), memory)
        ]
        walk_forward = _rule_walk_forward_summary(
            matched_memories,
            window_sessions=settings.shadow_rule_walk_forward_window_sessions,
            min_cases_per_window=settings.shadow_rule_walk_forward_min_cases_per_window,
        )
        rule_metrics["promotion_policy"] = {
            "min_cases": 20,
            "min_net_shadow_pl": 0.0,
            "losses_blocked_must_cover_gains_blocked": True,
            "min_walk_forward_windows": settings.shadow_rule_walk_forward_min_windows,
            "min_walk_forward_stable_ratio": settings.shadow_rule_walk_forward_min_stable_ratio,
            "status_note": "shadow hasta reunir evidencia suficiente y estabilidad walk-forward",
        }
        rule_metrics["walk_forward"] = walk_forward
        updated_status = rule["status"]
        if rule["status"] == "rejected" and rule_metrics["cases"] < 20:
            updated_status = "shadow"
        if rule["status"] in {"shadow", "rejected"} and rule_metrics["cases"] >= 20:
            stable_ratio = _num(walk_forward.get("stable_ratio")) or 0.0
            enough_windows = int(walk_forward.get("eligible_windows") or 0) >= settings.shadow_rule_walk_forward_min_windows
            stable_enough = stable_ratio >= settings.shadow_rule_walk_forward_min_stable_ratio
            if (
                rule_metrics["net_shadow_pl"] > 0
                and rule_metrics["losses_blocked"] >= rule_metrics["gains_blocked"]
                and enough_windows
                and stable_enough
            ):
                updated_status = "active"
            elif rule_metrics["net_shadow_pl"] < 0:
                updated_status = "rejected"
        store.upsert_strategy_rule({**rule, "status": updated_status, "metrics": rule_metrics})
        metrics_by_rule[rule["rule_id"]] = {**rule_metrics, "status": updated_status}

    return {
        "rules_evaluated": len(rules),
        "memories_evaluated": len(memories),
        "evaluations_saved": evaluations,
        "metrics_by_rule": metrics_by_rule,
    }


def _llm_learning_review(settings: Settings, report: dict[str, Any]) -> dict[str, Any]:
    client = OpenAI(
        api_key=settings.openai_api_key or "local-llama",
        base_url=settings.openai_api_base,
        timeout=settings.llm_timeout_seconds,
    )
    prompt = {
        "summary": report["summary"],
        "rules": report["rules"][:20],
        "recent_trade_memory": report["recent_trade_memory"][:30],
        "constraints": [
            "No propongas cambios grandes.",
            "No modifiques codigo.",
            "Propón reglas pequenas, medibles y reversibles.",
            "Las reglas nuevas deben empezar en shadow.",
            "Devuelve solo JSON valido.",
        ],
    }
    messages = [
        {
            "role": "system",
            "content": (
                "Eres un investigador cuantitativo post-operacion. Analiza memoria de trades y reglas shadow. "
                "Devuelve JSON con assessment, what_worked, mistakes, candidate_rules y next_actions. "
                "candidate_rules debe contener objetos con rule_id, name, description, condition, effect, confidence, evidence."
            ),
        },
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=True, default=str)},
    ]
    response = client.chat.completions.create(
        model=settings.openai_model,
        temperature=0.1,
        max_tokens=max(settings.llm_max_tokens or 0, 1800),
        messages=messages,
    )
    record_llm_response(settings, "operational_learning", response, prompt=messages)
    text = response.choices[0].message.content or "{}"
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {"assessment": _short(text, 1200), "parse_warning": "LLM no devolvio JSON valido."}


def _promote_llm_rules(store: Store, llm_review: dict[str, Any]) -> list[str]:
    changed = []
    for item in llm_review.get("candidate_rules", []) or []:
        if not isinstance(item, dict):
            continue
        raw_id = str(item.get("rule_id") or item.get("name") or new_id("llm_rule"))
        rule_id = raw_id if raw_id.startswith("rule_") else f"rule_llm_{_stable_id(raw_id)}"
        condition = item.get("condition")
        if not isinstance(condition, dict) or not condition.get("all"):
            continue
        store.upsert_strategy_rule(
            {
                "rule_id": rule_id,
                "name": str(item.get("name") or rule_id)[:160],
                "description": str(item.get("description") or "")[:1000],
                "condition": condition,
                "effect": str(item.get("effect") or "block_buy"),
                "status": "shadow",
                "source": "llm_learning_review",
                "evidence": {
                    "confidence": item.get("confidence"),
                    "evidence": item.get("evidence"),
                },
                "metrics": {},
            }
        )
        changed.append(rule_id)
    return changed


def build_operational_learning_review(
    settings: Settings,
    store: Store,
    reports_dir: Path,
    run_id: str,
    *,
    since_date: str = DEFAULT_HISTORY_START_DATE,
    use_llm: bool = False,
) -> dict[str, Any]:
    store.ensure_schema()
    reports_dir.mkdir(parents=True, exist_ok=True)
    memory_sync = sync_trade_memory(settings, store, since_date=since_date)
    traceability_audit = audit_trade_memory_traceability(store, since_date=since_date)
    default_rules_created = ensure_default_shadow_rules(store)
    shadow_eval = evaluate_shadow_rules(store, since_date=since_date, settings=settings)
    memories = store.trade_memory(limit=500, since_date=since_date)
    decisions = build_decision_memory(memories)
    rules = store.strategy_rules(limit=200)
    verdicts = Counter(memory.get("verdict") for memory in memories)
    by_symbol = Counter(memory.get("symbol") for memory in memories)
    summary = {
        "since_date": since_date,
        "trade_memories": len(memories),
        "trade_decisions": len(decisions),
        "rules_total": len(rules),
        "rules_shadow": sum(1 for rule in rules if rule["status"] == "shadow"),
        "rules_active": sum(1 for rule in rules if rule["status"] == "active"),
        "rules_rejected": sum(1 for rule in rules if rule["status"] == "rejected"),
        "verdicts": dict(verdicts),
        "top_symbols": dict(by_symbol.most_common(8)),
        "decision_summary": _decision_summary(decisions),
    }
    report: dict[str, Any] = {
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "memory_sync": memory_sync,
        "traceability_audit": traceability_audit,
        "default_rules_created": default_rules_created,
        "shadow_evaluation": shadow_eval,
        "rules": rules,
        "trade_decisions": decisions[:100],
        "recent_trade_memory": memories[:100],
        "learning_journal": _learning_journal(summary, shadow_eval, decisions),
        "llm_review": {},
        "llm_rules_created": [],
    }
    if use_llm:
        try:
            llm_review = _llm_learning_review(settings, report)
            report["llm_review"] = llm_review
            report["llm_rules_created"] = _promote_llm_rules(store, llm_review)
            if report["llm_rules_created"]:
                report["shadow_evaluation"] = evaluate_shadow_rules(store, since_date=since_date, settings=settings)
                report["rules"] = store.strategy_rules(limit=200)
        except Exception as exc:  # noqa: BLE001
            report["llm_review"] = {"error": str(exc)}

    path = reports_dir / f"operational_learning_{run_id}.json"
    latest_path = reports_dir / "latest_operational_learning.json"
    report["path"] = str(path)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    latest_path.write_text(json.dumps(report, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    return report


def load_operational_learning_context(data_dir: Path) -> dict[str, Any]:
    path = data_dir / "reports" / "latest_operational_learning.json"
    if not path.exists():
        return {"available": False}
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"available": False, "warning": "latest_operational_learning.json invalido"}
    active_rules = [rule for rule in report.get("rules", []) if rule.get("status") == "active"]
    shadow_rules = [rule for rule in report.get("rules", []) if rule.get("status") == "shadow"]
    return {
        "available": True,
        "as_of": report.get("as_of"),
        "summary": report.get("summary", {}),
        "active_rules": active_rules[:10],
        "shadow_rules": shadow_rules[:10],
        "decision_summary": (report.get("summary", {}) or {}).get("decision_summary", {}),
        "learning_journal": report.get("learning_journal", [])[:8],
        "llm_review": report.get("llm_review", {}),
    }
