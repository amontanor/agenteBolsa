"""Read-only study of market exposure drawdown-control overlays."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from agente_bolsa.tools.strategy_edge_backtest import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_OVERLAY_COST_BPS,
    DEFAULT_OVERLAY_DD_THRESHOLDS,
    DEFAULT_OVERLAY_SMA_WINDOWS,
    DEFAULT_OVERLAY_VOL_TARGETS,
    run_drawdown_overlay_study,
)


def _parse_ints(value: str) -> tuple[int, ...]:
    return tuple(int(item.strip()) for item in value.split(",") if item.strip())


def _parse_floats(value: str) -> tuple[float, ...]:
    return tuple(float(item.strip()) for item in value.split(",") if item.strip())


def _pct(value: Any) -> str:
    return "n/d" if value is None else f"{float(value) * 100:.2f}%"


def _num(value: Any) -> str:
    return "n/d" if value is None else f"{float(value):.3f}"


def print_summary(report: dict[str, Any]) -> None:
    print("\n=== Estudio overlay de riesgo / control de caidas (read-only) ===")
    study = report["study"]
    print(
        f"ventana={study['since']}->{study['end']} | costs={study['cost_bps_values']} bps | "
        f"sma={study['sma_windows']} | vol_targets={study['vol_targets']} | dd={study['dd_thresholds']}"
    )
    for market, market_report in report["markets"].items():
        print(f"\nMercado: {market}")
        for cost_bps, cost_block in market_report["policies_by_cost"].items():
            print(f"\nCoste {cost_bps} bps")
            print(
                f"{'policy':<28}{'CAGR':>10}{'maxDD':>10}{'Ulcer':>10}"
                f"{'worstW':>10}{'worstM':>10}{'Sortino':>10}{'DD/retSac':>12}"
            )
            rows = cost_block["policies"]
            ordered = sorted(
                rows.items(),
                key=lambda item: (
                    item[1]["tradeoff_vs_buy_hold"].get("dd_reduction_per_cagr_sacrificed") is None,
                    -(item[1]["tradeoff_vs_buy_hold"].get("dd_reduction_per_cagr_sacrificed") or -999),
                    abs(item[1]["metrics"].get("max_drawdown") or 0.0),
                ),
            )
            for policy, payload in ordered[:12]:
                metrics = payload["metrics"]
                tradeoff = payload["tradeoff_vs_buy_hold"]
                print(
                    f"{policy:<28}{_pct(metrics.get('cagr')):>10}{_pct(metrics.get('max_drawdown')):>10}"
                    f"{_pct(metrics.get('ulcer_index')):>10}{_pct(metrics.get('worst_week')):>10}"
                    f"{_pct(metrics.get('worst_month')):>10}{_num(metrics.get('sortino')):>10}"
                    f"{_num(tradeoff.get('dd_reduction_per_cagr_sacrificed')):>12}"
                )
    print("\nWalk-forward OOS")
    for market, oos in report["walk_forward_oos"].items():
        print(f"\nMercado: {market}")
        print(f"{'cost':>8}{'CAGR':>10}{'maxDD':>10}{'Ulcer':>10}{'worstW':>10}{'Sortino':>10}  selected")
        for cost_bps, block in oos["by_cost_bps"].items():
            metrics = block["oos_metrics"]
            stability = block["selection_stability"]
            print(
                f"{cost_bps:>8}{_pct(metrics.get('cagr')):>10}{_pct(metrics.get('max_drawdown')):>10}"
                f"{_pct(metrics.get('ulcer_index')):>10}{_pct(metrics.get('worst_week')):>10}"
                f"{_num(metrics.get('sortino')):>10}  {' -> '.join(stability['selected_sequence'])}"
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Estudio read-only de overlays de control de caidas.")
    parser.add_argument("--since", default="2022-01-01", help="Fecha inicial YYYY-MM-DD.")
    parser.add_argument("--to", dest="end", default=date.today().isoformat(), help="Fecha final YYYY-MM-DD.")
    parser.add_argument("--cost-bps", default="10,20,30", help="Costes bps por turnover de exposicion.")
    parser.add_argument("--sma-windows", default="150,200,250", help="Ventanas SMA de regimen.")
    parser.add_argument("--vol-targets", default="0.10,0.12,0.15", help="Vol targets anualizados.")
    parser.add_argument("--dd-thresholds", default="0.10,0.15,0.20", help="Umbrales drawdown guard.")
    parser.add_argument("--universe", default="sp500", help="Universo para cesta equal-weight.")
    parser.add_argument("--max-symbols", type=int, default=0, help="Limite opcional de simbolos.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--json", action="store_true", help="Imprime JSON.")
    parser.add_argument("--out", help="Ruta JSON opcional.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = run_drawdown_overlay_study(
        since=args.since,
        end=args.end,
        universe_name=args.universe,
        max_symbols=args.max_symbols,
        cost_bps_values=_parse_floats(args.cost_bps) or DEFAULT_OVERLAY_COST_BPS,
        sma_windows=_parse_ints(args.sma_windows) or DEFAULT_OVERLAY_SMA_WINDOWS,
        vol_targets=_parse_floats(args.vol_targets) or DEFAULT_OVERLAY_VOL_TARGETS,
        dd_thresholds=_parse_floats(args.dd_thresholds) or DEFAULT_OVERLAY_DD_THRESHOLDS,
        batch_size=args.batch_size,
    )
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
