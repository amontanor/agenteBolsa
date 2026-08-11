"""Caracterización roja del carrier P-L89B sobre la base sin cambios."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from agente_bolsa.tools.canonical_eod_account_snapshot import (
    build_from_postmarket_inputs,
)
from agente_bolsa.tools.capital_deployment_funnel_shadow import (
    account_projection_from_portfolio_snapshot,
    build_capital_deployment_funnel_shadow,
)

CAPTURED_AT = datetime(2026, 8, 11, 20, 0, tzinfo=timezone.utc)


def _candidate() -> dict[str, object]:
    return {
        "cycle_id": "cycle-p89b",
        "action": "buy",
        "signal_id": "signal-1",
        "recommendation_id": "recommendation-1",
        "recommendation_generated": True,
        "selection_status": "selected",
        "gate_status": "passed",
        "capacity_status": "passed",
        "sizing_status": "passed",
        "risk_status": "approved",
    }


def test_base_drops_nested_capital_and_account_observations() -> None:
    plan = {
        **_candidate(),
        "plan_id": "plan-1",
        "notional": 900.0,
        "payload": {
            "notional": 900.0,
            "risk_decision": {
                "checks": {
                    "proposal_notional": 1000.0,
                    "max_position_exposure": 0.05,
                    "cash_floor": 0.25,
                    "position_sizing": {
                        "adjusted_target_notional": 900.0,
                        "available_buying_power": 5000.0,
                        "max_position_notional": 3500.0,
                        "size_multiplier": 0.9,
                    },
                }
            },
        },
    }
    result = build_capital_deployment_funnel_shadow(
        "cycle-p89b",
        [_candidate()],
        plans=[plan],
        account={
            "equity": 10000.0,
            "cash": 9000.0,
            "buying_power": 5000.0,
            "gross_exposure": 1000.0,
            "net_exposure": 1000.0,
            "cash_floor": 0.25,
            "max_position_exposure": 0.05,
            "position_concentration": 0.10,
        },
        captured_at=CAPTURED_AT,
    )
    detail = result["details"][0]
    assert detail.get("approved_notional", detail["risk_approved_notional"]) == 900.0
    assert detail["cash_floor"] == 0.25
    assert detail["max_position_exposure"] == 0.05
    assert detail["max_position_notional"] == 3500.0
    assert detail["buying_power"] == 5000.0
    assert result["account"]["cash_floor"] == 0.25
    assert result["account"]["position_concentration"] == 0.10


def test_base_discards_previous_close_and_keeps_future_source_timestamps() -> None:
    portfolio = SimpleNamespace(
        account_id="paper",
        currency="USD",
        portfolio_value=1010.0,
        previous_close_equity=1000.0,
        cash=900.0,
        positions=[],
        open_orders=[],
    )
    snapshot = build_from_postmarket_inputs(
        "2026-08-11",
        portfolio=portfolio,
        canonical_telemetry={"captured_at": "2026-08-11T20:01:00Z"},
        canonical_trade_attribution={"captured_at": "2026-08-11T20:02:00Z"},
        report={"as_of": "2026-08-11T20:00:00Z", "window_start_at": None},
        captured_at=CAPTURED_AT,
    )
    assert snapshot["equity_start"] == 1000.0
    assert snapshot["account_read_at"] == "2026-08-11T20:00:00Z"
    assert snapshot["as_of"] == "2026-08-11T20:02:00Z"
    assert not any(reason.startswith("source_timestamp_after_as_of:") for reason in snapshot["reason_codes"])


def test_portfolio_projection_is_read_only_and_missing_values_stay_null() -> None:
    portfolio = SimpleNamespace(
        portfolio_value=10000.0,
        cash=9000.0,
        buying_power=5000.0,
        positions=[SimpleNamespace(market_value=1000.0, side="long")],
    )
    result = account_projection_from_portfolio_snapshot(portfolio)
    assert result == {
        "equity": 10000.0,
        "cash": 9000.0,
        "buying_power": 5000.0,
        "gross_exposure": 1000.0,
        "net_exposure": 1000.0,
        "position_concentration": 0.1,
    }
    portfolio.positions[0].market_value = None
    incomplete = account_projection_from_portfolio_snapshot(portfolio)
    assert incomplete["gross_exposure"] is None
    assert incomplete["net_exposure"] is None
    assert incomplete["position_concentration"] is None


def test_eod_missing_previous_close_remains_unavailable() -> None:
    portfolio = SimpleNamespace(
        account_id="paper",
        currency="USD",
        portfolio_value=1010.0,
        previous_close_equity=None,
        cash=900.0,
        positions=[],
        open_orders=[],
    )
    snapshot = build_from_postmarket_inputs(
        "2026-08-11",
        portfolio=portfolio,
        report={"as_of": "2026-08-11T20:00:00Z", "window_start_at": None},
        captured_at=CAPTURED_AT,
    )
    assert snapshot["equity_start"] is None
    assert snapshot["coverage"]["equity_coverage"]["status"] == "unavailable"
    assert snapshot["status"] == "unavailable"
