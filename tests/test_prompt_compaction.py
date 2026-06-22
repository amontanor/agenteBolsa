"""Tests de reduccion de prompt y parseo tolerante de JSON del LLM.

Contexto: el crew de decision daba timeout (120s) porque el `technical_context`
iba al prompt con `analysis_plan_counts`, rupturas completas y campos nulos. Y el
LLM a veces devolvia JSON truncado ("Unterminated string"). Estos tests fijan el
comportamiento esperado de las correcciones.
"""
from __future__ import annotations

import json

from agente_bolsa.tools.trade_decision import (
    _compact_technical_context_for_prompt,
    _extract_json_object,
    _repair_truncated_json,
    _strip_empty_for_prompt,
)


def test_strip_empty_keeps_false_and_zero():
    data = {"a": None, "b": "", "c": {}, "d": [], "keep_false": False, "keep_zero": 0, "n": 1}
    out = _strip_empty_for_prompt(data)
    assert out == {"keep_false": False, "keep_zero": 0, "n": 1}


def _raw_context():
    return {
        "source": "intraday_technical_scan",
        "run_id": "mkt_x",
        "as_of": None,
        "selected_candidates": [
            {
                "symbol": "AAA", "direction": "long", "score": 16,
                "setup_name": "confirmed_pattern",
                "technical_state": {"close": None, "return_20d": None, "rsi_14": None},
                "risk_plan": {"entry_price": 10.0, "stop_loss": 9.0, "take_profit": 12.0},
            }
        ],
        "top_longs": [],
        "top_shorts": [],
        "analysis_plan_counts": {f"k{i}": i for i in range(25)},
        "breakout_confirmed": [
            {"symbol": "BBB", "status": "confirmed_breakout", "tradable": False,
             "close": 100.0, "reward_risk": 2.0, "high": 101, "low": 99, "volume": 1,
             "resistance": 99.5, "atr_14": 3, "rsi_14": 60, "reasons": ["x", "y", "z"]}
        ],
        "breakout_watch": [],
    }


def test_compact_drops_analysis_plan_counts_and_nulls():
    raw = _raw_context()
    out = _compact_technical_context_for_prompt(raw)
    # analysis_plan_counts se omite por completo
    assert "analysis_plan_counts" not in out
    # rupturas reducidas a campos esenciales
    bo = out["breakout_confirmed"][0]
    assert set(bo).issubset({"symbol", "status", "tradable", "close", "reward_risk"})
    assert "volume" not in bo and "reasons" not in bo
    # campos nulos del technical_state eliminados
    ts = out["selected_candidates"][0].get("technical_state", {})
    assert "close" not in ts  # era None
    # el resultado serializado es bastante mas pequeno que el crudo
    assert len(json.dumps(out)) < len(json.dumps(raw))


def test_extract_json_plain_and_fenced():
    assert _extract_json_object('{"a": 1}') == {"a": 1}
    assert _extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_recovers_truncated_string():
    # Respuesta cortada a media cadena (caso "Unterminated string").
    truncated = '{"action": "buy", "reason": "momentum muy fuerte'
    out = _extract_json_object(truncated)
    assert out["action"] == "buy"
    assert out["reason"].startswith("momentum")


def test_repair_returns_none_on_unrecoverable():
    assert _repair_truncated_json('{"k":') is None
