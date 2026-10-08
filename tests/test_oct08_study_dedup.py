import gc
import weakref
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agente_bolsa import scheduler
from agente_bolsa.config import Settings
from agente_bolsa.storage import Store


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    settings = Settings(_env_file=None, data_dir=tmp_path)
    store = Store(tmp_path / "state.sqlite3", tmp_path / "agents")
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 7, 22, tzinfo=timezone.utc)
    monkeypatch.setattr(scheduler, "datetime", Clock)
    return settings, store


@pytest.mark.parametrize("job_name", ["daily_study_job", "closed_market_technical_study_job"])
@pytest.mark.parametrize("diagnostic_failure", [False, True])
def test_real_job_duplicate_returns_without_entering_body(context, monkeypatch, job_name, diagnostic_failure):
    from threading import Event
    settings, store = context
    entered, release = Event(), Event()
    calls = []
    def calendar(*args):
        calls.append(args)
        entered.set()
        assert release.wait(3)
        raise ValueError("calendar sentinel")
    monkeypatch.setattr(scheduler, "MarketCalendar", calendar)
    events = []
    active_runtime = {"status": "running", "run_id": "accepted-run"}
    monkeypatch.setattr(scheduler, "_set_job_status", lambda *args, **kwargs: active_runtime.update(kwargs))
    def diagnostic(*args):
        if diagnostic_failure:
            raise OSError("diagnostic unavailable")
        events.append(args)
    monkeypatch.setattr(scheduler, "log_system_event", diagnostic)
    job = getattr(scheduler, job_name)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(job, settings, store, use_crew=False)
        try:
            assert entered.wait(3)
            second = executor.submit(job, settings, store, use_crew=False, force=True)
            assert second.result(timeout=1) is None
            assert len(calls) == 1
            assert active_runtime == {"status": "running", "run_id": "accepted-run"}
            if diagnostic_failure:
                assert events == []
            else:
                assert events[0][1] == "study_job_concurrent_skipped"
                assert events[0][2] == {"job_name": job_name, "reason": "same_store_job_running"}
            assert not store.database_path.exists()
        finally:
            release.set()
        with pytest.raises(ValueError, match="calendar sentinel"):
            first.result(timeout=3)
    # A failed accepted run releases the guard.
    with pytest.raises(ValueError, match="calendar sentinel"):
        job(settings, store, use_crew=False)
    assert len(calls) == 2


@pytest.mark.parametrize("failure", [ValueError, KeyboardInterrupt])
def test_guard_passes_result_arguments_errors_and_releases(context, failure):
    settings, store = context
    marker = object()
    calls = []
    @scheduler._single_study_job
    def job(settings, store, *, value, fail=False):
        calls.append((settings, store, value, fail))
        if fail:
            raise failure("sentinel")
        return marker
    with pytest.raises(failure, match="sentinel"):
        job(settings, store, value=marker, fail=True)
    assert job(settings=settings, store=store, value=marker) is marker
    assert calls == [(settings, store, marker, True), (settings, store, marker, False)]


def test_distinct_jobs_and_stores_are_independent(context):
    from threading import Event
    settings, store = context
    other_store = Store(settings.data_dir / "other.sqlite3", settings.data_dir / "other")
    entered, release = Event(), Event()
    @scheduler._single_study_job
    def first(settings, store, *, block=False):
        if block:
            entered.set()
            assert release.wait(3)
        return "first"
    @scheduler._single_study_job
    def second(settings, store):
        return "second"
    with ThreadPoolExecutor(max_workers=2) as executor:
        future = executor.submit(first, settings, store, block=True)
        try:
            assert entered.wait(3)
            assert second(settings, store) == "second"
            assert first(settings, other_store) == "first"
        finally:
            release.set()
        assert future.result(timeout=3) == "first"
    reference = weakref.ref(other_store)
    del other_store
    gc.collect()
    assert reference() is None


def test_failed_diagnostic_cannot_enter_or_release_active_guard(context, monkeypatch):
    from threading import Event
    settings, store = context
    entered, release = Event(), Event()
    count = []
    def broken(*args):
        raise OSError("log unavailable")
    monkeypatch.setattr(scheduler, "log_system_event", broken)
    @scheduler._single_study_job
    def job(settings, store, *, block=False):
        count.append(1)
        if block:
            entered.set()
            assert release.wait(3)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(job, settings, store, block=True)
        try:
            assert entered.wait(3)
            assert executor.submit(job, settings, store).result(timeout=1) is None
            assert executor.submit(job, settings, store).result(timeout=1) is None
            assert len(count) == 1
        finally:
            release.set()
        first.result(timeout=3)
    job(settings, store)
    assert len(count) == 2


@pytest.mark.parametrize("job_name", ["daily_study_job", "closed_market_technical_study_job"])
@pytest.mark.parametrize("force", [False, True])
def test_real_job_accepted_trace_matches_original(context, monkeypatch, job_name, force):
    settings, store = context
    trace = []
    status = SimpleNamespace(is_open=True, now_market="2026-10-07T22:00:00+00:00")
    status.as_dict = lambda: {"is_open": True}
    calendar = SimpleNamespace(status=lambda: status, should_run_daily_study=lambda: (True, status))
    monkeypatch.setattr(scheduler, "MarketCalendar", lambda *args: calendar)
    monkeypatch.setattr(scheduler, "new_id", lambda prefix: prefix)
    monkeypatch.setattr(scheduler, "_set_job_status", lambda *args, **kwargs: trace.append(("status", args[1:], kwargs)))
    monkeypatch.setattr(scheduler, "_reporter", lambda *args: SimpleNamespace(emit=lambda *args: trace.append(("emit", args))))
    monkeypatch.setattr(store, "get_runtime_value", lambda key: trace.append(("get", key)))
    monkeypatch.setattr(store, "set_runtime_value", lambda *args: trace.append(("set", args)))
    monkeypatch.setattr(scheduler, "run_observable_cycle", lambda *args, **kwargs: trace.append(("cycle", kwargs)))
    job = getattr(scheduler, job_name)
    assert job(settings, store, use_crew=False, verbose=False, force=force) is None
    guarded_trace = trace.copy()
    trace.clear()
    assert job.__wrapped__(settings, store, use_crew=False, verbose=False, force=force) is None
    assert trace == guarded_trace


def test_closed_market_completed_trace_matches_original(context, monkeypatch):
    from copy import deepcopy
    settings, store = context
    trace = []
    status = SimpleNamespace(is_open=False, next_open="2026-10-08T13:30:00Z", now_market="2026-10-07T22:00:00Z")
    status.as_dict = lambda: {"is_open": False}
    monkeypatch.setattr(scheduler, "MarketCalendar", lambda *args: SimpleNamespace(status=lambda: status))
    monkeypatch.setattr(scheduler, "new_id", lambda prefix: prefix)
    monkeypatch.setattr(store, "get_runtime_value", lambda key: trace.append(("get", key)))
    monkeypatch.setattr(store, "set_runtime_value", lambda *args: trace.append(("set", args)))
    monkeypatch.setattr(scheduler, "_set_job_status", lambda *args, **kwargs: trace.append(("status", args[1:], kwargs)))
    monkeypatch.setattr(scheduler, "_reporter", lambda *args: SimpleNamespace(emit=lambda *args: trace.append(("emit", args))))
    monkeypatch.setattr(scheduler, "resolve_study_universe", lambda *args: ["ABC"])
    tracker = SimpleNamespace(
        producer_contract=lambda: {"contract": "synthetic"},
        fail=lambda **kwargs: trace.append(("fail", kwargs)),
        add_outputs=lambda **kwargs: trace.append(("outputs", kwargs)),
        succeed=lambda: trace.append(("succeed",)),
    )
    monkeypatch.setattr(scheduler, "AgentRunTracker", lambda *args, **kwargs: tracker)
    report = {"path": "synthetic.json", "symbols_scanned": 1, "symbols_with_data": 1,
              "top_longs": [], "top_shorts": [], "analysis_plan_counts": {}, "warnings": [], "tool_requests": []}
    monkeypatch.setattr(scheduler, "build_closed_market_technical_study", lambda *args, **kwargs: deepcopy(report))
    monkeypatch.setattr(scheduler, "prepare_signal_candidate_identities", lambda *args, **kwargs: {})
    monkeypatch.setattr(scheduler, "_selected_candidates", lambda *args: ([], []))
    monkeypatch.setattr(scheduler, "_prepare_learning_penalty_cycle_shadow", lambda *args: None)
    monkeypatch.setattr(scheduler, "record_signal_candidates", lambda *args, **kwargs: trace.append(("signals", deepcopy(args[1]), kwargs)) or 0)
    monkeypatch.setattr(scheduler, "write_json_report", lambda report, *args, **kwargs: trace.append(("report", deepcopy(report), kwargs)) or report)
    monkeypatch.setattr("agente_bolsa.tools.market_state.load_latest_market_state", lambda *args: None)
    job = scheduler.closed_market_technical_study_job
    job(settings, store, use_crew=False, verbose=False)
    guarded_trace = deepcopy(trace)
    trace.clear()
    job.__wrapped__(settings, store, use_crew=False, verbose=False)
    assert trace == guarded_trace
    assert trace[-1][2]["status"] == "completed"
    assert not store.database_path.exists()


@pytest.mark.parametrize("job_name", ["daily_study_job", "closed_market_technical_study_job"])
@pytest.mark.parametrize("failure", [ValueError, KeyboardInterrupt])
def test_real_jobs_release_after_calendar_baseexception(context, monkeypatch, job_name, failure):
    settings, store = context
    error = failure("accepted failure")
    calls = []
    def calendar(*args):
        calls.append(args)
        raise error
    monkeypatch.setattr(scheduler, "MarketCalendar", calendar)
    job = getattr(scheduler, job_name)
    for _ in range(2):
        with pytest.raises(failure) as caught:
            job(settings, store, use_crew=False)
        assert caught.value is error
    assert len(calls) == 2
