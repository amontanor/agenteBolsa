"""Read-only historical study of simple regime-governed policies."""

from __future__ import annotations

import argparse
import json
from datetime import date
from typing import Any

from agente_bolsa.tools.strategy_edge_backtest import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_BETA_LOOKBACK,
    DEFAULT_SAMPLE_EVERY,
    run_regime_policy_robustness_study,
    run_regime_policy_study,
)


def _pct(value: Any) -> str:
    return "n/d" if value is None else f"{float(value) * 100:.2f}%"


def _num(value: Any) -> str:
    return "n/d" if value is None else f"{float(value):.3f}"


def _parse_int_list(value: str) -> tuple[int, ...]:
    return tuple(int(item.strip()) for item in value.split(",") if item.strip())


def _parse_float_list(value: str) -> tuple[float, ...]:
    return tuple(float(item.strip()) for item in value.split(",") if item.strip())


def print_summary(report: dict[str, Any]) -> None:
    print("\n=== Estudio historico politica por regimen (read-only) ===")
    print(
        f"ventana={report['study']['since']}->{report['study']['end']} | "
        f"horizon={report['study']['horizon_days']} sesiones | "
        f"top_n={report['study']['top_n']} | cost_bps={report['study']['cost_bps']}"
    )
    for title, block in (("Overall", report["summary"]["overall"]), *[
        (f"Regimen: {regime}", policies) for regime, policies in report["summary"]["by_regime"].items()
    ]):
        print(f"\n{title}")
        print(f"{'policy':<42}{'weeks':>8}{'cum':>12}{'mean':>12}{'sharpe_ann':>12}{'max_dd':>12}{'worst_week':>12}")
        for policy, stats in block.items():
            print(
                f"{policy:<42}{stats['weeks']:>8}"
                f"{_pct(stats.get('cumulative_return')):>12}"
                f"{_pct(stats['mean']):>12}{_num(stats.get('sharpe_annualized')):>12}"
                f"{_pct(stats['max_drawdown']):>12}{_pct(stats['worst_week']):>12}"
            )
    print("\nTurnover semanal")
    print(f"{'policy':<42}{'trans':>8}{'mean':>12}{'median':>12}{'max':>12}")
    for policy, stats in report.get("turnover", {}).items():
        print(
            f"{policy:<42}{stats['transitions']:>8}"
            f"{_pct(stats.get('mean')):>12}{_pct(stats.get('median')):>12}{_pct(stats.get('max')):>12}"
        )


def print_robustness_summary(report: dict[str, Any]) -> None:
    print("\n=== Robustez politica por regimen (read-only) ===")
    print(
        f"ventana={report['study']['since']}->{report['study']['end']} | "
        f"sma={report['study']['sma_windows']} | costs={report['study']['cost_bps_values']} bps"
    )
    print(f"{'sma':>5}{'cost':>8}{'policy':<42}{'weeks':>8}{'cum':>12}{'sharpe_ann':>12}{'max_dd':>12}{'worst':>12}")
    for sma_window, cost_reports in report["reports_by_sma_window"].items():
        for cost_bps, cost_report in cost_reports.items():
            for policy, stats in cost_report["summary"]["overall"].items():
                print(
                    f"{sma_window:>5}{cost_bps:>8}{policy:<42}{stats['weeks']:>8}"
                    f"{_pct(stats.get('cumulative_return')):>12}{_num(stats.get('sharpe_annualized')):>12}"
                    f"{_pct(stats.get('max_drawdown')):>12}{_pct(stats.get('worst_week')):>12}"
                )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Estudio read-only de politicas por regimen SPY>SMA.")
    parser.add_argument("--since", default="2022-01-01", help="Fecha inicial YYYY-MM-DD.")
    parser.add_argument("--to", dest="end", default=date.today().isoformat(), help="Fecha final YYYY-MM-DD.")
    parser.add_argument("--cost-bps", type=float, default=10.0, help="Coste por periodo invertido en bps.")
    parser.add_argument("--cost-sensitivity-bps", default="", help="Lista de costes bps para robustez, ej. 10,20,30.")
    parser.add_argument("--sma-windows", default="200", help="Lista de ventanas SMA para regimen, ej. 150,200,250.")
    parser.add_argument("--top-n", type=int, default=15, help="Top N del selector por fecha.")
    parser.add_argument("--universe", default="sp500", help="Universo; default sp500.")
    parser.add_argument("--max-symbols", type=int, default=0, help="Limite opcional de simbolos.")
    parser.add_argument("--beta-lookback", type=int, default=DEFAULT_BETA_LOOKBACK)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--sample-every", type=int, default=DEFAULT_SAMPLE_EVERY)
    parser.add_argument("--progress-every", type=int, default=50)
    parser.add_argument("--random-seed", type=int, default=17, help="Seed fija para control random15.")
    parser.add_argument("--random-n", type=int, default=15, help="Tamano del control aleatorio.")
    parser.add_argument("--json", action="store_true", help="Imprime JSON completo.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    sma_windows = _parse_int_list(args.sma_windows)
    cost_values = _parse_float_list(args.cost_sensitivity_bps) if args.cost_sensitivity_bps else (args.cost_bps,)
    if len(sma_windows) > 1 or len(cost_values) > 1:
        report = run_regime_policy_robustness_study(
            since=args.since,
            end=args.end,
            cost_bps_values=cost_values,
            sma_windows=sma_windows,
            top_n=args.top_n,
            universe_name=args.universe,
            max_symbols=args.max_symbols,
            beta_lookback=args.beta_lookback,
            batch_size=args.batch_size,
            sample_every=args.sample_every,
            progress_every=args.progress_every,
            random_seed=args.random_seed,
            random_n=args.random_n,
        )
    else:
        report = run_regime_policy_study(
            since=args.since,
            end=args.end,
            cost_bps=args.cost_bps,
            top_n=args.top_n,
            universe_name=args.universe,
            max_symbols=args.max_symbols,
            beta_lookback=args.beta_lookback,
            batch_size=args.batch_size,
            sample_every=args.sample_every,
            progress_every=args.progress_every,
            regime_sma_window=sma_windows[0],
            random_seed=args.random_seed,
            random_n=args.random_n,
        )
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    elif report["study"]["name"] == "regime_governed_policy_robustness_historical":
        print_robustness_summary(report)
    else:
        print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
