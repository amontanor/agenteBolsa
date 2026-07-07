import json
from datetime import date, timedelta

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.broker_reconciliation import reconcile_broker_orders


def _latest_market_session(today: date | None = None) -> date:
    today = today or date.today()
    session = today
    while session.weekday() >= 5:
        session -= timedelta(days=1)
    return session


class _Order:
    id = "broker-1"
    client_order_id = "agente-plan-1"
    status = "filled"
    filled_qty = "3"
    filled_avg_price = "101.5"
    qty = "3"
    notional = None
    submitted_at = None
    filled_at = "2026-06-16T20:00:00+00:00"
    updated_at = "2026-06-16T20:00:01+00:00"


class _Client:
    def get_order_by_id(self, _order_id):
        return _Order()


def test_reconcile_broker_orders_marks_filled_buy_as_executed(tmp_path, monkeypatch):
    session_date = _latest_market_session()
    signal_date = session_date.isoformat()
    filled_at = f"{signal_date}T20:00:00+00:00"
    plan_created_at = f"{signal_date}T19:59:00+00:00"

    local_order = type(
        "LocalOrder",
        (),
        {
            "id": "broker-1",
            "client_order_id": "agente-plan-1",
            "status": "filled",
            "filled_qty": "3",
            "filled_avg_price": "101.5",
            "qty": "3",
            "notional": None,
            "submitted_at": None,
            "filled_at": filled_at,
            "updated_at": f"{signal_date}T20:00:01+00:00",
        },
    )()

    settings = Settings(DATA_DIR=tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.save_broker_order(
        broker_order_id="broker-1",
        plan_id="plan-1",
        cycle_id="cycle-1",
        symbol="AAPL",
        side="buy",
        status="OrderStatus.PENDING_NEW",
        payload={
            "broker_order": {"client_order_id": "agente-plan-1"},
            "plan": {"created_at": plan_created_at},
        },
    )
    store.save_signal_outcome(
        signal_id="run-1:AAPL",
        source_run_id="run-1",
        source="test",
        symbol="AAPL",
        signal_date=signal_date,
        decision="approved_buy",
        features={},
        gate={},
        outcome={},
    )
    store.upsert_learning_observation(
        {
            "observation_id": "obs-1",
            "signal_date": signal_date,
            "symbol": "AAPL",
            "source_family": "test",
            "decision": "approved_buy",
        }
    )

    class _Factory:
        def __init__(self, _settings):
            pass

        def alpaca_trading_client(self):
            return type("LocalClient", (), {"get_order_by_id": lambda self, _order_id: local_order})()

    monkeypatch.setattr("agente_bolsa.tools.broker_reconciliation.BrokerClientFactory", _Factory)
    monkeypatch.setattr(
        "agente_bolsa.tools.broker_reconciliation.update_signal_outcomes",
        lambda *_args, **_kwargs: {"updated": 0, "signals": 0, "symbols": 0, "warnings": []},
    )

    result = reconcile_broker_orders(settings, store, apply=True)

    assert result["applied"] is True
    assert len(result["changes"]) == 1
    assert result["changes"][0]["new"] == "filled"
    assert result["signal_execution_updates"] == 1
    assert result["learning_execution_updates"] == 1
    with store.connect() as conn:
        order = conn.execute("SELECT status, payload_json FROM broker_orders WHERE broker_order_id = 'broker-1'").fetchone()
        signal = conn.execute("SELECT gate_json FROM signal_outcomes WHERE signal_id = 'run-1:AAPL'").fetchone()
        learning = conn.execute("SELECT executed_buy, execution_json FROM learning_observations WHERE observation_id = 'obs-1'").fetchone()
    assert order["status"] == "filled"
    assert json.loads(order["payload_json"])["broker_order_reconciled"]["filled_avg_price"] == 101.5
    assert json.loads(signal["gate_json"])["executed_buy"] is True
    assert learning["executed_buy"] == 1
    assert json.loads(learning["execution_json"])["filled_qty"] == 3.0


def test_reconcile_broker_orders_links_fill_to_nearest_prior_signal_only(tmp_path, monkeypatch):
    base_session = _latest_market_session()
    old_session = (base_session - timedelta(days=4)).isoformat()
    new_session = base_session.isoformat()
    plan_created_at = f"{old_session}T14:00:00+00:00"

    local_order = type(
        "LocalOrder",
        (),
        {
            "id": "broker-1",
            "client_order_id": "agente-plan-1",
            "status": "filled",
            "filled_qty": "3",
            "filled_avg_price": "101.5",
            "qty": "3",
            "notional": None,
            "submitted_at": None,
            "filled_at": f"{old_session}T20:00:00+00:00",
            "updated_at": f"{old_session}T20:00:01+00:00",
        },
    )()

    settings = Settings(DATA_DIR=tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.save_broker_order(
        broker_order_id="broker-1",
        plan_id="plan-1",
        cycle_id="cycle-1",
        symbol="AAPL",
        side="buy",
        status="OrderStatus.PENDING_NEW",
        payload={
            "broker_order": {"client_order_id": "agente-plan-1"},
            "plan": {"created_at": plan_created_at},
        },
    )
    store.save_signal_outcome(
        signal_id="run-old:AAPL",
        source_run_id="run-old",
        source="test",
        symbol="AAPL",
        signal_date=old_session,
        decision="approved_buy",
        features={},
        gate={},
        outcome={},
    )
    store.save_signal_outcome(
        signal_id="run-new:AAPL",
        source_run_id="run-new",
        source="test",
        symbol="AAPL",
        signal_date=new_session,
        decision="candidate",
        features={},
        gate={},
        outcome={},
    )
    with store.connect() as conn:
        conn.execute(
            "UPDATE signal_outcomes SET created_at = ?, updated_at = ? WHERE signal_id = ?",
            (f"{old_session}T13:59:00+00:00", f"{old_session}T13:59:00+00:00", "run-old:AAPL"),
        )
        conn.execute(
            "UPDATE signal_outcomes SET created_at = ?, updated_at = ? WHERE signal_id = ?",
            (f"{new_session}T13:59:00+00:00", f"{new_session}T13:59:00+00:00", "run-new:AAPL"),
        )
    store.upsert_learning_observation(
        {
            "observation_id": "obs-old",
            "signal_date": old_session,
            "symbol": "AAPL",
            "source_family": "test",
            "decision": "approved_buy",
        }
    )
    store.upsert_learning_observation(
        {
            "observation_id": "obs-new",
            "signal_date": new_session,
            "symbol": "AAPL",
            "source_family": "test",
            "decision": "candidate",
        }
    )

    class _Factory:
        def __init__(self, _settings):
            pass

        def alpaca_trading_client(self):
            return type("LocalClient", (), {"get_order_by_id": lambda self, _order_id: local_order})()

    monkeypatch.setattr("agente_bolsa.tools.broker_reconciliation.BrokerClientFactory", _Factory)
    monkeypatch.setattr(
        "agente_bolsa.tools.broker_reconciliation.update_signal_outcomes",
        lambda *_args, **_kwargs: {"updated": 0, "signals": 0, "symbols": 0, "warnings": []},
    )

    result = reconcile_broker_orders(settings, store, apply=True)

    assert result["signal_execution_updates"] == 1
    assert result["learning_execution_updates"] == 1
    with store.connect() as conn:
        old_signal = conn.execute("SELECT gate_json FROM signal_outcomes WHERE signal_id = 'run-old:AAPL'").fetchone()
        new_signal = conn.execute("SELECT gate_json FROM signal_outcomes WHERE signal_id = 'run-new:AAPL'").fetchone()
        old_learning = conn.execute(
            "SELECT executed_buy, execution_json FROM learning_observations WHERE observation_id = 'obs-old'"
        ).fetchone()
        new_learning = conn.execute(
            "SELECT executed_buy, execution_json FROM learning_observations WHERE observation_id = 'obs-new'"
        ).fetchone()
    assert json.loads(old_signal["gate_json"])["executed_buy"] is True
    assert json.loads(new_signal["gate_json"] or "{}").get("executed_buy") is not True
    assert old_learning["executed_buy"] == 1
    assert new_learning["executed_buy"] == 0
