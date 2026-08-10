from __future__ import annotations

import json
from datetime import datetime, timezone
from inspect import getsource

import pandas as pd

from agente_bolsa import scheduler, web_app
from agente_bolsa.config import Settings
from agente_bolsa.models import PortfolioSnapshot, PositionSnapshot
from agente_bolsa.scheduler import _attempt_authoritative_spy_open_capture
from agente_bolsa.tools.opening_performance import (
    build_open_to_open_rows,
    load_cached_spy_open_observations,
)
from agente_bolsa.tools.trade_history import _open_positions_summary
from agente_bolsa.web_app import _position_rows


def _cache(
    root,
    name: str,
    *,
    created_at: str,
    open_price: float,
    current_price: float,
    requested_symbols: list[str],
    purpose: str | None = None,
) -> None:
    cache_root = root / "cache" / "market_data"
    cache_root.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {"Open": [open_price], "Close": [current_price]},
        index=pd.to_datetime(["2026-07-29"]),
    )
    frame.to_pickle(cache_root / f"market_data_{name}.pkl")
    metadata = {
        "created_at": created_at,
        "provider_observed_at": created_at,
        "requested_symbols": requested_symbols,
        "start": "2026-07-29",
        "end": "2026-07-29",
        "interval": "1d",
        "price_basis": "adjusted_ohlc",
        "source": "fixture",
    }
    if purpose:
        metadata["purpose"] = purpose
    (cache_root / f"market_data_{name}.json").write_text(json.dumps(metadata), encoding="utf-8")


def test_p73_position_carrier_and_p74_spy_authority_remain_independent(tmp_path):
    position = PositionSnapshot(
        symbol="AAPL",
        qty=2.0,
        market_value=1025.0,
        avg_entry_price=500.0,
        current_price=512.5,
        unrealized_pl=25.0,
        unrealized_plpc=0.025,
        unrealized_intraday_pl=7.5,
        unrealized_intraday_plpc=0.0075,
    )
    portfolio = PortfolioSnapshot(
        account_id="paper-account",
        status="ACTIVE",
        currency="USD",
        cash=10_000.0,
        portfolio_value=11_000.0,
        buying_power=10_000.0,
        positions=[position],
        open_orders=[],
    )
    history = {"open_positions": _open_positions_summary(portfolio)}
    [position_row] = _position_rows(history)
    assert position_row["P/L fuente"] == "alpaca_position_snapshot"
    assert position_row["P/L $"] == 25.0
    assert position_row["P/L día $"] == 7.5

    _cache(
        tmp_path,
        "broad",
        created_at="2026-07-29T13:42:39+00:00",
        open_price=739.1900024414062,
        current_price=739.5599975585938,
        requested_symbols=["AAPL", "SPY"],
    )
    _cache(
        tmp_path,
        "dedicated",
        created_at="2026-07-29T13:50:33+00:00",
        open_price=739.969970703125,
        current_price=738.6500244140625,
        requested_symbols=["SPY"],
        purpose="benchmark_open",
    )
    settings = Settings(_env_file=None, DATA_DIR=tmp_path)
    spy = load_cached_spy_open_observations(
        settings,
        now=datetime(2026, 7, 29, 16, 0, tzinfo=timezone.utc),
    )
    assert spy["status"] == "available"
    assert spy["opens"][0]["price"] == 739.969970703125
    assert spy["current"]["price"] == 738.6500244140625

    rows = build_open_to_open_rows(
        [{"session_date": "2026-07-29", "equity": 70_672.33, "observed_at": "2026-07-29T13:30:00+00:00"}],
        spy,
        current_equity=70_640.16,
        current_equity_at=datetime(2026, 7, 29, 16, 0, tzinfo=timezone.utc),
    )
    assert rows[0]["status"] == "in_progress"
    assert rows[0]["spy_pct"] < 0


def test_p75_wiring_keeps_shadow_after_active_route_and_no_portfolio_watch_polling():
    market_source = getsource(scheduler.market_cycle_job)
    helper_source = getsource(_attempt_authoritative_spy_open_capture)
    portfolio_source = getsource(scheduler.portfolio_watch_job)
    assert market_source.rfind('status="completed"') < market_source.index("_attempt_authoritative_spy_open_capture(")
    assert "capture_authoritative_spy_open_cache(" not in portfolio_source
    assert "portfolio_watch_spy_open_capture:" not in portfolio_source
    for terminal_status in ("inserted", "available", "idempotent", "recovered"):
        assert terminal_status in helper_source
    assert "market_cycle_spy_open_capture:" in helper_source
    assert "retry_on_next_market_cycle" in helper_source
    assert 'Rendimiento desde apertura: Sistema vs SPY' in getsource(web_app._render_daily_vs_spy_table)
