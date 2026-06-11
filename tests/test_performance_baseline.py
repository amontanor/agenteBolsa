"""Tests del baseline de rendimiento e iq_score (T0.2)."""

import math
from types import SimpleNamespace

from agente_bolsa.storage import Store
from agente_bolsa.tools.performance_baseline import (
    _lab_promotion_quality,
    _max_drawdown,
    _sharpe,
    build_daily_performance,
    system_iq_score,
)


def _store(tmp_path):
    store = Store(tmp_path / "db.sqlite3", tmp_path / "agents")
    store.ensure_schema()
    return store


def _settings(tmp_path):
    return SimpleNamespace(market_data_provider="auto", fmp_api_key=None, data_dir=tmp_path)


def _seed_neutral_perf(store):
    for i in range(1, 21):
        store.upsert_performance_daily(
            {"session_date": f"2026-05-{i:02d}", "alpha": 0.0005, "hit_rate_20": 0.55, "profit_factor": 1.8, "iq_score": 60}
        )


def test_lab_promotion_quality_ignores_neutral_changes(tmp_path):
    store = _store(tmp_path)
    for i in range(10):
        store.save_continuous_improvement_applied_change(
            {"applied_change_id": f"n{i}", "change_type": "CODE_CHANGE", "status": "APPLIED", "target_key": "x", "decision": {}}
        )
    assert _lab_promotion_quality(store) == 0.5  # promover neutros no mueve la nota


def test_iq_score_unmoved_by_neutral_but_lowered_by_rollback(tmp_path):
    store = _store(tmp_path)
    _seed_neutral_perf(store)
    iq_neutral = system_iq_score(store)

    store2 = _store(tmp_path / "b")
    _seed_neutral_perf(store2)
    store2.save_continuous_improvement_applied_change(
        {"applied_change_id": "r1", "change_type": "CODE_CHANGE", "status": "ROLLED_BACK", "target_key": "x", "decision": {}}
    )
    iq_reverted = system_iq_score(store2)
    assert iq_reverted < iq_neutral


def test_iq_score_raised_by_improved_promotions(tmp_path):
    store = _store(tmp_path)
    _seed_neutral_perf(store)
    base = system_iq_score(store)
    for i in range(3):
        store.save_continuous_improvement_applied_change(
            {
                "applied_change_id": f"g{i}",
                "change_type": "CODE_CHANGE",
                "status": "APPLIED",
                "target_key": "x",
                "decision": {"watchdog": {"improved": True}},
            }
        )
    assert system_iq_score(store) > base


def test_max_drawdown_manual():
    # Pico 110, valle 90 -> drawdown = (110-90)/110 = 0.1818...
    assert _max_drawdown([100, 110, 90, 95, 120]) == round(20 / 110, 4)


def test_sharpe_zero_variance_and_short_series():
    assert _sharpe([0.01]) is None
    assert _sharpe([0.01, 0.01, 0.01]) is None  # stdev 0


def test_sharpe_matches_manual_formula():
    series = [0.01, -0.005, 0.02, 0.0, 0.015]
    import statistics

    expected = (statistics.fmean(series) / statistics.pstdev(series)) * math.sqrt(252)
    assert _sharpe(series) == round(expected, 4)


def test_build_daily_performance_over_30_sessions(tmp_path):
    store = _store(tmp_path)
    settings = _settings(tmp_path)

    equity = 100000.0
    # 29 sesiones previas con equity creciente 0.1%/dia.
    for i in range(1, 30):
        date = f"2026-05-{i:02d}"
        equity *= 1.001
        payload = build_daily_performance(store, settings, date, equity=equity, spy_pct=0.0005)
        store.upsert_performance_daily(payload)

    # Sesion 30 con SPY presente.
    equity *= 1.001
    row = build_daily_performance(store, settings, "2026-05-30", equity=equity, spy_pct=0.0004)
    assert row["pnl_pct"] is not None
    assert abs(row["pnl_pct"] - 0.001) < 1e-4
    assert row["alpha_vs_spy"] is not None
    assert row["sharpe_60"] is not None
    assert row["max_dd"] is not None and row["max_dd"] >= 0
    assert 0.0 <= row["iq_score"] <= 100.0


def test_day_without_trades_does_not_break(tmp_path):
    store = _store(tmp_path)
    settings = _settings(tmp_path)
    row = build_daily_performance(store, settings, "2026-06-10")
    assert row["signals"] == 0
    assert row["pnl_pct"] is None
    assert row["alpha_vs_spy"] is None
    assert row["iq_score"] == 50.0


def test_spy_absent_degrades_alpha_to_null(tmp_path):
    store = _store(tmp_path)
    settings = _settings(tmp_path)
    store.upsert_performance_daily(
        build_daily_performance(store, settings, "2026-06-08", equity=100000.0, spy_pct=0.001)
    )
    row = build_daily_performance(store, settings, "2026-06-09", equity=100500.0, spy_pct=None)
    assert row["pnl_pct"] is not None
    assert row["alpha_vs_spy"] is None  # sin SPY no hay alpha, pero no rompe


def test_iq_score_stable_with_history(tmp_path):
    store = _store(tmp_path)
    settings = _settings(tmp_path)
    for i in range(1, 6):
        store.upsert_performance_daily(
            build_daily_performance(store, settings, f"2026-06-0{i}", equity=100000.0 + i * 100, spy_pct=0.0005)
        )
    score = system_iq_score(store, window_days=20)
    assert isinstance(score, float)
    assert 0.0 <= score <= 100.0


def test_performance_daily_round_trip(tmp_path):
    store = _store(tmp_path)
    settings = _settings(tmp_path)
    payload = build_daily_performance(store, settings, "2026-06-10", equity=123456.0, spy_pct=0.001)
    store.upsert_performance_daily(payload)
    rows = store.performance_daily(limit=0)
    assert len(rows) == 1
    assert rows[0]["session_date"] == "2026-06-10"
    assert rows[0]["equity"] == 123456.0
    latest = store.latest_performance_daily()
    assert latest["session_date"] == "2026-06-10"
