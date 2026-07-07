from __future__ import annotations

from datetime import date, timedelta

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement import promotion_readiness
from agente_bolsa.storage import Store
from agente_bolsa.tools import edge_analysis, profitability_scoreboard
from agente_bolsa.tools.setup_edge import compute_setup_edge_table_from_connection
from scripts.study_strategy_edge_compare import load_signal_rows


def _latest_market_session(today: date | None = None) -> date:
    today = today or date.today()
    session = today
    while session.weekday() >= 5:
        session -= timedelta(days=1)
    return session


def _save_signal(
    store: Store,
    *,
    signal_id: str,
    source: str,
    setup: str,
    signal_date: str = "2026-07-01",
    return_5d: float = 0.01,
    decision: str = "buy",
) -> None:
    setup_flags = {"orderly_breakout_long": True} if setup == "real_setup" else {"event_momentum_long": True}
    store.save_signal_outcome(
        signal_id=signal_id,
        source_run_id=f"run-{signal_id}",
        source=source,
        symbol="AAA",
        signal_date=signal_date,
        decision=decision,
        features={
            "setup_quality": setup,
            "strategy_name": setup,
            "strategy_status": "ACTIVE",
            "score": 15,
            "distance_sma20": 0.02,
            "rsi_14": 50,
            **setup_flags,
        },
        gate={"backtest_gate": {"reason": "regimenes negativos"}},
        outcome={
            "return_1d": return_5d,
            "return_3d": return_5d,
            "return_5d": return_5d,
            "return_10d": return_5d,
            "verdict": "winner_open" if return_5d > 0 else "loser_open",
        },
    )


def test_lab_book_source_is_excluded_from_real_book_consumers(monkeypatch, tmp_path):
    session_date = _latest_market_session()
    signal_date = session_date.isoformat()
    since_date = (session_date - timedelta(days=30)).isoformat()
    order_created_at = f"{signal_date}T15:30:00+00:00"
    settings = Settings(DATA_DIR=tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    _save_signal(store, signal_id="real", source="intraday_scan", setup="real_setup", signal_date=signal_date, return_5d=0.01)
    _save_signal(store, signal_id="lab", source="lab_book", setup="lab_setup", signal_date=signal_date, return_5d=0.50)
    store.save_broker_order(
        broker_order_id="bo-1",
        plan_id="plan-1",
        cycle_id="cycle-1",
        symbol="AAA",
        side="buy",
        status="filled",
        payload={"plan": {"created_at": order_created_at}},
    )
    with store.connect() as conn:
        conn.execute("UPDATE broker_orders SET created_at = ? WHERE broker_order_id = 'bo-1'", (order_created_at,))

    monkeypatch.setattr(
        edge_analysis,
        "_build_spy_forward_context",
        lambda settings, start, end: {"returns": {}, "regimes": {}},
    )
    monkeypatch.setattr(
        profitability_scoreboard,
        "build_spy_daily_returns",
        lambda settings, start, end: {},
    )
    monkeypatch.setattr(
        profitability_scoreboard,
        "build_exit_horizon_shadow",
        lambda settings, store, since_date, linked_rows: {"linked_executed_buys": len(linked_rows)},
    )
    monkeypatch.setattr(
        promotion_readiness,
        "_build_spy_forward_context",
        lambda settings, start, end: {"returns": {}, "regimes": {}},
    )

    assert [row["signal_id"] for row in store.signal_outcomes(limit=10, since_date=since_date)] == ["real"]
    assert {row["signal_id"] for row in store.signal_outcomes(limit=10, since_date=since_date, include_lab_book=True)} == {
        "real",
        "lab",
    }

    with store.connect() as conn:
        setup_edge = compute_setup_edge_table_from_connection(
            conn,
            as_of=(session_date + timedelta(days=1)).isoformat(),
            train_window_days=60,
            min_samples=1,
            horizon="return_5d",
        )
    assert setup_edge == {"sin_patron|real_setup": 0.01}

    strategy_rows = load_signal_rows(str(settings.database_path), since=since_date)
    assert [row.strategy_name for row in strategy_rows] == ["real_setup"]

    veto = edge_analysis.veto_forward_cohorts(settings, store, since_date=since_date)
    assert veto["total_rows"] == 0

    scoreboard = profitability_scoreboard.build_profitability_scoreboard(settings, store, since_date=since_date)
    assert scoreboard["execution"]["linked_executed_buys"] == 1
    assert scoreboard["edge"]["setup_quality"][0]["key"] == "real_setup"
    assert scoreboard["edge"]["setup_quality"][0]["expectancy_5d"] == 0.01

    readiness = promotion_readiness.evaluate_promotion_readiness(settings, store, since_date=since_date)
    evaluated_keys = {item["key"] for item in readiness["evaluations"]}
    assert "orderly_breakout" in evaluated_keys
    assert "event_momentum" not in evaluated_keys
