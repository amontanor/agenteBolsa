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


def _signal_context(store: Store, symbol: str) -> dict[str, Any]:
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
        signal = _signal_context(store, symbol)
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


def evaluate_shadow_rules(store: Store, *, since_date: str = DEFAULT_HISTORY_START_DATE) -> dict[str, Any]:
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
        updated_status = rule["status"]
        if rule["status"] == "rejected" and rule_metrics["cases"] < 10:
            updated_status = "shadow"
        if rule["status"] in {"shadow", "rejected"} and rule_metrics["cases"] >= 10:
            if rule_metrics["net_shadow_pl"] > 0 and rule_metrics["losses_blocked"] >= rule_metrics["gains_blocked"]:
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
    response = client.chat.completions.create(
        model=settings.openai_model,
        temperature=0.1,
        max_tokens=max(settings.llm_max_tokens or 0, 1800),
        messages=[
            {
                "role": "system",
                "content": (
                    "Eres un investigador cuantitativo post-operacion. Analiza memoria de trades y reglas shadow. "
                    "Devuelve JSON con assessment, what_worked, mistakes, candidate_rules y next_actions. "
                    "candidate_rules debe contener objetos con rule_id, name, description, condition, effect, confidence, evidence."
                ),
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=True, default=str)},
        ],
    )
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
    default_rules_created = ensure_default_shadow_rules(store)
    shadow_eval = evaluate_shadow_rules(store, since_date=since_date)
    memories = store.trade_memory(limit=500, since_date=since_date)
    rules = store.strategy_rules(limit=200)
    verdicts = Counter(memory.get("verdict") for memory in memories)
    by_symbol = Counter(memory.get("symbol") for memory in memories)
    summary = {
        "since_date": since_date,
        "trade_memories": len(memories),
        "rules_total": len(rules),
        "rules_shadow": sum(1 for rule in rules if rule["status"] == "shadow"),
        "rules_active": sum(1 for rule in rules if rule["status"] == "active"),
        "rules_rejected": sum(1 for rule in rules if rule["status"] == "rejected"),
        "verdicts": dict(verdicts),
        "top_symbols": dict(by_symbol.most_common(8)),
    }
    report: dict[str, Any] = {
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "memory_sync": memory_sync,
        "default_rules_created": default_rules_created,
        "shadow_evaluation": shadow_eval,
        "rules": rules,
        "recent_trade_memory": memories[:100],
        "llm_review": {},
        "llm_rules_created": [],
    }
    if use_llm:
        try:
            llm_review = _llm_learning_review(settings, report)
            report["llm_review"] = llm_review
            report["llm_rules_created"] = _promote_llm_rules(store, llm_review)
            if report["llm_rules_created"]:
                report["shadow_evaluation"] = evaluate_shadow_rules(store, since_date=since_date)
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
        "llm_review": report.get("llm_review", {}),
    }
