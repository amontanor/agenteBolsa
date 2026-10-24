"""Contract tests for the persistent dashboard snapshot repository."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.dashboard_snapshot import (
    RESOURCE_ACCOUNT,
    RESOURCE_CURVE,
    RESOURCE_FILLS,
    RESOURCE_ORDERS,
    RESOURCE_POSITIONS,
    SCHEMA_VERSION,
    SnapshotRepository,
    content_hash,
    environment_fingerprint,
    identity_key,
)
from agente_bolsa.storage import Store


def settings_for(tmp_path, **overrides):
    return Settings(DATA_DIR=tmp_path, _env_file=None, **overrides)


def repository(tmp_path):
    repo = SnapshotRepository(tmp_path / "state" / "dashboard.sqlite3")
    repo.ensure_schema()
    return repo


def count_rows(repository_path, table, where="1=1", params=()):
    with sqlite3.connect(repository_path) as conn:
        row = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()
    return int(row[0])


def test_identity_partitions_credentials_without_persisting_them(tmp_path):
    first = settings_for(tmp_path, ALPACA_API_KEY="key-alpha", ALPACA_SECRET_KEY="secret-alpha")
    second = settings_for(tmp_path, ALPACA_API_KEY="key-beta", ALPACA_SECRET_KEY="secret-beta")

    fingerprint = environment_fingerprint(first)
    assert fingerprint != environment_fingerprint(second)
    key = identity_key(fingerprint, "account-1")
    assert len(key) == 64
    assert "key-alpha" not in key and "secret-alpha" not in key
    assert identity_key(fingerprint, "account-1") == key
    assert identity_key(fingerprint, "account-2") != key
    assert identity_key("another-fingerprint", "account-1") != key


def test_same_content_is_idempotent_and_new_content_appends_a_version(tmp_path):
    repo = repository(tmp_path)
    key = identity_key(environment_fingerprint(settings_for(tmp_path)), "account-1")
    payload = {"account_id": "account-1", "cash": 100.0, "portfolio_value": 150.0}

    first = repo.save_many(key, [(RESOURCE_ACCOUNT, payload, "2026-10-23T15:00:00+00:00")])
    repeated = repo.save_many(key, [(RESOURCE_ACCOUNT, payload, "2026-10-23T15:00:30+00:00")])

    assert len(first) == 1 and len(repeated) == 1
    assert count_rows(repo.database_path, "dashboard_snapshots") == 1
    # Repeating the same payload appends no version, but the observation moves.
    assert repo.latest(key, RESOURCE_ACCOUNT).observed_at == "2026-10-23T15:00:30+00:00"

    updated = repo.save_many(
        key,
        [(RESOURCE_ACCOUNT, {**payload, "cash": 90.0}, "2026-10-23T15:01:00+00:00")],
    )
    assert len(updated) == 1
    assert count_rows(repo.database_path, "dashboard_snapshots") == 2
    latest = repo.latest(key, RESOURCE_ACCOUNT)
    assert latest is not None
    assert latest.payload["cash"] == 90.0
    # The previous version is preserved, never rewritten.
    assert count_rows(
        repo.database_path,
        "dashboard_snapshots",
        "content_hash = ?",
        (content_hash(payload),),
    ) == 1


def test_identical_payload_refreshes_age_without_appending_a_version(tmp_path):
    """Exact regression: a new correct read of an unchanged payload must date the data."""
    repo = repository(tmp_path)
    key = identity_key(environment_fingerprint(settings_for(tmp_path)), "account-1")
    payload = {"account_id": "account-1", "cash": 100.0, "portfolio_value": 150.0}

    repo.save_many(key, [(RESOURCE_ACCOUNT, payload, "2026-10-23T10:00:00+00:00")])
    repo.save_many(key, [(RESOURCE_ACCOUNT, payload, "2026-10-23T10:30:00+00:00")])

    latest = repo.latest(key, RESOURCE_ACCOUNT)
    assert latest is not None
    assert latest.observed_at == "2026-10-23T10:30:00+00:00"
    assert latest.payload == payload
    assert latest.observation_status == "current"
    assert count_rows(repo.database_path, "dashboard_snapshots") == 1
    observed_later = datetime(2026, 10, 23, 10, 30, 30, tzinfo=timezone.utc)
    assert latest.age_seconds(observed_later) == 30.0


def test_out_of_order_observation_never_regresses_freshness(tmp_path):
    repo = repository(tmp_path)
    key = identity_key(environment_fingerprint(settings_for(tmp_path)), "account-1")
    repo.save_many(key, [(RESOURCE_ACCOUNT, {"cash": 10.0}, "2026-10-23T15:00:00+00:00")])
    repo.save_many(key, [(RESOURCE_ACCOUNT, {"cash": 20.0}, "2026-10-23T14:59:00+00:00")])

    latest = repo.latest(key, RESOURCE_ACCOUNT)
    assert latest is not None
    assert latest.payload["cash"] == 10.0
    assert latest.observed_at == "2026-10-23T15:00:00+00:00"


def test_invalid_last_observation_declares_fallback_without_inventing_freshness(tmp_path):
    repo = repository(tmp_path)
    key = identity_key(environment_fingerprint(settings_for(tmp_path)), "account-1")
    repo.save_many(key, [(RESOURCE_ACCOUNT, {"cash": 1.0}, "2026-10-23T15:00:00+00:00")])
    repo.save_many(key, [(RESOURCE_ACCOUNT, {"cash": 2.0}, "2026-10-23T15:01:00+00:00")])

    with sqlite3.connect(repo.database_path) as conn:
        conn.execute(
            "UPDATE dashboard_snapshots SET payload_json = '{not json' WHERE payload_json LIKE ?",
            ('%"cash":2.0%',),
        )

    latest = repo.latest(key, RESOURCE_ACCOUNT)
    assert latest is not None
    assert latest.payload["cash"] == 1.0
    # The last observation belonged to the broken payload: it grants no freshness.
    assert latest.observed_at == "2026-10-23T15:00:00+00:00"
    assert latest.observation_status == "invalid_payload"


def test_state_is_isolated_per_account_and_resource(tmp_path):
    repo = repository(tmp_path)
    fingerprint = environment_fingerprint(settings_for(tmp_path))
    key_a1 = identity_key(fingerprint, "account-1")
    key_a2 = identity_key(fingerprint, "account-2")
    repo.save_many(key_a1, [(RESOURCE_ACCOUNT, {"cash": 10.0}, "2026-10-23T15:00:00+00:00")])
    repo.save_many(key_a2, [(RESOURCE_ACCOUNT, {"cash": 20.0}, "2026-10-23T15:00:30+00:00")])
    repo.save_many(key_a1, [(RESOURCE_FILLS, {"fills": [], "count": 0}, "2026-10-23T15:02:00+00:00")])

    assert repo.latest(key_a1, RESOURCE_ACCOUNT).observed_at == "2026-10-23T15:00:00+00:00"
    assert repo.latest(key_a2, RESOURCE_ACCOUNT).observed_at == "2026-10-23T15:00:30+00:00"
    assert repo.latest(key_a1, RESOURCE_FILLS).observed_at == "2026-10-23T15:02:00+00:00"


def test_batch_write_is_atomic_when_one_entry_is_invalid(tmp_path):
    repo = repository(tmp_path)
    key = identity_key(environment_fingerprint(settings_for(tmp_path)), "account-1")
    entries = [
        (RESOURCE_ACCOUNT, {"account_id": "account-1", "cash": 1.0}, "2026-10-23T15:00:00+00:00"),
        ("api_keys", {"secret": "nope"}, "2026-10-23T15:00:00+00:00"),
    ]

    with pytest.raises(ValueError):
        repo.save_many(key, entries)

    assert count_rows(repo.database_path, "dashboard_snapshots") == 0
    assert repo.latest(key, RESOURCE_ACCOUNT) is None


def test_invalid_observed_at_rejects_the_whole_batch(tmp_path):
    repo = repository(tmp_path)
    key = identity_key(environment_fingerprint(settings_for(tmp_path)), "account-1")

    with pytest.raises(ValueError):
        repo.save_many(
            key,
            [
                (RESOURCE_ACCOUNT, {"cash": 1.0}, "2026-10-23T15:00:00+00:00"),
                (RESOURCE_FILLS, {"fills": [], "count": 0}, "not-a-timestamp"),
            ],
        )

    assert count_rows(repo.database_path, "dashboard_snapshots") == 0


def test_schema_version_is_persisted_and_other_versions_are_ignored(tmp_path):
    repo = repository(tmp_path)
    key = identity_key(environment_fingerprint(settings_for(tmp_path)), "account-1")
    repo.save_many(key, [(RESOURCE_ACCOUNT, {"cash": 1.0}, "2026-10-23T15:00:00+00:00")])
    repo.save_many(key, [(RESOURCE_ACCOUNT, {"cash": 2.0}, "2026-10-23T15:01:00+00:00")])

    with sqlite3.connect(repo.database_path) as conn:
        stored = conn.execute(
            "SELECT schema_version FROM dashboard_snapshots"
        ).fetchall()
        assert {int(row[0]) for row in stored} == {SCHEMA_VERSION}
        # Simulate a future/foreign schema for the newest version.
        conn.execute(
            "UPDATE dashboard_snapshots SET schema_version = ? WHERE payload_json LIKE ?",
            (SCHEMA_VERSION + 99, '%"cash":2.0%'),
        )

    latest = repo.latest(key, RESOURCE_ACCOUNT)
    assert latest is not None
    assert latest.payload["cash"] == 1.0
    assert latest.schema_version == SCHEMA_VERSION
    # The newest observation pointed at a foreign schema: it grants no freshness.
    assert latest.observation_status == "invalid_payload"


def test_corrupt_payload_falls_back_to_last_correct_version(tmp_path):
    repo = repository(tmp_path)
    key = identity_key(environment_fingerprint(settings_for(tmp_path)), "account-1")
    repo.save_many(key, [(RESOURCE_ACCOUNT, {"cash": 1.0}, "2026-10-23T15:00:00+00:00")])
    repo.save_many(key, [(RESOURCE_ACCOUNT, {"cash": 2.0}, "2026-10-23T15:01:00+00:00")])

    with sqlite3.connect(repo.database_path) as conn:
        conn.execute(
            "UPDATE dashboard_snapshots SET payload_json = '{not json' WHERE payload_json LIKE ?",
            ('%"cash":2.0%',),
        )

    latest = repo.latest(key, RESOURCE_ACCOUNT)
    assert latest is not None
    assert latest.payload["cash"] == 1.0


def test_tampered_payload_hash_mismatch_is_rejected(tmp_path):
    repo = repository(tmp_path)
    key = identity_key(environment_fingerprint(settings_for(tmp_path)), "account-1")
    repo.save_many(key, [(RESOURCE_ACCOUNT, {"cash": 1.0}, "2026-10-23T15:00:00+00:00")])

    with sqlite3.connect(repo.database_path) as conn:
        conn.execute(
            "UPDATE dashboard_snapshots SET payload_json = ?",
            ('{"cash": 99999.0}',),
        )

    assert repo.latest(key, RESOURCE_ACCOUNT) is None


def test_accounts_and_environments_are_isolated(tmp_path):
    repo = repository(tmp_path)
    first = environment_fingerprint(settings_for(tmp_path))
    second = environment_fingerprint(
        settings_for(tmp_path, ALPACA_PAPER=False, ALPACA_ENDPOINT="https://api.alpaca.markets")
    )
    key_a1 = identity_key(first, "account-1")
    key_a2 = identity_key(first, "account-2")
    key_b1 = identity_key(second, "account-1")

    repo.save_many(key_a1, [(RESOURCE_ACCOUNT, {"cash": 10.0}, "2026-10-23T15:00:00+00:00")])
    repo.save_many(key_a2, [(RESOURCE_ACCOUNT, {"cash": 20.0}, "2026-10-23T15:00:00+00:00")])
    repo.save_many(key_b1, [(RESOURCE_ACCOUNT, {"cash": 30.0}, "2026-10-23T15:00:00+00:00")])

    assert repo.latest(key_a1, RESOURCE_ACCOUNT).payload["cash"] == 10.0
    assert repo.latest(key_a2, RESOURCE_ACCOUNT).payload["cash"] == 20.0
    assert repo.latest(key_b1, RESOURCE_ACCOUNT).payload["cash"] == 30.0
    assert set(repo.load_all(key_a1)) == {RESOURCE_ACCOUNT}


def test_all_resources_round_trip_with_their_own_timestamp(tmp_path):
    repo = repository(tmp_path)
    key = identity_key(environment_fingerprint(settings_for(tmp_path)), "account-1")
    entries = [
        (RESOURCE_ACCOUNT, {"account_id": "account-1", "cash": 1.0}, "2026-10-23T15:00:00+00:00"),
        (RESOURCE_POSITIONS, {"positions": []}, "2026-10-23T15:00:01+00:00"),
        (RESOURCE_ORDERS, {"orders": []}, "2026-10-23T15:00:02+00:00"),
        (RESOURCE_FILLS, {"fills": [], "count": 0}, "2026-10-23T15:00:03+00:00"),
        (RESOURCE_CURVE, {"curve": {"equity": [1, 2]}}, "2026-10-23T15:00:04+00:00"),
    ]
    saved = repo.save_many(key, entries)
    assert {item.resource for item in saved} == {
        RESOURCE_ACCOUNT,
        RESOURCE_POSITIONS,
        RESOURCE_ORDERS,
        RESOURCE_FILLS,
        RESOURCE_CURVE,
    }

    loaded = repo.load_all(key)
    assert loaded[RESOURCE_ACCOUNT].observed_at == "2026-10-23T15:00:00+00:00"
    assert loaded[RESOURCE_CURVE].observed_at == "2026-10-23T15:00:04+00:00"
    assert loaded[RESOURCE_FILLS].age_seconds() is not None


def test_attempts_are_recorded_without_destroying_the_last_correct_version(tmp_path):
    repo = repository(tmp_path)
    key = identity_key(environment_fingerprint(settings_for(tmp_path)), "account-1")
    repo.save_many(key, [(RESOURCE_CURVE, {"curve": {"equity": [1]}}, "2026-10-23T15:00:00+00:00")])

    repo.record_attempt(key, RESOURCE_CURVE, "error", error_code="TimeoutError", duration_ms=30000.0)

    assert repo.latest(key, RESOURCE_CURVE).payload == {"curve": {"equity": [1]}}
    attempt = repo.last_attempt(key, RESOURCE_CURVE)
    assert attempt is not None
    assert attempt.outcome == "error"
    assert attempt.error_code == "TimeoutError"
    assert attempt.duration_ms == 30000.0


def test_account_hint_is_scoped_by_environment(tmp_path):
    repo = repository(tmp_path)
    fingerprint = environment_fingerprint(settings_for(tmp_path))
    other = environment_fingerprint(settings_for(tmp_path, TRADING_MODE="live", ALPACA_PAPER=False))

    assert repo.account_hint(fingerprint) is None
    repo.record_account_hint(fingerprint, "account-1")
    repo.record_account_hint(fingerprint, "account-2")
    assert repo.account_hint(fingerprint) == "account-2"
    assert repo.account_hint(other) is None


def test_snapshot_schema_uses_store_connections(tmp_path):
    settings = settings_for(tmp_path)
    Store(settings.database_path, settings.agent_logs_dir).ensure_schema()
    SnapshotRepository(settings.database_path).ensure_schema()
    with sqlite3.connect(settings.database_path) as conn:
        names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
    assert {"dashboard_snapshots", "dashboard_snapshot_state", "dashboard_snapshot_attempts", "dashboard_identity_hints"} <= names


@pytest.fixture(autouse=True)
def forbid_sockets(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network prohibited in dashboard tests")
    monkeypatch.setattr("socket.create_connection", forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)
