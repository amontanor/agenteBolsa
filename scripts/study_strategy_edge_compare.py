"""Compara edge forward por estrategia en signal_outcomes (read-only).

Uso:
    .\.venv\Scripts\python.exe scripts\study_strategy_edge_compare.py
    .\.venv\Scripts\python.exe scripts\study_strategy_edge_compare.py --since 2026-06-25 --horizons 1,3,5,10
"""

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import dataclass
from typing import Any

from agente_bolsa._utils import sqlite_connect_ro, table_exists, to_float
from agente_bolsa.config import get_settings

DEFAULT_STRATEGIES = ("builtin_pullback", "builtin_breakout")
DEFAULT_HORIZONS = (1, 3, 5, 10)


@dataclass(frozen=True)
class SignalRow:
    signal_date: str
    symbol: str
    strategy_name: str
    source_run_id: str
    shadow_candidate: bool
    strategy_status: str | None
    outcome: dict[str, Any]
    updated_at: str = ""


def _loads(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _parse_csv(value: str, *, default: tuple[str, ...]) -> tuple[str, ...]:
    items = tuple(item.strip() for item in str(value or "").split(",") if item.strip())
    return items or default


def _parse_horizons(value: str) -> tuple[int, ...]:
    horizons: list[int] = []
    for item in str(value or "").split(","):
        item = item.strip().lower().replace("d", "")
        if not item:
            continue
        horizon = int(item)
        if horizon <= 0:
            raise ValueError("Los horizontes deben ser positivos.")
        horizons.append(horizon)
    return tuple(horizons) or DEFAULT_HORIZONS


def signal_row_from_record(record: dict[str, Any]) -> SignalRow | None:
    features = record.get("features")
    if features is None:
        features = _loads(record.get("features_json"))
    outcome = record.get("outcome")
    if outcome is None:
        outcome = _loads(record.get("outcome_json"))
    strategy_name = str((features or {}).get("strategy_name") or "").strip()
    signal_date = str(record.get("signal_date") or "")[:10]
    symbol = str(record.get("symbol") or "").upper().strip()
    if not signal_date or not symbol or not strategy_name:
        return None
    return SignalRow(
        signal_date=signal_date,
        symbol=symbol,
        strategy_name=strategy_name,
        source_run_id=str(record.get("source_run_id") or ""),
        shadow_candidate=bool((features or {}).get("shadow_candidate")),
        strategy_status=(features or {}).get("strategy_status"),
        outcome=outcome or {},
        updated_at=str(record.get("updated_at") or ""),
    )


def dedupe_signal_rows(rows: list[SignalRow]) -> list[SignalRow]:
    by_key: dict[tuple[str, str, str], SignalRow] = {}
    for row in sorted(rows, key=lambda item: item.updated_at, reverse=True):
        key = (row.signal_date, row.symbol, row.strategy_name)
        by_key.setdefault(key, row)
    return list(by_key.values())


def _stats(values: list[float], *, cost: float) -> dict[str, Any]:
    if not values:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "hit_rate": None,
            "std": None,
            "mean_net": None,
        }
    return {
        "n": len(values),
        "mean": round(sum(values) / len(values), 6),
        "median": round(statistics.median(values), 6),
        "hit_rate": round(sum(1 for value in values if value > 0) / len(values), 4),
        "std": round(statistics.stdev(values), 6) if len(values) > 1 else 0.0,
        "mean_net": round((sum(values) / len(values)) - cost, 6),
    }


def summarize_strategy_edge(
    rows: list[SignalRow],
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    strategies: tuple[str, ...] = DEFAULT_STRATEGIES,
    cost_bps: float = 10.0,
) -> dict[str, Any]:
    deduped = [
        row
        for row in dedupe_signal_rows(rows)
        if row.strategy_name in strategies
    ]
    cost = cost_bps / 10000.0
    by_strategy: dict[str, dict[str, Any]] = {}
    for strategy in strategies:
        strategy_rows = [row for row in deduped if row.strategy_name == strategy]
        by_strategy[strategy] = {"rows": len(strategy_rows), "horizons": {}}
        for horizon in horizons:
            key = f"return_{horizon}d"
            values = [
                value
                for value in (to_float(row.outcome.get(key)) for row in strategy_rows)
                if value is not None
            ]
            stats = _stats(values, cost=cost)
            stats["pending"] = len(strategy_rows) - stats["n"]
            stats["coverage"] = round(stats["n"] / len(strategy_rows), 4) if strategy_rows else 0.0
            by_strategy[strategy]["horizons"][key] = stats

    deltas: dict[str, dict[str, Any]] = {}
    if "builtin_pullback" in by_strategy and "builtin_breakout" in by_strategy:
        for horizon in horizons:
            key = f"return_{horizon}d"
            pullback = by_strategy["builtin_pullback"]["horizons"][key]
            breakout = by_strategy["builtin_breakout"]["horizons"][key]
            pullback_mean = pullback.get("mean")
            breakout_mean = breakout.get("mean")
            pullback_net = pullback.get("mean_net")
            breakout_net = breakout.get("mean_net")
            deltas[key] = {
                "mean_delta": (
                    round(pullback_mean - breakout_mean, 6)
                    if pullback_mean is not None and breakout_mean is not None
                    else None
                ),
                "mean_net_delta": (
                    round(pullback_net - breakout_net, 6)
                    if pullback_net is not None and breakout_net is not None
                    else None
                ),
                "pullback_n": pullback.get("n", 0),
                "breakout_n": breakout.get("n", 0),
            }
    return {
        "strategies": by_strategy,
        "deltas": deltas,
        "deduped_rows": len(deduped),
        "horizons": list(horizons),
        "cost_bps": cost_bps,
    }


def load_signal_rows(db_path: str, *, since: str) -> list[SignalRow]:
    connection = sqlite_connect_ro(db_path, timeout=30.0)
    try:
        if not table_exists(connection, "signal_outcomes"):
            return []
        records = connection.execute(
            """
            SELECT signal_id, source_run_id, source, symbol, signal_date,
                   features_json, outcome_json, created_at, updated_at
            FROM signal_outcomes
            WHERE signal_date >= ?
            ORDER BY updated_at DESC, created_at DESC
            """,
            (since,),
        ).fetchall()
    finally:
        connection.close()
    rows: list[SignalRow] = []
    for record in records:
        row = signal_row_from_record(dict(record))
        if row is not None:
            rows.append(row)
    return rows


def _pct(value: Any) -> str:
    number = to_float(value)
    return "n/d" if number is None else f"{number * 100:.2f}%"


def print_report(summary: dict[str, Any], *, since: str, strategies: tuple[str, ...]) -> None:
    print("\n=== Strategy edge compare (read-only) ===")
    print(f"since={since} | strategies={', '.join(strategies)} | cost_bps={summary['cost_bps']}")
    print(f"filas deduplicadas estrategia-simbolo-dia: {summary['deduped_rows']}")
    print("\nCaveat: no concluir con pocas muestras, horizons inmaduros o un unico regimen de mercado.")
    print(f"\n{'strategy':<18}{'horizon':<10}{'n':>6}{'pending':>9}{'coverage':>10}{'mean':>10}{'median':>10}{'hit':>8}{'std':>9}{'mean_net':>11}")
    for strategy in strategies:
        strategy_summary = summary["strategies"].get(strategy, {})
        for horizon_key, stats in (strategy_summary.get("horizons") or {}).items():
            print(
                f"{strategy:<18}{horizon_key:<10}{stats['n']:>6}{stats['pending']:>9}"
                f"{_pct(stats['coverage']):>10}{_pct(stats['mean']):>10}{_pct(stats['median']):>10}"
                f"{_pct(stats['hit_rate']):>8}{_pct(stats['std']):>9}{_pct(stats['mean_net']):>11}"
            )
    if summary.get("deltas"):
        print("\n=== Delta pullback - breakout ===")
        print(f"{'horizon':<10}{'pull_n':>8}{'brk_n':>8}{'mean_delta':>13}{'net_delta':>12}")
        for horizon_key, delta in summary["deltas"].items():
            print(
                f"{horizon_key:<10}{delta['pullback_n']:>8}{delta['breakout_n']:>8}"
                f"{_pct(delta['mean_delta']):>13}{_pct(delta['mean_net_delta']):>12}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Compara edge forward pullback vs breakout por simbolo-dia.")
    parser.add_argument("--since", default="2026-06-25", help="Fecha inicial YYYY-MM-DD.")
    parser.add_argument("--horizons", default="1,3,5,10", help="Horizontes separados por coma, ej. 1,3,5,10.")
    parser.add_argument("--cost-bps", type=float, default=10.0, help="Coste round-trip en bps. Default: 10.")
    parser.add_argument(
        "--strategies",
        default="builtin_pullback,builtin_breakout",
        help="Estrategias separadas por coma.",
    )
    parser.add_argument("--db", default=None, help="Ruta a la BD. Por defecto usa settings.")
    args = parser.parse_args()

    settings = get_settings()
    db_path = args.db or str(settings.database_path)
    strategies = _parse_csv(args.strategies, default=DEFAULT_STRATEGIES)
    horizons = _parse_horizons(args.horizons)
    rows = load_signal_rows(db_path, since=args.since)
    summary = summarize_strategy_edge(
        rows,
        horizons=horizons,
        strategies=strategies,
        cost_bps=args.cost_bps,
    )
    print_report(summary, since=args.since, strategies=strategies)


if __name__ == "__main__":
    main()
