from __future__ import annotations

from copy import deepcopy

from agente_bolsa.tools.controlled_position_adds import evaluate_controlled_position_add


def _context() -> dict:
    return {
        "symbol": "AAPL",
        "position": {
            "symbol": "AAPL",
            "qty": 100,
            "market_value": 4_000,
            "current_price": 100,
            "unrealized_pl": 250,
        },
        "prior_fill": {
            "symbol": "AAPL",
            "side": "buy",
            "status": "filled",
            "broker_order_id": "ord-old",
            "signal_id": "sig-old",
            "signal_capture_id": "cap-old",
            "filled_qty": 100,
            "filled_at": "2026-10-05T15:00:00+00:00",
            "session_date": "2026-10-05",
            "lineage_status": "verified",
        },
        "new_signal": {
            "side": "buy",
            "signal_id": "sig-new",
            "signal_capture_id": "cap-new",
            "captured_at": "2026-10-08T14:00:00+00:00",
            "session_date": "2026-10-08",
        },
        "thesis": {"valid": True},
        "gates": {"valid": True},
        "session_carrier": {
            "calendar": "XNYS",
            "current_session_date": "2026-10-08",
            "completed_sessions": [
                {
                    "session_date": "2026-10-06",
                    "status": "completed",
                    "close_utc": "2026-10-06T20:00:00+00:00",
                },
                {
                    "session_date": "2026-10-07",
                    "status": "completed",
                    "close_utc": "2026-10-07T20:00:00+00:00",
                },
            ],
        },
        "broker": {
            "provider": "alpaca",
            "canonical_bracket": {
                "supported": True,
                "verified": True,
                "supports_parent_legs": True,
                "route": "canonical_bracket",
            },
        },
        "existing_protection": {
            "symbol": "AAPL",
            "status": "confirmed",
            "protected_qty": 100,
            "lot_filled_qty": 100,
            "parent_order_id": "ord-old",
            "oco_group_id": "oco-old",
            "legs": [
                {
                    "id": "stop-old",
                    "symbol": "AAPL",
                    "side": "sell",
                    "qty": 100,
                    "role": "stop_loss",
                    "status": "confirmed",
                    "parent_order_id": "ord-old",
                    "oco_group_id": "oco-old",
                },
                {
                    "id": "take-old",
                    "symbol": "AAPL",
                    "side": "sell",
                    "qty": 100,
                    "role": "take_profit",
                    "status": "confirmed",
                    "parent_order_id": "ord-old",
                    "oco_group_id": "oco-old",
                },
            ],
        },
        "add_qty": 10,
        "add_price": 100,
        "equity": 100_000,
        "cash_available": 20_000,
        "total_risk_pct": 0.01,
        "add_risk_pct": 0.005,
    }


def _enabled(result_context: dict | None = None) -> dict:
    return evaluate_controlled_position_add(
        result_context or _context(),
        policy={"enabled": True, "mode": "guarded"},
    )


def test_valid_guard_is_eligible_but_has_no_execution_authority() -> None:
    result = _enabled()
    assert result["eligible"] is True
    assert result["guard_eligible"] is True
    assert result["authority"] == "guard_only"
    assert result["execution_authority"] is False
    assert result["preserve_existing_protection"] is True
    assert result["cancel_existing_orders"] is False


def test_protective_sell_legs_do_not_count_as_active_exit() -> None:
    context = _context()
    context["open_orders"] = [
        {
            "symbol": "AAPL",
            "side": "sell",
            "status": "working",
            "order_id": "stop-old",
            "role": "protective_stop",
        },
        {
            "symbol": "AAPL",
            "side": "sell",
            "status": "working",
            "order_id": "take-old",
            "role": "protective_take_profit",
        },
    ]
    result = _enabled(context)
    assert result["eligible"] is True
    assert "active_exit" not in result["reason_codes"]

    context["open_orders"][1]["role"] = "manual_exit"
    context["open_orders"][1]["order_id"] = "manual-exit"
    result = _enabled(context)
    assert result["eligible"] is False
    assert "active_exit" in result["reason_codes"]


def test_missing_lineage_blocks() -> None:
    context = _context()
    del context["prior_fill"]["signal_capture_id"]
    result = _enabled(context)
    assert result["eligible"] is False
    assert "fill_lineage_missing_exact_ids" in result["reason_codes"]


def test_repeat_add_same_session_blocks() -> None:
    context = _context()
    context["position_adds"] = [
        {"symbol": "AAPL", "action": "position_add", "status": "completed", "session_date": "2026-10-08"}
    ]
    result = _enabled(context)
    assert result["eligible"] is False
    assert "duplicate_add_same_session" in result["reason_codes"]


def test_new_signal_must_be_aware_and_after_old_fill() -> None:
    context = _context()
    context["new_signal"]["captured_at"] = "2026-10-04T15:00:00+00:00"
    result = _enabled(context)
    assert result["eligible"] is False
    assert "new_signal_not_after_prior_fill" in result["reason_codes"]

    context = _context()
    context["new_signal"]["captured_at"] = "2026-10-08T14:00:00"
    result = _enabled(context)
    assert "new_signal_timestamp_unavailable_or_naive" in result["reason_codes"]


def test_session_boundary_requires_completed_session_strictly_after_fill_session() -> None:
    context = _context()
    context["session_carrier"]["completed_sessions"] = [
        {
            "session_date": "2026-10-05",
            "status": "completed",
            "close_utc": "2026-10-05T20:00:00+00:00",
        }
    ]
    result = _enabled(context)
    assert result["eligible"] is False
    assert "missing_completed_xnys_session_after_prior_fill" in result["reason_codes"]


def test_loss_blocks() -> None:
    context = _context()
    context["position"]["unrealized_pl"] = -0.01
    result = _enabled(context)
    assert result["eligible"] is False
    assert "position_unrealized_pl_not_positive" in result["reason_codes"]


def test_aggregate_symbol_exposure_and_add_cap_block() -> None:
    context = _context()
    context["position"]["market_value"] = 4_000
    context["add_qty"] = 1_500
    result = _enabled(context)
    assert result["eligible"] is False
    assert "symbol_exposure_limit_exceeded" in result["reason_codes"]
    assert "add_size_limit_exceeded" in result["reason_codes"]


def test_duplicate_planned_add_blocks() -> None:
    context = _context()
    context["pending_plans"] = [
        {
            "symbol": "AAPL",
            "action": "position_add",
            "status": "pending",
            "session_date": "2026-10-08",
            "notional": 500,
        }
    ]
    result = _enabled(context)
    assert result["eligible"] is False
    assert "duplicate_planned_add" in result["reason_codes"]


def test_unsupported_broker_fails_closed_without_fabricating_protection() -> None:
    context = _context()
    context["broker"] = {"provider": "unsupported"}
    result = _enabled(context)
    assert result["eligible"] is False
    assert "unsupported_broker" in result["reason_codes"]
    assert "controlled_add_protection_unavailable" in result["reason_codes"]


def test_default_policy_is_shadow_and_disabled() -> None:
    result = evaluate_controlled_position_add(_context())
    assert result["eligible"] is False
    assert result["status"] == "shadow"
    assert "policy_disabled" in result["reason_codes"]
    assert "policy_shadow_only" in result["reason_codes"]


def test_carrier_is_stable_and_does_not_grant_order_authority() -> None:
    context = deepcopy(_context())
    result = evaluate_controlled_position_add(context, policy={"enabled": True, "mode": "guarded"})
    assert result["action"] == "BUY"
    assert result["authority"] == "guard_only"
    assert result["execution_authority"] is False


def test_future_completed_session_is_rejected_against_decision_time() -> None:
    context = _context()
    context["session_carrier"]["completed_sessions"].append(
        {
            "session_date": "2026-10-09",
            "status": "completed",
            "close_utc": "2026-10-09T20:00:00+00:00",
        }
    )
    result = _enabled(context)
    assert result["eligible"] is False
    assert "xnys_session_close_after_decision" in result["reason_codes"]


def test_fake_holiday_session_is_rejected_by_actual_xnys_calendar() -> None:
    context = _context()
    context["session_carrier"]["completed_sessions"] = [
        {
            "session_date": "2026-10-10",
            "status": "completed",
            "close_utc": "2026-10-10T20:00:00+00:00",
        }
    ]
    result = _enabled(context)
    assert result["eligible"] is False
    assert "xnys_session_not_in_calendar" in result["reason_codes"]


def test_protective_role_alone_cannot_exempt_unknown_sell() -> None:
    context = _context()
    context["open_orders"] = [
        {
            "symbol": "AAPL",
            "side": "sell",
            "status": "working",
            "order_id": "unknown-sell",
            "role": "protective",
        }
    ]
    result = _enabled(context)
    assert result["eligible"] is False
    assert "active_exit" in result["reason_codes"]


def test_protection_leg_qty_must_match_position_qty() -> None:
    context = _context()
    context["existing_protection"]["legs"][0]["qty"] = 99
    result = _enabled(context)
    assert result["eligible"] is False
    assert "existing_protection_leg_qty_mismatch" in result["reason_codes"]


def test_protection_leg_ids_must_be_unique() -> None:
    context = _context()
    context["existing_protection"]["legs"][1]["id"] = "stop-old"
    result = _enabled(context)
    assert result["eligible"] is False
    assert "existing_protection_duplicate_leg_id" in result["reason_codes"]


def test_conflicting_root_and_nested_lineage_blocks() -> None:
    context = _context()
    context["prior_fill"]["decision_lineage"] = {"signal_id": "sig-conflict"}
    result = _enabled(context)
    assert result["eligible"] is False
    assert "lineage_conflict" in result["reason_codes"]


def test_numeric_boolean_carrier_is_not_valid() -> None:
    context = _context()
    context["thesis"] = {"valid": 1}
    result = _enabled(context)
    assert result["eligible"] is False
    assert "thesis_invalid" in result["reason_codes"]


def test_unknown_open_order_status_fails_closed() -> None:
    context = _context()
    context["open_orders"] = [
        {"symbol": "AAPL", "side": "sell", "status": "mystery", "order_id": "ord-unknown"}
    ]
    result = _enabled(context)
    assert result["eligible"] is False
    assert "open_order_status_unknown" in result["reason_codes"]

def test_filled_add_same_session_blocks_repeat() -> None:
    context = _context()
    context["position_adds"] = [
        {
            "symbol": "AAPL",
            "action": "position_add",
            "status": "filled",
            "filled_qty": 10,
            "session_date": "2026-10-08",
        }
    ]
    result = _enabled(context)
    assert result["eligible"] is False
    assert "duplicate_add_same_session" in result["reason_codes"]


def test_explicit_zero_cash_blocks_even_with_buying_power() -> None:
    context = _context()
    context["cash_available"] = 0
    context["buying_power"] = 100_000
    result = _enabled(context)
    assert result["eligible"] is False
    assert "cash_available_insufficient" in result["reason_codes"]
    assert "cash_available_unavailable" not in result["reason_codes"]


def test_unknown_pending_plan_notional_fails_closed() -> None:
    context = _context()
    context["pending_plans"] = [
        {
            "symbol": "AAPL",
            "action": "position_add",
            "status": "pending",
            "session_date": "2026-10-08",
            "risk_pct": 0.001,
        }
    ]
    result = _enabled(context)
    assert result["eligible"] is False
    assert "pending_plan_notional_unavailable" in result["reason_codes"]


def test_missing_add_risk_blocks_without_zero_fallback() -> None:
    context = _context()
    del context["add_risk_pct"]
    result = _enabled(context)
    assert result["eligible"] is False
    assert "add_risk_unavailable" in result["reason_codes"]


def test_policy_exceeding_immutable_maximum_blocks() -> None:
    result = evaluate_controlled_position_add(
        _context(),
        policy={
            "enabled": True,
            "mode": "guarded",
            "max_symbol_exposure_pct": 0.06,
        },
    )
    assert result["eligible"] is False
    assert "policy_exceeds_immutable_maximum" in result["reason_codes"]
