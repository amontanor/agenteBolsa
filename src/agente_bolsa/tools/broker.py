"""Broker integration.

The first implementation is Alpaca. It defaults to paper trading and refuses live
mode unless the global safety settings allow it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from agente_bolsa.config import Settings
from agente_bolsa.models import OrderSnapshot, PortfolioSnapshot, PositionSnapshot


def _configured(value: str | None) -> bool:
    return bool(value and value.strip())


def _normal_endpoint(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    endpoint = value.strip().rstrip("/")
    if endpoint.endswith("/v2"):
        return endpoint[:-3]
    return endpoint


def _float_attr(obj: Any, attr: str, default: float = 0.0) -> float:
    value = getattr(obj, attr, default)
    if value is None:
        return default
    return float(value)


def _optional_float_attr(obj: Any, attr: str) -> float | None:
    value = getattr(obj, attr, None)
    if value is None:
        return None
    return float(value)


def _str_attr(obj: Any, attr: str, default: str = "") -> str:
    value = getattr(obj, attr, default)
    if value is None:
        return default
    return str(value.value if isinstance(value, Enum) else value)


class BrokerClientFactory:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # P-L186: cache por proceso de la evidencia de borrow. Se consulta una
        # vez por simbolo y sesion de ejecucion; nunca se inventa el resultado.
        self._asset_cache: dict[str, dict[str, Any]] = {}
        self._shorting_enabled: bool | None = None

    def alpaca_shorting_enabled(self) -> bool:
        """Whether the paper account allows shorting (broker authority)."""

        if self._shorting_enabled is not None:
            return self._shorting_enabled
        account = self.alpaca_trading_client().get_account()
        self._shorting_enabled = bool(getattr(account, "shorting_enabled", False))
        return self._shorting_enabled

    def alpaca_trading_client(self) -> Any:
        self.settings.assert_trading_safety()

        if not _configured(self.settings.alpaca_api_key) or not _configured(
            self.settings.alpaca_secret_key
        ):
            raise RuntimeError("Faltan ALPACA_API_KEY y ALPACA_SECRET_KEY.")

        try:
            from alpaca.trading.client import TradingClient
        except ImportError as exc:
            raise RuntimeError("Instala alpaca-py con `pip install -r requirements.txt`.") from exc

        paper = self.settings.trading_mode == "paper" and self.settings.alpaca_paper
        return TradingClient(
            self.settings.alpaca_api_key,
            self.settings.alpaca_secret_key,
            paper=paper,
            url_override=_normal_endpoint(self.settings.alpaca_endpoint),
        )

    def alpaca_account_snapshot(self) -> dict[str, Any]:
        account = self.alpaca_trading_client().get_account()
        return {
            "id": str(getattr(account, "id", "")),
            "status": str(getattr(account, "status", "")),
            "currency": str(getattr(account, "currency", "")),
            "cash": str(getattr(account, "cash", "")),
            "portfolio_value": str(getattr(account, "portfolio_value", "")),
            "previous_close_equity": _optional_float_attr(account, "last_equity"),
            "buying_power": str(getattr(account, "buying_power", "")),
            "pattern_day_trader": bool(getattr(account, "pattern_day_trader", False)),
            "trading_blocked": bool(getattr(account, "trading_blocked", False)),
            "transfers_blocked": bool(getattr(account, "transfers_blocked", False)),
            "account_blocked": bool(getattr(account, "account_blocked", False)),
            "shorting_enabled": bool(getattr(account, "shorting_enabled", False)),
        }

    def alpaca_asset_shortability(self, symbol: str) -> dict[str, Any]:
        """Return broker-side shortability evidence for one symbol.

        The payload is the only authority the plan builder and kernel accept for
        ``borrow.status == "verified"``. Any failure is reported as
        ``unavailable`` and blocks new shorts; it never degrades to "assume yes".
        """

        key = str(symbol or "").upper().strip()
        if not key:
            return {"status": "unavailable", "reason": "symbol_missing"}
        if key in self._asset_cache:
            return dict(self._asset_cache[key])
        try:
            asset = self.alpaca_trading_client().get_asset(key)
        except Exception as exc:  # noqa: BLE001 - borrow lookup never raises upstream.
            result = {"status": "unavailable", "reason": f"asset_lookup_failed:{type(exc).__name__}"}
            self._asset_cache[key] = result
            return dict(result)
        result = {
            "status": "verified",
            "as_of": datetime.now(timezone.utc).isoformat(),
            "symbol": key,
            "tradable": bool(getattr(asset, "tradable", False)),
            "marginable": bool(getattr(asset, "marginable", False)),
            "shortable": bool(getattr(asset, "shortable", False)),
            "easy_to_borrow": bool(getattr(asset, "easy_to_borrow", False)),
            "fractionable": bool(getattr(asset, "fractionable", False)),
            "asset_status": _str_attr(asset, "status"),
        }
        self._asset_cache[key] = result
        return dict(result)

    def alpaca_trade_activities(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Fetch trade fill activities from Alpaca paper REST API."""

        self.settings.assert_trading_safety()
        endpoint = _normal_endpoint(self.settings.alpaca_endpoint) or "https://paper-api.alpaca.markets"
        query = urlencode({"direction": "desc", "page_size": max(1, min(limit, 100))})
        url = f"{endpoint}/v2/account/activities/FILL?{query}"
        request = Request(
            url,
            headers={
                "APCA-API-KEY-ID": self.settings.alpaca_api_key or "",
                "APCA-API-SECRET-KEY": self.settings.alpaca_secret_key or "",
                "Accept": "application/json",
            },
        )
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []

    def alpaca_portfolio_history(
        self,
        *,
        period: str = "3M",
        timeframe: str = "1D",
    ) -> dict[str, Any]:
        """Fetch portfolio equity history from Alpaca paper REST API."""

        self.settings.assert_trading_safety()
        endpoint = _normal_endpoint(self.settings.alpaca_endpoint) or "https://paper-api.alpaca.markets"
        query = urlencode(
            {
                "period": period,
                "timeframe": timeframe,
                "pnl_reset": "no",
                "intraday_reporting": "market_hours",
            }
        )
        url = f"{endpoint}/v2/account/portfolio/history?{query}"
        request = Request(
            url,
            headers={
                "APCA-API-KEY-ID": self.settings.alpaca_api_key or "",
                "APCA-API-SECRET-KEY": self.settings.alpaca_secret_key or "",
                "Accept": "application/json",
            },
        )
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else {}

    def alpaca_positions(self) -> list[PositionSnapshot]:
        client = self.alpaca_trading_client()
        positions = client.get_all_positions()
        return [
            PositionSnapshot(
                symbol=_str_attr(position, "symbol"),
                qty=_float_attr(position, "qty"),
                market_value=_float_attr(position, "market_value"),
                avg_entry_price=_float_attr(position, "avg_entry_price"),
                current_price=_float_attr(position, "current_price"),
                unrealized_pl=_float_attr(position, "unrealized_pl"),
                unrealized_plpc=_float_attr(position, "unrealized_plpc"),
                side=_str_attr(position, "side", "long"),
                unrealized_intraday_pl=_optional_float_attr(position, "unrealized_intraday_pl"),
                unrealized_intraday_plpc=_optional_float_attr(position, "unrealized_intraday_plpc"),
            )
            for position in positions
        ]

    def alpaca_open_orders(self) -> list[OrderSnapshot]:
        try:
            from alpaca.trading.enums import QueryOrderStatus
            from alpaca.trading.requests import GetOrdersRequest
        except ImportError as exc:
            raise RuntimeError("Instala alpaca-py con `pip install -r requirements.txt`.") from exc

        client = self.alpaca_trading_client()
        orders = client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN))
        return [
            OrderSnapshot(
                order_id=_str_attr(order, "id"),
                symbol=_str_attr(order, "symbol"),
                side=_str_attr(order, "side"),
                qty=_optional_float_attr(order, "qty"),
                notional=_optional_float_attr(order, "notional"),
                order_type=_str_attr(order, "type"),
                status=_str_attr(order, "status"),
                submitted_at=_str_attr(order, "submitted_at", None),
            )
            for order in orders
        ]

    def alpaca_portfolio_snapshot(self) -> PortfolioSnapshot:
        client = self.alpaca_trading_client()
        account = client.get_account()
        positions = client.get_all_positions()

        try:
            from alpaca.trading.enums import QueryOrderStatus
            from alpaca.trading.requests import GetOrdersRequest
        except ImportError as exc:
            raise RuntimeError("Instala alpaca-py con `pip install -r requirements.txt`.") from exc

        orders = client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN))
        return PortfolioSnapshot(
            account_id=_str_attr(account, "id"),
            status=_str_attr(account, "status"),
            currency=_str_attr(account, "currency"),
            cash=_float_attr(account, "cash"),
            portfolio_value=_float_attr(account, "portfolio_value"),
            buying_power=_float_attr(account, "buying_power"),
            positions=[
                PositionSnapshot(
                    symbol=_str_attr(position, "symbol"),
                    qty=_float_attr(position, "qty"),
                    market_value=_float_attr(position, "market_value"),
                    avg_entry_price=_float_attr(position, "avg_entry_price"),
                    current_price=_float_attr(position, "current_price"),
                    unrealized_pl=_float_attr(position, "unrealized_pl"),
                    unrealized_plpc=_float_attr(position, "unrealized_plpc"),
                    side=_str_attr(position, "side", "long"),
                    unrealized_intraday_pl=_optional_float_attr(position, "unrealized_intraday_pl"),
                    unrealized_intraday_plpc=_optional_float_attr(position, "unrealized_intraday_plpc"),
                )
                for position in positions
            ],
            open_orders=[
                OrderSnapshot(
                    order_id=_str_attr(order, "id"),
                    symbol=_str_attr(order, "symbol"),
                    side=_str_attr(order, "side"),
                    qty=_optional_float_attr(order, "qty"),
                    notional=_optional_float_attr(order, "notional"),
                    order_type=_str_attr(order, "type"),
                    status=_str_attr(order, "status"),
                    submitted_at=_str_attr(order, "submitted_at", None),
                )
                for order in orders
            ],
            previous_close_equity=_optional_float_attr(account, "last_equity"),
        )
