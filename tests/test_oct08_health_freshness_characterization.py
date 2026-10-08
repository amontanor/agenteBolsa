"""Caracterizacion aislada de frescura del bloqueo operativo de compras.

Estas pruebas documentan el comportamiento observado en la base 0.4.348:
``load_operational_block_context`` consume el ultimo informe de salud completo
durante seis horas aunque un snapshot posterior ya exista. No son una
implementacion del refresco; fijan evidencia reproducible para un lote futuro.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

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
