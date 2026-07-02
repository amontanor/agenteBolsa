import json

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.lab_book import (
    LabBookConfig,
    build_lab_book_signal_rows,
    run_lab_book_once,
    select_lab_book_candidates,
)


def _settings(tmp_path: object) -> Settings:
    return Settings(
        _env_file=None,
        DATA_DIR=tmp_path,
        DATABASE_PATH=tmp_path / "state" / "test.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "logs" / "agents",
        LOGS_DIR=tmp_path / "logs",
        ALLOW_LIVE_TRADING=False,
        TRADING_MODE="paper",
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )


def _store(settings: Settings) -> Store:
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def _candidate(symbol: str, *, score: float, close: float = 100.0) -> dict:
    return {
        "symbol": symbol,
        "direction": "long",
        "score": score,
        "setup_name": "pre_gate_breakout",
        "strategy_name": "builtin_breakout",
        "strategy_status": "ACTIVE",
        "last_date": "2026-07-01",
        "technical_state": {"close": close, "rsi_14": 55},
        "risk_plan": {"entry_price": close, "stop_loss": close * 0.95, "take_profit": close * 1.1},
    }


def test_lab_book_disabled_is_noop_and_does_not_build_report(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    config_path = tmp_path / "config" / "lab_book.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps({"enabled": False, "mode": "log_only"}), encoding="utf-8")

    def fail_builder() -> dict:
        raise AssertionError("lab book apagado no debe construir candidatos")

    result = run_lab_book_once(settings, store, config_path=config_path, report_builder=fail_builder)

    assert result["status"] == "disabled"
    assert result["recorded"] == 0
    assert result["orders_submitted"] == 0
    assert store.signal_outcomes() == []


def test_lab_book_records_fixed_size_capped_and_tagged_rows(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    config_path = tmp_path / "config" / "lab_book.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps({"enabled": True, "mode": "log_only", "fixed_notional": 200, "daily_cap": 2}),
        encoding="utf-8",
    )
    report = {
        "run_id": "lab-source-1",
        "all_candidates": [
            _candidate("MSFT", score=14, close=300),
            _candidate("AAPL", score=18, close=200),
            _candidate("NVDA", score=16, close=150),
        ],
    }

    result = run_lab_book_once(settings, store, config_path=config_path, report_builder=lambda: report)
    rows = store.signal_outcomes()

    assert result["status"] == "recorded"
    assert result["recorded"] == 2
    assert result["orders_submitted"] == 0
    ranked_symbols = [row["symbol"] for row in sorted(rows, key=lambda item: item["features"]["source_rank"])]
    assert ranked_symbols == ["AAPL", "NVDA"]
    assert {row["source"] for row in rows} == {"lab_book"}
    assert all(row["features"]["fixed_notional"] == 200 for row in rows)
    assert all(row["features"]["hypothetical_notional"] == 200 for row in rows)
    assert all(row["features"]["selected_for_llm"] is False for row in rows)
    assert all(row["gate"]["orders_disabled"] is True for row in rows)
    assert all(row["gate"]["affects_real_book"] is False for row in rows)


def test_lab_book_selection_uses_unique_symbols_and_ignores_shorts():
    report = {
        "run_id": "lab-source-2",
        "all_candidates": [
            _candidate("AAPL", score=10),
            {**_candidate("TSLA", score=99), "direction": "short"},
            _candidate("AAPL", score=20),
            _candidate("MSFT", score=15),
        ],
    }
    config = LabBookConfig(enabled=True, daily_cap=10)

    selected = select_lab_book_candidates(report, config=config)

    assert [item["symbol"] for item in selected] == ["AAPL", "MSFT"]


def test_lab_book_rows_are_separate_from_real_book():
    report = {"run_id": "lab-source-3", "all_candidates": [_candidate("AAPL", score=10)]}

    rows = build_lab_book_signal_rows(report, config=LabBookConfig(enabled=True, fixed_notional=200, daily_cap=10))

    assert rows[0]["source"] == "lab_book"
    assert rows[0]["decision"] == "candidate"
    assert rows[0]["gate"]["executed_buy"] is False
    assert rows[0]["gate"]["promotion_eligible_without_oos"] is False
    assert rows[0]["features"]["affects_real_book"] is False


def test_lab_book_rejects_non_log_only_mode(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    config_path = tmp_path / "config" / "lab_book.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps({"enabled": True, "mode": "paper_orders"}), encoding="utf-8")

    with pytest.raises(ValueError, match="mode='log_only'"):
        run_lab_book_once(settings, store, config_path=config_path, report_builder=lambda: {"run_id": "x"})
