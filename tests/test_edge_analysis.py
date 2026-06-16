from agente_bolsa.tools.edge_analysis import summarize_by_group


def test_summarize_by_group_computes_expectancy_hit_rate_and_profit_factor():
    rows = [
        {"group": "confirmed_pattern", "signal_date": "2026-06-10", "outcome": {"return_1d": 0.02, "return_3d": 0.03, "return_5d": 0.05, "return_10d": 0.04}},
        {"group": "confirmed_pattern", "signal_date": "2026-06-11", "outcome": {"return_1d": -0.01, "return_3d": 0.00, "return_5d": -0.02, "return_10d": -0.01}},
    ]

    summary = summarize_by_group(rows, {}, key_fn=lambda row: row.get("group"))

    assert len(summary) == 1
    item = summary[0]
    assert item["key"] == "confirmed_pattern"
    assert item["n"] == 2
    assert item["expectancy_5d"] == 0.015
    assert item["hit_rate_5d"] == 0.5
    assert item["profit_factor_5d"] == 2.5
