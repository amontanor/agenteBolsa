"""Prospective EOD ordering; all data sources are local doubles."""
from types import SimpleNamespace

import pytest

from agente_bolsa import scheduler
from agente_bolsa.tools import spy_eod_authority


def test_existing_comparable_receipt_avoids_duplicate_refresh(monkeypatch, tmp_path):
    settings = SimpleNamespace(data_dir=tmp_path)
    monkeypatch.setattr(spy_eod_authority, "load_spy_eod_receipt", lambda *_: {
        "comparison_status": "comparable", "session_date": "2026-10-13"})
    def forbidden(*args, **kwargs):
        raise AssertionError("Existing authority must avoid another download")
    monkeypatch.setattr(spy_eod_authority, "refresh_and_capture_spy_eod", forbidden)
    result = scheduler._ensure_postmarket_spy_eod(settings, "2026-10-13")
    assert result["comparison_status"] == "comparable"
    assert result["source"] == "existing_receipt"


@pytest.mark.parametrize("existing", [None, {"comparison_status": "unavailable"}])
def test_missing_authority_refreshes_only_exact_session(monkeypatch, tmp_path, existing):
    calls = []
    monkeypatch.setattr(spy_eod_authority, "load_spy_eod_receipt", lambda *_: existing)
    def refresh(settings, session):
        calls.append((settings.data_dir, session))
        return {"persisted": True, "receipt": {"comparison_status": "comparable"}}
    monkeypatch.setattr(spy_eod_authority, "refresh_and_capture_spy_eod", refresh)
    result = scheduler._ensure_postmarket_spy_eod(SimpleNamespace(data_dir=tmp_path), "2026-10-13")
    assert calls == [(tmp_path, "2026-10-13")]
    assert result["comparison_status"] == "comparable"


def test_refresh_failure_stays_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(spy_eod_authority, "load_spy_eod_receipt", lambda *_: None)
    def fail(*args):
        raise RuntimeError("local provider failure")
    monkeypatch.setattr(spy_eod_authority, "refresh_and_capture_spy_eod", fail)
    result = scheduler._ensure_postmarket_spy_eod(SimpleNamespace(data_dir=tmp_path), "2026-10-13")
    assert result["persisted"] is False
    assert result["comparison_status"] == "unavailable"
    assert result["reason"] == "spy_eod_capture_failed_open:RuntimeError"


def test_postmarket_prepares_authority_before_persisting_daily_row(monkeypatch, tmp_path):
    from test_p48br1_adversarial_qa import _job_harness, _settings, _store

    settings = _settings(tmp_path)
    store = _store(tmp_path)
    counts = dict.fromkeys(["portfolio_snapshots", "reconcile_calls", "outcome_updates",
                           "build_calls", "persist_calls", "attribution_build_calls",
                           "attribution_persist_calls", "performance_calls"], 0)
    _job_harness(monkeypatch, store, counts=counts)
    order = []
    completed = {}
    def emit(_agent, event_type, _run, _message, payload):
        if event_type == "post_market_review_completed":
            completed.update(payload)
    monkeypatch.setattr(scheduler, "_reporter", lambda *_: SimpleNamespace(emit=emit))
    monkeypatch.setattr(scheduler, "_ensure_postmarket_spy_eod", lambda *_: (
        order.append("authority") or {"persisted": True, "comparison_status": "comparable"}))
    previous = scheduler._persist_daily_performance
    def persist(*args, **kwargs):
        order.append("performance")
        return previous(*args, **kwargs)
    monkeypatch.setattr(scheduler, "_persist_daily_performance", persist)
    report = scheduler.post_market_review_job(settings, store, use_llm=False,
                                             verbose=False, force=True)
    assert report is not None
    assert order == ["authority", "performance"]
    assert "spy_eod_receipt" not in report
    assert completed["spy_eod_receipt"]["comparison_status"] == "comparable"
    assert counts["reconcile_calls"] == counts["outcome_updates"] == 1
