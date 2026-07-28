"""Caracterizacion P-L57A de filas performance_daily incompletas."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement import promotion_readiness
from agente_bolsa.continuous_improvement.digest import build_lab_digest
from agente_bolsa.storage import Store
from agente_bolsa.tools import profitability_scoreboard


def _store(tmp_path) -> Store:
    settings = Settings(DATA_DIR=tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def _patch_scoreboard_dependencies(monkeypatch) -> None:
    monkeypatch.setattr(
        profitability_scoreboard,
        "build_spy_daily_returns",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        profitability_scoreboard,
        "linked_executed_buy_signals",
        lambda *_args, **_kwargs: {
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
    monkeypatch.setattr(
        profitability_scoreboard,
        "build_exit_horizon_shadow",
        lambda *_args, **_kwargs: {},
    )


def _seed(store: Store, rows: list[dict]) -> None:
    for row in rows:
        store.upsert_performance_daily(row)


def test_exact_23_null_pnl_does_not_break_scoreboard(monkeypatch, tmp_path) -> None:
    settings = Settings(DATA_DIR=tmp_path)
    store = _store(tmp_path)
    _seed(
        store,
        [
            {"session_date": "2026-07-22", "equity": 70500.0, "pnl_pct": 0.001},
            {
                "session_date": "2026-07-23",
                "equity": 70400.0,
                "pnl_pct": None,
                "spy_pct": 0.004,
                "alpha": None,
                "payload": {"result_metrics": {"pnl_pct": 0.002288}},
            },
        ],
    )
    _patch_scoreboard_dependencies(monkeypatch)

    summary = profitability_scoreboard._performance_summary(settings, store, since_date="2026-07-01")

    assert summary["available"] is True
    assert summary["cumulative_pnl_pct"] == 0.001
    assert summary["max_drawdown"] is not None
    assert summary["metric_coverage"]["pnl_pct"] == {"available": 1, "total": 2, "status": "partial"}


def test_exact_24_keeps_missing_return_and_alpha_null(monkeypatch, tmp_path) -> None:
    settings = Settings(DATA_DIR=tmp_path)
    store = _store(tmp_path)
    _seed(
        store,
        [
            {
                "session_date": "2026-07-24",
                "equity": 70507.63,
                "pnl_pct": None,
                "spy_pct": 0.0064889025,
                "alpha": None,
                "max_dd": None,
                "payload": {"result_metrics": {"pnl_pct": 0.002288, "alpha_vs_spy": -0.004201}},
            }
        ],
    )
    _patch_scoreboard_dependencies(monkeypatch)

    report = profitability_scoreboard.build_profitability_scoreboard(settings, store, since_date="2026-07-01")

    performance = report["performance"]
    assert performance["cumulative_pnl_pct"] is None
    assert performance["cumulative_alpha"] is None
    assert performance["cumulative_spy_pct"] == 0.006489
    assert performance["max_drawdown"] is None
    assert performance["series"][0]["pnl_pct"] is None


def test_mixed_rows_exclude_invalid_numbers_and_keep_valid_rows(monkeypatch, tmp_path) -> None:
    settings = Settings(DATA_DIR=tmp_path)
    store = _store(tmp_path)
    _seed(
        store,
        [
            {"session_date": "2026-07-21", "equity": 70000.0, "pnl_pct": 0.01, "spy_pct": 0.002},
            {"session_date": "2026-07-22", "equity": 70100.0, "pnl_pct": None, "spy_pct": None},
            {"session_date": "2026-07-23", "equity": 70200.0, "pnl_pct": "bad", "spy_pct": float("nan")},
            {"session_date": "2026-07-24", "equity": 70300.0, "pnl_pct": float("inf"), "spy_pct": True},
        ],
    )
    _patch_scoreboard_dependencies(monkeypatch)

    performance = profitability_scoreboard._performance_summary(settings, store, since_date="2026-07-01")

    assert performance["cumulative_pnl_pct"] == 0.01
    assert performance["cumulative_spy_pct"] == 0.002
    assert performance["cumulative_alpha"] == 0.008
    assert performance["metric_coverage"]["pnl_pct"] == {"available": 1, "total": 4, "status": "partial"}
    assert performance["metric_coverage"]["spy_pct"] == {"available": 1, "total": 4, "status": "partial"}
    assert all(math.isfinite(value) for value in (performance["cumulative_pnl_pct"], performance["cumulative_spy_pct"]))


def test_all_null_or_invalid_metrics_are_unavailable(monkeypatch, tmp_path) -> None:
    settings = Settings(DATA_DIR=tmp_path)
    store = _store(tmp_path)
    _seed(
        store,
        [
            {"session_date": "2026-07-21", "pnl_pct": None, "spy_pct": None, "max_dd": None},
            {"session_date": "2026-07-22", "pnl_pct": float("nan"), "spy_pct": float("inf")},
            {"session_date": "2026-07-23", "pnl_pct": True, "spy_pct": "bad", "max_dd": -0.02},
        ],
    )
    _patch_scoreboard_dependencies(monkeypatch)

    performance = profitability_scoreboard._performance_summary(settings, store, since_date="2026-07-01")

    assert performance["cumulative_pnl_pct"] is None
    assert performance["cumulative_spy_pct"] is None
    assert performance["cumulative_alpha"] is None
    assert performance["max_drawdown"] == -0.02
    assert performance["metric_coverage"]["pnl_pct"]["status"] == "unavailable"


def test_scoreboard_promotion_and_weekly_digest_survive_partial_rows(monkeypatch, tmp_path) -> None:
    settings = Settings(DATA_DIR=tmp_path)
    store = _store(tmp_path)
    _seed(store, [{"session_date": "2026-07-24", "pnl_pct": None, "spy_pct": None, "max_dd": None}])
    _patch_scoreboard_dependencies(monkeypatch)
    monkeypatch.setattr(promotion_readiness, "_executed_rows", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(promotion_readiness, "_build_spy_forward_context", lambda *_args, **_kwargs: {"returns": {}})

    scoreboard = profitability_scoreboard.build_profitability_scoreboard(settings, store, since_date="2026-07-01")
    readiness = promotion_readiness.evaluate_promotion_readiness(settings, store, since_date="2026-07-01")
    digest = build_lab_digest(store, days=7, data_dir=settings.data_dir, now=datetime(2026, 7, 25, tzinfo=timezone.utc))

    assert scoreboard["performance"]["cumulative_pnl_pct"] is None
    assert readiness["scoreboard"]["performance"]["cumulative_alpha"] is None
    assert digest["performance_benchmark"]["freshness"]["status"] == "unavailable"


def test_promotion_missing_metrics_remain_unavailable_not_zero() -> None:
    decision = promotion_readiness._candidate_decision(
        kind="setup",
        key="orderly_breakout",
        rows=[],
        benchmark={},
    )

    assert decision["promotion_checks"]["positive_alpha_margin"] is False
    assert decision["retire_checks"]["negative_alpha"] is False
    assert "alpha_10d" in decision["unavailable_metrics"]


def test_web_performance_series_marks_incomplete_pair_pending() -> None:
    from agente_bolsa import web_app

    rows = [
        {"session_date": "2026-07-23", "pnl_pct": None, "spy_pct": 0.004, "iq_score": 31.0},
        {"session_date": "2026-07-24", "pnl_pct": 0.002, "spy_pct": None, "iq_score": None},
    ]

    chart_rows, cumulative_pnl, cumulative_spy = web_app._performance_baseline_series(rows)

    assert chart_rows[0]["Sistema"] is None
    # P-L65B makes the comparison atomic: an isolated benchmark value cannot
    # be presented as a comparable series when the account leg is missing.
    assert chart_rows[0]["SPY"] is None
    assert chart_rows[1]["Sistema"] is None
    assert chart_rows[1]["SPY"] is None
    assert cumulative_pnl is None
    assert cumulative_spy is None
