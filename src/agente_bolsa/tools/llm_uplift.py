"""Read-only LLM uplift measurement over mature executed outcomes.

R2c pre-registered comparison: expectancy of LLM-selected executed buys
versus deterministically-selected executed buys, net of a fixed cost rate.
Grouping uses ONLY the causal `llm_selected` flag from
`decision_context_snapshot` (embedded in the observation features or
joined by exact `best_signal_id`); free-text `source` is never used as
a proxy (P-L59B-T lesson). This module never decides, promotes, trades
or writes operational state; it only reads and reports.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .decision_context import normalize_llm_selected
from .learning_scoreboard import _mature_return
from .reporting import write_json_report

MIN_UPLIFT_DECISIONS = 30
MIN_ARM_DECISIONS = 10
MIN_SNAPSHOT_COVERAGE = 0.70
DEFAULT_COST_RATE = 0.001


def _snapshot_for(row: dict[str, Any], snapshots_by_signal: dict[str, Any]) -> dict[str, Any]:
    embedded = (row.get("features") or {}).get("decision_context_snapshot") or {}
    if isinstance(embedded, dict) and embedded:
        return embedded
    signal_id = row.get("best_signal_id")
    joined = snapshots_by_signal.get(str(signal_id)) if signal_id else None
    return joined if isinstance(joined, dict) else {}


def _arm_of(row: dict[str, Any], snapshots_by_signal: dict[str, Any]) -> str:
    snapshot = _snapshot_for(row, snapshots_by_signal)
    if not snapshot:
        return "unattached"
    value = normalize_llm_selected(snapshot.get("llm_selected"))
    if value is True:
        return "llm"
    if value is False:
        return "deterministic"
    return "unattached"


def _arm_stats(values: list[float], dates: list[str], symbols: list[str]) -> dict[str, Any]:
    n = len(values)
    if not n:
        return {"n": 0, "expectancy_net": None, "hit_rate": None,
                "sessions": 0, "top_symbol_share": None}
    expectancy = round(sum(values) / n, 4)
    hit_rate = round(sum(1 for value in values if value > 0) / n, 4)
    symbol_counts: dict[str, int] = {}
    for symbol in symbols:
        symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
    top_share = round(max(symbol_counts.values()) / n, 4)
    return {
        "n": n,
        "expectancy_net": expectancy,
        "hit_rate": hit_rate,
        "sessions": len(set(dates)),
        "top_symbol_share": top_share,
    }


def build_llm_uplift_report(
    store: Any,
    reports_dir: Path,
    run_id: str,
    *,
    since_date: str = "2026-07-07",
    end_date: str | None = None,
    horizon: int = 5,
    cost_rate: float = DEFAULT_COST_RATE,
    limit: int = 200000,
) -> dict[str, Any]:
    outcomes = store.signal_outcomes(limit=limit, since_date=since_date)
    snapshots_by_signal = {
        str(row.get("signal_id")): ((row.get("features") or {}).get("decision_context_snapshot") or {})
        for row in outcomes
        if row.get("signal_id")
        and isinstance((row.get("features") or {}).get("decision_context_snapshot"), dict)
        and (row.get("features") or {}).get("decision_context_snapshot")
    }
    observations = store.learning_observations(since_date=since_date, end_date=end_date, limit=limit)

    arms: dict[str, list[float]] = {"llm": [], "deterministic": []}
    arm_dates: dict[str, list[str]] = {"llm": [], "deterministic": []}
    arm_symbols: dict[str, list[str]] = {"llm": [], "deterministic": []}
    mature_total = 0
    unattached = 0
    for row in observations:
        if not row.get("executed_buy"):
            continue
        value = _mature_return(row, horizon)
        if value is None:
            continue
        mature_total += 1
        arm = _arm_of(row, snapshots_by_signal)
        if arm == "unattached":
            unattached += 1
            continue
        net_value = value - cost_rate
        arms[arm].append(net_value)
        arm_dates[arm].append(str(row.get("signal_date") or ""))
        arm_symbols[arm].append(str(row.get("symbol") or ""))

    llm_stats = _arm_stats(arms["llm"], arm_dates["llm"], arm_symbols["llm"])
    det_stats = _arm_stats(arms["deterministic"], arm_dates["deterministic"], arm_symbols["deterministic"])
    uplift = None
    if llm_stats["expectancy_net"] is not None and det_stats["expectancy_net"] is not None:
        uplift = round(llm_stats["expectancy_net"] - det_stats["expectancy_net"], 4)
    attached = llm_stats["n"] + det_stats["n"]
    coverage = round(attached / mature_total, 4) if mature_total else None

    reasons: list[str] = []
    if mature_total < MIN_UPLIFT_DECISIONS:
        reasons.append(f"mature_executed {mature_total}<{MIN_UPLIFT_DECISIONS}")
    if coverage is None or coverage < MIN_SNAPSHOT_COVERAGE:
        reasons.append(f"snapshot_coverage {coverage}<{MIN_SNAPSHOT_COVERAGE}")
    if llm_stats["n"] < MIN_ARM_DECISIONS:
        reasons.append(f"llm_arm {llm_stats['n']}<{MIN_ARM_DECISIONS}")
    if det_stats["n"] < MIN_ARM_DECISIONS:
        reasons.append(f"deterministic_arm {det_stats['n']}<{MIN_ARM_DECISIONS}")
    verdict = "insufficient_sample" if reasons else "sufficient_sample"

    report = {
        "schema_version": 1,
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "period": {"from": since_date, "to": end_date},
        "horizon": horizon,
        "cost_rate": cost_rate,
        "verdict": verdict,
        "verdict_reasons": reasons,
        "mature_executed": mature_total,
        "unattached": unattached,
        "snapshot_coverage": coverage,
        "llm": llm_stats,
        "deterministic": det_stats,
        "uplift_net": uplift,
    }
    return write_json_report(
        report,
        reports_dir,
        "llm_uplift",
        run_id,
        latest_filename="latest_llm_uplift.json",
    )
