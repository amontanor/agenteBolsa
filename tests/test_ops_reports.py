from __future__ import annotations

import json

import pandas as pd

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.ops_reports import (
    backup_database,
    build_market_data_quality_report,
    build_selection_bandwidth_review,
    build_weekly_trading_review,
)


def _settings(tmp_path):
    return Settings(DATA_DIR=str(tmp_path))


def test_market_data_quality_report_writes_latest(monkeypatch, tmp_path):
    settings = _settings(tmp_path)
    frame = pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [101.0, 102.0],
            "Low": [99.0, 100.0],
            "Close": [100.5, 101.5],
            "Volume": [1_000_000, 1_100_000],
        },
        index=pd.date_range("2026-05-01", periods=2, freq="D"),
    )

    monkeypatch.setattr("agente_bolsa.tools.ops_reports.resolve_study_universe", lambda *args, **kwargs: ["AAPL", "MSFT"])
    monkeypatch.setattr(
        "agente_bolsa.tools.ops_reports.download_daily_prices_with_metadata",
        lambda *args, **kwargs: (
            frame,
            {
                "source": "fmp",
                "requested_count": 2,
                "symbols_with_data_count": 2,
                "coverage_ratio": 1.0,
                "cache_hit": False,
                "cache_age_seconds": 0.0,
                "validation_alerts": [],
                "missing_symbols_count": 0,
            },
        ),
    )

    report = build_market_data_quality_report(settings, tmp_path / "reports", "dq_test")

    assert report["summary"]["provider_used"] == "fmp"
    assert report["summary"]["coverage_ratio"] == 1.0
    assert report["anomalies"] == []
    assert (tmp_path / "reports" / "latest_market_data_quality.json").exists()


def _quality_report(monkeypatch, tmp_path, frame, meta):
    settings = _settings(tmp_path)
    monkeypatch.setattr("agente_bolsa.tools.ops_reports.resolve_study_universe", lambda *args, **kwargs: ["AAPL"])
    monkeypatch.setattr(
        "agente_bolsa.tools.ops_reports.download_daily_prices_with_metadata",
        lambda *args, **kwargs: (frame, meta),
    )
    return build_market_data_quality_report(settings, tmp_path / "reports", "dq_test")


def _quality_meta(**overrides):
    meta = {
        "source": "fmp",
        "requested_count": 1,
        "symbols_with_data_count": 1,
        "coverage_ratio": 1.0,
        "cache_hit": True,
        "cache_key": "stable-cache-key",
        "cache_age_seconds": 12.0,
        "validation_alerts": [],
        "missing_symbols_count": 0,
    }
    meta.update(overrides)
    return meta


def test_market_data_quality_identifies_latest_invalid_ohlc_as_blocking(monkeypatch, tmp_path):
    frame = pd.DataFrame(
        {"Open": [100.0], "High": [99.0], "Low": [98.0], "Close": [101.0], "Volume": [1000.0]},
        index=pd.to_datetime(["2026-05-01"]),
    )

    report = _quality_report(monkeypatch, tmp_path, frame, _quality_meta())

    assert report["anomalies"] == [
        {
            "symbol": "AAPL",
            "date": "2026-05-01",
            "invalid_fields": ["high"],
            "invalidity_class": "ohlc_invalid",
            "severity": "bloqueante",
            "provider": "fmp",
            "cache": {"cache_hit": True, "cache_key": "stable-cache-key", "cache_age_seconds": 12.0},
            "affects_operational_scan": True,
        }
    ]
    assert report["summary"]["real_blockers"] == 1


def test_market_data_quality_identifies_invalid_volume_as_warning(monkeypatch, tmp_path):
    frame = pd.DataFrame(
        {"Open": [100.0], "High": [101.0], "Low": [99.0], "Close": [100.0], "Volume": [-1.0]},
        index=pd.to_datetime(["2026-05-01"]),
    )

    report = _quality_report(monkeypatch, tmp_path, frame, _quality_meta())

    anomaly = report["anomalies"][0]
    assert anomaly["invalidity_class"] == "volume_invalid"
    assert anomaly["severity"] == "advertencia"
    assert anomaly["affects_operational_scan"] is False


def test_market_data_quality_deduplicates_repeated_cached_bar(monkeypatch, tmp_path):
    frame = pd.DataFrame(
        {"Open": [100.0, 100.0], "High": [99.0, 99.0], "Low": [98.0, 98.0], "Close": [101.0, 101.0], "Volume": [1000.0, 1000.0]},
        index=pd.to_datetime(["2026-05-01", "2026-05-01"]),
    )

    report = _quality_report(monkeypatch, tmp_path, frame, _quality_meta())

    assert len(report["anomalies"]) == 1
    assert report["summary"]["anomalies_unique"] == 1


def test_market_data_quality_marks_legacy_alert_without_detail_unavailable(monkeypatch, tmp_path):
    frame = pd.DataFrame(
        {"Open": [100.0], "High": [101.0], "Low": [99.0], "Close": [100.0], "Volume": [1000.0]},
        index=pd.to_datetime(["2026-05-01"]),
    )

    report = _quality_report(monkeypatch, tmp_path, frame, _quality_meta(validation_alerts=["MSFT: 1 barras invalidas"]))

    assert report["anomalies"] == [
        {
            "symbol": "MSFT",
            "date": "unavailable",
            "invalid_fields": [],
            "invalidity_class": "unavailable",
            "severity": "informativa",
            "provider": "fmp",
            "cache": {"cache_hit": True, "cache_key": "stable-cache-key", "cache_age_seconds": 12.0},
            "affects_operational_scan": "unavailable",
        }
    ]


def test_weekly_trading_review_aggregates_gates(monkeypatch, tmp_path):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.upsert_learning_observation(
        {
            "observation_id": "obs_1",
            "signal_date": "2026-05-10",
            "symbol": "AAPL",
            "source_family": "technical",
            "source_run_ids": ["run_1"],
            "decision": "candidate",
            "explanation": "test",
            "approved_buy": True,
            "blocked_entry_quality": False,
            "blocked_backtest": False,
            "executed_buy": True,
            "duplicate_count": 0,
            "rank_path": [],
            "features": {},
            "gate": {},
            "outcome": {"return_5d": 0.04},
            "execution": {},
        }
    )
    store.upsert_learning_observation(
        {
            "observation_id": "obs_2",
            "signal_date": "2026-05-11",
            "symbol": "MSFT",
            "source_family": "technical",
            "source_run_ids": ["run_2"],
            "decision": "blocked_entry_quality",
            "explanation": "test",
            "approved_buy": False,
            "blocked_entry_quality": True,
            "blocked_backtest": False,
            "executed_buy": False,
            "duplicate_count": 0,
            "rank_path": [],
            "features": {},
            "gate": {},
            "outcome": {"return_5d": 0.03},
            "execution": {},
        }
    )
    store.save_signal_outcome(
        signal_id="sig_1",
        source_run_id="run_1",
        source="technical",
        symbol="AAPL",
        signal_date="2026-05-10",
        decision="approved_buy",
        features={},
        gate={},
        outcome={"verdict": "win", "return_5d": 0.04},
    )

    monkeypatch.setattr(
        "agente_bolsa.tools.ops_reports.build_trade_history",
        lambda *args, **kwargs: {
            "current_statistics": {"total_pl": 100.0, "total_plpc_on_equity": 0.01},
            "days": [{"date": "2026-05-10", "realized_pl": 50.0, "open_unrealized_pl": 10.0}],
        },
    )
    monkeypatch.setattr(
        "agente_bolsa.tools.ops_reports.download_daily_prices_with_metadata",
        lambda *args, **kwargs: (
            pd.DataFrame({"Close": [100.0, 102.0]}, index=pd.date_range("2026-05-10", periods=2, freq="D")),
            {"source": "fmp"},
        ),
    )

    report = build_weekly_trading_review(
        settings,
        store,
        tmp_path / "reports",
        "weekly_test",
        since_date="2026-05-01",
        end_date="2026-05-15",
    )

    assert report["summary"]["approved_buy"] == 1
    assert report["summary"]["blocked_entry_quality"] == 1
    assert report["summary"]["positive_blocked"] == 1
    assert report["benchmark"]["available"] is True


def test_backup_database_copies_sqlite(tmp_path):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()

    report = backup_database(settings, tmp_path / "reports", "backup_test")

    backup_path = report["summary"]["backup_path"]
    assert backup_path
    assert json.loads((tmp_path / "reports" / "latest_database_backup.json").read_text(encoding="utf-8"))["summary"]["backup_path"] == backup_path


def test_selection_bandwidth_review_reports_shadow_additions(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    candidate_strong = {
        "symbol": "CSCO",
        "direction": "long",
        "score": 17,
        "setup_quality": "strong",
        "relative_return_20d": 0.06,
        "last_date": "2026-05-27",
        "technical_state": {
            "close": 110.0,
            "sma_20": 100.0,
            "return_20d": 0.09,
            "rsi_14": 71.0,
            "volume_zscore_20": 2.1,
            "chart_patterns": [
                {"bias": "bullish", "status": "confirmed", "label": "flag"},
                {"bias": "bullish", "status": "confirmed", "label": "triangle"},
            ],
        },
        "risk_plan": {"entry_price": 110.0, "stop_loss": 104.0, "take_profit": 124.0},
    }
    candidate_weaker = {
        "symbol": "WELL",
        "direction": "long",
        "score": 16,
        "setup_quality": "strong",
        "relative_return_20d": 0.01,
        "last_date": "2026-05-27",
        "technical_state": {
            "close": 101.0,
            "sma_20": 98.0,
            "return_20d": 0.05,
            "rsi_14": 63.0,
            "volume_zscore_20": -1.2,
            "chart_patterns": [],
        },
        "risk_plan": {"entry_price": 101.0, "stop_loss": 96.0, "take_profit": 112.0},
    }
    (reports_dir / "latest_closed_market_technical_study.json").write_text(
        json.dumps(
            {
                "run_id": "scan-latest",
                "as_of": "2026-05-27T20:00:00Z",
                "symbols_scanned": 2,
                "symbols_with_data": 2,
                "all_candidates": [candidate_strong, candidate_weaker],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("agente_bolsa.tools.ops_reports.load_daily_learning_context", lambda *_args, **_kwargs: {})

    report = build_selection_bandwidth_review(settings, reports_dir, "bandwidth_test", base_limit=1, shadow_limit=2)

    assert report["summary"]["base_selected"] == 1
    assert report["summary"]["shadow_selected"] == 2
    assert report["summary"]["additional_candidates_if_promoted"] == 1
    assert report["base_selected_symbols"] == ["CSCO"]
    assert report["additional_shadow_candidates"][0]["symbol"] == "WELL"
