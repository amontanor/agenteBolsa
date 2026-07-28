from types import SimpleNamespace

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools import telegram_trade_notifications as telegram


def _store(tmp_path):
    settings = Settings(DATA_DIR=tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def _save_order(store, *, order_id, plan_id, side, price, source_plan_id=None):
    checks = {"source_plan_id": source_plan_id} if source_plan_id else {}
    store.save_broker_order(
        broker_order_id=order_id,
        plan_id=plan_id,
        cycle_id="cycle-1",
        symbol="AAPL",
        side=side,
        status="filled",
        payload={
            "plan": {
                "plan_id": plan_id,
                "payload": {"risk_decision": {"checks": checks}},
            },
            "broker_order_reconciled": {
                "status": "filled",
                "filled_qty": 2,
                "filled_avg_price": price,
                "filled_at": "2026-07-28T14:00:00+00:00",
            },
        },
    )


def _change(*, order_id, plan_id, side, price):
    return {
        "broker_order_id": order_id,
        "plan_id": plan_id,
        "cycle_id": "cycle-1",
        "symbol": "AAPL",
        "side": side,
        "old": "pending_new",
        "new": "filled",
        "fill": {
            "filled_qty": 2,
            "filled_avg_price": price,
            "filled_at": "2026-07-28T14:00:00+00:00",
        },
    }


def test_build_buy_fill_uses_actual_fill_price(tmp_path):
    store = _store(tmp_path)
    _save_order(store, order_id="buy-1", plan_id="plan-buy", side="buy", price=101.25)

    payload = telegram.build_trade_fill(
        store,
        _change(order_id="buy-1", plan_id="plan-buy", side="buy", price=101.25),
    )

    assert payload["entry_price"] == 101.25
    assert payload["entry_link_status"] == "self_fill"
    assert "Entrada real: $101.2500" in telegram.format_trade_fill(payload)


def test_build_sell_fill_uses_exact_source_plan_and_calculates_gross_pl(tmp_path):
    store = _store(tmp_path)
    _save_order(store, order_id="buy-1", plan_id="plan-buy", side="buy", price=100)
    _save_order(
        store,
        order_id="sell-1",
        plan_id="plan-sell",
        side="sell",
        price=105,
        source_plan_id="plan-buy",
    )

    payload = telegram.build_trade_fill(
        store,
        _change(order_id="sell-1", plan_id="plan-sell", side="sell", price=105),
    )

    assert payload["entry_link_status"] == "exact_source_plan"
    assert payload["entry_price"] == 100
    assert payload["gross_pl"] == 10
    assert payload["gross_pl_pct"] == pytest.approx(0.05)
    assert "P/L bruto: +10.00 USD (+5.00%)" in telegram.format_trade_fill(payload)


def test_sell_never_guesses_entry_from_symbol_when_source_is_missing(tmp_path):
    store = _store(tmp_path)
    _save_order(store, order_id="buy-1", plan_id="plan-buy", side="buy", price=100)
    _save_order(store, order_id="sell-1", plan_id="plan-sell", side="sell", price=95)

    payload = telegram.build_trade_fill(
        store,
        _change(order_id="sell-1", plan_id="plan-sell", side="sell", price=95),
    )

    assert payload["entry_link_status"] == "unavailable"
    assert payload["entry_price"] is None
    assert payload["gross_pl"] is None
    assert "Entrada real: n/d" in telegram.format_trade_fill(payload)


def test_publish_is_idempotent_and_fail_open(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _save_order(store, order_id="buy-1", plan_id="plan-buy", side="buy", price=101.25)
    change = _change(order_id="buy-1", plan_id="plan-buy", side="buy", price=101.25)
    settings = SimpleNamespace(
        telegram_trade_notifications_enabled=True,
        telegram_bot_token="secret",
        telegram_daily_summary_chat_id="-1",
        telegram_timeout_seconds=15,
    )
    calls = []
    monkeypatch.setattr(
        telegram,
        "send_telegram_message",
        lambda **kwargs: calls.append(kwargs) or {"ok": True, "message_id": 7},
    )

    first = telegram.publish_trade_fill_notifications(settings, store, [change])
    second = telegram.publish_trade_fill_notifications(settings, store, [change])

    assert first["sent"] == 1
    assert second["sent"] == 0
    assert len(calls) == 1

    _save_order(store, order_id="buy-2", plan_id="plan-buy-2", side="buy", price=102)
    monkeypatch.setattr(
        telegram,
        "send_telegram_message",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("network and secret must not escape")),
    )
    failed = telegram.publish_trade_fill_notifications(
        settings,
        store,
        [_change(order_id="buy-2", plan_id="plan-buy-2", side="buy", price=102)],
    )
    assert failed == {
        "status": "noop",
        "sent": 0,
        "errors": [{"broker_order_id": "buy-2", "reason": "telegram_trade_fill_failed:OSError"}],
    }
