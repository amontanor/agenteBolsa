"""P-L158-B: perfil fino del dashboard y total_seconds sin doble suma.

Formula documentada de total_seconds:
- si existe la seccion envolvente "total", total_seconds == sections["total"];
- si no existe, total_seconds == suma de las demas secciones (sin "total").
Nunca se suma "total" junto a sus parciales: eso duplicaba el tiempo real.
"""

from __future__ import annotations

import json

from agente_bolsa.web_app import _DashboardTimer

_OPENING_SUBSECTIONS = {
    "opening_context.opening_performance_context",
    "opening_context.daily_equity_metric_for_portfolio",
    "opening_context.position_intraday_pl_reconciliation",
    "opening_context.portfolio_value_series_from_alpaca",
    "opening_context.portfolio_equity_summary",
}


def test_total_seconds_equals_total_section_when_enveloping_exists(capsys):
    timer = _DashboardTimer()
    timer.start("total")
    timer.start("setup")
    timer.stop("setup")
    timer.start("opening_context")
    timer.start("opening_context.opening_performance_context")
    timer.stop("opening_context.opening_performance_context")
    timer.stop("opening_context")
    timer.stop("total")

    payload = timer.emit()

    assert payload["total_seconds"] == payload["sections"]["total"]
    logged = json.loads(capsys.readouterr().out.split("dashboard_timing ", 1)[1])
    assert logged["total_seconds"] == payload["sections"]["total"]


def test_total_seconds_falls_back_to_sum_without_total(capsys):
    timer = _DashboardTimer()
    timer.start("a")
    timer.stop("a")
    timer.start("b")
    timer.stop("b")

    payload = timer.emit()

    assert "total" not in payload["sections"]
    assert payload["total_seconds"] == round(
        payload["sections"]["a"] + payload["sections"]["b"], 3
    )


def test_nested_subsections_measured_without_breaking_render():
    timer = _DashboardTimer()
    timer.start("opening_context")
    for name in sorted(_OPENING_SUBSECTIONS):
        timer.start(name)
        timer.stop(name)
    timer.stop("opening_context")

    assert _OPENING_SUBSECTIONS <= set(timer.sections.keys())
    parent = timer.sections["opening_context"]
    child_sum = round(sum(timer.sections[name] for name in _OPENING_SUBSECTIONS), 3)
    # Cada sub-seccion es un subintervalo del padre; no puede superarlo salvo
    # por el redondeo a 3 decimales (tolerancia minima).
    assert child_sum <= parent + 0.01


def test_stop_without_start_tolerated_and_emit_never_raises():
    timer = _DashboardTimer()
    timer.stop("nunca_iniciada")
    timer.start("")
    timer.stop("")

    payload = timer.emit()

    assert "nunca_iniciada" not in payload["sections"]
    assert payload["total_seconds"] >= 0.0
