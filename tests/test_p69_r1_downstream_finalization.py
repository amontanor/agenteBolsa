from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools import fill_watch, telegram_trade_notifications
from agente_bolsa.tools.broker_reconciliation import reconcile_broker_orders
from agente_bolsa.tools.execution_quality import build_planned_snapshot

NOW = datetime(2026, 7, 28, 20, 0, tzinfo=timezone.utc)
SESSION_DATE = "2026-07-28"


class _FilledProvider:
    def __init__(self, status: str = "filled") -> None:
        self.status = status

    def snapshot_order(self, broker_order_id: str, **_kwargs):
        return {
            "id": broker_order_id,
            "client_order_id": f"client-{broker_order_id}",
            "status": self.status,
            "filled_qty": "3" if self.status == "filled" else None,
            "filled_avg_price": "27.5" if self.status == "filled" else None,
            "filled_at": f"{SESSION_DATE}T19:59:00+00:00" if self.status == "filled" else None,
            "updated_at": f"{SESSION_DATE}T20:00:00+00:00",
        }


def _settings(tmp_path, *, telegram: bool = True) -> Settings:
    return Settings(
        DATA_DIR=tmp_path,
        TELEGRAM_TRADE_NOTIFICATIONS_ENABLED=telegram,
        TELEGRAM_BOT_TOKEN="test-token" if telegram else None,
        TELEGRAM_DAILY_SUMMARY_CHAT_ID="test-chat" if telegram else None,
        TRADE_FILL_WATCH_ENABLED=True,
    )


def _seed_buy(store: Store, *, order_id: str = "broker-buy-1", side: str = "buy") -> None:
    plan_id = f"plan-{order_id}"
    cycle_id = "cycle-r1"
    plan_created_at = f"{SESSION_DATE}T19:50:00+00:00"
    plan_payload = {
        "decision_lineage": {
            "signal_id": "run-r1:AAPL",
            "signal_capture_id": "capture-r1",
            "candidate_id": "candidate-r1",
            "lineage_id": "lineage-r1",
            "cycle_id": cycle_id,
        },
        "recommendation": {"recommendation_id": "recommendation-r1", "entry_price": 27.4},
        "qty": 3,
        "entry_price": 27.4,
    }
    quality = build_planned_snapshot(
        plan_id=plan_id,
        cycle_id=cycle_id,
        symbol="AAPL",
        side=side,
        payload=plan_payload,
        planned_at=plan_created_at,
        signal_price=27.3,
        signal_at=f"{SESSION_DATE}T19:40:00+00:00",
    )
    store.save_broker_order(
        broker_order_id=order_id,
        plan_id=plan_id,
        cycle_id=cycle_id,
        symbol="AAPL",
        side=side,
        status="PENDING_NEW",
        payload={
            "broker_order": {"id": order_id, "client_order_id": f"client-{order_id}", "qty": 3},
            "plan": {"plan_id": plan_id, "created_at": plan_created_at},
            "execution_quality_snapshot": quality,
        },
    )
    store.save_signal_outcome(
        signal_id="run-r1:AAPL",
        source_run_id="run-r1",
        source="test",
        symbol="AAPL",
        signal_date=SESSION_DATE,
        decision="approved_buy",
        features={},
        gate={},
        outcome={},
    )
    store.upsert_learning_observation(
        {
            "observation_id": "learning-r1",
            "signal_date": SESSION_DATE,
            "symbol": "AAPL",
            "source_family": "test",
            "decision": "approved_buy",
        }
    )
    with store.connect() as conn:
        conn.execute(
            "UPDATE broker_orders SET created_at = ? WHERE broker_order_id = ?",
            (plan_created_at, order_id),
        )
        conn.execute(
            "UPDATE signal_outcomes SET created_at = ?, updated_at = ? WHERE signal_id = ?",
            (f"{SESSION_DATE}T19:45:00+00:00", f"{SESSION_DATE}T19:45:00+00:00", "run-r1:AAPL"),
        )


def test_watcher_terminal_order_is_finalized_by_postmarket_exactly_once(tmp_path, monkeypatch):
    """The corrected tree carries watcher terminal state into postmarket once."""

    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    _seed_buy(store)
    sent = []
    monkeypatch.setattr(
        telegram_trade_notifications,
        "send_telegram_message",
        lambda **kwargs: sent.append(kwargs) or {"ok": True, "message_id": 701},
    )

    watcher = fill_watch.run_trade_fill_watch(
        settings,
        store,
        provider=_FilledProvider(),
        now=NOW,
    )
    assert watcher["filled_transitions"] == 1
    assert len(sent) == 1

    with store.connect() as conn:
        order = conn.execute(
            "SELECT status, payload_json FROM broker_orders WHERE broker_order_id = ?",
            ("broker-buy-1",),
        ).fetchone()
    assert order["status"] == "filled"
    assert "broker_order_reconciled" in order["payload_json"]

    restarted = Store(settings.database_path, settings.agent_logs_dir)
    postmarket = reconcile_broker_orders(settings, restarted, apply=True, update_learning=False)

    assert postmarket["pending"] == 1
    assert postmarket["changes"][0]["finalization_pending"] is True
    assert postmarket["signal_execution_updates"] == 1
    assert postmarket["learning_execution_updates"] == 1
    assert postmarket["execution_quality_updates"] == 1
    assert postmarket["finalization_applied"] == 1
    with store.connect() as conn:
        order = conn.execute(
            "SELECT payload_json FROM broker_orders WHERE broker_order_id = ?",
            ("broker-buy-1",),
        ).fetchone()
        signal = conn.execute(
            "SELECT gate_json, features_json, outcome_json FROM signal_outcomes WHERE signal_id = ?",
            ("run-r1:AAPL",),
        ).fetchone()
        learning = conn.execute(
            "SELECT executed_buy, execution_json FROM learning_observations WHERE observation_id = ?",
            ("learning-r1",),
        ).fetchone()
    assert json.loads(signal["gate_json"] or "{}")["executed_buy"] is True
    assert json.loads(signal["outcome_json"] or "{}")["execution"]["broker_order_id"] == "broker-buy-1"
    assert learning["executed_buy"] == 1
    assert json.loads(signal["features_json"] or "{}")["execution_quality_snapshot"]["status"] == "filled"
    marker = json.loads(order["payload_json"])["reconciliation_finalization"]
    assert marker["status"] == "applied"
    assert marker["snapshot_content_hash"]
    assert json.loads(order["payload_json"])["reconciliation_finalization_pending"] is False

    repeated = reconcile_broker_orders(settings, restarted, apply=True, update_learning=False)
    assert repeated["pending"] == 0
    assert repeated["signal_execution_updates"] == 0
    assert repeated["learning_execution_updates"] == 0
    assert repeated["execution_quality_updates"] == 0
    assert repeated["finalization_applied"] == 0


def test_terminal_non_buy_paths_are_not_buy_execution_effects_on_base(tmp_path, monkeypatch):
    for side, terminal in (("sell", "filled"), ("buy", "rejected"), ("buy", "cancelled")):
        settings = _settings(tmp_path / f"{side}-{terminal}", telegram=True)
        store = Store(settings.database_path, settings.agent_logs_dir)
        store.ensure_schema()
        order_id = f"broker-{side}-{terminal}"
        _seed_buy(store, order_id=order_id, side=side)
        sent = []
        monkeypatch.setattr(
            telegram_trade_notifications,
            "send_telegram_message",
            lambda sent=sent, **kwargs: sent.append(kwargs) or {"ok": True, "message_id": 702},
        )

        result = fill_watch.run_trade_fill_watch(
            settings,
            store,
            provider=_FilledProvider(status=terminal),
            now=NOW,
        )
        assert result["filled_transitions"] == (1 if side == "sell" and terminal == "filled" else 0)
        assert len(sent) == (1 if side == "sell" and terminal == "filled" else 0)
        postmarket = reconcile_broker_orders(settings, store, apply=True, update_learning=False)
        assert postmarket["pending"] == 1
        assert postmarket["signal_execution_updates"] == 0
        assert postmarket["learning_execution_updates"] == 0
        assert postmarket["finalization_applied"] == 1
        repeated = reconcile_broker_orders(settings, store, apply=True, update_learning=False)
        assert repeated["pending"] == 0


def test_two_postmarket_finalizers_claim_one_marker_and_preserve_exact_ids(tmp_path, monkeypatch):
    settings = _settings(tmp_path, telegram=False)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    _seed_buy(store)
    fill_watch.run_trade_fill_watch(settings, store, provider=_FilledProvider(), now=NOW)

    class _UnexpectedBrokerFactory:
        def __init__(self, _settings):
            raise AssertionError("terminal watcher finalization must not query the broker")

    monkeypatch.setattr(
        "agente_bolsa.tools.broker_reconciliation.BrokerClientFactory",
        _UnexpectedBrokerFactory,
    )

    def finalize_once(_item):
        local = Store(settings.database_path, settings.agent_logs_dir)
        return reconcile_broker_orders(settings, local, apply=True, update_learning=False)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(finalize_once, range(2)))

    assert sum(item["finalization_applied"] for item in results) == 1
    assert sum(item["finalization_skipped"] for item in results) in {0, 1}
    assert sum(item["signal_execution_updates"] for item in results) == 1
    assert sum(item["learning_execution_updates"] for item in results) == 1
    assert sum(item["execution_quality_updates"] for item in results) == 1
    with store.connect() as conn:
        order = conn.execute(
            "SELECT payload_json FROM broker_orders WHERE broker_order_id = ?",
            ("broker-buy-1",),
        ).fetchone()
        signal = conn.execute(
            "SELECT gate_json, features_json FROM signal_outcomes WHERE signal_id = ?",
            ("run-r1:AAPL",),
        ).fetchone()
    payload = json.loads(order["payload_json"])
    assert payload["reconciliation_finalization"]["status"] == "applied"
    assert json.loads(signal["gate_json"])["broker_order_id"] == "broker-buy-1"
    assert json.loads(signal["features_json"])["execution_quality_snapshot"]["broker_order_id"] == "broker-buy-1"
