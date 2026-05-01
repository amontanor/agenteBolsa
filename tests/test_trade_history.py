from agente_bolsa.tools.trade_history import (
    _attach_risk_levels,
    _current_statistics,
    _daily_groups,
    _filter_fills_from_date,
    realized_pl_from_fills,
)


def test_realized_pl_from_fills_uses_fifo_lots():
    fills = [
        {
            "transaction_time": "2026-04-27T10:00:00Z",
            "symbol": "AMD",
            "side": "buy",
            "qty": "10",
            "price": "100",
            "order_id": "buy-1",
        },
        {
            "transaction_time": "2026-04-27T10:05:00Z",
            "symbol": "AMD",
            "side": "buy",
            "qty": "5",
            "price": "110",
            "order_id": "buy-2",
        },
        {
            "transaction_time": "2026-04-27T10:10:00Z",
            "symbol": "AMD",
            "side": "sell",
            "qty": "12",
            "price": "120",
            "order_id": "sell-1",
        },
    ]

    trades, summary = realized_pl_from_fills(fills)

    sell = next(item for item in trades if item["side"] == "sell")
    assert sell["realized_pl"] == 220.0
    assert sell["realized_plpc"] == 0.1803
    assert summary["fills"] == 3
    assert summary["buy_notional"] == 1550.0
    assert summary["sell_notional"] == 1440.0
    assert summary["realized_pl"] == 220.0
    assert summary["realized_trades"] == 1
    assert summary["unknown_realized_trades"] == 0
    assert [item["side"] for item in trades] == ["buy", "buy", "sell"]


def test_realized_pl_marks_sell_unknown_without_prior_buy():
    trades, summary = realized_pl_from_fills(
        [
            {
                "transaction_time": "2026-04-27T10:10:00Z",
                "symbol": "AMD",
                "side": "sell",
                "qty": "12",
                "price": "120",
                "order_id": "sell-1",
            }
        ]
    )

    assert trades[0]["realized_pl"] is None
    assert trades[0]["realized_pl_known"] is False
    assert summary["realized_pl"] == 0.0
    assert summary["realized_trades"] == 0
    assert summary["unknown_realized_trades"] == 1


def test_attach_risk_levels_to_trades_and_positions():
    trades = [{"symbol": "AMD"}]
    positions = [{"symbol": "AMD", "unrealized_pl": 5.0}]
    risk = {"AMD": {"entry_price": 100.0, "stop_loss": 95.0, "take_profit": 110.0}}

    _attach_risk_levels(trades, positions, risk)

    assert trades[0]["stop_loss"] == 95.0
    assert trades[0]["take_profit"] == 110.0
    assert positions[0]["stop_loss"] == 95.0
    assert positions[0]["take_profit"] == 110.0


def test_daily_groups_include_today_open_pl():
    days = _daily_groups(
        [
            {
                "date": "2026-04-27",
                "time": "2026-04-27T10:00:00Z",
                "symbol": "AMD",
                "side": "buy",
                "notional": 1000.0,
                "realized_pl": None,
            },
            {
                "date": "2026-04-27",
                "time": "2026-04-27T11:00:00Z",
                "symbol": "AMD",
                "side": "sell",
                "notional": 500.0,
                "realized_pl": 25.0,
            },
        ],
        [{"symbol": "AMD", "unrealized_pl": 10.0}],
        today="2026-04-27",
        portfolio_value=2000.0,
    )

    assert days[0]["date"] == "2026-04-27"
    assert days[0]["buy_notional"] == 1000.0
    assert days[0]["sell_notional"] == 500.0
    assert days[0]["realized_pl"] == 25.0
    assert days[0]["realized_plpc"] == 0.05
    assert days[0]["open_unrealized_pl"] == 10.0
    assert days[0]["open_unrealized_plpc"] == 0.005


def test_filter_fills_from_date_removes_old_account_activity():
    fills = [
        {"transaction_time": "2026-02-02T00:00:00Z", "symbol": "DOGE/USD"},
        {"transaction_time": "2026-04-27T10:00:00Z", "symbol": "AMD"},
    ]

    filtered = _filter_fills_from_date(fills, "2026-04-01", "Europe/Madrid")

    assert len(filtered) == 1
    assert filtered[0]["symbol"] == "AMD"


def test_current_statistics_tracks_biggest_gain_and_loss():
    stats = _current_statistics(
        {
            "equity": 10000.0,
            "cash": 4000.0,
            "buy_notional": 2000.0,
            "sell_notional": 1500.0,
            "realized_pl": 100.0,
            "unrealized_pl": -25.0,
            "open_positions": 2,
        },
        [
            {"symbol": "AMD", "realized_pl": 100.0, "realized_plpc": 0.1, "time": "2026-04-27T10:00:00Z"},
            {"symbol": "AMZN", "realized_pl": -50.0, "realized_plpc": -0.05, "time": "2026-04-27T11:00:00Z"},
        ],
        [
            {"symbol": "NVDA", "market_value": 3000.0, "unrealized_pl": 20.0, "unrealized_plpc": 0.01},
            {"symbol": "VRT", "market_value": 3000.0, "unrealized_pl": -45.0, "unrealized_plpc": -0.02},
        ],
    )

    assert stats["cash_pct"] == 0.4
    assert stats["exposure"] == 6000.0
    assert stats["total_pl"] == 75.0
    assert stats["biggest_gain"]["symbol"] == "AMD"
    assert stats["biggest_loss"]["symbol"] == "AMZN"
