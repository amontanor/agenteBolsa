"""Tests de realismo de ejecucion (T5.5)."""

from agente_bolsa.tools.cost_calibration import (
    apply_synthetic_slippage,
    calibrate_cost_bps,
    gap_exceeds_cap,
    limit_price_with_gap_cap,
)


def test_synthetic_slippage_makes_net_below_gross():
    gross = 0.05
    net = apply_synthetic_slippage(gross, slippage_bps=10)
    assert net < gross
    assert net == round(0.05 - 0.002, 6)  # 2x10bps


def test_slippage_includes_atr_half_spread():
    net = apply_synthetic_slippage(0.05, slippage_bps=10, atr_pct=0.02)
    assert net == round(0.05 - 0.002 - 0.01, 6)


def test_limit_price_and_gap_cap():
    assert limit_price_with_gap_cap(100.0, max_gap_pct=0.015) == 101.5
    assert gap_exceeds_cap(102.0, 100.0, max_gap_pct=0.015) is True   # +2% > 1.5%
    assert gap_exceeds_cap(101.0, 100.0, max_gap_pct=0.015) is False  # +1% < 1.5%


def test_calibrate_cost_bps_from_fills():
    fills = [
        {"signal_price": 100.0, "fill_price": 100.1, "side": "buy"},   # +10 bps adverso
        {"signal_price": 100.0, "fill_price": 100.2, "side": "buy"},   # +20 bps
        {"signal_price": 50.0, "fill_price": 50.05, "side": "buy"},    # +10 bps
    ]
    result = calibrate_cost_bps(fills)
    assert result["samples"] == 3
    assert result["median_bps"] == 10.0
