"""A2: el shadow de setup-edge por ciclo mide el funnel sin tocar la seleccion.

Verifica que `record_setup_edge_cycle_shadow`:
  - no hace nada con los flags apagados (no escribe reporte),
  - con el flag shadow encendido cuenta el funnel de setup-quality (incluido
    sin_patron|strong) y escribe el reporte, sin cambiar conducta real.
"""
from __future__ import annotations

import json

from agente_bolsa.config import Settings
from agente_bolsa.tools import trade_decision as td


def _technical_context():
    return {
        "run_id": "cycle-test",
        "selected_candidates": [
            {
                "symbol": "AAA",
                "direction": "long",
                "setup_quality": "strong",
                "technical_state": {
                    "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
                    "close": 100.0,
                    "return_20d": 0.12,
                    "sma_20": 90.0,
                    "last_date": "2026-06-22",
                },
            },
            {
                "symbol": "BBB",
                "direction": "long",
                "setup_quality": "strong",
                "technical_state": {
                    "chart_patterns": [],
                    "close": 50.0,
                    "return_20d": 0.06,
                    "sma_20": 48.0,
                    "last_date": "2026-06-22",
                },
            },
        ],
    }


def _market_state():
    return {"relative_strength": {"benchmark_return_20d": 0.03}}


def test_cycle_shadow_disabled_writes_nothing(tmp_path):
    settings = Settings(
        DATA_DIR=str(tmp_path),
        SETUP_EDGE_BIAS_SHADOW_ENABLED=False,
        SETUP_EDGE_BIAS_ENABLED=False,
    )
    result = td.record_setup_edge_cycle_shadow(settings, _technical_context(), _market_state())
    assert result == {"enabled": False}
    assert not (tmp_path / "reports" / "latest_setup_edge_cycle_shadow.json").exists()


def test_cycle_shadow_counts_funnel_and_writes_report(tmp_path, monkeypatch):
    # Edge table medida (mock): sin_patron|strong positivo, confirmed negativo.
    monkeypatch.setattr(
        td,
        "load_setup_edge_table",
        lambda *a, **k: {"sin_patron|strong": 0.02, "confirmed_pattern|strong": -0.01},
    )
    settings = Settings(DATA_DIR=str(tmp_path), SETUP_EDGE_BIAS_SHADOW_ENABLED=True)

    result = td.record_setup_edge_cycle_shadow(settings, _technical_context(), _market_state())

    assert result["enabled"] is True
    assert "error" not in result
    assert result["candidates_total"] == 2
    assert result["sin_patron_strong_count"] == 1

    report_path = tmp_path / "reports" / "latest_setup_edge_cycle_shadow.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["selection_method"] == "cycle_shadow"
    assert report["mode"] == "shadow"
    assert report["setup_quality_counts"]["sin_patron|strong"] == 1
    assert report["setup_quality_counts"]["confirmed_pattern|strong"] == 1
    # Las dos claves casan con la edge_table -> no debe haber claves sin match.
    assert report["keys_without_edge_match"] == []


def test_cycle_shadow_surfaces_positive_edge_candidates_from_all_candidates(tmp_path, monkeypatch):
    # Paso 1 A2: el shadow debe analizar TODO el slate (no solo finalistas) y
    # destacar los setups con edge positivo (sin_patron|mixed) que quedan fuera del corte.
    monkeypatch.setattr(
        td,
        "load_setup_edge_table",
        lambda *a, **k: {"sin_patron|mixed": 0.0049, "confirmed_pattern|strong": -0.0015},
    )
    settings = Settings(DATA_DIR=str(tmp_path), SETUP_EDGE_BIAS_SHADOW_ENABLED=True)

    # Estudio tecnico con un sin_patron|mixed de calidad que NO esta entre los finalistas.
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    study = {
        "all_candidates": [
            {
                "symbol": "AAA",  # finalista confirmed_pattern (en el contexto)
                "direction": "long",
                "setup_quality": "strong",
                "score": 18.0,
                "technical_state": {"chart_patterns": [{"bias": "bullish", "status": "confirmed"}], "return_20d": 0.12},
            },
            {
                "symbol": "ZZZ",  # sin_patron|mixed con buen score, NO finalista
                "direction": "long",
                "setup_quality": "mixed",
                "score": 15.0,
                "technical_state": {"chart_patterns": [], "return_20d": 0.08},
            },
        ]
    }
    (reports_dir / "latest_closed_market_technical_study.json").write_text(
        json.dumps(study), encoding="utf-8"
    )

    td.record_setup_edge_cycle_shadow(settings, _technical_context(), _market_state())

    report = json.loads((reports_dir / "latest_setup_edge_cycle_shadow.json").read_text(encoding="utf-8"))
    assert report["all_candidates_total"] == 2
    assert report["all_candidates_setup_counts"]["sin_patron|mixed"] == 1
    surfaced = {c["symbol"]: c for c in report["positive_edge_top_candidates"]}
    assert "ZZZ" in surfaced  # el sin_patron|mixed de edge+ se destaca
    assert surfaced["ZZZ"]["setup_edge_key"] == "sin_patron|mixed"
    assert surfaced["ZZZ"]["already_finalist"] is False
