"""Tests del modelo de costes de trading."""
from __future__ import annotations

from agente_bolsa.tools.trade_costs import net_return, round_trip_cost_fraction


def test_default_round_trip_is_15bps():
    # 2*0 + 2*5 + 5 = 15 bps = 0.0015
    assert round_trip_cost_fraction() == 0.0015


def test_net_subtracts_cost():
    assert abs(net_return(0.0032) - 0.0017) < 1e-9


def test_net_can_turn_marginal_edge_negative():
    # Un edge bruto pequeño se vuelve negativo tras costes.
    assert net_return(0.0010) < 0


def test_cost_scales_with_inputs():
    base = round_trip_cost_fraction()
    more = round_trip_cost_fraction(slippage_bps=10.0, spread_bps=10.0)
    assert more > base


def test_cost_never_negative():
    assert round_trip_cost_fraction(commission_bps=0, slippage_bps=0, spread_bps=0) == 0.0
