from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools import profitability_scoreboard


def test_profitability_scoreboard_uses_performance_daily(monkeypatch, tmp_path):
    settings = Settings(DATA_DIR=tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.upsert_performance_daily({"session_date": "2026-06-10", "equity": 100000, "pnl_pct": 0.01, "spy_pct": 0.004, "alpha": 0.006, "iq_score": 55})
    store.upsert_performance_daily({"session_date": "2026-06-11", "equity": 101000, "pnl_pct": -0.002, "spy_pct": 0.001, "alpha": -0.003, "iq_score": 57})

    monkeypatch.setattr(
        profitability_scoreboard,
        "build_spy_daily_returns",
        lambda settings, start, end: {},
    )
    monkeypatch.setattr(
        profitability_scoreboard,
        "linked_executed_buy_signals",
        lambda settings, store, since_date: {
            "linked_rows": [],
            "unmatched_order_ids": [],
            "benchmark_points": 0,
            "regime_coverage": {"persisted": 0, "benchmark": 0, "unknown": 0, "known_ratio": 0.0},
            "setup_quality": [],
            "setup_key": [],
            "tag": [],
            "regime": [],
        },
    )

    report = profitability_scoreboard.build_profitability_scoreboard(settings, store, since_date="2026-06-01")

    assert report["performance"]["available"] is True
    assert report["performance"]["latest_equity"] == 101000
    assert report["performance"]["cumulative_pnl_pct"] == 0.008
    assert report["performance"]["cumulative_alpha"] == 0.003


def test_profitability_scoreboard_fetches_missing_spy_without_assuming_zero(monkeypatch, tmp_path):
    settings = Settings(DATA_DIR=tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.upsert_performance_daily({"session_date": "2026-06-10", "equity": 100000, "pnl_pct": 0.01})
    monkeypatch.setattr(
        profitability_scoreboard,
        "build_spy_daily_returns",
        lambda settings, start, end: {"2026-06-10": 0.004},
    )
    monkeypatch.setattr(
        profitability_scoreboard,
        "linked_executed_buy_signals",
        lambda settings, store, since_date: {
            "linked_rows": [], "unmatched_order_ids": [], "benchmark_points": 0,
            "regime_coverage": {"persisted": 0, "benchmark": 0, "unknown": 0, "known_ratio": 0.0},
            "setup_quality": [], "setup_key": [], "tag": [], "regime": [],
        },
    )

    report = profitability_scoreboard.build_profitability_scoreboard(settings, store, since_date="2026-06-01")

    assert report["performance"]["cumulative_spy_pct"] == 0.004
    assert report["performance"]["cumulative_alpha"] == 0.006
    assert report["performance"]["benchmark_coverage"]["ratio"] == 1.0
