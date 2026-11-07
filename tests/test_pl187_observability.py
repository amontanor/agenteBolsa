"""P-L187: observabilidad operativa (guard de reloj, skips, timing, mensajes)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


# ---------------- clock guard ----------------

def test_require_sane_clock_returns_with_valid_clock():
    from agente_bolsa._utils import require_sane_clock

    require_sane_clock(wait_seconds=1.0, _now=lambda: datetime(2026, 11, 7, tzinfo=timezone.utc))


def test_require_sane_clock_aborts_with_1970_clock():
    from agente_bolsa._utils import require_sane_clock

    ticks = iter([0.0, 0.0, 5.0, 10.0, 20.0])
    with pytest.raises(SystemExit) as excinfo:
        require_sane_clock(
            wait_seconds=1.0,
            _now=lambda: datetime(1970, 1, 1, tzinfo=timezone.utc),
            _monotonic=lambda: next(ticks),
            _sleep=lambda _seconds: None,
        )
    assert "reloj" in str(excinfo.value)


# ---------------- throttle de skips ----------------

def test_scheduler_skip_throttle_writes_once_per_window(tmp_path, monkeypatch):
    from agente_bolsa.config import Settings
    from agente_bolsa import scheduler

    writes: list[str] = []

    class FakeStore:
        def record_append_only_event(self, *, event_id, event_type, cycle_id, payload, **kwargs):
            writes.append(event_id)
            return {"status": "inserted"}

    settings = Settings(DATA_DIR=tmp_path)
    settings.ensure_runtime_dirs()
    event = SimpleNamespace(
        code=scheduler.EVENT_JOB_MAX_INSTANCES,
        job_id="portfolio_watch_1m",
        scheduled_run_times=[datetime(2026, 11, 7, 9, 0, tzinfo=timezone.utc)],
    )
    scheduler._reset_control_event_throttle()
    scheduler._persist_scheduler_control_event(settings, FakeStore(), event)
    scheduler._persist_scheduler_control_event(settings, FakeStore(), event)
    assert len(writes) == 1

    scheduler._reset_control_event_throttle()
    scheduler._persist_scheduler_control_event(settings, FakeStore(), event)
    assert len(writes) == 2


# ---------------- timing por pagina ----------------

def test_page_timing_emits_line_for_non_dashboard(capsys):
    from agente_bolsa.web_app import _emit_page_timing

    _emit_page_timing("page_portfolio", time.monotonic() - 0.01)
    out = capsys.readouterr().out
    assert "page_timing" in out
    assert "page_portfolio" in out


def test_page_timing_is_silent_for_dashboard(capsys):
    from agente_bolsa.web_app import _emit_page_timing

    _emit_page_timing("page_dashboard", time.monotonic() - 0.01)
    assert capsys.readouterr().out == ""


# ---------------- mensajes de error completos ----------------

def test_dashboard_loading_logs_exception_message():
    import inspect

    from agente_bolsa import dashboard_loading

    source = inspect.getsource(dashboard_loading)
    assert 'dashboard_fills_sync_failed error=%s: %s' in source
    assert 'dashboard_snapshot_attempt_failed error=%s: %s' in source
