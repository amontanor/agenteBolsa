"""Incremental daily learning ledger, digest and conservative promotion flow."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.models import new_id
from agente_bolsa.storage import Store

from .counterfactual_analysis import _compare_policy_rows, _rebuild_signal_cohorts, _session_dates
from .learning_mode import LEARNING_EXPERIMENT_SOURCE
from .llm_degraded_watchdog import evaluate as evaluate_llm_watchdog
from .pre_earnings import load_pre_earnings_learning_context
from .reporting import write_json_report
from .signal_learning import HORIZONS, _indicator_tags, _num, update_signal_outcomes

DEFAULT_DAILY_LEARNING_START = "2026-04-01"
LEDGER_LIMIT = 200000


def _round(value: Any, digits: int = 4) -> float | None:
    number = _num(value)
    if number is None:
        return None
    return round(number, digits)


def _write_report(report: dict[str, Any], reports_dir: Path, prefix: str, run_id: str) -> dict[str, Any]:
    return write_json_report(report, reports_dir, prefix, run_id)


def _llm_status_snapshot(store: Store) -> dict[str, Any]:
    try:
        return evaluate_llm_watchdog(getattr(store, "database_path", ""))
    except Exception as exc:  # noqa: BLE001 - el digest nunca debe romper.
        return {
            "degraded": None,
            "severity": "unknown",
            "roles": {},
            "status_line": f"LLM: no disponible ({exc})",
        }


def _source_family(row: dict[str, Any]) -> str:
    source = str(row.get("source") or "").strip().lower()
    if source:
        return source
    source_run_id = str(row.get("source_run_id") or "").strip().lower()
    if "_" in source_run_id:
        return source_run_id.split("_", maxsplit=1)[0]
    if "-" in source_run_id:
        return source_run_id.split("-", maxsplit=1)[0]
    return source_run_id or "unknown"


def _matured_for_horizon(observation: dict[str, Any], horizon: int) -> bool:
    outcome = observation.get("outcome", {}) or {}
    matured = outcome.get("matured_horizons", {}) or {}
    return bool(matured.get(f"{horizon}d"))


def _horizon_return(observation: dict[str, Any], horizon: int) -> float | None:
    return _num((observation.get("outcome") or {}).get(f"return_{horizon}d"))


def _winner_for_horizon(observation: dict[str, Any], horizon: int) -> bool:
    value = _horizon_return(observation, horizon)
    return value is not None and value > 0.01


def _loser_for_horizon(observation: dict[str, Any], horizon: int) -> bool:
    value = _horizon_return(observation, horizon)
    return value is not None and value < -0.01


def _decision_error_example(observation: dict[str, Any], horizon: int) -> dict[str, Any]:
    features = observation.get("features", {}) or {}
    gate = observation.get("gate", {}) or {}
    entry_gate = gate.get("entry_quality_gate", {}) or {}
    backtest_gate = gate.get("backtest_gate", {}) or {}
    return {
        "observation_id": observation.get("observation_id"),
        "signal_date": observation.get("signal_date"),
        "symbol": observation.get("symbol"),
        "source_family": observation.get("source_family"),
        "decision": observation.get("decision"),
        "setup": _setup_name(features),
        "return": _round(_horizon_return(observation, horizon), 4),
        "best_score": _round(observation.get("best_score"), 2),
        "selection_score": _round(observation.get("best_selection_score"), 4),
        "rank_priority_score": _round(observation.get("best_rank_priority_score"), 4),
        "selection_rank": observation.get("best_selection_rank"),
        "blocked_reason": (
            entry_gate.get("reason")
            or backtest_gate.get("reason")
            or str(observation.get("explanation") or "")
        ),
    }


def _decision_error_rates(observations: list[dict[str, Any]], horizon: int) -> dict[str, Any]:
    matured = [item for item in observations if _matured_for_horizon(item, horizon)]
    executed = [item for item in matured if bool(item.get("executed_buy"))]
    blocked = [
        item
        for item in matured
        if bool(item.get("blocked_entry_quality")) or bool(item.get("blocked_backtest"))
    ]
    false_positive_executed_losers = [item for item in executed if _loser_for_horizon(item, horizon)]
    false_negative_blocked_winners = [item for item in blocked if _winner_for_horizon(item, horizon)]
    return {
        "horizon": f"{horizon}d",
        "matured": len(matured),
        "executed_buys": len(executed),
        "blocked_candidates": len(blocked),
        "false_positive_executed_losers": len(false_positive_executed_losers),
        "false_positive_rate": _round(len(false_positive_executed_losers) / len(executed), 4) if executed else None,
        "false_negative_blocked_winners": len(false_negative_blocked_winners),
        "false_negative_rate": _round(len(false_negative_blocked_winners) / len(blocked), 4) if blocked else None,
        "false_positive_examples": [
            _decision_error_example(item, horizon)
            for item in sorted(
                false_positive_executed_losers,
                key=lambda row: _horizon_return(row, horizon) or 0.0,
            )[:5]
        ],
        "false_negative_examples": [
            _decision_error_example(item, horizon)
            for item in sorted(
                false_negative_blocked_winners,
                key=lambda row: _horizon_return(row, horizon) or 0.0,
                reverse=True,
            )[:5]
        ],
    }


def _feature_bucket_stats(observations: list[dict[str, Any]], horizon: int, *, min_samples: int = 3) -> list[dict[str, Any]]:
    by_tag: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        for tag in _indicator_tags({"features": observation.get("features", {}) or {}}):
            by_tag[tag].append(observation)
    rows = []
    for tag, items in by_tag.items():
        matured = [item for item in items if _matured_for_horizon(item, horizon)]
        if len(matured) < min_samples:
            continue
        returns = [_horizon_return(item, horizon) for item in matured]
        clean_returns = [value for value in returns if value is not None]
        if not clean_returns:
            continue
        rows.append(
            {
                "tag": tag,
                "signals": len(items),
                "matured": len(matured),
                "win_rate": _round(sum(1 for item in matured if _winner_for_horizon(item, horizon)) / len(matured), 4),
                "loss_rate": _round(sum(1 for item in matured if _loser_for_horizon(item, horizon)) / len(matured), 4),
                "avg_return": _round(sum(clean_returns) / len(clean_returns), 4),
            }
        )
    return sorted(
        rows,
        key=lambda item: (
            item["matured"],
            item["avg_return"] if item["avg_return"] is not None else -999,
            item["win_rate"] if item["win_rate"] is not None else -1,
        ),
        reverse=True,
    )


def _observation_payload(group: list[dict[str, Any]]) -> dict[str, Any]:
    sorted_group = sorted(
        group,
        key=lambda item: (
            not bool(item.get("executed_buy")),
            -float(_num(item.get("score")) or 0.0),
            item.get("signal_id", ""),
        ),
    )
    best = sorted_group[0]
    decision_priority = {
        "executed_buy": 6,
        "approved_buy": 5,
        "blocked_backtest": 4,
        "blocked_entry_quality": 3,
        "hold": 2,
        "candidate": 1,
    }
    effective_decision = max(
        group,
        key=lambda item: decision_priority.get(
            "executed_buy" if item.get("executed_buy") else str(item.get("decision") or "candidate"),
            0,
        ),
    )
    first_seen = min((row.get("created_at") for row in group if row.get("created_at")), default=None)
    last_seen = max((row.get("created_at") for row in group if row.get("created_at")), default=None)
    executed = [row for row in group if row.get("executed_buy")]
    explanation_parts = []
    if len(group) > 1:
        explanation_parts.append(f"{len(group)} senales intradia agregadas")
    if executed:
        explanation_parts.append(f"{len(executed)} ejecucion(es) real(es)")
    if effective_decision.get("decision") == "blocked_entry_quality":
        explanation_parts.append("bloqueada por calidad de entrada")
    elif effective_decision.get("decision") == "blocked_backtest":
        explanation_parts.append("bloqueada por backtest")
    elif effective_decision.get("executed_buy"):
        explanation_parts.append("compra ejecutada")
    elif effective_decision.get("decision") == "approved_buy":
        explanation_parts.append("aprobada pero no ejecutada")
    else:
        explanation_parts.append("solo candidata/no seleccionada")
    explanation = "; ".join(explanation_parts)
    return {
        "observation_id": f"{best['signal_date']}:{best['symbol']}:{_source_family(best)}",
        "signal_date": best["signal_date"],
        "symbol": best["symbol"],
        "source_family": _source_family(best),
        "source_run_ids": sorted({str(row.get("source_run_id") or "") for row in group if row.get("source_run_id")}),
        "first_seen_at": first_seen,
        "last_seen_at": last_seen,
        "best_signal_id": best.get("signal_id"),
        "best_score": _num(best.get("score")),
        "best_selection_score": _num((best.get("features") or {}).get("selection_score") or best.get("selection_score")),
        "best_rank_priority_score": _num(
            (best.get("features") or {}).get("rank_priority_score") or best.get("rank_priority_score")
        ),
        "best_selection_rank": (best.get("features") or {}).get("selection_rank") or best.get("selection_rank"),
        "best_effective_setup_edge_3d": _num(
            (best.get("features") or {}).get("effective_setup_edge_3d") or best.get("effective_setup_edge_3d")
        ),
        "decision": "executed_buy" if executed else str(effective_decision.get("decision") or "candidate"),
        "explanation": explanation,
        "llm_considered": any(bool(row.get("considered_by_llm")) for row in group),
        "approved_buy": any(str(row.get("decision")) == "approved_buy" for row in group),
        "blocked_entry_quality": any(str(row.get("decision")) == "blocked_entry_quality" for row in group),
        "blocked_backtest": any(str(row.get("decision")) == "blocked_backtest" for row in group),
        "executed_buy": bool(executed),
        "duplicate_count": max(0, len(group) - 1),
        "rank_path": [
            {
                "signal_id": row.get("signal_id"),
                "score": _num(row.get("score")),
                "selection_score": _num((row.get("features") or {}).get("selection_score") or row.get("selection_score")),
                "rank_priority_score": _num(
                    (row.get("features") or {}).get("rank_priority_score") or row.get("rank_priority_score")
                ),
                "selection_rank": (row.get("features") or {}).get("selection_rank") or row.get("selection_rank"),
                "effective_setup_edge_3d": _num(
                    (row.get("features") or {}).get("effective_setup_edge_3d") or row.get("effective_setup_edge_3d")
                ),
                "score_rank": ((row.get("rank_context") or {}).get("score_rank")),
                "source_run_id": row.get("source_run_id"),
                "decision": row.get("decision"),
            }
            for row in sorted(group, key=lambda item: (item.get("created_at", ""), item.get("signal_id", "")))
        ],
        "features": best.get("features", {}) or {},
        "gate": effective_decision.get("gate", {}) or {},
        "outcome": (executed[0] if executed else best).get("outcome", {}) or {},
        "execution": {
            "executed_rows": len(executed),
            "duplicate_execution": any(bool((row.get("flags") or {}).get("duplicate_execution")) for row in group),
            "orders_same_day": sum(int(row.get("orders_same_day") or 0) for row in group),
        },
        "created_at": first_seen,
    }


def _materialize_observations(store: Store, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["signal_date"], row["symbol"], _source_family(row))].append(row)
    observations = []
    for group in grouped.values():
        observation = _observation_payload(group)
        store.upsert_learning_observation(observation)
        observations.append(observation)
    return sorted(observations, key=lambda item: (item["signal_date"], item["symbol"], item["source_family"]))


def _build_health(observations: list[dict[str, Any]], raw_rows: list[dict[str, Any]]) -> dict[str, Any]:
    duplicate_signals = sum(int(item.get("duplicate_count") or 0) for item in observations)
    total_observations = len(observations)
    total_signals = max(len(raw_rows), total_observations + duplicate_signals)
    horizon_counts = {
        f"{h}d": sum(1 for item in observations if _matured_for_horizon(item, h))
        for h in HORIZONS
    }
    available = sum(1 for item in observations if (item.get("outcome") or {}).get("available"))
    executed = sum(1 for item in observations if item.get("executed_buy"))
    blockers = []
    if duplicate_signals:
        blockers.append(
            {
                "kind": "duplicate_intraday_signals",
                "severity": "high" if duplicate_signals > total_observations else "medium",
                "detail": f"{duplicate_signals} senales repetidas frente a {total_observations} observaciones canonicas.",
            }
        )
    if horizon_counts["3d"] < max(10, int(total_observations * 0.1)):
        blockers.append(
            {
                "kind": "low_short_horizon_coverage",
                "severity": "high",
                "detail": f"Solo {horizon_counts['3d']} observaciones con retorno 3d utilizable.",
            }
        )
    if executed < max(5, int(total_observations * 0.02)):
        blockers.append(
            {
                "kind": "low_real_execution_volume",
                "severity": "medium",
                "detail": f"Solo {executed} observaciones ejecutadas; el bucle de feedback real sigue siendo escaso.",
            }
        )
    if available < total_observations:
        blockers.append(
            {
                "kind": "missing_forward_outcomes",
                "severity": "medium",
                "detail": f"{total_observations - available} observaciones todavia no tienen outcome forward disponible.",
            }
        )
    return {
        "signals_raw": total_signals,
        "canonical_observations": total_observations,
        "duplicate_signals": duplicate_signals,
        "duplicate_ratio": _round(duplicate_signals / total_signals, 4) if total_signals else 0.0,
        "outcomes_available": available,
        "executed_observations": executed,
        "horizon_coverage": horizon_counts,
        "blockers": blockers,
    }


def _order_rejections_by_session_symbol(store: Store, session_date: str) -> dict[str, list[dict[str, Any]]]:
    with store.connect() as conn:
        rows = conn.execute(
            """
            SELECT payload_json
            FROM agent_events
            WHERE event_type = 'paper_auto_trade_completed'
              AND substr(created_at, 1, 10) = ?
            ORDER BY created_at ASC
            """,
            (session_date,),
        ).fetchall()
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        payload = json.loads(row["payload_json"] or "{}")
        for rejection in payload.get("rejected_order_plans", []) or []:
            symbol = str(rejection.get("symbol") or "").upper()
            if symbol:
                result[symbol].append(rejection)
    return result


def _candidate_entry(features: dict[str, Any]) -> float | None:
    return _num(features.get("entry_price") or features.get("close"))


def _same_session_return(direction: str, first_entry: float | None, latest_entry: float | None) -> float | None:
    if not first_entry or not latest_entry:
        return None
    if str(direction).lower() == "short":
        return (first_entry - latest_entry) / first_entry
    return (latest_entry - first_entry) / first_entry


def _blocked_reason(row: dict[str, Any], rejections: dict[str, list[dict[str, Any]]]) -> str:
    symbol_rejections = rejections.get(str(row.get("symbol") or "").upper()) or []
    if symbol_rejections:
        latest = symbol_rejections[-1]
        return f"{latest.get('stage')}: {latest.get('reason')}"
    gate = row.get("gate", {}) or {}
    for key in ("entry_quality_gate", "backtest_gate"):
        item = gate.get(key) or {}
        if item and item.get("approved") is False:
            return f"{key}: {item.get('reason')}"
    if row.get("decision") == "approved_buy" and not row.get("executed_buy"):
        return "approved_buy_without_execution"
    if row.get("considered_by_llm"):
        llm = gate.get("llm") or {}
        action = llm.get("action") or row.get("decision")
        return f"llm_{action}"
    return "not_selected_by_llm"


def _build_same_session_opportunity_ledger(
    rows: list[dict[str, Any]],
    store: Store,
    session_date: str,
    *,
    top: int = 20,
) -> dict[str, Any]:
    session_rows = [row for row in rows if row.get("signal_date") == session_date]
    rejections = _order_rejections_by_session_symbol(store, session_date)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in session_rows:
        features = row.get("features", {}) or {}
        score = _num(features.get("score") or row.get("score"))
        if score is None:
            continue
        grouped[(row["symbol"], row.get("source") or "unknown")].append(row)

    items = []
    for (symbol, source), group in grouped.items():
        ordered = sorted(group, key=lambda item: (item.get("created_at") or "", item.get("signal_id") or ""))
        first = ordered[0]
        latest = ordered[-1]
        first_features = first.get("features", {}) or {}
        latest_features = latest.get("features", {}) or {}
        first_entry = _candidate_entry(first_features)
        latest_entry = _candidate_entry(latest_features)
        direction = str(latest_features.get("direction") or first_features.get("direction") or "long")
        executed = any(bool(row.get("executed_buy")) for row in group)
        score = max(_num((row.get("features") or {}).get("score") or row.get("score")) or 0.0 for row in group)
        items.append(
            {
                "symbol": symbol,
                "source": source,
                "direction": direction,
                "max_score": _round(score, 2),
                "observations": len(group),
                "first_seen_at": first.get("created_at"),
                "last_seen_at": latest.get("created_at"),
                "first_entry_price": _round(first_entry, 4),
                "latest_entry_price": _round(latest_entry, 4),
                "same_session_return": _round(_same_session_return(direction, first_entry, latest_entry), 4),
                "decision": latest.get("decision"),
                "executed_buy": executed,
                "considered_by_llm": any(bool(row.get("considered_by_llm")) for row in group),
                "reason_not_executed": "" if executed else _blocked_reason(latest, rejections),
                "latest_gate": latest.get("gate", {}) or {},
                "latest_features": {
                    "rsi_14": _round(latest_features.get("rsi_14"), 2),
                    "volume_zscore_20": _round(latest_features.get("volume_zscore_20"), 2),
                    "distance_sma20": _round(latest_features.get("distance_sma20"), 4),
                    "chart_patterns": latest_features.get("chart_patterns", {}),
                },
            }
        )

    non_executed = [item for item in items if not item["executed_buy"]]
    ranked = sorted(
        non_executed,
        key=lambda item: (
            item["same_session_return"] if item["same_session_return"] is not None else -999.0,
            item["max_score"] or 0.0,
            item["observations"],
        ),
        reverse=True,
    )
    return {
        "session_date": session_date,
        "summary": {
            "candidates": len(items),
            "non_executed": len(non_executed),
            "executed": len(items) - len(non_executed),
        },
        "top_non_executed": ranked[:top],
    }


def _bullish_confirmed_count_from_features(features: dict[str, Any]) -> int:
    chart_patterns = features.get("chart_patterns", {}) or {}
    if isinstance(chart_patterns, dict):
        return int(chart_patterns.get("bullish_confirmed_count") or 0)
    if isinstance(chart_patterns, list):
        return sum(
            1
            for item in chart_patterns
            if item.get("bias") == "bullish" and item.get("status") == "confirmed"
        )
    return 0


def _same_session_shadow_candidates(ledger: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Create shadow-only expansion candidates from repeated intraday misses."""

    if not isinstance(ledger, dict):
        return []
    rows = []
    for item in ledger.get("top_non_executed", []) or []:
        if str(item.get("source") or "") != "intraday_scan":
            continue
        if str(item.get("reason_not_executed") or "") != "not_selected_by_llm":
            continue
        same_session_return = _num(item.get("same_session_return"))
        max_score = _num(item.get("max_score"))
        observations = int(item.get("observations") or 0)
        features = item.get("latest_features", {}) or {}
        volume_z = _num(features.get("volume_zscore_20"))
        distance_sma20 = _num(features.get("distance_sma20"))
        rsi = _num(features.get("rsi_14"))
        bullish_patterns = _bullish_confirmed_count_from_features(features)
        if same_session_return is None or max_score is None:
            continue
        if same_session_return < 0.04 or max_score < 14 or observations < 3:
            continue
        if distance_sma20 is not None and distance_sma20 > 0.30:
            continue
        if rsi is not None and rsi > 84:
            continue
        if (volume_z is None or volume_z < 0.50) and bullish_patterns < 2:
            continue
        rows.append(
            {
                "symbol": item.get("symbol"),
                "same_session_return": _round(same_session_return, 4),
                "max_score": _round(max_score, 2),
                "observations": observations,
                "volume_zscore_20": _round(volume_z, 2),
                "distance_sma20": _round(distance_sma20, 4),
                "rsi_14": _round(rsi, 2),
                "bullish_confirmed_patterns": bullish_patterns,
                "first_seen_at": item.get("first_seen_at"),
                "last_seen_at": item.get("last_seen_at"),
            }
        )
    if len(rows) < 2:
        return []

    rows = sorted(rows, key=lambda item: item["same_session_return"] or 0.0, reverse=True)
    top3_capture = sum(float(item.get("same_session_return") or 0.0) * 0.05 for item in rows[:3])
    return [
        {
            "policy_id": "shadow_intraday_same_session_momentum_promotion",
            "name": "Shadow promotion for repeated intraday momentum not selected by LLM",
            "policy_type": "intraday_selection_shadow",
            "status": "shadow",
            "scope": "intraday_scan",
            "auto_activatable": False,
            "evidence": {
                "session_date": ledger.get("session_date"),
                "selection_reason": "repeated intraday candidates moved materially while remaining not_selected_by_llm",
            },
            "metrics": {
                "cases": len(rows),
                "avg_same_session_return": _round(
                    sum(float(item.get("same_session_return") or 0.0) for item in rows) / len(rows),
                    4,
                ),
                "top3_portfolio_capture_at_5pct": _round(top3_capture, 4),
                "examples": rows[:8],
            },
            "notes": (
                "Shadow-only: study whether repeated intraday strength should promote candidates before LLM. "
                "Do not auto-buy or relax risk gates without walk-forward evidence."
            ),
            "last_evaluated_at": datetime.now(timezone.utc).isoformat(),
        }
    ]


def _daily_guidance(
    health: dict[str, Any],
    candidates: list[dict[str, Any]],
    weak_tags: list[dict[str, Any]],
    pre_earnings_context: dict[str, Any] | None = None,
    entry_quality_filter_calibration: dict[str, Any] | None = None,
    same_session_shadow_candidates: list[dict[str, Any]] | None = None,
) -> list[str]:
    guidance = []
    if health.get("duplicate_signals", 0) > 0:
        guidance.append("Tratar como una sola oportunidad las senales repetidas del mismo simbolo en la misma sesion.")
    if weak_tags:
        first = weak_tags[0]
        guidance.append(
            f"Dejar en shadow penalización para {first['tag']} hasta confirmar estabilidad out-of-sample."
        )
    if health.get("executed_observations", 0) < 5:
        guidance.append("No promover reglas expansivas: todavía falta volumen de ejecuciones reales.")
    if any(item.get("status") == "guarded_active" for item in candidates):
        guidance.append("Mantener activas solo reglas conservadoras de bloqueo con evidencia suficiente.")
    if entry_quality_filter_calibration:
        missed_winners = int(entry_quality_filter_calibration.get("missed_winners") or 0)
        avoided_losers = int(entry_quality_filter_calibration.get("avoided_losers") or 0)
        if missed_winners > avoided_losers:
            guidance.append("Revisar entry-quality en shadow: esta vetando mas ganadores maduros de los perdedores que evita.")
    if same_session_shadow_candidates:
        metrics = same_session_shadow_candidates[0].get("metrics", {}) or {}
        guidance.append(
            "Estudiar en shadow promocion de momentum intradia repetido: "
            f"captura teorica top3 al 5%={_round(metrics.get('top3_portfolio_capture_at_5pct'), 4)}."
        )
    if pre_earnings_context and pre_earnings_context.get("available"):
        guidance.extend(list(pre_earnings_context.get("guidance", []) or [])[:2])
    return guidance[:8]


def _setup_name(features: dict[str, Any]) -> str:
    if bool(features.get("event_momentum_long")):
        return "event_momentum"
    if bool(features.get("range_expansion_breakout_long")):
        return "range_expansion_breakout"
    if bool(features.get("orderly_breakout_long")):
        return "orderly_breakout"
    if bool(features.get("momentum_shakeout_hold_long")):
        return "momentum_shakeout"
    chart = features.get("chart_patterns", {}) or {}
    if isinstance(chart, dict) and int(chart.get("bullish_confirmed_count") or 0) > 0:
        return "confirmed_pattern"
    if (_num(features.get("volume_zscore_20")) or 0.0) >= 1.0 and (_num(features.get("return_20d")) or 0.0) > 0:
        return "trend_volume"
    return "baseline_trend"


def _setup_stats(observations: list[dict[str, Any]], horizon: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        grouped[_setup_name(observation.get("features", {}) or {})].append(observation)
    rows = []
    for setup, items in grouped.items():
        matured = [item for item in items if _matured_for_horizon(item, horizon)]
        returns = [_horizon_return(item, horizon) for item in matured]
        clean = [value for value in returns if value is not None]
        rows.append(
            {
                "setup": setup,
                "signals": len(items),
                "matured": len(matured),
                "avg_return": _round(sum(clean) / len(clean), 4) if clean else None,
                "win_rate": _round(sum(1 for item in matured if _winner_for_horizon(item, horizon)) / len(matured), 4)
                if matured
                else None,
            }
        )
    return sorted(
        rows,
        key=lambda item: (
            item["matured"],
            item["avg_return"] if item["avg_return"] is not None else -999,
        ),
        reverse=True,
    )


def _symbol_setup_memory(
    observations: list[dict[str, Any]],
    horizon: int,
    *,
    min_samples: int = 1,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        symbol = str(observation.get("symbol") or "").upper()
        if not symbol:
            continue
        grouped[(symbol, _setup_name(observation.get("features", {}) or {}))].append(observation)

    rows = []
    for (symbol, setup), items in grouped.items():
        matured = [item for item in items if _matured_for_horizon(item, horizon)]
        if len(matured) < min_samples:
            continue
        returns = [_horizon_return(item, horizon) for item in matured]
        clean_returns = [value for value in returns if value is not None]
        if not clean_returns:
            continue
        executed = [item for item in matured if item.get("executed_buy")]
        blocked = [item for item in matured if item.get("blocked_entry_quality") or item.get("blocked_backtest")]
        false_positive_losers = [item for item in executed if _loser_for_horizon(item, horizon)]
        false_negative_winners = [item for item in blocked if _winner_for_horizon(item, horizon)]
        rows.append(
            {
                "symbol": symbol,
                "setup": setup,
                "signals": len(items),
                "matured": len(matured),
                "executed_buys": len(executed),
                "blocked_candidates": len(blocked),
                "avg_return": _round(sum(clean_returns) / len(clean_returns), 4),
                "win_rate": _round(sum(1 for item in matured if _winner_for_horizon(item, horizon)) / len(matured), 4),
                "false_positive_losers": len(false_positive_losers),
                "false_negative_winners": len(false_negative_winners),
                "last_signal_date": max(str(item.get("signal_date") or "") for item in items),
            }
        )
    return sorted(
        rows,
        key=lambda item: (
            abs(item["avg_return"] or 0.0),
            item["matured"],
            item["signals"],
        ),
        reverse=True,
    )


def _prior_profile_key(features: dict[str, Any]) -> str:
    feature_tags = _indicator_tags({"features": features})
    selected = []
    for prefix in ("score:", "rsi:", "sma20_dist:", "volume_z:", "chart_confirmed:"):
        for tag in feature_tags:
            if tag.startswith(prefix):
                selected.append(tag)
                break
    return "|".join([_setup_name(features), *selected])


def _setup_priors(observations: list[dict[str, Any]], horizon: int, *, min_samples: int = 3) -> list[dict[str, Any]]:
    setup_base = {item["setup"]: item for item in _setup_stats(observations, horizon)}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        features = observation.get("features", {}) or {}
        grouped[_prior_profile_key(features)].append(observation)

    rows = []
    for profile_key, items in grouped.items():
        matured = [item for item in items if _matured_for_horizon(item, horizon)]
        if len(matured) < min_samples:
            continue
        clean_returns = [_horizon_return(item, horizon) for item in matured]
        clean_returns = [value for value in clean_returns if value is not None]
        if not clean_returns:
            continue
        setup = _setup_name(matured[0].get("features", {}) or {})
        base = setup_base.get(setup, {})
        profile_avg = sum(clean_returns) / len(clean_returns)
        setup_avg = _num(base.get("avg_return")) or 0.0
        confidence_weight = min(1.0, len(matured) / 8.0)
        expected_edge = (profile_avg * confidence_weight) + (setup_avg * (1.0 - confidence_weight))
        feature_tags = _indicator_tags({"features": (matured[0].get("features", {}) or {})})
        rows.append(
            {
                "profile_key": profile_key,
                "setup": setup,
                "signals": len(items),
                "matured": len(matured),
                "avg_return": _round(profile_avg, 4),
                "setup_avg_return": _round(setup_avg, 4),
                "expected_edge": _round(expected_edge, 4),
                "win_rate": _round(sum(1 for item in matured if _winner_for_horizon(item, horizon)) / len(matured), 4),
                "confidence_weight": _round(confidence_weight, 4),
                "profile_tags": feature_tags,
            }
        )
    return sorted(
        rows,
        key=lambda item: (
            item["expected_edge"] if item["expected_edge"] is not None else -999,
            item["matured"],
        ),
        reverse=True,
    )


def _confidence_bucket(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "unknown"
    if number < 0.60:
        return "lt0_60"
    if number < 0.75:
        return "0_60_0_74"
    if number < 0.90:
        return "0_75_0_89"
    return "gte0_90"


def _confidence_calibration(observations: list[dict[str, Any]], horizon: int, *, min_samples: int = 3) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        gate = observation.get("gate", {}) or {}
        llm = gate.get("llm", {}) or {}
        bucket = _confidence_bucket(llm.get("confidence"))
        if bucket == "unknown":
            continue
        grouped[bucket].append(observation)

    rows = []
    for bucket, items in grouped.items():
        matured = [item for item in items if _matured_for_horizon(item, horizon)]
        if len(matured) < min_samples:
            continue
        returns = [_horizon_return(item, horizon) for item in matured]
        clean_returns = [value for value in returns if value is not None]
        if not clean_returns:
            continue
        rows.append(
            {
                "bucket": bucket,
                "signals": len(items),
                "matured": len(matured),
                "avg_return": _round(sum(clean_returns) / len(clean_returns), 4),
                "win_rate": _round(sum(1 for item in matured if _winner_for_horizon(item, horizon)) / len(matured), 4),
            }
        )
    order = {"lt0_60": 0, "0_60_0_74": 1, "0_75_0_89": 2, "gte0_90": 3}
    return sorted(rows, key=lambda item: order.get(str(item.get("bucket")), 99))


def _blocked_filter_calibration(
    observations: list[dict[str, Any]],
    horizon: int,
    *,
    flag_key: str,
    min_samples: int = 3,
) -> dict[str, Any]:
    blocked = [item for item in observations if bool(item.get(flag_key))]
    matured = [item for item in blocked if _matured_for_horizon(item, horizon)]
    by_tag: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in matured:
        for tag in _indicator_tags({"features": observation.get("features", {}) or {}}):
            by_tag[tag].append(observation)
    top_tags = []
    for tag, items in by_tag.items():
        if len(items) < min_samples:
            continue
        returns = [_horizon_return(item, horizon) for item in items]
        clean_returns = [value for value in returns if value is not None]
        if not clean_returns:
            continue
        missed_winners = sum(1 for item in items if _winner_for_horizon(item, horizon))
        avoided_losers = sum(1 for item in items if _loser_for_horizon(item, horizon))
        top_tags.append(
            {
                "tag": tag,
                "matured": len(items),
                "avg_return": _round(sum(clean_returns) / len(clean_returns), 4),
                "missed_winners": missed_winners,
                "avoided_losers": avoided_losers,
                "net_winner_gap": missed_winners - avoided_losers,
            }
        )
    top_tags.sort(
        key=lambda item: (
            item["net_winner_gap"],
            item["avg_return"] if item["avg_return"] is not None else -999,
            item["matured"],
        ),
        reverse=True,
    )
    returns = [_horizon_return(item, horizon) for item in matured]
    clean_returns = [value for value in returns if value is not None]
    return {
        "signals": len(blocked),
        "matured": len(matured),
        "avg_return": _round(sum(clean_returns) / len(clean_returns), 4) if clean_returns else None,
        "missed_winners": sum(1 for item in matured if _winner_for_horizon(item, horizon)),
        "avoided_losers": sum(1 for item in matured if _loser_for_horizon(item, horizon)),
        "top_tags": top_tags[:8],
    }


def _prior_accuracy(observations: list[dict[str, Any]], horizon: int, *, min_samples: int = 3) -> list[dict[str, Any]]:
    priors = {item["profile_key"]: item for item in _setup_priors(observations, horizon, min_samples=min_samples)}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        features = observation.get("features", {}) or {}
        profile_key = _prior_profile_key(features)
        grouped[profile_key].append(observation)

    rows = []
    for profile_key, items in grouped.items():
        prior = priors.get(profile_key)
        expected_edge = _num((prior or {}).get("expected_edge"))
        if expected_edge is None:
            continue
        matured = [item for item in items if _matured_for_horizon(item, horizon)]
        if len(matured) < min_samples:
            continue
        realized = [_horizon_return(item, horizon) for item in matured]
        clean_realized = [value for value in realized if value is not None]
        if not clean_realized:
            continue
        errors = [expected_edge - value for value in clean_realized]
        abs_errors = [abs(value) for value in errors]
        rows.append(
            {
                "profile_key": profile_key,
                "setup": str((prior or {}).get("setup") or _setup_name(matured[0].get("features", {}) or {})),
                "matured": len(matured),
                "expected_edge": _round(expected_edge, 4),
                "realized_avg_return": _round(sum(clean_realized) / len(clean_realized), 4),
                "avg_error": _round(sum(errors) / len(errors), 4),
                "avg_abs_error": _round(sum(abs_errors) / len(abs_errors), 4),
                "profile_tags": list((prior or {}).get("profile_tags", [])),
            }
        )
    return sorted(
        rows,
        key=lambda item: (
            item["avg_abs_error"] if item["avg_abs_error"] is not None else -999,
            item["matured"],
        ),
        reverse=True,
    )


def _select_shadow_candidate_tags(stats_3d: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for item in stats_3d:
        matured = int(item.get("matured") or 0)
        avg_return = _num(item.get("avg_return"))
        win_rate = _num(item.get("win_rate")) or 0.0
        loss_rate = _num(item.get("loss_rate")) or 0.0
        if matured < 100:
            continue
        if avg_return is None:
            continue
        edge = loss_rate - win_rate
        if avg_return < 0 or edge >= 0.08:
            enriched = dict(item)
            enriched["edge"] = _round(edge, 4)
            candidates.append(enriched)
    candidates.sort(
        key=lambda item: (
            item["avg_return"],
            -(item.get("edge") or 0.0),
            -int(item.get("matured") or 0),
        )
    )
    return candidates[:2]


def _upsert_policy_candidates(
    store: Store,
    observations: list[dict[str, Any]],
    session_date: str,
) -> list[dict[str, Any]]:
    candidates = []
    health = _build_health(observations, observations)
    dedupe_candidate = {
        "policy_id": "dedupe_same_symbol_cycle",
        "name": "Block duplicate same-symbol buy per cycle/source",
        "policy_type": "risk_block",
        "status": "guarded_active" if health.get("duplicate_signals", 0) > 0 else "active",
        "scope": "global",
        "auto_activatable": True,
        "evidence": {
            "duplicate_signals": health.get("duplicate_signals", 0),
            "canonical_observations": health.get("canonical_observations", 0),
        },
        "metrics": {
            "duplicate_ratio": health.get("duplicate_ratio", 0.0),
            "executed_observations": health.get("executed_observations", 0),
        },
        "notes": "Regla conservadora ya alineada con la política propuesta; no aumenta compras.",
        "promoted_at": datetime.now(timezone.utc).isoformat(),
        "last_evaluated_at": datetime.now(timezone.utc).isoformat(),
    }
    candidates.append(dedupe_candidate)

    stats_3d = _feature_bucket_stats(observations, 3, min_samples=3)
    weak_tags = _select_shadow_candidate_tags(stats_3d)
    for item in weak_tags:
        policy_id = f"shadow_penalty_{item['tag'].replace(':', '_').replace('|', '_')}"
        candidates.append(
            {
                "policy_id": policy_id,
                "name": f"Shadow penalty for {item['tag']}",
                "policy_type": "feature_shadow",
                "status": "shadow",
                "scope": "global",
                "auto_activatable": False,
                "evidence": {
                    "tag": item["tag"],
                    "horizon": "3d",
                    "session_date": session_date,
                    "selection_reason": "negative short-horizon expectancy or materially worse loss-vs-win balance",
                },
                "metrics": item,
                "notes": "Penalización en shadow; requiere walk-forward antes de promoverse.",
                "last_evaluated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    for candidate in candidates:
        store.upsert_learning_policy_candidate(candidate)
        store.save_learning_policy_evaluation(
            {
                "evaluation_id": new_id("pol_eval"),
                "policy_id": candidate["policy_id"],
                "session_date": session_date,
                "phase": "daily",
                "payload": {
                    "status": candidate["status"],
                    "metrics": candidate.get("metrics", {}),
                    "evidence": candidate.get("evidence", {}),
                },
            }
        )
    return candidates


def _load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _learning_experiment_proposal_candidates(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matured = [item for item in observations if _matured_for_horizon(item, 3)]
    soft_override = [
        item
        for item in matured
        if bool(item.get("features", {}).get("backtest_soft_override"))
        or bool(item.get("gate", {}).get("backtest_soft_override"))
    ]
    if len(soft_override) < 5:
        return []
    returns = [_horizon_return(item, 3) for item in soft_override]
    clean_returns = [value for value in returns if value is not None]
    if len(clean_returns) < 5:
        return []
    avg_return = sum(clean_returns) / len(clean_returns)
    if avg_return >= 0:
        return []
    return [
        {
            "proposal_type": "RISK_RULE_CHANGE",
            "target_component": "learning_mode",
            "target_identifier": "backtest_near_miss_threshold",
            "current_value": "near_miss activo con override soft en paper",
            "proposed_value": "Endurecer learning_near_miss para exigir mejores metricas antes del override soft.",
            "rationale": "El cohorte learning_experiment muestra expectativa negativa en 3d para overrides near-miss.",
            "expected_impact": "Reducir entradas de aprendizaje con sesgo negativo persistente.",
            "risk_level": "MEDIUM",
            "required_validations": ["tests", "paper_trading_evidence"],
            "rollback_plan": "Restaurar umbrales near-miss actuales del learning mode.",
            "promotion_state": "shadow",
            "evidence": [
                f"learning_experiment soft_override matured_3d={len(clean_returns)}",
                f"learning_experiment soft_override avg_return_3d={round(avg_return, 4)}",
            ],
            "target_files": ["data/config/learning_mode.json", "src/agente_bolsa/cycle_runner.py"],
            "test_requirement": "tests del learning mode + evidencia paper del cohorte",
            "test_commands": ["python -m pytest tests/test_learning_mode.py -q"],
            "source": "learning_experiment_digest",
        }
    ]


def _build_learning_experiment_section(
    store: Store,
    reports_dir: Path,
    *,
    since_date: str,
    end_date: str | None,
) -> dict[str, Any]:
    session_date = end_date
    shadow_payload = _load_json_file(reports_dir / "latest_learning_mode_shadow.json")
    if not session_date:
        session_date = str(shadow_payload.get("session_date") or "")
    cohort_rows = _rebuild_signal_cohorts(
        store,
        since_date=since_date,
        end_date=end_date,
        include_learning_experiment=True,
        sources=[LEARNING_EXPERIMENT_SOURCE],
    )
    observations = _materialize_observations(store, cohort_rows) if cohort_rows else []
    if not session_date and observations:
        session_date = max(str(item.get("signal_date") or "") for item in observations)
    session_rows = [item for item in observations if not session_date or item.get("signal_date") == session_date]
    matured_3d = [item for item in session_rows if _matured_for_horizon(item, 3)]
    executed = [item for item in session_rows if bool(item.get("executed_buy"))]
    open_pl = [
        _num(((item.get("outcome") or {}).get("execution") or {}).get("open_pl"))
        for item in executed
    ]
    clean_open_pl = [value for value in open_pl if value is not None]
    latest_post_market = _load_json_file(reports_dir / "latest_post_market_learning.json")
    latest_operational = _load_json_file(reports_dir / "latest_operational_learning.json")
    post_market_same_session = bool(latest_post_market) and str(latest_post_market.get("session_date") or "") == str(session_date or "")
    operational_same_session = bool(latest_operational) and str(latest_post_market.get("session_date") or "") == str(session_date or "")
    proposal_candidates = _learning_experiment_proposal_candidates(session_rows)
    lessons = []
    if latest_operational:
        lessons = [
            str(item)
            for item in (latest_operational.get("learning_journal") or [])
            if "learning_experiment" in json.dumps(item, ensure_ascii=False).lower()
        ][:5]
    if not lessons and executed and not proposal_candidates:
        lessons = ["Opero pero no aprendio nada nuevo."]
    elif not lessons and shadow_payload:
        lessons = ["Shadow registrado sin fills reales todavia; quedan pendientes reconciliation y post-market del primer fill."]

    shadow_buys = list(shadow_payload.get("would_buy") or []) if shadow_payload else []
    pipeline = {
        "signal_outcomes": {"status": "ok" if cohort_rows else "pending", "count": len(cohort_rows)},
        "learning_observations": {"status": "ok" if session_rows else "pending", "count": len(session_rows)},
        "broker_reconciliation": {
            "status": "ok" if executed else "pending_first_fill",
            "fills_linked": len(executed),
        },
        "post_market_review": {
            "status": "ok" if executed and post_market_same_session else "pending_first_fill",
            "available": post_market_same_session,
        },
        "memories_lessons": {
            "status": "ok" if executed and operational_same_session else "pending_first_fill",
            "available": operational_same_session,
        },
        "findings_to_proposals": {
            "status": "ok" if proposal_candidates else "wired_no_actionable_evidence",
            "proposal_candidates": len(proposal_candidates),
        },
    }
    return {
        "available": bool(cohort_rows or shadow_payload),
        "session_date": session_date,
        "signals": len(cohort_rows),
        "observations": len(session_rows),
        "trades": len(executed),
        "pnl": {
            "realized": 0.0,
            "open": _round(sum(clean_open_pl), 2) if clean_open_pl else None,
        },
        "matured_outcomes": {
            "3d": len(matured_3d),
        },
        "shadow": {
            "available": bool(shadow_payload),
            "would_buy": shadow_buys,
            "kill_switch_active": bool((shadow_payload.get("operational_kill_switch") or {}).get("kill_switch_active")),
        },
        "lessons": lessons[:5],
        "adjustments": {
            "proposal_candidates": proposal_candidates,
            "status": "opero pero no aprendio nada nuevo." if executed and not proposal_candidates else None,
        },
        "pipeline": pipeline,
    }


def _build_digest(
    observations: list[dict[str, Any]],
    health: dict[str, Any],
    candidates: list[dict[str, Any]],
    llm_status: dict[str, Any],
    pre_earnings_context: dict[str, Any] | None = None,
    same_session_ledger: dict[str, Any] | None = None,
    learning_experiment_section: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stats_1d = _feature_bucket_stats(observations, 1, min_samples=3)
    stats_3d = _feature_bucket_stats(observations, 3, min_samples=3)
    stats_5d = _feature_bucket_stats(observations, 5, min_samples=3)
    weak_tags = list(reversed(sorted(stats_3d, key=lambda item: (item["avg_return"] if item["avg_return"] is not None else 999))))[:0]
    weak_tags = sorted(
        [item for item in stats_3d if item.get("avg_return") is not None],
        key=lambda item: item["avg_return"],
    )[:5]
    strong_tags = [item for item in stats_3d if (item.get("avg_return") or -999) > 0][:5]
    duplicate_symbols = [
        {"signal_date": item["signal_date"], "symbol": item["symbol"], "duplicates": item["duplicate_count"]}
        for item in observations
        if int(item.get("duplicate_count") or 0) > 0
    ][:20]
    setup_rows = _setup_stats(observations, 3)
    symbol_setup_memory_3d = _symbol_setup_memory(observations, 3)
    priors_1d = _setup_priors(observations, 1, min_samples=3)
    priors_3d = _setup_priors(observations, 3, min_samples=3)
    confidence_3d = _confidence_calibration(observations, 3, min_samples=3)
    prior_accuracy_3d = _prior_accuracy(observations, 3, min_samples=3)
    entry_quality_filter_calibration_3d = _blocked_filter_calibration(
        observations,
        3,
        flag_key="blocked_entry_quality",
        min_samples=3,
    )
    backtest_filter_calibration_3d = _blocked_filter_calibration(
        observations,
        3,
        flag_key="blocked_backtest",
        min_samples=3,
    )
    same_session_shadow = _same_session_shadow_candidates(same_session_ledger)
    active_runtime_policies = []
    if same_session_shadow:
        active_runtime_policies.append(
            {
                "policy_id": "intraday_same_session_momentum_promotion",
                "name": "Promote repeated intraday momentum before LLM",
                "status": "guarded_active",
                "notes": (
                    "Activa solo en ranking previo al LLM cuando hay repeticion intradia fuerte "
                    "y no relaja entry-quality ni riesgo."
                ),
            }
        )
    shadow_candidates = [
        {
            "policy_id": item["policy_id"],
            "name": item["name"],
            "tag": (item.get("evidence") or {}).get("tag"),
            "metrics": item.get("metrics", {}),
        }
        for item in candidates
        if item["status"] == "shadow"
    ]
    shadow_candidates.extend(
        {
            "policy_id": item["policy_id"],
            "name": item["name"],
            "tag": "intraday_same_session_momentum",
            "metrics": item.get("metrics", {}),
        }
        for item in same_session_shadow
    )
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "llm_status": llm_status,
        "llm_status_line": llm_status.get("status_line"),
        "summary": {
            "canonical_observations": health.get("canonical_observations", 0),
            "duplicate_ratio": health.get("duplicate_ratio", 0.0),
            "executed_observations": health.get("executed_observations", 0),
            "horizon_coverage": health.get("horizon_coverage", {}),
            "decision_error_rates_3d": _decision_error_rates(observations, 3),
        },
        "strong_buckets_1d": stats_1d[:5],
        "strong_buckets_3d": strong_tags[:5],
        "weak_buckets_3d": weak_tags,
        "strong_buckets_5d": stats_5d[:5],
        "setup_stats_3d": setup_rows,
        "symbol_setup_memory_3d": symbol_setup_memory_3d[:30],
        "setup_priors_1d": priors_1d[:20],
        "setup_priors_3d": priors_3d[:20],
        "confidence_calibration_3d": confidence_3d,
        "prior_accuracy_3d": prior_accuracy_3d[:20],
        "entry_quality_filter_calibration_3d": entry_quality_filter_calibration_3d,
        "backtest_filter_calibration_3d": backtest_filter_calibration_3d,
        "pre_earnings": pre_earnings_context or {"available": False},
        "learning_experiment_yesterday": learning_experiment_section or {"available": False},
        "active_or_guarded_policies": [
            {
                "policy_id": item["policy_id"],
                "name": item["name"],
                "status": item["status"],
                "notes": item["notes"],
            }
            for item in candidates
            if item["status"] in {"active", "guarded_active"}
        ]
        + active_runtime_policies,
        "shadow_candidates": shadow_candidates[:8],
        "duplicate_symbols_recent": duplicate_symbols,
        "same_session_opportunity_ledger": same_session_ledger or {"available": False},
        "guidance": _daily_guidance(
            health,
            candidates,
            weak_tags,
            pre_earnings_context,
            entry_quality_filter_calibration_3d,
            same_session_shadow,
        ),
    }


def build_learning_daily_run(
    settings: Settings,
    store: Store,
    reports_dir: Path,
    run_id: str,
    *,
    since_date: str = DEFAULT_DAILY_LEARNING_START,
    end_date: str | None = None,
    compact: bool = True,
) -> dict[str, Any]:
    update_result = update_signal_outcomes(settings, store, since_date=since_date, limit=LEDGER_LIMIT)
    rows = _rebuild_signal_cohorts(store, since_date=since_date, end_date=end_date)
    observations = _materialize_observations(store, rows)
    session_dates = _session_dates(rows)
    session_date = end_date or (session_dates[-1] if session_dates else since_date)
    health = _build_health(observations, rows)
    policy_candidates = _upsert_policy_candidates(store, observations, session_date)
    llm_status = _llm_status_snapshot(store)
    pre_earnings_context = load_pre_earnings_learning_context(reports_dir.parent)
    same_session_ledger = _build_same_session_opportunity_ledger(rows, store, session_date)
    learning_experiment_section = _build_learning_experiment_section(
        store,
        reports_dir,
        since_date=since_date,
        end_date=session_date,
    )
    digest = _build_digest(
        observations,
        health,
        policy_candidates,
        llm_status,
        pre_earnings_context,
        same_session_ledger,
        learning_experiment_section,
    )
    comparison = _compare_policy_rows(rows, "proposed") if rows else {}
    summary_payload = {
        "session_date": session_date,
        "health": health,
        "digest": digest,
        "policy_comparison": comparison,
    }
    store.upsert_learning_daily_summary(
        summary_id=f"daily:{session_date}",
        session_date=session_date,
        kind="daily_learning",
        payload=summary_payload,
    )
    latest_digest_path = reports_dir / "latest_daily_learning_digest.json"
    latest_digest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_digest_path.write_text(json.dumps(digest, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    report = {
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "period": {"from": since_date, "to": end_date or session_date},
        "session_date": session_date,
        "update_result": update_result,
        "health": health,
        "digest": digest,
        "policy_candidates": policy_candidates,
        "policy_comparison": comparison,
        "observations_summary": {
            "observations": len(observations),
            "duplicates_removed": health.get("duplicate_signals", 0),
        },
    }
    if not compact:
        report["observations"] = observations
        report["raw_signal_rows"] = rows
    return _write_report(report, reports_dir, "learning_daily_run", run_id)


def build_learning_health_report(
    store: Store,
    reports_dir: Path,
    run_id: str,
    *,
    since_date: str = DEFAULT_DAILY_LEARNING_START,
    end_date: str | None = None,
) -> dict[str, Any]:
    observations = store.learning_observations(since_date=since_date, end_date=end_date, limit=LEDGER_LIMIT)
    health = _build_health(observations, observations)
    report = {
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "period": {"from": since_date, "to": end_date or max((item["signal_date"] for item in observations), default=since_date)},
        "health": health,
        "recent_duplicates": [item for item in observations if int(item.get("duplicate_count") or 0) > 0][:20],
    }
    return _write_report(report, reports_dir, "learning_health", run_id)


def build_learning_digest_report(
    store: Store,
    reports_dir: Path,
    run_id: str,
    *,
    since_date: str = DEFAULT_DAILY_LEARNING_START,
    end_date: str | None = None,
) -> dict[str, Any]:
    observations = store.learning_observations(since_date=since_date, end_date=end_date, limit=LEDGER_LIMIT)
    health = _build_health(observations, observations)
    candidates = store.learning_policy_candidates(limit=100)
    llm_status = _llm_status_snapshot(store)
    pre_earnings_context = load_pre_earnings_learning_context(reports_dir.parent)
    learning_experiment_section = _build_learning_experiment_section(
        store,
        reports_dir,
        since_date=since_date,
        end_date=end_date,
    )
    digest = _build_digest(
        observations,
        health,
        candidates,
        llm_status,
        pre_earnings_context,
        None,
        learning_experiment_section,
    )
    report = {
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "period": {"from": since_date, "to": end_date or max((item["signal_date"] for item in observations), default=since_date)},
        "digest": digest,
    }
    latest_digest_path = reports_dir / "latest_daily_learning_digest.json"
    latest_digest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_digest_path.write_text(json.dumps(digest, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    return _write_report(report, reports_dir, "learning_digest", run_id)


def build_policy_candidates_report(
    store: Store,
    reports_dir: Path,
    run_id: str,
) -> dict[str, Any]:
    candidates = store.learning_policy_candidates(limit=200)
    report = {
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "policies": len(candidates),
            "shadow": sum(1 for item in candidates if item["status"] == "shadow"),
            "guarded_active": sum(1 for item in candidates if item["status"] == "guarded_active"),
            "active": sum(1 for item in candidates if item["status"] == "active"),
        },
        "policies": candidates,
    }
    return _write_report(report, reports_dir, "policy_candidates", run_id)


def build_learning_promotions_report(
    store: Store,
    reports_dir: Path,
    run_id: str,
) -> dict[str, Any]:
    candidates = store.learning_policy_candidates(limit=200)
    policies = []
    for candidate in candidates:
        policies.append(
            {
                **candidate,
                "evaluations": store.learning_policy_evaluations(policy_id=candidate["policy_id"], limit=20),
            }
        )
    report = {
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "promoted": sum(1 for item in policies if item.get("promoted_at")),
            "guarded_active": sum(1 for item in policies if item["status"] == "guarded_active"),
            "shadow": sum(1 for item in policies if item["status"] == "shadow"),
        },
        "policies": policies,
    }
    return _write_report(report, reports_dir, "learning_promotions", run_id)


def load_daily_learning_context(data_dir: Path) -> dict[str, Any]:
    path = data_dir / "reports" / "latest_daily_learning_digest.json"
    if not path.exists():
        return {"available": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"available": False}
    return {
        "available": True,
        "as_of": payload.get("as_of"),
        "llm_status": payload.get("llm_status", {}),
        "llm_status_line": payload.get("llm_status_line"),
        "summary": payload.get("summary", {}),
        "guidance": payload.get("guidance", []),
        "pre_earnings": payload.get("pre_earnings", {"available": False}),
        "learning_experiment_yesterday": payload.get("learning_experiment_yesterday", {"available": False}),
        "active_or_guarded_policies": payload.get("active_or_guarded_policies", []),
        "weak_buckets_3d": payload.get("weak_buckets_3d", [])[:5],
        "strong_buckets_3d": payload.get("strong_buckets_3d", [])[:5],
        "setup_stats_3d": payload.get("setup_stats_3d", [])[:8],
        "symbol_setup_memory_3d": payload.get("symbol_setup_memory_3d", [])[:20],
        "setup_priors_1d": payload.get("setup_priors_1d", [])[:20],
        "setup_priors_3d": payload.get("setup_priors_3d", [])[:20],
        "confidence_calibration_3d": payload.get("confidence_calibration_3d", [])[:8],
        "prior_accuracy_3d": payload.get("prior_accuracy_3d", [])[:20],
        "entry_quality_filter_calibration_3d": payload.get("entry_quality_filter_calibration_3d", {}),
        "backtest_filter_calibration_3d": payload.get("backtest_filter_calibration_3d", {}),
    }
