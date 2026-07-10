"""Weekly scoreboard for the learning_experiment cohort."""

from __future__ import annotations

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
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    observations = store.learning_observations(since_date=since_date, end_date=end_date, limit=200000)
    cohort = [row for row in observations if str(row.get("source_family") or "") == LEARNING_EXPERIMENT_SOURCE]
    executed = [row for row in cohort if bool(row.get("executed_buy"))]
    control = [row for row in cohort if not bool(row.get("executed_buy"))]
    return executed, control


def _weekly_rows(
    settings: Settings,
    rows: list[dict[str, Any]],
    control_rows: list[dict[str, Any]],
    *,
    since_date: str,
    end_date: str | None,
    horizon: int = 5,
) -> list[dict[str, Any]]:
    if not rows:
        return []
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


def _data_quality(executed: list[dict[str, Any]], control: list[dict[str, Any]]) -> dict[str, Any]:
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
            "method": "legacy_all_nonexecuted",
            "status": "pending_matched_control_v2",
            "matched_executed": 0,
            "total_executed": len(executed),
            "pct": 0.0 if executed else None,
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
    executed, control = _cohort_rows(store, since_date=since_date, end_date=resolved_end_date)
    weekly_rows = _weekly_rows(
        settings,
        executed,
        control,
        since_date=since_date,
        end_date=resolved_end_date,
    )
    evaluation = _evaluation(weekly_rows, executed_total=len(executed))
    data_quality = _data_quality(executed, control)
    report = {
        "schema_version": 2,
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "period": {"from": since_date, "to": resolved_end_date},
        "cohort": LEARNING_EXPERIMENT_SOURCE,
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
            f"exp20={row.get('expectancy_net_20bps')} hit={row.get('hit_rate')} pf={row.get('profit_factor')} "
            f"alpha={row.get('alpha_vs_spy')} dd={row.get('max_drawdown')} control_exp10={row.get('control_expectancy_net_10bps')}"
        )
    return "\n".join(lines)
