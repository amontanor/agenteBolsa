"""Incremental daily learning ledger, digest and conservative promotion flow."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.models import new_id
from agente_bolsa.storage import Store

from .counterfactual_analysis import _compare_policy_rows, _rebuild_signal_cohorts, _session_dates
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


def _daily_guidance(
    health: dict[str, Any],
    candidates: list[dict[str, Any]],
    weak_tags: list[dict[str, Any]],
    pre_earnings_context: dict[str, Any] | None = None,
    entry_quality_filter_calibration: dict[str, Any] | None = None,
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
        setup = _setup_name((matured[0].get("features", {}) or {}))
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


def _build_digest(
    observations: list[dict[str, Any]],
    health: dict[str, Any],
    candidates: list[dict[str, Any]],
    pre_earnings_context: dict[str, Any] | None = None,
    same_session_ledger: dict[str, Any] | None = None,
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
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "canonical_observations": health.get("canonical_observations", 0),
            "duplicate_ratio": health.get("duplicate_ratio", 0.0),
            "executed_observations": health.get("executed_observations", 0),
            "horizon_coverage": health.get("horizon_coverage", {}),
        },
        "strong_buckets_1d": stats_1d[:5],
        "strong_buckets_3d": strong_tags[:5],
        "weak_buckets_3d": weak_tags,
        "strong_buckets_5d": stats_5d[:5],
        "setup_stats_3d": setup_rows,
        "setup_priors_1d": priors_1d[:20],
        "setup_priors_3d": priors_3d[:20],
        "confidence_calibration_3d": confidence_3d,
        "prior_accuracy_3d": prior_accuracy_3d[:20],
        "entry_quality_filter_calibration_3d": entry_quality_filter_calibration_3d,
        "backtest_filter_calibration_3d": backtest_filter_calibration_3d,
        "pre_earnings": pre_earnings_context or {"available": False},
        "active_or_guarded_policies": [
            {
                "policy_id": item["policy_id"],
                "name": item["name"],
                "status": item["status"],
                "notes": item["notes"],
            }
            for item in candidates
            if item["status"] in {"active", "guarded_active"}
        ],
        "shadow_candidates": [
            {
                "policy_id": item["policy_id"],
                "name": item["name"],
                "tag": (item.get("evidence") or {}).get("tag"),
                "metrics": item.get("metrics", {}),
            }
            for item in candidates
            if item["status"] == "shadow"
        ][:8],
        "duplicate_symbols_recent": duplicate_symbols,
        "same_session_opportunity_ledger": same_session_ledger or {"available": False},
        "guidance": _daily_guidance(
            health,
            candidates,
            weak_tags,
            pre_earnings_context,
            entry_quality_filter_calibration_3d,
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
    pre_earnings_context = load_pre_earnings_learning_context(reports_dir.parent)
    same_session_ledger = _build_same_session_opportunity_ledger(rows, store, session_date)
    digest = _build_digest(observations, health, policy_candidates, pre_earnings_context, same_session_ledger)
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
    pre_earnings_context = load_pre_earnings_learning_context(reports_dir.parent)
    digest = _build_digest(observations, health, candidates, pre_earnings_context)
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
        "summary": payload.get("summary", {}),
        "guidance": payload.get("guidance", []),
        "pre_earnings": payload.get("pre_earnings", {"available": False}),
        "active_or_guarded_policies": payload.get("active_or_guarded_policies", []),
        "weak_buckets_3d": payload.get("weak_buckets_3d", [])[:5],
        "strong_buckets_3d": payload.get("strong_buckets_3d", [])[:5],
        "setup_stats_3d": payload.get("setup_stats_3d", [])[:8],
        "setup_priors_1d": payload.get("setup_priors_1d", [])[:20],
        "setup_priors_3d": payload.get("setup_priors_3d", [])[:20],
        "confidence_calibration_3d": payload.get("confidence_calibration_3d", [])[:8],
        "prior_accuracy_3d": payload.get("prior_accuracy_3d", [])[:20],
        "entry_quality_filter_calibration_3d": payload.get("entry_quality_filter_calibration_3d", {}),
        "backtest_filter_calibration_3d": payload.get("backtest_filter_calibration_3d", {}),
    }
