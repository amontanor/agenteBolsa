"""Canonical portfolio cases for P-L186N tests.

They mirror the production cases observed on 2026-11-03: a long with a plan,
a short with a plan, a legacy long, a long opened after a short cover, and an
orphan position without any local order.
"""

from __future__ import annotations


def _plan(plan_id: str, *, effect: str | None, stop: float, take: float, entry: float, qty: float) -> dict:
    payload = {
        "qty": qty,
        "entry_price": entry,
        "stop_loss": stop,
        "take_profit": take,
        "recommendation": {"confidence": 0.7, "reason": f"case {plan_id}"},
    }
    if effect is not None:
        payload["position_effect"] = effect
    return {"plan_id": plan_id, "notional": round(entry * qty, 2), "payload": payload}


BROKER_ORDERS = [
    {
        "broker_order_id": "bo-evrge",
        "plan_id": "plan-evrge",
        "cycle_id": "cycle-1",
        "symbol": "EVRG",
        "side": "buy",
        "status": "filled",
        "created_at": "2026-10-29T19:11:13+00:00",
        "payload": {
            "plan": _plan(
                "plan-evrge",
                effect="open_long",
                stop=82.2425,
                take=89.4363,
                entry=85.26,
                qty=49,
            )
        },
    },
    {
        "broker_order_id": "bo-app",
        "plan_id": "plan-app",
        "cycle_id": "cycle-2",
        "symbol": "APP",
        "side": "sell",
        "status": "filled",
        "created_at": "2026-11-02T16:53:22+00:00",
        "payload": {
            "plan": _plan(
                "plan-app",
                effect="open_short",
                stop=261.3766,
                take=204.0601,
                entry=238.45,
                qty=5,
            )
        },
    },
    {
        "broker_order_id": "bo-mo",
        "plan_id": "plan-mo",
        "cycle_id": "cycle-1",
        "symbol": "MO",
        "side": "buy",
        "status": "filled",
        "created_at": "2026-10-29T15:50:49+00:00",
        "payload": {
            "plan": _plan(
                "plan-mo",
                effect=None,
                stop=72.43,
                take=80.555,
                entry=75.71,
                qty=55,
            )
        },
    },
    {
        # A short cover: a buy with inverted levels. It must never be an entry.
        "broker_order_id": "bo-adm-cover",
        "plan_id": "plan-adm-cover",
        "cycle_id": "cycle-3",
        "symbol": "ADM",
        "side": "buy",
        "status": "filled",
        "created_at": "2026-11-03T15:16:35+00:00",
        "payload": {
            "plan": _plan(
                "plan-adm-cover",
                effect="close_short",
                stop=79.1801,
                take=92.5928,
                entry=71.6,
                qty=28,
            )
        },
    },
    {
        # Older real long entry for ADM; the cover above is newer.
        "broker_order_id": "bo-adm-long",
        "plan_id": "plan-adm-long",
        "cycle_id": "cycle-4",
        "symbol": "ADM",
        "side": "buy",
        "status": "filled",
        "created_at": "2026-09-02T14:12:19+00:00",
        "payload": {
            "plan": _plan(
                "plan-adm-long",
                effect="open_long",
                stop=70.0,
                take=85.0,
                entry=80.0,
                qty=10,
            )
        },
    },
]

# APO has no local order at all: the orphan case.
OPEN_POSITIONS = [
    {
        "symbol": "EVRG",
        "side": "long",
        "qty": 49.0,
        "avg_entry_price": 85.26,
        "current_price": 85.775,
        "market_value": 4202.975,
        "unrealized_pl": 25.235,
        "unrealized_plpc": 0.00604,
    },
    {
        "symbol": "APP",
        "side": "short",
        "qty": -5.0,
        "avg_entry_price": 238.24,
        "current_price": 242.68,
        "market_value": -1213.4,
        "unrealized_pl": -22.2,
        "unrealized_plpc": -0.01864,
    },
    {
        "symbol": "ADM",
        "side": "long",
        "qty": 10.0,
        "avg_entry_price": 80.0,
        "current_price": 78.0,
        "market_value": 780.0,
        "unrealized_pl": -20.0,
        "unrealized_plpc": -0.025,
    },
    {
        "symbol": "MO",
        "side": "long",
        "qty": 55.0,
        "avg_entry_price": 75.71,
        "current_price": 76.78,
        "market_value": 4222.9,
        "unrealized_pl": 58.85,
        "unrealized_plpc": 0.01413,
    },
    {
        "symbol": "APO",
        "side": "long",
        "qty": 7.0,
        "avg_entry_price": 137.55,
        "current_price": 113.125,
        "market_value": 791.875,
        "unrealized_pl": -170.975,
        "unrealized_plpc": -0.17757,
    },
]
