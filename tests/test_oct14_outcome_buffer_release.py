"""Characterize bounded local outcome-buffer release before capture persistence."""
from __future__ import annotations

import gc
import json
import weakref
from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from agente_bolsa.tools import signal_learning as learning

OBSERVED = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)


class WeakOutcome(dict):
    """Weak-referenceable outcome payload for the release characterization."""


class SerializingStore:
    def __init__(self, mode: str, *, fail: bool = False):
        self.mode = mode
        self.fail = fail
        self.bulk_payload = None
        self.single_payload = {}

    def __getattribute__(self, name):
        if name == "update_signal_outcomes_bulk":
            if object.__getattribute__(self, "mode") == "fallback":
                raise AttributeError(name)
        return super().__getattribute__(name)

    def iter_signal_outcomes(self, **_kwargs):
        yield from (
            {
                "signal_id": "signal-1",
                "symbol": "AAA",
                "signal_date": "2026-10-01",
                "source_run_id": "cycle-1",
                "features": {"entry_price": 100, "stop_loss": 90, "take_profit": 120},
            },
            {
                "signal_id": "signal-2",
                "symbol": "AAA",
                "signal_date": "2026-10-01",
                "source_run_id": "cycle-1",
                "features": {"entry_price": 101, "stop_loss": 91, "take_profit": 121},
            },
        )

    def update_signal_outcomes_bulk(self, payload):
        if self.fail:
            raise RuntimeError("store_write_failure")
        self.bulk_payload = json.loads(json.dumps(payload, sort_keys=True))

    def update_signal_outcome(self, signal_id, outcome):
        if self.fail:
            raise RuntimeError("store_write_failure")
        self.single_payload[signal_id] = json.loads(json.dumps(outcome, sort_keys=True))

    @property
    def persisted_ids(self):
        payload = self.bulk_payload if self.mode == "bulk" else self.single_payload
        return list(payload)


@pytest.fixture
def data_frame():
    dates = pd.bdate_range("2026-10-02", periods=3)
    return pd.concat(
        {
            "AAA": pd.DataFrame(
                {"Close": [102, 103, 104], "High": [103, 104, 105], "Low": [101, 102, 103]},
                index=dates,
            )
        },
        axis=1,
    )


def _patch_pipeline(monkeypatch, data_frame, outcome_factory):
    monkeypatch.setattr(learning, "download_daily_prices", lambda symbols, **_kwargs: data_frame)
    monkeypatch.setattr(
        learning,
        "trim_to_completed_sessions",
        lambda frame, **_kwargs: (frame, 0, "2026-10-13", False),
    )
    monkeypatch.setattr(learning, "_outcome_for_signal", outcome_factory)


def test_local_buffers_release_before_capture_and_preserve_payload(monkeypatch, data_frame):
    weak_outcomes = weakref.WeakValueDictionary()
    captured = []

    def outcome_factory(signal, _frame):
        outcome = WeakOutcome({"signal_id": signal["signal_id"], "available": True})
        weak_outcomes[signal["signal_id"]] = outcome
        return outcome

    def capture(_settings, _store, signals, data, *, observed_at):
        gc.collect()
        # signal-1 is no longer retained by either local buffer when capture starts.
        assert "signal-1" not in weak_outcomes
        captured.append(
            {
                "signal_ids": [signal["signal_id"] for signal in signals],
                "columns": list(data.columns),
                "observed_at": observed_at,
            }
        )
        return True

    monkeypatch.setattr(learning, "_persist_signal_outcome_captures", capture)
    _patch_pipeline(monkeypatch, data_frame, outcome_factory)

    for mode in ("bulk", "fallback"):
        store = SerializingStore(mode)
        result = learning.update_signal_outcomes(
            SimpleNamespace(), store, now=OBSERVED, observed_at=OBSERVED
        )

        assert result["updated"] == 2
        assert result["warnings"] == []
        assert store.persisted_ids == ["signal-1", "signal-2"]
        assert captured[-1]["signal_ids"] == ["signal-1", "signal-2"]
        assert captured[-1]["columns"] == list(data_frame.columns)
        assert captured[-1]["observed_at"] == OBSERVED
        gc.collect()
        assert not weak_outcomes


def test_bulk_and_fallback_write_errors_have_same_contract(monkeypatch, data_frame):
    def outcome_factory(signal, _frame):
        return {"signal_id": signal["signal_id"], "available": True}

    _patch_pipeline(monkeypatch, data_frame, outcome_factory)
    monkeypatch.setattr(
        learning,
        "_persist_signal_outcome_captures",
        lambda *_args, **_kwargs: pytest.fail("capture must not run"),
    )

    errors = []
    for mode in ("bulk", "fallback"):
        with pytest.raises(RuntimeError, match="^store_write_failure$") as caught:
            learning.update_signal_outcomes(
                SimpleNamespace(), SerializingStore(mode, fail=True), now=OBSERVED, observed_at=OBSERVED
            )
        errors.append(str(caught.value))

    assert errors == ["store_write_failure", "store_write_failure"]