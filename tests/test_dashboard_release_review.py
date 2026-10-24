"""Regressions found during the joint-release review, without external I/O."""

import importlib.util
import sqlite3
from concurrent.futures import Future
from pathlib import Path

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.dashboard_broker import DashboardBroker as BrokerClientFactory
from agente_bolsa.dashboard_fills import FillRepository, backfill_fills
from agente_bolsa.dashboard_loading import REMOTE_FILLS, DashboardLoadState
from agente_bolsa.dashboard_snapshot import SnapshotRepository, environment_fingerprint


@pytest.fixture(scope="module")
def observations(tmp_path_factory):
    script = Path(__file__).resolve().parents[1] / "scripts/dashboard_review_oct24.py"
    spec = importlib.util.spec_from_file_location("dashboard_contract_review", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.audit(tmp_path_factory.mktemp("release-review"))


def test_real_array_contract_fetches_all_pages(observations):
    value = observations["bare_array_pagination"]
    assert value["returned"] == value["available"] == 3
    assert value["requests"] == 3  # Includes the terminal empty page.
    assert observations["bare_array_backfill"]["stored"] == 3


def test_repeated_cursor_never_certifies_completeness(observations):
    value = observations["repeated_token_backfill"]
    assert value["coverage"] == "partial"
    assert value["truncated"] is True
    assert value["stop_reason"] == "error"


def test_incremental_query_uses_activity_token_not_date_filter(observations):
    value = observations["incremental_request"]
    assert value["after"] is None
    assert value["page_token"] == "20261023000000003::activity-3"
    assert value["direction"] == "asc"


def test_resuming_older_pages_preserves_incremental_high_water_mark(observations):
    value = observations["resume_cursor"]
    assert value["after"] == value["before"]


def test_new_credentials_cannot_hydrate_previous_account(observations):
    value = observations["credential_change_before_network"]
    assert value == {"same_fingerprint": False, "hydrated_account": None,
                     "displayed_cash": None}


@pytest.mark.parametrize("envelope", [
    {"items": [], "next_page_token": "pending"},
    {"items": [], "next_page_token": None, "truncated": True},
    {"items": [], "next_page_token": None, "stop_reason": "repeated_token"},
    {"items": [{"symbol": "MISSING-ID"}], "next_page_token": None},
])
def test_invalid_or_incomplete_page_fails_closed(tmp_path, envelope):
    settings = Settings(DATA_DIR=tmp_path, _env_file=None)
    repo = FillRepository(settings.database_path)
    result = backfill_fills(settings, repository=repo, identity_key="test",
                            fetch=lambda **kwargs: envelope)
    assert result["status"] == "degraded"
    assert result["coverage"]["backfill_completed_at"] is None
    assert result["coverage"]["status"] != "complete"


def test_activity_id_is_rejected_as_after_before_any_network(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Network must not be reached")

    monkeypatch.setattr("agente_bolsa.dashboard_broker._read_activity_page", forbidden)
    with pytest.raises(ValueError):
        BrokerClientFactory(Settings(DATA_DIR=tmp_path, _env_file=None)).alpaca_trade_activities_page(
            after="20261023000000003::activity-3")


def test_credential_change_discards_old_pending_results(tmp_path):
    settings = Settings(DATA_DIR=tmp_path, _env_file=None, ALPACA_API_KEY="key-A")
    other = Settings(DATA_DIR=tmp_path, _env_file=None, ALPACA_API_KEY="key-B")
    state = DashboardLoadState()
    state._wire(settings)
    future = Future()
    state.futures[REMOTE_FILLS] = future
    state._wire(other)
    future.set_result({"value": [], "generation": 1})
    assert state._collect() is False
    assert state.data is None
    assert state.futures == {}
    assert state.fingerprint == environment_fingerprint(other)


def test_queued_fill_callback_keeps_original_storage_identity(tmp_path, monkeypatch):
    settings = Settings(DATA_DIR=tmp_path, _env_file=None, ALPACA_API_KEY="key-A")
    other = Settings(DATA_DIR=tmp_path, _env_file=None, ALPACA_API_KEY="key-B")
    state = DashboardLoadState()
    state._wire(settings)
    state.account_id, state.identity_key = "account-A", "identity-A"
    original_repo = state.fills_repository
    callbacks = state._callbacks(settings)
    state._wire(other)
    monkeypatch.setattr(state, "_sync_fills", lambda config, repo, key: (config, repo, key))
    assert callbacks[REMOTE_FILLS]() == (settings, original_repo, "identity-A")


@pytest.mark.parametrize("repo_type", [FillRepository, SnapshotRepository])
def test_repository_read_connections_close_without_garbage_collection(tmp_path, monkeypatch, repo_type):
    repo = repo_type(tmp_path / "read.sqlite3")
    repo.ensure_schema()
    opened = []
    original = repo.read_connection

    def track():
        conn = original()
        opened.append(conn)
        return conn

    monkeypatch.setattr(repo, "read_connection", track)
    if repo_type is FillRepository:
        repo.count_fills("test")
        repo.sync_state("test")
    else:
        repo.account_hint("test")
        repo.load_all("test")
    assert opened
    for conn in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            conn.execute("SELECT 1")


@pytest.fixture(autouse=True)
def forbid_sockets(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network prohibited in dashboard tests")
    monkeypatch.setattr("socket.create_connection", forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)
