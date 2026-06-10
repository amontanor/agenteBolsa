"""Tests del contexto macro y la tesis de mercado (T3.1)."""

import json

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.macro_context import (
    build_market_thesis,
    fetch_macro_events,
    risk_off_buy_factor,
)


def _setup(tmp_path, **overrides):
    settings = Settings(DATA_DIR=tmp_path, **overrides)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return settings, store


def test_fetch_macro_events_degrades_without_provider(tmp_path):
    settings, _ = _setup(tmp_path)
    events = fetch_macro_events(settings)
    assert events["quality"] == "no_provider"
    assert events["economic_calendar"] == []


def test_build_market_thesis_persists(tmp_path):
    settings, store = _setup(tmp_path)

    def llm(messages):
        return json.dumps(
            {
                "stance": "risk_off",
                "confidence": 0.85,
                "key_risks": ["fed hawkish"],
                "key_catalysts": [],
                "sector_bias": {"tech": "underweight"},
                "changes_vs_previous": "mas cauto",
            }
        )

    thesis = build_market_thesis(store, settings, macro_events={"quality": "ok"}, llm=llm)
    assert thesis["stance"] == "risk_off"
    assert thesis["confidence"] == 0.85
    latest = store.latest_market_thesis()
    assert latest["stance"] == "risk_off"


def test_build_market_thesis_clamps_invalid_values(tmp_path):
    settings, store = _setup(tmp_path)

    def llm(messages):
        return json.dumps({"stance": "moon", "confidence": 5.0})

    thesis = build_market_thesis(store, settings, macro_events={"quality": "ok"}, llm=llm)
    assert thesis["stance"] == "neutral"
    assert thesis["confidence"] == 1.0


def test_risk_off_buy_factor(tmp_path):
    settings, _ = _setup(tmp_path)
    assert risk_off_buy_factor(settings, {"stance": "risk_off", "confidence": 0.85}) == 0.5
    assert risk_off_buy_factor(settings, {"stance": "risk_off", "confidence": 0.6}) == 1.0
    assert risk_off_buy_factor(settings, {"stance": "risk_on", "confidence": 0.95}) == 1.0
    assert risk_off_buy_factor(settings, None) == 1.0
