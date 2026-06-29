"""Compara edge forward por estrategia en signal_outcomes (read-only).

Uso:
    .\\.venv\\Scripts\\python.exe scripts\\study_strategy_edge_compare.py
    .\\.venv\\Scripts\\python.exe scripts\\study_strategy_edge_compare.py --since 2026-06-25 --horizons 1,3,5,10
    .\\.venv\\Scripts\\python.exe scripts\\study_strategy_edge_compare.py --benchmark SPY --beta-adjust

Niveles de medida:
- CRUDO: retorno forward tal cual.
- EXCESS = retorno - retorno_benchmark (mismo signal_date/horizonte). Ajusta el NIVEL de
  mercado, pero el delta entre estrategias es invariante a un benchmark comun (la beta
  diferencial no se elimina).
- BETA-AJUSTADO = retorno - beta_simbolo * retorno_benchmark. Quita la beta de cada simbolo,
  asi el delta pullback-breakout refleja el alpha residual, no la diferencia de beta.
  Requiere --beta-adjust (descarga historico de los simbolos para estimar beta).
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from agente_bolsa._utils import sqlite_connect_ro, table_exists, to_float
from agente_bolsa.config import get_settings

DEFAULT_STRATEGIES = ("builtin_pullback", "builtin_breakout")
DEFAULT_HORIZONS = (1, 3, 5, 10)
DEFAULT_BENCHMARK = "SPY"
DEFAULT_BETA_LOOKBACK = 120
_BENCHMARK_DISABLED = {"", "NONE", "OFF", "NO"}


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


def _bar_date(index: Any) -> str:
    if hasattr(index, "date"):
        return str(index.date())
    return str(index)[:10]


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


def benchmark_returns_from_closes(
    ordered_dates: list[str],
    closes: list[float | None],
    signal_dates: Iterable[str],
    horizons: tuple[int, ...],
) -> dict[tuple[str, int], float]:
    """Retorno forward del benchmark por (signal_date, horizonte).

    Replica la convencion de signal_learning: base = cierre del propio signal_date,
    objetivo = cierre N sesiones despues. Solo emite claves con datos disponibles.
    """
    position = {date: index for index, date in enumerate(ordered_dates)}
    result: dict[tuple[str, int], float] = {}
    for signal_date in {str(date)[:10] for date in signal_dates if date}:
        index = position.get(signal_date)
        if index is None:
            continue
        base = closes[index]
        if not base:
            continue
        for horizon in horizons:
            target = index + int(horizon)
            if 0 <= target < len(closes) and closes[target] is not None:
                result[(signal_date, int(horizon))] = round((closes[target] - base) / base, 4)
    return result


def build_benchmark_returns(
    signal_dates: Iterable[str],
    horizons: tuple[int, ...],
    *,
    symbol: str = DEFAULT_BENCHMARK,
    since: str | None = None,
) -> dict[tuple[str, int], float]:
    """Descarga precios del benchmark y construye el mapa de retornos forward.

    Aislado del calculo puro (`benchmark_returns_from_closes`) para que la red no
    contamine los tests. Devuelve {} si no hay datos o falla la descarga.
    """
    dates = sorted({str(date)[:10] for date in signal_dates if date})
    if not dates:
        return {}
    try:
        from agente_bolsa.tools.market_data import download_daily_prices
    except Exception:
        return {}
    start = since or dates[0]
    try:
        frame = download_daily_prices([symbol], start)
    except Exception:
        return {}
    if frame is None or getattr(frame, "empty", True):
        return {}
    if "Close" not in getattr(frame, "columns", []):
        try:
            frame = frame[symbol]
        except Exception:
            return {}
        if frame is None or getattr(frame, "empty", True) or "Close" not in frame.columns:
            return {}
    ordered_dates = [_bar_date(index) for index in frame.index]
    closes = [to_float(value) for value in frame["Close"].tolist()]
    return benchmark_returns_from_closes(ordered_dates, closes, dates, horizons)


def daily_returns_from_closes(closes: list[float | None]) -> list[float | None]:
    """Retornos diarios simples a partir de una serie de cierres alineada por fecha."""
    returns: list[float | None] = []
    for index in range(1, len(closes)):
        prev = closes[index - 1]
        curr = closes[index]
        if prev and curr is not None:
            returns.append((curr - prev) / prev)
        else:
            returns.append(None)
    return returns


def compute_betas(
    symbol_returns: dict[str, list[float | None]],
    market_returns: list[float | None],
    *,
    min_obs: int = 20,
) -> dict[str, float]:
    """Beta por simbolo = cov(r_simbolo, r_mercado) / var(r_mercado).

    Las series deben estar alineadas por fecha (misma posicion = misma sesion).
    Omite simbolos con menos de `min_obs` pares validos o varianza nula.
    """
    betas: dict[str, float] = {}
    for symbol, series in symbol_returns.items():
        pairs = [
            (sym_ret, mkt_ret)
            for sym_ret, mkt_ret in zip(series, market_returns, strict=False)
            if sym_ret is not None and mkt_ret is not None
        ]
        if len(pairs) < min_obs:
            continue
        sym_vals = [pair[0] for pair in pairs]
        mkt_vals = [pair[1] for pair in pairs]
        sym_mean = sum(sym_vals) / len(sym_vals)
        mkt_mean = sum(mkt_vals) / len(mkt_vals)
        variance = sum((mkt - mkt_mean) ** 2 for mkt in mkt_vals)
        if variance <= 0:
            continue
        covariance = sum((sym - sym_mean) * (mkt - mkt_mean) for sym, mkt in pairs)
        betas[symbol] = round(covariance / variance, 4)
    return betas


def _extract_closes(frame: Any, symbols: list[str]) -> dict[str, list[float | None]]:
    import pandas as pd

    closes_by_symbol: dict[str, list[float | None]] = {}
    multi = isinstance(frame.columns, pd.MultiIndex)
    for symbol in symbols:
        try:
            if multi:
                if symbol not in frame.columns.get_level_values(0):
                    continue
                series = frame[symbol]["Close"]
            else:
                series = frame["Close"]
        except Exception:
            continue
        closes_by_symbol[symbol] = [to_float(value) for value in series.tolist()]
    return closes_by_symbol


def build_betas(
    symbols: Iterable[str],
    *,
    since: str,
    lookback_days: int = DEFAULT_BETA_LOOKBACK,
    market: str = DEFAULT_BENCHMARK,
) -> dict[str, float]:
    """Estima beta por simbolo sobre una ventana historica que termina en `since`.

    Descarga precios de los simbolos + mercado, calcula retornos diarios alineados y
    delega en `compute_betas`. Devuelve {} si falla la descarga o no hay datos.
    """
    wanted = sorted({str(symbol).upper() for symbol in symbols if symbol})
    if not wanted:
        return {}
    try:
        from datetime import datetime, timedelta

        from agente_bolsa.tools.market_data import download_daily_prices
    except Exception:
        return {}
    try:
        start_dt = datetime.fromisoformat(since) - timedelta(days=int(lookback_days * 1.6) + 10)
        start = start_dt.date().isoformat()
    except Exception:
        start = since
    fetch = wanted + ([market] if market not in wanted else [])
    try:
        frame = download_daily_prices(fetch, start, since)
    except Exception:
        return {}
    if frame is None or getattr(frame, "empty", True):
        return {}
    closes_by_symbol = _extract_closes(frame, fetch)
    market_closes = closes_by_symbol.get(market)
    if not market_closes:
        return {}
    market_returns = daily_returns_from_closes(market_closes)
    symbol_returns = {
        symbol: daily_returns_from_closes(closes)
        for symbol, closes in closes_by_symbol.items()
        if symbol != market
    }
    return compute_betas(symbol_returns, market_returns)


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


def _coverage(stats: dict[str, Any], total: int) -> dict[str, Any]:
    stats["pending"] = total - stats["n"]
    stats["coverage"] = round(stats["n"] / total, 4) if total else 0.0
    return stats


def _delta_block(pullback: dict[str, Any], breakout: dict[str, Any]) -> dict[str, Any]:
    pullback_mean = pullback.get("mean")
    breakout_mean = breakout.get("mean")
    pullback_net = pullback.get("mean_net")
    breakout_net = breakout.get("mean_net")
    return {
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


def _horizon_values(
    strategy_rows: list[SignalRow],
    key: str,
    horizon: int,
    *,
    benchmark_returns: dict[tuple[str, int], float] | None,
    betas: dict[str, float] | None,
    mode: str,
) -> list[float]:
    values: list[float] = []
    for row in strategy_rows:
        raw = to_float(row.outcome.get(key))
        if raw is None:
            continue
        if mode == "raw":
            values.append(raw)
            continue
        bench = (benchmark_returns or {}).get((row.signal_date, int(horizon)))
        if bench is None:
            continue
        if mode == "excess":
            values.append(raw - bench)
        elif mode == "beta_adj":
            beta = (betas or {}).get(row.symbol)
            if beta is None:
                continue
            values.append(raw - beta * bench)
    return values


def summarize_strategy_edge(
    rows: list[SignalRow],
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    strategies: tuple[str, ...] = DEFAULT_STRATEGIES,
    cost_bps: float = 10.0,
    benchmark_returns: dict[tuple[str, int], float] | None = None,
    betas: dict[str, float] | None = None,
) -> dict[str, Any]:
    deduped = [
        row
        for row in dedupe_signal_rows(rows)
        if row.strategy_name in strategies
    ]
    cost = cost_bps / 10000.0
    use_excess = benchmark_returns is not None
    use_beta_adj = benchmark_returns is not None and betas is not None

    blocks = [("horizons", "raw")]
    if use_excess:
        blocks.append(("excess_horizons", "excess"))
    if use_beta_adj:
        blocks.append(("beta_adj_horizons", "beta_adj"))

    by_strategy: dict[str, dict[str, Any]] = {}
    for strategy in strategies:
        strategy_rows = [row for row in deduped if row.strategy_name == strategy]
        by_strategy[strategy] = {"rows": len(strategy_rows)}
        for block_key, _mode in blocks:
            by_strategy[strategy][block_key] = {}
        for horizon in horizons:
            key = f"return_{horizon}d"
            for block_key, mode in blocks:
                values = _horizon_values(
                    strategy_rows,
                    key,
                    horizon,
                    benchmark_returns=benchmark_returns,
                    betas=betas,
                    mode=mode,
                )
                by_strategy[strategy][block_key][key] = _coverage(
                    _stats(values, cost=cost), len(strategy_rows)
                )

    summary: dict[str, Any] = {
        "strategies": by_strategy,
        "deltas": {},
        "deduped_rows": len(deduped),
        "horizons": list(horizons),
        "cost_bps": cost_bps,
    }
    if use_excess:
        summary["excess_deltas"] = {}
        summary["benchmark_pairs"] = len(benchmark_returns)
    if use_beta_adj:
        summary["beta_adj_deltas"] = {}
        summary["beta_symbols"] = len(betas)

    if "builtin_pullback" in by_strategy and "builtin_breakout" in by_strategy:
        delta_targets = [("horizons", "deltas")]
        if use_excess:
            delta_targets.append(("excess_horizons", "excess_deltas"))
        if use_beta_adj:
            delta_targets.append(("beta_adj_horizons", "beta_adj_deltas"))
        for horizon in horizons:
            key = f"return_{horizon}d"
            for block_key, delta_key in delta_targets:
                summary[delta_key][key] = _delta_block(
                    by_strategy["builtin_pullback"][block_key][key],
                    by_strategy["builtin_breakout"][block_key][key],
                )
    return summary


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


def _print_table(title: str, strategies: tuple[str, ...], summary: dict[str, Any], block: str) -> None:
    print(f"\n{title}")
    print(f"\n{'strategy':<18}{'horizon':<10}{'n':>6}{'pending':>9}{'coverage':>10}{'mean':>10}{'median':>10}{'hit':>8}{'std':>9}{'mean_net':>11}")
    for strategy in strategies:
        strategy_summary = summary["strategies"].get(strategy, {})
        for horizon_key, stats in (strategy_summary.get(block) or {}).items():
            print(
                f"{strategy:<18}{horizon_key:<10}{stats['n']:>6}{stats['pending']:>9}"
                f"{_pct(stats['coverage']):>10}{_pct(stats['mean']):>10}{_pct(stats['median']):>10}"
                f"{_pct(stats['hit_rate']):>8}{_pct(stats['std']):>9}{_pct(stats['mean_net']):>11}"
            )


def _print_delta(title: str, deltas: dict[str, Any]) -> None:
    print(f"\n{title}")
    print(f"{'horizon':<10}{'pull_n':>8}{'brk_n':>8}{'mean_delta':>13}{'net_delta':>12}")
    for horizon_key, delta in deltas.items():
        print(
            f"{horizon_key:<10}{delta['pullback_n']:>8}{delta['breakout_n']:>8}"
            f"{_pct(delta['mean_delta']):>13}{_pct(delta['mean_net_delta']):>12}"
        )


def print_report(
    summary: dict[str, Any],
    *,
    since: str,
    strategies: tuple[str, ...],
    benchmark: str | None = None,
) -> None:
    label = benchmark or DEFAULT_BENCHMARK
    print("\n=== Strategy edge compare (read-only) ===")
    print(f"since={since} | strategies={', '.join(strategies)} | cost_bps={summary['cost_bps']}")
    print(f"filas deduplicadas estrategia-simbolo-dia: {summary['deduped_rows']}")
    print("\nCaveat: no concluir con pocas muestras, horizons inmaduros o un unico regimen de mercado.")
    _print_table("--- Retorno CRUDO ---", strategies, summary, "horizons")
    if summary.get("deltas"):
        _print_delta("=== Delta pullback - breakout (crudo) ===", summary["deltas"])

    if "excess_deltas" in summary:
        pairs = summary.get("benchmark_pairs", 0)
        print(f"\n>>> EXCESS vs {label} (retorno - benchmark; ajusta nivel, NO la beta diferencial). pares benchmark={pairs}")
        _print_table("--- Retorno EXCESS (vs benchmark) ---", strategies, summary, "excess_horizons")
        if summary["excess_deltas"]:
            _print_delta("=== Delta pullback - breakout (excess) ===", summary["excess_deltas"])

    if "beta_adj_deltas" in summary:
        n_betas = summary.get("beta_symbols", 0)
        print(f"\n>>> BETA-AJUSTADO vs {label} (retorno - beta*benchmark; el delta aisla alpha). simbolos con beta={n_betas}")
        _print_table("--- Retorno BETA-AJUSTADO ---", strategies, summary, "beta_adj_horizons")
        if summary["beta_adj_deltas"]:
            _print_delta("=== Delta pullback - breakout (beta-ajustado) ===", summary["beta_adj_deltas"])


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
    parser.add_argument(
        "--benchmark",
        default=DEFAULT_BENCHMARK,
        help="Simbolo benchmark para retorno excess (default SPY). Usar 'none' para desactivar.",
    )
    parser.add_argument(
        "--beta-adjust",
        action="store_true",
        help="Anade retorno beta-ajustado (descarga historico de simbolos para estimar beta).",
    )
    parser.add_argument(
        "--beta-lookback",
        type=int,
        default=DEFAULT_BETA_LOOKBACK,
        help=f"Sesiones de historico para estimar beta. Default: {DEFAULT_BETA_LOOKBACK}.",
    )
    parser.add_argument("--db", default=None, help="Ruta a la BD. Por defecto usa settings.")
    args = parser.parse_args()

    settings = get_settings()
    db_path = args.db or str(settings.database_path)
    strategies = _parse_csv(args.strategies, default=DEFAULT_STRATEGIES)
    horizons = _parse_horizons(args.horizons)
    rows = load_signal_rows(db_path, since=args.since)

    benchmark = (args.benchmark or "").strip().upper()
    benchmark_returns: dict[tuple[str, int], float] | None = None
    betas: dict[str, float] | None = None
    if benchmark not in _BENCHMARK_DISABLED:
        benchmark_returns = build_benchmark_returns(
            (row.signal_date for row in rows),
            horizons,
            symbol=benchmark,
            since=args.since,
        )
        if args.beta_adjust:
            betas = build_betas(
                (row.symbol for row in rows),
                since=args.since,
                lookback_days=args.beta_lookback,
                market=benchmark,
            )

    summary = summarize_strategy_edge(
        rows,
        horizons=horizons,
        strategies=strategies,
        cost_bps=args.cost_bps,
        benchmark_returns=benchmark_returns,
        betas=betas,
    )
    print_report(
        summary,
        since=args.since,
        strategies=strategies,
        benchmark=None if benchmark in _BENCHMARK_DISABLED else benchmark,
    )


if __name__ == "__main__":
    main()
