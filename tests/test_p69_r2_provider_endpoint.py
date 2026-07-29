from __future__ import annotations

from types import SimpleNamespace

from alpaca.trading.client import TradingClient

from agente_bolsa.tools.fill_provider import AlpacaOrderStatusProvider


class _Response:
    def __init__(self, payload, *, error: bool = False):
        self.payload = payload
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise RuntimeError("order_not_found")

    def json(self):
        return self.payload


def _provider(requests, responses):
    client = TradingClient("fake-key", "fake-secret", paper=True)

    def request(*args, **kwargs):
        requests.append((args, kwargs))
        return responses.pop(0)

    client._session = SimpleNamespace(request=request)
    return AlpacaOrderStatusProvider(client)


def test_real_trading_client_enum_base_url_is_normalized_for_exact_order_get():
    requests = []
    provider = _provider(
        requests,
        [
            _Response(
                {
                    "id": "broker-1",
                    "client_order_id": "client-1",
                    "status": "filled",
                    "filled_qty": "3",
                    "filled_avg_price": "27.5",
                }
            )
        ],
    )

    snapshot = provider.snapshot_order("broker-1", timeout_seconds=7)

    assert snapshot.status == "filled"
    assert requests[0][0][1] == "https://paper-api.alpaca.markets/v2/orders/broker-1"
    assert requests[0][1]["timeout"] == 7
    assert requests[0][1]["allow_redirects"] is False
    assert requests[0][1]["headers"]["APCA-API-KEY-ID"] == "fake-key"


def test_real_trading_client_enum_base_url_is_normalized_for_client_id_fallback():
    requests = []
    provider = _provider(
        requests,
        [
            _Response({}, error=True),
            _Response(
                {
                    "id": "broker-2",
                    "client_order_id": "client-2",
                    "status": "pending_new",
                }
            ),
        ],
    )

    snapshot = provider.snapshot_order("broker-2", client_order_id="client-2", timeout_seconds=9)

    assert snapshot.status == "pending_new"
    assert requests[0][0][1] == "https://paper-api.alpaca.markets/v2/orders/broker-2"
    assert requests[1][0][1] == "https://paper-api.alpaca.markets/v2/orders:by_client_order_id"
    assert requests[1][1]["params"] == {"client_order_id": "client-2"}
    assert requests[1][1]["timeout"] == 9
