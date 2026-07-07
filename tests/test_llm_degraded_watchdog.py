"""Tests del watchdog de modo degradado del LLM."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from agente_bolsa.tools.llm_degraded_watchdog import evaluate, format_status_line

NOW = datetime(2026, 6, 16, 12, 0, 0, tzinfo=timezone.utc)


def _make_db(path, decision_ages_h=None, sentiment_ages_h=None, recs=None):
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE llm_usage (source TEXT, created_at TEXT)")
    con.execute("CREATE TABLE trade_recommendations (payload_json TEXT, created_at TEXT)")
    for h in decision_ages_h or []:
        ts = (NOW - timedelta(hours=h)).isoformat()
        con.execute("INSERT INTO llm_usage (source, created_at) VALUES ('trade_decision', ?)", (ts,))
    for h in sentiment_ages_h or []:
        ts = (NOW - timedelta(hours=h)).isoformat()
        con.execute("INSERT INTO llm_usage (source, created_at) VALUES ('news_sentiment', ?)", (ts,))
    for payload, h in recs or []:
        ts = (NOW - timedelta(hours=h)).isoformat()
        con.execute("INSERT INTO trade_recommendations (payload_json, created_at) VALUES (?, ?)", (payload, ts))
    con.commit()
    con.close()


def test_healthy_when_recent_llm(tmp_path):
    db = tmp_path / "s.sqlite3"
    _make_db(db, decision_ages_h=[1.0], sentiment_ages_h=[2.0],
             recs=[('{"source":"llm_committee"}', 1)])
    res = evaluate(db, now=NOW)
    assert res["degraded"] is False
    assert res["severity"] == "ok"


def test_degraded_when_no_decision_calls(tmp_path):
    db = tmp_path / "s.sqlite3"
    _make_db(db, decision_ages_h=[], sentiment_ages_h=[1.0])
    res = evaluate(db, now=NOW)
    assert res["degraded"] is True
    assert res["hours_since_decision_llm"] is None
    assert any("decision" in r for r in res["reasons"])


def test_critical_when_stale_and_heavy_fallback(tmp_path):
    db = tmp_path / "s.sqlite3"
    recs = [('{"source":"deterministic_fallback"}', 1) for _ in range(5)]
    _make_db(db, decision_ages_h=[240.0], sentiment_ages_h=[240.0], recs=recs)
    res = evaluate(db, now=NOW)
    assert res["degraded"] is True
    assert res["severity"] == "critical"
    assert res["recent_recommendations"]["ratio"] == 1.0


def test_recent_decision_overrides_fallback_noise(tmp_path):
    db = tmp_path / "s.sqlite3"
    recs = [('{"source":"deterministic_fallback"}', 1) for _ in range(5)]
    # LLM de decision reciente: aunque haya fallback en recomendaciones, no esta degradado.
    _make_db(db, decision_ages_h=[2.0], sentiment_ages_h=[2.0], recs=recs)
    res = evaluate(db, now=NOW)
    assert res["degraded"] is False


def test_status_line_mentions_hours_without_real_response(tmp_path):
    db = tmp_path / "s.sqlite3"
    _make_db(db, decision_ages_h=[30.0], sentiment_ages_h=[5.0])

    res = evaluate(db, now=NOW)

    assert res["roles"]["decision"]["ok"] is False
    assert res["roles"]["sentiment"]["ok"] is True
    assert "decision=CAIDO" in res["status_line"]
    assert "30.0h sin respuesta real" in format_status_line(res)
