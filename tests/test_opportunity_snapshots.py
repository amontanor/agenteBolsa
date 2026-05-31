import argparse

from agente_bolsa.config import Settings
from agente_bolsa.main import build_parser, command_opportunity_snapshot
from agente_bolsa.models import PortfolioSnapshot
from agente_bolsa.scheduler import opportunity_snapshot_job, scheduler_status
from agente_bolsa.storage import Store
from agente_bolsa.tools.broker import BrokerClientFactory
from agente_bolsa.tools.opportunities import (
    build_opportunity_snapshot,
    opportunity_assessment,
    opportunity_entry_risk,
    parse_opportunity_snapshot_times,
)


def _portfolio_snapshot():
    return PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=10000.0,
        portfolio_value=20000.0,
        buying_power=10000.0,
        positions=[],
        open_orders=[],
    )


def _candidate(symbol: str, **overrides):
    candidate = {
        "symbol": symbol,
        "direction": "long",
        "score": 15.0,
        "selection_score": 0.055,
        "rank_priority_score": 0.03,
        "selection_rank": 1,
        "setup_name": "orderly_breakout",
        "setup_quality": "strong",
        "reasons": ["momentum 20d positivo"],
        "technical_state": {
            "close": 105.0,
            "return_5d": 0.04,
            "return_20d": 0.12,
            "return_60d": 0.18,
            "sma_20": 100.0,
            "sma_50": 95.0,
            "sma_200": 80.0,
            "rsi_14": 64.0,
            "atr_14": 3.5,
            "volume_zscore_20": 1.6,
            "chart_patterns": [],
            "candle_patterns": [],
            "breakout_failure_risk": False,
        },
        "risk_plan": {
            "entry_price": 105.0,
            "stop_loss": 99.0,
            "take_profit": 117.0,
            "reward_risk": 2.0,
            "invalidation": "Pierde soporte.",
            "time_stop": "5-10 sesiones",
        },
    }
    candidate.update(overrides)
    return candidate


def test_parse_opportunity_snapshot_times_normalizes_values():
    assert parse_opportunity_snapshot_times("16:00, 19:0,21:00,16:00") == ["16:00", "19:00", "21:00"]


def test_store_opportunity_snapshots_replace_same_date_slot(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()

    store.upsert_opportunity_snapshot(
        snapshot_id="snap_1",
        session_date="2026-05-28",
        slot_time="16:00",
        run_id="run_1",
        report_path="report_1.json",
        opportunities=[{"symbol": "AAPL"}],
        summary={"best_puntuacion": 0.05},
    )
    store.upsert_opportunity_snapshot(
        snapshot_id="snap_2",
        session_date="2026-05-28",
        slot_time="16:00",
        run_id="run_2",
        report_path="report_2.json",
        opportunities=[{"symbol": "MSFT"}],
        summary={"best_puntuacion": 0.08},
    )

    rows = store.opportunity_snapshots(limit=10)

    assert len(rows) == 1
    assert rows[0]["snapshot_id"] == "snap_2"
    assert rows[0]["run_id"] == "run_2"
    assert rows[0]["opportunities"][0]["symbol"] == "MSFT"


def test_store_opportunity_snapshots_order_latest_first(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.upsert_opportunity_snapshot(
        snapshot_id="snap_1",
        session_date="2026-05-27",
        slot_time="21:00",
        run_id="run_1",
        report_path="report_1.json",
        opportunities=[],
        summary={},
    )
    store.upsert_opportunity_snapshot(
        snapshot_id="snap_2",
        session_date="2026-05-28",
        slot_time="16:00",
        run_id="run_2",
        report_path="report_2.json",
        opportunities=[],
        summary={},
    )

    rows = store.opportunity_snapshots(limit=10)

    assert [item["snapshot_id"] for item in rows] == ["snap_2", "snap_1"]


def test_build_opportunity_snapshot_preserves_ranking_and_scores(tmp_path, monkeypatch):
    settings = Settings(DATA_DIR=tmp_path, AUTO_PAPER_TRADING=True, REQUIRE_HUMAN_APPROVAL=False)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    monkeypatch.setattr(BrokerClientFactory, "alpaca_portfolio_snapshot", lambda self: _portfolio_snapshot())
    technical_context = {
        "path": "report.json",
        "run_id": "scan_1",
        "as_of": "2026-05-28T16:00:00+02:00",
        "selected_candidates": [_candidate("AAPL"), _candidate("MSFT", selection_rank=2, selection_score=0.041)],
        "top_longs": [],
        "all_candidates": [_candidate("AAPL"), _candidate("MSFT", selection_rank=2, selection_score=0.041)],
        "selection_metadata": {"method": "selection_score_with_shrunk_learning_prior"},
    }

    snapshot = build_opportunity_snapshot(
        settings,
        store,
        technical_context,
        slot_time="16:00",
        limit=20,
    )

    assert snapshot["session_date"]
    assert snapshot["slot_time"] == "16:00"
    assert snapshot["report_path"] == "report.json"
    assert snapshot["opportunities"][0]["ranking"] == 1
    assert snapshot["opportunities"][0]["puntuacion"] == 0.055
    assert snapshot["opportunities"][0]["summary_row"]["puntuacion"] == 0.055
    assert snapshot["opportunities"][0]["assessment"]["label"] == "Oportunidad razonable"
    assert snapshot["opportunities"][0]["summary_row"]["oportunidad"] == "Oportunidad razonable"


def test_opportunity_assessment_marks_strong_candidate_as_good():
    assessment = opportunity_assessment(
        _candidate("NVDA", score=18.0, selection_score=0.08, risk_plan={"entry_price": 105.0, "stop_loss": 99.0, "take_profit": 117.0, "reward_risk": 2.0})
    )

    assert assessment["label"] == "Buena oportunidad"
    assert assessment["tone"] == "good"


def test_opportunity_assessment_marks_weak_candidate_as_not_worth_it():
    assessment = opportunity_assessment(
        _candidate(
            "IBM",
            score=11.0,
            selection_score=-0.12,
            setup_quality="weak",
            technical_state={"close": 105.0, "breakout_failure_risk": True},
            risk_plan={"entry_price": 105.0, "stop_loss": 101.0, "take_profit": 109.0, "reward_risk": 1.0},
        )
    )

    assert assessment["label"] == "No compensa ahora"
    assert assessment["tone"] == "bad"


def test_opportunity_assessment_waits_when_candidate_is_chased():
    candidate = _candidate(
        "FSLR",
        score=18.0,
        selection_score=-0.0192,
        technical_state={
            "close": 292.495,
            "return_5d": 0.2297,
            "return_20d": 0.5345,
            "rsi_14": 82.97,
            "volume_zscore_20": -2.24,
            "close_position_in_range": 1.0,
            "breakout_failure_risk": False,
        },
    )

    entry_risk = opportunity_entry_risk(candidate)
    assessment = opportunity_assessment(candidate)

    assert entry_risk["label"] == "Entrada perseguida"
    assert assessment["label"] == "Esperar pullback"
    assert "demasiado estirado" in assessment["summary"]


def test_opportunity_snapshot_job_saves_snapshot(tmp_path, monkeypatch):
    settings = Settings(DATA_DIR=tmp_path, OPPORTUNITY_SNAPSHOT_TIMES_LOCAL="16:00,19:00,21:00")
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    monkeypatch.setattr("agente_bolsa.scheduler.resolve_study_universe", lambda *args, **kwargs: ["AAPL"])
    monkeypatch.setattr(
        "agente_bolsa.scheduler.build_closed_market_technical_study",
        lambda *args, **kwargs: {
            "path": "report.json",
            "run_id": "scan_1",
            "as_of": "2026-05-28T16:00:00+02:00",
            "selected_candidates": [_candidate("AAPL")],
            "top_longs": [_candidate("AAPL")],
            "top_shorts": [],
            "all_candidates": [_candidate("AAPL")],
            "analysis_plan_counts": {},
            "tool_requests": [],
            "warnings": [],
            "symbols_scanned": 1,
            "symbols_with_data": 1,
        },
    )
    monkeypatch.setattr("agente_bolsa.scheduler.record_signal_candidates", lambda *args, **kwargs: 1)
    monkeypatch.setattr(BrokerClientFactory, "alpaca_portfolio_snapshot", lambda self: _portfolio_snapshot())

    snapshot = opportunity_snapshot_job(settings, store, slot_time="16:00", verbose=False, force=True)

    assert snapshot["slot_time"] == "16:00"
    latest = store.latest_opportunity_snapshot()
    assert latest is not None
    assert latest["slot_time"] == "16:00"
    assert latest["report_path"] == "report.json"


def test_scheduler_status_lists_opportunity_snapshot_jobs(tmp_path):
    settings = Settings(DATA_DIR=tmp_path, OPPORTUNITY_SNAPSHOT_TIMES_LOCAL="16:00,19:00,21:00")
    status = scheduler_status(settings)

    job_ids = {item["id"] for item in status["jobs"]}

    assert "opportunity_snapshot_1600" in job_ids
    assert "opportunity_snapshot_1900" in job_ids
    assert "opportunity_snapshot_2100" in job_ids


def test_build_parser_supports_opportunity_snapshot_command():
    parser = build_parser()
    args = parser.parse_args(["opportunity-snapshot", "--slot", "16:00"])

    assert args.slot == "16:00"
    assert args.func == command_opportunity_snapshot


def test_command_opportunity_snapshot_calls_scheduler_job(tmp_path, monkeypatch, capsys):
    settings = Settings(DATA_DIR=tmp_path)
    monkeypatch.setattr("agente_bolsa.main.get_settings", lambda: settings)
    monkeypatch.setattr("agente_bolsa.main.configure_logging", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "agente_bolsa.main.opportunity_snapshot_job",
        lambda settings, store, slot_time, verbose, force: {
            "session_date": "2026-05-28",
            "slot_time": slot_time,
            "run_id": "opp_1",
            "report_path": "report.json",
            "summary": {"best_puntuacion": 0.055},
        },
    )

    command_opportunity_snapshot(argparse.Namespace(slot="16:00", quiet=True, force=False))
    output = capsys.readouterr().out

    assert "opp_1" in output
    assert "16:00" in output
