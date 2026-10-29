"""P-L172: el semaforo del LLM se evalua en vivo, no desde el informe cacheado.

agents_healthcheck corre cada 30 minutos; leer su ultimo informe hacia que el
panel mostrara DOWN justo despues de restaurar el proveedor o de la primera
decision real del ciclo.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from agente_bolsa.tools import llm_degraded_watchdog
from agente_bolsa.tools.system_status import DOWN, WARN, build_status


def _reports(tmp_path: Path, *, degraded: bool, severity: str) -> Path:
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    payload = {"watchdog": {"degraded": degraded, "severity": severity}}
    (reports / "latest_agents_healthcheck.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    return reports


def _db(tmp_path: Path) -> Path:
    db = tmp_path / "state" / "agente_bolsa.sqlite3"
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db):
        pass
    return db


def _llm_component(status: dict) -> dict:
    return next(item for item in status["components"] if item["name"] == "LLM de decision")


def test_stale_critical_report_does_not_override_live_evaluation(tmp_path: Path) -> None:
    reports = _reports(tmp_path, degraded=True, severity="critical")
    status = build_status(db_path=_db(tmp_path), reports_dir=reports)

    component = _llm_component(status)
    # En vivo, sin decisiones y sin fallback reciente, la severidad es warning.
    assert component["state"] == WARN
    assert component["state"] != DOWN


def test_live_ok_with_recent_decision_marks_llm_ok(tmp_path: Path, monkeypatch) -> None:
    reports = _reports(tmp_path, degraded=True, severity="critical")
    now = datetime.now(timezone.utc).isoformat()

    def _fake_evaluate(_db, **_kwargs):
        return {
            "degraded": False,
            "severity": "ok",
            "last_decision_llm_at": now,
            "recent_recommendations": {"total": 1, "fallback": 0, "ratio": 0.0},
        }

    monkeypatch.setattr(llm_degraded_watchdog, "evaluate", _fake_evaluate)

    status = build_status(db_path=_db(tmp_path), reports_dir=reports)

    component = _llm_component(status)
    assert component["state"] == "OK"
    assert "0.0 h" in component["detail"]
