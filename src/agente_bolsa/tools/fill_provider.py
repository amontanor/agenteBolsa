"""Provider-neutral order status snapshots for the intraday fill watcher."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

TERMINAL_STATUSES = frozenset(
    {
        "filled",
        "canceled",
        "cancelled",
        "expired",
        "rejected",
        "done_for_day",
        "replaced",
        "stopped",
    }
)


def normalize_order_status(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text.rsplit(".", 1)[-1] if text else ""


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and result not in {float("inf"), float("-inf")} else None


def _timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class CanonicalOrderSnapshot:
    """Minimal order state used by reconciliation and notifications."""

    broker_order_id: str
    provider_order_id: str | None
    client_order_id: str | None
    status: str
    filled_qty: float | None
    filled_avg_price: float | None
    filled_at: str | None
    updated_at: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.broker_order_id,
            "provider_order_id": self.provider_order_id,
            "client_order_id": self.client_order_id,
            "status": self.status,
            "filled_qty": self.filled_qty,
            "filled_avg_price": self.filled_avg_price,
            "filled_at": self.filled_at,
            "updated_at": self.updated_at,
        }


class OrderStatusProvider(Protocol):
    def snapshot_order(
        self,
        broker_order_id: str,
        *,
        client_order_id: str | None = None,
        timeout_seconds: int | None = None,
    ) -> CanonicalOrderSnapshot: ...


def _value(order: Any, name: str, default: Any = None) -> Any:
    if isinstance(order, dict):
        return order.get(name, default)
    return getattr(order, name, default)


def canonical_order_snapshot(order: Any, *, requested_id: str) -> CanonicalOrderSnapshot:
    broker_order_id = str(_value(order, "id", requested_id) or requested_id).strip()
    if broker_order_id != requested_id:
        raise ValueError("provider_order_identity_mismatch")
    status = normalize_order_status(_value(order, "status"))
    if not status:
        raise ValueError("provider_order_status_missing")
    return CanonicalOrderSnapshot(
        broker_order_id=broker_order_id,
        provider_order_id=broker_order_id,
        client_order_id=str(_value(order, "client_order_id") or "").strip() or None,
        status=status,
        filled_qty=_number(_value(order, "filled_qty")),
        filled_avg_price=_number(_value(order, "filled_avg_price")),
        filled_at=_timestamp(_value(order, "filled_at")),
        updated_at=_timestamp(_value(order, "updated_at")),
    )


class AlpacaOrderStatusProvider:
    """Alpaca adapter; provider-specific objects do not cross this boundary."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def snapshot_order(
        self,
        broker_order_id: str,
        *,
        client_order_id: str | None = None,
        timeout_seconds: int | None = None,
    ) -> CanonicalOrderSnapshot:
        del timeout_seconds  # The existing SDK client owns its request timeout.
        try:
            order = self._client.get_order_by_id(broker_order_id)
        except Exception:
            if not client_order_id:
                raise
            order = self._client.get_order_by_client_id(client_order_id)
        return canonical_order_snapshot(order, requested_id=broker_order_id)


def build_order_status_provider(settings: Any) -> OrderStatusProvider:
    """Build the configured adapter without leaking SDK types to consumers."""

    provider = str(getattr(settings, "broker", "") or "").strip().lower()
    if provider != "alpaca":
        raise RuntimeError(f"unsupported_order_status_provider:{provider or 'missing'}")
    from .broker import BrokerClientFactory

    return AlpacaOrderStatusProvider(BrokerClientFactory(settings).alpaca_trading_client())

