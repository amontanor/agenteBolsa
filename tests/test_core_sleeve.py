from __future__ import annotations

import json

import pandas as pd

from agente_bolsa.config import Settings
from agente_bolsa.market_calendar import MarketStatus
from agente_bolsa.models import PortfolioSnapshot, PositionSnapshot
from agente_bolsa.research.overlay_shadow import build_overlay_shadow_observation
from agente_bolsa.strategies import core_sleeve
from agente_bolsa.strategies.core_sleeve import (
    CoreSleeveConfig,
    calculate_core_sleeve_decision,
    core_sleeve_client_order_id,
    load_core_sleeve_config,
    run_core_sleeve_once,
)
from agente_bolsa.tools.strategy_edge_backtest import exposure_vol_target


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        DATA_DIR=tmp_path,
        DATABASE_PATH=tmp_path / "state" / "test.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "logs" / "agents",
        ALLOW_LIVE_TRADING=False,
        TRADING_MODE="paper",
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )


def _portfolio(*, equity: float = 100_000, spy_value: float = 0.0, spy_price: float = 500.0) -> PortfolioSnapshot:
    positions = []
    if spy_value > 0:
        positions.append(
            PositionSnapshot(
                symbol="SPY",
                qty=spy_value / spy_price,
                market_value=spy_value,
                avg_entry_price=spy_price,
                current_price=spy_price,
                unrealized_pl=0.0,
                unrealized_plpc=0.0,
                side="long",
            )
        )
    return PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=equity - spy_value,
        portfolio_value=equity,
        buying_power=equity - spy_value,
        positions=positions,
        open_orders=[],
    )


def test_core_sleeve_config_defaults_are_created(tmp_path):
    path = tmp_path / "config" / "core_sleeve.json"

    config = load_core_sleeve_config(path)

    assert path.exists()
    assert config == CoreSleeveConfig()
    assert json.loads(path.read_text(encoding="utf-8"))["enabled"] is False


def test_core_sleeve_sizing_uses_equity_sleeve_and_vt12():
    decision = calculate_core_sleeve_decision(
        portfolio=_portfolio(equity=100_000, spy_value=10_000),
        config=CoreSleeveConfig(enabled=True, dry_run=True, sleeve_fraction=0.30, rebalance_band_pp=5, target_vol=0.12),
        exposure=0.50,
        price=500,
        data_date="2026-07-02",
    )

    assert decision.target_notional == 15_000
    assert decision.current_notional == 10_000
    assert decision.rebalance_band_notional == 1_500
    assert decision.order is not None
    assert decision.order["side"] == "buy"
    assert decision.order["notional"] == 5_000


def test_core_sleeve_deadband_does_not_trade_inside_band():
    decision = calculate_core_sleeve_decision(
        portfolio=_portfolio(equity=100_000, spy_value=14_000),
        config=CoreSleeveConfig(enabled=True, dry_run=True, sleeve_fraction=0.30, rebalance_band_pp=5, target_vol=0.12),
        exposure=0.50,
        price=500,
        data_date="2026-07-02",
    )

    assert decision.order is None
    assert decision.reason == "within_rebalance_band"


def test_core_sleeve_flag_off_is_noop_without_portfolio_or_broker(monkeypatch, tmp_path):
    monkeypatch.setattr(core_sleeve, "get_settings", lambda: _settings(tmp_path))

    def fail_portfolio():
        raise AssertionError("portfolio loader must not run when disabled")

    result = run_core_sleeve_once(
        config_path=tmp_path / "config" / "core_sleeve.json",
        log_dir=tmp_path / "logs",
        overlay_runner=lambda: {"observation": {"data_date": "2026-07-02", "price": 500, "target_exposures": {"vol_target_12pct": 0.5}}},
        portfolio_loader=fail_portfolio,
    )

    assert result["status"] == "disabled"


def test_core_sleeve_dry_run_does_not_call_broker_submitter(monkeypatch, tmp_path):
    monkeypatch.setattr(core_sleeve, "get_settings", lambda: _settings(tmp_path))
    config_path = tmp_path / "config" / "core_sleeve.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps({"enabled": True, "dry_run": True, "sleeve_fraction": 0.30, "rebalance_band_pp": 5, "target_vol": 0.12}),
        encoding="utf-8",
    )

    def fail_submitter(*args, **kwargs):
        raise AssertionError("dry-run must not submit broker orders")

    result = run_core_sleeve_once(
        config_path=config_path,
        log_dir=tmp_path / "core_sleeve",
        overlay_runner=lambda: {"observation": {"data_date": "2026-07-02", "price": 500, "target_exposures": {"vol_target_12pct": 0.5}}},
        portfolio_loader=lambda: _portfolio(equity=100_000, spy_value=0),
        order_submitter=fail_submitter,
    )

    assert result["status"] == "would_submit"
    assert (tmp_path / "core_sleeve" / "core_sleeve_log.jsonl").exists()


def test_core_sleeve_second_run_after_submit_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setattr(core_sleeve, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(core_sleeve, "MarketCalendar", _fake_market_calendar(is_open=True))
    config_path = tmp_path / "config" / "core_sleeve.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps({"enabled": True, "dry_run": False, "sleeve_fraction": 0.30, "rebalance_band_pp": 5, "target_vol": 0.12}),
        encoding="utf-8",
    )
    submitted: list[dict[str, object]] = []

    def submitter(_settings, order, *, client_order_id):
        submitted.append({"order": order, "client_order_id": client_order_id})
        return {"id": "paper-1", "client_order_id": client_order_id}

    kwargs = {
        "config_path": config_path,
        "log_dir": tmp_path / "core_sleeve",
        "overlay_runner": lambda: {"observation": {"data_date": "2026-07-02", "price": 500, "target_exposures": {"vol_target_12pct": 0.5}}},
        "portfolio_loader": lambda: _portfolio(equity=100_000, spy_value=0),
        "order_submitter": submitter,
    }

    first = run_core_sleeve_once(**kwargs)
    second = run_core_sleeve_once(**kwargs)

    assert first["status"] == "submitted"
    assert second["status"] == "no_order"
    assert second["decision"]["reason"] == "already_rebalanced_today"
    assert len(submitted) == 1
    assert submitted[0]["client_order_id"] == "core-sleeve-20260702"
    assert core_sleeve_client_order_id("2026-07-02") == core_sleeve_client_order_id("2026-07-02")


def test_core_sleeve_max_order_notional_caps_excessive_delta():
    decision = calculate_core_sleeve_decision(
        portfolio=_portfolio(equity=1_000_000, spy_value=0),
        config=CoreSleeveConfig(enabled=True, dry_run=True, sleeve_fraction=0.30, rebalance_band_pp=1, target_vol=0.12),
        exposure=1.0,
        price=500,
        data_date="2026-07-02",
        max_order_notional=12_345,
    )

    assert decision.max_sleeve_notional == 300_000
    assert decision.order is not None
    assert decision.order["notional"] == 12_345
    assert decision.order["notional"] <= decision.max_sleeve_notional


def test_core_sleeve_market_closed_never_submits(monkeypatch, tmp_path):
    monkeypatch.setattr(core_sleeve, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(core_sleeve, "MarketCalendar", _fake_market_calendar(is_open=False))
    config_path = tmp_path / "config" / "core_sleeve.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps({"enabled": True, "dry_run": False, "sleeve_fraction": 0.30, "rebalance_band_pp": 5, "target_vol": 0.12}),
        encoding="utf-8",
    )

    def fail_submitter(*args, **kwargs):
        raise AssertionError("market-closed runs must not submit broker orders")

    result = run_core_sleeve_once(
        config_path=config_path,
        log_dir=tmp_path / "core_sleeve",
        overlay_runner=lambda: {"observation": {"data_date": "2026-07-02", "price": 500, "target_exposures": {"vol_target_12pct": 0.5}}},
        portfolio_loader=lambda: _portfolio(equity=100_000, spy_value=0),
        order_submitter=fail_submitter,
    )

    assert result["status"] == "market_closed"
    assert result["ok"] is False


def test_core_sleeve_missing_equity_or_price_has_no_order():
    missing_equity = calculate_core_sleeve_decision(
        portfolio=_portfolio(equity=0, spy_value=0),
        config=CoreSleeveConfig(enabled=True, dry_run=True, sleeve_fraction=0.30, rebalance_band_pp=5, target_vol=0.12),
        exposure=0.5,
        price=500,
        data_date="2026-07-02",
    )
    missing_price = calculate_core_sleeve_decision(
        portfolio=_portfolio(equity=100_000, spy_value=0),
        config=CoreSleeveConfig(enabled=True, dry_run=True, sleeve_fraction=0.30, rebalance_band_pp=5, target_vol=0.12),
        exposure=0.5,
        price=0,
        data_date="2026-07-02",
    )

    assert missing_equity.order is None
    assert missing_equity.reason == "missing_equity"
    assert missing_price.order is None
    assert missing_price.reason == "missing_price"


def test_core_sleeve_preview_shows_order_without_submit(monkeypatch, tmp_path):
    monkeypatch.setattr(core_sleeve, "get_settings", lambda: _settings(tmp_path))
    config_path = tmp_path / "config" / "core_sleeve.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps({"enabled": True, "dry_run": False, "sleeve_fraction": 0.30, "rebalance_band_pp": 5, "target_vol": 0.12}),
        encoding="utf-8",
    )

    def fail_submitter(*args, **kwargs):
        raise AssertionError("preview must not submit broker orders")

    result = run_core_sleeve_once(
        config_path=config_path,
        log_dir=tmp_path / "core_sleeve",
        overlay_runner=lambda: {"observation": {"data_date": "2026-07-02", "price": 500, "target_exposures": {"vol_target_12pct": 0.5}}},
        portfolio_loader=lambda: _portfolio(equity=100_000, spy_value=0),
        order_submitter=fail_submitter,
        preview=True,
    )

    assert result["status"] == "preview"
    assert result["decision"]["order"]["side"] == "buy"
    assert result["decision"]["order"]["notional"] == 15_000


def test_core_sleeve_never_shorts_or_exceeds_sleeve():
    sell = calculate_core_sleeve_decision(
        portfolio=_portfolio(equity=100_000, spy_value=40_000),
        config=CoreSleeveConfig(enabled=True, dry_run=True, sleeve_fraction=0.30, rebalance_band_pp=5, target_vol=0.12),
        exposure=0.0,
        price=500,
        data_date="2026-07-02",
    )
    buy = calculate_core_sleeve_decision(
        portfolio=_portfolio(equity=100_000, spy_value=0),
        config=CoreSleeveConfig(enabled=True, dry_run=True, sleeve_fraction=0.30, rebalance_band_pp=5, target_vol=0.12),
        exposure=2.0,
        price=500,
        data_date="2026-07-02",
    )

    assert sell.order is not None
    assert sell.order["side"] == "sell"
    assert sell.order["notional"] == 40_000
    assert buy.target_notional == 30_000
    assert buy.order is not None
    assert buy.order["notional"] == 30_000


def test_core_sleeve_exposure_matches_overlay_motor():
    index = pd.bdate_range("2025-01-02", periods=260)
    close = pd.Series([500 + idx * 0.4 + ((idx % 5) - 2) for idx in range(len(index))], index=index)
    observation = build_overlay_shadow_observation(close)
    expected = round(float(exposure_vol_target(close, target_vol=0.12).iloc[-1]), 6)

    decision = calculate_core_sleeve_decision(
        portfolio=_portfolio(equity=100_000, spy_value=0),
        config=CoreSleeveConfig(enabled=True, dry_run=True, sleeve_fraction=0.30, rebalance_band_pp=5, target_vol=0.12),
        exposure=observation["target_exposures"]["vol_target_12pct"],
        price=observation["price"],
        data_date=observation["data_date"],
    )

    assert decision.exposure == expected


def _fake_market_calendar(*, is_open: bool):
    class FakeMarketCalendar:
        def __init__(self, *args, **kwargs):
            pass

        def status(self):
            return MarketStatus(
                is_open=is_open,
                now_utc="2026-07-02T20:00:00+00:00",
                now_local="2026-07-02T22:00:00+02:00",
                now_market="2026-07-02T16:00:00-04:00",
                calendar="XNYS-test",
                session_date="2026-07-02" if is_open else None,
                market_open="2026-07-02T15:30:00+02:00" if is_open else None,
                market_close="2026-07-02T22:00:00+02:00" if is_open else None,
                next_open=None,
                next_close=None,
                reason="test",
            )

    return FakeMarketCalendar
