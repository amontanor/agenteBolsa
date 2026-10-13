"""Outcome update parity against frozen c1ffb964 implementation; no providers."""
import tracemalloc
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from agente_bolsa.tools import h_capture
from agente_bolsa.tools import signal_learning as learning

OBSERVED = datetime(2026, 10, 13, 6, tzinfo=timezone.utc)


class FrozenClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return OBSERVED


def fixture():
    signals, events = [], []
    for i in range(18):
        signal = {
            "signal_id": f"s-{i}", "symbol": "AAA" if i % 2 else "BBB", "signal_date": "2026-10-01",
            "source_run_id": "cycle", "signal_source_run_id": "cycle", "signal_capture_id": f"capture-{i}", "candidate_id": f"candidate-{i}",
            "features": {"entry_price": None if i % 4 == 0 else 100, "close": 100, "stop_loss": 90, "take_profit": 125,
                         "unused": "x" * 20000, "producer_agent_contract": {"cycle_id": "cycle", "agent_run_id": "agent", "unused": "y" * 20000}},
            "gate": {"unused": "z" * 20000}, "outcome": {"unused": "z" * 20000},
        }
        lineage = {"cycle_id": "cycle", "agent_run_id": "agent", **signal, "source_event_id": f"source-{i}", "source_event_content_hash": f"hash-{i}"}
        event = h_capture.build_prediction_capture(lineage=lineage, producer_stage="signal_candidate", capture_observed_at=OBSERVED,
            prediction={"prediction_at": "2026-10-01T20:00:00Z", "horizon_sessions": 1, "predicted_probability": 0.6,
                        "event_definition": "positive_forward_return", "event_parameters": {"reference_price": 100}})
        signals.append(signal)
        events.append({"event_id": event["event_id"], "event_type": event["event_type"], "cycle_id": "cycle", "payload": event})
    data = pd.concat({symbol: pd.DataFrame({"Close": [102, 105, 110, 108, 115, 125, 130, 131, 132, 130],
                                           "High": [104, 107, 112, 110, 117, 127, 132, 133, 134, 132],
                                           "Low": [100, 103, 108, 106, 113, 123, 128, 129, 130, 128]},
                    index=pd.bdate_range("2026-10-02", periods=10)) for symbol in ("AAA", "BBB")},axis=1)
    return signals, events, data


@pytest.mark.parametrize("variant", ["normal", "ambiguous", "mismatch", "missing_symbol", "empty_symbol", "malformed", "download_failure", "capture_failure", "bulk_failure", "feature_identity", "empty", "single_writes"])
def test_update_and_captures_exact_parity(monkeypatch, variant):
    signals, events, data = fixture()
    if variant == "ambiguous":
        signals.append({**signals[0], "symbol": "AAA", "source_run_id": "other"})
        signals.append(deepcopy(signals[1]))
    if variant == "mismatch":
        signals[0]["features"]["producer_agent_contract"]["agent_run_id"] = "different"
        signals[1]["features"].pop("producer_agent_contract")
        signals[2]["signal_capture_id"] = "different"
    if variant == "feature_identity":
        for signal in signals:
            for field in ("signal_capture_id", "signal_source_run_id", "candidate_id"):
                signal["features"][field] = signal.pop(field)
    if variant == "empty":
        signals.clear()
    if variant == "missing_symbol":
        data = data.drop(columns="BBB", level=0)
    if variant == "empty_symbol":
        for field in ("Close", "High", "Low"):
            data[("BBB", field)] = float("nan")
    if variant == "malformed":
        signals[0]["features"] = [1]
    monkeypatch.setattr(learning, "datetime", FrozenClock)
    monkeypatch.setattr(learning, "MarketCalendar", lambda *args: object())
    monkeypatch.setattr(learning, "trim_to_completed_sessions", lambda frame, **_: (frame, 0, "2026-10-12", False))
    monkeypatch.setattr(h_capture, "resolve_xnys_maturity", lambda *args, **_: {"status": "available", "outcome_matured_at": "2026-10-02T20:00:00Z", "outcome_maturity_session_date": "2026-10-02", "reference_session_date": "2026-10-01"})
    calls, captures = [], []

    def download(symbols, **kwargs):
        calls.append((symbols, kwargs))
        if variant == "download_failure":
            raise RuntimeError("download_failure")
        return data

    def persist(store, event):
        if variant == "capture_failure" and event["signal_id"] == "s-3":
            raise RuntimeError("capture_failure")
        assert h_capture.validate_h_capture_event({"event_id": event["event_id"], "event_type": event["event_type"], "cycle_id": event["cycle_id"], "payload": event}, expected_event_type=h_capture.OUTCOME_EVENT_TYPE)
        captures.append(deepcopy(event))

    monkeypatch.setattr(learning, "download_daily_prices", download)
    monkeypatch.setattr(learning, "persist_h_capture_event", persist)

    class MemoryStore:
        def __init__(self):
            self.reads = []
            self.event_reads = []
            self.closed = False
            self.saved = None

        def __getattribute__(self, name):
            if name == "update_signal_outcomes_bulk" and variant == "single_writes":
                raise AttributeError(name)
            return super().__getattribute__(name)

        def update_signal_outcome(self, signal_id, outcome):
            if self.saved is None:
                self.saved = {}
            self.saved[signal_id] = deepcopy(outcome)

        def signal_outcomes(self, **kwargs):
            self.reads.append(kwargs)
            return deepcopy(signals)

        def iter_signal_outcomes(self, **kwargs):
            self.reads.append(kwargs)
            try:
                for signal in signals:
                    yield deepcopy(signal)
            finally:
                self.closed = True

        def iter_agent_events(self, **kwargs):
            self.event_reads.append(kwargs)
            yield from (row for row in events if not kwargs.get("cycle_id") or row["cycle_id"] == kwargs["cycle_id"])

        def update_signal_outcomes_bulk(self, payload):
            if variant == "bulk_failure":
                raise RuntimeError("bulk_failure")
            self.saved = deepcopy(payload)

    namespace = dict(vars(learning))
    exec(Path(__file__).with_name("oct13_update_outcomes_legacy.txt").read_text(encoding="utf-8"), namespace)
    outputs = []
    for function in (namespace["update_signal_outcomes"], learning.update_signal_outcomes):
        calls.clear()
        captures.clear()
        store = MemoryStore()
        try:
            result = function(SimpleNamespace(market_calendar="XNYS", local_timezone="Europe/Madrid"), store, limit=200000, now=OBSERVED, observed_at=OBSERVED)
        except RuntimeError as exc:
            result = str(exc)
        outputs.append((result, store.saved, deepcopy(captures), deepcopy(calls), store.reads, store.event_reads))
        if function is learning.update_signal_outcomes and hasattr(learning, "_compact_outcome_update_signal"):
            assert store.closed
    assert outputs[0] == outputs[1]
    if variant in {"normal", "feature_identity", "single_writes"}:
        assert len(outputs[1][2]) == 18


def test_update_peak_drops_historical_payloads(monkeypatch):
    _, _, data = fixture()
    monkeypatch.setattr(learning, "datetime", FrozenClock)
    calls = []
    monkeypatch.setattr(learning, "download_daily_prices", lambda symbols, **kwargs: calls.append((symbols, kwargs)) or data)
    monkeypatch.setattr(learning, "trim_to_completed_sessions", lambda frame, **_: (frame, 0, "2026-10-12", False))
    monkeypatch.setattr(learning, "_persist_signal_outcome_captures", lambda *args, **_: True)
    saved = []
    closed = []

    def reader(**kwargs):
        assert kwargs == {"limit": 200000, "since_date": "2026-04-01", "include_lab_book": True, "include_learning_experiment": True}
        try:
            for i in range(1200):
                yield {"signal_id": f"s-{i}", "symbol": "AAA", "signal_date": "2026-10-01", "source_run_id": "cycle", "features": {"entry_price": 100, "stop_loss": 90, "take_profit": 125, "unused": "x" * 100000}, "outcome": {"unused": "y" * 100000}, "gate": {"unused": "z" * 100000}}
        finally:
            closed.append(True)

    store = SimpleNamespace(iter_signal_outcomes=reader, update_signal_outcomes_bulk=lambda payload: saved.append(payload))
    tracemalloc.start()
    try:
        result = learning.update_signal_outcomes(SimpleNamespace(), store, limit=200000, now=OBSERVED)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result["signals"] == result["updated"] == 1200
    assert len(saved[0]) == 1200
    assert len(calls) == 1
    assert closed == [True]
    assert peak < 6_000_000, peak


def test_projection_reader_failure_closes_and_does_not_download(monkeypatch):
    closed = []
    def reader(**_):
        try:
            yield {"features": {}, "symbol": "AAA", "signal_date": "2026-10-01", "signal_id": "s"}
            raise ValueError("decode_failure")
        finally:
            closed.append(True)
    monkeypatch.setattr(learning, "download_daily_prices", lambda *_args, **_kwargs: pytest.fail("download must not happen"))
    with pytest.raises(ValueError, match="decode_failure"):
        learning.update_signal_outcomes(SimpleNamespace(), SimpleNamespace(iter_signal_outcomes=reader))
    assert closed == [True]
