"""Prospective, observational P-L27D reward/risk cohort.

The cohort only records existing long signals.  It never alters a decision,
geometry, gate, order, execution path, or historical observation.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any

from agente_bolsa.market_calendar import MarketCalendar
from agente_bolsa.storage import Store

from .reporting import write_json_report

SCHEMA_VERSION = "p-l27d.rr-cohort.v2"
LEGACY_SCHEMA_VERSION = "p-l27d.rr-cohort.v1"
COHORT_FEATURE_KEY = "rr_cohort_p_l27d"
COHORT_START = "2026-07-13"
HYPOTHESIS_ID = "pl27d_rr_1_1_5_vs_1_5_2"
MIN_SAMPLE = 300
MIN_CLUSTERS = 100
MAX_CONTROLS = 3
MAX_SESSIONS = 40
CAPACITY_REASONS = {
    "max_orders_per_cycle_reached",
    "max_daily_buy_orders_reached",
    "low_sample_daily_quota_exhausted",
}
CONTRACT = {
    "hypothesis_id": HYPOTHESIS_ID,
    "change_class": "observability",
    "horizon_sessions_xnys": 10,
    "arms": {"A": {"rr_gte": 1.0, "rr_lt": 1.5}, "B": {"rr_gte": 1.5, "rr_lt": 2.0}},
    "min_sample_per_arm": MIN_SAMPLE,
    "min_symbol_date_clusters_per_arm": MIN_CLUSTERS,
    "max_top_1_share": 0.20,
    "max_sessions": MAX_SESSIONS,
    "primary_metrics": ["mean_return_10d_a_minus_b", "median_return_10d_a_minus_b", "positive_rate_a_minus_b"],
    "success": "las tres diferencias positivas en dos ventanas cronologicas maduras consecutivas con muestra, clusters, concentracion, linaje y control validos",
    "invalidation": "cambio de signo en dos ventanas maduras consecutivas, muestra insuficiente, concentracion, control no comparable o contaminacion/falta de linaje",
    "unavailable_metrics": ["costs", "alpha", "spy", "executed_pnl"],
}


def sync_rr_cohort_observations(store: Store, observations: list[dict[str, Any]]) -> dict[str, Any]:
    """Append the immutable cohort card to eligible prospective observations."""
    all_observations = store.learning_observations(since_date=COHORT_START, limit=200_000)
    controls_by_key = _control_candidates(all_observations)
    result = Counter()
    pending: list[dict[str, Any]] = []
    for observation in observations:
        if str(observation.get("signal_date") or "") < COHORT_START:
            continue
        card, reason = _cohort_card(observation, controls_by_key)
        features = dict(observation.get("features") or {})
        existing = features.get(COHORT_FEATURE_KEY)
        if existing and isinstance(existing, dict) and existing.get("hypothesis_id") == HYPOTHESIS_ID:
            card["observation_id"] = existing.get("observation_id") or card.get("observation_id")
        features[COHORT_FEATURE_KEY] = card
        pending.append({**observation, "features": features})
        result["recorded" if reason is None else f"excluded_{reason}"] += 1
    batch_method = getattr(store, "upsert_learning_observations_batch", None)
    if pending and callable(batch_method):
        result["batch"] = {"phase": "rr_sync", **batch_method(pending)}
    elif pending:
        # Compatibilidad con dobles de test/Stores legacy sin la API nueva.
        for item in pending:
            store.upsert_learning_observation(item)
        result["batch"] = {
            "phase": "rr_sync",
            "status": "legacy_fallback",
            "received": len(pending),
            "written": len(pending),
            "chunks_completed": None,
        }
    else:
        result["batch"] = {
            "phase": "rr_sync",
            "status": "available",
            "received": 0,
            "written": 0,
            "chunks_completed": 0,
        }
    return dict(result)


def build_rr_cohort_report(
    store: Store,
    *,
    start: str | None = None,
    end: str | None = None,
    window: str = "all",
    include_legacy_context: bool = False,
) -> dict[str, Any]:
    """Read the prospective cards and evaluate only their pre-registered contract."""
    if window not in {"all", "first", "second"}:
        return _unavailable("window_invalid", {"window": window})
    start = start or COHORT_START
    observations = store.learning_observations(since_date=start, end_date=end, limit=200_000)
    cards = [dict((item.get("features") or {}).get(COHORT_FEATURE_KEY) or {}) for item in observations]
    cards = [card for card in cards if card.get("hypothesis_id") == HYPOTHESIS_ID]
    if end:
        cards = [card for card in cards if str(card.get("signal_date") or "") <= end]
    first, second = _split_windows(cards)
    selected = {"all": cards, "first": first, "second": second}[window]
    as_of = _report_as_of(end)
    report = {
        "schema_version": SCHEMA_VERSION,
        "observational_only": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "contract": CONTRACT,
        "cohort_start": COHORT_START,
        "parameters": {"from": start, "to": end, "window": window, "include_legacy_context": include_legacy_context},
        "collection_sessions_completed": _collection_sessions_completed(COHORT_START, as_of),
        "collection_max_sessions": MAX_SESSIONS,
        "calendar": "XNYS",
        "views": {
            "selected": _view(selected, as_of=as_of),
            "first": _view(first, as_of=as_of),
            "second": _view(second, as_of=as_of),
        },
        "exclusions": _exclusions(cards),
        "criteria": _criteria(first, second, as_of=as_of),
        "legacy_context": _legacy_context(store) if include_legacy_context else None,
        "earliest_possible_first_maturity_date": nth_xnys_session_after(COHORT_START, 10),
        "next_possible_maturity_date": _next_possible_maturity_date(cards),
        "cohort_evaluation_date": "unavailable",
        "warnings": [
            "Cohorte prospectiva observacional: no modifica geometria, seleccion, gates, ordenes ni ejecucion.",
            "P&L, costes, alpha y SPY permanecen unavailable sin evidencia comparable.",
        ],
    }
    report["overall_status"] = _overall_status(cards, first, second, report["criteria"])
    report["evaluation_status"] = report["overall_status"]
    report["content_hash"] = _content_hash(report)
    return report


def write_rr_cohort_report(store: Store, reports_dir: Any, run_id: str) -> dict[str, Any]:
    return write_json_report(
        build_rr_cohort_report(store),
        reports_dir,
        "rr_cohort",
        run_id,
        latest_filename="latest_rr_cohort.json",
    )


def rr_cohort_digest_summary(store: Store) -> dict[str, Any]:
    report = build_rr_cohort_report(store)
    selected = report["views"]["selected"]
    return {
        "status": report["overall_status"],
        "collection_sessions_completed": report["collection_sessions_completed"],
        "mature_by_arm": {arm: selected["arms"][arm]["matured_count"] for arm in ("A", "B")},
        "lineage_coverage": selected["lineage_coverage"],
        "control_coverage": selected["control_coverage"],
        "criteria_pending": [key for key, value in report["criteria"].items() if value is not True],
        "next_possible_maturity_date": report["next_possible_maturity_date"],
    }


def _cohort_card(
    observation: dict[str, Any],
    controls_by_key: dict[tuple[str, str], list[dict[str, Any]]],
) -> tuple[dict[str, Any], str | None]:
    features = dict(observation.get("features") or {})
    lineage = dict(features.get("decision_lineage") or {})
    outcome = dict(observation.get("outcome") or {})
    direction = str(features.get("direction") or "").lower()
    entry, stop, take = features.get("entry_price"), features.get("stop_loss"), features.get("take_profit")
    reason = _eligibility_reason(observation, direction, entry, stop, take, lineage)
    geometry = _geometry(entry, stop, take) if reason is None else {}
    arm = _arm(geometry.get("reward_risk_ratio")) if geometry else None
    if reason is None and arm is None:
        reason = "rr_outside_contract"
    maturity = bool((outcome.get("matured_horizons") or {}).get("10d")) and _number(outcome.get("return_10d"))
    cycle_id = lineage.get("cycle_id")
    candidates = controls_by_key.get((str(cycle_id or ""), str(observation.get("signal_date") or "")), [])
    controls = [
        item
        for item in candidates
        if item.get("observation_id") != observation.get("observation_id")
        and _same_gates_and_theory(observation, item)
    ][:MAX_CONTROLS]
    control_reason = None if controls else "no_comparable_control_same_cycle"
    return ({
        "observation_id": f"rrcohort:{observation.get('observation_id')}",
        "schema_version": SCHEMA_VERSION,
        "temporal_semantics": "strict_post_signal_sessions",
        "hypothesis_id": HYPOTHESIS_ID,
        "cohort_start": COHORT_START,
        "signal_id": observation.get("best_signal_id"),
        "lineage_id": lineage.get("lineage_id"),
        "lineage_status": lineage.get("lineage_status") or "legacy_unverified",
        "cycle_id": cycle_id,
        "signal_date": observation.get("signal_date"),
        "timestamp": observation.get("first_seen_at"),
        "symbol": observation.get("symbol"),
        "direction": direction or None,
        "entry_price": entry,
        "stop_loss": stop,
        "take_profit": take,
        **geometry,
        "rr_arm": arm,
        "strategy_name": lineage.get("strategy_name"),
        "strategy_version": lineage.get("strategy_version"),
        "decision_source": lineage.get("decision_source"),
        "candidate_rank": lineage.get("candidate_rank"),
        "setup_quality": features.get("setup_quality"),
        "executed": bool(observation.get("executed_buy")),
        "comparable_control_available": bool(controls),
        "comparable_control_reason": control_reason,
        "comparable_control_ids": [item.get("observation_id") for item in controls],
        "maturity_status_10d": "mature" if maturity else "immature",
        "return_10d": float(outcome["return_10d"]) if maturity else None,
        "outcome_source": outcome.get("source") or "signal_outcomes",
        "data_quality_warnings": [] if reason is None else [reason],
        "eligibility_status": "eligible" if reason is None else "excluded",
        "exclusion_reason": reason,
    }, reason)


def _control_candidates(observations: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    result: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in observations:
        features = item.get("features") or {}
        lineage = features.get("decision_lineage") or {}
        cycle_id = str(lineage.get("cycle_id") or "")
        if not cycle_id or not _control_eligible(item):
            continue
        result.setdefault((cycle_id, str(item.get("signal_date") or "")), []).append(item)
    for key, items in result.items():
        result[key] = sorted(items, key=_control_sort_key)[:MAX_CONTROLS]
    return result


def _control_eligible(item: dict[str, Any]) -> bool:
    features, gate, execution = item.get("features") or {}, item.get("gate") or {}, item.get("execution") or {}
    lineage = features.get("decision_lineage") or {}
    if str(lineage.get("lineage_status") or "") != "verified" or bool(item.get("executed_buy")):
        return False
    if str(features.get("direction") or "").lower() != "long" or not _geometry(features.get("entry_price"), features.get("stop_loss"), features.get("take_profit")):
        return False
    if str(item.get("decision") or "") != "approved_buy":
        return False
    reason = str(execution.get("reason") or gate.get("execution", {}).get("reason") or "")
    return reason in CAPACITY_REASONS or str(gate.get("execution", {}).get("status") or "") == "approved_not_planned"


def _control_sort_key(item: dict[str, Any]) -> tuple[float, str]:
    lineage = (item.get("features") or {}).get("decision_lineage") or {}
    rank = lineage.get("candidate_rank")
    return (float(rank) if _number(rank) else math.inf, str(item.get("observation_id") or ""))


def _same_gates_and_theory(primary: dict[str, Any], control: dict[str, Any]) -> bool:
    """Keep control selection descriptive and limited to comparable candidates."""
    primary_features = primary.get("features") or {}
    control_features = control.get("features") or {}
    for key in ("entry_price", "stop_loss", "take_profit"):
        if not _number(primary_features.get(key)) or not _number(control_features.get(key)):
            return False
    primary_gate = primary.get("gate") or {}
    control_gate = control.get("gate") or {}
    return (
        primary_features.get("entry_price") == control_features.get("entry_price")
        and primary_features.get("stop_loss") == control_features.get("stop_loss")
        and primary_features.get("take_profit") == control_features.get("take_profit")
        and primary_gate.get("gate_status") == control_gate.get("gate_status")
    )


def _eligibility_reason(observation: dict[str, Any], direction: str, entry: Any, stop: Any, take: Any, lineage: dict[str, Any]) -> str | None:
    if direction != "long":
        return "direction_not_long"
    if not _geometry(entry, stop, take):
        return "geometry_invalid"
    if not observation.get("best_signal_id"):
        return "signal_id_missing"
    if str(lineage.get("lineage_status") or "") != "verified" or not lineage.get("lineage_id"):
        return "lineage_not_verified"
    if not lineage.get("cycle_id"):
        return "cycle_id_missing"
    if not observation.get("symbol") or not observation.get("signal_date"):
        return "symbol_or_date_missing"
    return None


def _geometry(entry: Any, stop: Any, take: Any) -> dict[str, float]:
    if not all(_number(value) for value in (entry, stop, take)) or entry <= 0 or stop >= entry or take <= entry:
        return {}
    risk = float(entry) - float(stop)
    reward = float(take) - float(entry)
    return {"risk_distance": risk, "reward_distance": reward, "stop_distance_pct": risk / float(entry), "take_distance_pct": reward / float(entry), "reward_risk_ratio": reward / risk}


def _arm(value: Any) -> str | None:
    if not _number(value):
        return None
    if 1.0 <= value < 1.5:
        return "A"
    if 1.5 <= value < 2.0:
        return "B"
    return None


def _split_windows(cards: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split only mature observations, keeping every signal date intact."""
    cards = [card for card in cards if card.get("maturity_status_10d") == "mature"]
    dates = sorted({str(card.get("signal_date") or "") for card in cards if card.get("signal_date")})
    midpoint = (len(dates) + 1) // 2
    first_dates = set(dates[:midpoint])
    return [card for card in cards if card.get("signal_date") in first_dates], [card for card in cards if card.get("signal_date") not in first_dates]


def _view(cards: list[dict[str, Any]], *, as_of: datetime) -> dict[str, Any]:
    cards = [_temporal_card(card, as_of) for card in cards]
    eligible = [card for card in cards if card.get("eligibility_status") == "eligible"]
    mature = [card for card in eligible if card.get("maturity_status_10d") == "mature"]
    arms = {arm: _arm_metrics([card for card in mature if card.get("rr_arm") == arm]) for arm in ("A", "B")}
    return {
        "raw_count": len(cards),
        "eligible_count": len(eligible),
        "immature_count": len(eligible) - len(mature),
        "mature_count": len(mature),
        "arms": arms,
        "differences_a_minus_b": _differences(arms),
        "lineage_coverage": _ratio(sum(card.get("lineage_status") == "verified" for card in eligible), len(eligible)),
        "control_coverage": _ratio(sum(bool(card.get("comparable_control_available")) for card in eligible), len(eligible)),
        "post_signal_sessions_completed_by_observation": {
            str(card.get("observation_id")): card.get("post_signal_sessions_completed") for card in eligible
        },
        "temporal_semantics_by_observation": {
            str(card.get("observation_id")): card.get("temporal_semantics") for card in cards
        },
    }


def _arm_metrics(cards: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [float(card["return_10d"]) for card in cards if _number(card.get("return_10d"))]
    symbols, dates = Counter(str(card.get("symbol") or "") for card in cards), Counter(str(card.get("signal_date") or "") for card in cards)
    return {"matured_count": len(returns), "symbol_date_clusters": len({(card.get("symbol"), card.get("signal_date")) for card in cards}), "unique_symbols": len(symbols), "unique_dates": len(dates), "top_1_symbol_share": _ratio(max(symbols.values(), default=0), len(cards)), "top_1_date_share": _ratio(max(dates.values(), default=0), len(cards)), "mean_return_10d": _mean(returns), "median_return_10d": _median(returns), "positive_rate": _ratio(sum(value > 0 for value in returns), len(returns))}


def _differences(arms: dict[str, dict[str, Any]]) -> dict[str, float | None]:
    return {"mean_return_10d": _difference(arms["A"].get("mean_return_10d"), arms["B"].get("mean_return_10d")), "median_return_10d": _difference(arms["A"].get("median_return_10d"), arms["B"].get("median_return_10d")), "positive_rate": _difference(arms["A"].get("positive_rate"), arms["B"].get("positive_rate"))}


def _criteria(first: list[dict[str, Any]], second: list[dict[str, Any]], *, as_of: datetime) -> dict[str, bool | None]:
    views = [_view(first, as_of=as_of), _view(second, as_of=as_of)]
    pending = {
        "two_chronological_windows": None,
        "sample_clusters_concentration": None,
        "lineage": None,
        "control": None,
        "all_differences_positive": None,
        "signs_consecutive": None,
    }
    if not first or not second:
        return pending
    def arm_ok(view: dict[str, Any], arm: str) -> bool:
        item = view["arms"][arm]
        return item["matured_count"] >= MIN_SAMPLE and item["symbol_date_clusters"] >= MIN_CLUSTERS and (item["top_1_symbol_share"] or 1) < .2 and (item["top_1_date_share"] or 1) < .2
    diffs = [view["differences_a_minus_b"] for view in views]
    return {
        "two_chronological_windows": True,
        "sample_clusters_concentration": all(arm_ok(view, arm) for view in views for arm in ("A", "B")),
        "lineage": all((view["lineage_coverage"] or 0) == 1 for view in views),
        "control": all((view["control_coverage"] or 0) > 0 for view in views),
        "all_differences_positive": all(all((diff.get(key) or 0) > 0 for key in diff) for diff in diffs),
        "signs_consecutive": all((diffs[0].get(key) or 0) * (diffs[1].get(key) or 0) > 0 for key in diffs[0]),
    }


def _overall_status(cards: list[dict[str, Any]], first: list[dict[str, Any]], second: list[dict[str, Any]], criteria: dict[str, bool | None]) -> str:
    eligible = [card for card in cards if card.get("eligibility_status") == "eligible"]
    mature = [card for card in eligible if card.get("maturity_status_10d") == "mature"]
    if not cards:
        return "collecting"
    if not mature:
        return "immature"
    if any(card.get("lineage_status") != "verified" for card in eligible):
        return "unavailable"
    if any(criteria.get(key) is None for key in criteria):
        return "immature"
    if criteria.get("sample_clusters_concentration") is False:
        return "insufficient_sample"
    if criteria.get("all_differences_positive") is False and criteria.get("signs_consecutive") is False:
        return "invalidated"
    if all(value is True for value in criteria.values()):
        return "descriptively_supported"
    return "not_supported"


def _exclusions(cards: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(card.get("exclusion_reason") for card in cards if card.get("exclusion_reason")).items()))


def _legacy_context(store: Store) -> dict[str, Any]:
    rows = store.signal_outcomes(limit=200_000)
    return {"status": "context_only", "primary_excluded": True, "signal_outcomes_rows_read": len(rows), "reason": "legacy_unverified_no_se_reinterpreta_como_cohorte_prospectiva"}


def nth_xnys_session_after(signal_date: str, count: int) -> str | None:
    """Return the nth XNYS session strictly after ``signal_date``.

    This deliberately cannot include the signal session.  It mirrors the
    outcome producer, which only consumes bars whose date is greater than the
    signal date.
    """
    if count < 1:
        raise ValueError("count must be at least one")
    start = date.fromisoformat(signal_date) + timedelta(days=1)
    calendar = MarketCalendar()._calendar
    if calendar is None:
        day = start
        found = 0
        while found < count:
            if day.weekday() < 5:
                found += 1
                if found == count:
                    return day.isoformat()
            day += timedelta(days=1)
        return None
    schedule = calendar.schedule(start_date=start.isoformat(), end_date=(start + timedelta(days=45)).isoformat())
    return str(schedule.index[count - 1].date()) if len(schedule) >= count else None


def _report_as_of(end: str | None) -> datetime:
    if end is None:
        return datetime.now(timezone.utc)
    return _session_close_at(end) or datetime.combine(date.fromisoformat(end), datetime.max.time(), tzinfo=timezone.utc)


def _session_close_at(session_date: str) -> datetime | None:
    calendar = MarketCalendar()._calendar
    if calendar is None:
        day = date.fromisoformat(session_date)
        if day.weekday() >= 5:
            return None
        return datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=21)
    schedule = calendar.schedule(start_date=session_date, end_date=session_date)
    if schedule.empty:
        return None
    return schedule.iloc[0]["market_close"].to_pydatetime().astimezone(timezone.utc)


def _collection_sessions_completed(start: str, as_of: datetime) -> int:
    if as_of.date().isoformat() < start:
        return 0
    calendar = MarketCalendar()._calendar
    if calendar is None:
        return sum(
            1
            for index in range((as_of.date() - date.fromisoformat(start)).days + 1)
            if (date.fromisoformat(start) + timedelta(days=index)).weekday() < 5
            and _session_close_at((date.fromisoformat(start) + timedelta(days=index)).isoformat()) <= as_of
        )
    schedule = calendar.schedule(start_date=start, end_date=as_of.date().isoformat())
    return sum(close.to_pydatetime().astimezone(timezone.utc) <= as_of for close in schedule["market_close"])


def _post_signal_sessions_completed(signal_date: str, as_of: datetime) -> int:
    first_after = (date.fromisoformat(signal_date) + timedelta(days=1)).isoformat()
    if as_of.date().isoformat() < first_after:
        return 0
    calendar = MarketCalendar()._calendar
    if calendar is None:
        return sum(
            1
            for index in range((as_of.date() - date.fromisoformat(first_after)).days + 1)
            if (date.fromisoformat(first_after) + timedelta(days=index)).weekday() < 5
            and _session_close_at((date.fromisoformat(first_after) + timedelta(days=index)).isoformat()) <= as_of
        )
    schedule = calendar.schedule(start_date=first_after, end_date=as_of.date().isoformat())
    return sum(close.to_pydatetime().astimezone(timezone.utc) <= as_of for close in schedule["market_close"])


def _temporal_card(card: dict[str, Any], as_of: datetime) -> dict[str, Any]:
    result = dict(card)
    signal_date = str(result.get("signal_date") or "")
    if not signal_date:
        return result
    post_sessions = _post_signal_sessions_completed(signal_date, as_of)
    result["post_signal_sessions_completed"] = post_sessions
    result["earliest_possible_maturity_date"] = nth_xnys_session_after(signal_date, 10)
    if result.get("schema_version") != SCHEMA_VERSION:
        result["temporal_semantics"] = "legacy_semantics"
    warnings = list(result.get("data_quality_warnings") or [])
    if post_sessions >= 10 and result.get("maturity_status_10d") == "immature":
        warnings.append("calendar_maturity_due_outcome_immature")
    result["data_quality_warnings"] = list(dict.fromkeys(warnings))
    return result


def _next_possible_maturity_date(cards: list[dict[str, Any]]) -> str | None:
    dates = [
        nth_xnys_session_after(str(card.get("signal_date")), 10)
        for card in cards
        if card.get("eligibility_status") == "eligible" and card.get("maturity_status_10d") == "immature"
    ]
    return min((value for value in dates if value), default=nth_xnys_session_after(COHORT_START, 10))


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 6) if values else None


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 6) if values else None


def _difference(left: float | None, right: float | None) -> float | None:
    return round(left - right, 6) if left is not None and right is not None else None


def _content_hash(report: dict[str, Any]) -> str:
    stable = {key: value for key, value in report.items() if key not in {"generated_at", "content_hash"}}
    return hashlib.sha256(json.dumps(stable, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _unavailable(reason: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "observational_only": True, "overall_status": "unavailable", "reason": reason, "parameters": parameters}
