from __future__ import annotations

from copy import deepcopy

from agente_bolsa.web_app import (
    _account_group,
    _sales_since_open_rows,
)


def test_account_group_exposes_position_intraday_amount_and_coverage(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr("agente_bolsa.web_app.st.markdown", lambda body, **_kwargs: captured.append(body))

    _account_group(
        initial_equity=1000,
        current_equity=1010,
        cash=900,
        exposure=100,
        exposure_pct=0.1,
        total_pl=10,
        total_pct=0.01,
        today_pl=5,
        today_pct=0.005,
        positions_count=3,
        orders_count=0,
        position_intraday={"amount": 4.25, "known": 2, "total": 3, "status": "partial"},
    )

    rendered = "".join(captured)
    assert "Ganancia/pérdida de la cartera actual hoy" in rendered
    assert "$4.25" in rendered
    assert "2/3 posiciones" in rendered
    assert "%" not in rendered.split("Ganancia/pérdida de la cartera actual hoy", 1)[1].split("Posiciones", 1)[0]


def test_sales_since_open_keeps_one_row_per_sell_fill_and_missing_realized_pl():
    history = {
        "trades": [
            {"time": "2026-08-06T13:29:59+00:00", "side": "sell", "symbol": "OLD", "notional": 10, "realized_pl": 1},
            {"time": "2026-08-06T13:30:00+00:00", "side": "sell", "symbol": "AAA", "notional": 120.5, "realized_pl": None},
            {"time": "2026-08-06T13:31:00+00:00", "side": "sell", "symbol": "AAA", "notional": 80, "realized_pl": -2.5},
            {"time": "2026-08-06T13:32:00+00:00", "side": "buy", "symbol": "BUY", "notional": 30, "realized_pl": None},
        ]
    }
    opening_context = {"account_current": {"system_start_at": "2026-08-06T13:30:00+00:00"}}

    result = _sales_since_open_rows(history, opening_context)

    assert result["status"] == "available"
    assert [row["symbol"] for row in result["rows"]] == ["AAA", "AAA"]
    assert result["rows"][0]["realized_pl"] is None
    assert result["rows"][1]["realized_pl"] == -2.5


def test_sales_since_open_requires_exact_opening_authority():
    result = _sales_since_open_rows(
        {"trades": [{"side": "sell", "symbol": "AAA", "notional": 1}]},
        {"account_current": {}},
    )

    assert result == {"status": "unavailable", "reason": "opening_unavailable", "rows": []}


def test_sales_since_open_excludes_missing_or_unparseable_fill_time():
    history = {
        "trades": [
            {"side": "sell", "symbol": "MISSING", "notional": 1, "realized_pl": 2},
            {"time": "not-a-timestamp", "side": "sell", "symbol": "BAD", "notional": 2},
        ]
    }

    result = _sales_since_open_rows(
        history,
        {"account_current": {"system_start_at": "2026-08-06T13:30:00+00:00"}},
    )

    assert result["status"] == "available"
    assert result["rows"] == []


def test_sales_since_open_does_not_mutate_history():
    history = {
        "trades": [
            {"time": "2026-08-06T13:30:00+00:00", "side": "sell", "symbol": "AAA", "notional": 10}
        ]
    }
    original = deepcopy(history)

    _sales_since_open_rows(
        history,
        {"account_current": {"system_start_at": "2026-08-06T13:30:00+00:00"}},
    )

    assert history == original


def test_sales_since_open_normalizes_symbol_and_uses_stable_time_order():
    history = {
        "trades": [
            {"time": "2026-08-06T13:32:00+00:00", "side": "sell", "symbol": "bbb", "notional": 2},
            {"time": "2026-08-06T13:31:00+00:00", "side": "sell", "symbol": "aaa", "notional": 1},
        ]
    }

    result = _sales_since_open_rows(
        history,
        {"account_current": {"system_start_at": "2026-08-06T13:30:00+00:00"}},
    )

    assert [(row["symbol"], row["time"]) for row in result["rows"]] == [
        ("AAA", "2026-08-06T13:31:00+00:00"),
        ("BBB", "2026-08-06T13:32:00+00:00"),
    ]


def test_sales_since_open_accepts_aware_datetime_equivalents():
    result = _sales_since_open_rows(
        {"trades": [{"time": "2026-08-06T15:30:00+02:00", "side": "sell", "symbol": "AAA", "notional": 1}]},
        {"account_current": {"system_start_at": "2026-08-06T13:30:00+00:00"}},
    )

    assert result["rows"][0]["symbol"] == "AAA"


def test_sales_since_open_returns_no_rows_for_buy_only_history():
    result = _sales_since_open_rows(
        {"trades": [{"time": "2026-08-06T13:31:00+00:00", "side": "buy", "symbol": "AAA", "notional": 1}]},
        {"account_current": {"system_start_at": "2026-08-06T13:30:00+00:00"}},
    )

    assert result["status"] == "available"
    assert result["rows"] == []
