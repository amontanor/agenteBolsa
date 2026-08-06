from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from agente_bolsa.kindle_server import KindleRequestHandler, render_kindle_page
from agente_bolsa.tools.kindle_snapshot import (
    benchmark_from_performance,
    build_kindle_snapshot,
    publish_kindle_snapshot,
    read_kindle_snapshot,
    snapshot_path,
)

CAPTURED = datetime(2026, 8, 6, 9, 45, tzinfo=timezone.utc)


def _position(symbol: str, *, total: float | None = 0.1, today: float | None = 0.02):
    return SimpleNamespace(
        symbol=symbol,
        qty=2.0,
        avg_entry_price=100.0,
        current_price=101.0,
        unrealized_plpc=total,
        unrealized_intraday_plpc=today,
    )


def _portfolio(*, previous: float | None = 1000.0, positions=None):
    return SimpleNamespace(
        portfolio_value=1012.5,
        previous_close_equity=previous,
        positions=list(positions or []),
    )


def test_snapshot_uses_provider_neutral_daily_equity_and_stable_positions():
    snapshot = build_kindle_snapshot(
        _portfolio(positions=[_position("zeta"), _position("<x>", today=None)]),
        captured_at=CAPTURED,
        benchmark={
            "status": "comparable",
            "pct": 0.012,
            "as_of": CAPTURED.isoformat(),
            "source": "canonical_eod",
        },
    )
    assert snapshot["portfolio"]["amount"] == 12.5
    assert snapshot["portfolio"]["pct"] == 0.0125
    assert snapshot["benchmark"]["pct"] == 0.012
    assert [item["symbol"] for item in snapshot["positions"]] == ["<X>", "ZETA"]
    assert snapshot["positions"][0]["today_pl_pct"] is None
    assert "account_id" not in json.dumps(snapshot)
    assert "cash" not in json.dumps(snapshot)


def test_snapshot_is_unavailable_without_previous_close_and_benchmark_alignment():
    snapshot = build_kindle_snapshot(
        _portfolio(previous=None),
        captured_at=CAPTURED,
        benchmark={"status": "unavailable", "reason": "spy_current_not_comparable"},
    )
    assert snapshot["portfolio"]["status"] == "unavailable"
    assert snapshot["portfolio"]["amount"] is None
    assert snapshot["benchmark"]["status"] == "unavailable"
    assert snapshot["benchmark"]["reason"] == "spy_current_not_comparable"


def test_publish_is_atomic_and_reader_is_read_only(tmp_path: Path):
    target = snapshot_path(tmp_path)
    result = publish_kindle_snapshot(tmp_path, _portfolio(), captured_at=CAPTURED)
    assert result["status"] == "published"
    first = read_kindle_snapshot(target)
    assert first is not None
    before = target.read_bytes()
    assert read_kindle_snapshot(target) == first
    assert target.read_bytes() == before
    assert not list(target.parent.glob("*.tmp"))


def test_performance_benchmark_projection_requires_canonical_eod_contract():
    valid = benchmark_from_performance(
        {
            "performance_benchmark": {
                "benchmark": {
                    "symbol": "SPY",
                    "daily_return": 0.01,
                    "comparison_status": "comparable",
                    "eod_authority": "confirmed",
                    "data_quality": "available",
                    "price_basis": "adjusted_ohlc",
                    "source": "cache",
                    "as_of": "2026-08-05T20:00:00+00:00",
                }
            }
        }
    )
    assert valid["status"] == "comparable"
    assert valid["pct"] == 0.01
    invalid = benchmark_from_performance({"performance_benchmark": {"benchmark": {"daily_return": 0.2}}})
    assert invalid == {"status": "unavailable", "reason": "spy_eod_not_comparable"}


def test_render_is_escaped_narrow_and_has_no_script_or_external_resources():
    snapshot = build_kindle_snapshot(_portfolio(positions=[_position("<X>")]), captured_at=CAPTURED)
    page = render_kindle_page(snapshot, now=CAPTURED)
    assert "&lt;X&gt;" in page
    assert "<script" not in page.lower()
    assert "http://" not in page.lower()
    assert "https://" not in page.lower()
    assert "/kindle" in page
    assert "S&amp;P 500" in page


def test_http_contract_get_health_kindle_and_mutator_rejection(tmp_path: Path):
    target = snapshot_path(tmp_path)
    publish_kindle_snapshot(tmp_path, _portfolio(), captured_at=CAPTURED)
    server = ThreadingHTTPServer(("127.0.0.1", 0), KindleRequestHandler)
    server.snapshot_file = target
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    try:
        connection.request("GET", "/kindle")
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        assert response.status == 200
        assert response.getheader("Cache-Control") == "no-store"
        assert "Cartera" in body
        connection.request("GET", "/health")
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read()) == {"ok": True, "service": "kindle", "snapshot_available": True}
        connection.request("GET", "/other")
        assert connection.getresponse().status == 404
        connection.request("POST", "/kindle")
        assert connection.getresponse().status == 405
    finally:
        connection.close()
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()
