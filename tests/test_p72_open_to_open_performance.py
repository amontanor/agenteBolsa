from __future__ import annotations

import json
from datetime import datetime, timezone
from inspect import getsource

import pandas as pd
import pytest

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.opening_performance import (
    build_open_to_open_rows,
    build_session_open_snapshot,
    extract_exact_open_snapshots,
    load_cached_spy_open_observations,
    opening_performance_context,
    persist_session_open_snapshot,
    read_session_open_snapshots,
)
from agente_bolsa.tools.telegram_daily_summary import build_daily_summary, format_daily_summary
from agente_bolsa.web_app import _render_daily_vs_spy_table

ACCOUNT_HISTORY = {
    "timestamp": [
        "2026-07-24T13:30:00+00:00",
        "2026-07-27T13:30:00+00:00",
        "2026-07-28T13:30:00+00:00",
        "2026-07-28T20:00:00+00:00",
        "2026-07-29T00:00:00+00:00",
    ],
    "equity": [70421.85, 70561.64, 70672.33, 70633.17, 99999.0],
}


def _store(tmp_path) -> Store:
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    return store


def _settings(tmp_path) -> Settings:
    return Settings(_env_file=None, DATA_DIR=tmp_path)


def _write_spy_cache(tmp_path) -> None:
    cache = tmp_path / "cache" / "market_data"
    cache.mkdir(parents=True)
    frame = pd.DataFrame(
        {
            "Open": [738.510009765625, 744.9099731445312, 739.1900024414062],
            "Close": [741.0, 738.0, 740.8599853515625],
        },
        index=pd.to_datetime(["2026-07-24", "2026-07-27", "2026-07-28"]),
    )
    frame.to_pickle(cache / "market_data_spy.pkl")
    (cache / "market_data_spy.json").write_text(
        json.dumps(
            {
                "requested_symbols": ["SPY"],
                "interval": "1d",
                "price_basis": "adjusted_ohlc",
                "source": "yfinance_cache",
                "created_at": "2026-07-28T20:05:00+00:00",
                "provider_observed_at": "2026-07-28T20:05:00+00:00",
            }
        ),
        encoding="utf-8",
    )


def test_exact_open_extraction_rejects_close_and_midnight_rows() -> None:
    rows = extract_exact_open_snapshots(ACCOUNT_HISTORY)

    assert [row["session_date"] for row in rows] == ["2026-07-24", "2026-07-27", "2026-07-28"]
    assert [row["equity"] for row in rows] == [70421.85, 70561.64, 70672.33]


def test_open_to_open_rows_use_next_xnys_session_and_current_interval(tmp_path) -> None:
    _write_spy_cache(tmp_path)
    account = extract_exact_open_snapshots(ACCOUNT_HISTORY)
    spy = load_cached_spy_open_observations(
        _settings(tmp_path),
        now=datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc),
    )

    rows = build_open_to_open_rows(
        account,
        spy,
        current_equity=70641.51,
        current_equity_at=datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc),
    )

    assert [(row["session_date"], row["status"]) for row in rows] == [
        ("2026-07-24", "final"),
        ("2026-07-27", "final"),
        ("2026-07-28", "in_progress"),
    ]
    assert rows[0]["system_pct"] == pytest.approx(0.00198504, abs=1e-8)
    assert rows[0]["spy_pct"] == pytest.approx(0.00866605, abs=1e-8)
    assert rows[1]["system_pct"] == pytest.approx(0.00156870, abs=1e-8)
    assert rows[1]["spy_pct"] == pytest.approx(-0.00767874, abs=1e-8)
    assert rows[2]["system_delta"] == pytest.approx(-30.82, abs=1e-8)
    assert rows[2]["system_pct"] == pytest.approx(-0.00043610, abs=1e-8)
    assert rows[2]["spy_pct"] == pytest.approx(0.00225921, abs=1e-8)


def test_missing_intermediate_open_does_not_create_multisession_return(tmp_path) -> None:
    _write_spy_cache(tmp_path)
    account = [
        row
        for row in extract_exact_open_snapshots(ACCOUNT_HISTORY)
        if row["session_date"] != "2026-07-27"
    ]
    spy = load_cached_spy_open_observations(
        _settings(tmp_path),
        now=datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc),
    )

    rows = build_open_to_open_rows(
        account,
        spy,
        current_equity=70641.51,
        current_equity_at=datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc),
    )

    assert [row["status"] for row in rows] == ["in_progress"]
    assert rows[0]["session_date"] == "2026-07-28"


def test_stale_spy_price_is_not_published_as_current(tmp_path) -> None:
    _write_spy_cache(tmp_path)
    account = extract_exact_open_snapshots(
        {
            "timestamp": [*ACCOUNT_HISTORY["timestamp"], "2026-07-29T13:30:00+00:00"],
            "equity": [*ACCOUNT_HISTORY["equity"], 70700.0],
        }
    )
    spy = load_cached_spy_open_observations(
        _settings(tmp_path),
        now=datetime(2026, 7, 29, 15, 0, tzinfo=timezone.utc),
    )

    rows = build_open_to_open_rows(
        account,
        spy,
        current_equity=70710.0,
        current_equity_at=datetime(2026, 7, 29, 15, 0, tzinfo=timezone.utc),
    )

    assert all(row["status"] == "final" for row in rows)


def test_session_open_event_is_append_only_idempotent_and_conflict_safe(tmp_path) -> None:
    store = _store(tmp_path)
    observation = extract_exact_open_snapshots(ACCOUNT_HISTORY)[-1]
    payload = build_session_open_snapshot(
        observation,
        captured_at=datetime(2026, 7, 28, 14, 0, tzinfo=timezone.utc),
    )
    repeated = build_session_open_snapshot(
        observation,
        captured_at=datetime(2026, 7, 28, 15, 0, tzinfo=timezone.utc),
    )

    assert persist_session_open_snapshot(store, payload)["status"] == "inserted"
    assert persist_session_open_snapshot(store, repeated)["status"] == "idempotent"
    changed = build_session_open_snapshot({**observation, "equity": observation["equity"] + 1})
    assert persist_session_open_snapshot(store, changed)["status"] == "conflict"
    assert read_session_open_snapshots(store)[0]["equity"] == observation["equity"]


def test_context_and_telegram_share_the_same_opening_denominator(tmp_path) -> None:
    store = _store(tmp_path)
    _write_spy_cache(tmp_path)
    context = opening_performance_context(
        _settings(tmp_path),
        store,
        intraday_history=ACCOUNT_HISTORY,
        current_equity=70641.51,
        now=datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc),
    )
    portfolio = type("Portfolio", (), {"portfolio_value": 70641.51, "positions": []})()

    payload = build_daily_summary(
        session_date="2026-07-28",
        performance={},
        portfolio=portfolio,
        opening_performance=context,
    )
    text = format_daily_summary(payload)

    assert payload["schema_version"] == "p-l72.telegram-daily-summary.v3"
    assert payload["previous_equity"] == pytest.approx(70672.33)
    assert payload["account_daily_return"] == pytest.approx(-0.00043610, abs=1e-8)
    assert payload["spy_daily_return"] == pytest.approx(0.00225921, abs=1e-8)
    assert payload["comparison_status"] == "in_progress"
    assert "(-30.82 USD / -0.04%)" in text
    assert "SP500 +0.23%" in text and "(en curso)" in text


def test_daily_table_renders_only_complete_rows_newest_first() -> None:
    source = getsource(_render_daily_vs_spy_table)

    assert "for row in reversed(visible_rows)" in source
    assert "Pendiente" not in source
    assert "performance_daily" not in source
