from __future__ import annotations

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
