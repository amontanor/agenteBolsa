from __future__ import annotations

import hashlib
from types import SimpleNamespace

from agente_bolsa.config import Settings
from agente_bolsa.models import PortfolioSnapshot
from agente_bolsa.storage import Store
from agente_bolsa.tools import telegram_daily_summary as daily
from agente_bolsa.tools import telegram_trade_notifications as fills


def test_p70br1_summary_receipt_is_idempotent_and_separate_from_fill_events(tmp_path, monkeypatch):
    settings = Settings(DATA_DIR=tmp_path, _env_file=None)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    telegram_settings = SimpleNamespace(
        telegram_daily_summary_enabled=True,
        telegram_bot_token="test-token",
        telegram_daily_summary_chat_id="-100123",
        telegram_timeout_seconds=15,
    )
    sent_texts: list[str] = []
    monkeypatch.setattr(
        daily,
        "send_telegram_message",
        lambda **kwargs: sent_texts.append(kwargs["text"]) or {"ok": True, "message_id": 7},
    )
    portfolio = PortfolioSnapshot("paper", "ACTIVE", "USD", 0, 70_634.91, 0, [], [])
    performance = {
        "performance_benchmark": {
            "account": {"equity": 70_634.91, "previous_equity": 70_534.69},
            "benchmark": {
                "daily_return": -0.00304428,
                "previous_close": 100.0,
                "close": 99.695572,
                "price_basis": "unknown",
                "data_quality": "partial",
            },
            "comparison_status": "provisional",
        }
    }

    first = daily.publish_daily_summary(
        telegram_settings, store, session_date="2026-07-28", performance=performance, portfolio=portfolio
    )
    second = daily.publish_daily_summary(
        telegram_settings, store, session_date="2026-07-28", performance=performance, portfolio=portfolio
    )

    assert first["status"] == "sent"
    assert second["status"] == "idempotent"
    assert len(sent_texts) == 1
    receipt = store.agent_events(event_type_prefix=daily.EVENT_TYPE, limit=10)[0]["payload"]
    assert receipt["text"] == sent_texts[0]
    assert receipt["text_sha256"] == hashlib.sha256(sent_texts[0].encode("utf-8")).hexdigest()
    assert receipt["content_hash"] != receipt["text_sha256"]
    assert receipt["message_utf16_units"] <= 4096
    assert daily.EVENT_TYPE != fills.EVENT_TYPE
    assert "test-token" not in str(receipt)

