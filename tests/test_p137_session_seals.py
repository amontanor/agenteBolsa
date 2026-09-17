from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.signal_learning import trim_to_completed_sessions, update_signal_outcomes

# 2026-09-16 es miercoles. 16:00 UTC = 12:00 ET (sesion abierta, mutable);
# 21:05 UTC = 17:05 ET (sesion cerrada).
WED_NOON_ET = datetime(2026, 9, 16, 16, 0, tzinfo=timezone.utc)
WED_AFTER_CLOSE_ET = datetime(2026, 9, 16, 21, 5, tzinfo=timezone.utc)


def _frame(dates: list[str]) -> pd.DataFrame:
    n = len(dates)
    return pd.DataFrame(
        {
            "Open": [100.0 + i for i in range(n)],
            "High": [101.0 + i for i in range(n)],
            "Low": [99.0 + i for i in range(n)],
            "Close": [100.0 + i for i in range(n)],
        },
        index=pd.DatetimeIndex(dates),
    )


def test_open_session_bar_is_trimmed() -> None:
    frame = _frame(["2026-09-14", "2026-09-15", "2026-09-16"])

    kept, trimmed, last_completed, degraded = trim_to_completed_sessions(frame, now=WED_NOON_ET)

    assert trimmed == 1
    assert last_completed == "2026-09-15"
    assert degraded is False
    assert kept.index.map(lambda idx: str(idx.date())).tolist() == ["2026-09-14", "2026-09-15"]


def test_closed_session_bar_is_kept() -> None:
    frame = _frame(["2026-09-14", "2026-09-15", "2026-09-16"])

    kept, trimmed, last_completed, degraded = trim_to_completed_sessions(frame, now=WED_AFTER_CLOSE_ET)

    assert trimmed == 0
    assert last_completed == "2026-09-16"
    assert degraded is False
    assert len(kept) == 3


def test_mutable_bar_does_not_mature_outcome(tmp_path: Path, monkeypatch) -> None:
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="sig-seal-1",
        source_run_id="run-1",
        source="test",
        symbol="AAA",
        signal_date="2026-09-15",
        decision="approved_buy",
        features={"entry_price": 100.0, "close": 100.0},
        gate={},
    )
    frame = _frame(["2026-09-15", "2026-09-16"])
    monkeypatch.setattr(
        "agente_bolsa.tools.signal_learning.download_daily_prices",
        lambda symbols, start, end: frame,
    )
    monkeypatch.setattr(
        "agente_bolsa.tools.signal_learning.datetime",
        _FrozenDateTime(WED_NOON_ET),
    )

    result = update_signal_outcomes(Settings(DATA_DIR=tmp_path), store, since_date="2026-09-01")
    row = store.signal_outcome_by_id("sig-seal-1")

    assert result["bars_trimmed_universe"] == 1
    assert result["last_completed_session"] == "2026-09-15"
    assert row["outcome"]["matured_horizons"]["1d"] is False
    assert row["outcome"]["bars_seen"] == 0


def test_completed_history_is_untouched_parity(tmp_path: Path, monkeypatch) -> None:
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="sig-seal-2",
        source_run_id="run-1",
        source="test",
        symbol="AAA",
        signal_date="2026-04-27",
        decision="approved_buy",
        features={"entry_price": 100.0, "close": 100.0},
        gate={},
    )
    frame = pd.DataFrame(
        {
            "Open": [100, 101, 102, 103, 104, 105, 106],
            "High": [101, 102, 103, 104, 105, 106, 107],
            "Low": [99, 100, 101, 102, 103, 104, 105],
            "Close": [100, 101, 102, 103, 104, 105, 106],
        },
        index=pd.date_range("2026-04-27", periods=7, freq="B"),
    )
    monkeypatch.setattr(
        "agente_bolsa.tools.signal_learning.download_daily_prices",
        lambda symbols, start, end: frame,
    )

    result = update_signal_outcomes(Settings(DATA_DIR=tmp_path), store, since_date="2026-04-01")
    row = store.signal_outcome_by_id("sig-seal-2")

    assert result["bars_trimmed_universe"] == 0
    assert row["outcome"]["return_5d"] == 0.05
    assert row["outcome"]["matured_horizons"]["5d"] is True


class _FrozenDateTime:
    """datetime.now congelado; el resto delega al datetime real."""

    def __init__(self, frozen):
        self._frozen = frozen
        self._real = datetime

    def now(self, tz=None):
        return self._frozen

    def __call__(self, *args, **kwargs):
        return self._real(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)
