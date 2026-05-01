"""Broker integration.

The first implementation is Alpaca. It defaults to paper trading and refuses live
mode unless the global safety settings allow it.
"""

from __future__ import annotations

import json
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
    return str(value)


class BrokerClientFactory:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

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
            "buying_power": str(getattr(account, "buying_power", "")),
            "pattern_day_trader": bool(getattr(account, "pattern_day_trader", False)),
            "trading_blocked": bool(getattr(account, "trading_blocked", False)),
            "transfers_blocked": bool(getattr(account, "transfers_blocked", False)),
            "account_blocked": bool(getattr(account, "account_blocked", False)),
        }

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
        )
