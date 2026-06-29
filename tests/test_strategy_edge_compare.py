from scripts.study_strategy_edge_compare import (
    SignalRow,
    benchmark_returns_from_closes,
    dedupe_signal_rows,
    summarize_strategy_edge,
)


def _row(
    *,
    date: str,
    symbol: str,
    strategy: str,
    updated_at: str,
    outcome: dict,
) -> SignalRow:
    return SignalRow(
        signal_date=date,
        symbol=symbol,
        strategy_name=strategy,
        source_run_id="run",
        shadow_candidate=strategy == "builtin_pullback",
        strategy_status="SHADOW" if strategy == "builtin_pullback" else "ACTIVE",
        outcome=outcome,
        updated_at=updated_at,
    )


def test_dedupe_signal_rows_keeps_latest_symbol_day_strategy():
    rows = [
        _row(date="2026-06-25", symbol="AAA", strategy="builtin_pullback", updated_at="2026-06-25T10:00:00", outcome={"return_1d": 0.01}),
        _row(date="2026-06-25", symbol="AAA", strategy="builtin_pullback", updated_at="2026-06-25T11:00:00", outcome={"return_1d": 0.03}),
        _row(date="2026-06-25", symbol="AAA", strategy="builtin_breakout", updated_at="2026-06-25T09:00:00", outcome={"return_1d": -0.01}),
    ]

    deduped = dedupe_signal_rows(rows)
    by_strategy = {row.strategy_name: row for row in deduped}

    assert len(deduped) == 2
    assert by_strategy["builtin_pullback"].outcome["return_1d"] == 0.03
    assert by_strategy["builtin_breakout"].outcome["return_1d"] == -0.01


def test_summarize_strategy_edge_math_and_coverage():
    rows = [
        _row(date="2026-06-25", symbol="AAA", strategy="builtin_pullback", updated_at="1", outcome={"return_1d": 0.02}),
        _row(date="2026-06-25", symbol="BBB", strategy="builtin_pullback", updated_at="1", outcome={"return_1d": -0.01}),
        _row(date="2026-06-25", symbol="CCC", strategy="builtin_pullback", updated_at="1", outcome={}),
        _row(date="2026-06-25", symbol="AAA", strategy="builtin_breakout", updated_at="1", outcome={"return_1d": 0.01}),
        _row(date="2026-06-25", symbol="BBB", strategy="builtin_breakout", updated_at="1", outcome={"return_1d": 0.03}),
    ]

    summary = summarize_strategy_edge(rows, horizons=(1,), cost_bps=10.0)

    pullback = summary["strategies"]["builtin_pullback"]["horizons"]["return_1d"]
    breakout = summary["strategies"]["builtin_breakout"]["horizons"]["return_1d"]
    delta = summary["deltas"]["return_1d"]

    assert pullback["n"] == 2
    assert pullback["pending"] == 1
    assert pullback["coverage"] == 0.6667
    assert pullback["mean"] == 0.005
    assert pullback["median"] == 0.005
    assert pullback["hit_rate"] == 0.5
    assert pullback["mean_net"] == 0.004
    assert breakout["mean"] == 0.02
    assert breakout["median"] == 0.02
    assert breakout["hit_rate"] == 1.0
    assert breakout["mean_net"] == 0.019
    assert delta["mean_delta"] == -0.015
    assert delta["mean_net_delta"] == -0.015


def test_benchmark_returns_from_closes_uses_forward_window():
    ordered_dates = ["2026-06-25", "2026-06-26", "2026-06-29", "2026-06-30"]
    closes = [100.0, 101.0, 102.0, 99.0]

    benchmark = benchmark_returns_from_closes(
        ordered_dates, closes, ["2026-06-25"], (1, 3)
    )

    # base = cierre del signal_date (100); horizonte N = cierre N sesiones despues.
    assert benchmark[("2026-06-25", 1)] == 0.01
    assert benchmark[("2026-06-25", 3)] == -0.01
    # Sin barra suficiente para horizonte 5 no se emite clave.
    assert ("2026-06-25", 5) not in benchmark_returns_from_closes(
        ordered_dates, closes, ["2026-06-25"], (5,)
    )


def test_summarize_with_benchmark_reports_excess_and_excludes_missing():
    rows = [
        _row(date="2026-06-25", symbol="AAA", strategy="builtin_pullback", updated_at="1", outcome={"return_1d": 0.02}),
        _row(date="2026-06-25", symbol="BBB", strategy="builtin_pullback", updated_at="1", outcome={"return_1d": -0.01}),
        _row(date="2026-06-25", symbol="AAA", strategy="builtin_breakout", updated_at="1", outcome={"return_1d": 0.03}),
        # CCC no tiene benchmark -> queda fuera del excess.
        _row(date="2026-06-26", symbol="CCC", strategy="builtin_breakout", updated_at="1", outcome={"return_1d": 0.05}),
    ]
    benchmark_returns = {("2026-06-25", 1): 0.01}

    summary = summarize_strategy_edge(
        rows, horizons=(1,), cost_bps=10.0, benchmark_returns=benchmark_returns
    )

    pull_excess = summary["strategies"]["builtin_pullback"]["excess_horizons"]["return_1d"]
    brk_excess = summary["strategies"]["builtin_breakout"]["excess_horizons"]["return_1d"]

    # pullback: (0.02-0.01)=0.01 y (-0.01-0.01)=-0.02 -> mean -0.005
    assert pull_excess["n"] == 2
    assert pull_excess["mean"] == -0.005
    # breakout: solo AAA tiene benchmark -> (0.03-0.01)=0.02; CCC (2026-06-26) excluido
    assert brk_excess["n"] == 1
    assert brk_excess["pending"] == 1
    assert brk_excess["mean"] == 0.02
    # delta excess pullback - breakout = -0.005 - 0.02 = -0.025
    assert summary["excess_deltas"]["return_1d"]["mean_delta"] == -0.025
    # el bloque crudo no se ve afectado por el benchmark.
    assert summary["strategies"]["builtin_pullback"]["horizons"]["return_1d"]["n"] == 2
