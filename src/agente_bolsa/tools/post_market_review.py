"""Post-market trade review and learning report."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import time
from typing import Any
from zoneinfo import ZoneInfo

from openai import OpenAI

from agente_bolsa.config import Settings
from agente_bolsa.llm_usage import record_llm_response
from agente_bolsa.models import PortfolioSnapshot
from agente_bolsa.storage import Store

from .broker import BrokerClientFactory
from .adaptive_tuning import promote_post_market_improvements
from .daily_learning import build_learning_daily_run
from .operational_learning import build_operational_learning_review
from .reporting import write_json_report
from .signal_learning import build_learning_status, update_signal_outcomes, write_learning_report
from .trade_history import build_trade_history


def _round(value: float | int | None, precision: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), precision)


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


def _position_by_symbol(portfolio: PortfolioSnapshot) -> dict[str, Any]:
    return {position.symbol.upper(): position for position in portfolio.positions}


def _evaluate_trade(
    trade: dict[str, Any],
    *,
    portfolio_positions: dict[str, Any],
    local_orders: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    symbol = str(trade["symbol"]).upper()
    side = trade["side"]
    position = portfolio_positions.get(symbol)
    related_order = next((item for item in local_orders.get(symbol, []) if item.get("side") == side), {})
    stop_loss = trade.get("stop_loss") or related_order.get("stop_loss")
    take_profit = trade.get("take_profit") or related_order.get("take_profit")

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
            verdict = "venta_mejorable"
            issue = "Venta con perdida realizada."

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
    }


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
            if not str(item.get("issue") or "").lower().find("stop") >= 0
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

    realized = day_summary.get("realized_pl", 0.0)
    unrealized = day_summary.get("open_unrealized_pl", 0.0)
    if realized < 0 or unrealized < 0:
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
    client = OpenAI(
        api_key=settings.openai_api_key or "local-llama",
        base_url=settings.openai_api_base,
        timeout=settings.llm_timeout_seconds,
    )
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
    response = client.chat.completions.create(
        model=settings.openai_model,
        temperature=0.1,
        max_tokens=max(settings.llm_max_tokens or 0, 1800),
        messages=messages,
    )
    record_llm_response(settings, "post_market_review", response, prompt=messages)
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


def _build_trade_evaluations(
    portfolio: PortfolioSnapshot,
    history: dict[str, Any],
    target_date: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    local_orders = _latest_local_orders_by_symbol(history)
    positions = _position_by_symbol(portfolio)
    trades = [item for item in history.get("trades", []) if item.get("date") == target_date]
    evaluations = [
        _evaluate_trade(item, portfolio_positions=positions, local_orders=local_orders)
        for item in trades
    ]
    day = next((item for item in history.get("days", []) if item.get("date") == target_date), {})
    return evaluations, day


def _build_learning_pipeline(
    settings: Settings,
    store: Store,
    reports_dir: Path,
    run_id: str,
    target_date: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    signal_update = update_signal_outcomes(settings, store, since_date="2026-04-01", limit=200000)
    signal_learning = build_learning_status(store, since_date="2026-04-01", limit=200000)
    daily_learning = build_learning_daily_run(
        settings,
        store,
        reports_dir,
        f"{run_id}_daily",
        since_date="2026-04-01",
        end_date=target_date,
        compact=True,
    )
    return signal_update, signal_learning, daily_learning


def build_post_market_review(
    settings: Settings,
    reports_dir: Path,
    run_id: str,
    *,
    session_date: str | None = None,
    use_llm: bool = True,
) -> dict[str, Any]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    timings: dict[str, float] = {}

    started = time.perf_counter()
    portfolio = BrokerClientFactory(settings).alpaca_portfolio_snapshot()
    timings["portfolio_snapshot_seconds"] = round(time.perf_counter() - started, 3)

    started = time.perf_counter()
    history = build_trade_history(settings, limit=100)
    timings["trade_history_seconds"] = round(time.perf_counter() - started, 3)
    today = datetime.now(ZoneInfo(settings.local_timezone)).date().isoformat()
    target_date = session_date or today

    started = time.perf_counter()
    evaluations, day = _build_trade_evaluations(portfolio, history, target_date)
    timings["trade_evaluation_seconds"] = round(time.perf_counter() - started, 3)
    proposed = _learning_candidates(evaluations, day, portfolio)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    started = time.perf_counter()
    signal_update, signal_learning, daily_learning = _build_learning_pipeline(
        settings,
        store,
        reports_dir,
        run_id,
        target_date,
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
    }
    report: dict[str, Any] = {
        "run_id": run_id,
        "as_of": datetime.now(ZoneInfo(settings.local_timezone)).isoformat(),
        "session_date": target_date,
        "summary": summary,
        "trade_evaluations": evaluations,
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
