import json
from datetime import datetime, timezone

import pandas as pd

from agente_bolsa import web_app
from agente_bolsa.config import Settings
from agente_bolsa.tools.opening_performance import (
    build_opening_omissions,
    load_cached_spy_open_observations,
)


SESSION_DATE = "2026-07-29"
NOW = datetime(2026, 7, 29, 16, 0, tzinfo=timezone.utc)
AUTHORITY_PRICE = 739.969970703125


def _write_cache(
    tmp_path,
    name: str,
    *,
    created_at: str,
    open_price: float,
    current_price: float,
    requested_symbols: list[str],
    purpose: str | None = None,
    price_basis: str = "adjusted_ohlc",
) -> None:
    cache_root = tmp_path / "cache" / "market_data"
    cache_root.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {"Open": [open_price], "Close": [current_price]},
        index=pd.to_datetime([SESSION_DATE]),
    )
    frame.to_pickle(cache_root / f"market_data_{name}.pkl")
    metadata = {
        "source": "fixture",
        "created_at": created_at,
        "requested_symbols": requested_symbols,
        "start": SESSION_DATE,
        "end": SESSION_DATE,
        "interval": "1d",
        "price_basis": price_basis,
    }
    if purpose:
        metadata["purpose"] = purpose
    (cache_root / f"market_data_{name}.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )


def _settings(tmp_path) -> Settings:
    return Settings(_env_file=None, DATA_DIR=tmp_path)


def test_authority_in_same_value_group_dominates_generic_duplicate_regardless_of_arrival_order(tmp_path):
    """Caracteriza la regresión: group[0] hace depender la autoridad del orden."""

    _write_cache(
        tmp_path,
        "broad-different",
        created_at="2026-07-29T13:40:00+00:00",
        open_price=739.1900024414062,
        current_price=739.5599975585938,
        requested_symbols=["AAPL", "SPY"],
    )
    _write_cache(
        tmp_path,
        "a-generic-same",
        created_at="2026-07-29T13:45:00+00:00",
        open_price=AUTHORITY_PRICE,
        current_price=738.6500244140625,
        requested_symbols=["AAPL", "SPY"],
    )
    _write_cache(
        tmp_path,
        "z-dedicated-same",
        created_at="2026-07-29T13:50:00+00:00",
        open_price=AUTHORITY_PRICE,
        current_price=738.6500244140625,
        requested_symbols=["SPY"],
        purpose="benchmark_open",
    )

    observed = load_cached_spy_open_observations(_settings(tmp_path), now=NOW)

    assert observed["status"] == "available"
    assert observed["opens"][0]["price"] == AUTHORITY_PRICE
    assert observed["opens"][0]["provenance"]["authority"] == "explicit_benchmark_open"
    assert observed["current"]["price"] == 738.6500244140625


def test_authority_group_resolves_when_dedicated_artifact_arrives_first(tmp_path):
    _write_cache(
        tmp_path,
        "broad-different",
        created_at="2026-07-29T13:40:00+00:00",
        open_price=739.1900024414062,
        current_price=739.5599975585938,
        requested_symbols=["AAPL", "SPY"],
    )
    _write_cache(
        tmp_path,
        "dedicated-same",
        created_at="2026-07-29T13:45:00+00:00",
        open_price=AUTHORITY_PRICE,
        current_price=738.6500244140625,
        requested_symbols=["SPY"],
        purpose="benchmark_open",
    )
    _write_cache(
        tmp_path,
        "generic-same",
        created_at="2026-07-29T13:50:00+00:00",
        open_price=AUTHORITY_PRICE,
        current_price=738.6500244140625,
        requested_symbols=["AAPL", "SPY"],
    )

    observed = load_cached_spy_open_observations(_settings(tmp_path), now=NOW)

    assert observed["status"] == "available"
    assert observed["opens"][0]["provenance"]["authority"] == "explicit_benchmark_open"


def test_two_discordant_authorities_remain_conflict(tmp_path):
    _write_cache(
        tmp_path,
        "a-authority",
        created_at="2026-07-29T13:45:00+00:00",
        open_price=739.969970703125,
        current_price=738.65,
        requested_symbols=["SPY"],
        purpose="benchmark_open",
    )
    _write_cache(
        tmp_path,
        "z-authority",
        created_at="2026-07-29T13:50:00+00:00",
        open_price=740.50,
        current_price=739.0,
        requested_symbols=["SPY"],
        purpose="benchmark_open",
    )

    observed = load_cached_spy_open_observations(_settings(tmp_path), now=NOW)

    assert observed["status"] == "conflict"
    assert observed["opens"] == []
    assert observed["current"] is None


def test_multiple_values_without_authority_remain_conflict(tmp_path):
    _write_cache(
        tmp_path,
        "a-generic",
        created_at="2026-07-29T13:45:00+00:00",
        open_price=739.969970703125,
        current_price=738.65,
        requested_symbols=["AAPL", "SPY"],
    )
    _write_cache(
        tmp_path,
        "z-generic",
        created_at="2026-07-29T13:50:00+00:00",
        open_price=740.50,
        current_price=739.0,
        requested_symbols=["PM", "SPY"],
    )

    observed = load_cached_spy_open_observations(_settings(tmp_path), now=NOW)

    assert observed["status"] == "conflict"
    assert observed["opens"] == []


def test_invalid_basis_or_future_timestamp_is_unavailable(tmp_path):
    _write_cache(
        tmp_path,
        "invalid",
        created_at="2026-07-30T13:45:00+00:00",
        open_price=AUTHORITY_PRICE,
        current_price=738.65,
        requested_symbols=["SPY"],
        purpose="benchmark_open",
        price_basis="raw",
    )

    observed = load_cached_spy_open_observations(_settings(tmp_path), now=NOW)

    assert observed["status"] == "unavailable"
    assert observed["opens"] == []
    assert observed["current"] is None


def test_resolution_is_read_only_and_repeatable(tmp_path):
    _write_cache(
        tmp_path,
        "a-generic",
        created_at="2026-07-29T13:45:00+00:00",
        open_price=AUTHORITY_PRICE,
        current_price=738.65,
        requested_symbols=["AAPL", "SPY"],
    )
    _write_cache(
        tmp_path,
        "z-dedicated",
        created_at="2026-07-29T13:50:00+00:00",
        open_price=AUTHORITY_PRICE,
        current_price=738.65,
        requested_symbols=["SPY"],
        purpose="benchmark_open",
    )
    files = sorted((tmp_path / "cache" / "market_data").glob("*"))
    before = {path.name: path.read_bytes() for path in files}

    first = load_cached_spy_open_observations(_settings(tmp_path), now=NOW)
    second = load_cached_spy_open_observations(_settings(tmp_path), now=NOW)

    assert first == second
    assert {path.name: path.read_bytes() for path in files} == before


def test_omitted_session_exposes_reason_and_coverage():
    omissions = build_opening_omissions(
        [
            {"session_date": "2026-07-28"},
            {"session_date": SESSION_DATE},
        ],
        {
            "opens": [{"session_date": "2026-07-28", "price_basis": "adjusted_ohlc"}],
            "conflicts": {SESSION_DATE: [{"price": AUTHORITY_PRICE}]},
        },
        [],
    )

    assert omissions == [
        {
            "session_date": "2026-07-28",
            "end_session_date": SESSION_DATE,
            "status": "omitted",
            "reason": "spy_open_conflict",
            "coverage": {
                "account_start": True,
                "account_end": True,
                "spy_start": True,
                "spy_end": False,
            },
        }
    ]


def test_ui_renders_omitted_date_reason_and_coverage(monkeypatch):
    rendered: list[tuple[str, str]] = []

    class StreamlitStub:
        def markdown(self, value, **_kwargs):
            rendered.append(("markdown", value))

        def caption(self, value):
            rendered.append(("caption", value))

    monkeypatch.setattr(web_app, "st", StreamlitStub())
    web_app._render_opening_omissions(
        {
            "omitted_sessions": [
                {
                    "session_date": SESSION_DATE,
                    "end_session_date": "2026-07-30",
                    "status": "omitted",
                    "reason": "spy_open_conflict",
                    "coverage": {"account_start": True, "account_end": True, "spy_start": True, "spy_end": False},
                }
            ]
        }
    )

    text = " ".join(value for _kind, value in rendered)
    assert SESSION_DATE in text
    assert "spy_open_conflict" in text
    assert "spy_end=no" in text
