"""Regresion A1: el benchmark debe incluirse en el snapshot aunque no este en el universo.

Bug (23/24-jun): build_market_snapshot descargaba el benchmark pero el bucle
iteraba solo sobre `symbols` (candidatos), asi que SPY no entraba en
snapshot["symbols"]. Resultado: market_state sin benchmark -> regime="unknown",
benchmark_return_20d=0 -> modo defensivo permanente y fuerza relativa rota.
"""
from __future__ import annotations

import pandas as pd

from agente_bolsa.tools import market_snapshot as ms


def _fake_features(frame):
    f = frame.copy()
    f["return_20d"] = 0.1
    f["sma_20"] = 2.0
    f["sma_50"] = 2.0
    f["sma_200"] = 2.0
    f["volume_zscore_20"] = 0.0
    f["atr_14"] = 0.1
    f["trend_positive"] = True
    f["above_long_trend"] = True
    return f


def test_benchmark_included_even_if_not_in_universe(tmp_path, monkeypatch):
    idx = pd.to_datetime(["2026-06-19", "2026-06-20", "2026-06-21"])

    def fake_frame(_data, _symbol, _multi):
        return pd.DataFrame({"Close": [1.0, 2.0, 3.0]}, index=idx)

    monkeypatch.setattr(ms, "download_daily_prices", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(ms, "_symbol_frame", fake_frame)
    monkeypatch.setattr(ms, "add_basic_technical_features", _fake_features)

    # Universo de candidatos SIN el benchmark.
    snap = ms.build_market_snapshot(["AAA", "BBB"], "SPY", tmp_path, "cid-test")

    assert "SPY" in snap["symbols"], "el benchmark debe aparecer en symbols"
    assert "AAA" in snap["symbols"] and "BBB" in snap["symbols"]
    # El benchmark trae tecnicas pobladas (no None) -> el market_state podra clasificar regimen.
    assert snap["symbols"]["SPY"]["sma_50"] == 2.0
    assert snap["symbols"]["SPY"]["return_20d"] == 0.1
