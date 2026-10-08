"""Deterministic payload parity against frozen pre-optimization implementation."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from agente_bolsa.config import Settings
from agente_bolsa.tools import h_capture
from agente_bolsa.tools import signal_learning as learning

OBSERVED = datetime(2026, 10, 7, 22, tzinfo=timezone.utc)


def _fixture(count=120):
    signals, rows = [], []
    for index in range(count):
        symbol = "AAA" if index % 3 else "BBB"
        signal = {"signal_id": f"signal-{index}", "symbol": symbol,
                  "source_run_id": "cycle", "signal_source_run_id": "cycle", "signal_capture_id": f"capture-{index}",
                  "candidate_id": f"candidate-{index}", "features": {}}
        lineage = {"cycle_id": "cycle", "agent_run_id": "agent", **signal,
                   "signal_source_run_id": "cycle", "source_event_id": f"source-{index}",
                   "source_event_content_hash": f"hash-{index}"}
        payload = h_capture.build_prediction_capture(
            lineage=lineage, producer_stage="signal_candidate", capture_observed_at=OBSERVED,
            prediction={"prediction_at": "2026-10-05T20:00:00Z", "horizon_sessions": 1,
                        "predicted_probability": 0.6, "event_definition": "positive_forward_return",
                        "event_parameters": {"reference_price": 100}})
        signals.append(signal)
        rows.append({"event_id": payload["event_id"], "event_type": payload["event_type"],
                     "cycle_id": "cycle", "payload": payload})
    data = pd.concat({symbol: pd.DataFrame({"Close": values},
                     index=pd.to_datetime(["2026-10-06", "2026-10-07"]))
                     for symbol, values in {"AAA": [110, 115], "BBB": [90, 95]}.items()}, axis=1)
    return signals, rows, data


def _run(monkeypatch, tmp_path, signals, rows, data, *, legacy=False, fail_lookup=False,
         fail_persist=False):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    outputs, frames, calls = [], [], []
    monkeypatch.setattr(learning, "MarketCalendar", lambda *args: object())
    monkeypatch.setattr(learning, "_iter_signal_prediction_events", lambda *args: iter(rows))
    monkeypatch.setattr(h_capture, "resolve_xnys_maturity", lambda *args, **kwargs: {
        "status": "available", "outcome_matured_at": "2026-10-06T20:00:00Z",
        "outcome_maturity_session_date": "2026-10-06", "reference_session_date": "2026-10-05"})
    original = learning._symbol_frame
    # Keep original across successive calls within a monkeypatch context.
    original = getattr(original, "original", original)
    def lookup(frame, symbol):
        calls.append(symbol)
        if fail_lookup and symbol == "BBB":
            raise KeyError("lookup_failure")
        result = original(frame, symbol)
        frames.append((result, result.copy(deep=True)))
        return result
    lookup.original = original
    monkeypatch.setattr(learning, "_symbol_frame", lookup)
    def persist(store, payload):
        if fail_persist and payload["signal_id"] == "signal-2":
            raise RuntimeError("persist_failure")
        outputs.append(deepcopy(payload))
    monkeypatch.setattr(learning, "persist_h_capture_event", persist)
    function = learning._persist_signal_outcome_captures
    if legacy:
        namespace = dict(vars(learning))
        exec(Path(__file__).with_name("outcome_memory_legacy.txt").read_text(), namespace)
        function = namespace["_persist_signal_outcome_captures"]
    before = data.copy(deep=True)
    rows_before, signals_before = deepcopy(rows), deepcopy(signals)
    result = function(settings, object(), signals, data, observed_at=OBSERVED)
    pd.testing.assert_frame_equal(data, before)
    for frame, snapshot in frames:
        pd.testing.assert_frame_equal(frame, snapshot)
    assert signals == signals_before
    assert rows == rows_before
    return result, outputs, calls, frames


@pytest.mark.parametrize("fail_lookup,fail_persist", [(False, False), (True, False), (False, True)])
def test_full_payload_parity_and_fail_open(monkeypatch, tmp_path, fail_lookup, fail_persist):
    signals, rows, data = _fixture()
    expected = _run(monkeypatch, tmp_path, signals, rows, data, legacy=True,
                    fail_lookup=fail_lookup, fail_persist=fail_persist)
    actual = _run(monkeypatch, tmp_path, signals, rows, data,
                  fail_lookup=fail_lookup, fail_persist=fail_persist)
    assert actual[:2] == expected[:2]
    assert actual[0] is not (fail_lookup or fail_persist)
    assert len(actual[1]) == 120 - (40 if fail_lookup else 0) - (1 if fail_persist else 0)
    assert all(payload["outcome_status"] == "matured" for payload in actual[1])
    assert all(payload["outcome_value"] == (0.0 if int(payload["signal_id"].split("-")[1]) % 3 == 0
                                           else 1.0) for payload in actual[1])


def test_calls_are_isolated(monkeypatch, tmp_path):
    signals, rows, data = _fixture(6)
    first = _run(monkeypatch, tmp_path, signals, rows, data)
    changed = data.copy(deep=True)
    changed.loc[:, ("AAA", "Close")] = 80
    second = _run(monkeypatch, tmp_path, signals, rows, changed)
    assert first[1] != second[1]
    assert {id(frame) for frame, _ in first[3]}.isdisjoint(id(frame) for frame, _ in second[3])


@pytest.mark.parametrize("missing,empty,malformed", [(False, False, False),
    (True, False, False), (False, True, False), (False, False, True)])
def test_legacy_update_full_payload_parity(monkeypatch, tmp_path, missing, empty, malformed):
    signals, _, data = _fixture(30)
    for signal in signals:
        signal["signal_date"] = "2026-10-05"
        signal["features"] = {"entry_price": 100, "stop_loss": 85, "take_profit": 120}
    if missing:
        data = data.drop(columns="BBB", level=0)
    if empty:
        data[("BBB", "Close")] = float("nan")
    if malformed:
        signals[3]["features"] = [1]
    for symbol in data.columns.get_level_values(0).unique():
        data[(symbol, "High")] = data[(symbol, "Close")] + 2
        data[(symbol, "Low")] = data[(symbol, "Close")] - 2
    class FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return OBSERVED
    class MemoryStore:
        def signal_outcomes(self, **kwargs):
            return deepcopy(signals)
        def update_signal_outcomes_bulk(self, payload):
            self.saved = deepcopy(payload)
    monkeypatch.setattr(learning, "datetime", FrozenClock)
    monkeypatch.setattr(learning, "download_daily_prices", lambda *args, **kwargs: data)
    monkeypatch.setattr(learning, "trim_to_completed_sessions", lambda data, **kwargs:
                        (data, 0, "2026-10-07", False))
    monkeypatch.setattr(learning, "_persist_signal_outcome_captures", lambda *args, **kwargs: True)
    original = learning._symbol_frame
    calls, frames = [], []
    def lookup(data, symbol):
        calls.append(symbol)
        frame = original(data, symbol)
        frames.append((frame, frame.copy(deep=True)))
        return frame
    monkeypatch.setattr(learning, "_symbol_frame", lookup)
    namespace = dict(vars(learning))
    exec(Path(__file__).with_name("outcome_memory_legacy.txt").read_text(), namespace)
    namespace["_persist_signal_outcome_captures"] = learning._persist_signal_outcome_captures
    settings = Settings(_env_file=None, data_dir=tmp_path)
    before = data.copy(deep=True)
    legacy_store = MemoryStore()
    expected = namespace["update_signal_outcomes"](settings, legacy_store, now=OBSERVED)
    assert len(calls) == 30
    calls.clear()
    actual_store = MemoryStore()
    actual = learning.update_signal_outcomes(settings, actual_store, now=OBSERVED)
    assert actual == expected
    assert actual_store.saved == legacy_store.saved
    pd.testing.assert_frame_equal(data, before)
    for frame, snapshot in frames:
        pd.testing.assert_frame_equal(frame, snapshot)
    assert len(calls) == (11 if missing else 2)
