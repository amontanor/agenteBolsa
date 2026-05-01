from agente_bolsa.tools.costs import TransactionCostModel


def test_round_trip_cost_model():
    costs = TransactionCostModel(commission_bps=3, slippage_bps=5)

    assert costs.round_trip_bps == 16
    assert costs.one_way_cost(10_000) == 8
    assert costs.round_trip_cost(10_000) == 16
    assert costs.net_return(0.02) == 0.0184
