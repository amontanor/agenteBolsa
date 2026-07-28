from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agente_bolsa import scheduler
from agente_bolsa.config import Settings
from agente_bolsa.models import PortfolioSnapshot, PositionSnapshot
from agente_bolsa.storage import Store
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
        agent_events=lambda **_kwargs: [
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


def test_publish_uses_real_store_receipt_and_is_idempotent(tmp_path, monkeypatch):
    settings = Settings(DATA_DIR=tmp_path, _env_file=None)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    telegram_settings = SimpleNamespace(
        telegram_daily_summary_enabled=True,
        telegram_bot_token="secret-token",
        telegram_daily_summary_chat_id="-100123",
        telegram_timeout_seconds=15,
    )
    calls = []
    monkeypatch.setattr(
        telegram,
        "send_telegram_message",
        lambda **kwargs: calls.append(kwargs) or {"ok": True, "message_id": 99},
    )

    first = telegram.publish_daily_summary(
        telegram_settings,
        store,
        session_date="2026-07-28",
        performance={"pnl_pct": 0.0027, "spy_pct": 0.005, "equity": 10_000},
        portfolio=_portfolio(),
    )
    second = telegram.publish_daily_summary(
        telegram_settings,
        store,
        session_date="2026-07-28",
        performance={"pnl_pct": 0.0027, "spy_pct": 0.005, "equity": 10_000},
        portfolio=_portfolio(),
    )

    assert first["status"] == "sent"
    assert second["status"] == "idempotent"
    assert len(calls) == 1
    events = store.agent_events(event_type_prefix=telegram.EVENT_TYPE, limit=20)
    assert len(events) == 1
    assert events[0]["event_id"] == "telegram_daily_summary:2026-07-28"
    assert events[0]["payload"]["status"] == "sent"
    assert "secret-token" not in json.dumps(events[0])


def test_scheduled_job_does_not_touch_broker_when_disabled(monkeypatch):
    monkeypatch.setattr(
        scheduler,
        "BrokerClientFactory",
        lambda _settings: pytest.fail("no debe consultar broker"),
    )
    recorded = {}
    store = SimpleNamespace(set_runtime_value=lambda key, value: recorded.update({key: value}))
    settings = SimpleNamespace(telegram_daily_summary_enabled=False)

    result = scheduler.telegram_daily_summary_job(settings, store)

    assert result == {"status": "disabled"}
    assert recorded["scheduler_job_status:telegram_daily_summary"]["status"] == "skipped"


def test_scheduled_job_reuses_one_portfolio_and_local_performance(monkeypatch):
    portfolio = _portfolio()
    calls = {"broker": 0, "performance": 0, "publish": 0}

    class Calendar:
        def __init__(self, *_args):
            pass

        def should_run_daily_study(self):
            return True, SimpleNamespace(now_market="2026-07-28T16:05:00-04:00")

    class Broker:
        def alpaca_portfolio_snapshot(self):
            calls["broker"] += 1
            return portfolio

    monkeypatch.setattr(scheduler, "MarketCalendar", Calendar)
    monkeypatch.setattr(scheduler, "BrokerClientFactory", lambda _settings: Broker())

    def build(_store, _settings, session_date, *, portfolio):
        calls["performance"] += 1
        assert session_date == "2026-07-28"
        assert portfolio is globals_portfolio
        return {"pnl_pct": 0.0027, "spy_pct": 0.005}

    globals_portfolio = portfolio
    monkeypatch.setattr(scheduler, "build_daily_performance_item", build)

    def publish(_settings, _store, *, session_date, performance, portfolio):
        calls["publish"] += 1
        assert session_date == "2026-07-28"
        assert performance["pnl_pct"] == pytest.approx(0.0027)
        assert portfolio is globals_portfolio
        return {"status": "sent"}

    monkeypatch.setattr(scheduler, "publish_daily_summary", publish)
    recorded = {}
    store = SimpleNamespace(set_runtime_value=lambda key, value: recorded.update({key: value}))
    settings = SimpleNamespace(
        telegram_daily_summary_enabled=True,
        market_calendar="XNYS",
        local_timezone="Europe/Madrid",
        logs_dir=None,
    )

    result = scheduler.telegram_daily_summary_job(settings, store)

    assert result == {"status": "sent"}
    assert calls == {"broker": 1, "performance": 1, "publish": 1}
    assert recorded["scheduler_job_status:telegram_daily_summary"]["status"] == "completed"
