from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from agente_bolsa.config import Settings
from agente_bolsa.market_calendar import MarketCalendar
from agente_bolsa.scheduler import (
    _execute_stop_take_exits,
    _exit_policy_v2_runtime_trigger,
    _exit_policy_v2_time_stop_trigger,
    _risk_exit_plan,
)
from agente_bolsa.storage import Store
from agente_bolsa.tools.time_stop_policy import (
    POLICY_VERSION,
    SCHEMA_VERSION,
    TEMPORAL_SEMANTICS,
    evaluate_position_time_stop,
    evaluate_time_stop,
)


def _calendar() -> MarketCalendar:
    calendar = MarketCalendar("XNYS", "Europe/Madrid")
    assert calendar._calendar is not None
    return calendar


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _result(entry: str, evaluation: str):
    return evaluate_time_stop(
        entry_fill_at=entry,
        evaluation_at=evaluation,
        required_completed_sessions=5,
        calendar=_calendar(),
    )


def test_contract_and_entry_eighth_july_requires_close_of_fifteenth():
    before_fifth_close = _result("2026-07-08T16:00:00Z", "2026-07-15T19:59:59Z")
    after_fifth_close = _result("2026-07-08T16:00:00Z", "2026-07-15T20:00:00Z")

    assert before_fifth_close["schema_version"] == SCHEMA_VERSION
    assert before_fifth_close["policy_version"] == POLICY_VERSION
    assert before_fifth_close["time_stop_semantics"] == TEMPORAL_SEMANTICS
    assert before_fifth_close["completed_xnys_sessions_after_entry"] == 4
    assert before_fifth_close["xnys_eligible"] is False
    assert before_fifth_close["first_eligible_session"] == "2026-07-15"
    assert after_fifth_close["completed_xnys_sessions_after_entry"] == 5
    assert after_fifth_close["xnys_eligible"] is True


def test_weekend_and_holiday_are_not_sessions():
    friday = _result("2026-07-10T15:00:00Z", "2026-07-16T20:00:00Z")
    friday_after_fifth = _result("2026-07-10T15:00:00Z", "2026-07-17T20:00:00Z")
    holiday = _result("2026-07-03T15:00:00Z", "2026-07-13T20:00:00Z")

    assert friday["completed_xnys_sessions_after_entry"] == 4
    assert friday["xnys_eligible"] is False
    assert friday_after_fifth["completed_xnys_sessions_after_entry"] == 5
    assert friday_after_fifth["xnys_eligible"] is True
    assert holiday["status"] == "unavailable"
    assert "entry_not_xnys_session" in holiday["warnings"]

    before_second = evaluate_time_stop(
        entry_fill_at="2026-07-02T15:00:00Z",
        evaluation_at="2026-07-06T20:00:00Z",
        required_completed_sessions=2,
        calendar=_calendar(),
    )
    after_second = evaluate_time_stop(
        entry_fill_at="2026-07-02T15:00:00Z",
        evaluation_at="2026-07-07T20:00:00Z",
        required_completed_sessions=2,
        calendar=_calendar(),
    )
    assert before_second["completed_xnys_sessions_after_entry"] == 1
    assert before_second["xnys_eligible"] is False
    assert after_second["xnys_eligible"] is True


def test_entry_before_or_after_close_uses_same_entry_session():
    before_close = _result("2026-07-08T19:59:59Z", "2026-07-15T20:00:00Z")
    after_close = _result("2026-07-08T20:00:01Z", "2026-07-15T20:00:00Z")

    assert before_close["entry_session"] == "2026-07-08"
    assert after_close["entry_session"] == "2026-07-08"
    assert before_close["completed_xnys_sessions_after_entry"] == 5
    assert after_close["completed_xnys_sessions_after_entry"] == 5


def test_early_close_is_not_counted_before_exchange_close():
    calendar = _calendar()
    before_close = evaluate_time_stop(
        entry_fill_at="2026-11-25T15:00:00Z",
        evaluation_at="2026-11-27T17:59:59Z",
        required_completed_sessions=1,
        calendar=calendar,
    )
    at_close = evaluate_time_stop(
        entry_fill_at="2026-11-25T15:00:00Z",
        evaluation_at="2026-11-27T18:00:00Z",
        required_completed_sessions=1,
        calendar=calendar,
    )

    assert before_close["xnys_eligible"] is False
    assert at_close["xnys_eligible"] is True


def test_timestamp_timezones_and_naive_inputs_are_deterministic():
    utc = _result("2026-07-08T16:00:00Z", "2026-07-15T20:00:00Z")
    madrid = _result("2026-07-08T18:00:00+02:00", "2026-07-15T22:00:00+02:00")
    naive = _result("2026-07-08T16:00:00", "2026-07-15T20:00:00")

    assert utc["content_hash"] == madrid["content_hash"]
    assert naive["xnys_eligible"] == utc["xnys_eligible"]
    assert "timestamp_naive_assumed_utc" in naive["warnings"]


def test_dst_transition_is_handled_by_utc_and_exchange_schedule():
    result = _result("2026-03-06T15:00:00Z", "2026-03-13T21:00:00Z")

    assert result["status"] == "available"
    assert result["completed_xnys_sessions_after_entry"] == 5


def test_calendar_unavailable_does_not_authorise_time_stop():
    calendar = _calendar()
    calendar._calendar = None
    result = evaluate_time_stop(
        entry_fill_at="2026-07-08T16:00:00Z",
        evaluation_at="2026-07-15T20:00:00Z",
        required_completed_sessions=5,
        calendar=calendar,
    )

    assert result["status"] == "unavailable"
    assert result["xnys_eligible"] is None
    assert "calendar_unavailable" in result["warnings"]


def test_legacy_shadow_and_same_comparisons_are_explicit():
    legacy_only = _result("2026-07-08T16:00:00Z", "2026-07-13T20:00:00Z")
    same = _result("2026-07-08T16:00:00Z", "2026-07-15T20:00:00Z")

    assert legacy_only["comparison"] == "legacy_only"
    assert same["comparison"] == "same"
    assert legacy_only["legacy_calendar_eligible"] is True
    assert legacy_only["xnys_eligible"] is False


def test_hash_is_stable_for_repeated_evaluation():
    first = _result("2026-07-08T16:00:00Z", "2026-07-15T20:00:00Z")
    second = _result("2026-07-08T16:00:00Z", "2026-07-15T20:00:00Z")

    assert first == second


def test_position_lots_are_not_merged_when_inventory_is_ambiguous():
    result = evaluate_position_time_stop(
        lots=[
            {"broker_order_id": "buy-a", "entry_fill_at": "2026-07-08T16:00:00Z", "filled_qty": 3},
            {"broker_order_id": "buy-b", "entry_fill_at": "2026-07-09T16:00:00Z", "filled_qty": 2},
        ],
        position_qty=5,
        evaluation_at="2026-07-15T20:00:00Z",
        required_completed_sessions=5,
        calendar=_calendar(),
    )

    assert result["status"] == "ambiguous"
    assert "ambiguous_lots" in result["warnings"]
    assert result["xnys_eligible"] is None


def test_verified_lots_are_evaluated_without_fusing_their_clocks():
    result = evaluate_position_time_stop(
        lots=[
            {"broker_order_id": "buy-a", "entry_fill_at": "2026-07-08T16:00:00Z", "open_qty": 3},
            {"broker_order_id": "buy-b", "entry_fill_at": "2026-07-09T16:00:00Z", "open_qty": 2},
        ],
        position_qty=5,
        evaluation_at="2026-07-15T20:00:00Z",
        required_completed_sessions=5,
        calendar=_calendar(),
    )

    assert result["status"] == "available"
    assert result["xnys_eligible"] is False
    assert [item["completed_xnys_sessions_after_entry"] for item in result["lots"]] == [5, 4]


def test_partial_fill_requires_first_fill_evidence():
    missing = evaluate_position_time_stop(
        lots=[{"broker_order_id": "buy-1", "filled_qty": 5, "submitted_qty": 10}],
        position_qty=5,
        evaluation_at="2026-07-15T20:00:00Z",
        required_completed_sessions=5,
        calendar=_calendar(),
    )
    verified = evaluate_position_time_stop(
        lots=[
            {
                "broker_order_id": "buy-1",
                "entry_fill_at": "2026-07-08T16:00:00Z",
                "filled_qty": 5,
                "submitted_qty": 10,
            }
        ],
        position_qty=5,
        evaluation_at="2026-07-15T20:00:00Z",
        required_completed_sessions=5,
        calendar=_calendar(),
    )

    assert missing["status"] == "unavailable"
    assert verified["status"] == "available"


def test_missing_fill_never_uses_created_at_as_fallback():
    result = evaluate_position_time_stop(
        lots=[{"broker_order_id": "buy-1", "created_at": "2026-07-01T16:00:00Z", "filled_qty": 1}],
        position_qty=1,
        evaluation_at="2026-07-15T20:00:00Z",
        required_completed_sessions=5,
        calendar=_calendar(),
    )

    assert result["status"] == "unavailable"


def test_short_position_is_not_time_stop_eligible():
    result = evaluate_position_time_stop(
        lots=[{"entry_fill_at": "2026-07-08T16:00:00Z", "filled_qty": 1}],
        position_qty=1,
        side="short",
        evaluation_at="2026-07-15T20:00:00Z",
        required_completed_sessions=5,
        calendar=_calendar(),
    )

    assert result["status"] == "unavailable"
    assert "unsupported_side" in result["warnings"]


def test_scheduler_uses_xnys_and_preserves_return_gate(tmp_path):
    settings = Settings(
        DATA_DIR=tmp_path,
        EXIT_POLICY_V2_ENABLED=True,
        EXIT_POLICY_V2_TIME_STOP_DAYS=5,
        EXIT_POLICY_V2_TIME_STOP_MIN_RETURN=0.0,
    )
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    source = {
        "plan": {"plan_id": "plan-1"},
        "lots": [{"broker_order_id": "buy-1", "entry_fill_at": "2026-07-08T16:00:00Z", "filled_qty": 1}],
    }
    position = SimpleNamespace(avg_entry_price=100.0, qty=1.0, current_price=99.0, unrealized_plpc=-0.01)

    before = _exit_policy_v2_runtime_trigger(
        settings,
        store,
        symbol="AAPL",
        position=position,
        source=source,
        payload={"entry_price": 100.0, "stop_loss": 95.0},
        calendar=_calendar(),
        evaluation_at=_dt("2026-07-14T20:00:00Z"),
    )
    after = _exit_policy_v2_runtime_trigger(
        settings,
        store,
        symbol="AAPL",
        position=position,
        source=source,
        payload={"entry_price": 100.0, "stop_loss": 95.0},
        calendar=_calendar(),
        evaluation_at=_dt("2026-07-15T20:00:00Z"),
    )

    assert before is None
    assert after["trigger"] == "time_stop_v2"
    assert after["time_stop_evidence"]["time_stop_semantics"] == TEMPORAL_SEMANTICS
    assert after["time_stop_evidence"]["return_condition_met"] is True


def test_positive_return_does_not_trigger_after_fifth_session(tmp_path):
    settings = Settings(DATA_DIR=tmp_path, EXIT_POLICY_V2_ENABLED=True, EXIT_POLICY_V2_TIME_STOP_DAYS=5)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    result = _exit_policy_v2_runtime_trigger(
        settings,
        store,
        symbol="AAPL",
        position=SimpleNamespace(avg_entry_price=100.0, qty=1.0, current_price=102.0, unrealized_plpc=0.02),
        source={"plan": {"plan_id": "plan-1"}, "lots": [{"entry_fill_at": "2026-07-08T16:00:00Z", "filled_qty": 1}]},
        payload={"entry_price": 100.0, "stop_loss": 95.0},
        calendar=_calendar(),
        evaluation_at=_dt("2026-07-15T20:00:00Z"),
    )

    assert result is None
    evidence = store.get_runtime_value("time_stop_v2_evidence:AAPL")
    assert evidence["xnys_eligible"] is True
    assert evidence["return_condition_met"] is False


def test_existing_time_stop_wrapper_requires_verified_fill():
    settings = Settings(DATA_DIR=".", EXIT_POLICY_V2_ENABLED=True, EXIT_POLICY_V2_TIME_STOP_DAYS=5)
    position = SimpleNamespace(current_price=101.0, unrealized_plpc=-0.002)

    trigger, level = _exit_policy_v2_time_stop_trigger(
        settings,
        position=position,
        source_created_at="2026-07-01T16:00:00Z",
        evaluation_at=_dt("2026-07-15T20:00:00Z"),
        calendar=_calendar(),
    )

    assert trigger is None
    assert level == 0.0


def test_p43a_historical_reproduction_and_current_open_positions():
    cases = [
        ("AIZ", "2026-07-08T16:00:00Z", "2026-07-13T20:00:00Z"),
        ("CRWD", "2026-07-08T16:00:00Z", "2026-07-13T20:00:00Z"),
        ("STT", "2026-07-09T16:00:00Z", "2026-07-14T20:00:00Z"),
        ("SBUX", "2026-07-09T16:00:00Z", "2026-07-14T20:00:00Z"),
        ("EXPE", "2026-07-09T16:00:00Z", "2026-07-14T20:00:00Z"),
        ("ALL", "2026-07-08T16:00:00Z", "2026-07-14T20:00:00Z"),
        ("EBAY", "2026-07-10T14:14:42Z", "2026-07-15T20:00:00Z"),
    ]

    for symbol, entry, evaluation in cases:
        result = _result(entry, evaluation)
        assert result["legacy_calendar_eligible"] is True, symbol
        assert result["xnys_eligible"] is False, symbol
        assert result["comparison"] == "legacy_only", symbol

    crwd_during_fourth = _result("2026-07-08T16:00:00Z", "2026-07-14T20:00:00Z")
    assert crwd_during_fourth["xnys_eligible"] is False


def test_ddog_and_anet_are_not_eligible_until_close_of_21_july():
    for symbol in ("DDOG", "ANET"):
        before = _result("2026-07-14T16:00:00Z", "2026-07-20T20:00:00Z")
        after = _result("2026-07-14T16:00:00Z", "2026-07-21T20:00:00Z")
        assert before["xnys_eligible"] is False, symbol
        assert after["xnys_eligible"] is True, symbol


def test_store_exposes_fill_not_created_at_and_rejects_partial_without_first_fill(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_broker_order(
        broker_order_id="buy-full",
        plan_id="plan-full",
        cycle_id="cycle-1",
        symbol="AAPL",
        side="buy",
        status="filled",
        payload={
            "plan": {"plan_id": "plan-full"},
            "broker_order": {
                "id": "buy-full",
                "qty": 1,
                "filled_qty": 1,
                "filled_at": "2026-07-08T16:00:00Z",
            },
        },
    )
    store.save_broker_order(
        broker_order_id="buy-partial",
        plan_id="plan-partial",
        cycle_id="cycle-1",
        symbol="MSFT",
        side="buy",
        status="partially_filled",
        payload={
            "plan": {"plan_id": "plan-partial"},
            "broker_order": {
                "id": "buy-partial",
                "qty": 10,
                "filled_qty": 5,
                "filled_at": "2026-07-08T16:00:00Z",
            },
        },
    )

    lots = store.executed_buy_lots_by_symbol()
    assert lots["AAPL"][0]["entry_fill_at"] == "2026-07-08T16:00:00Z"
    assert lots["AAPL"][0]["created_at"] != lots["AAPL"][0]["entry_fill_at"]
    assert lots["MSFT"][0]["entry_fill_at"] is None


def test_store_excludes_unfilled_buy_orders_from_position_lots(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_broker_order(
        broker_order_id="buy-filled",
        plan_id="plan-filled",
        cycle_id="cycle-1",
        symbol="AAPL",
        side="buy",
        status="filled",
        payload={
            "broker_order": {
                "id": "buy-filled",
                "qty": 1,
                "filled_qty": 1,
                "filled_at": "2026-07-08T16:00:00Z",
            }
        },
    )
    store.save_broker_order(
        broker_order_id="buy-rejected",
        plan_id="plan-rejected",
        cycle_id="cycle-1",
        symbol="AAPL",
        side="buy",
        status="rejected",
        payload={"broker_order": {"id": "buy-rejected", "qty": 1, "filled_qty": 0}},
    )

    lots = store.executed_buy_lots_by_symbol()
    assert [lot["broker_order_id"] for lot in lots["AAPL"]] == ["buy-filled"]


def test_time_stop_evidence_is_fail_open_and_risk_plan_is_versioned(tmp_path, monkeypatch):
    settings = Settings(DATA_DIR=tmp_path, EXIT_POLICY_V2_ENABLED=True, EXIT_POLICY_V2_TIME_STOP_DAYS=5)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    source = {"plan": {"plan_id": "plan-1"}, "lots": [{"entry_fill_at": "2026-07-08T16:00:00Z", "filled_qty": 1}]}
    position = SimpleNamespace(avg_entry_price=100.0, qty=1.0, current_price=99.0, unrealized_plpc=-0.01)

    def _boom(**_kwargs):
        raise RuntimeError("calendar fixture failed")

    monkeypatch.setattr("agente_bolsa.scheduler._evaluate_time_stop_v2_position", _boom)
    assert _exit_policy_v2_runtime_trigger(
        settings,
        store,
        symbol="AAPL",
        position=position,
        source=source,
        payload={"entry_price": 100.0, "stop_loss": 95.0},
        calendar=_calendar(),
        evaluation_at=_dt("2026-07-15T20:00:00Z"),
    ) is None
    evidence = store.get_runtime_value("time_stop_v2_evidence:AAPL")
    assert evidence["status"] == "unavailable"
    assert evidence["xnys_eligible"] is None

    plan = _risk_exit_plan(
        symbol="AAPL",
        notional=99.0,
        qty=1.0,
        current_price=99.0,
        trigger="time_stop_v2",
        level=99.0,
        source_plan={"plan_id": "plan-1", "payload": {"stop_loss": 95.0}},
        time_stop_evidence={"comparison": "legacy_only", "status": "available"},
    )
    policy = plan["payload"]["risk_decision"]["checks"]["exit_policy_v2"]
    assert policy["exit_policy_version"] == POLICY_VERSION
    assert policy["time_stop_semantics"] == TEMPORAL_SEMANTICS


def test_non_time_stop_risk_plan_has_no_temporal_policy_fields():
    plan = _risk_exit_plan(
        symbol="AAPL",
        notional=99.0,
        qty=1.0,
        current_price=99.0,
        trigger="stop_loss",
        level=99.0,
        source_plan={"plan_id": "plan-1", "payload": {"stop_loss": 99.0}},
    )
    policy = plan["payload"]["risk_decision"]["checks"]["exit_policy_v2"]
    assert policy == {"enabled": False, "trigger": "stop_loss"}


def test_portfolio_watch_integration_uses_fill_and_keeps_stop_loss_operational(tmp_path, monkeypatch):
    settings = Settings(
        DATA_DIR=tmp_path,
        TRADING_MODE="paper",
        ALPACA_PAPER=True,
        AUTO_PAPER_TRADING=True,
        REQUIRE_HUMAN_APPROVAL=False,
        EXIT_POLICY_V2_ENABLED=True,
        EXIT_POLICY_V2_TIME_STOP_DAYS=5,
    )
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.save_broker_order(
        broker_order_id="buy-aapl",
        plan_id="plan-aapl",
        cycle_id="cycle-1",
        symbol="AAPL",
        side="buy",
        status="filled",
        payload={
            "plan": {"plan_id": "plan-aapl", "payload": {"entry_price": 100.0, "stop_loss": 95.0, "take_profit": 110.0}},
            "broker_order": {"id": "buy-aapl", "qty": 1, "filled_qty": 1, "filled_at": "2026-07-08T16:00:00Z"},
        },
    )
    portfolio = SimpleNamespace(
        open_orders=[],
        positions=[SimpleNamespace(symbol="AAPL", qty=1.0, market_value=99.0, current_price=99.0, avg_entry_price=100.0, unrealized_plpc=-0.01)],
    )

    class Reporter:
        def __init__(self):
            self.events = []

        def emit(self, *args, **kwargs):
            self.events.append((args, kwargs))

    submitted = []

    def fake_submit(_settings, plan, *, client_order_id):
        submitted.append(plan)
        return {"id": "sell-aapl", "status": "accepted", "client_order_id": client_order_id}

    monkeypatch.setattr("agente_bolsa.scheduler.submit_paper_order_plan", fake_submit)
    reporter = Reporter()
    before = _execute_stop_take_exits(
        settings,
        store,
        reporter,
        "watch-before",
        portfolio,
        calendar=_calendar(),
        evaluation_at=_dt("2026-07-14T20:00:00Z"),
    )
    assert before == []
    assert submitted == []

    after = _execute_stop_take_exits(
        settings,
        store,
        reporter,
        "watch-after",
        portfolio,
        calendar=_calendar(),
        evaluation_at=_dt("2026-07-15T20:00:00Z"),
    )
    assert after[0]["trigger"] == "time_stop_v2"
    assert submitted[0]["payload"]["risk_decision"]["checks"]["exit_policy_v2"]["time_stop_semantics"] == TEMPORAL_SEMANTICS

    stop_portfolio = SimpleNamespace(
        open_orders=[],
        positions=[SimpleNamespace(symbol="AAPL", qty=1.0, market_value=94.0, current_price=94.0, avg_entry_price=100.0, unrealized_plpc=-0.06)],
    )
    stop_exits = _execute_stop_take_exits(
        settings,
        store,
        reporter,
        "watch-stop",
        stop_portfolio,
        calendar=_calendar(),
        evaluation_at=_dt("2026-07-09T20:00:00Z"),
    )
    assert stop_exits[0]["trigger"] == "stop_loss"
