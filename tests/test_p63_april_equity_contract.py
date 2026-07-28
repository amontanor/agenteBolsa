from inspect import getsource

import pandas as pd

import agente_bolsa.web_app as web_app
from agente_bolsa.web_app import (
    DEFAULT_START_DATE,
    PORTFOLIO_CHART_START_DATE,
    PORTFOLIO_HISTORY_PERIOD,
    _portfolio_chart_visible_summary,
    _portfolio_value_series_from_alpaca,
)


def _descending_equity_history() -> dict[str, list[object]]:
    return {
        "timestamp": [
            "2026-04-01T00:00:00Z",
            "2026-04-28T00:00:00Z",
            "2026-07-28T00:00:00Z",
        ],
        "equity": [71550.0, 71000.0, 70600.0],
    }


def test_p63_reproduces_april_baseline_exclusion_on_base():
    df = _portfolio_value_series_from_alpaca(
        _descending_equity_history(),
        current_equity=70588.17,
    )

    assert DEFAULT_START_DATE == "2026-04-01"
    assert PORTFOLIO_CHART_START_DATE == DEFAULT_START_DATE
    assert df["fecha"].iloc[0] == "2026-04-01"
    assert _portfolio_chart_visible_summary(df)["start_value"] == 71550.0


def test_portfolio_history_request_is_single_and_covers_april_cutoff():
    assert PORTFOLIO_HISTORY_PERIOD == "all"
    source = getsource(web_app.page_dashboard)
    assert source.count("alpaca_portfolio_history(") == 1
    assert "start_date=DEFAULT_START_DATE" in source


def test_account_header_uses_equity_summary_not_trade_history_total_pl():
    source = getsource(web_app.page_dashboard)

    assert "full_equity_summary" in source
    assert 'stats.get("total_pl")' not in source
