from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from agente_bolsa.config import Settings
from agente_bolsa.market_calendar import MarketCalendar
from agente_bolsa.models import PortfolioSnapshot
from agente_bolsa.storage import Store
from agente_bolsa.tools.pre_earnings import (
    backfill_pending_pre_earnings_estimates,
    build_pre_earnings_estimation_history,
    build_pre_earnings_resolved_history,
    build_pre_earnings_tracking_status,
    build_pre_earnings_event_study,
    build_pre_earnings_learning_digest,
    build_pre_earnings_report,
    build_pre_earnings_score_study,
    build_pre_earnings_trade_operation,
    build_pre_earnings_trade_recommendations,
    calculate_pre_earnings_score_v2,
    calculate_success_summary,
    enrich_report_with_local_analyst_revisions,
    enrich_report_with_pre_earnings_score_v2,
    normalize_pre_earnings_score,
    _analyst_expectation_features,
    _frame_from_cached_rows,
    _technical_hypothesis,
    load_pre_earnings_learning_context,
    record_pre_earnings_analyst_snapshots,
    record_pre_earnings_predictions,
    target_after_close_session,
    update_pre_earnings_outcomes,
    upcoming_after_close_sessions,
)


def test_target_after_close_session_uses_current_open_session_close():
    calendar = MarketCalendar("XNYS", "Europe/Madrid")
    now = datetime(2026, 5, 1, 18, 0, tzinfo=ZoneInfo("Europe/Madrid"))

    assert target_after_close_session(calendar, now).isoformat() == "2026-05-01"


def test_target_after_close_session_keeps_just_closed_session():
    calendar = MarketCalendar("XNYS", "Europe/Madrid")
    now = datetime(2026, 5, 1, 23, 0, tzinfo=ZoneInfo("Europe/Madrid"))

    assert target_after_close_session(calendar, now).isoformat() == "2026-05-01"


def test_upcoming_after_close_sessions_returns_requested_market_days():
    calendar = MarketCalendar("XNYS", "Europe/Madrid")
    now = datetime(2026, 5, 1, 18, 0, tzinfo=ZoneInfo("Europe/Madrid"))

    sessions = upcoming_after_close_sessions(calendar, session_count=5, now=now)

    assert [item.isoformat() for item in sessions] == [
        "2026-05-01",
        "2026-05-04",
        "2026-05-05",
        "2026-05-06",
        "2026-05-07",
    ]


def test_calculate_success_summary_ignores_pending_and_scores_bullish_hits():
    sessions = [
        {
            "items": [
                {
                    "hypothesis": "subida_probable",
                    "outcome": {"return_pct": 0.02},
                },
                {
                    "hypothesis": "neutral_alcista",
                    "outcome": {"return_pct": -0.01},
                },
                {
                    "hypothesis": "subida_probable",
                    "outcome": {"return_pct": None},
                },
                {
                    "hypothesis": "sin_ventaja_clara",
                    "outcome": {"return_pct": 0.03},
                },
            ]
        }
    ]

    summary = calculate_success_summary(sessions)

    assert summary["total_events"] == 4
    assert summary["resolved_count"] == 3
    assert summary["pending_count"] == 1
    assert summary["bullish_predictions"] == 3
    assert summary["bullish_resolved"] == 2
    assert summary["bullish_hits"] == 1
    assert summary["bullish_misses"] == 1
    assert summary["success_rate"] == 0.5


def test_build_pre_earnings_report_reuses_calendar_cache(monkeypatch, tmp_path):
    calls = {"earnings": 0}

    def fake_sessions(*_args, **_kwargs):
        return [datetime(2026, 5, 1).date()]

    def fake_earnings_rows(symbol: str, limit: int = 12):
        calls["earnings"] += 1
        frame = pd.DataFrame(
            [
                {
                    "earnings_datetime": pd.Timestamp("2026-05-01T16:00:00-04:00"),
                    "EPS Estimate": 1.0,
                    "Reported EPS": None,
                    "Surprise(%)": None,
                }
            ]
        )
        frame = frame.set_index("earnings_datetime", drop=False)
        return frame, None

    monkeypatch.setattr("agente_bolsa.tools.pre_earnings.upcoming_after_close_sessions", fake_sessions)
    monkeypatch.setattr("agente_bolsa.tools.pre_earnings._earnings_rows", fake_earnings_rows)
    monkeypatch.setattr("agente_bolsa.tools.pre_earnings.download_daily_prices", lambda *_args, **_kwargs: pd.DataFrame())

    first = build_pre_earnings_report(
        ["AAPL"],
        tmp_path / "reports",
        "first",
        cache_dir=tmp_path / "cache",
    )
    second = build_pre_earnings_report(
        ["AAPL"],
        tmp_path / "reports",
        "second",
        cache_dir=tmp_path / "cache",
    )

    assert calls["earnings"] == 1
    assert first["data_quality"]["yfinance_calls"] == 1
    assert second["data_quality"]["cache_hits"] == 1
    assert second["sessions"][0]["items"][0]["source"] == "cache"


def test_build_pre_earnings_report_groups_next_premarket_with_prior_session(monkeypatch, tmp_path):
    def fake_sessions(*_args, **_kwargs):
        return [datetime(2026, 5, 1).date(), datetime(2026, 5, 4).date()]

    def fake_earnings_rows(symbol: str, limit: int = 12):
        frame = pd.DataFrame(
            [
                {
                    "earnings_datetime": pd.Timestamp("2026-05-04T08:00:00-04:00"),
                    "EPS Estimate": 1.0,
                    "Reported EPS": None,
                    "Surprise(%)": None,
                }
            ]
        )
        frame = frame.set_index("earnings_datetime", drop=False)
        return frame, None

    monkeypatch.setattr("agente_bolsa.tools.pre_earnings.upcoming_after_close_sessions", fake_sessions)
    monkeypatch.setattr(
        "agente_bolsa.tools.pre_earnings.datetime",
        type(
            "FixedDateTime",
            (datetime,),
            {"now": classmethod(lambda cls, tz=None: datetime(2026, 5, 2, 10, 0, tzinfo=tz))},
        ),
    )
    monkeypatch.setattr("agente_bolsa.tools.pre_earnings._earnings_rows", fake_earnings_rows)
    monkeypatch.setattr("agente_bolsa.tools.pre_earnings.download_daily_prices", lambda *_args, **_kwargs: pd.DataFrame())

    report = build_pre_earnings_report(
        ["AAPL"],
        tmp_path / "reports",
        "premarket",
        session_count=1,
        cache_dir=tmp_path / "cache",
    )

    item = report["sessions"][0]["items"][0]
    assert report["sessions"][0]["session_date"] == "2026-05-01"
    assert item["estimated_on"] == "2026-05-02"
    assert item["base_session_date"] == "2026-05-01"
    assert item["earnings_date"] == "2026-05-04"
    assert item["earnings_session"] == "pre-market"
    assert item["earnings_time"] == "08:00"


def test_cached_earnings_rows_accept_mixed_timezones():
    frame = _frame_from_cached_rows(
        [
            {
                "earnings_datetime": "2026-05-04T16:00:00-04:00",
                "EPS Estimate": 1.0,
                "Reported EPS": None,
                "Surprise(%)": None,
            },
            {
                "earnings_datetime": "2026-11-04T16:00:00-05:00",
                "EPS Estimate": 1.2,
                "Reported EPS": None,
                "Surprise(%)": None,
            },
        ]
    )

    assert len(frame) == 2
    assert str(frame["earnings_datetime"].dt.tz) == "UTC"


def test_technical_hypothesis_uses_earnings_history():
    dates = pd.date_range("2025-01-01", periods=260, freq="B")
    rows = []
    price = 100.0
    for index, _day in enumerate(dates):
        price *= 1.001
        rows.append(
            {
                "Open": price * 0.99,
                "High": price * 1.01,
                "Low": price * 0.98,
                "Close": price,
                "Volume": 1_000_000 + index * 1_000,
            }
        )
    frame = pd.DataFrame(rows, index=dates)
    weak_history = {
        "earnings_history_count": 8,
        "earnings_positive_rate": 0.25,
        "earnings_big_gap_rate": 0.0,
        "earnings_down_gap_rate": 0.5,
        "earnings_reaction_avg": -0.02,
    }
    strong_history = {
        "earnings_history_count": 8,
        "earnings_positive_rate": 0.75,
        "earnings_big_gap_rate": 0.25,
        "earnings_down_gap_rate": 0.0,
        "earnings_reaction_avg": 0.03,
    }

    weak = _technical_hypothesis("AAPL", frame, frame, weak_history)
    strong = _technical_hypothesis("AAPL", frame, frame, strong_history)

    assert strong["score"] > weak["score"]
    assert strong["max_score"] == 16
    assert strong["earnings_positive_rate"] == 0.75
    assert "historico earnings mayoritariamente positivo" in strong["reason"]


def test_technical_hypothesis_uses_analyst_expectations():
    dates = pd.date_range("2025-01-01", periods=260, freq="B")
    frame = pd.DataFrame(
        [
            {
                "Open": 100 + idx,
                "High": 101 + idx,
                "Low": 99 + idx,
                "Close": 100 + idx,
                "Volume": 1_000_000 + idx,
            }
            for idx, _day in enumerate(dates)
        ],
        index=dates,
    )
    base = _technical_hypothesis("AAPL", frame, frame, {})
    with_expectations = _technical_hypothesis(
        "AAPL",
        frame,
        frame,
        {},
        {
            "analyst_estimates_error": None,
            "analyst_eps_count": 7,
            "analyst_revenue_count": 9,
            "analyst_eps_growth_vs_prev": 0.12,
            "analyst_revenue_growth_vs_prev": 0.08,
        },
    )

    assert with_expectations["score"] >= base["score"] + 4
    assert with_expectations["analyst_eps_growth_vs_prev"] == 0.12
    assert "EPS esperado crece" in with_expectations["reason"]


def test_pre_earnings_predictions_are_persisted_and_resolved(monkeypatch, tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    report = {
        "run_id": "preearn_test",
        "as_of": "2026-04-30T19:00:00+00:00",
        "sessions": [
            {
                "session_date": "2026-04-30",
                "items": [
                    {
                        "symbol": "AAPL",
                        "session_date": "2026-04-30",
                        "earnings_datetime": "2026-04-30T16:00:00-04:00",
                        "hypothesis": "subida_probable",
                        "score": 7,
                        "max_score": 8,
                        "reason": "test",
                        "last_close": 100.0,
                        "outcome": {"status": "pendiente", "return_pct": None},
                    }
                ],
            }
        ],
    }

    saved = record_pre_earnings_predictions(store, report)
    status = build_pre_earnings_tracking_status(store)

    assert saved == 1
    assert status["total_predictions"] == 1
    assert status["pending_count"] == 1

    prices = pd.DataFrame(
        [
            {"Open": 99.0, "High": 101.0, "Low": 98.0, "Close": 100.0, "Volume": 1000},
            {"Open": 103.0, "High": 104.0, "Low": 102.0, "Close": 103.5, "Volume": 1200},
        ],
        index=pd.to_datetime(["2026-04-30", "2026-05-01"]),
    )
    monkeypatch.setattr("agente_bolsa.tools.pre_earnings.download_daily_prices", lambda *_args, **_kwargs: prices)

    updated = update_pre_earnings_outcomes(store, lookback_days=3650)
    status = build_pre_earnings_tracking_status(store)

    assert updated["updated"] == 1
    assert status["resolved_count"] == 1
    assert status["bullish_hits"] == 1
    assert status["success_rate"] == 1.0


def test_local_analyst_snapshots_generate_revision_features(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    previous = {
        "run_id": "old",
        "as_of": "2026-04-20T19:00:00+00:00",
        "sessions": [
            {
                "items": [
                    {
                        "symbol": "AAPL",
                        "session_date": "2026-05-01",
                        "earnings_datetime": "2026-05-01T16:00:00-04:00",
                        "analyst_eps_estimate": 1.0,
                        "analyst_revenue_estimate": 100.0,
                        "analyst_eps_count": 8,
                        "analyst_revenue_count": 8,
                    }
                ]
            }
        ],
    }
    current = {
        "run_id": "new",
        "as_of": "2026-05-01T19:00:00+00:00",
        "sessions": [
            {
                "items": [
                    {
                        "symbol": "AAPL",
                        "session_date": "2026-05-01",
                        "earnings_datetime": "2026-05-01T16:00:00-04:00",
                        "analyst_eps_estimate": 1.1,
                        "analyst_revenue_estimate": 105.0,
                        "analyst_eps_count": 9,
                        "analyst_revenue_count": 9,
                    }
                ]
            }
        ],
    }

    assert record_pre_earnings_analyst_snapshots(store, previous) == 1
    assert previous["analyst_snapshot_coverage"] == {
        "candidates": 1,
        "saved": 1,
        "missing_estimates": 0,
        "coverage_rate": 1.0,
    }
    updated = enrich_report_with_local_analyst_revisions(store, current)
    item = current["sessions"][0]["items"][0]

    assert updated == 1
    assert item["analyst_eps_revision_7d_local"] == 0.1
    assert item["analyst_revenue_revision_7d_local"] == 0.05


def test_analyst_expectation_features_fallback_to_yfinance_snapshot(monkeypatch):
    monkeypatch.setattr(
        "agente_bolsa.tools.pre_earnings._yfinance_analyst_snapshot",
        lambda _symbol: (
            {
                "analyst_eps_estimate": 1.25,
                "analyst_revenue_estimate": 120.0,
                "analyst_eps_count": 18.0,
                "analyst_revenue_count": 15.0,
                "analyst_eps_growth_vs_prev": 0.14,
                "analyst_revenue_growth_vs_prev": 0.08,
                "analyst_eps_revision_7d_model": 0.03,
                "analyst_eps_revision_30d_model": 0.07,
            },
            None,
        ),
    )

    features, diagnostics = _analyst_expectation_features("AAPL", datetime(2026, 5, 1).date(), {}, api_key=None)

    assert diagnostics["source"] == "yfinance"
    assert features["analyst_estimates_source"] == "yfinance"
    assert features["analyst_estimates_error"] is None
    assert features["analyst_eps_estimate"] == 1.25
    assert features["analyst_revenue_estimate"] == 120.0
    assert features["analyst_eps_revision_7d_model"] == 0.03
    assert features["analyst_eps_revision_30d_model"] == 0.07


def test_analyst_snapshot_coverage_reports_missing_estimates(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    report = {
        "run_id": "missing-analyst",
        "as_of": "2026-05-01T19:00:00+00:00",
        "sessions": [{"items": [{"symbol": "AAPL"}, {"symbol": "MSFT", "analyst_eps_estimate": 1.2}]}],
    }

    assert record_pre_earnings_analyst_snapshots(store, report) == 1
    assert report["analyst_snapshot_coverage"] == {
        "candidates": 2,
        "saved": 1,
        "missing_estimates": 1,
        "coverage_rate": 0.5,
    }


def test_estimation_history_marks_latest_pre_earnings_as_official(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    first = {
        "run_id": "first",
        "as_of": "2026-05-01T19:00:00+00:00",
        "sessions": [
            {
                "session_date": "2026-05-04",
                "items": [
                    {
                        "symbol": "AAPL",
                        "session_date": "2026-05-04",
                        "estimated_on": "2026-05-01",
                        "earnings_date": "2026-05-04",
                        "earnings_session": "post-market",
                        "earnings_datetime": "2026-05-04T16:00:00-04:00",
                        "hypothesis": "neutral_alcista",
                        "score": 6,
                        "max_score": 16,
                        "reason": "primera",
                        "outcome": {"status": "pendiente", "return_pct": None},
                    }
                ],
            }
        ],
    }
    second = {
        "run_id": "second",
        "as_of": "2026-05-02T19:00:00+00:00",
        "sessions": [
            {
                "session_date": "2026-05-04",
                "items": [
                    {
                        "symbol": "AAPL",
                        "session_date": "2026-05-04",
                        "estimated_on": "2026-05-02",
                        "earnings_date": "2026-05-04",
                        "earnings_session": "post-market",
                        "earnings_datetime": "2026-05-04T16:00:00-04:00",
                        "hypothesis": "subida_probable",
                        "score": 10,
                        "max_score": 16,
                        "reason": "segunda",
                        "outcome": {"status": "pendiente", "return_pct": None},
                    }
                ],
            }
        ],
    }

    record_pre_earnings_predictions(store, first)
    record_pre_earnings_predictions(store, second)
    history = build_pre_earnings_estimation_history(store, second)
    item = next(iter(history.values()))

    assert item["count"] == 2
    assert item["first_hypothesis"] == "neutral_alcista"
    assert item["official_hypothesis"] == "subida_probable"
    assert item["official_prediction_date"] == "2026-05-02"
    assert "*" in item["timeline"]


def test_resolved_history_reports_hit_and_real_return(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    report = {
        "run_id": "resolved",
        "as_of": "2026-05-02T19:00:00+00:00",
        "sessions": [
            {
                "session_date": "2026-05-01",
                "items": [
                    {
                        "symbol": "AAPL",
                        "session_date": "2026-05-01",
                        "earnings_date": "2026-05-01",
                        "earnings_session": "post-market",
                        "earnings_datetime": "2026-05-01T16:00:00-04:00",
                        "hypothesis": "subida_probable",
                        "score": 13,
                        "max_score": 16,
                        "reason": "test",
                        "outcome": {"status": "publicado_next_open", "return_pct": 0.042},
                    }
                ],
            }
        ],
    }

    record_pre_earnings_predictions(store, report)
    rows = build_pre_earnings_resolved_history(store)

    assert len(rows) == 1
    assert rows[0]["status"] == "acierto"
    assert rows[0]["return_pct"] == 0.042
    assert rows[0]["score_pct"] == 0.8125


def test_normalize_pre_earnings_score_uses_0_to_100_scale():
    assert normalize_pre_earnings_score(8, 16) == 50.0
    assert normalize_pre_earnings_score(7, 8) == 87.5
    assert normalize_pre_earnings_score(1, 0) is None


def test_score_v2_uses_momentum_history_research_and_risk():
    ftnt = {
        "symbol": "FTNT",
        "prediction_date": "2026-05-06",
        "created_at": "2026-05-06T19:00:00+00:00",
        "hypothesis": "sin_ventaja_clara",
        "score": 5,
        "max_score": 16,
        "features": {
            "return_20d": 0.077116,
            "rel_strength_spy_20d": -0.008415,
            "above_sma50": True,
            "above_sma200": True,
            "volume_zscore_20": 0.802399,
            "earnings_history_count": 8,
            "earnings_positive_rate": 0.5,
            "earnings_big_gap_rate": 0.125,
            "earnings_down_gap_rate": 0.5,
            "earnings_reaction_avg": -0.026801,
        },
    }
    tdg = {
        "symbol": "TDG",
        "prediction_date": "2026-05-02",
        "created_at": "2026-05-02T19:00:00+00:00",
        "hypothesis": "sin_ventaja_clara",
        "score": 0,
        "max_score": 16,
        "features": {
            "return_20d": -0.010754,
            "rel_strength_spy_20d": -0.109591,
            "above_sma50": False,
            "above_sma200": False,
            "volume_zscore_20": -0.398911,
            "earnings_history_count": 0,
        },
    }
    axon = {
        "symbol": "AXON",
        "prediction_date": "2026-05-05",
        "created_at": "2026-05-05T19:00:00+00:00",
        "hypothesis": "sin_ventaja_clara",
        "score": 4,
        "max_score": 16,
        "features": {
            "return_20d": -0.046772,
            "rel_strength_spy_20d": -0.136433,
            "above_sma50": False,
            "above_sma200": False,
            "volume_zscore_20": -0.643232,
            "earnings_history_count": 8,
            "earnings_positive_rate": 0.75,
            "earnings_big_gap_rate": 0.75,
            "earnings_down_gap_rate": 0.125,
            "earnings_reaction_avg": 0.062534,
        },
    }

    for prediction in [ftnt, tdg, axon]:
        result = calculate_pre_earnings_score_v2(prediction, [prediction])
        assert result["score_v2_label"] in {"neutral_alcista", "subida_probable"}
        assert result["pre_earnings_score_v2"] >= 45


def test_score_v2_promotes_high_conviction_pre_earnings_to_subida_probable():
    ddog = {
        "symbol": "DDOG",
        "prediction_date": "2026-05-06",
        "created_at": "2026-05-06T19:00:00+00:00",
        "hypothesis": "neutral_alcista",
        "score": 8,
        "max_score": 16,
        "features": {
            "return_20d": 0.233562,
            "rel_strength_spy_20d": 0.148031,
            "above_sma50": True,
            "above_sma200": True,
            "volume_zscore_20": 1.874932,
            "earnings_history_count": 8,
            "earnings_positive_rate": 1.0,
            "earnings_big_gap_rate": 1.0,
            "earnings_down_gap_rate": 0.0,
            "earnings_reaction_avg": 0.161366,
        },
    }
    history = [
        {
            **ddog,
            "prediction_date": "2026-05-02",
            "created_at": "2026-05-02T19:00:00+00:00",
        },
        {
            **ddog,
            "prediction_date": "2026-05-05",
            "created_at": "2026-05-05T19:00:00+00:00",
        },
        ddog,
    ]

    result = calculate_pre_earnings_score_v2(ddog, history)

    assert result["pre_earnings_score_v2"] >= 70
    assert result["score_v2_label"] == "subida_probable"


def test_score_v2_promotes_catalyst_supported_bullish_pre_earnings():
    mnst = {
        "symbol": "MNST",
        "prediction_date": "2026-05-06",
        "created_at": "2026-05-06T19:00:00+00:00",
        "hypothesis": "neutral_alcista",
        "score": 7,
        "max_score": 16,
        "features": {
            "return_20d": 0.035,
            "rel_strength_spy_20d": 0.012,
            "above_sma50": True,
            "above_sma200": True,
            "volume_zscore_20": 0.2,
            "earnings_history_count": 8,
            "earnings_positive_rate": 0.75,
            "earnings_big_gap_rate": 0.125,
            "earnings_down_gap_rate": 0.125,
            "earnings_reaction_avg": 0.03,
        },
    }

    result = calculate_pre_earnings_score_v2(mnst, [mnst])

    assert result["pre_earnings_score_v2"] >= 70
    assert result["score_v2_label"] == "subida_probable"
    assert result["actionable_pre_earnings_long"] is True


def test_score_v2_promotes_external_momentum_override_without_lookahead():
    amd = {
        "symbol": "AMD",
        "prediction_date": "2026-05-05",
        "created_at": "2026-05-05T19:00:00+00:00",
        "hypothesis": "neutral_alcista",
        "score": 6,
        "max_score": 16,
        "features": {
            "return_20d": 0.26,
            "rel_strength_spy_20d": 0.18,
            "above_sma50": True,
            "above_sma200": True,
            "volume_zscore_20": 1.1,
            "earnings_history_count": 8,
            "earnings_positive_rate": 0.5,
            "earnings_big_gap_rate": 0.125,
            "earnings_down_gap_rate": 0.5,
            "earnings_reaction_avg": 0.01,
        },
    }
    history = [
        {
            **amd,
            "prediction_date": "2026-05-02",
            "created_at": "2026-05-02T19:00:00+00:00",
            "score": 6,
            "max_score": 16,
        },
        amd,
    ]

    result = calculate_pre_earnings_score_v2(amd, history)

    assert result["pre_earnings_score_v2"] >= 70
    assert result["score_v2_label"] == "subida_probable"
    assert result["actionable_pre_earnings_long"] is False
    assert result["high_conviction_pre_earnings_long"] is True
    assert result["review_pre_earnings_risk_veto"] is True


def test_score_v2_keeps_neutral_when_external_support_is_not_strong_enough():
    app = {
        "symbol": "APP",
        "prediction_date": "2026-05-05",
        "created_at": "2026-05-05T19:00:00+00:00",
        "hypothesis": "neutral_alcista",
        "score": 7,
        "max_score": 16,
        "features": {
            "return_20d": 0.18,
            "rel_strength_spy_20d": 0.12,
            "above_sma50": True,
            "above_sma200": True,
            "volume_zscore_20": 0.7,
            "earnings_history_count": 8,
            "earnings_positive_rate": 0.75,
            "earnings_big_gap_rate": 0.75,
            "earnings_down_gap_rate": 0.125,
            "earnings_reaction_avg": 0.06,
        },
    }
    result = calculate_pre_earnings_score_v2(app, [app])

    assert result["pre_earnings_score_v2"] < 70
    assert result["score_v2_label"] == "neutral_alcista"
    assert result["actionable_pre_earnings_long"] is False


def test_score_v2_marks_external_low_risk_bullish_as_actionable():
    tdg = {
        "symbol": "TDG",
        "prediction_date": "2026-05-02",
        "created_at": "2026-05-02T19:00:00+00:00",
        "hypothesis": "sin_ventaja_clara",
        "score": 0,
        "max_score": 16,
        "features": {
            "return_20d": None,
            "rel_strength_spy_20d": None,
            "above_sma50": False,
            "above_sma200": False,
            "volume_zscore_20": None,
            "earnings_history_count": 0,
        },
    }

    result = calculate_pre_earnings_score_v2(tdg, [tdg])

    assert result["pre_earnings_score_v2"] == 45.0
    assert result["score_v2_label"] == "neutral_alcista"
    assert result["actionable_pre_earnings_long"] is True
    assert result["actionable_pre_earnings_reason"] == "catalizador fuerte con riesgo contenido"


def test_score_study_groups_events_and_reports_daily_and_final_scores(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    first = {
        "run_id": "old",
        "as_of": "2026-05-05T19:00:00+00:00",
        "sessions": [
            {
                "session_date": "2026-05-06",
                "items": [
                    {
                        "symbol": "FTNT",
                        "session_date": "2026-05-06",
                        "earnings_date": "2026-05-06",
                        "earnings_session": "post-market",
                        "earnings_datetime": "2026-05-06T16:00:00-04:00",
                        "hypothesis": "sin_ventaja_clara",
                        "score": 4,
                        "max_score": 16,
                        "reason": "primera",
                        "return_20d": 0.077116,
                        "rel_strength_spy_20d": -0.008415,
                        "above_sma50": True,
                        "above_sma200": True,
                        "volume_zscore_20": 0.802399,
                        "earnings_history_count": 8,
                        "earnings_positive_rate": 0.5,
                        "earnings_big_gap_rate": 0.125,
                        "earnings_down_gap_rate": 0.5,
                        "earnings_reaction_avg": -0.026,
                        "outcome": {"status": "pendiente", "return_pct": None},
                    }
                ],
            }
        ],
    }
    final = {
        "run_id": "new",
        "as_of": "2026-05-06T19:00:00+00:00",
        "sessions": [
            {
                "session_date": "2026-05-06",
                "items": [
                    {
                        **first["sessions"][0]["items"][0],
                        "score": 5,
                        "reason": "final",
                        "outcome": {"status": "publicado_next_open", "return_pct": 0.1723},
                    }
                ],
            }
        ],
    }

    record_pre_earnings_predictions(store, first)
    record_pre_earnings_predictions(store, final)
    study = build_pre_earnings_score_study(store, tmp_path / "reports", "score")

    assert study["metrics"]["events"] == 1
    assert study["metrics"]["resolved_events"] == 1
    assert study["metrics"]["big_winners_gt_5"] == 1
    assert study["metrics"]["v2_big_winners_bullish"] == 1
    assert study["metrics"]["v2_big_winners_high_conviction"] == 1
    assert study["metrics"]["v2_blocked_big_winners"] == 1
    assert study["big_winners"][0]["final_label_v2"] in {"neutral_alcista", "subida_probable"}
    assert study["blocked_big_winners"][0]["symbol"] == "FTNT"
    assert len(study["big_winners"][0]["daily_scores"]) == 2
    assert Path(study["path"]).exists()


def test_pre_earnings_learning_digest_reports_blocked_big_winners_and_snapshot_health(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    report = {
        "run_id": "digest-src",
        "as_of": "2026-05-06T19:00:00+00:00",
        "sessions": [
            {
                "session_date": "2026-05-06",
                "items": [
                    {
                        "symbol": "FTNT",
                        "session_date": "2026-05-06",
                        "earnings_date": "2026-05-06",
                        "earnings_session": "post-market",
                        "earnings_datetime": "2026-05-06T16:00:00-04:00",
                        "hypothesis": "sin_ventaja_clara",
                        "score": 5,
                        "max_score": 16,
                        "reason": "final",
                        "return_20d": 0.077116,
                        "rel_strength_spy_20d": -0.008415,
                        "above_sma50": True,
                        "above_sma200": True,
                        "volume_zscore_20": 0.802399,
                        "earnings_history_count": 8,
                        "earnings_positive_rate": 0.5,
                        "earnings_big_gap_rate": 0.125,
                        "earnings_down_gap_rate": 0.5,
                        "earnings_reaction_avg": -0.026801,
                        "analyst_estimates_error": "FMP_API_KEY no configurada",
                        "outcome": {"status": "publicado_next_open", "return_pct": 0.1723},
                    }
                ],
            }
        ],
    }
    record_pre_earnings_predictions(store, report)

    digest_report = build_pre_earnings_learning_digest(store, tmp_path / "reports", "preearn_digest")
    context = load_pre_earnings_learning_context(tmp_path)

    assert digest_report["metrics"]["blocked_big_winners"] == 1
    assert digest_report["metrics"]["risk_veto_big_winners"] == 1
    assert digest_report["metrics"]["estimate_error_rows"] == 1
    assert digest_report["digest"]["blocked_big_winners"][0]["symbol"] == "FTNT"
    assert context["available"] is True
    assert context["summary"]["blocked_big_winners"] == 1


def test_backfill_pending_pre_earnings_estimates_updates_only_future_pending_rows(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    pending_item = {
        "prediction_id": "p_future",
        "source_run_id": "run_future",
        "symbol": "AAPL",
        "prediction_date": "2026-05-12",
        "session_date": "2026-05-12",
        "earnings_datetime": "2026-05-20T16:00:00-04:00",
        "hypothesis": "neutral_alcista",
        "score": 8,
        "max_score": 16,
        "reason": "pending",
        "features": {
            "earnings_date": "2026-05-20",
            "earnings_session": "post-market",
            "return_20d": 0.12,
            "rel_strength_spy_20d": 0.06,
            "above_sma50": True,
            "above_sma200": True,
            "volume_zscore_20": 0.7,
            "earnings_history_count": 4,
            "earnings_positive_rate": 0.5,
            "earnings_big_gap_rate": 0.25,
            "earnings_down_gap_rate": 0.0,
            "earnings_reaction_avg": 0.03,
        },
        "outcome": {"status": "pendiente", "return_pct": None},
        "status": "pending",
    }
    resolved_item = {
        **pending_item,
        "prediction_id": "p_old",
        "source_run_id": "run_old",
        "prediction_date": "2026-05-01",
        "session_date": "2026-05-01",
        "earnings_datetime": "2026-05-05T16:00:00-04:00",
        "features": {**pending_item["features"], "earnings_date": "2026-05-05"},
        "status": "resolved",
        "outcome": {"status": "publicado_next_open", "return_pct": 0.04},
    }
    store.save_pre_earnings_prediction(pending_item)
    store.save_pre_earnings_prediction(resolved_item)
    monkeypatch.setattr(
        "agente_bolsa.tools.pre_earnings._yfinance_analyst_snapshot",
        lambda _symbol: (
            {
                "analyst_eps_estimate": 1.4,
                "analyst_revenue_estimate": 125.0,
                "analyst_eps_count": 22.0,
                "analyst_revenue_count": 18.0,
                "analyst_eps_growth_vs_prev": 0.12,
                "analyst_revenue_growth_vs_prev": 0.09,
                "analyst_eps_revision_7d_model": 0.02,
                "analyst_eps_revision_30d_model": 0.05,
            },
            None,
        ),
    )

    report = backfill_pending_pre_earnings_estimates(
        store,
        tmp_path / "reports",
        "bf1",
        today=datetime(2026, 5, 12).date(),
        limit=20,
        api_key=None,
    )
    rows = {item["prediction_id"]: item for item in store.pre_earnings_predictions(limit=20)}

    assert report["updated_predictions"] == 1
    assert report["eligible_predictions"] == 1
    assert rows["p_future"]["features"]["analyst_eps_estimate"] == 1.4
    assert rows["p_future"]["features"]["score_v2_label"] in {"neutral_alcista", "subida_probable"}
    assert rows["p_old"]["features"].get("analyst_eps_estimate") is None


def test_daily_report_persists_score_v2_snapshot(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    report = {
        "run_id": "daily-v2",
        "as_of": "2026-05-06T19:00:00+00:00",
        "sessions": [
            {
                "session_date": "2026-05-06",
                "items": [
                    {
                        "symbol": "FTNT",
                        "session_date": "2026-05-06",
                        "earnings_date": "2026-05-06",
                        "earnings_session": "post-market",
                        "earnings_datetime": "2026-05-06T16:00:00-04:00",
                        "hypothesis": "sin_ventaja_clara",
                        "score": 5,
                        "max_score": 16,
                        "reason": "test",
                        "return_20d": 0.077116,
                        "rel_strength_spy_20d": -0.008415,
                        "above_sma50": True,
                        "above_sma200": True,
                        "volume_zscore_20": 0.802399,
                        "earnings_history_count": 8,
                        "earnings_positive_rate": 0.5,
                        "earnings_big_gap_rate": 0.125,
                        "earnings_down_gap_rate": 0.5,
                        "earnings_reaction_avg": -0.026801,
                        "outcome": {"status": "pendiente", "return_pct": None},
                    }
                ],
            }
        ],
    }

    assert enrich_report_with_pre_earnings_score_v2(store, report) == 1
    assert report["sessions"][0]["items"][0]["score_v2_label"] == "neutral_alcista"
    assert report["sessions"][0]["items"][0]["high_conviction_pre_earnings_long"] is True
    assert report["sessions"][0]["items"][0]["actionable_pre_earnings_long"] is False
    assert report["sessions"][0]["items"][0]["review_pre_earnings_risk_veto"] is True
    record_pre_earnings_predictions(store, report)
    saved = store.pre_earnings_predictions(limit=10)[0]

    assert saved["features"]["score_v2_label"] == "neutral_alcista"
    assert saved["features"]["pre_earnings_score_v2"] >= 45
    assert saved["features"]["high_conviction_pre_earnings_long"] is True
    assert saved["features"]["actionable_pre_earnings_long"] is False
    assert saved["features"]["review_pre_earnings_risk_veto"] is True


def test_score_study_regression_current_sqlite(tmp_path):
    db_path = Path("data/state/agente_bolsa.sqlite3")
    if not db_path.exists():
        pytest.skip("local SQLite history is not available")
    store = Store(db_path, Path("data/logs/agents"))
    report = build_pre_earnings_score_study(store, tmp_path / "reports", "pytest-regression")

    assert report["metrics"]["resolved_events"] >= 70
    assert report["metrics"]["big_winners_gt_5"] >= 14
    required = {"FTNT", "TDG", "AXON", "DDOG"}
    by_symbol = {item["symbol"]: item for item in report["big_winners"]}
    assert required <= set(by_symbol)
    for symbol in required:
        assert by_symbol[symbol]["final_label_v2"] in {"neutral_alcista", "subida_probable"}
    assert by_symbol["DDOG"]["final_label_v2"] == "subida_probable"
    assert report["metrics"]["v2_big_winners_high_conviction"] >= report["metrics"]["v2_big_winners_actionable"]


def test_build_pre_earnings_event_study_scores_historical_bullish_hit(monkeypatch, tmp_path):
    dates = pd.date_range("2024-01-01", periods=430, freq="B")

    def symbol_prices(start_price: float, drift: float) -> pd.DataFrame:
        price = start_price
        rows = []
        for idx, _day in enumerate(dates):
            price *= 1 + drift
            open_price = price * 0.998
            if idx == 421:
                open_price = price * 1.05
            rows.append(
                {
                    "Open": open_price,
                    "High": max(open_price, price) * 1.01,
                    "Low": min(open_price, price) * 0.99,
                    "Close": price,
                    "Volume": 1_000_000 + idx * 1_000,
                }
            )
        return pd.DataFrame(rows, index=dates)

    event_day = dates[420]
    aapl = symbol_prices(100.0, 0.0015)
    spy = symbol_prices(100.0, 0.0002)
    price_data = pd.concat({"AAPL": aapl, "SPY": spy}, axis=1)

    def fake_earnings_rows(symbol: str, limit: int = 100):
        frame = pd.DataFrame(
            [
                {
                    "earnings_datetime": pd.Timestamp(event_day).tz_localize("America/New_York")
                    + pd.Timedelta(hours=16),
                    "EPS Estimate": 1.0,
                    "Reported EPS": 1.1,
                    "Surprise(%)": 10.0,
                }
            ]
        )
        frame = frame.set_index("earnings_datetime", drop=False)
        return frame, None

    monkeypatch.setattr("agente_bolsa.tools.pre_earnings._earnings_rows", fake_earnings_rows)
    monkeypatch.setattr("agente_bolsa.tools.pre_earnings.download_daily_prices", lambda *_args, **_kwargs: price_data)

    report = build_pre_earnings_event_study(
        ["AAPL"],
        tmp_path / "reports",
        "study",
        start=str(event_day.date()),
        end=str(event_day.date()),
        cache_dir=tmp_path / "cache",
    )

    assert report["operation_allowed"] is False
    assert report["metrics"]["events"] == 1
    assert report["metrics"]["resolved"] == 1
    assert report["metrics"]["bullish_hits"] == 1
    assert report["metrics"]["success_rate"] == 1.0
    assert report["events"][0]["hypothesis"] in {"subida_probable", "neutral_alcista"}
    assert report["events"][0]["outcome"]["return_pct"] > 0


def test_build_pre_earnings_trade_recommendations_only_uses_current_actionable_items(tmp_path):
    settings = Settings(DATA_DIR=tmp_path)
    report = {
        "sessions": [
            {
                "session_date": "2026-05-12",
                "items": [
                    {
                        "symbol": "AAPL",
                        "last_close": 100.0,
                        "pre_earnings_score_v2": 74.0,
                        "actionable_pre_earnings_long": True,
                        "actionable_pre_earnings_reason": "catalizador fuerte con riesgo contenido",
                        "review_pre_earnings_risk_veto": False,
                        "score_v2_drivers": ["momentum tecnico fuerte", "catalizadores externos/previews favorables"],
                        "score_v2_components": {
                            "risk_penalty": 2,
                            "expectation_score": 4,
                            "external_catalyst_score": 14,
                        },
                    },
                    {
                        "symbol": "AMD",
                        "last_close": 110.0,
                        "pre_earnings_score_v2": 78.0,
                        "actionable_pre_earnings_long": False,
                        "review_pre_earnings_risk_veto": True,
                        "score_v2_components": {"risk_penalty": 7, "external_catalyst_score": 14},
                    },
                ],
            },
            {
                "session_date": "2026-05-13",
                "items": [
                    {
                        "symbol": "MSFT",
                        "last_close": 200.0,
                        "pre_earnings_score_v2": 88.0,
                        "actionable_pre_earnings_long": True,
                        "actionable_pre_earnings_reason": "deberia quedar fuera por no ser la sesion actual",
                        "review_pre_earnings_risk_veto": False,
                        "score_v2_components": {"risk_penalty": 1, "expectation_score": 5, "external_catalyst_score": 16},
                    }
                ],
            },
        ]
    }

    recommendations = build_pre_earnings_trade_recommendations(settings, report)

    assert [item.symbol for item in recommendations] == ["AAPL"]
    recommendation = recommendations[0]
    assert recommendation.source == "pre_earnings"
    assert recommendation.action == "buy"
    assert recommendation.entry_price == 100.0
    assert recommendation.stop_loss < recommendation.entry_price
    assert recommendation.take_profit > recommendation.entry_price
    assert recommendation.confidence >= settings.min_llm_confidence_to_trade


def test_build_pre_earnings_trade_operation_generates_buy_plan(tmp_path):
    settings = Settings(DATA_DIR=tmp_path)
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=10_000.0,
        portfolio_value=10_000.0,
        buying_power=10_000.0,
        positions=[],
        open_orders=[],
    )
    report = {
        "sessions": [
            {
                "session_date": "2026-05-12",
                "items": [
                    {
                        "symbol": "AAPL",
                        "last_close": 100.0,
                        "pre_earnings_score_v2": 82.0,
                        "actionable_pre_earnings_long": True,
                        "actionable_pre_earnings_reason": "catalizador fuerte con riesgo contenido",
                        "review_pre_earnings_risk_veto": False,
                        "score_v2_drivers": ["momentum tecnico fuerte"],
                        "score_v2_components": {
                            "risk_penalty": 1,
                            "expectation_score": 4,
                            "external_catalyst_score": 16,
                        },
                    }
                ],
            }
        ]
    }

    operation = build_pre_earnings_trade_operation(settings, portfolio, report, dry_run=True)

    assert operation["enabled"] is True
    assert operation["actionable_symbols"] == ["AAPL"]
    assert len(operation["recommendations"]) == 1
    assert len(operation["plans"]) == 1
    plan = operation["plans"][0]
    assert plan.symbol == "AAPL"
    assert plan.side == "buy"
    assert plan.recommendation.source == "pre_earnings"
    assert plan.risk_decision.approved is True
