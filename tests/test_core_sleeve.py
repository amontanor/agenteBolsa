from __future__ import annotations

import json

import pandas as pd

from agente_bolsa.config import Settings
from agente_bolsa.models import PortfolioSnapshot, PositionSnapshot
from agente_bolsa.research.overlay_shadow import build_overlay_shadow_observation
from agente_bolsa.strategies import core_sleeve
from agente_bolsa.strategies.core_sleeve import (
    CoreSleeveConfig,
    calculate_core_sleeve_decision,
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
