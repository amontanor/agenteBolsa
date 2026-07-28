from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agente_bolsa.models import PortfolioSnapshot, PositionSnapshot
from agente_bolsa.tools import telegram_daily_summary as telegram


def _portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=8_000,
        portfolio_value=10_000,
        buying_power=16_000,
        positions=[
            PositionSnapshot(
                symbol="AAA",
                qty=10,
                market_value=1_000,
                avg_entry_price=90,
                current_price=100,
                unrealized_pl=100,
                unrealized_plpc=0.1111,
                unrealized_intraday_pl=25,
                unrealized_intraday_plpc=0.025,
            ),
            PositionSnapshot(
                symbol="BBB",
                qty=5,
                market_value=1_000,
                avg_entry_price=210,
                current_price=200,
                unrealized_pl=-50,
                unrealized_plpc=-0.0476,
                unrealized_intraday_pl=-10,
                unrealized_intraday_plpc=-0.01,
            ),
        ],
        open_orders=[],
    )


def test_build_and_format_daily_summary_keeps_denominators_separate():
    payload = telegram.build_daily_summary(
        session_date="2026-07-28",
        performance={"pnl_pct": 0.0027, "spy_pct": 0.005, "equity": 10_000},
        portfolio=_portfolio(),
    )

    assert payload["account_daily_return"] == pytest.approx(0.0027)
    assert payload["spy_daily_return"] == pytest.approx(0.005)
    assert payload["open_total_pl"] == pytest.approx(50)
    assert payload["open_today_pl"] == pytest.approx(15)
    text = telegram.format_daily_summary(payload)
    assert "variación diaria de equity): +0.27%" in text
    assert "SP500: +0.50%" in text
    assert "AAA: total +100.00 USD (+11.11%); hoy +25.00 USD (+2.50%)" in text


def test_missing_intraday_values_are_unavailable_not_zero():
    position = PositionSnapshot(
        symbol="AAA",
        qty=1,
        market_value=100,
        avg_entry_price=100,
        current_price=100,
        unrealized_pl=0,
        unrealized_plpc=0,
    )
    portfolio = PortfolioSnapshot("paper", "ACTIVE", "USD", 0, 100, 0, [position], [])

    payload = telegram.build_daily_summary(
        session_date="2026-07-28",
        performance=None,
        portfolio=portfolio,
    )

    assert payload["account_daily_return"] is None
    assert payload["open_today_pl"] is None
    assert "P/L abierto hoy: n/d" in telegram.format_daily_summary(payload)


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps({"ok": True, "result": {"message_id": 42}}).encode()


def test_sender_posts_json_without_putting_token_in_body():
    captured = {}

    def opener(request, *, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return _Response()

    result = telegram.send_telegram_message(
        token="secret-token",
        chat_id="-100123",
        text="hola",
        timeout_seconds=7,
        opener=opener,
    )

    assert result == {"ok": True, "message_id": 42}
    assert captured["body"] == {"chat_id": "-100123", "text": "hola", "disable_web_page_preview": True}
    assert "secret-token" not in json.dumps(captured["body"])
    assert captured["timeout"] == 7


def test_sender_sanitizes_transport_error():
    def failing_opener(*_args, **_kwargs):
        raise OSError("https://api.telegram.org/botsecret-token/sendMessage")

    with pytest.raises(RuntimeError, match=r"telegram_send_failed:OSError") as error:
        telegram.send_telegram_message(
            token="secret-token",
            chat_id="-100123",
            text="hola",
            timeout_seconds=7,
            opener=failing_opener,
        )
    assert "secret-token" not in str(error.value)


def test_publish_is_disabled_or_unavailable_without_external_call(monkeypatch):
    called = False

    def sender(**_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(telegram, "send_telegram_message", sender)
    store = SimpleNamespace()
    disabled = SimpleNamespace(telegram_daily_summary_enabled=False)
    missing = SimpleNamespace(
        telegram_daily_summary_enabled=True,
        telegram_bot_token=None,
        telegram_daily_summary_chat_id=None,
    )

    assert telegram.publish_daily_summary(
        disabled, store, session_date="2026-07-28", performance=None, portfolio=None
    ) == {"status": "disabled"}
    assert telegram.publish_daily_summary(
        missing, store, session_date="2026-07-28", performance=None, portfolio=None
    ) == {"status": "unavailable", "reason": "telegram_configuration_missing"}
    assert called is False


def test_publish_skips_session_with_durable_receipt(monkeypatch):
    monkeypatch.setattr(
        telegram,
        "send_telegram_message",
        lambda **_kwargs: pytest.fail("no debe reenviar"),
    )
    store = SimpleNamespace(
        recent_agent_events=lambda **_kwargs: [
            {"event_id": "telegram_daily_summary:2026-07-28", "event_type": telegram.EVENT_TYPE}
        ]
    )
    settings = SimpleNamespace(
        telegram_daily_summary_enabled=True,
        telegram_bot_token="token",
        telegram_daily_summary_chat_id="-100123",
    )

    result = telegram.publish_daily_summary(
        settings,
        store,
        session_date="2026-07-28",
        performance={},
        portfolio=None,
    )

    assert result["status"] == "idempotent"
