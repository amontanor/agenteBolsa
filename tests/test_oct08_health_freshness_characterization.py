"""Caracterizacion y contrato aislado de frescura del bloqueo operativo."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.tools import operational_health
from agente_bolsa.tools.operational_health import (
    KILL_SWITCH_MAX_REPORT_AGE_SECONDS,
    activate_persistent_kill_switch,
    load_operational_block_context,
)

FIXED_NOW = datetime(2026, 10, 8, 19, 15, tzinfo=timezone.utc)


class _FrozenDateTime(datetime):
    """Reloj local de la prueba para que la edad del informe sea determinista."""

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return FIXED_NOW.replace(tzinfo=None)
        return FIXED_NOW.astimezone(tz)


def _freeze_health_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(operational_health, "datetime", _FrozenDateTime)


def _write_json_with_mtime(path: Path, payload: dict, observed_at: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    timestamp = observed_at.timestamp()
    os.utime(path, (timestamp, timestamp))


def _critical_alert(kind: str, detail: str) -> dict[str, str]:
    return {
        "severity": "critical",
        "kind": kind,
        "scope": "market_data" if kind == "data_pipeline_down" else "market_cycle",
        "detail": detail,
    }


def _health_payload(
    health_at: datetime | None,
    *,
    alerts: list[dict[str, str]],
    session_date: str = "2026-10-08",
    calendar: str | None = "XNYS",
    local_timezone: str | None = "Europe/Madrid",
) -> dict:
    pipeline = {"session_date": session_date}
    if calendar is not None:
        pipeline["calendar"] = calendar
    if local_timezone is not None:
        pipeline["local_timezone"] = local_timezone
    payload = {
        "report_health": {"data_pipeline": pipeline},
        "alerts": alerts,
    }
    if health_at is not None:
        payload["as_of"] = health_at.isoformat()
    return payload


def _valid_snapshot(session_date: str = "2026-10-08") -> dict:
    return {
        "as_of": session_date,
        "benchmark": "SPY",
        "provider": "local",
        "symbols": {"SPY": {"close": 500.0}},
        "warnings": [],
    }


def _valid_market_state(captured_at: datetime = FIXED_NOW - timedelta(minutes=10)) -> dict:
    return {
        "as_of": captured_at.isoformat(),
        "run_id": "state_recovered",
        "provider": "local",
        "benchmark": "SPY",
        "data_quality": {"status": "GOOD"},
    }


def test_stale_data_pipeline_alert_survives_newer_snapshot(tmp_path, monkeypatch):
    """Reproduce old health block after pipeline produced a newer snapshot."""

    _freeze_health_clock(monkeypatch)
    health_at = FIXED_NOW - timedelta(minutes=80)
    snapshot_at = FIXED_NOW - timedelta(minutes=20)
    reports = tmp_path / "reports"
    _write_json_with_mtime(
        reports / "latest_operational_health.json",
        {
            "as_of": health_at.isoformat(),
            "alerts": [
                _critical_alert(
                    "data_pipeline_down",
                    "Sin snapshots frescos durante 30 minutos.",
                )
            ],
        },
        health_at,
    )
    _write_json_with_mtime(
        reports / "market_snapshot_recovered.json",
        {"as_of": snapshot_at.isoformat(), "symbols": {"SPY": {"close": 1.0}}},
        snapshot_at,
    )

    block = load_operational_block_context(tmp_path, now=FIXED_NOW)

    assert snapshot_at > health_at
    assert block["as_of"] == health_at.isoformat()
    assert block["kill_switch_active"] is True
    assert block["block_new_buys"] is True
    assert block["block_buy_execution"] is True
    assert block["blocking_alerts"][0]["kind"] == "data_pipeline_down"
    assert block["reasons"] == [
        "data_pipeline_down:market_data: Sin snapshots frescos durante 30 minutos."
    ]


def test_stale_pipeline_alert_does_not_hide_other_critical_alerts(tmp_path, monkeypatch):
    """Current loader retains unrelated critical gates beside stale pipeline data."""

    _freeze_health_clock(monkeypatch)
    health_at = FIXED_NOW - timedelta(minutes=80)
    snapshot_at = FIXED_NOW - timedelta(minutes=20)
    reports = tmp_path / "reports"
    alerts = [
        _critical_alert("data_pipeline_down", "Sin snapshots frescos."),
        _critical_alert("job_failed", "market_cycle fallo; requiere diagnostico."),
    ]
    _write_json_with_mtime(
        reports / "latest_operational_health.json",
        {"as_of": health_at.isoformat(), "alerts": alerts},
        health_at,
    )
    _write_json_with_mtime(
        reports / "market_snapshot_recovered.json",
        {"as_of": snapshot_at.isoformat()},
        snapshot_at,
    )

    block = load_operational_block_context(tmp_path, now=FIXED_NOW)

    assert {item["kind"] for item in block["blocking_alerts"]} == {
        "data_pipeline_down",
        "job_failed",
    }
    assert block["kill_switch_active"] is True
    assert block["block_buy_execution"] is True


def test_persistent_override_remains_authoritative_after_healthy_report(tmp_path, monkeypatch):
    """A selective refresh must never clear a persistent human safety override."""

    _freeze_health_clock(monkeypatch)
    reports = tmp_path / "reports"
    _write_json_with_mtime(
        reports / "latest_operational_health.json",
        {"as_of": FIXED_NOW.isoformat(), "alerts": []},
        FIXED_NOW,
    )
    override = activate_persistent_kill_switch(
        tmp_path,
        reason="manual_pause: operator review required",
        kind="manual",
    )

    block = load_operational_block_context(tmp_path, now=FIXED_NOW)

    assert override["active"] is True
    assert block["kill_switch_active"] is True
    assert block["block_new_buys"] is True
    assert block["block_buy_execution"] is True
    assert block["reasons"] == ["manual_pause: operator review required"]
    assert (tmp_path / "state" / "operational_kill_switch.json").exists()


def test_report_older_than_six_hours_fails_open_without_inventing_pipeline_state(tmp_path, monkeypatch):
    """An expired health report yields explicit stale evidence, not a fresh block."""

    _freeze_health_clock(monkeypatch)
    health_at = FIXED_NOW - timedelta(seconds=KILL_SWITCH_MAX_REPORT_AGE_SECONDS + 1)
    _write_json_with_mtime(
        tmp_path / "reports" / "latest_operational_health.json",
        {
            "as_of": health_at.isoformat(),
            "alerts": [_critical_alert("data_pipeline_down", "Informe antiguo.")],
        },
        health_at,
    )

    block = load_operational_block_context(tmp_path, now=FIXED_NOW)

    assert block["available"] is True
    assert block["kill_switch_active"] is False
    assert block["block_new_buys"] is False
    assert block["block_buy_execution"] is False
    assert block["blocking_alerts"] == []
    assert block["reasons"] == [
        f"stale_operational_health_report:{KILL_SWITCH_MAX_REPORT_AGE_SECONDS + 1}s"
    ]


def test_newer_valid_same_session_snapshot_recovers_only_pipeline_block(tmp_path, monkeypatch):
    _freeze_health_clock(monkeypatch)
    health_at = FIXED_NOW - timedelta(minutes=20)
    snapshot_at = FIXED_NOW - timedelta(minutes=10)
    reports = tmp_path / "reports"
    alert = _critical_alert("data_pipeline_down", "Sin snapshots frescos.")
    _write_json_with_mtime(
        reports / "latest_operational_health.json",
        _health_payload(health_at, alerts=[alert]),
        health_at,
    )
    _write_json_with_mtime(reports / "market_state_recovered.json", _valid_market_state(snapshot_at), snapshot_at)

    block = load_operational_block_context(tmp_path, now=FIXED_NOW)

    assert block["as_of"] == health_at.isoformat()
    assert block["kill_switch_active"] is False
    assert block["block_new_buys"] is False
    assert block["block_buy_execution"] is False
    assert block["blocking_alerts"] == []
    assert block["reasons"] == []


def test_newer_valid_snapshot_preserves_unrelated_critical_alert(tmp_path, monkeypatch):
    _freeze_health_clock(monkeypatch)
    health_at = FIXED_NOW - timedelta(minutes=20)
    snapshot_at = FIXED_NOW - timedelta(minutes=10)
    reports = tmp_path / "reports"
    alerts = [
        _critical_alert("data_pipeline_down", "Sin snapshots frescos."),
        _critical_alert("job_failed", "market_cycle fallo; requiere diagnostico."),
    ]
    _write_json_with_mtime(
        reports / "latest_operational_health.json",
        _health_payload(health_at, alerts=alerts),
        health_at,
    )
    _write_json_with_mtime(reports / "market_state_recovered.json", _valid_market_state(snapshot_at), snapshot_at)

    block = load_operational_block_context(tmp_path, now=FIXED_NOW)

    assert block["kill_switch_active"] is True
    assert block["block_buy_execution"] is True
    assert [item["kind"] for item in block["blocking_alerts"]] == ["job_failed"]


def test_missing_health_as_of_keeps_pipeline_block_even_with_newer_snapshot(tmp_path, monkeypatch):
    _freeze_health_clock(monkeypatch)
    health_at = FIXED_NOW - timedelta(minutes=20)
    snapshot_at = FIXED_NOW - timedelta(minutes=10)
    reports = tmp_path / "reports"
    _write_json_with_mtime(
        reports / "latest_operational_health.json",
        _health_payload(None, alerts=[_critical_alert("data_pipeline_down", "Sin snapshots frescos.")]),
        health_at,
    )
    _write_json_with_mtime(reports / "market_state_recovered.json", _valid_market_state(snapshot_at), snapshot_at)

    block = load_operational_block_context(tmp_path, now=FIXED_NOW)

    assert block["kill_switch_active"] is True
    assert block["blocking_alerts"][0]["kind"] == "data_pipeline_down"


def test_naive_health_as_of_keeps_pipeline_block_even_with_newer_snapshot(tmp_path, monkeypatch):
    _freeze_health_clock(monkeypatch)
    health_at = FIXED_NOW - timedelta(minutes=20)
    snapshot_at = FIXED_NOW - timedelta(minutes=10)
    reports = tmp_path / "reports"
    payload = _health_payload(
        None,
        alerts=[_critical_alert("data_pipeline_down", "Sin snapshots frescos.")],
    )
    payload["as_of"] = "2026-10-08T19:00:00"
    _write_json_with_mtime(reports / "latest_operational_health.json", payload, health_at)
    _write_json_with_mtime(reports / "market_state_recovered.json", _valid_market_state(snapshot_at), snapshot_at)

    block = load_operational_block_context(tmp_path, now=FIXED_NOW)

    assert block["kill_switch_active"] is True
    assert block["blocking_alerts"][0]["kind"] == "data_pipeline_down"


def test_future_health_as_of_keeps_pipeline_block(tmp_path, monkeypatch):
    _freeze_health_clock(monkeypatch)
    health_at = FIXED_NOW + timedelta(minutes=1)
    snapshot_at = FIXED_NOW - timedelta(minutes=10)
    reports = tmp_path / "reports"
    _write_json_with_mtime(
        reports / "latest_operational_health.json",
        _health_payload(health_at, alerts=[_critical_alert("data_pipeline_down", "Sin snapshots frescos.")]),
        FIXED_NOW - timedelta(minutes=20),
    )
    _write_json_with_mtime(reports / "market_state_recovered.json", _valid_market_state(snapshot_at), snapshot_at)

    block = load_operational_block_context(tmp_path, now=FIXED_NOW)

    assert block["kill_switch_active"] is True
    assert block["blocking_alerts"][0]["kind"] == "data_pipeline_down"


@pytest.mark.parametrize("artifact_payload", [{}, {"as_of": "2026-10-08"}])
def test_empty_or_unknown_artifact_does_not_authorize_recovery(tmp_path, monkeypatch, artifact_payload):
    _freeze_health_clock(monkeypatch)
    health_at = FIXED_NOW - timedelta(minutes=20)
    snapshot_at = FIXED_NOW - timedelta(minutes=10)
    reports = tmp_path / "reports"
    _write_json_with_mtime(
        reports / "latest_operational_health.json",
        _health_payload(health_at, alerts=[_critical_alert("data_pipeline_down", "Sin snapshots frescos.")]),
        health_at,
    )
    _write_json_with_mtime(reports / "market_state_recovered.json", artifact_payload, snapshot_at)

    block = load_operational_block_context(tmp_path, now=FIXED_NOW)

    assert block["kill_switch_active"] is True
    assert block["blocking_alerts"][0]["kind"] == "data_pipeline_down"


def test_future_mtime_does_not_authorize_recovery(tmp_path, monkeypatch):
    _freeze_health_clock(monkeypatch)
    health_at = FIXED_NOW - timedelta(minutes=20)
    reports = tmp_path / "reports"
    _write_json_with_mtime(
        reports / "latest_operational_health.json",
        _health_payload(health_at, alerts=[_critical_alert("data_pipeline_down", "Sin snapshots frescos.")]),
        health_at,
    )
    _write_json_with_mtime(
        reports / "market_state_recovered.json",
        _valid_market_state(FIXED_NOW - timedelta(minutes=10)),
        FIXED_NOW + timedelta(minutes=1),
    )

    block = load_operational_block_context(tmp_path, now=FIXED_NOW)

    assert block["kill_switch_active"] is True
    assert block["blocking_alerts"][0]["kind"] == "data_pipeline_down"


def test_date_only_snapshot_legacy_does_not_authorize_recovery(tmp_path, monkeypatch):
    _freeze_health_clock(monkeypatch)
    health_at = FIXED_NOW - timedelta(minutes=20)
    snapshot_at = FIXED_NOW - timedelta(minutes=10)
    reports = tmp_path / "reports"
    _write_json_with_mtime(
        reports / "latest_operational_health.json",
        _health_payload(health_at, alerts=[_critical_alert("data_pipeline_down", "Sin snapshots frescos.")]),
        health_at,
    )
    _write_json_with_mtime(reports / "market_snapshot_recovered.json", _valid_snapshot(), snapshot_at)

    block = load_operational_block_context(tmp_path, now=FIXED_NOW)

    assert block["kill_switch_active"] is True
    assert block["blocking_alerts"][0]["kind"] == "data_pipeline_down"


def test_touched_copy_with_old_content_does_not_authorize_recovery(tmp_path, monkeypatch):
    _freeze_health_clock(monkeypatch)
    health_at = FIXED_NOW - timedelta(minutes=20)
    touched_at = FIXED_NOW - timedelta(minutes=10)
    reports = tmp_path / "reports"
    _write_json_with_mtime(
        reports / "latest_operational_health.json",
        _health_payload(health_at, alerts=[_critical_alert("data_pipeline_down", "Sin snapshots frescos.")]),
        health_at,
    )
    _write_json_with_mtime(
        reports / "market_state_recovered.json",
        _valid_market_state(health_at - timedelta(minutes=1)),
        touched_at,
    )

    block = load_operational_block_context(tmp_path, now=FIXED_NOW)

    assert block["kill_switch_active"] is True
    assert block["blocking_alerts"][0]["kind"] == "data_pipeline_down"


def test_future_capture_timestamp_does_not_authorize_recovery(tmp_path, monkeypatch):
    _freeze_health_clock(monkeypatch)
    health_at = FIXED_NOW - timedelta(minutes=20)
    artifact_at = FIXED_NOW - timedelta(minutes=10)
    reports = tmp_path / "reports"
    _write_json_with_mtime(
        reports / "latest_operational_health.json",
        _health_payload(health_at, alerts=[_critical_alert("data_pipeline_down", "Sin snapshots frescos.")]),
        health_at,
    )
    _write_json_with_mtime(
        reports / "market_state_recovered.json",
        _valid_market_state(FIXED_NOW + timedelta(minutes=1)),
        artifact_at,
    )

    block = load_operational_block_context(tmp_path, now=FIXED_NOW)

    assert block["kill_switch_active"] is True
    assert block["blocking_alerts"][0]["kind"] == "data_pipeline_down"


def test_naive_reference_clock_fails_closed(tmp_path, monkeypatch):
    _freeze_health_clock(monkeypatch)
    health_at = FIXED_NOW - timedelta(minutes=20)
    _write_json_with_mtime(
        tmp_path / "reports" / "latest_operational_health.json",
        _health_payload(health_at, alerts=[_critical_alert("data_pipeline_down", "Sin snapshots frescos.")]),
        health_at,
    )

    block = load_operational_block_context(tmp_path, now=FIXED_NOW.replace(tzinfo=None))

    assert block["kill_switch_active"] is True
    assert block["blocking_alerts"][0]["kind"] == "invalid_operational_health_report"


def test_invalid_json_does_not_authorize_recovery(tmp_path, monkeypatch):
    _freeze_health_clock(monkeypatch)
    health_at = FIXED_NOW - timedelta(minutes=20)
    snapshot_at = FIXED_NOW - timedelta(minutes=10)
    reports = tmp_path / "reports"
    _write_json_with_mtime(
        reports / "latest_operational_health.json",
        _health_payload(health_at, alerts=[_critical_alert("data_pipeline_down", "Sin snapshots frescos.")]),
        health_at,
    )
    artifact = reports / "market_state_recovered.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("{invalid", encoding="utf-8")
    os.utime(artifact, (snapshot_at.timestamp(), snapshot_at.timestamp()))

    block = load_operational_block_context(tmp_path, now=FIXED_NOW)

    assert block["kill_switch_active"] is True
    assert block["blocking_alerts"][0]["kind"] == "data_pipeline_down"


def test_older_artifact_does_not_authorize_recovery(tmp_path, monkeypatch):
    _freeze_health_clock(monkeypatch)
    health_at = FIXED_NOW - timedelta(minutes=20)
    reports = tmp_path / "reports"
    _write_json_with_mtime(
        reports / "latest_operational_health.json",
        _health_payload(health_at, alerts=[_critical_alert("data_pipeline_down", "Sin snapshots frescos.")]),
        health_at,
    )
    _write_json_with_mtime(
        reports / "market_state_recovered.json",
        _valid_market_state(health_at - timedelta(minutes=1)),
        health_at - timedelta(minutes=1),
    )

    block = load_operational_block_context(tmp_path, now=FIXED_NOW)

    assert block["kill_switch_active"] is True
    assert block["blocking_alerts"][0]["kind"] == "data_pipeline_down"


def test_mismatched_session_does_not_authorize_recovery(tmp_path, monkeypatch):
    _freeze_health_clock(monkeypatch)
    health_at = FIXED_NOW - timedelta(minutes=20)
    snapshot_at = FIXED_NOW - timedelta(minutes=10)
    reports = tmp_path / "reports"
    _write_json_with_mtime(
        reports / "latest_operational_health.json",
        _health_payload(
            health_at,
            alerts=[_critical_alert("data_pipeline_down", "Sin snapshots frescos.")],
            session_date="2026-10-07",
        ),
        health_at,
    )
    _write_json_with_mtime(reports / "market_state_recovered.json", _valid_market_state(snapshot_at), snapshot_at)

    block = load_operational_block_context(tmp_path, now=FIXED_NOW)

    assert block["kill_switch_active"] is True
    assert block["blocking_alerts"][0]["kind"] == "data_pipeline_down"


def test_missing_calendar_metadata_stays_blocked_without_settings(tmp_path, monkeypatch):
    _freeze_health_clock(monkeypatch)
    health_at = FIXED_NOW - timedelta(minutes=20)
    snapshot_at = FIXED_NOW - timedelta(minutes=10)
    reports = tmp_path / "reports"
    _write_json_with_mtime(
        reports / "latest_operational_health.json",
        _health_payload(
            health_at,
            alerts=[_critical_alert("data_pipeline_down", "Sin snapshots frescos.")],
            calendar=None,
            local_timezone=None,
        ),
        health_at,
    )
    _write_json_with_mtime(reports / "market_state_recovered.json", _valid_market_state(snapshot_at), snapshot_at)

    block = load_operational_block_context(tmp_path, now=FIXED_NOW)

    assert block["kill_switch_active"] is True
    assert block["blocking_alerts"][0]["kind"] == "data_pipeline_down"


def test_explicit_settings_metadata_allows_legacy_pipeline_recovery(tmp_path, monkeypatch):
    _freeze_health_clock(monkeypatch)
    health_at = FIXED_NOW - timedelta(minutes=20)
    snapshot_at = FIXED_NOW - timedelta(minutes=10)
    reports = tmp_path / "reports"
    _write_json_with_mtime(
        reports / "latest_operational_health.json",
        _health_payload(
            health_at,
            alerts=[_critical_alert("data_pipeline_down", "Sin snapshots frescos.")],
            calendar=None,
            local_timezone=None,
        ),
        health_at,
    )
    _write_json_with_mtime(reports / "market_state_recovered.json", _valid_market_state(snapshot_at), snapshot_at)
    settings = Settings(
        _env_file=None,
        DATA_DIR=tmp_path,
        MARKET_CALENDAR="XNYS",
        LOCAL_TIMEZONE="Europe/Madrid",
    )

    block = load_operational_block_context(tmp_path, settings=settings, now=FIXED_NOW)

    assert block["kill_switch_active"] is False
    assert block["blocking_alerts"] == []
