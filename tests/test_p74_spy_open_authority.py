from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

from agente_bolsa.config import Settings
from agente_bolsa.tools.opening_performance import load_cached_spy_open_observations


def _write_cache(
    tmp_path,
    name: str,
    *,
    created_at: str,
    open_price: float,
    current_price: float,
    requested_symbols: list[str],
) -> None:
    cache_root = tmp_path / "cache" / "market_data"
    cache_root.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {"Open": [open_price], "Close": [current_price]},
        index=pd.to_datetime(["2026-07-29"]),
    )
    frame.to_pickle(cache_root / f"market_data_{name}.pkl")
    (cache_root / f"market_data_{name}.json").write_text(
        json.dumps(
            {
                "source": "yfinance",
                "created_at": created_at,
                "requested_symbols": requested_symbols,
                "start": "2026-07-29",
                "end": "2026-07-29",
                "interval": "1d",
                "price_basis": "adjusted_ohlc",
            }
        ),
        encoding="utf-8",
    )


def test_conflicting_same_session_caches_are_not_resolved_by_latest_timestamp(tmp_path):
    """La base selecciona la caché estrecha más reciente sin resolver el conflicto."""

    _write_cache(
        tmp_path,
        "0bc493d6d987c1b1",
        created_at="2026-07-29T13:42:39+00:00",
        open_price=739.1900024414062,
        current_price=739.5599975585938,
        requested_symbols=[f"S{index:02d}" for index in range(24)] + ["SPY"],
    )
    _write_cache(
        tmp_path,
        "fae973e5b2174803",
        created_at="2026-07-29T13:50:33+00:00",
        open_price=739.969970703125,
        current_price=738.6500244140625,
        requested_symbols=["PM", "SPY"],
    )

    observed = load_cached_spy_open_observations(
        Settings(_env_file=None, DATA_DIR=tmp_path),
        now=datetime(2026, 7, 29, 16, 0, tzinfo=timezone.utc),
    )

    assert observed["status"] == "conflict"
    assert observed["current"] is None
    assert observed["opens"] == []
    assert "conflicting_session_open_observations" in observed["warnings"]
