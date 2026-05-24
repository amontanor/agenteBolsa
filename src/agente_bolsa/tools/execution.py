"""Paper order execution through Alpaca."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.tools.operational_health import load_operational_block_context
from agente_bolsa.tools.broker import BrokerClientFactory


def _order_value(order: Any, key: str, default: Any = None) -> Any:
    if isinstance(order, dict):
        return order.get(key, default)
    return getattr(order, key, default)


def _order_snapshot(order: Any) -> dict[str, Any]:
    return {
        "id": str(_order_value(order, "id", "")),
        "client_order_id": str(_order_value(order, "client_order_id", "")),
        "symbol": str(_order_value(order, "symbol", "")),
        "side": str(_order_value(order, "side", "")),
        "type": str(_order_value(order, "type", "")),
        "order_class": str(_order_value(order, "order_class", "")),
        "status": str(_order_value(order, "status", "")),
        "qty": _order_value(order, "qty"),
        "notional": _order_value(order, "notional"),
        "submitted_at": str(_order_value(order, "submitted_at", "")),
    }


def _alpaca_price(value: Any) -> float:
    price = Decimal(str(value))
    increment = Decimal("0.0001") if price < Decimal("1") else Decimal("0.01")
    return float(price.quantize(increment, rounding=ROUND_HALF_UP))


def _is_fractional_qty(value: Any) -> bool:
    qty = Decimal(str(value))
    return qty != qty.to_integral_value()


def _is_full_position_exit(plan: dict[str, Any]) -> bool:
    if str(plan.get("side", "")).lower() != "sell":
        return False
    payload = plan.get("payload", {}) or {}
    recommendation = payload.get("recommendation", {}) or {}
    risk_decision = payload.get("risk_decision", {}) or {}
    checks = risk_decision.get("checks", {}) or {}
    action = str(recommendation.get("action") or checks.get("action") or "").lower()
    return action in {"sell", "exit"}


def build_market_order_request(
    plan: dict[str, Any],
    *,
    client_order_id: str,
    use_bracket_orders: bool,
) -> Any:
    try:
        from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
        from alpaca.trading.requests import (
            MarketOrderRequest,
            StopLossRequest,
            TakeProfitRequest,
        )
    except ImportError as exc:
        raise RuntimeError("Instala alpaca-py con `pip install -r requirements.txt`.") from exc

    payload = plan["payload"]
    side = OrderSide.BUY if plan["side"].lower() == "buy" else OrderSide.SELL
    qty = payload.get("qty")
    notional = plan.get("notional")
    if not qty:
        raise RuntimeError("El plan no contiene qty calculada.")

    request_kwargs = {
        "symbol": plan["symbol"],
        "side": side,
        "time_in_force": TimeInForce.DAY,
        "client_order_id": client_order_id,
    }
    use_bracket = (
        use_bracket_orders
        and plan["side"].lower() == "buy"
        and not _is_fractional_qty(qty)
    )
    if use_bracket:
        request_kwargs["qty"] = float(qty)
        request_kwargs.update(
            {
                "order_class": OrderClass.BRACKET,
                "take_profit": TakeProfitRequest(
                    limit_price=_alpaca_price(payload["take_profit"]),
                ),
                "stop_loss": StopLossRequest(
                    stop_price=_alpaca_price(payload["stop_loss"]),
                ),
            }
        )
    elif plan["side"].lower() == "buy" and notional:
        request_kwargs["notional"] = float(notional)
    else:
        request_kwargs["qty"] = float(qty)
    return MarketOrderRequest(**request_kwargs)


def submit_paper_order_plan(
    settings: Settings,
    plan: dict[str, Any],
    *,
    client_order_id: str,
) -> dict[str, Any]:
    if settings.trading_mode != "paper" or not settings.alpaca_paper:
        raise RuntimeError("La ejecucion automatica solo esta permitida en Alpaca paper.")
    if (
        settings.operational_kill_switch_enabled
        and str(plan.get("side", "")).lower() == "buy"
    ):
        operational_block = load_operational_block_context(settings.data_dir)
        if operational_block.get("block_buy_execution"):
            reason = "; ".join(operational_block.get("reasons", [])[:3]) or "critical_operational_alerts_active"
            raise RuntimeError(f"Compra bloqueada por operational kill switch: {reason}")

    client = BrokerClientFactory(settings).alpaca_trading_client()
    if _is_full_position_exit(plan):
        order = client.close_position(plan["symbol"])
        return _order_snapshot(order)

    order_request = build_market_order_request(
        plan,
        client_order_id=client_order_id,
        use_bracket_orders=settings.use_bracket_orders,
    )
    order = client.submit_order(order_data=order_request)
    return _order_snapshot(order)
