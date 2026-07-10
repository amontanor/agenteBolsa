"""Daily read-only research cuts for the pre-registered learning experiment."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agente_bolsa.storage import Store

from .reporting import write_json_report


def build_autonomous_research_report(
    store: Store,
    reports_dir: Path,
    run_id: str,
    *,
    since_date: str = "2026-07-07",
    end_date: str | None = None,
) -> dict[str, Any]:
    """Measure the fixed daily research agenda without changing trading policy."""

    rows = store.learning_observations(since_date=since_date, end_date=end_date, limit=200000)
    matured = [row for row in rows if _mature_return(row, 5) is not None]
    report = {
        "schema_version": 1,
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "window": {"since": since_date, "to": end_date},
        "policy_frozen": True,
        "sample": {"observations": len(rows), "matured_5d": len(matured)},
        "strategy_edge": _group_return(rows, _strategy_name),
        "pullback_promotion_gate": _pullback_promotion_gate(rows, end_date=end_date),
        "llm_vs_fallback": _group_return(rows, _decision_source),
        "low_sample_subcohort": _group_return(rows, _low_sample_label),
        "gate_effectiveness": _gate_effectiveness(rows),
        "excursion_and_exits": _excursion_summary(rows),
        "setup_and_regime": {
            "setup": _group_return(rows, _setup_name),
            "regime": _group_return(rows, _regime_name),
        },
        "decisions": [],
        "notes": [
            "Informe observacional: no cambia gates, limites, exposicion ni politica.",
            "Una dimension sin muestra madura queda unavailable; no se rellena con P/L abierto.",
        ],
    }
    return write_json_report(
        report,
        reports_dir,
        "autonomous_research",
        run_id,
        latest_filename="latest_autonomous_research.json",
    )


def _mature_return(row: dict[str, Any], horizon: int) -> float | None:
    outcome = row.get("outcome") or {}
    maturity = outcome.get("matured_horizons") or {}
    value = outcome.get(f"return_{horizon}d")
    if not bool(maturity.get(f"{horizon}d")) or not isinstance(value, (int, float)):
        return None
    return float(value) - 0.001


def _pullback_promotion_gate(rows: list[dict[str, Any]], *, end_date: str | None) -> dict[str, Any]:
    pullback = [row for row in rows if _strategy_name(row) == "builtin_pullback"]
    values_5d = [value for row in pullback if (value := _mature_return(row, 5)) is not None]
    values_10d = [value for row in pullback if (value := _mature_return(row, 10)) is not None]
    alpha = []
    sectors = set()
    dates: dict[str, int] = defaultdict(int)
    for row in pullback:
        outcome = row.get("outcome") or {}
        value = outcome.get("excess_vs_spy_5d")
        if isinstance(value, (int, float)) and _mature_return(row, 5) is not None:
            alpha.append(float(value) - 0.001)
        sector = (row.get("features") or {}).get("sector")
        if sector:
            sectors.add(str(sector))
        dates[str(row.get("signal_date") or "")] += 1
    expectancy_5d = sum(values_5d) / len(values_5d) if values_5d else None
    expectancy_10d = sum(values_10d) / len(values_10d) if values_10d else None
    alpha_5d = sum(alpha) / len(alpha) if alpha else None
    max_date_share = max(dates.values()) / len(pullback) if pullback and dates else None
    criteria = {
        "observation_until_2026_07_20_complete": bool(end_date and end_date >= "2026-07-20"),
        "expectancy_5d_net_positive": expectancy_5d is not None and expectancy_5d > 0,
        "expectancy_10d_net_positive": expectancy_10d is not None and expectancy_10d > 0,
        "excess_vs_spy_positive": alpha_5d is not None and alpha_5d > 0,
        "min_sample_30": len(values_5d) >= 30 and len(values_10d) >= 30,
        "no_date_concentration": max_date_share is not None and max_date_share <= 0.25,
        "sector_concentration_evaluable": bool(sectors),
    }
    eligible = all(criteria.values())
    return {
        "status": "promotion_eligible" if eligible else "blocked_criteria_unmet_or_unavailable",
        "eligible": eligible,
        "criteria": criteria,
        "metrics": {
            "n_5d": len(values_5d),
            "n_10d": len(values_10d),
            "expectancy_5d_net_10bps": round(expectancy_5d, 6) if expectancy_5d is not None else None,
            "expectancy_10d_net_10bps": round(expectancy_10d, 6) if expectancy_10d is not None else None,
            "excess_vs_spy_5d_net_10bps": round(alpha_5d, 6) if alpha_5d is not None else None,
            "max_signal_date_share": round(max_date_share, 4) if max_date_share is not None else None,
            "sectors_available": len(sectors),
        },
        "action": "keep_shadow" if not eligible else "request_human_promotion_review",
    }


def _group_return(rows: list[dict[str, Any]], key_fn: Any) -> dict[str, Any]:
    groups: dict[str, list[float]] = defaultdict(list)
    total: dict[str, int] = defaultdict(int)
    for row in rows:
        key = str(key_fn(row) or "unavailable")
        total[key] += 1
        value = _mature_return(row, 5)
        if value is not None:
            groups[key].append(value)
    items = []
    for key in sorted(total):
        values = groups.get(key, [])
        items.append(
            {
                "group": key,
                "observations": total[key],
                "n_5d": len(values),
                "expectancy_5d_net_10bps": round(sum(values) / len(values), 6) if values else None,
                "win_rate_5d": round(sum(1 for value in values if value > 0) / len(values), 4) if values else None,
                "status": "measured" if values else "unavailable",
            }
        )
    return {"status": "measured" if groups else "unavailable", "items": items}


def _gate_effectiveness(rows: list[dict[str, Any]]) -> dict[str, Any]:
    blocked = [row for row in rows if row.get("blocked_entry_quality") or row.get("blocked_backtest")]
    values = [value for row in blocked if (value := _mature_return(row, 5)) is not None]
    return {
        "status": "measured" if values else "unavailable",
        "blocked_observations": len(blocked),
        "matured_5d": len(values),
        "blocked_winners": sum(1 for value in values if value > 0),
        "losses_avoided": sum(1 for value in values if value < 0),
        "expectancy_5d_net_10bps": round(sum(values) / len(values), 6) if values else None,
    }


def _excursion_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    mfe = _numeric_outcomes(rows, ("mfe", "mfe_pct", "max_favorable_excursion"))
    mae = _numeric_outcomes(rows, ("mae", "mae_pct", "max_adverse_excursion"))
    return {
        "status": "measured" if mfe or mae else "unavailable",
        "mfe": _metric_summary(mfe),
        "mae": _metric_summary(mae),
        "stop_take_profit_time_stop": "unavailable" if not (mfe or mae) else "requires_exit_event_linkage",
    }


def _numeric_outcomes(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> list[float]:
    values = []
    for row in rows:
        outcome = row.get("outcome") or {}
        value = next((outcome.get(key) for key in keys if isinstance(outcome.get(key), (int, float))), None)
        if value is not None:
            values.append(float(value))
    return values


def _metric_summary(values: list[float]) -> dict[str, Any]:
    return {"n": len(values), "mean": round(sum(values) / len(values), 6) if values else None}


def _lineage(row: dict[str, Any]) -> dict[str, Any]:
    features = row.get("features") or {}
    execution = row.get("execution") or {}
    return features.get("decision_lineage") or execution.get("decision_lineage") or {}


def _strategy_name(row: dict[str, Any]) -> str:
    return str(_lineage(row).get("strategy_name") or "legacy_unverified")


def _decision_source(row: dict[str, Any]) -> str:
    return str(_lineage(row).get("decision_source") or "legacy_unverified")


def _low_sample_label(row: dict[str, Any]) -> str:
    return "low_sample" if bool(_lineage(row).get("low_sample_exploration")) else "standard"


def _setup_name(row: dict[str, Any]) -> str:
    features = row.get("features") or {}
    return str(features.get("setup") or features.get("setup_name") or _strategy_name(row))


def _regime_name(row: dict[str, Any]) -> str:
    features = row.get("features") or {}
    state = features.get("market_state") or {}
    return str(features.get("regime") or state.get("market_regime") or "unavailable")
