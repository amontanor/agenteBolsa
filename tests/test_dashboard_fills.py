"""P3b: fill pagination, local repository, incremental sync, coverage and backfill.

All checks are deterministic and offline: no broker, network, sleeps or
production SQLite. The broker transport is replaced by an in-memory urlopen.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from agente_bolsa import dashboard_broker as broker_module
from agente_bolsa.config import Settings
from agente_bolsa.dashboard_broker import DashboardBroker as BrokerClientFactory
from agente_bolsa.dashboard_fills import (
    STATUS_COMPLETE,
    STATUS_PARTIAL,
    STATUS_UNAVAILABLE,
    FillRepository,
    backfill_fills,
    reconcile_fills,
    sync_recent,
)
from agente_bolsa.models import PortfolioSnapshot

IDENTITY = "identity-test"
BACKFILL_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dashboard_fills_backfill.py"


def load_backfill_script():
    spec = importlib.util.spec_from_file_location("dashboard_fills_backfill", BACKFILL_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def settings_for(tmp_path) -> Settings:
    return Settings(DATA_DIR=tmp_path, _env_file=None)


def repository_for(tmp_path) -> FillRepository:
    repository = FillRepository(tmp_path / "state" / "dashboard_fills.sqlite3")
    repository.ensure_schema()
    return repository


def fill(
    activity_id: str,
    transaction_time: str,
    *,
    symbol: str = "AAPL",
    side: str = "buy",
    qty: float = 1.0,
    price: float = 10.0,
    order_id: str | None = None,
) -> dict:
    return {
        "id": activity_id,
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "price": price,
        "transaction_time": transaction_time,
        "order_id": order_id or f"order-{activity_id}",
    }


def portfolio(cash: float = 1000.0) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        account_id="account-test",
        status="ACTIVE",
        currency="USD",
        cash=cash,
        portfolio_value=cash,
        buying_power=cash,
        positions=[],
        open_orders=[],
    )


# -- broker pagination --------------------------------------------------


class FakeResponse:
    def __init__(self, payload, token: str | None = None) -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self.headers = {} if token is None else {"X-Next-Page-Token": token}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args) -> bool:
        return False


def install_transport(monkeypatch, pages: list[FakeResponse], calls: list[dict]) -> None:
    def fake_urlopen(request, timeout=None):
        query = parse_qs(urlparse(request.full_url).query)
        calls.append(
            {
                "page_token": query.get("page_token", [None])[0],
                "direction": query.get("direction", [None])[0],
                "page_size": query.get("page_size", [None])[0],
                "after": query.get("after", [None])[0],
                "timeout": timeout,
            }
        )
        return pages.pop(0)

    monkeypatch.setattr(broker_module, "urlopen", fake_urlopen)


def test_pagination_reads_three_pages_with_metadata(monkeypatch, tmp_path):
    calls: list[dict] = []
    pages = [
        FakeResponse({"activities": [fill("a1", "2026-10-01")], "next_page_token": "t1"}),
        FakeResponse({"activities": [fill("a2", "2026-10-02")], "next_page_token": "t2"}),
        FakeResponse({"activities": [fill("a3", "2026-10-03")]}),
    ]
    install_transport(monkeypatch, pages, calls)

    envelope = BrokerClientFactory(settings_for(tmp_path)).alpaca_trade_activities_page(
        page_size=100, direction="asc", after="2026-09-30T00:00:00Z", max_pages=5
    )

    assert [item["id"] for item in envelope["items"]] == ["a1", "a2", "a3"]
    assert envelope["pages"] == 3
    assert envelope["next_page_token"] is None
    assert envelope["truncated"] is False
    assert envelope["stop_reason"] == "exhausted"
    assert [call["page_token"] for call in calls] == [None, "t1", "t2"]
    assert {call["direction"] for call in calls} == {"asc"}
    assert {call["after"] for call in calls} == {"2026-09-30T00:00:00Z"}


def test_array_pagination_uses_last_id_instead_of_untrusted_header(monkeypatch, tmp_path):
    calls: list[dict] = []
    pages = [
        FakeResponse([fill("a1", "2026-10-01")], token="h1"),
        FakeResponse([fill("a2", "2026-10-02")]),
        FakeResponse([]),
    ]
    install_transport(monkeypatch, pages, calls)

    envelope = BrokerClientFactory(settings_for(tmp_path)).alpaca_trade_activities_page(
        max_pages=3
    )

    assert envelope["pages"] == 3
    assert [item["id"] for item in envelope["items"]] == ["a1", "a2"]
    assert envelope["truncated"] is False
    assert calls[1]["page_token"] == "a1"
    assert calls[2]["page_token"] == "a2"


def test_pagination_stops_on_repeated_token(monkeypatch, tmp_path):
    calls: list[dict] = []
    pages = [
        FakeResponse({"activities": [fill("a1", "2026-10-01")], "next_page_token": "t1"}),
        FakeResponse({"activities": [fill("a2", "2026-10-02")], "next_page_token": "t1"}),
    ]
    install_transport(monkeypatch, pages, calls)

    envelope = BrokerClientFactory(settings_for(tmp_path)).alpaca_trade_activities_page(
        max_pages=10
    )

    assert envelope["pages"] == 2
    assert envelope["stop_reason"] == "repeated_token"
    assert envelope["truncated"] is True
    assert len(calls) == 2


def test_pagination_respects_page_ceiling_and_declares_truncation(monkeypatch, tmp_path):
    calls: list[dict] = []
    pages = [
        FakeResponse({"activities": [fill("a1", "2026-10-01")], "next_page_token": "t1"}),
        FakeResponse({"activities": [fill("a2", "2026-10-02")], "next_page_token": "t2"}),
        FakeResponse({"activities": [fill("a3", "2026-10-03")], "next_page_token": "t3"}),
    ]
    install_transport(monkeypatch, pages, calls)

    envelope = BrokerClientFactory(settings_for(tmp_path)).alpaca_trade_activities_page(
        max_pages=2
    )

    assert envelope["pages"] == 2
    assert [item["id"] for item in envelope["items"]] == ["a1", "a2"]
    assert envelope["next_page_token"] == "t2"
    assert envelope["truncated"] is True
    assert envelope["stop_reason"] == "max_pages"


def test_pagination_validates_items_and_deduplicates_ids(monkeypatch, tmp_path):
    calls: list[dict] = []
    pages = [
        FakeResponse(
            {
                "activities": [
                    fill("a1", "2026-10-01"),
                    fill("a1", "2026-10-01"),
                    fill("a2", "2026-10-02"),
                ]
            }
        )
    ]
    install_transport(monkeypatch, pages, calls)

    envelope = BrokerClientFactory(settings_for(tmp_path)).alpaca_trade_activities_page(
        max_pages=2
    )

    assert [item["id"] for item in envelope["items"]] == ["a1", "a2"]
    assert envelope["stop_reason"] == "exhausted"


def test_legacy_list_read_keeps_one_page(monkeypatch, tmp_path):
    calls: list[dict] = []
    pages = [
        FakeResponse([fill("a1", "2026-10-01")], token="h1"),
        FakeResponse([fill("a2", "2026-10-02")]),
    ]
    install_transport(monkeypatch, pages, calls)

    items = BrokerClientFactory(settings_for(tmp_path)).alpaca_trade_activities(limit=1000)

    assert [item["id"] for item in items] == ["a1"]
    assert len(calls) == 1
    assert calls[0]["page_size"] == "100"


# -- repository: idempotency and conflicts ------------------------------


def test_same_id_same_content_is_a_noop(tmp_path):
    repository = repository_for(tmp_path)
    row = fill("a1", "2026-10-01T14:00:00Z")

    first = repository.store_fills(IDENTITY, [row], observed_at="2026-10-01T15:00:00+00:00")
    second = repository.store_fills(IDENTITY, [dict(row)], observed_at="2026-10-01T16:00:00+00:00")

    assert (first.stored, first.unchanged, first.conflicts) == (1, 0, 0)
    assert (second.stored, second.unchanged, second.conflicts) == (0, 1, 0)
    assert repository.count_fills(IDENTITY) == 1
    assert repository.conflicts(IDENTITY) == []
    assert repository.load_fills(IDENTITY)[0]["id"] == "a1"


def test_same_id_different_content_keeps_original_and_records_conflict(tmp_path):
    repository = repository_for(tmp_path)
    original = fill("a1", "2026-10-01T14:00:00Z", price=10.0)
    changed = fill("a1", "2026-10-01T14:00:00Z", price=99.0)

    repository.store_fills(IDENTITY, [original], observed_at="2026-10-01T15:00:00+00:00")
    result = repository.store_fills(
        IDENTITY, [changed], observed_at="2026-10-01T16:00:00+00:00"
    )

    assert (result.stored, result.unchanged, result.conflicts) == (0, 0, 1)
    stored = repository.load_fills(IDENTITY)
    assert len(stored) == 1
    assert stored[0]["price"] == 10.0
    conflicts = repository.conflicts(IDENTITY)
    assert len(conflicts) == 1
    assert conflicts[0]["fill_id"] == "a1"
    assert conflicts[0]["observed_payload"]["price"] == 99.0


def test_duplicate_ids_inside_one_batch_are_deduplicated(tmp_path):
    repository = repository_for(tmp_path)
    row = fill("a1", "2026-10-01T14:00:00Z")

    result = repository.store_fills(IDENTITY, [row, dict(row), dict(row)])

    assert (result.stored, result.unchanged, result.conflicts) == (1, 0, 0)
    assert repository.count_fills(IDENTITY) == 1


def test_fill_without_id_is_rejected_not_merged_by_symbol(tmp_path):
    repository = repository_for(tmp_path)
    anonymous = {"symbol": "AAPL", "qty": 1, "price": 10, "transaction_time": "2026-10-01"}

    result = repository.store_fills(IDENTITY, [anonymous, fill("a1", "2026-10-01T14:00:00Z")])

    assert result.rejected == 1
    assert result.stored == 1
    assert repository.count_fills(IDENTITY) == 1


def test_loaded_fills_have_stable_order(tmp_path):
    repository = repository_for(tmp_path)
    repository.store_fills(
        IDENTITY,
        [
            fill("b", "2026-10-03T14:00:00Z"),
            fill("a", "2026-10-01T14:00:00Z"),
            fill("c", "2026-10-02T14:00:00Z"),
        ],
    )

    loaded = repository.load_fills(IDENTITY)

    assert [row["id"] for row in loaded] == ["a", "c", "b"]
    assert [row["id"] for row in repository.load_fills(IDENTITY)] == ["a", "c", "b"]


def test_observed_at_does_not_change_the_content_hash(tmp_path):
    repository = repository_for(tmp_path)
    row = fill("a1", "2026-10-01T14:00:00Z")
    repository.store_fills(IDENTITY, [row], observed_at="2026-10-01T15:00:00+00:00")
    later = repository.store_fills(IDENTITY, [dict(row)], observed_at="2026-12-31T00:00:00+00:00")
    assert later.unchanged == 1
    assert repository.conflicts(IDENTITY) == []


# -- incremental sync ---------------------------------------------------


class FakeFetcher:
    def __init__(self, steps: list) -> None:
        self.steps = list(steps)
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(dict(kwargs))
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def page(items: list[dict], token: str | None = None) -> dict:
    return {"items": items, "next_page_token": token, "pages": 1, "truncated": bool(token)}


def test_second_sync_asks_only_for_new_activity_since_cursor(tmp_path):
    settings = settings_for(tmp_path)
    repository = repository_for(tmp_path)
    fetcher = FakeFetcher(
        [
            page([fill("a1", "2026-10-01T14:00:00Z"), fill("a2", "2026-10-02T14:00:00Z")]),
            page([]),
        ]
    )

    first = sync_recent(settings, repository=repository, identity_key=IDENTITY, fetch=fetcher)
    second = sync_recent(settings, repository=repository, identity_key=IDENTITY, fetch=fetcher)

    assert first.status == "ok"
    assert first.fetched == 2
    assert fetcher.calls[0]["direction"] == "desc"
    assert fetcher.calls[0]["after"] is None
    assert second.fetched == 0
    # The second read resumes from the newest known activity, not from scratch.
    assert fetcher.calls[1]["direction"] == "asc"
    assert fetcher.calls[1]["after"] is None
    assert fetcher.calls[1]["page_token"] == "a2"
    assert repository.count_fills(IDENTITY) == 2


def test_sync_resumes_from_persisted_token_after_failure(tmp_path):
    settings = settings_for(tmp_path)
    repository = repository_for(tmp_path)
    fetcher = FakeFetcher(
        [
            page([fill("a1", "2026-10-01T14:00:00Z")], token="t2"),
            RuntimeError("connection reset"),
            page([fill("a2", "2026-10-02T14:00:00Z")]),
        ]
    )

    failed = sync_recent(settings, repository=repository, identity_key=IDENTITY, fetch=fetcher)
    assert failed.status == "degraded"
    assert failed.pages == 1
    assert failed.error == "connection reset"
    state = repository.sync_state(IDENTITY)
    assert state.pending_page_token == "t2"
    assert state.pending_direction == "desc"
    assert state.last_error is not None

    resumed = sync_recent(settings, repository=repository, identity_key=IDENTITY, fetch=fetcher)
    assert resumed.status == "ok"
    assert resumed.pages == 1
    assert resumed.fetched == 1
    assert fetcher.calls[2]["page_token"] == "t2"
    assert repository.count_fills(IDENTITY) == 2
    # No duplicate work: page 1 was requested exactly once.
    assert len(fetcher.calls) == 3


def test_sync_truncation_is_declared_and_resumable(tmp_path):
    settings = settings_for(tmp_path)
    repository = repository_for(tmp_path)
    fetcher = FakeFetcher(
        [
            page([fill("a1", "2026-10-01T14:00:00Z")], token="t1"),
            page([fill("a2", "2026-10-02T14:00:00Z")], token="t2"),
            page([fill("a3", "2026-10-03T14:00:00Z")]),
        ]
    )

    result = sync_recent(
        settings, repository=repository, identity_key=IDENTITY, fetch=fetcher, max_pages=1
    )

    assert result.pages == 1
    assert result.truncated is True
    assert result.stop_reason == "max_pages"
    state = repository.sync_state(IDENTITY)
    assert state.pending_page_token == "t1"
    assert repository.coverage(IDENTITY)["truncated"] is True
    assert repository.coverage(IDENTITY)["status"] == STATUS_PARTIAL


def test_sync_conflict_keeps_original_and_counts_it(tmp_path):
    settings = settings_for(tmp_path)
    repository = repository_for(tmp_path)
    repository.store_fills(IDENTITY, [fill("a1", "2026-10-01T14:00:00Z", price=10.0)])
    fetcher = FakeFetcher([page([fill("a1", "2026-10-01T14:00:00Z", price=99.0)])])

    result = sync_recent(settings, repository=repository, identity_key=IDENTITY, fetch=fetcher)

    assert result.status == "ok"
    assert result.conflicts == 1
    assert repository.load_fills(IDENTITY)[0]["price"] == 10.0


def test_sync_rejects_unidentifiable_items(tmp_path):
    settings = settings_for(tmp_path)
    repository = repository_for(tmp_path)
    fetcher = FakeFetcher([page([{"symbol": "AAPL", "qty": 1}, fill("a1", "2026-10-01")])])

    result = sync_recent(settings, repository=repository, identity_key=IDENTITY, fetch=fetcher)

    assert result.rejected == 1
    assert result.stored == 1


# -- coverage -----------------------------------------------------------


def test_coverage_is_unavailable_without_fills(tmp_path):
    repository = repository_for(tmp_path)
    coverage = repository.coverage(IDENTITY)
    assert coverage["status"] == STATUS_UNAVAILABLE
    assert coverage["fills_stored"] == 0
    assert coverage["oldest_fill_at"] is None
    assert coverage["complete_since"] is None
    assert coverage["source"] == "local_sync"


def test_coverage_stays_partial_without_backfill(tmp_path):
    settings = settings_for(tmp_path)
    repository = repository_for(tmp_path)
    fetcher = FakeFetcher(
        [page([fill("a2", "2026-10-02T14:00:00Z"), fill("a1", "2026-10-01T14:00:00Z")])]
    )
    sync_recent(settings, repository=repository, identity_key=IDENTITY, fetch=fetcher)

    coverage = repository.coverage(IDENTITY)
    assert coverage["status"] == STATUS_PARTIAL
    assert coverage["fills_stored"] == 2
    assert coverage["oldest_fill_at"] == "2026-10-01T14:00:00Z"
    assert coverage["newest_fill_at"] == "2026-10-02T14:00:00Z"
    assert coverage["complete_since"] is None
    assert coverage["last_sync_at"] is not None
    assert coverage["pages_last_sync"] == 1


def test_backfill_exhaustion_is_the_only_path_to_complete_coverage(tmp_path):
    settings = settings_for(tmp_path)
    repository = repository_for(tmp_path)
    fetcher = FakeFetcher(
        [
            page([fill("a2", "2026-10-02T14:00:00Z")], token="t1"),
            page([fill("a1", "2026-10-01T14:00:00Z")]),
        ]
    )

    result = backfill_fills(
        settings, repository=repository, identity_key=IDENTITY, fetch=fetcher
    )

    assert result["status"] == "ok"
    assert result["pages"] == 2
    assert result["truncated"] is False
    coverage = repository.coverage(IDENTITY)
    assert coverage["status"] == STATUS_COMPLETE
    assert coverage["complete_since"] == "2026-10-01T14:00:00Z"
    assert coverage["backfill_completed_at"] is not None


def test_backfill_is_idempotent_and_does_not_repeat_when_already_complete(tmp_path):
    settings = settings_for(tmp_path)
    repository = repository_for(tmp_path)
    fetcher = FakeFetcher([page([fill("a1", "2026-10-01T14:00:00Z")])])
    backfill_fills(settings, repository=repository, identity_key=IDENTITY, fetch=fetcher)

    calls = len(fetcher.calls)
    second = backfill_fills(
        settings, repository=repository, identity_key=IDENTITY, fetch=fetcher
    )

    assert len(fetcher.calls) == calls
    assert second["status"] == "complete"
    assert second["stop_reason"] == "already_complete"
    assert repository.count_fills(IDENTITY) == 1


def test_backfill_resumes_after_partial_failure(tmp_path):
    settings = settings_for(tmp_path)
    repository = repository_for(tmp_path)
    fetcher = FakeFetcher(
        [
            page([fill("a2", "2026-10-02T14:00:00Z")], token="t2"),
            RuntimeError("timeout"),
            page([fill("a1", "2026-10-01T14:00:00Z")]),
        ]
    )

    failed = backfill_fills(
        settings, repository=repository, identity_key=IDENTITY, fetch=fetcher
    )
    assert failed["status"] == "degraded"
    state = repository.sync_state(IDENTITY)
    assert state.backfill_page_token == "t2"

    resumed = backfill_fills(
        settings, repository=repository, identity_key=IDENTITY, fetch=fetcher
    )
    assert resumed["status"] == "ok"
    assert fetcher.calls[2]["page_token"] == "t2"
    assert fetcher.calls[2]["direction"] == "desc"
    assert repository.coverage(IDENTITY)["status"] == STATUS_COMPLETE


def test_backfill_max_pages_is_declared_truncated(tmp_path):
    settings = settings_for(tmp_path)
    repository = repository_for(tmp_path)
    fetcher = FakeFetcher(
        [
            page([fill("a2", "2026-10-02T14:00:00Z")], token="t1"),
            page([fill("a1", "2026-10-01T14:00:00Z")], token="t2"),
        ]
    )

    result = backfill_fills(
        settings, repository=repository, identity_key=IDENTITY, fetch=fetcher, max_pages=1
    )

    assert result["truncated"] is True
    assert result["stop_reason"] == "max_pages"
    assert repository.coverage(IDENTITY)["status"] == STATUS_PARTIAL


# -- reconciliation -----------------------------------------------------


def test_reconciliation_reports_missing_ids_without_deleting(tmp_path):
    repository = repository_for(tmp_path)
    local_twin = fill("a1", "2026-10-01T14:00:00Z")
    local_extra = fill("local-x", "2026-10-02T14:00:00Z")
    repository.store_fills(IDENTITY, [local_twin, local_extra])

    result = reconcile_fills(
        repository,
        IDENTITY,
        [local_twin, fill("broker-y", "2026-10-02T15:00:00Z")],
        run_at="2026-10-03T00:00:00+00:00",
    )

    assert result["status"] == "mismatch"
    assert result["broker_only"] == ["broker-y"]
    assert result["local_only"] == ["local-x"]
    latest = repository.latest_reconciliation(IDENTITY)
    assert latest is not None
    assert latest["broker_only_count"] == 1
    assert repository.count_fills(IDENTITY) == 2


def test_reconciliation_skips_an_empty_window(tmp_path):
    repository = repository_for(tmp_path)
    result = reconcile_fills(repository, IDENTITY, [], run_at="2026-10-03T00:00:00+00:00")
    assert result["status"] == "skipped"
    assert result["reason"] == "empty_window"


# -- history and dashboard integration ---------------------------------




@pytest.fixture(autouse=True)
def forbid_sockets(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network prohibited in dashboard tests")
    monkeypatch.setattr("socket.create_connection", forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)
