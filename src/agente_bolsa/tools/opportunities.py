"""Opportunity snapshot builders and ranking helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from agente_bolsa.config import Settings
from agente_bolsa.models import PortfolioSnapshot
from agente_bolsa.storage import Store
from agente_bolsa.tools.broker import BrokerClientFactory
from agente_bolsa.tools.daily_learning import load_daily_learning_context
from agente_bolsa.tools.operational_health import load_operational_response_context
from agente_bolsa.tools.trade_decision import _annotate_technical_context_with_learning


def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_opportunity_snapshot_times(raw: str) -> list[str]:
    values = []
    seen: set[str] = set()
    for item in str(raw or "").split(","):
        text = item.strip()
        if not text:
            continue
        parts = text.split(":")
        if len(parts) != 2:
            raise ValueError(f"Horario invalido: {text}")
        hour, minute = parts
        normalized = f"{int(hour):02d}:{int(minute):02d}"
        dt = datetime.strptime(normalized, "%H:%M")
        value = dt.strftime("%H:%M")
        if value in seen:
            continue
        seen.add(value)
        values.append(value)
    if not values:
        raise ValueError("OPPORTUNITY_SNAPSHOT_TIMES_LOCAL no contiene horarios validos.")
    return values


def empty_portfolio_snapshot() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        account_id="unavailable",
        status="unavailable",
        currency="USD",
        cash=0.0,
        portfolio_value=0.0,
        buying_power=0.0,
        positions=[],
        open_orders=[],
    )


def opportunity_sort_key(candidate: dict[str, Any]) -> tuple[float, float, float]:
    return (
        _num(candidate.get("selection_score")) or float("-inf"),
        _num(candidate.get("rank_priority_score")) or float("-inf"),
        _num(candidate.get("score")) or float("-inf"),
    )


def opportunity_candidates(technical_context: dict[str, Any], *, limit: int = 20) -> list[dict[str, Any]]:
    rows = []
    seen: set[str] = set()
    for candidate in [
        *(technical_context.get("selected_candidates", []) or []),
        *(technical_context.get("top_longs", []) or []),
        *(technical_context.get("all_candidates", []) or []),
    ]:
        if not isinstance(candidate, dict):
            continue
        symbol = str(candidate.get("symbol") or "").upper().strip()
        if not symbol or symbol in seen:
            continue
        if str(candidate.get("direction") or "").lower() != "long":
            continue
        rows.append(candidate)
        seen.add(symbol)
    rows.sort(key=opportunity_sort_key, reverse=True)
    return rows[:limit]


def opportunity_risk_plan(candidate: dict[str, Any]) -> dict[str, Any]:
    risk_plan = candidate.get("risk_plan", {}) or {}
    entry = _num(risk_plan.get("entry_price"))
    close = _num((candidate.get("technical_state", {}) or {}).get("close"))
    stop = _num(risk_plan.get("stop_loss"))
    take = _num(risk_plan.get("take_profit"))
    reward_risk = _num(risk_plan.get("reward_risk"))
    if reward_risk is None and entry is not None and stop is not None and take is not None and entry > stop:
        reward_risk = round((take - entry) / (entry - stop), 2)
    return {
        "entry_price": entry if entry is not None else close,
        "current_price": close if close is not None else entry,
        "stop_loss": stop,
        "take_profit": take,
        "reward_risk": reward_risk,
        "invalidation": risk_plan.get("invalidation"),
        "time_stop": risk_plan.get("time_stop"),
    }


def opportunity_score(candidate: dict[str, Any]) -> float | None:
    for key in ("selection_score", "rank_priority_score", "score"):
        value = _num(candidate.get(key))
        if value is not None:
            return round(value, 4)
    return None


def opportunity_entry_risk(candidate: dict[str, Any]) -> dict[str, Any]:
    technical = candidate.get("technical_state", {}) or {}
    rsi = _num(technical.get("rsi_14"))
    ret_5d = _num(technical.get("return_5d"))
    ret_20d = _num(technical.get("return_20d"))
    volume_z = _num(technical.get("volume_zscore_20"))
    close_position = _num(technical.get("close_position_in_range"))
    flags = []
    if rsi is not None and rsi >= 80:
        flags.append("RSI muy alto")
    elif rsi is not None and rsi >= 76:
        flags.append("RSI elevado")
    if ret_5d is not None and ret_5d >= 0.15:
        flags.append("subida 5d muy fuerte")
    if ret_20d is not None and ret_20d >= 0.30:
        flags.append("subida 20d muy fuerte")
    if volume_z is not None and volume_z < 0:
        flags.append("volumen relativo debil")
    if close_position is not None and close_position >= 0.90:
        flags.append("cierre en extremo del rango")

    strong_chase = (
        (rsi is not None and rsi >= 80)
        or (ret_5d is not None and ret_5d >= 0.15)
        or (ret_20d is not None and ret_20d >= 0.35)
    ) and (volume_z is None or volume_z < 0.75)
    moderate_chase = bool(flags) and (
        (rsi is not None and rsi >= 76)
        or (ret_5d is not None and ret_5d >= 0.10)
        or (ret_20d is not None and ret_20d >= 0.22)
    )
    if strong_chase:
        return {
            "level": "alto",
            "label": "Entrada perseguida",
            "reason": "; ".join(flags) or "movimiento reciente demasiado extendido",
        }
    if moderate_chase:
        return {
            "level": "medio",
            "label": "Entrada estirada",
            "reason": "; ".join(flags),
        }
    return {
        "level": "normal",
        "label": "Entrada no estirada",
        "reason": "No hay senales claras de entrada perseguida.",
    }


def opportunity_assessment(candidate: dict[str, Any]) -> dict[str, Any]:
    score_value = opportunity_score(candidate)
    technical_score = _num(candidate.get("score"))
    reward_risk = _num((candidate.get("risk_plan", {}) or {}).get("reward_risk"))
    if reward_risk is None:
        reward_risk = opportunity_risk_plan(candidate).get("reward_risk")
    setup_quality = str(candidate.get("setup_quality") or "").lower()
    breakout_failure_risk = bool(((candidate.get("technical_state", {}) or {}).get("breakout_failure_risk")))
    entry_risk = opportunity_entry_risk(candidate)

    if entry_risk["level"] == "alto":
        return {
            "label": "Esperar pullback",
            "tone": "neutral",
            "summary": "El activo llega demasiado estirado; no parece buen punto para empezar ahora.",
            "reason": f"{entry_risk['label']}: {entry_risk['reason']}. Mejor esperar retroceso, consolidacion o nueva confirmacion.",
        }

    if (
        isinstance(score_value, (int, float))
        and score_value >= 0.05
        and isinstance(technical_score, (int, float))
        and technical_score >= 16
        and isinstance(reward_risk, (int, float))
        and reward_risk >= 1.5
        and not breakout_failure_risk
    ):
        return {
            "label": "Buena oportunidad",
            "tone": "good",
            "summary": "Tiene sentido comprar si encaja con tu riesgo.",
            "reason": "Combina fuerza tecnica, prioridad alta y salida riesgo/beneficio razonable.",
        }
    if (
        isinstance(score_value, (int, float))
        and score_value >= 0.0
        and isinstance(technical_score, (int, float))
        and technical_score >= 14
    ):
        if entry_risk["level"] == "medio":
            return {
                "label": "Oportunidad estirada",
                "tone": "neutral",
                "summary": "El setup es valido, pero el punto de entrada ya no es especialmente comodo.",
                "reason": f"{entry_risk['label']}: {entry_risk['reason']}. Tiene mas sentido esperar confirmacion que perseguir precio.",
            }
        return {
            "label": "Oportunidad razonable",
            "tone": "good",
            "summary": "Se puede plantear una entrada, aunque no es de las mas limpias.",
            "reason": "El setup tecnico es bueno y la prioridad ajustada sigue siendo aceptable.",
        }
    if (
        isinstance(score_value, (int, float))
        and score_value > -0.03
        and isinstance(technical_score, (int, float))
        and technical_score >= 15
    ):
        return {
            "label": "Solo vigilancia",
            "tone": "neutral",
            "summary": "El grafico es fuerte, pero no hay suficiente ventaja para empezar ahora.",
            "reason": "La puntuacion final es negativa o muy ajustada; mejor esperar confirmacion, retroceso o mejora de volumen.",
        }
    if (
        isinstance(score_value, (int, float))
        and score_value > -0.08
        and isinstance(technical_score, (int, float))
        and technical_score >= 12
    ) or setup_quality in {"strong", "good"}:
        return {
            "label": "Solo vigilancia",
            "tone": "neutral",
            "summary": "Aun no destaca como compra clara; sirve mas para seguimiento que para entrar ya.",
            "reason": "Hay elementos tecnicos validos, pero no suficiente ventaja neta para considerarla comoda.",
        }
    return {
        "label": "No compensa ahora",
        "tone": "bad",
        "summary": "No parece una entrada con buen equilibrio entre oportunidad y riesgo.",
        "reason": "La prioridad de compra es baja o el setup no ofrece suficiente claridad en este momento.",
    }


def opportunity_summary_row(candidate: dict[str, Any]) -> dict[str, Any]:
    risk = opportunity_risk_plan(candidate)
    technical = candidate.get("technical_state", {}) or {}
    assessment = opportunity_assessment(candidate)
    entry_risk = opportunity_entry_risk(candidate)
    return {
        "simbolo": candidate.get("symbol"),
        "ranking": candidate.get("selection_rank"),
        "puntuacion": opportunity_score(candidate),
        "score_tecnico": candidate.get("score"),
        "oportunidad": assessment["label"],
        "riesgo_entrada": entry_risk["label"],
        "lectura": assessment["summary"],
        "setup": candidate.get("setup_name"),
        "calidad": candidate.get("setup_quality"),
        "precio_actual": risk.get("current_price"),
        "entrada": risk.get("entry_price"),
        "stop_loss": risk.get("stop_loss"),
        "take_profit": risk.get("take_profit"),
        "rr": risk.get("reward_risk"),
        "rsi": technical.get("rsi_14"),
        "ret_20d": technical.get("return_20d"),
        "vol_z": technical.get("volume_zscore_20"),
    }


def pending_buy_plans_by_symbol(store: Store) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in store.pending_order_plans(limit=500):
        symbol = str(item.get("symbol") or "").upper().strip()
        if symbol and symbol not in result:
            result[symbol] = item
    return result


def latest_llm_context_by_symbol(store: Store, symbols: list[str]) -> dict[str, dict[str, Any]]:
    requested = {str(symbol or "").upper().strip() for symbol in symbols if str(symbol or "").strip()}
    if not requested:
        return {}
    result: dict[str, dict[str, Any]] = {}
    with store.connect() as conn:
        for symbol in requested:
            learning_row = conn.execute(
                """
                SELECT symbol, signal_date, decision, explanation, llm_considered,
                       approved_buy, blocked_entry_quality, blocked_backtest,
                       executed_buy, gate_json, updated_at
                FROM learning_observations
                WHERE symbol = ?
                ORDER BY signal_date DESC, updated_at DESC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
            if learning_row:
                gate = _json_cell(learning_row["gate_json"])
                result[symbol] = {
                    "symbol": symbol,
                    "source": "learning_observations",
                    "signal_date": learning_row["signal_date"],
                    "decision": learning_row["decision"],
                    "explanation": learning_row["explanation"],
                    "llm_considered": bool(learning_row["llm_considered"]),
                    "approved_buy": bool(learning_row["approved_buy"]),
                    "blocked_entry_quality": bool(learning_row["blocked_entry_quality"]),
                    "blocked_backtest": bool(learning_row["blocked_backtest"]),
                    "executed_buy": bool(learning_row["executed_buy"]),
                    "llm_gate": gate.get("llm", {}) if isinstance(gate, dict) else {},
                    "updated_at": learning_row["updated_at"],
                }
                continue

            signal_row = conn.execute(
                """
                SELECT symbol, signal_date, decision, gate_json, updated_at
                FROM signal_outcomes
                WHERE symbol = ?
                ORDER BY signal_date DESC, updated_at DESC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
            if signal_row:
                gate = _json_cell(signal_row["gate_json"])
                llm_gate = gate.get("llm", {}) if isinstance(gate, dict) else {}
                result[symbol] = {
                    "symbol": symbol,
                    "source": "signal_outcomes",
                    "signal_date": signal_row["signal_date"],
                    "decision": signal_row["decision"],
                    "explanation": llm_gate.get("reason") or "",
                    "llm_considered": bool(llm_gate),
                    "approved_buy": str(signal_row["decision"] or "").lower() == "buy",
                    "blocked_entry_quality": False,
                    "blocked_backtest": False,
                    "executed_buy": False,
                    "llm_gate": llm_gate,
                    "updated_at": signal_row["updated_at"],
                }
    return result


def llm_status_reason(llm_context: dict[str, Any] | None) -> tuple[str, str, str]:
    if not llm_context:
        return (
            "neutral",
            "Sin revision LLM",
            "No hay una decision LLM reciente guardada para este simbolo.",
        )
    decision = str(llm_context.get("decision") or "").lower()
    explanation = str(llm_context.get("explanation") or "").strip()
    llm_gate = llm_context.get("llm_gate", {}) or {}
    llm_reason = str(llm_gate.get("reason") or "").strip()
    detail = explanation or llm_reason or "Sin explicacion LLM guardada."
    if llm_context.get("approved_buy") or decision == "buy":
        return ("good", "LLM aprobo compra", detail)
    if llm_context.get("blocked_entry_quality"):
        return ("bad", "LLM bloqueada calidad", detail)
    if llm_context.get("blocked_backtest"):
        return ("bad", "LLM bloqueada backtest", detail)
    if decision in {"hold", "watch", "candidate"}:
        return ("neutral", f"LLM {decision}", detail)
    if decision:
        return ("neutral", f"LLM {decision}", detail)
    return ("neutral", "LLM sin dictamen", detail)


def opportunity_status(
    candidate: dict[str, Any],
    *,
    portfolio: PortfolioSnapshot,
    pending_plans_by_symbol_map: dict[str, dict[str, Any]],
    settings: Settings,
    llm_context: dict[str, Any] | None = None,
) -> dict[str, str]:
    symbol = str(candidate.get("symbol") or "").upper()
    open_order_symbols = {str(item.symbol or "").upper() for item in portfolio.open_orders}
    position_symbols = {
        str(item.symbol or "").upper()
        for item in portfolio.positions
        if str(item.side or "long").lower() == "long" and float(item.qty or 0.0) > 0
    }
    if symbol in pending_plans_by_symbol_map:
        return {"tone": "neutral", "label": "Plan pendiente", "reason": "Ya existe un plan pendiente de ejecucion."}
    if symbol in open_order_symbols:
        return {"tone": "neutral", "label": "Orden abierta", "reason": "Ya hay una orden abierta en broker para este simbolo."}
    if symbol in position_symbols:
        return {"tone": "neutral", "label": "Posicion abierta", "reason": "Ya existe una posicion larga y no se deberia duplicar."}
    if candidate.get("blocked_auto_buy"):
        return {
            "tone": "bad",
            "label": "Bloqueada auto-compra",
            "reason": str(candidate.get("blocked_auto_buy_reason") or "La configuracion marca este setup como shadow/watch."),
        }
    if not settings.auto_paper_trading:
        return {
            "tone": "neutral",
            "label": "Manual por configuracion",
            "reason": "AUTO_PAPER_TRADING=false: el sistema no compra automaticamente.",
        }
    if settings.require_human_approval:
        return {
            "tone": "neutral",
            "label": "Requiere aprobacion",
            "reason": "REQUIRE_HUMAN_APPROVAL=true: necesita confirmacion humana antes de ejecucion.",
        }
    tone, label, reason = llm_status_reason(llm_context)
    return {"tone": tone, "label": label, "reason": reason}


def build_opportunity_snapshot(
    settings: Settings,
    store: Store,
    technical_context: dict[str, Any],
    *,
    slot_time: str,
    snapshot_dt: datetime | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    annotated_context = _annotate_technical_context_with_learning(
        technical_context,
        load_daily_learning_context(settings.data_dir),
        load_operational_response_context(settings.data_dir),
        settings.data_dir,
        settings=settings,
    )
    opportunities = opportunity_candidates(annotated_context, limit=limit)
    portfolio_error = None
    portfolio = empty_portfolio_snapshot()
    try:
        portfolio = BrokerClientFactory(settings).alpaca_portfolio_snapshot()
    except Exception as exc:  # noqa: BLE001
        portfolio_error = str(exc)
    pending = pending_buy_plans_by_symbol(store)
    llm_map = latest_llm_context_by_symbol(store, [str(item.get("symbol") or "") for item in opportunities])
    snapshot_local = snapshot_dt.astimezone(ZoneInfo(settings.local_timezone)) if snapshot_dt else datetime.now(ZoneInfo(settings.local_timezone))

    snapshot_rows = []
    actionable = 0
    for index, candidate in enumerate(opportunities, start=1):
        symbol = str(candidate.get("symbol") or "").upper()
        llm_context = llm_map.get(symbol)
        status = opportunity_status(
            candidate,
            portfolio=portfolio,
            pending_plans_by_symbol_map=pending,
            settings=settings,
            llm_context=llm_context,
        )
        if status["label"] not in {"Plan pendiente", "Orden abierta", "Posicion abierta"}:
            actionable += 1
        snapshot_rows.append(
            {
                **candidate,
                "ranking": candidate.get("selection_rank") or index,
                "puntuacion": opportunity_score(candidate),
                "assessment": opportunity_assessment(candidate),
                "risk_snapshot": opportunity_risk_plan(candidate),
                "summary_row": opportunity_summary_row(candidate),
                "llm_context": llm_context or {},
                "operational_status": status,
            }
        )

    best_score = max((_num(item.get("puntuacion")) or float("-inf") for item in snapshot_rows), default=float("-inf"))
    summary = {
        "session_date": snapshot_local.date().isoformat(),
        "slot_time": slot_time,
        "snapshot_local": snapshot_local.isoformat(),
        "as_of": annotated_context.get("as_of"),
        "report_path": technical_context.get("path"),
        "run_id": technical_context.get("run_id"),
        "opportunities_count": len(snapshot_rows),
        "actionable_count": actionable,
        "pending_count": len(pending),
        "best_puntuacion": None if best_score == float("-inf") else round(best_score, 4),
        "selection_method": ((annotated_context.get("selection_metadata") or {}).get("method") or "-"),
        "portfolio_error": portfolio_error,
    }
    return {
        "session_date": summary["session_date"],
        "slot_time": slot_time,
        "run_id": technical_context.get("run_id"),
        "report_path": technical_context.get("path"),
        "summary": summary,
        "opportunities": snapshot_rows,
    }


def _json_cell(value: Any) -> dict[str, Any]:
    import json

    if isinstance(value, dict):
        return value
    try:
        return json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
