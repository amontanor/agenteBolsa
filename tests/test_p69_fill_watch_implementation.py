from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools import fill_provider, fill_watch, telegram_trade_notifications

NOW = datetime(2026, 7, 29, 14, 0, tzinfo=timezone.utc)


class FakeProvider:
    def __init__(self, snapshots):
        self.snapshots = list(snapshots)
        self.requested = []

    def snapshot_order(self, broker_order_id, *, client_order_id=None, timeout_seconds=None):
        self.requested.append((broker_order_id, client_order_id, timeout_seconds))
        value = self.snapshots.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def _settings(tmp_path, *, telegram=False):
    return Settings(
        DATA_DIR=tmp_path,
        TRADE_FILL_WATCH_ENABLED=True,
        TELEGRAM_TRADE_NOTIFICATIONS_ENABLED=telegram,
        TELEGRAM_BOT_TOKEN="test-token" if telegram else None,
        TELEGRAM_DAILY_SUMMARY_CHAT_ID="test-chat" if telegram else None,
        TRADE_FILL_WATCH_BACKOFF_SECONDS=30,
        TRADE_FILL_WATCH_MAX_BACKOFF_SECONDS=120,
    )


def _store(settings, *, status="PENDING_NEW", order_id="bo-1"):
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.save_broker_order(
        broker_order_id=order_id,
        plan_id=f"plan-{order_id}",
        cycle_id="cycle-1",
        symbol="KHC",
        side="buy",
        status=status,
        payload={
            "broker_order": {"client_order_id": f"client-{order_id}", "qty": 3},
            "plan": {"plan_id": f"plan-{order_id}", "payload": {}},
        },
    )
    return store


def _snapshot(order_id="bo-1", status="pending_new", **values):
    return fill_provider.CanonicalOrderSnapshot(
        broker_order_id=order_id,
        provider_order_id=order_id,
        client_order_id=f"client-{order_id}",
        status=status,
        filled_qty=values.get("filled_qty"),
        filled_avg_price=values.get("filled_avg_price"),
        filled_at=values.get("filled_at"),
        updated_at=values.get("updated_at", "2026-07-29T14:00:00+00:00"),
    )


def test_fake_provider_is_canonical_and_alpaca_adapter_is_confined() -> None:
    snapshot = fill_provider.canonical_order_snapshot(
        {
            "id": "bo-1",
            "client_order_id": "client-1",
            "status": "OrderStatus.PENDING_NEW",
            "filled_qty": None,
            "filled_avg_price": None,
        },
        requested_id="bo-1",
    )

    assert snapshot.status == "pending_new"
    assert snapshot.broker_order_id == "bo-1"
    assert "Alpaca" not in __import__("inspect").getsource(fill_watch)


def test_provider_adapter_applies_request_timeout_without_network():
    requests = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "id": "bo-1",
                "client_order_id": "client-bo-1",
                "status": "filled",
                "filled_qty": "3",
                "filled_avg_price": "27.2",
            }

    class Session:
        def request(self, *args, **kwargs):
            requests.append((args, kwargs))
            return Response()

    client = SimpleNamespace(
        _session=Session(),
        _base_url="https://paper.example",
        _api_version="v2",
        _get_default_headers=lambda: {"Authorization": "test"},
    )
    snapshot = fill_provider.AlpacaOrderStatusProvider(client).snapshot_order("bo-1", timeout_seconds=5)

    assert snapshot.status == "filled"
    assert requests[0][1]["timeout"] == 5
    assert "paper.example/v2/orders/bo-1" in requests[0][0][1]


def test_provider_adapter_uses_public_sdk_fallback_when_private_session_is_absent():
    calls = []

    class Client:
        def get_order_by_id(self, order_id):
            calls.append(order_id)
            return {
                "id": order_id,
                "client_order_id": "client-bo-1",
                "status": "filled",
                "filled_qty": "3",
                "filled_avg_price": "27.2",
            }

    snapshot = fill_provider.AlpacaOrderStatusProvider(Client()).snapshot_order("bo-1", timeout_seconds=5)

    assert snapshot.status == "filled"
    assert calls == ["bo-1"]


def test_pending_submit_is_polled_by_exact_id_and_never_notifies(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    store = _store(settings)
    provider = FakeProvider([_snapshot(status="pending_new")])
    notifications = []
    monkeypatch.setattr(fill_watch, "publish_trade_fill_notifications", lambda *_args: notifications.append(1) or {"sent": 0})

    result = fill_watch.run_trade_fill_watch(settings, store, provider=provider, now=NOW)

    assert result["filled_transitions"] == 0
    assert notifications == []
    assert provider.requested == [("bo-1", "client-bo-1", 5)]
    assert store.pending_broker_orders()[0]["status"].lower() == "pending_new"


def test_remote_filled_is_committed_before_telegram_and_is_idempotent(tmp_path, monkeypatch):
    settings = _settings(tmp_path, telegram=True)
    store = _store(settings)
    sent = []
    monkeypatch.setattr(
        telegram_trade_notifications,
        "send_telegram_message",
        lambda **kwargs: sent.append(kwargs) or {"ok": True, "message_id": 42},
    )
    provider = FakeProvider(
        [
            _snapshot(
                status="filled",
                filled_qty=3,
                filled_avg_price=27.666842,
                filled_at="2026-07-29T13:51:34+00:00",
            )
        ]
    )

    result = fill_watch.run_trade_fill_watch(settings, store, provider=provider, now=NOW)

    assert result["filled_transitions"] == 1
    assert result["sent"] == 1
    assert len(sent) == 1
    assert "27.6668" in sent[0]["text"]
    with store.connect() as conn:
        order = conn.execute("SELECT status, payload_json FROM broker_orders WHERE broker_order_id = 'bo-1'").fetchone()
        receipt = conn.execute("SELECT payload_json FROM agent_events WHERE event_id = 'telegram_trade_fill:bo-1'").fetchone()
    assert order["status"] == "filled"
    assert "broker_order_reconciled" in order["payload_json"]
    assert '"status": "sent"' in receipt["payload_json"]

    second = fill_watch.run_trade_fill_watch(settings, store, provider=FakeProvider([]), now=NOW)
    assert second["sent"] == 0
    assert len(sent) == 1


def test_known_telegram_failure_retries_without_requerying_filled_order(tmp_path, monkeypatch):
    settings = _settings(tmp_path, telegram=True)
    store = _store(settings)
    calls = []

    def send(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise OSError("temporary telegram failure")
        return {"ok": True, "message_id": 43}

    monkeypatch.setattr(telegram_trade_notifications, "send_telegram_message", send)
    first = fill_watch.run_trade_fill_watch(
        settings,
        store,
        provider=FakeProvider([_snapshot(status="filled", filled_qty=3, filled_avg_price=27.0)]),
        now=NOW,
    )
    assert first["sent"] == 0
    assert first["failed"] == 1

    second = fill_watch.run_trade_fill_watch(settings, store, provider=FakeProvider([]), now=NOW)
    assert second["sent"] == 1
    assert len(calls) == 2
    assert store.retryable_trade_fill_changes() == []


def test_partial_fill_notifies_only_on_terminal_fill(tmp_path, monkeypatch):
    settings = _settings(tmp_path, telegram=True)
    store = _store(settings)
    sent = []
    monkeypatch.setattr(
        telegram_trade_notifications,
        "send_telegram_message",
        lambda **kwargs: sent.append(kwargs) or {"ok": True, "message_id": 44},
    )
    partial = fill_watch.run_trade_fill_watch(
        settings,
        store,
        provider=FakeProvider([_snapshot(status="partially_filled", filled_qty=1, filled_avg_price=27.0)]),
        now=NOW,
    )
    assert partial["filled_transitions"] == 0
    assert sent == []
    terminal = fill_watch.run_trade_fill_watch(
        settings,
        store,
        provider=FakeProvider([_snapshot(status="filled", filled_qty=3, filled_avg_price=27.1)]),
        now=NOW,
    )
    assert terminal["filled_transitions"] == 1
    assert len(sent) == 1


def test_rejected_and_cancelled_orders_never_notify_or_enter_retry_queue(tmp_path, monkeypatch):
    for terminal_status in ("rejected", "cancelled"):
        settings = _settings(tmp_path / terminal_status, telegram=True)
        store = _store(settings, status="PENDING_NEW", order_id=f"bo-{terminal_status}")
        sent = []
        monkeypatch.setattr(
            telegram_trade_notifications,
            "send_telegram_message",
            lambda sent=sent, **kwargs: sent.append(kwargs) or {"ok": True, "message_id": 99},
        )
        result = fill_watch.run_trade_fill_watch(
            settings,
            store,
            provider=FakeProvider([_snapshot(order_id=f"bo-{terminal_status}", status=terminal_status)]),
            now=NOW,
        )
        assert result["filled_transitions"] == 0
        assert sent == []
        assert store.retryable_trade_fill_changes() == []


def test_malformed_provider_snapshot_uses_bounded_backoff(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    malformed = SimpleNamespace(as_dict=lambda: {"id": "bo-1", "status": ""})

    result = fill_watch.run_trade_fill_watch(settings, store, provider=FakeProvider([malformed]), now=NOW)

    assert result["provider_unavailable"] == 1
    state = store.runtime_values_by_prefix(fill_watch.WATCH_STATE_PREFIX)["trade_fill_watch:order:bo-1"]
    assert state["attempt"] == 1
    assert state["backoff_seconds"] == 30


def test_watcher_and_postmarket_race_has_one_local_transition_and_one_message(tmp_path, monkeypatch):
    settings = _settings(tmp_path, telegram=True)
    _store(settings)
    sent = []
    monkeypatch.setattr(
        telegram_trade_notifications,
        "send_telegram_message",
        lambda **kwargs: sent.append(kwargs) or {"ok": True, "message_id": 101},
    )

    def run_once():
        local = Store(settings.database_path, settings.agent_logs_dir)
        return fill_watch.run_trade_fill_watch(
            settings,
            local,
            provider=FakeProvider([_snapshot(status="filled", filled_qty=3, filled_avg_price=27.2)]),
            now=NOW,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _item: run_once(), range(2)))
    assert sum(item["filled_transitions"] for item in results) == 1
    assert len(sent) == 1


def test_configuration_is_disabled_and_provider_timeout_is_neutral(tmp_path):
    settings = Settings(DATA_DIR=tmp_path)

    assert settings.trade_fill_watch_enabled is False
    assert settings.trade_fill_watch_cadence_seconds == 30
    assert settings.trade_fill_watch_max_pending_per_run == 25
    assert settings.trade_fill_watch_request_timeout_seconds == 5
    assert settings.trade_fill_watch_backoff_seconds == 30
    assert settings.trade_fill_watch_max_backoff_seconds == 300


def test_claim_is_single_winner_and_conflicts_are_not_overwritten(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)

    def claim():
        local = Store(settings.database_path, settings.agent_logs_dir)
        return local.claim_trade_fill_notification(
            broker_order_id="bo-claim",
            content_hash="hash-a",
            cycle_id="cycle-1",
        )

    # The order is absent on purpose: claiming an identity does not infer or
    # create a broker order, but the append-only event still arbitrates sends.
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _item: claim(), range(2)))
    assert sorted(item["status"] for item in outcomes) == ["acquired", "busy"]

    conflict = store.record_append_only_event(
        event_id="telegram_trade_fill:bo-claim",
        event_type="telegram_trade_fill_sent",
        cycle_id="cycle-1",
        payload={"status": "sent", "content_hash": "different"},
    )
    same = store.record_append_only_event(
        event_id="telegram_trade_fill:bo-claim",
        event_type="telegram_trade_fill_sent",
        cycle_id="cycle-1",
        payload={"status": "sent", "content_hash": "different"},
    )
    assert conflict["status"] == "inserted"
    assert same["status"] == "idempotent"


def test_provider_failure_backoff_is_bounded_and_no_network_retry_storm(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    provider = FakeProvider([TimeoutError("provider unavailable")])

    first = fill_watch.run_trade_fill_watch(settings, store, provider=provider, now=NOW)
    second = fill_watch.run_trade_fill_watch(settings, store, provider=FakeProvider([]), now=NOW)

    assert first["provider_unavailable"] == 1
    assert second["skipped_backoff"] == 1
    state = store.runtime_values_by_prefix(fill_watch.WATCH_STATE_PREFIX)
    assert state["trade_fill_watch:order:bo-1"]["backoff_seconds"] == 30
    assert provider.requested == [("bo-1", "client-bo-1", 5)]
