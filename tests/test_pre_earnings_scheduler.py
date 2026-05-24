from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agente_bolsa.config import Settings
from agente_bolsa.scheduler import pre_earnings_job, scheduler_status


@dataclass
class FakeStatus:
    is_open: bool = True
    now_utc: str = "2026-05-01T19:30:00+00:00"
    now_market: str = "2026-05-01T15:30:00-04:00"
    market_close: str = "2026-05-01T22:00:00+02:00"
    next_close: str = "2026-05-01T22:00:00+02:00"
    session_date: str = "2026-05-01"

    def as_dict(self):
        return {
            "is_open": self.is_open,
            "now_utc": self.now_utc,
            "now_market": self.now_market,
            "market_close": self.market_close,
            "next_close": self.next_close,
            "session_date": self.session_date,
        }


class FakeCalendar:
    status_value = FakeStatus()

    def __init__(self, *_args, **_kwargs):
        pass

    def status(self):
        return self.status_value


class FakeReporter:
    def __init__(self):
        self.events = []

    def emit(self, agent, event_type, cycle_id, message, payload=None):
        self.events.append(
            {
                "agent": agent,
                "event_type": event_type,
                "cycle_id": cycle_id,
                "message": message,
                "payload": payload or {},
            }
        )


class FakeStore:
    def __init__(self):
        self.state = {}

    def get_runtime_value(self, key):
        return self.state.get(key)

    def set_runtime_value(self, key, value):
        self.state[key] = value


def test_scheduler_status_includes_pre_earnings_job():
    settings = Settings()

    status = scheduler_status(settings)

    assert any(job["id"] == "pre_earnings_daily" for job in status["jobs"])


def test_pre_earnings_job_runs_once_per_session(monkeypatch, tmp_path: Path):
    calls = []
    reporter = FakeReporter()

    def fake_report(**kwargs):
        calls.append(kwargs)
        return {
            "path": str(tmp_path / "pre_earnings_test.json"),
            "session_date": "2026-05-01",
            "session_count": 5,
            "operation_allowed": False,
            "summary": {
                "total_events": 1,
                "pending_count": 1,
                "success_rate": None,
            },
        }

    monkeypatch.setattr("agente_bolsa.scheduler.MarketCalendar", FakeCalendar)
    monkeypatch.setattr("agente_bolsa.scheduler._reporter", lambda *_args, **_kwargs: reporter)
    monkeypatch.setattr("agente_bolsa.scheduler.resolve_study_universe", lambda *_args, **_kwargs: ["AAPL"])
    monkeypatch.setattr("agente_bolsa.scheduler.build_pre_earnings_report", fake_report)
    monkeypatch.setattr("agente_bolsa.scheduler.update_pre_earnings_outcomes", lambda *_args, **_kwargs: {"updated": 0})
    monkeypatch.setattr("agente_bolsa.scheduler.record_pre_earnings_predictions", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        "agente_bolsa.scheduler.backfill_pending_pre_earnings_estimates",
        lambda *_args, **_kwargs: {"updated_predictions": 2, "path": str(tmp_path / "preearn_backfill.json")},
    )
    monkeypatch.setattr(
        "agente_bolsa.scheduler.build_pre_earnings_learning_digest",
        lambda *_args, **_kwargs: {"path": str(tmp_path / "preearn_digest.json")},
    )
    monkeypatch.setattr("agente_bolsa.scheduler.build_learning_digest_report", lambda *_args, **_kwargs: {"ok": True})

    settings = Settings(
        DATA_DIR=tmp_path,
        PRE_EARNINGS_TIME_MARKET="15:00",
        PRE_EARNINGS_DAYS=5,
        PRE_EARNINGS_UNIVERSE="AAPL",
        PRE_EARNINGS_MAX_SYMBOLS=1,
    )
    store = FakeStore()

    first = pre_earnings_job(settings, store, verbose=False)
    second = pre_earnings_job(settings, store, verbose=False)

    assert first is not None
    assert second is None
    assert len(calls) == 1
    assert calls[0]["session_count"] == 5
    assert calls[0]["symbols"] == ["AAPL"]
    assert first["estimates_backfill"]["updated_predictions"] == 2
    assert first["learning_digest"]["path"].endswith("preearn_digest.json")
    assert reporter.events[-1]["event_type"] == "pre_earnings_completed"


def test_pre_earnings_job_waits_until_one_hour_before_close(monkeypatch, tmp_path: Path):
    calls = []
    reporter = FakeReporter()

    def fake_report(**kwargs):
        calls.append(kwargs)
        return {
            "path": str(tmp_path / "pre_earnings_test.json"),
            "session_date": "2026-05-01",
            "session_count": 5,
            "operation_allowed": False,
            "summary": {"total_events": 1, "pending_count": 1, "success_rate": None},
        }

    monkeypatch.setattr("agente_bolsa.scheduler.MarketCalendar", FakeCalendar)
    monkeypatch.setattr("agente_bolsa.scheduler._reporter", lambda *_args, **_kwargs: reporter)
    monkeypatch.setattr("agente_bolsa.scheduler.resolve_study_universe", lambda *_args, **_kwargs: ["AAPL"])
    monkeypatch.setattr("agente_bolsa.scheduler.build_pre_earnings_report", fake_report)
    monkeypatch.setattr("agente_bolsa.scheduler.update_pre_earnings_outcomes", lambda *_args, **_kwargs: {"updated": 0})
    monkeypatch.setattr("agente_bolsa.scheduler.record_pre_earnings_predictions", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        "agente_bolsa.scheduler.backfill_pending_pre_earnings_estimates",
        lambda *_args, **_kwargs: {"updated_predictions": 1, "path": str(tmp_path / "preearn_backfill.json")},
    )
    monkeypatch.setattr(
        "agente_bolsa.scheduler.build_pre_earnings_learning_digest",
        lambda *_args, **_kwargs: {"path": str(tmp_path / "preearn_digest.json")},
    )
    monkeypatch.setattr("agente_bolsa.scheduler.build_learning_digest_report", lambda *_args, **_kwargs: {"ok": True})

    settings = Settings(
        DATA_DIR=tmp_path,
        PRE_EARNINGS_BEFORE_CLOSE_MINUTES=60,
        PRE_EARNINGS_UNIVERSE="AAPL",
        PRE_EARNINGS_MAX_SYMBOLS=1,
    )
    store = FakeStore()

    FakeCalendar.status_value = FakeStatus(
        now_utc="2026-05-01T18:30:00+00:00",
        now_market="2026-05-01T14:30:00-04:00",
        market_close="2026-05-01T22:00:00+02:00",
        next_close="2026-05-01T22:00:00+02:00",
    )
    assert pre_earnings_job(settings, store, verbose=False) is None

    FakeCalendar.status_value = FakeStatus(
        now_utc="2026-05-01T19:00:00+00:00",
        now_market="2026-05-01T15:00:00-04:00",
        market_close="2026-05-01T22:00:00+02:00",
        next_close="2026-05-01T22:00:00+02:00",
    )
    assert pre_earnings_job(settings, store, verbose=False) is not None
    assert len(calls) == 1
