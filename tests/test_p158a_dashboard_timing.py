"""P-L158-A: el temporizador del dashboard mide sin interrumpir el render."""

from __future__ import annotations

import json

from agente_bolsa.web_app import _DashboardTimer


def test_timer_records_section_duration():
    timer = _DashboardTimer()
    timer.start("setup")
    timer.stop("setup")
    assert "setup" in timer.sections
    assert timer.sections["setup"] >= 0.0


def test_stop_without_start_is_tolerated():
    timer = _DashboardTimer()
    timer.stop("missing")
    assert timer.sections == {}
    assert timer.emit() == {"total_seconds": 0.0, "sections": {}}


def test_emit_logs_total_equal_to_section_sum(capsys):
    timer = _DashboardTimer()
    timer.start("a")
    timer.stop("a")
    timer.start("b")
    timer.stop("b")
    payload = timer.emit()
    # La linea sale por stdout a proposito (el handler de Streamlit filtra
    # INFO y debe llegar al log del contenedor).
    out = capsys.readouterr().out
    assert "dashboard_timing" in out
    assert payload["total_seconds"] == round(
        payload["sections"]["a"] + payload["sections"]["b"], 3
    )
    logged = json.loads(out.split("dashboard_timing ", 1)[1])
    assert logged["total_seconds"] == payload["total_seconds"]


def test_timer_never_raises_on_bad_input():
    timer = _DashboardTimer()
    timer.start("")
    timer.stop("")
    assert timer.emit()["total_seconds"] >= 0.0
