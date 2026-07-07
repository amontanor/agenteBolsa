"""Weekly scoreboard for the learning_experiment cohort."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

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
    first_day = min(date.fromisoformat(str(row["signal_date"])) for row in rows)
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
            outcome = item.get("outcome") or {}
            value = _num(outcome.get(f"return_{horizon}d"))
            if value is None:
                continue
            net_10 = value - 0.001
            net_20 = value - 0.002
            costs_10.append(net_10)
            costs_20.append(net_20)
            hit_flags.append(net_10 > 0)
            spy_return = benchmark.get((str(item.get("signal_date") or ""), horizon))
            if spy_return is not None:
                alpha_values.append(value - spy_return)
        control_values = []
        for item in control_grouped.get(week, []):
            value = _num((item.get("outcome") or {}).get(f"return_{horizon}d"))
            if value is not None:
                control_values.append(value - 0.001)
        weekly.append(
            {
                "week": week,
                "label": _week_label(week),
                "n": len(costs_10),
                "expectancy_net_10bps": _round(_mean(costs_10)),
                "expectancy_net_20bps": _round(_mean(costs_20)),
                "hit_rate": _round(sum(1 for flag in hit_flags if flag) / len(hit_flags), 4) if hit_flags else None,
                "profit_factor": _round(_profit_factor(costs_10), 4),
                "alpha_vs_spy": _round(_mean(alpha_values)),
                "max_drawdown": _round(_max_drawdown(costs_10), 4),
                "control_n": len(control_values),
                "control_expectancy_net_10bps": _round(_mean(control_values)),
            }
        )
    return weekly


def _evaluation(weekly_rows: list[dict[str, Any]]) -> dict[str, Any]:
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
    if not valid:
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
    executed, control = _cohort_rows(store, since_date=since_date, end_date=end_date)
    weekly_rows = _weekly_rows(settings, executed, control, since_date=since_date, end_date=end_date)
    evaluation = _evaluation(weekly_rows)
    report = {
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "period": {"from": since_date, "to": end_date},
        "cohort": LEARNING_EXPERIMENT_SOURCE,
        "weekly_rows": weekly_rows,
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
