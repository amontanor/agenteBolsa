import json
from datetime import datetime, timezone

import pandas as pd

from agente_bolsa.config import Settings
from agente_bolsa.tools.opening_performance import load_cached_spy_open_observations


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
        "price_basis": "adjusted_ohlc",
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
