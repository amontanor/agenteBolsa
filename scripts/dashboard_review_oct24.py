"""Read-only contract audit using synthetic providers and temporary SQLite only.

Print observations, not a deployment approval. No network, SDK or production data.
Run with PYTHONPATH=src and the project interpreter.
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from agente_bolsa.config import Settings
from agente_bolsa.dashboard_broker import DashboardBroker as BrokerClientFactory
from agente_bolsa.dashboard_fills import FillRepository, backfill_fills, sync_recent
from agente_bolsa.dashboard_loading import DashboardLoadState
from agente_bolsa.dashboard_snapshot import (
    RESOURCE_ACCOUNT,
    SnapshotRepository,
    environment_fingerprint,
    identity_key,
)


def fill(number: int) -> dict:
    return {
        "id": f"2026102300000000{number}::activity-{number}",
        "symbol": "TEST",
        "side": "buy",
        "qty": "1",
        "price": "10",
        "transaction_time": f"2026-10-23T10:00:0{number}+00:00",
        "order_id": f"order-{number}",
    }


def audit(root: Path) -> dict:
    settings = Settings(DATA_DIR=root, _env_file=None,
                        ALPACA_API_KEY="synthetic-a", ALPACA_SECRET_KEY="synthetic-a")
    observations = {}
    calls = []
    items = [fill(3), fill(2), fill(1)]

    def read_page(url, headers, timeout):
        query = parse_qs(urlparse(url).query)
        calls.append(query)
        token = query.get("page_token", [None])[0]
        start = next((i + 1 for i, item in enumerate(items) if item["id"] == token), 0)
        size = int(query["page_size"][0])
        return items[start:start + size], None

    with patch("agente_bolsa.dashboard_broker._read_activity_page", read_page):
        page = BrokerClientFactory(settings).alpaca_trade_activities_page(
            page_size=2, max_pages=5)
        observations["bare_array_pagination"] = {
            "available": 3, "returned": len(page["items"]),
            "requests": len(calls), "truncated": page["truncated"],
            "stop_reason": page["stop_reason"],
        }
        repo = FillRepository(root / "array.sqlite3")
        result = backfill_fills(settings, repository=repo, identity_key="test",
                                page_size=2, max_pages=5)
        observations["bare_array_backfill"] = {
            "available": 3, "stored": result["coverage"]["fills_stored"],
            "coverage": result["coverage"]["status"],
        }

    repo = FillRepository(root / "repeated.sqlite3")
    result = backfill_fills(
        settings, repository=repo, identity_key="test", max_pages=5,
        fetch=lambda **kwargs: {"items": [fill(1)], "next_page_token": "repeat"})
    observations["repeated_token_backfill"] = {
        "stop_reason": result["stop_reason"], "truncated": result["truncated"],
        "coverage": result["coverage"]["status"],
    }

    repo = FillRepository(root / "incremental.sqlite3")
    sync_recent(settings, repository=repo, identity_key="test",
                fetch=lambda **kwargs: {"items": [fill(3)], "next_page_token": None})
    requests = []

    def incremental(**kwargs):
        requests.append(kwargs)
        return {"items": [], "next_page_token": None}

    sync_recent(settings, repository=repo, identity_key="test", fetch=incremental)
    observations["incremental_request"] = requests[0]

    repo = FillRepository(root / "resume.sqlite3")
    sync_recent(settings, repository=repo, identity_key="test", max_pages=1,
                fetch=lambda **kwargs: {"items": [fill(3)], "next_page_token": "older"})
    before = repo.sync_state("test").cursor_after
    sync_recent(settings, repository=repo, identity_key="test", max_pages=1,
                fetch=lambda **kwargs: {"items": [fill(1)], "next_page_token": None})
    observations["resume_cursor"] = {
        "before": before, "after": repo.sync_state("test").cursor_after}

    snapshots = SnapshotRepository(settings.database_path)
    snapshots.ensure_schema()
    fingerprint = environment_fingerprint(settings)
    snapshots.record_account_hint(fingerprint, "account-A")
    snapshots.save_many(identity_key(fingerprint, "account-A"), [(
        RESOURCE_ACCOUNT,
        {"account_id": "account-A", "cash": 123, "portfolio_value": 123},
        "2026-10-23T10:00:00+00:00",
    )])
    other = Settings(DATA_DIR=root, _env_file=None,
                     ALPACA_API_KEY="synthetic-b", ALPACA_SECRET_KEY="synthetic-b")
    state = DashboardLoadState()
    state._wire(other)
    state.hydrate()
    observations["credential_change_before_network"] = {
        "same_fingerprint": fingerprint == environment_fingerprint(other),
        "hydrated_account": state.account_id,
        "displayed_cash": state.data["portfolio"].cash if state.data else None,
    }
    observations["network_used"] = False
    observations["production_used"] = False
    return observations


if __name__ == "__main__":
    with TemporaryDirectory(prefix="dashboard-audit-") as directory:
        print(json.dumps(audit(Path(directory)), indent=2))
