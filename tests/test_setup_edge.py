"""Tests del sesgo y carga de edge por setup."""
from __future__ import annotations

import json
import sqlite3

from agente_bolsa.tools.setup_edge import (
    compute_setup_edge_table_from_connection,
    setup_edge_bias,
    setup_quality_key,
)


def test_key_confirmed_pattern():
    feats = {"chart_patterns": {"bullish_confirmed_count": 2}, "setup_quality": "strong"}
    assert setup_quality_key(feats) == "confirmed_pattern|strong"


def test_key_sin_patron():
    feats = {"chart_patterns": {"bullish_confirmed_count": 0}, "setup_quality": "mixed"}
    assert setup_quality_key(feats) == "sin_patron|mixed"


def test_key_uses_explicit_setup_name_when_present():
    assert setup_quality_key({"setup_name": "orderly_breakout"}) == "orderly_breakout"


def test_key_handles_empty():
    assert setup_quality_key(None) == "sin_patron|n/d"
    assert setup_quality_key({}) == "sin_patron|n/d"


def test_bias_sign_matches_edge():
    table = {"sin_patron|strong": 0.0035, "confirmed_pattern|strong": -0.0023}
    assert setup_edge_bias("sin_patron|strong", table) > 0
    assert setup_edge_bias("confirmed_pattern|strong", table) < 0


def test_bias_neutral_without_data():
    assert setup_edge_bias("sin_patron|strong", None) == 0.0
    assert setup_edge_bias("desconocido", {"otra": 0.01}) == 0.0


def test_bias_is_capped():
    assert setup_edge_bias("k", {"k": 999.0}, cap=15.0) == 15.0
    assert setup_edge_bias("k", {"k": -999.0}, cap=15.0) == -15.0


def test_compute_setup_edge_table_from_in_memory_sqlite():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE signal_outcomes (
            signal_id TEXT PRIMARY KEY,
            signal_date TEXT NOT NULL,
            features_json TEXT NOT NULL,
            outcome_json TEXT NOT NULL
        )
        """
    )
    rows = [
        (
            "a",
            "2026-06-10",
            {"setup_quality": "strong", "chart_patterns": {"bullish_confirmed_count": 0}},
            {"return_5d": 0.03},
        ),
        (
            "b",
            "2026-06-12",
            {"setup_quality": "strong", "chart_patterns": {"bullish_confirmed_count": 0}},
            {"return_5d": 0.01},
        ),
        (
            "c",
            "2026-06-11",
            {"setup_quality": "strong", "chart_patterns": {"bullish_confirmed_count": 2}},
            {"return_5d": -0.02},
        ),
        (
            "old",
            "2026-05-01",
            {"setup_quality": "strong", "chart_patterns": {"bullish_confirmed_count": 0}},
            {"return_5d": 0.99},
        ),
        (
            "immature",
            "2026-06-13",
            {"setup_quality": "strong", "chart_patterns": {"bullish_confirmed_count": 2}},
            {},
        ),
    ]
    connection.executemany(
        "INSERT INTO signal_outcomes(signal_id, signal_date, features_json, outcome_json) VALUES (?, ?, ?, ?)",
        [(signal_id, signal_date, json.dumps(features), json.dumps(outcome)) for signal_id, signal_date, features, outcome in rows],
    )

    edge_table = compute_setup_edge_table_from_connection(
        connection,
        as_of="2026-06-20",
        train_window_days=20,
        min_samples=1,
    )

    assert edge_table["sin_patron|strong"] == 0.02
    assert edge_table["confirmed_pattern|strong"] == -0.02


def _twin_candidates():
    # Dos candidatos tecnicamente identicos; solo difieren en el setup.
    base_ts = {
        "close": 110.0, "return_20d": 0.12, "sma_20": 104.0, "sma_50": 98.0,
        "sma_200": 90.0, "volume_zscore_20": 0.8, "atr_14": 2.0,
        "trend_positive": True, "above_long_trend": True,
    }
    good = {"symbol": "GOOD", "technical_state": dict(base_ts),
            "setup_quality": "strong", "chart_patterns": {"bullish_confirmed_count": 0}}
    bad = {"symbol": "BAD", "technical_state": dict(base_ts),
           "setup_quality": "strong", "chart_patterns": {"bullish_confirmed_count": 2}}
    return good, bad


def test_prioritize_reorders_by_setup_edge():
    from agente_bolsa.tools.opportunity_ranker import prioritize_candidates

    good, bad = _twin_candidates()
    edge_table = {"sin_patron|strong": 0.0038, "confirmed_pattern|strong": -0.0020}
    out = prioritize_candidates([bad, good], edge_table=edge_table)
    # Con sesgo de edge, el setup ganador (sin_patron|strong) va primero pese a
    # ser tecnicamente identico al confirmed_pattern.
    assert [c["symbol"] for c in out] == ["GOOD", "BAD"]


def test_prioritize_without_edge_table_is_backward_compatible():
    from agente_bolsa.tools.opportunity_ranker import prioritize_candidates

    good, bad = _twin_candidates()
    out = prioritize_candidates([bad, good])
    # Sin tabla, no hay sesgo: el orden no depende del setup (scores iguales),
    # y no se anaden claves de sesgo.
    assert {c["symbol"] for c in out} == {"GOOD", "BAD"}
    assert "setup_edge_bias" not in out[0]
