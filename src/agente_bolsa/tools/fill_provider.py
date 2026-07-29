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
        try:
            order = self._request(
                f"/orders/{broker_order_id}",
                timeout_seconds=timeout_seconds,
            )
        except Exception:
            if not client_order_id:
                raise
            order = self._request(
                "/orders:by_client_order_id",
                params={"client_order_id": client_order_id},
                timeout_seconds=timeout_seconds,
            )
        return canonical_order_snapshot(order, requested_id=broker_order_id)

    def _request(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        timeout_seconds: int | None,
    ) -> Any:
        """Use the SDK session only inside the provider adapter.

        The public SDK order methods do not expose a timeout.  Its session and
        URL construction are provider details, so the bounded request remains
        isolated here; test doubles without that session use the public methods.
        """

        session = getattr(self._client, "_session", None)
        if session is None or timeout_seconds is None:
            if path.startswith("/orders:by_client_order_id"):
                return self._client.get_order_by_client_id(str((params or {}).get("client_order_id") or ""))
            return self._client.get_order_by_id(path.rsplit("/", 1)[-1])
        base_url = str(getattr(self._client, "_base_url", "")).rstrip("/")
        api_version = str(getattr(self._client, "_api_version", "v2")).strip("/")
        url = f"{base_url}/{api_version}{path}"
        headers = self._client._get_default_headers()
        response = session.request(
            "GET",
            url,
            headers=headers,
            params=params,
            allow_redirects=False,
            timeout=int(timeout_seconds),
        )
        response.raise_for_status()
        return response.json()


def build_order_status_provider(settings: Any) -> OrderStatusProvider:
    """Build the configured adapter without leaking SDK types to consumers."""

    provider = str(getattr(settings, "broker", "") or "").strip().lower()
    if provider != "alpaca":
        raise RuntimeError(f"unsupported_order_status_provider:{provider or 'missing'}")
    from .broker import BrokerClientFactory

    return AlpacaOrderStatusProvider(BrokerClientFactory(settings).alpaca_trading_client())
