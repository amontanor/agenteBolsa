"""P-L186K: regresiones P0 2026-11-03 (gate merge, PMR, calendario)."""

from __future__ import annotations

import inspect
import sqlite3
from pathlib import Path

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.market_calendar import MarketCalendar
from agente_bolsa.scheduler import _build_post_market_review_with_lock_retry
from agente_bolsa.storage import Store
from agente_bolsa.tools import operational_learning, post_market_review


def _settings(tmp_path: Path) -> Settings:
    return Settings(DATA_DIR=tmp_path, _env_file=None)


def _store(tmp_path: Path) -> Store:
    store = Store(_settings(tmp_path).database_path, _settings(tmp_path).agent_logs_dir)
    store.ensure_schema()
    return store


def _save_signal(store: Store, *, gate: dict) -> None:
    store.save_signal_outcome(
        signal_id="sig-p0-1",
        source_run_id="run-p0",
        source="learning_experiment",
        symbol="APP",
        signal_date="2026-11-02",
        decision="candidate",
        features={"direction": "short"},
        gate=gate,
        outcome={},
    )


def _signal_gate(store: Store) -> dict:
    with store.connect() as conn:
        row = conn.execute(
            "SELECT gate_json FROM signal_outcomes WHERE signal_id = ?",
            ("sig-p0-1",),
        ).fetchone()
    import json

    return json.loads(row["gate_json"] or "{}")


def test_signal_gate_merge_preserves_execution(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _save_signal(
        store,
        gate={"executed_short": True, "broker_order_id": "bo-1", "direction": "short"},
    )
    _save_signal(store, gate={})
    gate = _signal_gate(store)
    assert gate["executed_short"] is True
    assert gate["broker_order_id"] == "bo-1"
    assert gate["direction"] == "short"


def test_signal_gate_merge_respects_explicit_false(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _save_signal(store, gate={"executed_short": True, "broker_order_id": "bo-1"})
    _save_signal(store, gate={"executed_short": False})
    assert _signal_gate(store)["executed_short"] is False
    assert _signal_gate(store)["broker_order_id"] == "bo-1"


def test_signal_gate_merge_bulk_preserves_execution(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _save_signal(store, gate={"executed_short": True, "broker_order_id": "bo-1"})
    store.save_signal_outcomes_bulk(
        [
            {
                "signal_id": "sig-p0-1",
                "source_run_id": "run-p0",
                "source": "learning_experiment",
                "symbol": "APP",
                "signal_date": "2026-11-02",
                "decision": "candidate",
                "features": {"direction": "short"},
                "gate": {},
                "outcome": {},
            }
        ]
    )
    gate = _signal_gate(store)
    assert gate["executed_short"] is True
    assert gate["broker_order_id"] == "bo-1"


class _BrokenSchedule:
    def __init__(self) -> None:
        self.calls = 0

    def schedule(self, **_kwargs):
        self.calls += 1
        raise AttributeError("'XNYS' object has no attribute '_holidays'")


class _GoodSchedule:
    def schedule(self, **_kwargs):
        return "schedule-ok"


def test_calendar_rebuilds_once_after_broken_instance(monkeypatch) -> None:
    calendar = MarketCalendar()
    broken = _BrokenSchedule()
    calendar._calendar = broken
    monkeypatch.setattr(
        MarketCalendar,
        "_load_calendar",
        staticmethod(lambda _name: _GoodSchedule()),
    )
    assert calendar._safe_schedule("2026-11-02", "2026-11-03") == "schedule-ok"
    assert broken.calls == 1


def test_calendar_fallback_never_raises(monkeypatch) -> None:
    calendar = MarketCalendar()
    calendar._calendar = _BrokenSchedule()
    monkeypatch.setattr(
        MarketCalendar,
        "_load_calendar",
        staticmethod(lambda _name: _BrokenSchedule()),
    )
    assert calendar._safe_schedule("2026-11-02", "2026-11-03") is None
    status = calendar.status()
    assert status.is_open in {True, False}
    assert status.calendar.endswith("-fallback")


def test_pmr_retries_lock_then_completes(monkeypatch, tmp_path: Path) -> None:
    calls = {"n": 0}

    def fake_build(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise sqlite3.OperationalError("database is locked")
        return {"ok": True}

    monkeypatch.setattr("agente_bolsa.scheduler.build_post_market_review", fake_build)
    monkeypatch.setattr("agente_bolsa.scheduler.time.sleep", lambda _seconds: None)
    result = _build_post_market_review_with_lock_retry(
        _settings(tmp_path),
        tmp_path / "reports",
        "pmr-test",
        session_date="2026-11-02",
        use_llm=False,
        portfolio_snapshot=None,
        broker_client=None,
        stage_recorder=lambda *_args, **_kwargs: None,
    )
    assert result == {"ok": True}
    assert calls["n"] == 3


def test_pmr_non_lock_error_is_not_retried(monkeypatch, tmp_path: Path) -> None:
    calls = {"n": 0}

    def fake_build(*_args, **_kwargs):
        calls["n"] += 1
        raise sqlite3.OperationalError("no such table")

    monkeypatch.setattr("agente_bolsa.scheduler.build_post_market_review", fake_build)
    with pytest.raises(sqlite3.OperationalError):
        _build_post_market_review_with_lock_retry(
            _settings(tmp_path),
            tmp_path / "reports",
            "pmr-test",
            session_date="2026-11-02",
            use_llm=False,
            portfolio_snapshot=None,
            broker_client=None,
            stage_recorder=lambda *_args, **_kwargs: None,
        )
    assert calls["n"] == 1


def test_pmr_build_path_does_not_call_ensure_schema() -> None:
    source = inspect.getsource(post_market_review.build_post_market_review)
    assert "if not settings.database_path.exists()" in source
    assert source.count("ensure_schema") == 1
    assert "ensure_schema" not in inspect.getsource(
        operational_learning.build_operational_learning_review
    )
