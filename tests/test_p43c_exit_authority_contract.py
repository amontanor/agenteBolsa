from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

SCHEMA_DECISION = "p-l43c.time-stop-exit-authority.v1"
SCHEMA_LINK = "p-l43c.time-stop-exit-order-link.v1"
ACTIVE_AUTHORITIES = {"legacy_calendar_days", "guarded_xnys", "active_xnys", "other", "unavailable"}
EXCLUDED_FROM_HASH = {
    "captured_at",
    "observed_at",
    "generated_at",
    "created_at",
    "content_hash",
    "decision_id",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _stable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _stable(item)
            for key, item in value.items()
            if str(key) not in EXCLUDED_FROM_HASH
        }
    if isinstance(value, list):
        return [_stable(item) for item in value]
    return value


def _content_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(_stable(value)).encode("utf-8")).hexdigest()


def _decision(
    *,
    decision_time: str = "2026-07-21T13:30:00+00:00",
    cycle_id: str = "watch-test-1",
    position_identity: str | None = "position-buy-a",
    buy_broker_order_id: str | None = "buy-order-a",
    source_plan_id: str | None = "plan-buy-a",
    source_plan_ids: list[str] | None = None,
    plan_id: str | None = "risk_exit-test-a",
    symbol: str = "AAPL",
    qty: float = 1.0,
    active_authority: str = "legacy_calendar_days",
    active_policy_version: str | None = "legacy-calendar-days.v1",
    active_eligible: bool | None = True,
    active_reason_code: str | None = "legacy_time_stop_activated",
    trigger: str = "time_stop_v2",
    shadow_authority: str = "xnys_time_stop",
    shadow_policy_version: str | None = "time_stop_xnys.v1",
    shadow_only: bool = True,
    shadow_eligible: bool | None = False,
    comparison_status: str = "legacy_only",
    fill_authority: str | None = "first_fill_at",
    buy_fill_at: str | None = "2026-07-14T13:30:00+00:00",
    status: str | None = None,
    captured_at: str = "2026-07-21T13:30:00.100000+00:00",
    observed_at: str | None = None,
) -> dict[str, Any]:
    source_plan_ids = source_plan_ids if source_plan_ids is not None else [source_plan_id] if source_plan_id else []
    unique_source_plans = {item for item in source_plan_ids if item}
    authority_status = "available"
    reason_codes: list[str] = []
    if active_authority not in ACTIVE_AUTHORITIES:
        raise ValueError(f"invalid active_authority: {active_authority}")
    if trigger in {"stop_loss", "take_profit"}:
        authority_status = "not_applicable"
        active_authority = "other"
        active_policy_version = None
        active_eligible = None
        reason_codes.append("not_a_time_stop")
    elif len(unique_source_plans) > 1:
        authority_status = "ambiguous"
        reason_codes.append("duplicate_source_plan_id")
    elif active_eligible is True and not source_plan_id:
        authority_status = "unavailable"
        reason_codes.append("missing_source_plan_id")
    elif active_eligible is True and not position_identity:
        authority_status = "unavailable"
        reason_codes.append("missing_position_identity")
    elif active_eligible is True and not buy_broker_order_id:
        authority_status = "unavailable"
        reason_codes.append("missing_buy_broker_order_id")
    elif fill_authority in {None, "", "unavailable"} or not buy_fill_at:
        authority_status = "unavailable"
        reason_codes.append("fill_authority_unavailable")
    elif active_eligible is not True:
        authority_status = "not_generated"
        reason_codes.append("active_policy_not_eligible")

    if authority_status == "not_generated":
        plan_id = None
    if authority_status == "ambiguous":
        reason_codes.append("no_fifo_or_symbol_fallback")
    if status is None:
        status = "captured" if authority_status == "available" else authority_status

    payload = {
        "schema_version": SCHEMA_DECISION,
        "revision": 1,
        "decided_at": decision_time,
        "cycle_id": cycle_id,
        "watch_id": cycle_id,
        "position_identity": position_identity,
        "lot_id": position_identity,
        "buy_broker_order_id": buy_broker_order_id,
        "source_plan_id": source_plan_id,
        "plan_id": plan_id,
        "symbol": symbol,
        "qty": qty,
        "active_authority": active_authority,
        "active_policy_version": active_policy_version,
        "active_result": "eligible" if active_eligible is True else "ineligible" if active_eligible is False else "unavailable",
        "active_eligible": active_eligible,
        "active_reason_code": active_reason_code,
        "trigger": trigger,
        "shadow_authority": shadow_authority,
        "shadow_policy_version": shadow_policy_version,
        "shadow_only": shadow_only,
        "shadow_result": "eligible" if shadow_eligible is True else "ineligible" if shadow_eligible is False else "unavailable",
        "shadow_eligible": shadow_eligible,
        "comparison_status": comparison_status,
        "fill_authority": fill_authority,
        "buy_fill_at": buy_fill_at,
        "legacy_inputs": {"calendar": "legacy_calendar_days", "age_days": 5},
        "xnys_inputs": {
            "completed_sessions": 0 if shadow_eligible is False else None,
            "required_sessions": 5,
            "logical_eligibility_at": "2026-07-23T20:00:00+00:00",
            "first_actionable_market_time": "2026-07-24T13:30:00+00:00",
        },
        "data_quality": "verified" if authority_status == "available" else "partial",
        "reason_codes": reason_codes,
        "authority_status": authority_status,
        "status": status,
    }
    payload["content_hash"] = _content_hash(payload)
    payload["decision_id"] = f"decision_{payload['content_hash'][:32]}"
    payload["captured_at"] = captured_at
    if observed_at is not None:
        payload["observed_at"] = observed_at
    return payload


def _request_fingerprint(request: Mapping[str, Any]) -> str:
    safe = {
        str(key): value
        for key, value in request.items()
        if str(key).lower() not in {"api_key", "secret", "token", "password", "authorization"}
    }
    return hashlib.sha256(_canonical_json(_stable(safe)).encode("utf-8")).hexdigest()


def _order_link(
    decision: Mapping[str, Any],
    *,
    broker_order_id: str | None,
    client_order_id: str | None,
    submitted_at: str,
    submission_status: str,
    request: Mapping[str, Any],
    error_reason: str | None = None,
    captured_at: str = "2026-07-21T13:30:01+00:00",
) -> dict[str, Any]:
    identity = broker_order_id or client_order_id
    if not identity:
        raise ValueError("order link requires broker_order_id or client_order_id")
    payload = {
        "schema_version": SCHEMA_LINK,
        "revision": 1,
        "event_id": f"exit_order_link:{identity}",
        "decision_id": decision["decision_id"],
        "decision_content_hash": decision["content_hash"],
        "plan_id": decision.get("plan_id"),
        "source_plan_id": decision.get("source_plan_id"),
        "position_identity": decision.get("position_identity"),
        "broker_order_id": broker_order_id,
        "client_order_id": client_order_id,
        "submitted_at": submitted_at,
        "submission_status": submission_status,
        "error_reason": error_reason,
        "active_authority": decision.get("active_authority"),
        "request_fingerprint": _request_fingerprint(request),
    }
    payload["content_hash"] = _content_hash(payload)
    payload["captured_at"] = captured_at
    return payload


class _AuthorityEventStore:
    """Test-only append-only analogue of agent_events."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with sqlite3.connect(path, timeout=5) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS agent_events ("
                "event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL)"
            )

    def record(self, event_type: str, payload: Mapping[str, Any]) -> str:
        event_id = str(payload["event_id"] if "event_id" in payload else f"exit_authority:{payload['decision_id']}")
        encoded = _canonical_json(payload)
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT payload_json FROM agent_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            if existing is not None:
                existing_payload = json.loads(existing[0])
                if existing_payload.get("content_hash") == payload.get("content_hash"):
                    connection.commit()
                    return "idempotent"
                conflict_id = f"{event_id}:conflict:{payload['content_hash']}"
                try:
                    connection.execute(
                        "INSERT INTO agent_events (event_id,event_type,payload_json,created_at) VALUES (?,?,?,?)",
                        (conflict_id, f"{event_type}_conflict", _canonical_json({
                            "event_id": conflict_id,
                            "original_event_id": event_id,
                            "existing_content_hash": existing_payload.get("content_hash"),
                            "candidate_content_hash": payload.get("content_hash"),
                        }), "2026-07-21T13:30:02+00:00"),
                    )
                except sqlite3.IntegrityError:
                    pass
                connection.commit()
                return "conflict"
            connection.execute(
                "INSERT INTO agent_events (event_id,event_type,payload_json,created_at) VALUES (?,?,?,?)",
                (event_id, event_type, encoded, "2026-07-21T13:30:02+00:00"),
            )
            connection.commit()
            return "inserted"

    def events(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT event_id,event_type,payload_json FROM agent_events ORDER BY event_id"
            ).fetchall()
        return [{"event_id": row[0], "event_type": row[1], "payload": json.loads(row[2])} for row in rows]


def _persist_after_submit(
    submit: Callable[[], Mapping[str, Any]],
    store: _AuthorityEventStore,
    decision: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
) -> tuple[Mapping[str, Any], dict[str, Any]]:
    order = submit()
    link = _order_link(
        decision,
        broker_order_id=order.get("broker_order_id"),
        client_order_id=order.get("client_order_id"),
        submitted_at=str(order["submitted_at"]),
        submission_status=str(order["status"]),
        request=request,
        error_reason=order.get("error_reason"),
    )
    try:
        store.record("exit_authority_decision", {**decision, "event_id": f"exit_authority:{decision['decision_id']}"})
        store.record("exit_order_link", link)
    except Exception as exc:  # noqa: BLE001 - characterization of fail-open telemetry.
        link["persistence_status"] = "unavailable"
        link["persistence_error"] = type(exc).__name__
    return order, link


FIVE_LEGACY_ONLY = [
    ("DDOG", "buy-ddog", "plan-ddog", "risk-ddog", "watch-ddog"),
    ("BNY", "buy-bny", "plan-bny", "risk-bny", "watch-bny"),
    ("JPM", "buy-jpm", "plan-jpm", "risk-jpm", "watch-jpm"),
    ("BAC", "buy-bac", "plan-bac", "risk-bac", "watch-bac"),
    ("CRWD", "buy-crwd", "plan-crwd", "risk-crwd", "watch-crwd"),
]


@pytest.mark.parametrize("symbol,buy_id,source_plan,plan_id,cycle_id", FIVE_LEGACY_ONLY)
def test_five_sanitized_legacy_only_cases_have_distinct_authority(symbol, buy_id, source_plan, plan_id, cycle_id):
    decision = _decision(
        symbol=symbol,
        buy_broker_order_id=buy_id,
        source_plan_id=source_plan,
        plan_id=plan_id,
        cycle_id=cycle_id,
    )
    assert decision["schema_version"] == SCHEMA_DECISION
    assert decision["active_authority"] == "legacy_calendar_days"
    assert decision["active_eligible"] is True
    assert decision["shadow_authority"] == "xnys_time_stop"
    assert decision["shadow_only"] is True
    assert decision["shadow_eligible"] is False
    assert decision["comparison_status"] == "legacy_only"
    assert decision["trigger"] == "time_stop_v2"
    assert decision["authority_status"] == "available"
    assert decision["plan_id"] == plan_id


def test_legacy_eligible_xnys_unavailable_still_has_legacy_authority():
    decision = _decision(shadow_eligible=None, comparison_status="unavailable")
    assert decision["active_authority"] == "legacy_calendar_days"
    assert decision["active_eligible"] is True
    assert decision["shadow_eligible"] is None
    assert decision["authority_status"] == "available"


def test_xnys_shadow_cannot_create_an_exit_when_legacy_is_false():
    decision = _decision(
        active_eligible=False,
        active_reason_code="legacy_not_eligible",
        shadow_eligible=True,
        comparison_status="xnys_only",
    )
    assert decision["active_authority"] == "legacy_calendar_days"
    assert decision["authority_status"] == "not_generated"
    assert decision["plan_id"] is None


def test_both_eligible_still_records_legacy_as_active_authority():
    decision = _decision(active_eligible=True, shadow_eligible=True, comparison_status="both_eligible")
    assert decision["active_authority"] == "legacy_calendar_days"
    assert decision["authority_status"] == "available"


def test_neither_eligible_has_no_exit_plan():
    decision = _decision(active_eligible=False, shadow_eligible=False, comparison_status="neither")
    assert decision["plan_id"] is None
    assert decision["status"] == "not_generated"


@pytest.mark.parametrize("trigger", ["stop_loss", "take_profit"])
def test_non_time_stop_triggers_are_not_applicable_to_time_stop_authority(trigger):
    decision = _decision(trigger=trigger)
    assert decision["authority_status"] == "not_applicable"
    assert decision["active_authority"] == "other"
    assert decision["active_policy_version"] is None


def test_rebuys_same_symbol_require_distinct_exact_identity():
    first = _decision(
        symbol="AAPL",
        position_identity="position-buy-a",
        buy_broker_order_id="buy-a",
        source_plan_id="plan-a",
        plan_id="risk-a",
    )
    second = _decision(
        symbol="AAPL",
        position_identity="position-buy-b",
        buy_broker_order_id="buy-b",
        source_plan_id="plan-b",
        plan_id="risk-b",
    )
    assert first["decision_id"] != second["decision_id"]
    assert first["position_identity"] != second["position_identity"]
    assert first["source_plan_id"] != second["source_plan_id"]


def test_missing_or_duplicate_source_plan_is_not_recovered_by_symbol_or_fifo():
    missing = _decision(source_plan_id=None, source_plan_ids=[])
    duplicate = _decision(source_plan_id="plan-a", source_plan_ids=["plan-a", "plan-b"])
    assert missing["authority_status"] == "unavailable"
    assert "missing_source_plan_id" in missing["reason_codes"]
    assert duplicate["authority_status"] == "ambiguous"
    assert "no_fifo_or_symbol_fallback" in duplicate["reason_codes"]


def test_partial_buy_without_first_fill_is_unavailable():
    decision = _decision(fill_authority=None, buy_fill_at=None)
    assert decision["authority_status"] == "unavailable"
    assert decision["active_eligible"] is True
    assert "fill_authority_unavailable" in decision["reason_codes"]


@pytest.mark.parametrize("status", ["pending", "rejected", "cancelled", "failed"])
def test_pending_rejected_cancelled_orders_are_linked_without_authorizing_future_fill(tmp_path, status):
    decision = _decision()
    store = _AuthorityEventStore(tmp_path / f"{status}.sqlite3")
    order = {"broker_order_id": f"sell-{status}", "client_order_id": f"client-{status}", "status": status, "submitted_at": "2026-07-21T13:30:01Z"}
    _, link = _persist_after_submit(lambda: order, store, decision, request={"method": "close_position", "symbol": "AAPL"})
    assert link["submission_status"] == status
    assert link["decision_id"] == decision["decision_id"]
    assert len(store.events()) == 2


def test_failed_submission_link_preserves_error_reason():
    decision = _decision()
    link = _order_link(
        decision,
        broker_order_id=None,
        client_order_id="client-failed",
        submitted_at="2026-07-21T13:30:01Z",
        submission_status="failed",
        error_reason="broker_timeout",
        request={"method": "close_position", "symbol": "AAPL"},
    )
    assert link["submission_status"] == "failed"
    assert link["error_reason"] == "broker_timeout"
    assert link["broker_order_id"] is None


def test_capture_can_be_carried_in_local_plan_without_changing_broker_request():
    decision = _decision()
    local_plan = {
        "plan_id": decision["plan_id"],
        "payload": {"risk_decision": {"checks": {"exit_authority_capture": decision}}},
    }
    broker_request_before = {"method": "close_position", "symbol": "AAPL"}
    broker_request_after = dict(broker_request_before)
    assert local_plan["payload"]["risk_decision"]["checks"]["exit_authority_capture"]["decision_id"] == decision["decision_id"]
    assert broker_request_after == broker_request_before


def test_authority_payload_contains_no_future_outcomes_or_secrets():
    decision = _decision()
    link = _order_link(
        decision,
        broker_order_id="sell-1",
        client_order_id="client-1",
        submitted_at="2026-07-21T13:30:01Z",
        submission_status="filled",
        request={"method": "close_position", "symbol": "AAPL", "api_key": "secret"},
    )
    encoded = json.dumps({"decision": decision, "link": link}).lower()
    for forbidden in ("pnl", "mfe", "mae", "outcome", "first_hit", "prompt", "llm", "secret"):
        assert forbidden not in encoded


def test_broker_submission_exception_does_not_persist_a_success_link(tmp_path):
    decision = _decision()
    store = _AuthorityEventStore(tmp_path / "submission-error.sqlite3")

    def submit() -> Mapping[str, Any]:
        raise RuntimeError("paper submission unavailable")

    with pytest.raises(RuntimeError, match="paper submission unavailable"):
        _persist_after_submit(submit, store, decision, request={"method": "close_position", "symbol": "AAPL"})
    assert store.events() == []


def test_capture_is_created_before_post_submit_persistence(tmp_path):
    decision = _decision(decision_time="2026-07-21T13:30:00Z", captured_at="2026-07-21T13:30:00.010Z")
    store = _AuthorityEventStore(tmp_path / "temporal.sqlite3")
    order, link = _persist_after_submit(
        lambda: {"broker_order_id": "sell-1", "client_order_id": "client-1", "status": "filled", "submitted_at": "2026-07-21T13:30:01Z"},
        store,
        decision,
        request={"method": "close_position", "symbol": "AAPL"},
    )
    assert decision["decided_at"] < order["submitted_at"]
    assert decision["decided_at"] < link["submitted_at"]
    assert [item["event_type"] for item in store.events()] == ["exit_authority_decision", "exit_order_link"]


def test_persistence_failure_is_fail_open_and_does_not_change_active_result():
    decision = _decision()
    active_request = {"method": "close_position", "symbol": "AAPL", "client_order_id": "client-1"}
    calls: list[Mapping[str, Any]] = []

    class BrokenStore:
        def record(self, *_args: Any, **_kwargs: Any) -> str:
            raise OSError("telemetry unavailable")

    result = {"broker_order_id": "sell-1", "client_order_id": "client-1", "status": "filled", "submitted_at": "2026-07-21T13:30:01Z"}

    def submit() -> Mapping[str, Any]:
        calls.append(active_request)
        return result

    submitted, link = _persist_after_submit(submit, BrokenStore(), decision, request=active_request)
    assert submitted == result
    assert calls[-1] == active_request
    assert link["persistence_status"] == "unavailable"


def test_request_fingerprint_preserves_broker_call_and_excludes_secrets():
    before = {"method": "close_position", "symbol": "AAPL", "client_order_id": "client-1"}
    after = dict(before)
    after_with_secret = {**after, "api_key": "secret-value", "authorization": "bearer-secret"}
    decision = _decision()
    link_before = _order_link(decision, broker_order_id="sell-1", client_order_id="client-1", submitted_at="2026-07-21T13:30:01Z", submission_status="filled", request=before)
    link_after = _order_link(decision, broker_order_id="sell-1", client_order_id="client-1", submitted_at="2026-07-21T13:30:01Z", submission_status="filled", request=after_with_secret)
    assert before == after
    assert link_before["request_fingerprint"] == link_after["request_fingerprint"]
    assert "secret-value" not in json.dumps(link_after)


def test_hash_is_stable_when_captured_at_and_json_order_change():
    first = _decision(captured_at="2026-07-21T13:30:00.001Z", observed_at="2026-07-21T13:30:00.002Z")
    second = dict(reversed(list(first.items())))
    second["captured_at"] = "2026-07-21T13:31:00.001Z"
    second["observed_at"] = "2026-07-21T13:31:00.002Z"
    second_without_hash = {key: value for key, value in second.items() if key != "content_hash"}
    assert first["content_hash"] == _content_hash(second_without_hash)
    assert first["decision_id"] == second["decision_id"]


def test_same_content_is_idempotent_and_different_content_is_conflict(tmp_path):
    store = _AuthorityEventStore(tmp_path / "append-only.sqlite3")
    decision = _decision()
    event = {**decision, "event_id": f"exit_authority:{decision['decision_id']}"}
    assert store.record("exit_authority_decision", event) == "inserted"
    assert store.record("exit_authority_decision", dict(event)) == "idempotent"
    changed = {**event, "active_reason_code": "changed"}
    changed["content_hash"] = _content_hash(changed)
    assert store.record("exit_authority_decision", changed) == "conflict"
    events = store.events()
    assert len(events) == 2
    assert events[0]["event_type"] == "exit_authority_decision"
    assert events[1]["event_type"] == "exit_authority_decision_conflict"


def test_retry_does_not_create_two_canonical_authorities(tmp_path):
    store = _AuthorityEventStore(tmp_path / "retry.sqlite3")
    decision = _decision()
    event = {**decision, "event_id": f"exit_authority:{decision['decision_id']}"}
    assert store.record("exit_authority_decision", event) == "inserted"
    assert store.record("exit_authority_decision", event) == "idempotent"
    assert [item for item in store.events() if item["event_type"] == "exit_authority_decision"] == [
        {"event_id": event["event_id"], "event_type": "exit_authority_decision", "payload": event}
    ]


def test_concurrent_same_content_is_inserted_once_and_not_locked(tmp_path):
    store = _AuthorityEventStore(tmp_path / "concurrent.sqlite3")
    decision = _decision()
    event = {**decision, "event_id": f"exit_authority:{decision['decision_id']}"}
    barrier = threading.Barrier(2)
    results: list[str] = []
    errors: list[BaseException] = []

    def writer() -> None:
        try:
            barrier.wait()
            results.append(store.record("exit_authority_decision", event))
        except BaseException as exc:  # pragma: no cover - assertion below reports unexpected thread failures.
            errors.append(exc)

    threads = [threading.Thread(target=writer) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert sorted(results) == ["idempotent", "inserted"]
    assert len(store.events()) == 1
