from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from scripts.study_decision_token_cost import build_report, format_report


def _seed_db(path):
    con = sqlite3.connect(path)
    con.execute(
        """
        CREATE TABLE llm_usage (
            usage_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            model TEXT,
            request_count INTEGER NOT NULL,
            prompt_tokens INTEGER NOT NULL,
            completion_tokens INTEGER NOT NULL,
            total_tokens INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            role TEXT
        )
        """
    )
    con.execute(
        """
        CREATE TABLE order_plans (
            plan_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL
        )
        """
    )
    now = datetime.now(timezone.utc)
    rows = [
        ("u1", "trade_decision", 1, 30000, 2000, 32000, (now - timedelta(days=1)).isoformat(), "decision"),
        ("u2", "trade_decision", 1, 40000, 3000, 43000, (now - timedelta(days=1)).isoformat(), "decision"),
        ("u3", "news_sentiment", 1, 5000, 500, 5500, (now - timedelta(days=1)).isoformat(), "sentiment"),
        ("u4", "trade_decision", 1, 50000, 1000, 51000, (now - timedelta(days=30)).isoformat(), "decision"),
    ]
    for usage_id, source, req, prompt, completion, total, created, role in rows:
        con.execute(
            "INSERT INTO llm_usage VALUES (?, ?, NULL, ?, ?, ?, ?, '{}', ?, ?)",
            (usage_id, source, req, prompt, completion, total, created, role),
        )
    con.execute("INSERT INTO order_plans VALUES ('p1', ?)", ((now - timedelta(days=1)).isoformat(),))
    con.commit()
    con.close()


def test_build_report_filters_window_and_role(tmp_path):
    db = tmp_path / "test.sqlite3"
    _seed_db(db)
    report = build_report(db, days=14)
    totals = report["totals"]
    assert totals["calls"] == 2  # excluye sentiment y la llamada fuera de ventana
    assert totals["prompt"] == 70000
    assert totals["total"] == 75000
    assert report["order_plans_in_window"] == 1
    assert report["tokens_per_order_plan"] == 75000
    assert report["prompt_tokens_per_call"]["max"] == 40000


def test_format_report_renders_table(tmp_path):
    db = tmp_path / "test.sqlite3"
    _seed_db(db)
    report = build_report(db, days=14)
    text = format_report(report)
    assert "Coste de tokens del LLM de decision" in text
    assert "order_plans en ventana: 1" in text
    assert "| Dia | Llamadas |" in text


def test_empty_window_does_not_break(tmp_path):
    db = tmp_path / "empty.sqlite3"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE llm_usage (usage_id TEXT, source TEXT, model TEXT, request_count INTEGER, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, payload_json TEXT, created_at TEXT, role TEXT)")
    con.execute("CREATE TABLE order_plans (plan_id TEXT, created_at TEXT)")
    con.commit()
    con.close()
    report = build_report(db, days=7)
    assert report["totals"]["calls"] == 0
    assert report["tokens_per_order_plan"] is None
    assert "n/d" in format_report(report)
