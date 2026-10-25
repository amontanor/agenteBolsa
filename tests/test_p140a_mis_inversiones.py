from __future__ import annotations

import sys

import pytest

from agente_bolsa.web_app import _invested_day_metric


def test_primary_pct_over_invested() -> None:
    metric = _invested_day_metric(50.0, 5000.0, equity_pct=0.0007)

    assert metric["amount"] == "$50.00"
    assert metric["primary_pct"] == "+1.00%"
    assert metric["secondary"] == "+0.07% sobre equity"
    assert metric["tone"] == "good"


def test_zero_invested_is_not_a_number() -> None:
    metric = _invested_day_metric(50.0, 0.0, equity_pct=0.0007)

    assert metric["primary_pct"] == "n/d"
    assert metric["tone"] == "neutral"


def test_missing_intraday_is_not_a_number() -> None:
    metric = _invested_day_metric(None, 5000.0, equity_pct=0.0007)

    assert metric["amount"] == "n/d"
    assert metric["primary_pct"] == "n/d"
    assert metric["tone"] == "neutral"


def test_negative_day_is_bad() -> None:
    metric = _invested_day_metric(-120.5, 5000.0, equity_pct=None)

    assert metric["primary_pct"] == "-2.41%"
    assert metric["secondary"] == "n/d sobre equity"
    assert metric["tone"] == "bad"


def test_partial_coverage_is_declared() -> None:
    metric = _invested_day_metric(10.0, 5000.0, equity_pct=0.0, known=2, total=4)

    assert metric["coverage"] == "2/4 posiciones"
    assert metric["primary_pct"] == "+0.20%"


def test_full_coverage_needs_no_warning() -> None:
    metric = _invested_day_metric(10.0, 5000.0, equity_pct=0.0, known=4, total=4)

    assert metric["coverage"] == "4/4 posiciones"


def test_investments_group_renders_strip_headless() -> None:
    from streamlit.testing.v1 import AppTest

    def _script() -> None:
        from agente_bolsa import web_app as _web_app

        _web_app._investments_group(
            invested=5000.0,
            invested_pct=0.07,
            intraday_pl=50.0,
            intraday_known=4,
            intraday_total=4,
            open_pl=120.0,
            cash=65000.0,
            today_equity_pct=0.0007,
        )

    app = AppTest.from_function(_script)
    app.run()

    assert not app.exception
    html = "".join(item.value for item in app.markdown)
    assert "Mis inversiones" in html
    assert "+1.00%" in html
    assert "+0.07% sobre equity" in html


@pytest.fixture(autouse=True)
def restore_main_after_apptest():
    """Streamlit replaces __main__; preserve the caller for Windows spawn."""
    original_main = sys.modules["__main__"]
    try:
        yield
    finally:
        sys.modules["__main__"] = original_main
