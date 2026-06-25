"""Tests del registro de estrategias plugables (T1.2)."""

import numpy as np
import pandas as pd

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.strategies.base import MarketContext
from agente_bolsa.strategies.builtin_breakout import BreakoutMomentumStrategy
from agente_bolsa.strategies.registry import (
    discover,
    discover_active,
    register,
    validate_strategy_source,
)
from agente_bolsa.tools.technical_analysis import add_basic_technical_features
from agente_bolsa.tools.technical_state_validator import validate_symbol_technical_state


def _store(tmp_path):
    settings = Settings(DATA_DIR=tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def _synthetic_prices(rows: int = 260, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-01", periods=rows)
    steps = rng.normal(0.001, 0.02, size=rows).cumsum()
    close = 100.0 * np.exp(steps)
    high = close * (1 + rng.uniform(0.0, 0.01, size=rows))
    low = close * (1 - rng.uniform(0.0, 0.01, size=rows))
    open_ = close * (1 + rng.normal(0.0, 0.003, size=rows))
    volume = rng.integers(1_000_000, 5_000_000, size=rows)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates,
    )


# -- AST guard --------------------------------------------------------------
def test_validate_strategy_source_rejects_forbidden_imports():
    assert validate_strategy_source("import os\n") is None
    assert validate_strategy_source("from agente_bolsa.tools.broker import X") is not None
    assert validate_strategy_source("from agente_bolsa.tools.execution import s") is not None
    assert validate_strategy_source("import requests") is not None
    assert validate_strategy_source("import urllib.request") is not None


# -- Regresion: builtin_breakout == bucle previo ---------------------------
def test_builtin_breakout_matches_inline_candidate():
    raw = _synthetic_prices()
    context = MarketContext(symbols=["AAA"], data=raw, multi_symbol=False, benchmark_return_20d=0.01)

    produced = BreakoutMomentumStrategy().generate_candidates(context)

    # Reproduccion del bucle previo de technical_study.
    features = add_basic_technical_features(raw.copy().dropna(how="all"))
    expected = validate_symbol_technical_state("AAA", features)
    sr20 = (expected.get("technical_state", {}) or {}).get("return_20d")
    expected["relative_return_20d"] = round(sr20 - 0.01, 4) if sr20 is not None else None

    assert produced == [expected]


# -- Registry ---------------------------------------------------------------
def test_discover_defaults_to_builtin_breakout(tmp_path):
    store = _store(tmp_path)
    strategies = discover(store)
    names = {s.name: s.status for s in strategies}
    assert names.get("builtin_breakout") == "ACTIVE"
    assert names.get("builtin_pullback") == "SHADOW"
    assert discover_active(store)  # al menos una ACTIVE
    assert "builtin_pullback" not in {s.name for s in discover_active(store)}


def test_register_and_status_transitions(tmp_path):
    store = _store(tmp_path)
    register(store, name="my_shadow", status="SHADOW")
    rows = {r["name"]: r["status"] for r in store.strategy_versions()}
    assert rows["my_shadow"] == "SHADOW"

    store.set_strategy_status("my_shadow", "RETIRED")
    rows = {r["name"]: r["status"] for r in store.strategy_versions()}
    assert rows["my_shadow"] == "RETIRED"


def test_retiring_builtin_removes_it_from_discovery(tmp_path):
    store = _store(tmp_path)
    register(store, name="builtin_breakout", version="1", status="RETIRED")
    names = {s.name for s in discover(store)}
    assert "builtin_breakout" not in names


def test_shadow_builtin_is_discovered_but_not_active(tmp_path):
    store = _store(tmp_path)
    register(store, name="builtin_breakout", version="1", status="SHADOW")
    discovered = {s.name: s.status for s in discover(store)}
    assert discovered.get("builtin_breakout") == "SHADOW"
    assert "builtin_breakout" not in {s.name for s in discover_active(store)}
