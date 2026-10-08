from __future__ import annotations

import hashlib
import json
import re
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
        performance={
            "pnl_pct": 0.0027,
            "spy_pct": -0.003,
            "equity": 10_000,
            "performance_benchmark": {
                "captured_at": "2026-07-29T04:40:00+00:00",
                "benchmark": {
                    "symbol": "SPY",
                    "instrument_label": "SPY (ETF S&P 500)",
                    "daily_return": 0.005,
                    "price_basis": "adjusted_ohlc",
                    "source": "synthetic",
                    "as_of": "2026-07-29T04:37:00+00:00",
                    "eod_authority": "post_session_cache",
                    "comparison_status": "comparable",
                    "data_quality": "available",
                },
                "eod_overlay": {"status": "available"},
            },
        },
        portfolio=_portfolio(),
    )

    assert payload["account_daily_return"] == pytest.approx(0.0027)
    assert payload["spy_daily_return"] == pytest.approx(0.005)
    assert payload["open_total_pl"] == pytest.approx(50)
    assert payload["open_today_pl"] == pytest.approx(15)
    text = telegram.format_daily_summary(payload)
    assert "Equity: 10,000.00 USD" in text
    assert "(n/d / +0.27%)" in text
    assert payload["account_daily_return_source"] == "legacy_percentage"
    assert "SP500 +0.50%" in text and "(provisional)" in text
    assert payload["position_groups"] == {"profit": 1, "loss": 1}
    assert "AAA +25.00 USD" in text


def test_p70_characterizes_base_summary_ux_defects_before_redesign():
    payload = telegram.build_daily_summary(
        session_date="2026-07-28",
        performance={"pnl_pct": 0.0014, "spy_pct": -0.003, "equity": 70_638.81},
        portfolio=_portfolio(),
    )

    text = telegram.format_daily_summary(payload)

    # P-L129 mantiene el payload completo y muestra un resumen compacto.
    assert "Equity: 70,638.81 USD" in text
    assert payload["position_groups"] == {"profit": 1, "loss": 1}
    assert "Abiertas (2): total +50.00 USD - hoy +15.00 USD" in text
    assert "AAA +25.00 USD" in text and "BBB -10.00 USD" in text


def _acceptance_portfolio(*, previous_close_equity: float | None = 70_534.69) -> PortfolioSnapshot:
    rows = [
        ("AAPL", 21.27, 0.0213, 10.05, 0.0099),
        ("CPAY", 24.90, 0.0335, 9.22, 0.0121),
        ("GD", 16.72, 0.0217, 9.78, 0.0126),
        ("KHC", 42.94, 0.0432, 40.28, 0.0404),
        ("PRU", 17.20, 0.0176, 16.32, 0.0167),
        ("TMO", 17.96, 0.0321, 17.27, 0.0309),
        ("UNP", -37.25, -0.0402, -9.35, -0.0104),
        ("VTR", -18.20, -0.0182, -19.70, -0.0197),
    ]
    positions = [
        PositionSnapshot(
            symbol=symbol,
            qty=1,
            market_value=1_000,
            avg_entry_price=100,
            current_price=100,
            unrealized_pl=total,
            unrealized_plpc=total_pct,
            unrealized_intraday_pl=today,
            unrealized_intraday_plpc=today_pct,
        )
        for symbol, total, total_pct, today, today_pct in rows
    ]
    return PortfolioSnapshot(
        "paper",
        "ACTIVE",
        "USD",
        1_000,
        70_638.81,
        2_000,
        positions,
        [],
        previous_close_equity,
    )


def _comparable_performance(*, equity: float = 70_638.81, previous_equity: float | None = 70_538.59, spy_return: float = -0.003):
    return {
        "performance_benchmark": {
            "account": {"equity": equity, "previous_equity": previous_equity},
            "benchmark": {
                "daily_return": spy_return,
                "previous_close": 100.0,
                "close": 100.0 * (1.0 + spy_return),
                "price_basis": "adjusted_ohlc",
                "source": "local_cache",
                "as_of": "2026-07-28T20:00:00+00:00",
                "data_quality": "available",
            },
        }
    }


def _operator_performance_daily_row(*, quality: object = "partial", include_source_as_of: bool = False):
    benchmark = {
        "daily_return": -0.00304428,
        "previous_close": 100.0,
        "close": 99.695572,
        "price_basis": "unknown",
        "data_quality": quality,
    }
    if include_source_as_of:
        benchmark.update(source="persisted_local_snapshot", as_of="2026-07-28T20:00:00+00:00")
    payload_json = json.dumps(
        {
            "performance_benchmark": {
                "account": {
                    "equity": 70_634.91,
                    "previous_equity": 70_534.69,
                },
                "benchmark": benchmark,
                "comparison_status": "provisional",
            }
        },
        ensure_ascii=True,
        sort_keys=True,
    )
    return {"payload_json": payload_json, "payload": json.loads(payload_json)}


@pytest.mark.parametrize("quality", ["partial", {"status": "partial"}])
def test_p70_reads_anonymized_performance_daily_payload_without_promoting_provisional_data(quality):
    row = _operator_performance_daily_row(quality=quality)
    payload = telegram.build_daily_summary(
        session_date="2026-07-28",
        performance=row,
        portfolio=_acceptance_portfolio(previous_close_equity=None),
    )
    text = telegram.format_daily_summary(payload)

    assert payload["equity"] == pytest.approx(70_634.91)
    assert payload["previous_equity"] == pytest.approx(70_534.69)
    assert payload["equity_delta"] == pytest.approx(100.22)
    assert payload["account_daily_return"] == pytest.approx(100.22 / 70_534.69)
    assert payload["spy_daily_return"] == pytest.approx(-0.00304428)
    assert payload["comparison_status"] == "provisional"
    assert payload["benchmark_source"] is None
    assert payload["benchmark_as_of"] is None
    assert "benchmark_source_unavailable" in payload["comparison_reason_codes"]
    assert "benchmark_as_of_unavailable" in payload["comparison_reason_codes"]
    assert "SP500 -0.30%" in text and "(provisional)" in text
    assert "SP500 provisional: base no plenamente comparable." in text
    assert "ganador" not in text.lower()


def test_p70_comparison_requires_explicit_comparable_source_and_as_of():
    row = _operator_performance_daily_row(quality="available", include_source_as_of=True)
    row["payload"]["performance_benchmark"]["benchmark"].update(
        price_basis="adjusted_ohlc",
        daily_return=-0.00304428,
        comparison_status="comparable",
    )
    row["payload"]["performance_benchmark"]["comparison_status"] = "comparable"
    payload = telegram.build_daily_summary(
        session_date="2026-07-28", performance=row, portfolio=_acceptance_portfolio()
    )

    assert payload["comparison_status"] == "comparable"
    assert payload["benchmark_source"] == "persisted_local_snapshot"
    assert payload["benchmark_as_of"] == "2026-07-28T20:00:00+00:00"


def test_p70_acceptance_contract_reconciles_account_and_all_positions():
    payload = telegram.build_daily_summary(
        session_date="2026-07-28",
        performance=_comparable_performance(),
        portfolio=_acceptance_portfolio(previous_close_equity=None),
    )
    text = telegram.format_daily_summary(payload)

    assert payload["schema_version"] == "p-l70.telegram-daily-summary.v2"
    assert payload["equity_delta"] == pytest.approx(100.22)
    assert payload["account_daily_return"] == pytest.approx(100.22 / 70_538.59)
    assert payload["comparison_status"] == "comparable"
    assert payload["comparison_difference"] == pytest.approx(100.22 / 70_538.59 - (-0.003))
    assert payload["open_total_pl"] == pytest.approx(85.54)
    assert payload["open_today_pl"] == pytest.approx(73.87)
    assert payload["open_total_pl_coverage"] == {"known": 8, "total": 8, "status": "complete"}
    assert payload["open_today_pl_coverage"] == {"known": 8, "total": 8, "status": "complete"}
    assert payload["position_groups"] == {"profit": 6, "loss": 2}
    assert "Equity: 70,638.81 USD" in text
    assert "Equity: +70,638.81 USD" not in text
    assert "(+100.22 USD / +0.14%)" in text
    assert "SP500 -0.30%" in text
    assert "+0.44 pp por encima (comparable)" in text
    assert "Abiertas (8): total +85.54 USD - hoy +73.87 USD" in text
    assert len(payload["positions"]) == 8
    assert "P/L abierto hoy" not in text
    assert "Top: KHC +40.28 USD - VTR -19.70 USD - TMO +17.27 USD - +5 mas" in text
    unp = next(row for row in payload["positions"] if row["symbol"] == "UNP")
    assert unp["total_pl"] == pytest.approx(-37.25)
    assert unp["today_pl"] == pytest.approx(-9.35)


def test_p70_preserves_numeric_provisional_benchmark_without_declaring_winner():
    performance = _comparable_performance(spy_return=0.005)
    performance["performance_benchmark"]["benchmark"].update(
        price_basis="unknown", data_quality="partial"
    )

    payload = telegram.build_daily_summary(
        session_date="2026-07-28",
        performance=performance,
        portfolio=_acceptance_portfolio(previous_close_equity=None),
    )
    text = telegram.format_daily_summary(payload)

    assert payload["comparison_status"] == "provisional"
    assert payload["comparison_difference"] is not None
    assert "SP500 +0.50%" in text and "(provisional)" in text
    assert "+0.36 pp por debajo (provisional)" in text
    assert "ganador" not in text.lower()
    assert "SP500 provisional: base no plenamente comparable." in text


def test_p70_missing_equity_pair_keeps_legacy_percentage_but_not_amount():
    payload = telegram.build_daily_summary(
        session_date="2026-07-28",
        performance={
            "pnl_pct": 0.0027,
            "spy_pct": 0.005,
            "performance_benchmark": {"account": {"equity": 70_638.81, "previous_equity": None}},
        },
        portfolio=_acceptance_portfolio(previous_close_equity=None),
    )

    assert payload["equity_delta"] is None
    assert payload["account_daily_return_source"] == "legacy_percentage"
    text = telegram.format_daily_summary(payload)
    assert "(n/d / +0.27%)" in text


def test_p70_partial_position_coverage_does_not_turn_missing_into_zero():
    known = PositionSnapshot(
        symbol="KNOWN",
        qty=1,
        market_value=100,
        avg_entry_price=100,
        current_price=100,
        unrealized_pl=0.0,
        unrealized_plpc=0.0,
        unrealized_intraday_pl=2.0,
        unrealized_intraday_plpc=0.02,
    )
    missing = PositionSnapshot(
        symbol="MISSING",
        qty=1,
        market_value=100,
        avg_entry_price=100,
        current_price=100,
        unrealized_pl=float("nan"),
        unrealized_plpc=float("nan"),
        unrealized_intraday_pl=None,
        unrealized_intraday_plpc=None,
    )
    portfolio = PortfolioSnapshot("paper", "ACTIVE", "USD", 0, 100, 0, [known, missing], [])
    payload = telegram.build_daily_summary(
        session_date="2026-07-28", performance=None, portfolio=portfolio
    )

    assert payload["open_total_pl"] == pytest.approx(0.0)
    assert payload["open_total_pl_coverage"] == {"known": 1, "total": 2, "status": "partial"}
    assert payload["open_today_pl"] == pytest.approx(2.0)
    assert payload["open_today_pl_coverage"] == {"known": 1, "total": 2, "status": "partial"}
    text = telegram.format_daily_summary(payload)
    assert "Abiertas (2): total +0.00 USD - hoy +2.00 USD - parcial" in text
    assert payload["position_groups"]["incomplete"] == 1
    assert "MISSING n/d" in text


def test_p70_large_portfolio_is_explicitly_bounded_without_losing_payload_positions():
    positions = [
        PositionSnapshot(
            symbol=f"S{index:03d}",
            qty=1,
            market_value=100,
            avg_entry_price=100,
            current_price=100,
            unrealized_pl=float(index + 1),
            unrealized_plpc=0.01,
            unrealized_intraday_pl=float(index) / 10,
            unrealized_intraday_plpc=0.001,
        )
        for index in range(100)
    ]
    portfolio = PortfolioSnapshot("paper", "ACTIVE", "USD", 0, 10_000, 0, positions, [])
    payload = telegram.build_daily_summary(
        session_date="2026-07-28", performance=None, portfolio=portfolio
    )
    text = telegram.format_daily_summary(payload)

    assert len(payload["positions"]) == 100
    assert telegram._telegram_utf16_units(text) <= telegram.TELEGRAM_MESSAGE_LIMIT_UNITS
    match = re.search(r"Top: (.*?) - \+(\d+) mas", text)
    assert match
    visible, total, omitted = len(match.group(1).split(" - ")), len(payload["positions"]), int(match.group(2))
    assert total == 100
    assert visible + omitted == total


def test_p70_telegram_limit_uses_utf16_units_and_never_emits_empty_group_heading():
    exact = "🧪" * 2048
    assert len(exact) == 2048
    assert telegram._telegram_utf16_units(exact) == 4096
    assert telegram._telegram_utf16_units(exact + "a") == 4097

    positions = [
        PositionSnapshot(
            symbol=f"🧪{index:03d}",
            qty=1,
            market_value=100,
            avg_entry_price=100,
            current_price=100,
            unrealized_pl=float(index + 1),
            unrealized_plpc=0.01,
            unrealized_intraday_pl=float(index) / 10,
            unrealized_intraday_plpc=0.001,
        )
        for index in range(120)
    ]
    payload = telegram.build_daily_summary(
        session_date="2026-07-28",
        performance=None,
        portfolio=PortfolioSnapshot("paper", "ACTIVE", "USD", 0, 10_000, 0, positions, []),
    )
    text = telegram.format_daily_summary(payload)

    assert telegram._telegram_utf16_units(text) <= telegram.TELEGRAM_MESSAGE_LIMIT_UNITS
    match = re.search(r"Top: (.*?) - \+(\d+) mas", text)
    assert match
    visible, total, omitted = len(match.group(1).split(" - ")), len(payload["positions"]), int(match.group(2))
    assert total == 120
    assert visible + omitted == total
    for heading in ("🟢 En beneficio", "🔴 En pérdida", "⚪ Sin cambio", "⚠️ Datos incompletos"):
        for line_number, line in enumerate(text.splitlines()):
            if line.startswith(heading):
                assert text.splitlines()[line_number + 1].startswith("• ")


def test_p70_sender_rejects_text_over_utf16_limit_before_transport():
    with pytest.raises(ValueError, match="telegram_message_too_long"):
        telegram.send_telegram_message(
            token="secret-token",
            chat_id="-100123",
            text="🧪" * 2048 + "a",
            timeout_seconds=7,
            opener=lambda *_args, **_kwargs: pytest.fail("no debe transportar texto inválido"),
        )


def test_p70_empty_unicode_and_non_finite_values_are_explicitly_unavailable():
    empty = PortfolioSnapshot("paper", "ACTIVE", "USD", 0, 0, 0, [], [])
    payload = telegram.build_daily_summary(
        session_date="2026-07-28",
        performance={"pnl_pct": float("nan"), "spy_pct": float("inf"), "equity": float("nan")},
        portfolio=empty,
    )

    assert payload["open_total_pl"] == 0.0
    assert payload["open_total_pl_coverage"]["status"] == "not_applicable"
    assert payload["account_daily_return"] is None
    assert payload["spy_daily_return"] is None
    assert payload["comparison_status"] == "unavailable"
    json.dumps(payload, allow_nan=False)
    text = telegram.format_daily_summary(payload)
    assert "Sin posiciones abiertas." in text
    assert "SP500 n/d (sin datos comparables)" in text

    unicode_position = PositionSnapshot(
        symbol="ÑANDÚ",
        qty=1,
        market_value=100,
        avg_entry_price=100,
        current_price=100,
        unrealized_pl=0.0,
        unrealized_plpc=0.0,
        unrealized_intraday_pl=None,
        unrealized_intraday_plpc=None,
    )
    unicode_payload = telegram.build_daily_summary(
        session_date="2026-07-28", performance=None, portfolio=PortfolioSnapshot(
            "paper", "ACTIVE", "USD", 0, 100, 0, [unicode_position], []
        )
    )
    assert "ÑANDÚ" in telegram.format_daily_summary(unicode_payload)
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
    assert payload["open_today_pl_coverage"] == {"known": 0, "total": 1, "status": "unavailable"}
    assert "Abiertas (1): total +0.00 USD - hoy n/d" in telegram.format_daily_summary(payload)


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
    assert events[0]["payload"]["schema_version"] == "p-l70.telegram-daily-summary.v2"
    assert events[0]["payload"]["message_length"] <= telegram.MAX_TELEGRAM_MESSAGE_LENGTH
    assert events[0]["payload"]["text"] == calls[0]["text"]
    assert events[0]["payload"]["text_sha256"] == hashlib.sha256(calls[0]["text"].encode("utf-8")).hexdigest()
    assert events[0]["payload"]["message_utf16_units"] == telegram._telegram_utf16_units(calls[0]["text"])
    assert events[0]["payload"]["message_utf16_units"] <= telegram.TELEGRAM_MESSAGE_LIMIT_UNITS
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
