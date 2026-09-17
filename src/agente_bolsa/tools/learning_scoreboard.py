"""Weekly scoreboard for the learning_experiment cohort."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store

from .edge_analysis import _build_spy_forward_returns
from .learning_mode import LEARNING_EXPERIMENT_SOURCE
from .reporting import write_json_report
from .signal_learning import _num

LEARNING_SCOREBOARD_CRITERION = (
    "el sistema aprende si la expectancy neta media de las semanas 5-8 supera a "
    "la de las semanas 1-4 Y la pendiente semanal es positiva Y el resultado no "
    "lo explica solo el mercado (control: cohorte contrafactual de candidatos "
    "rechazados y/o selección aleatoria del universo con las herramientas "
    "counterfactual existentes — el aprendizaje debe batir a SU contrafactual, no "
    "solo al azar de un mes verde)."
)


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(float(value), digits)


MIN_CALIBRATION_SAMPLES = 10
MAX_CALIBRATION_ABS_BPS = 200.0


def _calibrated_cost(executed: list[dict[str, Any]]) -> dict[str, Any]:
    """Median signal_to_fill_bps over executed snapshots; assumption fallback.

    P-L131: the scoreboard no longer presents fixed 10/20 bps as the only
    truth. With >= MIN_CALIBRATION_SAMPLES finite snapshots (|bps| <= 200)
    the cost rate is the observed median; otherwise the calibrated column
    stays unavailable and the 10 bps band remains explicitly labelled as
    an assumption, never as measured cost.
    """

    samples: list[float] = []
    for row in executed:
        snapshot = (row.get("execution") or {}).get("execution_snapshot") or {}
        bps = (snapshot.get("metrics") or {}).get("signal_to_fill_bps")
        if isinstance(bps, bool) or not isinstance(bps, (int, float)):
            continue
        value = float(bps)
        if not math.isfinite(value) or abs(value) > MAX_CALIBRATION_ABS_BPS:
            continue
        samples.append(value)
    if len(samples) < MIN_CALIBRATION_SAMPLES:
        return {
            "cost_basis": "assumption_10bps",
            "cost_bps": 10.0,
            "cost_rate": 0.001,
            "calibration_samples": len(samples),
            "calibrated": False,
        }
    median_bps = round(float(statistics.median(samples)), 2)
    return {
        "cost_basis": "calibrated",
        "cost_bps": median_bps,
        "cost_rate": median_bps / 10_000.0,
        "calibration_samples": len(samples),
        "calibrated": True,
    }


def _week_index(first_day: date, current_day: date) -> int:
    return 1 + ((current_day - first_day).days // 7)


def _week_label(index: int) -> str:
    return f"week_{index}"


def _mean(values: list[float]) -> float | None:
    return None if not values else sum(values) / len(values)


def _profit_factor(values: list[float]) -> float | None:
    gains = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value < 0))
    if losses <= 0:
        return None if gains <= 0 else float("inf")
    return gains / losses


def _max_drawdown(values: list[float]) -> float | None:
    if not values:
        return None
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for value in values:
        equity *= 1.0 + value
        peak = max(peak, equity)
        drawdown = (equity / peak) - 1.0
        worst = min(worst, drawdown)
    return worst


def _resolved_end_date(end_date: str | None) -> str:
    if end_date:
        return date.fromisoformat(end_date[:10]).isoformat()
    return datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).date().isoformat()


def _mature_return(row: dict[str, Any], horizon: int) -> float | None:
    outcome = row.get("outcome") or {}
    if str(outcome.get("source") or "").strip().lower() == "trade_memory":
        return None
    maturity = outcome.get("matured_horizons") or {}
    if not bool(maturity.get(f"{horizon}d")):
        return None
    return _num(outcome.get(f"return_{horizon}d"))


def _daily_portfolio_returns(items: list[dict[str, Any]], *, horizon: int, cost: float) -> list[float]:
    by_day: dict[str, list[float]] = defaultdict(list)
    for item in items:
        value = _mature_return(item, horizon)
        if value is not None:
            by_day[str(item.get("signal_date") or "")].append(value - cost)
    return [sum(by_day[day]) / len(by_day[day]) for day in sorted(by_day) if by_day[day]]


def _linear_slope(points: list[tuple[int, float]]) -> float | None:
    if len(points) < 2:
        return None
    xs = [float(x) for x, _y in points]
    ys = [float(y) for _x, y in points]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    denom = sum((x - x_mean) ** 2 for x in xs)
    if denom <= 0:
        return None
    numer = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=False))
    return numer / denom


def _cohort_rows(
    store: Store,
    *,
    since_date: str,
    end_date: str | None,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, list[str]],
    list[dict[str, Any]],
]:
    observations = store.learning_observations(since_date=since_date, end_date=end_date, limit=200000)
    cohort = [row for row in observations if str(row.get("source_family") or "") == LEARNING_EXPERIMENT_SOURCE]
    executed = [row for row in cohort if bool(row.get("executed_buy"))]
    all_control = [row for row in cohort if not bool(row.get("executed_buy"))]
    matches: dict[str, list[str]] = {}
    matched_by_id: dict[str, dict[str, Any]] = {}
    allowed_capacity_reasons = {
        "max_orders_per_cycle_reached",
        "max_daily_buy_orders_reached",
        "low_sample_daily_quota_exhausted",
    }

    def source_ids(row: dict[str, Any]) -> set[str]:
        return {
            str(item).removesuffix(":shadow")
            for item in list(row.get("source_run_ids") or [])
            if str(item).strip()
        }

    def eligible_capacity_control(row: dict[str, Any]) -> bool:
        decision = str(row.get("decision") or "")
        execution = ((row.get("gate") or {}).get("execution") or {})
        return decision.startswith("approved_buy") and (
            str(execution.get("reason") or "") in allowed_capacity_reasons
            or str(execution.get("status") or "") == "approved_not_planned"
        )

    def control_sort_key(row: dict[str, Any]) -> tuple[float, float, str]:
        features = row.get("features") or {}
        lineage = features.get("decision_lineage") or {}
        rank = _num(lineage.get("candidate_rank") or features.get("selection_rank") or features.get("score_rank"))
        score = _num(row.get("best_score") or features.get("score"))
        return (rank if rank is not None else 1e9, -(score or 0.0), str(row.get("observation_id") or ""))

    for item in executed:
        item_sources = source_ids(item)
        candidates = [
            row
            for row in all_control
            if str(row.get("signal_date") or "") == str(item.get("signal_date") or "")
            and bool(item_sources.intersection(source_ids(row)))
            and eligible_capacity_control(row)
        ]
        selected = sorted(candidates, key=control_sort_key)[:3]
        observation_id = str(item.get("observation_id") or "")
        matches[observation_id] = [str(row.get("observation_id") or "") for row in selected]
        for row in selected:
            matched_by_id[str(row.get("observation_id") or "")] = row
    return executed, list(matched_by_id.values()), matches, all_control


def _weekly_rows(
    settings: Settings,
    rows: list[dict[str, Any]],
    control_rows: list[dict[str, Any]],
    *,
    since_date: str,
    end_date: str | None,
    horizon: int = 5,
    calibration: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    calibration = calibration or {"cost_basis": "assumption_10bps", "calibrated": False,
                                  "calibration_samples": 0}
    calibrated_rate = float(calibration["cost_rate"]) if calibration.get("calibrated") else None
    first_day = date.fromisoformat(since_date)
    benchmark = _build_spy_forward_returns(settings, start=since_date, end=end_date)
    grouped: dict[int, list[dict[str, Any]]] = {}
    control_grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        week = _week_index(first_day, date.fromisoformat(str(row["signal_date"])))
        grouped.setdefault(week, []).append(row)
    for row in control_rows:
        week = _week_index(first_day, date.fromisoformat(str(row["signal_date"])))
        control_grouped.setdefault(week, []).append(row)

    weekly = []
    for week in sorted(grouped):
        items = grouped[week]
        costs_10 = []
        costs_20 = []
        costs_cal = []
        alpha_values = []
        hit_flags = []
        for item in items:
            value = _mature_return(item, horizon)
            if value is None:
                continue
            net_10 = value - 0.001
            net_20 = value - 0.002
            costs_10.append(net_10)
            costs_20.append(net_20)
            if calibrated_rate is not None:
                costs_cal.append(value - calibrated_rate)
            hit_flags.append(net_10 > 0)
            spy_return = benchmark.get((str(item.get("signal_date") or ""), horizon))
            if spy_return is not None:
                alpha_values.append(net_10 - spy_return)
        control_values = []
        for item in control_grouped.get(week, []):
            value = _mature_return(item, horizon)
            if value is not None:
                control_values.append(value - 0.001)
        daily_returns = _daily_portfolio_returns(items, horizon=horizon, cost=0.001)
        expectancy_10 = _round(_mean(costs_10))
        expectancy_20 = _round(_mean(costs_20))
        expectancy_cal = _round(_mean(costs_cal)) if calibrated_rate is not None and costs_cal else None
        alpha_net = _round(_mean(alpha_values))
        portfolio_drawdown = _round(_max_drawdown(daily_returns), 4)
        control_expectancy = _round(_mean(control_values))
        weekly.append(
            {
                "week": week,
                "label": _week_label(week),
                "n": len(costs_10),
                "expectancy_net_10bps": expectancy_10,
                "expectancy_net_20bps": expectancy_20,
                "expectancy_net_calibrated": expectancy_cal,
                "cost_basis": calibration.get("cost_basis"),
                "calibration_samples": calibration.get("calibration_samples"),
                "hit_rate": _round(sum(1 for flag in hit_flags if flag) / len(hit_flags), 4) if hit_flags else None,
                "profit_factor": _round(_profit_factor(costs_10), 4),
                "alpha_vs_spy": alpha_net,
                "max_drawdown": portfolio_drawdown,
                "control_n": len(control_values),
                "control_expectancy_net_10bps": control_expectancy,
                "policy_expectancy_net_10bps": expectancy_10,
                "policy_expectancy_net_20bps": expectancy_20,
                "alpha_net_vs_spy": alpha_net,
                "portfolio_max_drawdown": portfolio_drawdown,
                "matched_control_expectancy_net_10bps": control_expectancy,
            }
        )
    return weekly


def _data_quality(
    executed: list[dict[str, Any]],
    control: list[dict[str, Any]],
    matches: dict[str, list[str]],
    all_control: list[dict[str, Any]],
) -> dict[str, Any]:
    maturity = {
        f"{horizon}d": {
            "executed": sum(_mature_return(row, horizon) is not None for row in executed),
            "control": sum(_mature_return(row, horizon) is not None for row in control),
        }
        for horizon in (1, 3, 5, 10)
    }
    contaminated = sum(
        str((row.get("outcome") or {}).get("source") or "").strip().lower() == "trade_memory"
        for row in [*executed, *control]
    )
    verified_lineage = sum(
        str((((row.get("features") or {}).get("decision_lineage") or {}).get("lineage_status")) or "")
        == "verified"
        for row in executed
    )
    matched_executed = sum(bool(items) for items in matches.values())
    blocked_counts: dict[str, int] = defaultdict(int)
    for row in all_control:
        decision = str(row.get("decision") or "")
        if decision.startswith("blocked_"):
            blocked_counts[decision] += 1
    regime_pool = sum(
        bool((row.get("features") or {}).get("market_regime"))
        for row in all_control
        if str(row.get("decision") or "") == "candidate"
    )
    return {
        "eligible_executed": len(executed),
        "eligible_control": len(control),
        "excluded_trade_memory_as_forward": contaminated,
        "maturity_by_horizon": maturity,
        "lineage_coverage": {
            "verified": verified_lineage,
            "total": len(executed),
            "pct": _round(verified_lineage / len(executed), 4) if executed else None,
        },
        "control_coverage": {
            "method": "same_cycle_eligible_next_best",
            "status": "available" if matched_executed else "unavailable",
            "matched_executed": matched_executed,
            "total_executed": len(executed),
            "pct": _round(matched_executed / len(executed), 4) if executed else None,
            "matched_control_observations": len(control),
        },
        "blocked_candidates": dict(sorted(blocked_counts.items())),
        "secondary_controls": {
            "spy": "available_via_alpha_net_vs_spy",
            "regime_matched_candidate_pool": regime_pool,
            "status": "diagnostic_only",
        },
    }


def _execution_quality(executed: list[dict[str, Any]]) -> dict[str, Any]:
    snapshots = [
        ((row.get("execution") or {}).get("execution_snapshot") or {})
        for row in executed
    ]
    available = [item for item in snapshots if item]
    open_pl = [_num(item.get("open_pl")) for item in available]
    realized_pl = [_num(item.get("realized_pl")) for item in available]
    return {
        "executed": len(executed),
        "snapshots_available": len(available),
        "open_pl": _round(sum(value for value in open_pl if value is not None), 2)
        if any(value is not None for value in open_pl)
        else None,
        "realized_pl": _round(sum(value for value in realized_pl if value is not None), 2)
        if any(value is not None for value in realized_pl)
        else None,
    }


def _evaluation(weekly_rows: list[dict[str, Any]], *, executed_total: int = 0) -> dict[str, Any]:
    valid = [row for row in weekly_rows if row.get("expectancy_net_10bps") is not None]
    slope = _linear_slope(
        [(int(row["week"]), float(row["expectancy_net_10bps"])) for row in valid if row.get("expectancy_net_10bps") is not None]
    )
    weeks_1_4 = [row for row in valid if 1 <= int(row["week"]) <= 4]
    weeks_5_8 = [row for row in valid if 5 <= int(row["week"]) <= 8]
    control_5_8 = [row for row in weeks_5_8 if row.get("control_expectancy_net_10bps") is not None]
    avg_1_4 = _mean([float(row["expectancy_net_10bps"]) for row in weeks_1_4 if row.get("expectancy_net_10bps") is not None])
    avg_5_8 = _mean([float(row["expectancy_net_10bps"]) for row in weeks_5_8 if row.get("expectancy_net_10bps") is not None])
    control_avg_5_8 = _mean(
        [float(row["control_expectancy_net_10bps"]) for row in control_5_8 if row.get("control_expectancy_net_10bps") is not None]
    )
    enough_window = len(weeks_1_4) == 4 and len(weeks_5_8) == 4
    beats_counterfactual = (
        avg_5_8 is not None and control_avg_5_8 is not None and avg_5_8 > control_avg_5_8
    )
    learns = bool(
        enough_window
        and avg_5_8 is not None
        and avg_1_4 is not None
        and avg_5_8 > avg_1_4
        and slope is not None
        and slope > 0
        and beats_counterfactual
    )
    if not valid and executed_total > 0:
        status = "pending_maturity"
    elif not valid:
        status = "pending_no_executed_cohort"
    elif not enough_window:
        status = "pending_weeks_5_8"
    elif learns:
        status = "learning_confirmed"
    else:
        status = "learning_not_confirmed"
    return {
        "criterion_verbatim": LEARNING_SCOREBOARD_CRITERION,
        "status": status,
        "weeks_1_4_expectancy_net_10bps": _round(avg_1_4),
        "weeks_5_8_expectancy_net_10bps": _round(avg_5_8),
        "weekly_slope_expectancy_net_10bps": _round(slope, 6),
        "beats_counterfactual": beats_counterfactual,
        "counterfactual_expectancy_weeks_5_8": _round(control_avg_5_8),
        "learns": learns,
    }


def build_learning_scoreboard(
    settings: Settings,
    store: Store,
    reports_dir: Path,
    run_id: str,
    *,
    since_date: str = "2026-07-07",
    end_date: str | None = None,
) -> dict[str, Any]:
    store.ensure_schema()
    resolved_end_date = _resolved_end_date(end_date)
    executed, control, matches, all_control = _cohort_rows(
        store,
        since_date=since_date,
        end_date=resolved_end_date,
    )
    calibration = _calibrated_cost(executed)
    weekly_rows = _weekly_rows(
        settings,
        executed,
        control,
        since_date=since_date,
        end_date=resolved_end_date,
        calibration=calibration,
    )
    evaluation = _evaluation(weekly_rows, executed_total=len(executed))
    data_quality = _data_quality(executed, control, matches, all_control)
    report = {
        "schema_version": 3,
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "period": {"from": since_date, "to": resolved_end_date},
        "cohort": LEARNING_EXPERIMENT_SOURCE,
        "cost_calibration": calibration,
        "weekly_rows": weekly_rows,
        "data_quality": data_quality,
        "maturity_by_horizon": data_quality["maturity_by_horizon"],
        "lineage_coverage": data_quality["lineage_coverage"],
        "control_coverage": data_quality["control_coverage"],
        "policy_quality": {
            "weekly_rows": weekly_rows,
            "evaluation": evaluation,
        },
        "execution_quality": _execution_quality(executed),
        "matched_controls": matches,
        "trend": {
            "weekly_expectancy_net_10bps": [
                {"week": row["week"], "value": row["expectancy_net_10bps"]}
                for row in weekly_rows
                if row.get("expectancy_net_10bps") is not None
            ]
        },
        "evaluation": evaluation,
    }
    return write_json_report(
        report,
        reports_dir,
        "learning_scoreboard",
        run_id,
        latest_filename="latest_learning_scoreboard.json",
        manifest={"criterion_verbatim": LEARNING_SCOREBOARD_CRITERION},
    )


def format_learning_scoreboard(report: dict[str, Any]) -> str:
    lines = [
        "LEARNING SCOREBOARD",
        f"cohort={report.get('cohort')} | from={report.get('period', {}).get('from')} | to={report.get('period', {}).get('to')}",
        f"criterion={report.get('evaluation', {}).get('criterion_verbatim')}",
        f"status={report.get('evaluation', {}).get('status')} | learns={report.get('evaluation', {}).get('learns')}",
    ]
    for row in report.get("weekly_rows") or []:
        lines.append(
            f"  - {row['label']}: n={row['n']} exp10={row.get('expectancy_net_10bps')} "
            f"exp20={row.get('expectancy_net_20bps')} exp_cal={row.get('expectancy_net_calibrated')} "
            f"hit={row.get('hit_rate')} pf={row.get('profit_factor')} "
            f"alpha={row.get('alpha_vs_spy')} dd={row.get('max_drawdown')} control_exp10={row.get('control_expectancy_net_10bps')}"
        )
    calibration = report.get("cost_calibration") or {}
    lines.append(
        f"cost_basis={calibration.get('cost_basis')} "
        f"cost_bps={calibration.get('cost_bps')} samples={calibration.get('calibration_samples')}"
    )
    return "\n".join(lines)
