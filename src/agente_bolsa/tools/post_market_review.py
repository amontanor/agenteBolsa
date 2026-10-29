"""Post-market trade review and learning report."""

from __future__ import annotations

import copy
import json
import math
import sqlite3
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from agente_bolsa.config import Settings
from agente_bolsa.llm_router import chat_completion_with_fallback
from agente_bolsa.llm_usage import record_llm_response
from agente_bolsa.models import PortfolioSnapshot
from agente_bolsa.storage import Store

from .adaptive_tuning import promote_post_market_improvements
from .broker import BrokerClientFactory
from .daily_learning import build_learning_daily_run
from .operational_learning import build_operational_learning_review
from .reporting import write_json_report
from .signal_learning import build_learning_status, update_signal_outcomes, write_learning_report
from .trade_history import build_trade_history


def _round(value: float | int | None, precision: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), precision)


def _metric_number(value: Any) -> float | None:
    """Return finite numeric P/L data, preserving missing values as unavailable."""

    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _short(text: Any, max_chars: int = 280) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 3].rstrip() + "..."


def _latest_local_orders_by_symbol(history: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for order in history.get("local_broker_orders", []):
        result[str(order.get("symbol", "")).upper()].append(order)
    return result


_EXIT_ORIGINS = {
    "time_stop_v2": "automatic_time_stop",
    "stale_guard_v2": "automatic_stale_guard",
    "trailing_stop_v2": "automatic_trailing_stop",
    "partial_take_profit_v2": "automatic_partial_take_profit",
    "stop_loss": "stop_loss",
    "take_profit": "take_profit",
    "risk_exit": "risk_exit",
    "manual": "manual",
    "manual_exit": "manual",
}


def _order_payload(order: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    payload = order.get("payload") or {}
    plan = payload.get("plan") or {}
    plan_payload = plan.get("payload") or {}
    recommendation = plan_payload.get("recommendation") or {}
    lineage = (
        plan_payload.get("decision_lineage")
        or recommendation.get("decision_lineage")
        or {}
    )
    return plan_payload, recommendation, lineage, payload


def _exit_attribution(trade: dict[str, Any], order: dict[str, Any]) -> tuple[str | None, str, str | None]:
    plan_payload, _recommendation, _lineage, payload = _order_payload(order)
    checks = (plan_payload.get("risk_decision") or {}).get("checks") or {}
    trigger = (
        trade.get("exit_trigger")
        or order.get("exit_trigger")
        or payload.get("exit_trigger")
        or checks.get("trigger")
        or (checks.get("exit_policy_v2") or {}).get("trigger")
    )
    trigger_text = str(trigger or "").strip().lower() or None
    return trigger_text, _EXIT_ORIGINS.get(trigger_text or "", "unknown_exit_origin"), trigger_text


def _lineage_fields(order: dict[str, Any]) -> dict[str, Any]:
    plan_payload, recommendation, lineage, _payload = _order_payload(order)
    context = recommendation.get("decision_context_snapshot") or {}
    return {
        "order_plan_id": order.get("plan_id") or (order.get("payload") or {}).get("plan", {}).get("plan_id"),
        "recommendation_id": recommendation.get("recommendation_id") or plan_payload.get("recommendation_id"),
        "signal_id": lineage.get("signal_id") or context.get("signal_id"),
        "candidate_id": lineage.get("candidate_id"),
        "lineage_id": lineage.get("lineage_id"),
        "cycle_id": order.get("cycle_id") or lineage.get("cycle_id") or context.get("cycle_id"),
        "decision_source": lineage.get("decision_source") or context.get("decision_source"),
        "non_execution_reason": plan_payload.get("non_execution_reason"),
    }


def _position_by_symbol(portfolio: PortfolioSnapshot) -> dict[str, Any]:
    return {position.symbol.upper(): position for position in portfolio.positions}


def _evaluate_trade(
    trade: dict[str, Any],
    *,
    portfolio_positions: dict[str, Any],
    local_orders: dict[str, list[dict[str, Any]]],
    local_orders_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    symbol = str(trade["symbol"]).upper()
    side = trade["side"]
    position = portfolio_positions.get(symbol)
    order_id = str(trade.get("order_id") or "").strip()
    related_order = (local_orders_by_id or {}).get(order_id, {}) if order_id else {}
    if not related_order:
        candidates = [item for item in local_orders.get(symbol, []) if item.get("side") == side]
        # A symbol/date join is only safe when there is exactly one local
        # order.  Ambiguity is preserved as unavailable rather than guessed.
        related_order = candidates[0] if len(candidates) == 1 else {}
    stop_loss = trade.get("stop_loss") or related_order.get("stop_loss")
    take_profit = trade.get("take_profit") or related_order.get("take_profit")
    trigger, exit_origin, _ = _exit_attribution(trade, related_order)
    lineage = _lineage_fields(related_order)

    realized_pl = trade.get("realized_pl")
    open_pl = _round(getattr(position, "unrealized_pl", None), 2) if position else None
    open_plpc = _round(getattr(position, "unrealized_plpc", None), 4) if position else None
    verdict = "pendiente"
    issue = None
    if side == "buy" and position:
        if (position.unrealized_plpc or 0) > 0.002:
            verdict = "bien_de_momento"
        elif (position.unrealized_plpc or 0) < -0.005:
            verdict = "debil_de_momento"
            issue = "Entrada con perdida abierta relevante antes del cierre."
        else:
            verdict = "neutro_de_momento"
    elif side == "sell":
        if realized_pl is None:
            verdict = "venta_sin_pl_completo"
            issue = "No hay base completa de coste en el rango de fills."
        elif realized_pl >= 0:
            verdict = "venta_correcta"
        else:
            if exit_origin == "unknown_exit_origin":
                verdict = "venta_mejorable"
                issue = "Venta con perdida realizada; origen de salida desconocido."
            elif exit_origin == "manual":
                verdict = "venta_mejorable"
                issue = "Venta manual con perdida realizada."
            else:
                verdict = "venta_automatica_con_perdida"
                issue = f"Salida automatica ({exit_origin}) con perdida realizada."

    return {
        "time": trade["time"],
        "symbol": symbol,
        "side": side,
        "qty": trade["qty"],
        "price": trade["price"],
        "notional": trade["notional"],
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "realized_pl": realized_pl,
        "realized_plpc": trade.get("realized_plpc"),
        "open_pl": open_pl,
        "open_plpc": open_plpc,
        "verdict": verdict,
        "issue": issue,
        "broker_order_id": order_id or related_order.get("broker_order_id"),
        "order_plan_id": lineage.get("order_plan_id"),
        "recommendation_id": lineage.get("recommendation_id"),
        "signal_id": lineage.get("signal_id"),
        "candidate_id": lineage.get("candidate_id"),
        "lineage_id": lineage.get("lineage_id"),
        "cycle_id": lineage.get("cycle_id"),
        "decision_source": lineage.get("decision_source"),
        "non_execution_reason": lineage.get("non_execution_reason"),
        "exit_trigger": trigger,
        "exit_origin": exit_origin,
    }


def _canonical_trade_evaluations(
    evaluations: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Collapse fill/activity fragments to one evaluation per broker order.

    Rows without a broker order ID remain separate legacy rows: grouping them
    by symbol/date would invent an identity.  The raw fragment count remains
    visible for reconciliation and diagnostics.
    """

    grouped: dict[str, list[dict[str, Any]]] = {}
    legacy_rows: list[dict[str, Any]] = []
    for row in evaluations:
        broker_id = str(row.get("broker_order_id") or "").strip()
        if broker_id:
            grouped.setdefault(broker_id, []).append(row)
        else:
            legacy_rows.append(row)

    canonical: list[dict[str, Any]] = []
    duplicate_fragments = 0
    for broker_id, fragments in grouped.items():
        base = copy.deepcopy(fragments[0])
        duplicate_fragments += max(0, len(fragments) - 1)
        base["activity_count"] = len(fragments)
        base["activity_fragments"] = [
            {
                "time": item.get("time"),
                "qty": item.get("qty"),
                "price": item.get("price"),
                "notional": item.get("notional"),
                "realized_pl": item.get("realized_pl"),
            }
            for item in fragments
        ]
        base["duplicate_fragment_count"] = max(0, len(fragments) - 1)
        base["broker_order_id"] = broker_id
        if len(fragments) > 1:
            quantities = [float(item.get("qty") or 0.0) for item in fragments]
            notionals = [float(item.get("notional") or 0.0) for item in fragments]
            total_qty = sum(quantities)
            base["qty"] = round(total_qty, 6)
            base["notional"] = round(sum(notionals), 2)
            if total_qty > 0:
                base["price"] = round(
                    sum(float(item.get("price") or 0.0) * qty for item, qty in zip(fragments, quantities, strict=True))
                    / total_qty,
                    4,
                )
            realized = [item.get("realized_pl") for item in fragments if item.get("realized_pl") is not None]
            if realized:
                base["realized_pl"] = round(sum(float(value) for value in realized), 2)
        canonical.append(base)

    for row in legacy_rows:
        item = copy.deepcopy(row)
        item["activity_count"] = 1
        item["activity_fragments"] = []
        item["duplicate_fragment_count"] = 0
        item["lineage_status"] = "legacy_unverified"
        item["exit_origin"] = item.get("exit_origin") or "unknown_exit_origin"
        canonical.append(item)

    canonical.sort(key=lambda item: (str(item.get("time") or ""), str(item.get("broker_order_id") or "")))
    sells = [item for item in canonical if str(item.get("side") or "").lower() == "sell"]
    known_exit = [item for item in sells if item.get("exit_origin") not in {None, "unknown_exit_origin"}]
    origin_coverage = round(len(known_exit) / len(sells), 4) if sells else None
    metrics = {
        "broker_orders": len(grouped),
        "activity_fragments": len(evaluations),
        "canonical_trade_evaluations": len(canonical),
        "duplicate_fragment_count": duplicate_fragments,
        "exit_origin_coverage": origin_coverage,
        "automatic_exit_count": sum(1 for item in sells if str(item.get("exit_origin") or "").startswith("automatic_")),
        "manual_exit_count": sum(1 for item in sells if item.get("exit_origin") == "manual"),
        "unknown_exit_origin_count": sum(1 for item in sells if item.get("exit_origin") in {None, "unknown_exit_origin"}),
        "legacy_unverified_count": len(legacy_rows),
    }
    return canonical, metrics


def _llm_attribution_conflicts(
    evaluations: list[dict[str, Any]],
    llm_review: dict[str, Any] | None,
) -> int:
    """Count contradictory LLM exit labels without letting them mutate truth."""

    if not isinstance(llm_review, dict):
        return 0
    candidates = llm_review.get("exit_attributions") or llm_review.get("trade_evaluations") or []
    if not isinstance(candidates, list):
        return 0
    deterministic = {
        str(item.get("broker_order_id")): item
        for item in evaluations
        if item.get("broker_order_id")
    }
    conflicts = 0
    for item in candidates:
        if not isinstance(item, dict):
            continue
        order_id = str(item.get("broker_order_id") or "")
        expected = deterministic.get(order_id)
        if not expected:
            continue
        proposed = str(item.get("exit_trigger") or item.get("exit_origin") or "").strip().lower()
        actual = str(expected.get("exit_trigger") or expected.get("exit_origin") or "").strip().lower()
        if proposed and actual and proposed not in {actual, _EXIT_ORIGINS.get(actual, "")}:
            expected["llm_attribution_conflict"] = True
            conflicts += 1
    return conflicts


def _learning_candidates(
    evaluations: list[dict[str, Any]],
    day_summary: dict[str, Any],
    portfolio: PortfolioSnapshot,
) -> list[dict[str, Any]]:
    buys = [item for item in evaluations if item["side"] == "buy"]
    sells = [item for item in evaluations if item["side"] == "sell"]
    weak_buys = [item for item in buys if item["verdict"] == "debil_de_momento"]
    open_positions = len(portfolio.positions)
    suggestions: list[dict[str, Any]] = []

    if open_positions >= 6:
        suggestions.append(
            {
                "id": "limit_daily_entries",
                "type": "risk_parameter",
                "priority": "high",
                "proposal": "Limitar nuevas compras por sesion o reducir MAX_ORDERS_PER_CYCLE.",
                "reason": f"La cartera termino con {open_positions} posiciones abiertas; puede ser demasiada rotacion/dispersion para paper intradia.",
                "suggested_config": {"MAX_ORDERS_PER_CYCLE": 2},
                "auto_apply": False,
            }
        )
    if weak_buys:
        suggestions.append(
            {
                "id": "raise_entry_threshold_after_weak_buys",
                "type": "selection_parameter",
                "priority": "medium",
                "proposal": "Subir temporalmente la exigencia de confianza o score cuando varias entradas cierran en negativo.",
                "reason": f"{len(weak_buys)} compra(s) terminaron debiles al cierre.",
                "suggested_config": {"MIN_LLM_CONFIDENCE_TO_TRADE": 0.70},
                "auto_apply": False,
            }
        )
    if sells:
        non_stop_sells = [
            item
            for item in sells
            if item.get("exit_origin") in {None, "unknown_exit_origin", "manual"}
        ]
        if non_stop_sells:
            suggestions.append(
                {
                    "id": "prefer_stop_take_exits",
                    "type": "exit_policy",
                    "priority": "high",
                    "proposal": "Mantener la politica actual: salida normal solo por stop_loss/take_profit, no por rotacion ordinaria.",
                    "reason": "Hubo ventas durante la sesion; las salidas deben auditarse contra stop/take antes de permitir rotaciones.",
                    "auto_apply": False,
                }
            )

    realized = _metric_number(day_summary.get("realized_pl"))
    unrealized = _metric_number(day_summary.get("open_unrealized_pl"))
    if (realized is not None and realized < 0) or (unrealized is not None and unrealized < 0):
        suggestions.append(
            {
                "id": "add_entry_quality_filters",
                "type": "technical_analysis",
                "priority": "medium",
                "proposal": "Investigar filtro adicional: no comprar RSI extremo salvo confirmacion de volumen/noticias y fuerza relativa.",
                "reason": f"P/L realizado {realized}, P/L abierto {unrealized}; conviene reducir entradas extendidas.",
                "candidate_filters": ["RSI extremo", "volumen relativo", "fuerza relativa 20d", "noticias negativas"],
                "auto_apply": False,
            }
        )
    return suggestions


def _load_recent_learning(data_dir: Path) -> dict[str, Any]:
    path = data_dir / "reports" / "latest_post_market_learning.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def load_post_market_learning_context(data_dir: Path) -> dict[str, Any]:
    learning = _load_recent_learning(data_dir)
    if not learning:
        return {"available": False}
    return {
        "available": True,
        "as_of": learning.get("as_of"),
        "session_date": learning.get("session_date"),
        "summary": learning.get("summary", {}),
        "active_guidance": learning.get("next_session_guidance", [])[:8],
        "proposed_improvements": learning.get("proposed_improvements", [])[:8],
    }


def _llm_review(settings: Settings, report: dict[str, Any]) -> dict[str, Any]:
    prompt = {
        "session_date": report["session_date"],
        "summary": report["summary"],
        "trade_evaluations": report["trade_evaluations"][:40],
        "trade_decisions": (report.get("operational_learning", {}) or {}).get("trade_decisions", [])[:30],
        "learning_journal": (report.get("operational_learning", {}) or {}).get("learning_journal", []),
        "proposed_improvements": report["proposed_improvements"],
        "constraints": [
            "No propongas cambios grandes.",
            "No actives live trading.",
            "Prioriza salida por stop_loss/take_profit.",
            "Las mejoras deben ser concretas, medibles y reversibles.",
        ],
    }
    messages = [
        {
            "role": "system",
            "content": (
                "Eres un analista post-mercado. Evalua si las entradas/salidas fueron "
                "buenas decisiones con los datos dados. Devuelve solo JSON con: "
                "assessment, mistakes, what_worked, next_session_guidance, "
                "minimal_improvements. No inventes precios."
            ),
        },
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=True)},
    ]
    response, endpoint, _attempts = chat_completion_with_fallback(
        settings,
        messages=messages,
        temperature=0.1,
        max_tokens=max(settings.llm_max_tokens or 0, 1800),
    )
    record_llm_response(settings, "post_market_review", response, prompt=messages, endpoint=endpoint)
    text = response.choices[0].message.content or "{}"
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict):
                return _normalize_llm_review(parsed)
        except json.JSONDecodeError:
            pass
    return {"assessment": _short(text, 1200), "parse_warning": "LLM no devolvio JSON valido."}


def _normalize_llm_review(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep LLM auto-apply flags as requests, never as authorization."""

    normalized = dict(payload)
    improvements = payload.get("minimal_improvements")
    if not isinstance(improvements, list):
        return normalized
    rows: list[dict[str, Any]] = []
    for raw in improvements:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        if "auto_apply" in item:
            item["requested_auto_apply"] = item.pop("auto_apply")
        item["authorized_auto_apply"] = False
        rows.append(item)
    normalized["minimal_improvements"] = rows
    return normalized


def _build_trade_evaluations(
    portfolio: PortfolioSnapshot,
    history: dict[str, Any],
    target_date: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    local_orders = _latest_local_orders_by_symbol(history)
    local_orders_by_id = {
        str(item.get("broker_order_id")): item
        for item in history.get("local_broker_orders", [])
        if item.get("broker_order_id")
    }
    positions = _position_by_symbol(portfolio)
    trades = [item for item in history.get("trades", []) if item.get("date") == target_date]
    evaluations = [
        _evaluate_trade(
            item,
            portfolio_positions=positions,
            local_orders=local_orders,
            local_orders_by_id=local_orders_by_id,
        )
        for item in trades
    ]
    day = next((item for item in history.get("days", []) if item.get("date") == target_date), {})
    return _canonical_trade_evaluations(evaluations)[0], day


def _session_event_payloads(store: Store, session_date: str) -> list[dict[str, Any]]:
    with store.connect() as conn:
        rows = conn.execute(
            """
            SELECT payload_json, cycle_id
            FROM agent_events
            WHERE event_type = 'paper_auto_trade_completed'
              AND substr(created_at, 1, 10) = ?
            ORDER BY created_at ASC
            """,
            (session_date,),
        ).fetchall()
    payloads: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            payload = {}
        if isinstance(payload, dict):
            payload["__event_cycle_id"] = row["cycle_id"]
            payloads.append(payload)
    return payloads


def _is_exact_identity(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text) and "UNKNOWN" not in text.upper()


def _session_candidate_attribution(
    store: Store,
    session_date: str,
    evaluations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the mandatory session ledger from persisted decisions, not cohorts.

    ``learning_experiment`` is intentionally included.  Legacy placeholders
    are retained as raw evidence but never promoted to a verified candidate.
    """

    reader = getattr(store, "iter_trade_recommendations", None)
    incoming = reader(limit=100000) if callable(reader) else store.trade_recommendations(limit=100000)
    recommendations = []
    try:
        for item in incoming:
            payload = item.get("payload") or {}
            lineage = payload.get("decision_lineage") or {}
            if str(item.get("created_at") or "")[:10] == session_date or session_date in str(lineage.get("signal_id") or ""):
                recommendations.append({
                    key: item.get(key) for key in ("recommendation_id", "cycle_id", "symbol", "action")
                } | {"payload": {"decision_lineage": {
                    key: lineage[key] for key in ("candidate_id", "signal_id") if key in lineage
                }}})
    finally:
        close = getattr(incoming, "close", None)
        if callable(close):
            close()
    rec_by_key: dict[str, dict[str, Any]] = {}
    legacy_rec_count = 0
    for item in recommendations:
        payload = item.get("payload") or {}
        lineage = payload.get("decision_lineage") or {}
        key = str(item.get("recommendation_id") or "").strip()
        if not key:
            key = str(lineage.get("candidate_id") or lineage.get("signal_id") or "").strip()
        if not key:
            # A cycle-aware fallback keeps duplicates apart without inventing
            # a candidate identity; it is explicitly legacy/unverified.
            key = "legacy:" + "|".join(
                [str(item.get("cycle_id") or ""), str(item.get("symbol") or ""), str(item.get("action") or "")]
            )
            legacy_rec_count += 1
        rec_by_key.setdefault(key, item)

    events = _session_event_payloads(store, session_date)
    rejected_raw: list[dict[str, Any]] = []
    for payload in events:
        for item in (payload.get("rejected_order_plans") or []):
            if not isinstance(item, dict):
                continue
            enriched = dict(item)
            enriched["_event_cycle_id"] = payload.get("__event_cycle_id")
            rejected_raw.append(enriched)
    rejected_by_key: dict[str, dict[str, Any]] = {}
    legacy_rejected = 0
    for item in rejected_raw:
        payload = item.get("payload") or {}
        lineage = item.get("decision_lineage") or payload.get("decision_lineage") or {}
        key = str(item.get("plan_id") or item.get("recommendation_id") or lineage.get("candidate_id") or "").strip()
        if not key:
            key = "|".join(
                [
                    str(item.get("cycle_id") or item.get("_event_cycle_id") or ""),
                    str(item.get("symbol") or "").upper(),
                    str(item.get("stage") or ""),
                    str(item.get("reason") or ""),
                ]
            )
            legacy_rejected += 1
        rejected_by_key.setdefault(key, item)

    executed_ids = {
        str(item.get("recommendation_id") or "")
        for item in evaluations
        if item.get("recommendation_id")
    }
    executed_order_ids = {
        str(item.get("broker_order_id") or "")
        for item in evaluations
        if item.get("broker_order_id")
    }
    non_executed = 0
    unavailable_identity = legacy_rec_count + legacy_rejected
    for item in rec_by_key.values():
        recommendation_id = str(item.get("recommendation_id") or "")
        if recommendation_id and recommendation_id not in executed_ids:
            non_executed += 1
        elif not recommendation_id:
            unavailable_identity += 1

    candidate_signals = set()
    cycles = set()
    for item in rec_by_key.values():
        cycles.add(str(item.get("cycle_id") or ""))
        lineage = (item.get("payload") or {}).get("decision_lineage") or {}
        signal_id = lineage.get("signal_id")
        if _is_exact_identity(signal_id):
            candidate_signals.add(str(signal_id))
        elif signal_id:
            unavailable_identity += 1

    return {
        "source": "trade_recommendations+paper_auto_trade_completed",
        "learning_experiment_included": True,
        "recommendations_raw": len(recommendations),
        "recommendations_unique": len(rec_by_key),
        "cycles_unique": len({item for item in cycles if item}),
        "candidate_signals_unique": len(candidate_signals) if candidate_signals else None,
        "rejected_plans_raw": len(rejected_raw),
        "rejected_plans_unique": len(rejected_by_key),
        "executed_treatments": len(executed_order_ids),
        "non_executed_candidates": non_executed,
        "blocked_candidates": len(rejected_by_key),
        "unavailable_identity_count": unavailable_identity,
        "legacy_unverified_count": legacy_rec_count + legacy_rejected,
        "raw_recommendations": [
            {"recommendation_id": item.get("recommendation_id"), "cycle_id": item.get("cycle_id"), "symbol": item.get("symbol")}
            for item in recommendations
        ],
        "rejected_plans": list(rejected_by_key.values()),
    }


def _execution_metrics_from_canonical(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    broker_ids = {str(item.get("broker_order_id")) for item in evaluations if item.get("broker_order_id")}
    fragments = sum(max(1, int(item.get("activity_count") or 1)) for item in evaluations)
    sells = [item for item in evaluations if str(item.get("side") or "").lower() == "sell"]
    known = [item for item in sells if item.get("exit_origin") not in {None, "unknown_exit_origin"}]
    return {
        "broker_orders": len(broker_ids),
        "activity_fragments": fragments,
        "canonical_trade_evaluations": len(evaluations),
        "duplicate_fragment_count": sum(max(0, int(item.get("activity_count") or 1) - 1) for item in evaluations),
        "exit_origin_coverage": round(len(known) / len(sells), 4) if sells else None,
        "automatic_exit_count": sum(1 for item in sells if str(item.get("exit_origin") or "").startswith("automatic_")),
        "manual_exit_count": sum(1 for item in sells if item.get("exit_origin") == "manual"),
        "unknown_exit_origin_count": sum(1 for item in sells if item.get("exit_origin") in {None, "unknown_exit_origin"}),
        "legacy_unverified_count": sum(1 for item in evaluations if item.get("lineage_status") == "legacy_unverified"),
    }


def _attribution_status(execution: dict[str, Any], candidates: dict[str, Any]) -> str:
    if not execution and not candidates:
        return "unavailable"
    if not int(execution.get("canonical_trade_evaluations") or 0) and not int(candidates.get("recommendations_raw") or 0):
        return "collecting"
    if (
        int(execution.get("llm_attribution_conflicts") or 0)
        or int(execution.get("unknown_exit_origin_count") or 0)
        or int(execution.get("legacy_unverified_count") or 0)
        or int(candidates.get("unavailable_identity_count") or 0)
    ):
        return "degraded_attribution"
    return "healthy"


def _immature_outcome_count(store: Store, session_date: str) -> int | None:
    try:
        with store.connect() as conn:
            rows = conn.execute(
                "SELECT outcome_json FROM signal_outcomes WHERE signal_date = ?",
                (session_date,),
            ).fetchall()
    except Exception:  # noqa: BLE001 - diagnostic metric must not block review.
        return None
    count = 0
    for row in rows:
        try:
            outcome = json.loads(row["outcome_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            outcome = {}
        matured = outcome.get("matured_horizons") or {}
        if not any(bool(value) for value in matured.values()) and not any(
            outcome.get(f"return_{h}d") is not None for h in (1, 3, 5, 10)
        ):
            count += 1
    return count


def _mandatory_market_review(
    report: dict[str, Any],
    session_ledger: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministic post-market checklist required for every session close."""

    summary = report.get("summary", {}) or {}
    evaluations = list(report.get("trade_evaluations", []) or [])
    daily_digest = ((report.get("daily_learning", {}) or {}).get("digest", {}) or {})
    ledger = daily_digest.get("same_session_opportunity_ledger", {}) or {}
    canonical_ledger = session_ledger or {}
    operational = report.get("operational_learning", {}) or {}
    traceability = operational.get("traceability_audit", {}) or {}
    reconciliation = operational.get("broker_memory_reconciliation", {}) or {}

    winners = [
        item
        for item in evaluations
        if str(item.get("verdict") or "") in {"bien_de_momento", "venta_correcta"}
        or (_round(item.get("realized_pl"), 2) or 0.0) > 0
        or (_round(item.get("open_pl"), 2) or 0.0) > 0
    ]
    weak = [item for item in evaluations if item.get("issue") or str(item.get("verdict") or "").startswith("debil")]
    missed = [
        item
        for item in list(ledger.get("top_non_executed", []) or [])
        if item.get("same_session_return") is not None and float(item.get("same_session_return") or 0.0) > 0
    ]
    blocker_reasons: dict[str, int] = {}
    for item in list(ledger.get("top_non_executed", []) or []):
        reason = str(item.get("reason_not_executed") or "unknown")
        blocker_reasons[reason] = blocker_reasons.get(reason, 0) + 1
    if canonical_ledger:
        blocker_reasons = {}
        for item in canonical_ledger.get("rejected_plans", []) or []:
            reason = str(item.get("reason") or item.get("rejection_reason") or "unknown")
            blocker_reasons[reason] = blocker_reasons.get(reason, 0) + 1
        # Forward opportunities are not inferred from a cohort that excluded
        # learning_experiment; the canonical ledger reports availability only.
        missed = []

    data_failures = []
    if traceability and not traceability.get("complete", True):
        data_failures.append(
            {
                "kind": "trade_memory_traceability",
                "detail": "Memoria de trades con trazabilidad incompleta.",
                "evidence": traceability.get("issue_counts", {}),
            }
        )
    if reconciliation and not reconciliation.get("complete", True):
        data_failures.append(
            {
                "kind": "broker_memory_reconciliation",
                "detail": "Broker y trade_memory no cuadran completamente.",
                "evidence": reconciliation.get("issue_counts", {}),
            }
        )
    if int((report.get("signal_update", {}) or {}).get("updated") or 0) == 0:
        data_failures.append(
            {
                "kind": "signal_outcomes_not_updated",
                "detail": "No se actualizaron outcomes de senales en este post-market.",
                "evidence": report.get("signal_update", {}),
            }
        )

    criteria_failures = []
    if weak:
        criteria_failures.append(
            {
                "kind": "weak_executed_trades",
                "detail": "Entradas/salidas ejecutadas con resultado o issue debil.",
                "count": len(weak),
                "examples": weak[:5],
            }
        )
    if missed:
        criteria_failures.append(
            {
                "kind": "positive_non_executed_opportunities",
                "detail": "Candidatos no ejecutados tuvieron retorno intradia positivo.",
                "count": len(missed),
                "examples": missed[:5],
            }
        )

    ledger_summary = ledger.get("summary", {}) if isinstance(ledger, dict) else {}
    if canonical_ledger:
        ledger_summary = {
            "candidates": canonical_ledger.get("recommendations_unique"),
            "non_executed": canonical_ledger.get("non_executed_candidates"),
        }
    return {
        "required": True,
        "session_date": report.get("session_date"),
        "recommendations_reviewed": {
            "trade_evaluations": summary.get("trades_evaluated", 0),
            "daily_candidates": ledger_summary.get("candidates"),
            "non_executed_candidates": ledger_summary.get("non_executed"),
            **(
                {
                    "recommendations_raw": canonical_ledger.get("recommendations_raw"),
                    "recommendations_unique": canonical_ledger.get("recommendations_unique"),
                    "cycles_unique": canonical_ledger.get("cycles_unique"),
                    "candidate_signals_unique": canonical_ledger.get("candidate_signals_unique"),
                    "rejected_plans_raw": canonical_ledger.get("rejected_plans_raw"),
                    "rejected_plans_unique": canonical_ledger.get("rejected_plans_unique"),
                    "executed_treatments": canonical_ledger.get("executed_treatments"),
                    "blocked_candidates": canonical_ledger.get("blocked_candidates"),
                    "unavailable_identity_count": canonical_ledger.get("unavailable_identity_count"),
                }
                if canonical_ledger
                else {}
            ),
        },
        "execution_review": {
            "buys": summary.get("buys", 0),
            "sells": summary.get("sells", 0),
            "day_realized_pl": summary.get("day_realized_pl", 0.0),
            "open_unrealized_pl": summary.get("open_unrealized_pl", 0.0),
        },
        "blockers_review": {
            "reason_counts": blocker_reasons,
            "top_blocked": list(ledger.get("top_non_executed", []) or [])[:10] if isinstance(ledger, dict) else [],
        },
        "what_worked": winners[:10],
        "what_failed_due_to_data": data_failures,
        "what_failed_due_to_criteria": criteria_failures,
        "proposed_improvements": list(report.get("proposed_improvements", []) or [])[:10],
    }


def _build_learning_pipeline(
    settings: Settings,
    store: Store,
    reports_dir: Path,
    run_id: str,
    target_date: str,
    stage_recorder: Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if stage_recorder:
        stage_recorder("outcome_update", "started")
    outcome_update_deferred = False
    try:
        signal_update = update_signal_outcomes(settings, store, since_date="2026-04-01", limit=200000)
    except sqlite3.OperationalError as exc:
        # P-L163: una contencion de SQLite no puede tumbar el informe completo.
        # Los outcomes se recalculan de forma idempotente en la siguiente pasada.
        if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
            raise
        outcome_update_deferred = True
        if stage_recorder:
            stage_recorder("outcome_update", "failed", error=repr(exc))
        signal_update = {
            "updated": 0,
            "signals": 0,
            "symbols": 0,
            "warnings": ["outcome_update_locked"],
            "deferred": True,
            "error": type(exc).__name__,
        }
    except Exception as exc:
        if stage_recorder:
            stage_recorder("outcome_update", "failed", error=repr(exc))
        raise
    if stage_recorder and not outcome_update_deferred:
        stage_recorder("outcome_update", "completed")
    signal_learning = build_learning_status(store, since_date="2026-04-01", limit=200000)
    if stage_recorder:
        stage_recorder("daily_learning", "started")
    try:
        daily_learning = build_learning_daily_run(
            settings,
            store,
            reports_dir,
            f"{run_id}_daily",
            since_date="2026-04-01",
            end_date=target_date,
            compact=True,
            update_result=signal_update,
        )
    except Exception as exc:
        if stage_recorder:
            stage_recorder("daily_learning", "failed", error=repr(exc))
        raise
    if stage_recorder:
        stage_recorder("daily_learning", "completed")
    return signal_update, signal_learning, daily_learning


_PORTFOLIO_UNSET = object()
_BROKER_UNSET = object()


def build_post_market_review(
    settings: Settings,
    reports_dir: Path,
    run_id: str,
    *,
    session_date: str | None = None,
    use_llm: bool = True,
    portfolio_snapshot: PortfolioSnapshot | None | object = _PORTFOLIO_UNSET,
    broker_client: Any | object = _BROKER_UNSET,
    stage_recorder: Any | None = None,
) -> dict[str, Any]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    timings: dict[str, float] = {}

    started = time.perf_counter()
    if portfolio_snapshot is _PORTFOLIO_UNSET:
        broker = BrokerClientFactory(settings) if broker_client is _BROKER_UNSET else broker_client
        broker_client = broker
        portfolio = broker.alpaca_portfolio_snapshot()
    else:
        portfolio = portfolio_snapshot
    if portfolio is None:
        raise RuntimeError("post_market_portfolio_unavailable")
    timings["portfolio_snapshot_seconds"] = round(time.perf_counter() - started, 3)

    started = time.perf_counter()
    history = build_trade_history(
        settings,
        limit=100,
        portfolio_snapshot=portfolio,
        broker_client=broker_client,
    )
    timings["trade_history_seconds"] = round(time.perf_counter() - started, 3)
    today = datetime.now(ZoneInfo(settings.local_timezone)).date().isoformat()
    target_date = session_date or today

    started = time.perf_counter()
    evaluations, day = _build_trade_evaluations(portfolio, history, target_date)
    timings["trade_evaluation_seconds"] = round(time.perf_counter() - started, 3)
    proposed = _learning_candidates(evaluations, day, portfolio)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    execution_attribution = _execution_metrics_from_canonical(evaluations)
    session_ledger = _session_candidate_attribution(store, target_date, evaluations)
    started = time.perf_counter()
    signal_update, signal_learning, daily_learning = _build_learning_pipeline(
        settings,
        store,
        reports_dir,
        run_id,
        target_date,
        stage_recorder=stage_recorder,
    )
    timings["learning_pipeline_seconds"] = round(time.perf_counter() - started, 3)
    summary = {
        "trades_evaluated": len(evaluations),
        "buys": sum(1 for item in evaluations if item["side"] == "buy"),
        "sells": sum(1 for item in evaluations if item["side"] == "sell"),
        "open_positions": len(portfolio.positions),
        "day_buy_notional": day.get("buy_notional", 0.0),
        "day_sell_notional": day.get("sell_notional", 0.0),
        "day_realized_pl": day.get("realized_pl", 0.0),
        "day_realized_plpc": day.get("realized_plpc", 0.0),
        "open_unrealized_pl": history.get("summary", {}).get("unrealized_pl", 0.0),
        "signal_outcomes_updated": signal_update.get("updated", 0),
        "canonical_trade_evaluations": execution_attribution["canonical_trade_evaluations"],
    }
    report: dict[str, Any] = {
        "run_id": run_id,
        "as_of": datetime.now(ZoneInfo(settings.local_timezone)).isoformat(),
        "session_date": target_date,
        "summary": summary,
        "trade_evaluations": evaluations,
        "execution_attribution": execution_attribution,
        "candidate_attribution": session_ledger,
        "immature_outcome_count": _immature_outcome_count(store, target_date),
        "proposed_improvements": proposed,
        "signal_learning": signal_learning,
        "signal_update": signal_update,
        "daily_learning": {
            "path": daily_learning.get("path"),
            "health": daily_learning.get("health", {}),
            "digest": daily_learning.get("digest", {}),
            "policy_candidates": daily_learning.get("policy_candidates", []),
        },
        "next_session_guidance": [
            "Mantener posiciones hasta stop_loss/take_profit salvo deterioro excepcional.",
            "No rotar por score superior si la posicion no invalido la tesis.",
            "Evitar ampliar una posicion si ya esta cerca del limite por activo.",
        ],
        "pipeline_steps": timings,
        "llm_review": {},
    }
    if use_llm:
        try:
            started = time.perf_counter()
            llm = _llm_review(settings, report)
            timings["llm_review_seconds"] = round(time.perf_counter() - started, 3)
            report["llm_review"] = llm
            if isinstance(llm.get("next_session_guidance"), list):
                report["next_session_guidance"] = [
                    *report["next_session_guidance"],
                    *[str(item) for item in llm["next_session_guidance"][:5]],
                ]
        except Exception as exc:  # noqa: BLE001 - deterministic report is still valid.
            report["llm_review"] = {"error": str(exc)}

    report["execution_attribution"]["llm_attribution_conflicts"] = _llm_attribution_conflicts(
        report["trade_evaluations"], report.get("llm_review")
    )
    report["post_market_attribution_status"] = _attribution_status(
        report["execution_attribution"], report["candidate_attribution"]
    )

    report["operational_learning"] = build_operational_learning_review(
        settings,
        store,
        reports_dir,
        f"{run_id}_ops",
        since_date="2026-04-01",
        use_llm=use_llm,
    )
    report["auto_promotions"] = promote_post_market_improvements(settings, report)
    report["next_session_guidance"] = [
        *report["next_session_guidance"],
        *[
            str(item)
            for item in ((daily_learning.get("digest", {}) or {}).get("guidance", []) or [])[:5]
        ],
    ]
    report["mandatory_market_review"] = _mandatory_market_review(report, session_ledger)

    report = write_json_report(
        report,
        reports_dir,
        f"post_market_review_{target_date}",
        run_id,
        latest_filename="latest_post_market_learning.json",
        manifest={
            "pipeline_steps": timings,
            "signal_update": signal_update,
            "daily_learning_path": daily_learning.get("path"),
        },
    )
    if stage_recorder:
        stage_recorder("postmarket_report", "completed")
    write_learning_report(
        {
            "as_of": report["as_of"],
            "session_date": target_date,
            "update": signal_update,
            **signal_learning,
        },
        reports_dir,
        run_id,
    )
    return report
