"""Deep read-only SPY drawdown overlay robustness study."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from agente_bolsa.tools.strategy_edge_backtest import (
    DEFAULT_OVERLAY_COST_BPS,
    DEFAULT_OVERLAY_DD_THRESHOLDS,
    DEFAULT_OVERLAY_SMA_WINDOWS,
    DEFAULT_OVERLAY_VOL_TARGETS,
    _normalize_download_frame,
    _overlay_target_exposure,
    build_overlay_policy_report,
    build_overlay_walk_forward_report,
    download_prices_read_only,
    risk_overlay_metrics,
    simulate_exposure_overlay,
)

DEFAULT_SINCE = "2000-01-01"
DEFAULT_TRAIN_END_YEAR = 2004
DEFAULT_EPISODES = (
    {"id": "2000-02", "label": "2000-02 dot-com", "start": "2000-03-24", "end": "2002-10-09"},
    {"id": "2008-09", "label": "2008-09 crisis financiera", "start": "2007-10-09", "end": "2009-03-09"},
    {"id": "2011", "label": "2011 crisis deuda/US downgrade", "start": "2011-04-29", "end": "2011-10-03"},
    {"id": "2015-16", "label": "2015-16 China/energia", "start": "2015-05-21", "end": "2016-02-11"},
    {"id": "2018", "label": "2018 Q4 tightening", "start": "2018-09-20", "end": "2018-12-24"},
    {"id": "2020", "label": "2020 Covid shock", "start": "2020-02-19", "end": "2020-03-23"},
    {"id": "2022", "label": "2022 inflacion/tipos", "start": "2022-01-03", "end": "2022-10-12"},
)
FIXED_POLICY_IDS = ("buy_hold", "vol_target_10pct", "vol_target_12pct")


def _parse_floats(value: str) -> tuple[float, ...]:
    return tuple(float(item.strip()) for item in value.split(",") if item.strip())


def _pct_value(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return round(float(value) * 100.0, 2)
    except (TypeError, ValueError):
        return None


def _num_value(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def annual_expanding_blocks(*, first_year: int, train_end_year: int, final_year: int) -> tuple[dict[str, str], ...]:
    blocks: list[dict[str, str]] = []
    for apply_year in range(train_end_year + 1, final_year + 1):
        blocks.append(
            {
                "label": f"train_{first_year}_{apply_year - 1}_apply_{apply_year}",
                "train_end": f"{apply_year - 1}-12-31",
                "apply_start": f"{apply_year}-01-01",
                "apply_end": f"{apply_year}-12-31",
            }
        )
    return tuple(blocks)


def _policy_returns(
    *,
    close: pd.Series,
    policy_id: str,
    cost_bps: float,
    since: str,
    end: str,
) -> pd.Series:
    returns = pd.to_numeric(close, errors="coerce").dropna().sort_index().pct_change().dropna()
    if policy_id == "buy_hold":
        target = pd.Series(1.0, index=close.dropna().index)
    elif policy_id == "vol_target_10pct":
        target = _overlay_target_exposure(
            {"id": policy_id, "kind": "vol_target", "target_vol": 0.10},
            market_close=close,
            regime_close=close,
        )
    elif policy_id == "vol_target_12pct":
        target = _overlay_target_exposure(
            {"id": policy_id, "kind": "vol_target", "target_vol": 0.12},
            market_close=close,
            regime_close=close,
        )
    else:
        raise ValueError(f"politica fija no soportada: {policy_id}")
    simulation = simulate_exposure_overlay(returns, target, cost_bps=cost_bps, start=since, end=end)
    return simulation["returns"]


def fixed_policy_oos_report(
    *,
    close: pd.Series,
    since: str,
    end: str,
    cost_bps_values: tuple[float, ...],
    blocks: tuple[dict[str, str], ...],
) -> dict[str, Any]:
    by_cost: dict[str, Any] = {}
    for cost_bps in cost_bps_values:
        policies: dict[str, Any] = {}
        for policy_id in FIXED_POLICY_IDS:
            stitched: list[pd.Series] = []
            yearly: list[dict[str, Any]] = []
            for block in blocks:
                apply_start = max(block["apply_start"], since)
                apply_end = min(block["apply_end"], end)
                if apply_start > apply_end:
                    continue
                period = _policy_returns(
                    close=close,
                    policy_id=policy_id,
                    cost_bps=float(cost_bps),
                    since=apply_start,
                    end=apply_end,
                )
                stitched.append(period)
                yearly.append(
                    {
                        "block": block["label"],
                        "apply_start": apply_start,
                        "apply_end": apply_end,
                        "metrics": risk_overlay_metrics(period),
                    }
                )
            oos_returns = pd.concat(stitched).sort_index() if stitched else pd.Series(dtype=float)
            policies[policy_id] = {
                "metrics": risk_overlay_metrics(oos_returns),
                "yearly": yearly,
            }
        by_cost[str(cost_bps)] = {"policies": policies}
    return {
        "policy_ids": list(FIXED_POLICY_IDS),
        "cost_bps_values": list(cost_bps_values),
        "blocks": list(blocks),
        "by_cost_bps": by_cost,
    }


def recovery_days_from_episode_trough(
    full_returns: pd.Series,
    *,
    episode_start: str,
    episode_end: str,
) -> int | None:
    returns = pd.to_numeric(full_returns, errors="coerce").dropna().sort_index()
    if returns.empty:
        return None
    equity = (1.0 + returns).cumprod()
    episode_equity = equity.loc[str(episode_start) : str(episode_end)]
    if episode_equity.empty:
        return None
    running_peak = equity.cummax()
    episode_drawdown = (episode_equity / running_peak.loc[episode_equity.index]) - 1.0
    trough_date = episode_drawdown.idxmin()
    prior_peak_level = float(running_peak.loc[trough_date])
    recovered = equity.loc[trough_date:][equity.loc[trough_date:] >= prior_peak_level]
    if recovered.empty:
        return None
    return int(returns.loc[trough_date : recovered.index[0]].shape[0] - 1)


def episode_report(
    *,
    close: pd.Series,
    since: str,
    end: str,
    cost_bps: float,
    episodes: tuple[dict[str, str], ...] = DEFAULT_EPISODES,
) -> list[dict[str, Any]]:
    full_policy_returns = {
        policy_id: _policy_returns(close=close, policy_id=policy_id, cost_bps=cost_bps, since=since, end=end)
        for policy_id in FIXED_POLICY_IDS
    }
    rows: list[dict[str, Any]] = []
    for episode in episodes:
        policies: dict[str, Any] = {}
        for policy_id, full_returns in full_policy_returns.items():
            period = full_returns.loc[episode["start"] : episode["end"]]
            metrics = risk_overlay_metrics(period)
            policies[policy_id] = {
                "max_drawdown": metrics["max_drawdown"],
                "worst_week": metrics["worst_week"],
                "worst_month": metrics["worst_month"],
                "ulcer_index": metrics["ulcer_index"],
                "recovery_trading_days": recovery_days_from_episode_trough(
                    full_returns,
                    episode_start=episode["start"],
                    episode_end=episode["end"],
                ),
            }
        rows.append({**episode, "cost_bps": cost_bps, "policies": policies})
    return rows


def sanity_check_spy_vs_gspc(spy_close: pd.Series, gspc_close: pd.Series) -> dict[str, Any]:
    spy_returns = pd.to_numeric(spy_close, errors="coerce").dropna().pct_change()
    gspc_returns = pd.to_numeric(gspc_close, errors="coerce").dropna().pct_change()
    joined = pd.concat({"SPY": spy_returns, "GSPC": gspc_returns}, axis=1).dropna()
    if joined.empty:
        return {"overlap_days": 0, "correlation": None, "deviation_gt_1pct_count": 0, "anomalies": []}
    joined["abs_deviation"] = (joined["SPY"] - joined["GSPC"]).abs()
    anomalies = joined[joined["abs_deviation"] > 0.01].copy()
    anomaly_rows = []
    for idx, row in anomalies.sort_values("abs_deviation", ascending=False).head(25).iterrows():
        anomaly_rows.append(
            {
                "date": str(idx.date()),
                "spy_return": round(float(row["SPY"]), 6),
                "gspc_return": round(float(row["GSPC"]), 6),
                "abs_deviation": round(float(row["abs_deviation"]), 6),
            }
        )
    return {
        "overlap_days": int(joined.shape[0]),
        "correlation": round(float(joined["SPY"].corr(joined["GSPC"])), 6),
        "mean_abs_deviation": round(float(joined["abs_deviation"].mean()), 6),
        "max_abs_deviation": round(float(joined["abs_deviation"].max()), 6),
        "deviation_gt_1pct_count": int(anomalies.shape[0]),
        "anomalies": anomaly_rows,
        "note": "SPY se descarga con auto_adjust=True; ^GSPC es indice de precio. Desviaciones aisladas pueden reflejar dividendos, festivos o diferencias de feed.",
    }


def preregistered_criteria_report(
    *,
    close: pd.Series,
    since: str,
    end: str,
    cost_bps: float = 20.0,
) -> dict[str, Any]:
    buy_hold = _policy_returns(close=close, policy_id="buy_hold", cost_bps=cost_bps, since=since, end=end)
    vol_12 = _policy_returns(close=close, policy_id="vol_target_12pct", cost_bps=cost_bps, since=since, end=end)
    full_buy_hold = risk_overlay_metrics(buy_hold)
    full_vol_12 = risk_overlay_metrics(vol_12)
    years: list[dict[str, Any]] = []
    for year in range(pd.Timestamp(since).year, pd.Timestamp(end).year + 1):
        start = f"{year}-01-01"
        finish = f"{year}-12-31"
        bh_metrics = risk_overlay_metrics(buy_hold.loc[start:finish])
        vt_metrics = risk_overlay_metrics(vol_12.loc[start:finish])
        bh_max_dd = float(bh_metrics["max_drawdown"] or 0.0)
        if abs(bh_max_dd) <= 0.15:
            continue
        max_dd_reduced = abs(float(vt_metrics["max_drawdown"] or 0.0)) < abs(bh_max_dd)
        worst_month_reduced = abs(float(vt_metrics["worst_month"] or 0.0)) < abs(float(bh_metrics["worst_month"] or 0.0))
        years.append(
            {
                "year": year,
                "buy_hold_max_drawdown": bh_metrics["max_drawdown"],
                "vol_target_12pct_max_drawdown": vt_metrics["max_drawdown"],
                "buy_hold_worst_month": bh_metrics["worst_month"],
                "vol_target_12pct_worst_month": vt_metrics["worst_month"],
                "max_dd_reduced": max_dd_reduced,
                "worst_month_reduced": worst_month_reduced,
                "both_reduced": bool(max_dd_reduced and worst_month_reduced),
            }
        )
    successful_years = sum(1 for row in years if row["both_reduced"])
    success_ratio = successful_years / len(years) if years else 0.0
    sortino_ok = (full_vol_12.get("sortino") is not None and full_buy_hold.get("sortino") is not None) and (
        float(full_vol_12["sortino"]) >= float(full_buy_hold["sortino"])
    )
    dd_month_ok = success_ratio >= 0.80
    return {
        "definition": "Vol-target 12% fijo, neto 20 bps: reduce max DD y peor mes vs buy&hold en >=80% de los anos calendario con drawdown buy&hold >15%, y Sortino full-period >= buy&hold.",
        "cost_bps": cost_bps,
        "years_with_buy_hold_drawdown_gt_15pct": years,
        "successful_years": successful_years,
        "total_years": len(years),
        "success_ratio": round(success_ratio, 6),
        "dd_and_worst_month_threshold_met": dd_month_ok,
        "full_period_sortino_buy_hold": full_buy_hold.get("sortino"),
        "full_period_sortino_vol_target_12pct": full_vol_12.get("sortino"),
        "sortino_threshold_met": bool(sortino_ok),
        "verdict": "CUMPLE" if dd_month_ok and sortino_ok else "NO CUMPLE",
    }


def _close_from_download(data: pd.DataFrame, symbol: str) -> pd.Series:
    frame = _normalize_download_frame(data, symbol)
    if frame.empty or "Close" not in frame.columns:
        return pd.Series(dtype=float)
    close = pd.to_numeric(frame["Close"], errors="coerce").dropna().sort_index()
    return close.rename(symbol)


def run_deep_drawdown_overlay_study(
    *,
    since: str,
    end: str,
    cost_bps_values: tuple[float, ...] = DEFAULT_OVERLAY_COST_BPS,
) -> dict[str, Any]:
    prices, meta = download_prices_read_only(
        ["SPY", "^GSPC"],
        start=since,
        end=end,
        provider="yfinance",
        fmp_api_key=None,
        batch_size=2,
    )
    spy_close = _close_from_download(prices, "SPY")
    gspc_close = _close_from_download(prices, "^GSPC")
    if spy_close.empty:
        raise ValueError("SPY no disponible para el estudio profundo.")

    final_year = pd.Timestamp(end).year
    blocks = annual_expanding_blocks(
        first_year=pd.Timestamp(since).year,
        train_end_year=DEFAULT_TRAIN_END_YEAR,
        final_year=final_year,
    )
    policy_report = build_overlay_policy_report(
        market_name="SPY",
        market_close=spy_close,
        regime_close=spy_close,
        since=since,
        end=end,
        cost_bps_values=cost_bps_values,
        sma_windows=DEFAULT_OVERLAY_SMA_WINDOWS,
        vol_targets=DEFAULT_OVERLAY_VOL_TARGETS,
        dd_thresholds=DEFAULT_OVERLAY_DD_THRESHOLDS,
    )
    walk_forward = build_overlay_walk_forward_report(
        market_name="SPY",
        market_close=spy_close,
        regime_close=spy_close,
        since=since,
        end=end,
        cost_bps_values=cost_bps_values,
        sma_windows=DEFAULT_OVERLAY_SMA_WINDOWS,
        vol_targets=DEFAULT_OVERLAY_VOL_TARGETS,
        dd_thresholds=DEFAULT_OVERLAY_DD_THRESHOLDS,
        walk_forward_blocks=blocks,
    )
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "study": {
            "name": "drawdown_overlay_deep_read_only",
            "since_requested": since,
            "end_requested": end,
            "first_spy_date": str(spy_close.index.min().date()),
            "last_spy_date": str(spy_close.index.max().date()),
            "first_gspc_date": str(gspc_close.index.min().date()) if not gspc_close.empty else None,
            "last_gspc_date": str(gspc_close.index.max().date()) if not gspc_close.empty else None,
            "market": "SPY",
            "equal_weight_used": False,
            "cost_bps_values": list(cost_bps_values),
            "sma_windows": list(DEFAULT_OVERLAY_SMA_WINDOWS),
            "vol_targets": list(DEFAULT_OVERLAY_VOL_TARGETS),
            "dd_thresholds": list(DEFAULT_OVERLAY_DD_THRESHOLDS),
            "walk_forward": "expansivo anual: train 2000-2004 aplica 2005; luego expande un ano hasta 2026.",
            "causality": "Senales calculadas con datos <= t; exposicion aplicada con shift(1) a retornos posteriores.",
        },
        "data": {
            "download": meta,
            "sanity_spy_vs_gspc": sanity_check_spy_vs_gspc(spy_close, gspc_close),
        },
        "markets": {"SPY": policy_report},
        "walk_forward_oos": {"SPY": walk_forward},
        "fixed_policy_oos": fixed_policy_oos_report(
            close=spy_close,
            since=since,
            end=end,
            cost_bps_values=cost_bps_values,
            blocks=blocks,
        ),
        "episodes": episode_report(close=spy_close, since=since, end=end, cost_bps=20.0),
        "preregistered_criteria": preregistered_criteria_report(close=spy_close, since=since, end=end, cost_bps=20.0),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Estudio historico profundo read-only de overlay vol-target en SPY.")
    parser.add_argument("--since", default=DEFAULT_SINCE, help="Fecha inicial YYYY-MM-DD.")
    parser.add_argument("--to", dest="end", default=date.today().isoformat(), help="Fecha final YYYY-MM-DD.")
    parser.add_argument("--cost-bps", default="10,20,30", help="Costes bps por turnover de exposicion.")
    parser.add_argument("--out", help="Ruta JSON opcional.")
    parser.add_argument("--json", action="store_true", help="Imprime JSON.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = run_deep_drawdown_overlay_study(
        since=args.since,
        end=args.end,
        cost_bps_values=_parse_floats(args.cost_bps) or DEFAULT_OVERLAY_COST_BPS,
    )
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        criteria = report["preregistered_criteria"]
        stability = report["walk_forward_oos"]["SPY"]["by_cost_bps"]["20.0"]["selection_stability"]
        print("=== Estudio profundo overlay SPY read-only ===")
        print(
            f"SPY real: {report['study']['first_spy_date']} -> {report['study']['last_spy_date']} | "
            f"veredicto={criteria['verdict']}"
        )
        print(
            f"Criterio 80%: {criteria['successful_years']}/{criteria['total_years']} "
            f"({criteria['success_ratio']:.1%}); Sortino B&H={criteria['full_period_sortino_buy_hold']} "
            f"vs VT12={criteria['full_period_sortino_vol_target_12pct']}"
        )
        print(
            f"Walk-forward 20 bps: {stability['changes']} cambios en "
            f"{max(stability['steps'] - 1, 0)} transiciones"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
