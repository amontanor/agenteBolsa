from __future__ import annotations

import sys

import pytest

from agente_bolsa import web_app

DAY_PL = "P/L día $"
OPEN_PL = "P/L $"


def test_closed_market_all_zero_is_not_zero_percent() -> None:
    metric = web_app._invested_day_metric(
        0.0, 5000.0, 0.0007, known=3, total=3, market_open=False, all_zero=True
    )

    assert metric["amount"] == "n/d"
    assert metric["primary_pct"] == "n/d"
    assert metric["secondary"] == "+0.07% sobre equity"
    assert metric["tone"] == "neutral"
    assert metric["note"] == "mercado cerrado"


def test_open_market_all_zero_keeps_a_real_zero() -> None:
    metric = web_app._invested_day_metric(
        0.0, 5000.0, 0.0007, known=3, total=3, market_open=True, all_zero=True
    )

    assert metric["primary_pct"] == "0.00%"
    assert metric["note"] is None


def test_partial_coverage_is_declared_without_touching_primary_pct() -> None:
    metric = web_app._invested_day_metric(50.0, 5000.0, 0.0007, known=2, total=4)

    assert metric["primary_pct"] == "+1.00%"
    assert metric["partial"] is True
    assert metric["coverage"] == "2/4 posiciones"


def test_complete_coverage_is_not_partial() -> None:
    metric = web_app._invested_day_metric(50.0, 5000.0, 0.0007, known=4, total=4)

    assert metric["partial"] is False


def test_dilution_note_translates_portfolio_move_into_equity() -> None:
    note = web_app._dilution_note(70000.0, 2200.0)

    assert note == "con 3.14% invertido, un 5.00% de cartera mueve el equity +0.16%"


def test_dilution_note_without_exposure_is_explicit() -> None:
    assert web_app._dilution_note(None, 2200.0) == "sin exposicion calculable"
    assert web_app._dilution_note(70000.0, 0.0) == "sin exposicion calculable"


def test_portfolio_day_result_includes_closed_sales() -> None:
    result = web_app._portfolio_day_result(
        11.0,
        39.0,
        2200.0,
        500.0,
        intraday_known=3,
        intraday_total=3,
        sell_count=1,
        realized_known=1,
    )

    assert result["amount"] == "$50.00"
    assert result["primary_pct"] == "+1.85%"
    assert result["base"] == 2700.0
    assert result["estimated"] is True
    assert result["partial"] is False
    assert result["open_text"] == "$11.00"
    assert result["realized_text"] == "$39.00"


def test_portfolio_day_result_without_sales_is_exact() -> None:
    result = web_app._portfolio_day_result(
        11.0, None, 2200.0, 0.0, intraday_known=3, intraday_total=3, sell_count=0
    )

    assert result["amount"] == "$11.00"
    assert result["primary_pct"] == "+0.50%"
    assert result["estimated"] is False
    assert result["realized_text"] == "$0.00"


def test_portfolio_day_result_closed_market_is_unavailable() -> None:
    result = web_app._portfolio_day_result(
        0.0,
        None,
        2200.0,
        0.0,
        intraday_known=3,
        intraday_total=3,
        sell_count=0,
        market_open=False,
        all_zero=True,
    )

    assert result["amount"] == "n/d"
    assert result["primary_pct"] == "n/d"
    assert result["partial"] is True


def test_portfolio_day_result_unknown_realized_is_partial() -> None:
    result = web_app._portfolio_day_result(
        10.0,
        None,
        2000.0,
        400.0,
        intraday_known=2,
        intraday_total=2,
        sell_count=2,
        realized_known=1,
        realized_unknown=1,
    )

    assert result["amount"] == "n/d"
    assert result["primary_pct"] == "n/d"
    assert result["partial"] is True
    assert result["estimated"] is True


def test_position_rows_totals_sum_the_same_rows() -> None:
    rows = [
        {"Valor": 100.0, DAY_PL: 1.0, OPEN_PL: 5.0},
        {"Valor": 200.0, DAY_PL: 2.0, OPEN_PL: -1.0},
    ]

    totals = web_app._position_rows_totals(rows)

    assert totals["positions"] == 2
    assert totals["invested"] == 300.0
    assert totals["day_pl"] == 3.0
    assert totals["day_pct"] == pytest.approx(0.01)
    assert totals["open_pl"] == 4.0
    assert totals["complete"] is True


def test_position_rows_totals_declare_missing_without_inventing_zero() -> None:
    rows = [
        {"Valor": 100.0, DAY_PL: 1.0, OPEN_PL: 5.0},
        {"Valor": 200.0, DAY_PL: None, OPEN_PL: -1.0},
    ]

    totals = web_app._position_rows_totals(rows)

    assert totals["day_pl"] == 1.0
    assert totals["day_known"] == 1
    assert totals["complete"] is False


def test_position_rows_totals_empty_is_not_zero() -> None:
    totals = web_app._position_rows_totals([])

    assert totals["invested"] is None
    assert totals["day_pl"] is None
    assert totals["day_pct"] is None
    assert totals["complete"] is False


def test_exposure_rows_skip_sessions_without_exposure() -> None:
    rows = [
        {
            "session_date": "2026-10-29",
            "exposure_pct": 0.0138,
            "exposure_basis": 2200.0,
            "status": "final",
        },
        {"session_date": "2026-10-28"},
    ]

    assert web_app._portfolio_exposure_rows(rows) == [
        {"sesion": "2026-10-29", "cartera": 0.0138, "base": 2200.0, "estado": "Final"}
    ]


def test_cumulative_window_respects_each_range_kind() -> None:
    series = [
        {"fecha": f"2026-06-{day:02d}", "acumulado": 0.001 * day} for day in range(1, 11)
    ]

    assert len(web_app._cumulative_window(series, None)) == 10
    assert [row["fecha"] for row in web_app._cumulative_window(series, 3)] == [
        "2026-06-08",
        "2026-06-09",
        "2026-06-10",
    ]
    assert web_app._cumulative_window(series, "2026-06-09")[0]["fecha"] == "2026-06-09"
    assert web_app._cumulative_window([], 7) == []


class _Store:
    def __init__(self, rows: list[dict], *, fail: bool = False) -> None:
        self.rows = rows
        self.fail = fail
        self.calls: list[dict] = []

    def performance_daily(self, **kwargs: object) -> list[dict]:
        self.calls.append(dict(kwargs))
        if self.fail:
            raise RuntimeError("database is locked")
        return self.rows


def test_cumulative_series_reads_only_persisted_pct() -> None:
    store = _Store(
        [
            {"session_date": "2026-10-29", "cumulative_pnl_pct": 0.012},
            {"session_date": "2026-10-28", "cumulative_pnl_pct": None},
        ]
    )

    assert web_app._performance_daily_cumulative(store) == [
        {"fecha": "2026-10-29", "acumulado": 0.012}
    ]
    assert store.calls == [{"limit": 0, "readonly": True}]


def test_cumulative_series_fails_open_without_series() -> None:
    assert web_app._performance_daily_cumulative(_Store([], fail=True)) == []


def test_today_caption_no_longer_calls_equity_portfolio_pl() -> None:
    display = web_app._today_pl_display(38.42, 5246.0, 0.0005)

    assert display["period_caption"] == "equity total · cierre XNYS previo → ahora"
    assert "P/L diario de cartera" not in display["period_caption"]


def test_investments_group_shows_portfolio_result_first_with_realized() -> None:
    from streamlit.testing.v1 import AppTest

    def _script() -> None:
        from agente_bolsa import web_app as _web_app

        _web_app._investments_group(
            invested=5000.0,
            invested_pct=0.07,
            intraday_pl=11.0,
            intraday_known=3,
            intraday_total=3,
            open_pl=120.0,
            cash=65000.0,
            today_equity_pct=0.0007,
            market_open=True,
            realized_pl=39.0,
            realized_known=1,
            sell_count=1,
        )

    app = AppTest.from_function(_script)
    app.run()

    assert not app.exception
    html = "".join(item.value for item in app.markdown)
    assert "Resultado de la cartera hoy" in html
    assert "+0.22%" in html
    assert "realizadas hoy $39.00" in html


def test_investments_group_closed_market_never_paints_zero_percent() -> None:
    from streamlit.testing.v1 import AppTest

    def _script() -> None:
        from agente_bolsa import web_app as _web_app

        _web_app._investments_group(
            invested=5000.0,
            invested_pct=0.07,
            intraday_pl=0.0,
            intraday_known=3,
            intraday_total=3,
            open_pl=120.0,
            cash=65000.0,
            today_equity_pct=0.0,
            market_open=False,
            intraday_all_zero=True,
        )

    app = AppTest.from_function(_script)
    app.run()

    assert not app.exception
    html = "".join(item.value for item in app.markdown)
    assert "mercado cerrado" in html
    assert "n/d n/d" in html


@pytest.fixture(autouse=True)
def restore_main_after_apptest():
    """Streamlit replaces __main__; preserve the caller for Windows spawn."""

    original_main = sys.modules["__main__"]
    try:
        yield
    finally:
        sys.modules["__main__"] = original_main
