import json

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.research_evidence import (
    build_research_evidence_report,
    load_research_evidence_context,
    research_block_reason,
)


def _setup(tmp_path):
    settings = Settings(DATA_DIR=tmp_path, RESEARCH_EVIDENCE_FAIL_CLOSED_FOR_BUYS=True)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return settings, store


def test_build_research_report_persists_rows_and_latest_file(tmp_path, monkeypatch):
    settings, store = _setup(tmp_path)
    store.upsert_market_thesis(
        {
            "thesis_date": "2026-06-15",
            "payload": {"stance": "neutral", "key_risks": ["macro"]},
            "stance": "neutral",
            "confidence": 0.6,
        }
    )
    monkeypatch.setattr(
        "agente_bolsa.tools.research_evidence.fetch_macro_events",
        lambda _settings: {"economic_calendar": [], "earnings_calendar": [], "general_news": [], "quality": "ok"},
    )
    monkeypatch.setattr(
        "agente_bolsa.tools.research_evidence.fetch_symbol_news",
        lambda symbol, max_items=5: [
            {
                "title": f"{symbol} rallies on demand",
                "publisher": "Reuters",
                "published_at": "2026-06-15T10:00:00+00:00",
                "summary": "Demand remains strong",
                "link": "https://example.com/news",
            }
        ],
    )

    report = build_research_evidence_report(
        store,
        settings,
        tmp_path / "reports",
        "run_1",
        symbols=["AAPL"],
        sentiment_context={},
        market_state={},
    )

    assert report["summary"]["decision_ready"] is True
    rows = store.research_evidence(limit=10)
    assert any(item["symbol"] == "AAPL" for item in rows)
    latest = load_research_evidence_context(tmp_path)
    assert latest["summary"]["symbols_with_fresh_evidence"] == 1


def test_research_block_reason_uses_symbol_specific_failures(tmp_path, monkeypatch):
    settings, store = _setup(tmp_path)
    monkeypatch.setattr(
        "agente_bolsa.tools.research_evidence.fetch_macro_events",
        lambda _settings: {"economic_calendar": [], "earnings_calendar": [], "general_news": [], "quality": "ok"},
    )
    monkeypatch.setattr(
        "agente_bolsa.tools.research_evidence.fetch_symbol_news",
        lambda symbol, max_items=5: [],
    )

    report = build_research_evidence_report(
        store,
        settings,
        tmp_path / "reports",
        "run_2",
        symbols=["AAPL"],
        sentiment_context={},
        market_state={},
    )

    assert report["summary"]["decision_ready"] is False
    assert research_block_reason(report, symbol="AAPL") == "research_evidence_missing_or_stale"
